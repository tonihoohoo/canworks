#include "j1939_network.h"

#include <poll.h>

#include <algorithm>
#include <cerrno>
#include <cinttypes>
#include <cstdio>
#include <cstring>

#include "cJSON.h"
#include "j1939_signal.h"
#include "log.h"
#include "outputs_gate.h"

namespace canopen_plugin {

namespace {

std::string name_hex(uint64_t name) {
  char buf[24];
  std::snprintf(buf, sizeof(buf), "0x%016" PRIX64, name);
  return buf;
}

uint32_t pgn_of_request(const std::vector<uint8_t>& d) {
  uint32_t pgn = d[0] | uint32_t(d[1]) << 8 | uint32_t(d[2]) << 16;
  return j1939_pdu1(pgn) ? pgn & 0x3FF00 : pgn;
}

}  // namespace

// ---------------------------------------------------------------------------
// J1939Image

void J1939Image::build(const J1939Config& cfg) {
  cfg_ = &cfg;
  size_t n = 0;
  rx_slot_.clear();
  for (const auto& r : cfg.rx) {
    rx_slot_.push_back(n);
    n += 1 + 2 * r.signals.size();
  }
  claim_slot_ = n;
  n += 2;
  in_work_.assign(n, 0);
  in_work_[claim_slot_] = static_cast<uint8_t>(J1939ClaimState::NoBus);
  in_work_[claim_slot_ + 1] = kJ1939NullAddress;
  in_.resize(n);
  commit();
  size_t m = 0;
  tx_slot_.clear();
  for (const auto& t : cfg.tx) {
    tx_slot_.push_back(m);
    m += t.signals.size();
  }
  scan_slot_ = m;
  out_.resize(m + 1);
  scans_ = 0;
}

void J1939Image::commit() {
  std::memcpy(in_.back(), in_work_.data(), in_work_.size() * sizeof(uint64_t));
  in_.publish();
}

void J1939Image::copy_to_plc(const plugin_runtime_args_t& rt) {
  const uint64_t* snap = in_.latest();
  const J1939Config& c = *cfg_;
  for (size_t i = 0; i < c.rx.size(); ++i) {
    const J1939Rx& r = c.rx[i];
    const uint64_t* s = snap + rx_slot_[i];
    if (r.has_status_location) image_write_input(rt, r.status_location, s[0]);
    for (size_t k = 0; k < r.signals.size(); ++k) {
      image_write_input(rt, r.signals[k].location, s[1 + 2 * k]);
      if (r.signals[k].has_valid_location) image_write_input(rt, r.signals[k].valid_location, s[2 + 2 * k]);
    }
  }
  if (c.ecu.has_state_location) image_write_input(rt, c.ecu.state_location, snap[claim_slot_]);
  if (c.ecu.has_address_location) image_write_input(rt, c.ecu.address_location, snap[claim_slot_ + 1]);
}

void J1939Image::copy_from_plc(const plugin_runtime_args_t& rt) {
  uint64_t* back = out_.back();
  const J1939Config& c = *cfg_;
  for (size_t i = 0; i < c.tx.size(); ++i)
    for (size_t k = 0; k < c.tx[i].signals.size(); ++k)
      back[tx_slot_[i] + k] =
          c.tx[i].signals[k].has_location ? image_read_output(rt, c.tx[i].signals[k].location) : 0;
  back[scan_slot_] = ++scans_;
  out_.publish();
}

// ---------------------------------------------------------------------------
// J1939Engine

constexpr std::chrono::milliseconds J1939Engine::kReplyGap;  // C++14: odr-used
constexpr size_t J1939Engine::kRepliedMax;

J1939Engine::J1939Engine(const Config& cfg, J1939Image& image, J1939Socket& socket)
    : cfg_(cfg), j_(cfg.j1939), image_(image), socket_(socket), claimer_(cfg.j1939.ecu, *this) {
  for (const auto& r : j_.rx) {
    RxState st;
    for (const auto& s : r.signals) st.bits.push_back(j1939_signal_bits(s));
    st.active.assign(r.signals.size(), 1);
    st.sig_last.assign(r.signals.size(), clock::time_point{});
    st.sig_seen.assign(r.signals.size(), 0);
    rx_.push_back(st);
  }
  for (const auto& t : j_.tx) {
    TxState st;
    for (const auto& s : t.signals) st.bits.push_back(j1939_signal_bits(s));
    st.data.assign(t.length, 0xFF);
    st.next = st.data;
    if (t.pages != canworks_can::MuxPages::Program && t.layout.multiplexed() &&
        t.layout.page_count() <= canworks_can::kMuxMaxPages)
      st.pages = t.layout.pages();
    st.page_data.assign(st.pages.size(), st.data);
    st.page_sent_once.assign(st.pages.size(), 0);
    st.sw.assign(t.signals.size(), 0);
    st.act.assign(t.signals.size(), 1);
    tx_.push_back(st);
  }
  req_.resize(j_.requests.size());
}

std::vector<uint32_t> J1939Engine::receive_pgns() const {
  std::set<uint32_t> pgns = {kPgnRequest, kPgnAddressClaimed};
  for (const auto& r : j_.rx) pgns.insert(r.pgn);
  return std::vector<uint32_t>(pgns.begin(), pgns.end());
}

void J1939Engine::rebind(uint8_t address) {
  if (bound_ == address) return;
  int r = socket_.bind(claimer_.name(), address);
  if (r < 0) {
    log_error("J1939: cannot bind to address %u: %s", address,
              j1939_socket_problem(r, cfg_.adapter.interface).c_str());
    bound_ = 0xFF;
    return;
  }
  bound_ = address;
}

int J1939Engine::send(uint32_t pgn, uint8_t destination, uint8_t priority, const uint8_t* data, size_t len) {
  int r = socket_.send(pgn, destination, priority, data, len);
  // The kernel takes a claimed address into use 250 ms after it sees the claim
  // frame, which can be a little after our own 250 ms: such a send is retried.
  if (r == -EADDRNOTAVAIL && settling_) return r;
  if (r < 0) {
    ++send_errors_;
    auto now = clock::now();
    if (now - last_error_log_ >= std::chrono::seconds(5)) {
      log_warn("J1939: sending PGN %s failed: %s (%" PRIu64 " failed sends so far)", j1939_pgn_text(pgn).c_str(),
               strerror(-r), send_errors_);
      last_error_log_ = now;
    }
  }
  return r;
}

void J1939Engine::send_claim(uint8_t address) {
  rebind(address);
  uint64_t name = claimer_.name();
  uint8_t d[8];
  for (int k = 0; k < 8; ++k) d[k] = static_cast<uint8_t>(name >> (8 * k));
  send(kPgnAddressClaimed, kJ1939Global, 6, d, sizeof(d));
}

void J1939Engine::send_claim_request() {
  rebind(kJ1939NullAddress);
  const uint8_t d[3] = {uint8_t(kPgnAddressClaimed), uint8_t(kPgnAddressClaimed >> 8), 0};
  send(kPgnRequest, kJ1939Global, 6, d, sizeof(d));
}

bool J1939Engine::can_send(clock::time_point) const { return bus_ && claimer_.state() == J1939ClaimState::Claimed; }

void J1939Engine::bus_up(clock::time_point now) {
  bus_ = true;
  problem_.clear();
  session_start_ = now;
  was_claimed_ = false;
  bound_ = 0xFF;
  ecus_.clear();
  replied_.clear();
  for (auto& r : rx_) {
    r.seen = false;
    r.timed_out = false;
    r.sources.clear();
  }
  for (size_t i = 0; i < j_.rx.size(); ++i) image_.set_status(i, false);
  log_info("J1939: bus up on %s; claiming address %u", cfg_.adapter.interface.c_str(), j_.ecu.address);
  claimer_.start(now);
  image_.set_claim(claimer_.state(), claimer_.address());
  dirty_ = true;
}

void J1939Engine::bus_lost(const std::string& why) {
  if (bus_ || why != problem_) {
    if (bus_)
      log_error("J1939: %s; inputs hold their values, the address is claimed again when the bus is back",
                why.c_str());
    else
      log_error("J1939: %s; the network does not start, retrying", why.c_str());
  }
  bus_ = false;
  problem_ = why;
  claimer_.bus_lost();
  bound_ = 0xFF;
  for (size_t i = 0; i < j_.rx.size(); ++i) image_.set_status(i, false);
  image_.set_claim(J1939ClaimState::NoBus, kJ1939NullAddress);
  image_.commit();
  dirty_ = false;
}

void J1939Engine::on_message(const J1939Message& m, clock::time_point now) {
  if (!bus_) return;
  const uint8_t own = claimer_.claiming_address();
  if (m.pgn == kPgnAddressClaimed) {
    if (m.data.size() < 8) return;
    uint64_t name = 0;
    for (int k = 7; k >= 0; --k) name = name << 8 | m.data[k];
    if (name == claimer_.name()) return;  // our own claim
    if (m.source <= kJ1939MaxAddress) {
      ecus_[m.source].name = name;
      ecus_[m.source].last = now;
    }
    claimer_.on_claim(m.source, name, now);
    return;
  }
  // Our own messages come back on the receive socket.
  if (m.source == own && own != kJ1939NullAddress && (m.source_name == 0 || m.source_name == claimer_.name())) return;
  if (m.source <= kJ1939MaxAddress) {
    Ecu& e = ecus_[m.source];
    if (m.source_name) e.name = m.source_name;
    e.last = now;
  }
  if (m.pgn == kPgnRequest) {
    on_request(m, now);
    return;
  }
  for (size_t i = 0; i < j_.rx.size(); ++i) {
    const J1939Rx& r = j_.rx[i];
    if (r.pgn != m.pgn) continue;
    if (j1939_pdu1(r.pgn) && m.destination != kJ1939Global && m.destination != claimer_.address()) continue;
    if (r.has_source && m.source != r.source) continue;
    if (r.has_source_name && (!m.source_name || ((m.source_name ^ r.source_name) & r.source_name_mask))) continue;
    RxState& st = rx_[i];
    ++st.count;
    st.sources.insert(m.source);
    st.seen = true;
    st.last = now;
    if (st.timed_out) {
      st.timed_out = false;
      log_info("J1939: PGN %s arrives again", j1939_pgn_text(r.pgn).c_str());
    }
    image_.set_status(i, true);
    // A multiplexed message carries the switches and its page's signals; an
    // unknown page only the switches and the always-present signals.
    bool muxed = r.layout.multiplexed();
    bool unknown = false;
    if (muxed) {
      canworks_can::MuxLayout::Eval ev =
          r.layout.evaluate(m.data.data(), static_cast<unsigned>(m.data.size()), st.active.data());
      if (ev.short_frame) {
        for (size_t k = 0; k < r.signals.size(); ++k)
          if (!r.layout.always(k)) st.active[k] = 0;
      } else if (ev.unknown) {
        unknown = true;
        ++st.unknown_pages;
      }
    }
    for (size_t k = 0; k < r.signals.size(); ++k) {
      if (muxed && (!st.active[k] || (unknown && !r.layout.always(k) && !r.layout.is_switch(k)))) continue;
      uint64_t raw;
      if (!j1939_extract(m.data.data(), m.data.size(), st.bits[k], raw) || j1939_not_valid(r.signals[k], raw)) {
        image_.set_valid(i, k, false);
        continue;
      }
      image_.set_value(i, k, j1939_to_plc(r.signals[k], raw));
      image_.set_valid(i, k, true);
      st.sig_seen[k] = 1;
      st.sig_last[k] = now;
    }
    dirty_ = true;
  }
}

void J1939Engine::on_request(const J1939Message& m, clock::time_point now) {
  if (m.data.size() < 3) return;
  const uint32_t pgn = pgn_of_request(m.data);
  const bool to_us = claimer_.address() != kJ1939NullAddress && m.destination == claimer_.address();
  if (m.destination != kJ1939Global && !to_us &&
      !(pgn == kPgnAddressClaimed && m.destination == claimer_.claiming_address()))
    return;
  // Answers to the same PGN and requester at most every kReplyGap. Requests
  // for the claims from the null address (ECUs still claiming, possibly
  // several starting at once) are always answered.
  if (pgn == kPgnAddressClaimed) {
    if (m.source == kJ1939NullAddress || reply_allowed(pgn, m.source, now)) claimer_.on_claim_request(now);
    return;
  }
  if (!can_send(now)) return;
  for (size_t i = 0; i < j_.tx.size(); ++i) {
    if (j_.tx[i].pgn != pgn) continue;
    if (!outputs_enabled()) return;  // a transmit message, stopped with the outputs
    if (!reply_allowed(pgn, m.source, now)) return;
    const uint64_t* snap = image_.latest_outputs();
    uint8_t dest = j1939_pdu1(pgn) && m.source <= kJ1939MaxAddress ? m.source : kJ1939Global;
    send_all(i, dest, now, snap);
    ++tx_[i].answered;
    return;
  }
  if (!to_us || !reply_allowed(pgn, m.source, now)) return;
  // NACK (J1939-21 Acknowledgement, control byte 1) for a PGN we do not send.
  const uint8_t d[8] = {1, 0xFF, 0xFF, 0xFF, m.source, uint8_t(pgn), uint8_t(pgn >> 8), uint8_t(pgn >> 16)};
  send(kPgnAcknowledgement, kJ1939Global, 6, d, sizeof(d));
}

bool J1939Engine::reply_allowed(uint32_t pgn, uint8_t requester, clock::time_point now) {
  const uint32_t key = pgn << 8 | requester;
  auto it = replied_.find(key);
  if (it != replied_.end() && now - it->second < kReplyGap) return false;
  // Entries older than the gap limit nothing: drop them before the map grows.
  if (replied_.size() >= kRepliedMax) {
    for (auto e = replied_.begin(); e != replied_.end();) {
      if (now - e->second >= kReplyGap)
        e = replied_.erase(e);
      else
        ++e;
    }
  }
  if (replied_.size() >= kRepliedMax) return false;
  replied_[key] = now;
  return true;
}

bool J1939Engine::build_tx(size_t i, const uint64_t* snap, int page) {
  const J1939Tx& t = j_.tx[i];
  TxState& st = tx_[i];
  // Unused bits are sent as 1 (J1939-71); each signal is written over them.
  std::fill(st.next.begin(), st.next.end(), 0xFF);
  const uint8_t* active = nullptr;
  const uint64_t* switches = nullptr;
  bool unknown = false;
  if (page >= 0) {
    const auto& pg = st.pages[static_cast<size_t>(page)];
    active = pg.active.data();
    switches = pg.values.data();
  } else if (t.layout.multiplexed()) {
    for (size_t k = 0; k < t.signals.size(); ++k)
      st.sw[k] = t.signals[k].has_location ? j1939_from_plc(t.signals[k], snap[image_.tx_slot(i, k)]) : 0;
    unknown = t.layout.activity(st.sw.data(), st.act.data());
    st.unknown_page = unknown;
    active = st.act.data();
  }
  for (size_t k = 0; k < t.signals.size(); ++k) {
    if (active && !active[k]) continue;
    if (unknown && !t.layout.always(k) && !t.layout.is_switch(k)) continue;
    uint64_t v = t.signals[k].has_location ? j1939_from_plc(t.signals[k], snap[image_.tx_slot(i, k)])
                                           : (switches ? switches[k] : 0);
    j1939_insert(st.next.data(), st.next.size(), st.bits[k], v);
  }
  if (page >= 0) return !st.page_sent_once[static_cast<size_t>(page)] || st.next != st.page_data[static_cast<size_t>(page)];
  return !st.sent_once || st.next != st.data;
}

bool J1939Engine::send_tx(size_t i, uint8_t destination, clock::time_point now, int page) {
  const J1939Tx& t = j_.tx[i];
  TxState& st = tx_[i];
  int r = send(t.pgn, destination, static_cast<uint8_t>(t.priority), st.next.data(), st.next.size());
  if (r == -EADDRNOTAVAIL && settling_) return false;
  // A refused send does not count as sent: an on-change PGN stays changed and
  // is tried again on the next tick.
  if (r < 0) return true;
  ++st.sent;
  if (page >= 0) {
    st.page_data[static_cast<size_t>(page)] = st.next;
    st.page_sent_once[static_cast<size_t>(page)] = 1;
  } else {
    st.data = st.next;
  }
  st.sent_once = true;
  st.last_sent = now;
  return true;
}

bool J1939Engine::send_all(size_t i, uint8_t destination, clock::time_point now, const uint64_t* snap) {
  TxState& st = tx_[i];
  if (st.pages.empty()) {
    build_tx(i, snap);
    return send_tx(i, destination, now);
  }
  if (j_.tx[i].pages == canworks_can::MuxPages::Rotate) {
    int p = static_cast<int>(st.cursor);
    build_tx(i, snap, p);
    if (!send_tx(i, destination, now, p)) return false;
    st.cursor = (st.cursor + 1) % st.pages.size();
    return true;
  }
  for (size_t p = 0; p < st.pages.size(); ++p) {
    build_tx(i, snap, static_cast<int>(p));
    if (!send_tx(i, destination, now, static_cast<int>(p))) return false;
  }
  return true;
}

void J1939Engine::tick(clock::time_point now) {
  if (!bus_) return;
  claimer_.tick(now);
  // A claim seen on the bus changes the state too, so compare with what the PLC has.
  if (image_.claim_state() != static_cast<uint8_t>(claimer_.state()) ||
      image_.claim_address() != claimer_.address()) {
    image_.set_claim(claimer_.state(), claimer_.address());
    dirty_ = true;
  }
  const bool claimed = claimer_.state() == J1939ClaimState::Claimed;
  if (claimed && !was_claimed_) {
    claimed_at_ = now;
    for (auto& t : tx_) {
      t.next_due = now;
      t.sent_once = false;
      std::fill(t.page_sent_once.begin(), t.page_sent_once.end(), 0);
    }
    for (auto& q : req_) q.next_due = now;
  }
  was_claimed_ = claimed;
  settling_ = claimed && now - claimed_at_ < std::chrono::seconds(1);
  // Receive supervision: before the first message the session's start counts.
  for (size_t i = 0; i < j_.rx.size(); ++i) {
    const J1939Rx& r = j_.rx[i];
    RxState& st = rx_[i];
    // A signal's valid bit goes FALSE when no message carried it for the
    // timeout (a multiplexed signal's page stopped).
    for (size_t k = 0; r.timeout_ms && k < r.signals.size(); ++k) {
      if (!st.sig_seen[k] || now - st.sig_last[k] < std::chrono::milliseconds(r.timeout_ms)) continue;
      st.sig_seen[k] = 0;
      image_.set_valid(i, k, false);
      dirty_ = true;
    }
    if (!r.timeout_ms || st.timed_out) continue;
    clock::time_point since = st.seen ? st.last : session_start_;
    if (now - since < std::chrono::milliseconds(r.timeout_ms)) continue;
    st.timed_out = true;
    ++st.timeouts;
    image_.set_status(i, false);
    dirty_ = true;
    if (st.seen) log_warn("J1939: PGN %s timed out (nothing for %u ms)", j1939_pgn_text(r.pgn).c_str(), r.timeout_ms);
  }
  if (claimed) {
    const uint64_t* snap = image_.latest_outputs();
    // Nothing is sent from outputs the program has not written yet, nor while
    // the host's outputs gate is closed (the bridge's outputs off).
    const bool gate = outputs_enabled();
    if (gate && !gate_was_open_)
      for (auto& t : tx_) t.next_due = now;
    gate_was_open_ = gate;
    if (gate && image_.scan_count(snap) > 0) {
      for (size_t i = 0; i < j_.tx.size(); ++i) {
        const J1939Tx& t = j_.tx[i];
        TxState& st = tx_[i];
        uint8_t dest = t.has_destination ? static_cast<uint8_t>(t.destination) : kJ1939Global;
        if (!st.pages.empty() && !t.period_ms) {
          // On change, page by page: every changed page ("all"), or the
          // next changed page ("rotate").
          if (st.sent_once && now - st.last_sent < std::chrono::milliseconds(t.min_gap_ms)) continue;
          size_t n = st.pages.size();
          for (size_t s = 0; s < n; ++s) {
            size_t p = (t.pages == canworks_can::MuxPages::Rotate ? st.cursor + s : s) % n;
            if (!build_tx(i, snap, static_cast<int>(p))) continue;
            send_tx(i, dest, now, static_cast<int>(p));
            if (t.pages == canworks_can::MuxPages::Rotate) {
              st.cursor = (p + 1) % n;
              break;
            }
          }
          continue;
        }
        if (!st.pages.empty()) {
          if (now < st.next_due || !send_all(i, dest, now, snap)) continue;
          st.next_due += std::chrono::milliseconds(t.period_ms);
          if (st.next_due <= now) st.next_due = now + std::chrono::milliseconds(t.period_ms);
          continue;
        }
        bool changed = build_tx(i, snap);
        if (t.period_ms) {
          if (now < st.next_due || !send_tx(i, dest, now)) continue;
          st.next_due += std::chrono::milliseconds(t.period_ms);
          if (st.next_due <= now) st.next_due = now + std::chrono::milliseconds(t.period_ms);
        } else if (changed && (!st.sent_once || now - st.last_sent >= std::chrono::milliseconds(t.min_gap_ms))) {
          // On change: a change within min_gap_ms goes out when the gap has passed.
          send_tx(i, dest, now);
        }
      }
    }
    for (size_t i = 0; i < j_.requests.size(); ++i) {
      const J1939Request& q = j_.requests[i];
      RequestState& st = req_[i];
      if (now < st.next_due) continue;
      const uint8_t d[3] = {uint8_t(q.pgn), uint8_t(q.pgn >> 8), uint8_t(q.pgn >> 16)};
      int r = send(kPgnRequest, static_cast<uint8_t>(q.destination), 6, d, sizeof(d));
      if (r == -EADDRNOTAVAIL && settling_) continue;
      if (r == 0) ++st.sent;
      st.next_due += std::chrono::milliseconds(q.period_ms);
      if (st.next_due <= now) st.next_due = now + std::chrono::milliseconds(q.period_ms);
    }
  }
  if (dirty_) {
    image_.commit();
    dirty_ = false;
  }
}

cJSON* J1939Engine::status(clock::time_point now) const {
  auto age = [now](clock::time_point t) {
    return static_cast<double>(std::chrono::duration_cast<std::chrono::milliseconds>(now - t).count());
  };
  cJSON* j = cJSON_CreateObject();
  J1939ClaimState s = bus_ ? claimer_.state() : J1939ClaimState::NoBus;
  cJSON_AddNumberToObject(j, "state", static_cast<int>(s));
  cJSON_AddStringToObject(j, "state_name", j1939_claim_state_name(s));
  cJSON_AddNumberToObject(j, "address", bus_ ? claimer_.address() : kJ1939NullAddress);
  cJSON_AddStringToObject(j, "name", name_hex(claimer_.name()).c_str());
  if (!problem_.empty() && !bus_) cJSON_AddStringToObject(j, "error", problem_.c_str());
  cJSON* ecus = cJSON_AddArrayToObject(j, "ecus");
  for (const auto& it : ecus_) {
    cJSON* o = cJSON_CreateObject();
    cJSON_AddNumberToObject(o, "address", it.first);
    if (it.second.name)
      cJSON_AddStringToObject(o, "name", name_hex(it.second.name).c_str());
    else
      cJSON_AddNullToObject(o, "name");
    cJSON_AddNumberToObject(o, "age_ms", age(it.second.last));
    cJSON_AddItemToArray(ecus, o);
  }
  cJSON* rx = cJSON_AddArrayToObject(j, "rx");
  for (size_t i = 0; i < j_.rx.size(); ++i) {
    const J1939Rx& r = j_.rx[i];
    const RxState& st = rx_[i];
    cJSON* o = cJSON_CreateObject();
    cJSON_AddNumberToObject(o, "pgn", r.pgn);
    if (r.has_source) cJSON_AddNumberToObject(o, "source", r.source);
    if (r.has_source_name) {
      cJSON_AddStringToObject(o, "source_name", name_hex(r.source_name).c_str());
      cJSON_AddStringToObject(o, "source_name_mask", name_hex(r.source_name_mask).c_str());
    }
    cJSON* src = cJSON_AddArrayToObject(o, "sources");
    for (uint8_t a : st.sources) cJSON_AddItemToArray(src, cJSON_CreateNumber(a));
    if (st.seen)
      cJSON_AddNumberToObject(o, "age_ms", age(st.last));
    else
      cJSON_AddNullToObject(o, "age_ms");
    cJSON_AddBoolToObject(o, "timed_out", st.timed_out);
    cJSON_AddNumberToObject(o, "timeouts", static_cast<double>(st.timeouts));
    cJSON_AddNumberToObject(o, "count", static_cast<double>(st.count));
    if (r.layout.multiplexed()) cJSON_AddNumberToObject(o, "unknown_pages", static_cast<double>(st.unknown_pages));
    cJSON* sigs = cJSON_AddArrayToObject(o, "signals");
    for (size_t k = 0; k < r.signals.size(); ++k) {
      cJSON* g = cJSON_CreateObject();
      cJSON_AddStringToObject(g, "name", r.signals[k].name.c_str());
      uint64_t v = image_.value(i, k);
      // Signed values as signed numbers; JSON numbers hold 53 bits exactly.
      double d = r.signals[k].is_signed ? static_cast<double>(static_cast<int64_t>(v)) : static_cast<double>(v);
      cJSON_AddNumberToObject(g, "raw", d);
      cJSON_AddBoolToObject(g, "valid", image_.valid(i, k));
      cJSON_AddItemToArray(sigs, g);
    }
    cJSON_AddItemToArray(rx, o);
  }
  cJSON* tx = cJSON_AddArrayToObject(j, "tx");
  for (size_t i = 0; i < j_.tx.size(); ++i) {
    cJSON* o = cJSON_CreateObject();
    cJSON_AddNumberToObject(o, "pgn", j_.tx[i].pgn);
    cJSON_AddNumberToObject(o, "sent", static_cast<double>(tx_[i].sent));
    cJSON_AddNumberToObject(o, "requests_answered", static_cast<double>(tx_[i].answered));
    if (j_.tx[i].layout.multiplexed()) {
      cJSON_AddStringToObject(o, "pages", canworks_can::mux_pages_name(j_.tx[i].pages));
      if (tx_[i].unknown_page) cJSON_AddBoolToObject(o, "unknown_page", true);
    }
    cJSON_AddItemToArray(tx, o);
  }
  cJSON* rq = cJSON_AddArrayToObject(j, "requests");
  for (size_t i = 0; i < j_.requests.size(); ++i) {
    cJSON* o = cJSON_CreateObject();
    cJSON_AddNumberToObject(o, "pgn", j_.requests[i].pgn);
    cJSON_AddNumberToObject(o, "sent", static_cast<double>(req_[i].sent));
    cJSON_AddItemToArray(rq, o);
  }
  return j;
}

// ---------------------------------------------------------------------------
// J1939Network

J1939Network::J1939Network(const Config& cfg, DiagHub* hub, std::unique_ptr<J1939Socket> socket,
                           std::unique_ptr<CanAdapter> adapter, std::unique_ptr<LinkOps> link)
    : cfg_(cfg),
      hub_(hub),
      socket_(socket ? std::move(socket) : make_kernel_j1939_socket()),
      adapter_(adapter ? std::move(adapter) : make_adapter(cfg.adapter)),
      link_(link ? std::move(link) : make_netlink_ops()),
      engine_(cfg, image_, *socket_) {
  image_.build(cfg.j1939);
}

J1939Network::~J1939Network() { stop(); }

void J1939Network::start() {
  stop_ = false;
  thread_ = std::thread([this] { thread_main(); });
}

void J1939Network::stop() {
  {
    std::lock_guard<std::mutex> lock(mutex_);
    stop_ = true;
  }
  cv_.notify_all();
  if (thread_.joinable()) thread_.join();
}

bool J1939Network::wait_for(std::chrono::milliseconds d) {
  // In slices, so the diagnostics channel is answered while the bus is away.
  auto end = std::chrono::steady_clock::now() + d;
  while (!stop_) {
    serve_diag(std::chrono::steady_clock::now());
    auto now = std::chrono::steady_clock::now();
    if (now >= end) return true;
    std::unique_lock<std::mutex> lock(mutex_);
    cv_.wait_for(lock, std::min<std::chrono::steady_clock::duration>(end - now, std::chrono::milliseconds(50)),
                 [this] { return stop_.load(); });
  }
  return false;
}

void J1939Network::offline(const std::string& why) { engine_.bus_lost(why); }

void J1939Network::serve_diag(std::chrono::steady_clock::time_point now) {
  if (!hub_) return;
  std::vector<DiagRequest> reqs;
  hub_->take(reqs);
  for (auto& r : reqs) {
    if (r.op != "status") {
      hub_->answer(r.seq, diag_error(r.id, "network \"" + cfg_.network + "\" is a J1939 network; " + r.op +
                                               " needs a CANopen network"));
      continue;
    }
    cJSON* res = cJSON_CreateObject();
    cJSON_AddStringToObject(res, "version", hub_->version().c_str());
    cJSON_AddNumberToObject(res, "uptime_s", hub_->uptime_s());
    cJSON_AddStringToObject(res, "config_sha256", cfg_.file_sha256.c_str());
    cJSON_AddStringToObject(res, "network", cfg_.network.c_str());
    cJSON_AddStringToObject(res, "protocol", "j1939");
    diag_add_protocols(res);
    cJSON_AddBoolToObject(res, "session", engine_.problem().empty());
    cJSON* b = cJSON_AddObjectToObject(res, "bus");
    cJSON_AddStringToObject(b, "interface", cfg_.adapter.interface.c_str());
    cJSON_AddNumberToObject(b, "state", bus_state_);
    cJSON_AddNumberToObject(b, "tx_errors", link_info_.tx_errors);
    cJSON_AddNumberToObject(b, "rx_errors", link_info_.rx_errors);
    cJSON_AddNumberToObject(b, "bus_off_count", link_info_.bus_off);
    cJSON_AddItemToObject(res, "j1939", engine_.status(now));
    hub_->answer(r.seq, diag_ok(r.id, res));
  }
}

// The controller's state as the bus state byte (bus_monitor.h codes): 0 none,
// 1 error-active, 2 warning, 3 passive, 4 bus-off.
static uint8_t bus_code(int rc, const LinkInfo& info) {
  if (rc < 0 || !info.up) return 0;
  if (!info.has_can_state) return 1;  // vcan
  switch (info.can_state) {
    case 0: return 1;
    case 1: return 2;
    case 2: return 3;
    case 3: return 4;
    default: return 0;
  }
}

void J1939Network::thread_main() {
  ScopedLogPrefix prefix(cfg_.log_prefix.empty() ? "" : cfg_.log_prefix + ": ");
  if (hub_) hub_->attach();
  while (!stop_) {
    AdapterState st = adapter_->prepare();
    if (st != AdapterState::Ready) {
      bus_state_ = 0;
      offline(adapter_->problem());
      if (!wait_for(std::chrono::milliseconds(1000))) break;
      continue;
    }
    int r = socket_->open(cfg_.adapter.interface, engine_.receive_pgns());
    if (r < 0) {
      offline(j1939_socket_problem(r, cfg_.adapter.interface));
      // A missing kernel module stays missing until someone loads it.
      if (!wait_for(std::chrono::milliseconds(r == -EPROTONOSUPPORT ? 5000 : 1000))) break;
      continue;
    }
    run_session();
    socket_->close();
    if (!stop_ && !wait_for(std::chrono::milliseconds(1000))) break;
  }
  socket_->close();
  adapter_->release();
  if (hub_) hub_->detach();
}

void J1939Network::run_session() {
  using clock = std::chrono::steady_clock;
  const std::string& ifname = cfg_.adapter.interface;
  auto now = clock::now();
  link_info_ = LinkInfo();
  int lr = link_->get(ifname, link_info_);
  bus_state_ = bus_code(lr, link_info_);
  if (bus_state_ == 0 || bus_state_ == 4) {
    offline(lr < 0 ? "CAN interface " + ifname + " not found"
                   : bus_state_ == 4 ? "CAN interface " + ifname + " is bus-off" : "CAN interface " + ifname + " is down");
    return;
  }
  engine_.bus_up(now);
  auto next_link = now + std::chrono::milliseconds(100);
  J1939Message m;
  while (!stop_) {
    pollfd p = {socket_->fd(), POLLIN, 0};
    int pr = poll(&p, 1, 1);
    now = clock::now();
    if (pr < 0 && errno != EINTR) {
      offline(std::string("poll: ") + strerror(errno));
      return;
    }
    for (int k = 0; k < 256; ++k) {
      int rr = socket_->receive(m);
      if (rr == -EAGAIN) break;
      if (rr < 0) {
        offline(j1939_socket_problem(rr, ifname));
        return;
      }
      engine_.on_message(m, now);
    }
    if (now >= next_link) {
      next_link = now + std::chrono::milliseconds(100);
      lr = link_->get(ifname, link_info_);
      bus_state_ = bus_code(lr, link_info_);
      if (bus_state_ == 0 || bus_state_ == 4) {
        offline(lr < 0 ? "CAN interface " + ifname + " is gone"
                       : bus_state_ == 4 ? "CAN interface " + ifname + " is bus-off"
                                         : "CAN interface " + ifname + " is down");
        return;
      }
    }
    engine_.tick(now);
    serve_diag(now);
  }
}

}  // namespace canopen_plugin
