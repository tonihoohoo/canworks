// engine.cpp - see engine.h.

#include "engine.h"

#include <algorithm>
#include <cstring>

#include "../signals.h"

namespace canworks_raw {

namespace {
uint64_t le64(const uint8_t* d) {
  uint64_t v = 0;
  for (unsigned i = 0; i < 8; ++i) v |= static_cast<uint64_t>(d[i]) << (8 * i);
  return v;
}
// Signed signals go to the PLC sign-extended to the location's width, so an
// INT location reads -1 for a 12-bit all-ones value.
uint64_t to_location(uint64_t raw, const RawSignal& s) {
  if (!s.is_signed) return raw;
  return static_cast<uint64_t>(canworks_can::sign_extend(raw, s.length));
}
}  // namespace

RawEngine::RawEngine(const RawConfig& cfg) : cfg_(cfg) {
  size_t widest = 0;
  for (const RawRx& m : cfg_.rx) {
    RxMap map;
    if (m.status.set) map.status = add_in(m.status.loc);
    if (m.counter.set) map.counter = add_in(m.counter.loc);
    if (m.id_loc.set) map.id = add_in(m.id_loc.loc);
    if (m.dlc_loc.set) map.dlc = add_in(m.dlc_loc.loc);
    if (m.data.set) map.data = add_in(m.data.loc);
    for (const RawSignal& s : m.signals) {
      map.signals.push_back(add_in(s.loc));
      map.valid.push_back(s.valid.set ? add_in(s.valid.loc) : -1);
    }
    rx_map_.push_back(map);
    rx_sig_.emplace_back(m.signals.size());
    rx_active_.emplace_back(m.signals.size(), 1);
  }
  for (const RawTx& m : cfg_.tx) {
    TxMap map;
    if (m.trigger.set) map.trigger = add_out(m.trigger.loc);
    if (m.enable.set) map.enable = add_out(m.enable.loc);
    if (m.data.set) {
      map.data = add_out(m.data.loc);
      map.all.push_back(map.data);
    }
    std::vector<int> all_index(m.signals.size(), -1);  // signal -> index into `all`
    for (size_t k = 0; k < m.signals.size(); ++k) {
      const RawSignal& s = m.signals[k];
      if (!s.has_loc) {
        map.signals.push_back(-1);
        continue;
      }
      map.signals.push_back(add_out(s.loc));
      all_index[k] = static_cast<int>(map.all.size());
      map.all.push_back(map.signals.back());
    }
    std::vector<canworks_can::MuxLayout::Page> pages;
    if (m.pages != canworks_can::MuxPages::Program && m.layout.multiplexed() &&
        m.layout.page_count() <= canworks_can::kMuxMaxPages)
      pages = m.layout.pages();
    for (const auto& pg : pages) {
      std::vector<size_t> sends;
      if (map.data >= 0) sends.push_back(0);
      for (size_t k = 0; k < m.signals.size(); ++k)
        if (pg.active[k] && all_index[k] >= 0) sends.push_back(static_cast<size_t>(all_index[k]));
      map.page_all.push_back(sends);
    }
    tx_pages_.push_back(pages);
    tx_map_.push_back(map);
    widest = std::max(widest, m.signals.size());
  }
  sw_values_.assign(widest, 0);
  sw_active_.assign(widest, 0);
  in_vals_.assign(in_locs_.size(), 0);
  out_vals_.assign(out_locs_.size(), 0);
  rx_.assign(cfg_.rx.size(), RxStatus{});
  tx_.assign(cfg_.tx.size(), TxState{});
  for (size_t i = 0; i < tx_.size(); ++i) reset_tx(i, 0);
  tx_st_.assign(cfg_.tx.size(), TxStatus{});
}

int RawEngine::add_in(const IecLocation& l) {
  in_locs_.push_back(l);
  return static_cast<int>(in_locs_.size() - 1);
}

int RawEngine::add_out(const IecLocation& l) {
  out_locs_.push_back(l);
  return static_cast<int>(out_locs_.size() - 1);
}

void RawEngine::reset_tx(size_t i, uint64_t now_us) {
  TxState& t = tx_[i];
  t = TxState{};
  t.next_periodic = now_us;
  size_t n = tx_pages_[i].size();
  t.page_sent.assign(n, {});
  t.page_has_sent.assign(n, 0);
  t.page_pending.assign(n, 0);
  t.page_retry.assign(n, 0);
}

bool RawEngine::on_frame(const canworks_can_frame& f, uint64_t now_us) {
  bool ext = (f.flags & CANWORKS_CAN_EXTENDED) != 0;
  bool rtr = (f.flags & CANWORKS_CAN_RTR) != 0;
  bool changed = false;
  for (size_t i = 0; i < cfg_.rx.size(); ++i) {
    const RawRx& m = cfg_.rx[i];
    if (m.extended != ext || m.rtr != rtr) continue;
    if ((f.id & m.mask) != (m.id & m.mask)) continue;
    RxStatus& st = rx_[i];
    if (!rtr && f.dlc < m.need) {
      ++st.short_frames;
      continue;
    }
    uint8_t data[8] = {};
    if (!rtr) std::memcpy(data, f.data, f.dlc > 8 ? 8 : f.dlc);
    // A multiplexed frame carries the switches and its page's signals.
    uint8_t* active = rx_active_[i].data();
    bool unknown = false;
    if (m.layout.multiplexed() && !rtr) {
      canworks_can::MuxLayout::Eval ev = m.layout.evaluate(data, f.dlc, active);
      if (ev.short_frame || f.dlc < ev.need) {
        ++st.short_frames;
        continue;
      }
      if (ev.unknown) {
        unknown = true;
        ++st.unknown_pages;
      }
    }
    const RxMap& map = rx_map_[i];
    auto put = [&](int slot, uint64_t v) {
      if (slot < 0) return;
      if (in_vals_[slot] != v) changed = true;
      in_vals_[slot] = v;
    };
    ++st.count;
    st.seen = true;
    st.timed_out = false;
    st.last_us = now_us;
    st.last = f;
    put(map.status, 1);
    put(map.counter, st.count & 0xFFFFu);
    put(map.id, f.id);
    put(map.dlc, f.dlc);
    put(map.data, le64(data));
    bool muxed = m.layout.multiplexed() && !rtr;
    for (size_t k = 0; k < m.signals.size(); ++k) {
      if (muxed && !active[k]) continue;
      // An unknown page writes the always-present signals and the switches.
      if (unknown && !m.layout.always(k) && !m.layout.is_switch(k)) continue;
      const RawSignal& s = m.signals[k];
      uint64_t raw = canworks_can::unpack_signal(data, f.dlc, s.start_bit, s.length, s.big_endian);
      put(map.signals[k], to_location(raw, s));
      SigState& ss = rx_sig_[i][k];
      ss.seen = true;
      ss.timed_out = false;
      ss.last_us = now_us;
      put(map.valid[k], 1);
    }
  }
  return changed;
}

bool RawEngine::check_timeouts(uint64_t now_us) {
  bool changed = false;
  for (size_t i = 0; i < cfg_.rx.size(); ++i) {
    const RawRx& m = cfg_.rx[i];
    if (!m.timeout_ms) continue;
    uint64_t limit = static_cast<uint64_t>(m.timeout_ms) * 1000u;
    RxStatus& st = rx_[i];
    if (st.seen && !st.timed_out && now_us - st.last_us >= limit) {
      st.timed_out = true;
      int slot = rx_map_[i].status;
      if (slot >= 0 && in_vals_[slot] != 0) {
        in_vals_[slot] = 0;
        changed = true;
      }
    }
    for (size_t k = 0; k < m.signals.size(); ++k) {
      SigState& ss = rx_sig_[i][k];
      int slot = rx_map_[i].valid[k];
      if (slot < 0 || !ss.seen || ss.timed_out || now_us - ss.last_us < limit) continue;
      ss.timed_out = true;
      if (in_vals_[slot] != 0) {
        in_vals_[slot] = 0;
        changed = true;
      }
    }
  }
  return changed;
}

bool RawEngine::enabled(size_t i) const {
  int slot = tx_map_[i].enable;
  return slot < 0 || out_vals_[slot] != 0;
}

void RawEngine::set_plc_running(bool running, uint64_t now_us) {
  if (running == running_) return;
  running_ = running;
  for (size_t i = 0; i < tx_.size(); ++i) {
    reset_tx(i, now_us);
    TxState& t = tx_[i];
    if (running) {
      // A trigger already TRUE at start is not an edge.
      int slot = tx_map_[i].trigger;
      t.prev_trigger = slot >= 0 && have_outputs_ && out_vals_[slot] != 0;
    }
  }
}

void RawEngine::set_outputs(const uint64_t* values, uint64_t now_us) {
  (void)now_us;
  std::memcpy(out_vals_.data(), values, out_vals_.size() * sizeof(uint64_t));
  bool first = !have_outputs_;
  have_outputs_ = true;
  for (size_t i = 0; i < cfg_.tx.size(); ++i) {
    TxState& t = tx_[i];
    const TxMap& map = tx_map_[i];
    if (map.trigger >= 0) {
      bool now = out_vals_[map.trigger] != 0;
      if (now && !t.prev_trigger && !first && running_) t.trigger_pending = true;
      t.prev_trigger = now;
    }
    if (!cfg_.tx[i].on_change) continue;
    if (paged(i)) {
      // A page is pending when a value it sends changed since it was sent.
      for (size_t p = 0; p < map.page_all.size(); ++p) {
        if (!t.page_has_sent[p]) continue;
        for (size_t k : map.page_all[p])
          if (out_vals_[map.all[k]] != t.page_sent[p][k]) {
            t.page_pending[p] = 1;
            break;
          }
      }
    } else if (t.has_sent) {
      for (size_t k = 0; k < map.all.size(); ++k)
        if (out_vals_[map.all[k]] != t.sent_values[k]) {
          t.change_pending = true;
          break;
        }
    }
  }
}

canworks_can_frame RawEngine::build(size_t i, const uint64_t* values, size_t page) const {
  const RawTx& m = cfg_.tx[i];
  const TxMap& map = tx_map_[i];
  canworks_can_frame f{};
  f.id = m.id;
  f.flags = static_cast<uint8_t>((m.extended ? CANWORKS_CAN_EXTENDED : 0) | (m.rtr ? CANWORKS_CAN_RTR : 0));
  f.dlc = static_cast<uint8_t>(m.dlc);
  built_unknown_ = false;
  if (m.rtr) return f;
  std::memset(f.data, m.fill, sizeof f.data);
  if (map.data >= 0) {
    uint64_t v = values[map.data];
    for (unsigned b = 0; b < 8; ++b) f.data[b] = static_cast<uint8_t>(v >> (8 * b));
  }
  // Which signals the frame carries, and the switch values.
  const uint8_t* active = nullptr;
  const uint64_t* switches = nullptr;
  if (paged(i)) {
    const canworks_can::MuxLayout::Page& pg = tx_pages_[i][page < tx_pages_[i].size() ? page : 0];
    active = pg.active.data();
    switches = pg.values.data();
  } else if (m.layout.multiplexed()) {
    for (size_t k = 0; k < m.signals.size(); ++k)
      sw_values_[k] = map.signals[k] >= 0 ? values[map.signals[k]] : 0;
    built_unknown_ = m.layout.activity(sw_values_.data(), sw_active_.data());
    active = sw_active_.data();
  }
  for (size_t k = 0; k < m.signals.size(); ++k) {
    if (active && !active[k]) continue;
    if (built_unknown_ && !m.layout.always(k) && !m.layout.is_switch(k)) continue;
    const RawSignal& s = m.signals[k];
    uint64_t v = map.signals[k] >= 0 ? values[map.signals[k]] : (switches ? switches[k] : 0);
    canworks_can::pack_signal(f.data, s.start_bit, s.length, s.big_endian, v);
  }
  for (unsigned b = f.dlc; b < 8; ++b) f.data[b] = 0;
  return f;
}

void RawEngine::push(size_t i, int page, std::vector<canworks_can_frame>& frames, std::vector<size_t>& tx_index) {
  const TxMap& map = tx_map_[i];
  frames.push_back(build(i, out_vals_.data(), page < 0 ? 0 : static_cast<size_t>(page)));
  tx_index.push_back(i);
  if (page < 0) tx_st_[i].unknown_page = built_unknown_;
  std::vector<uint64_t> vals(map.all.size());
  for (size_t k = 0; k < map.all.size(); ++k) vals[k] = out_vals_[map.all[k]];
  tx_[i].inflight.emplace_back(page, std::move(vals));
}

void RawEngine::due_paged(size_t i, uint64_t now_us, std::vector<canworks_can_frame>& frames,
                          std::vector<size_t>& tx_index) {
  const RawTx& m = cfg_.tx[i];
  TxState& t = tx_[i];
  size_t n = tx_pages_[i].size();
  bool rotate = m.pages == canworks_can::MuxPages::Rotate;
  std::vector<uint8_t> send(n, 0);
  auto next = [&]() {
    send[t.cursor % n] = 1;
    t.cursor = (t.cursor + 1) % n;
  };
  auto every = [&]() { std::fill(send.begin(), send.end(), 1); };
  // Failed change and trigger sends go again first.
  for (size_t p = 0; p < n; ++p)
    if (t.page_retry[p]) send[p] = 1;
  if (t.trigger_pending) {
    t.trigger_pending = false;
    rotate ? next() : every();
  }
  if (enabled(i)) {
    if (m.period_ms && now_us >= t.next_periodic) {
      t.next_periodic = now_us + static_cast<uint64_t>(m.period_ms) * 1000u;
      rotate ? next() : every();
    }
    if (m.on_change && !t.has_sent && !m.period_ms && !m.trigger.set) every();  // first values
    if (m.on_change && now_us - t.last_sent >= static_cast<uint64_t>(m.min_gap_ms) * 1000u) {
      if (rotate) {
        for (size_t s = 0; s < n; ++s) {
          size_t p = (t.cursor + s) % n;
          if (t.page_pending[p]) {
            send[p] = 1;
            t.cursor = (p + 1) % n;
            break;
          }
        }
      } else {
        for (size_t p = 0; p < n; ++p)
          if (t.page_pending[p]) send[p] = 1;
      }
    }
  } else {
    std::fill(t.page_pending.begin(), t.page_pending.end(), 0);
  }
  for (size_t p = 0; p < n; ++p)
    if (send[p]) {
      t.page_retry[p] = 0;
      t.page_pending[p] = 0;
      push(i, static_cast<int>(p), frames, tx_index);
    }
}

void RawEngine::due(uint64_t now_us, std::vector<canworks_can_frame>& frames, std::vector<size_t>& tx_index) {
  if (!running_ || !have_outputs_) return;
  for (size_t i = 0; i < cfg_.tx.size(); ++i) {
    if (paged(i)) {
      due_paged(i, now_us, frames, tx_index);
      continue;
    }
    const RawTx& m = cfg_.tx[i];
    TxState& t = tx_[i];
    bool send = false;
    if (t.trigger_pending) send = true;
    if (enabled(i)) {
      if (m.period_ms && now_us >= t.next_periodic) send = true;
      if (m.on_change && !t.has_sent && !m.period_ms && !m.trigger.set) send = true;  // first value
      if (t.change_pending && now_us - t.last_sent >= static_cast<uint64_t>(m.min_gap_ms) * 1000u) send = true;
    } else {
      t.change_pending = false;
    }
    if (!send) continue;
    // Nothing counts as sent until sent() reports the write.
    push(i, -1, frames, tx_index);
  }
}

void RawEngine::sent(size_t i, uint64_t now_us, int error) {
  if (i >= tx_st_.size()) return;
  const RawTx& m = cfg_.tx[i];
  TxState& t = tx_[i];
  int page = -1;
  std::vector<uint64_t> vals;
  if (!t.inflight.empty()) {
    page = t.inflight.front().first;
    vals.swap(t.inflight.front().second);
    t.inflight.pop_front();
  }
  if (error) {
    tx_st_[i].last_error = error;
    if (page >= 0) {
      // A page of an entry sent on change or by a trigger stays pending; a
      // periodic-only entry waits for its next period (no burst).
      if (m.on_change || m.trigger.set) t.page_retry[static_cast<size_t>(page)] = 1;
      return;
    }
    // On-change and trigger sends stay pending and are tried again on the
    // next tick; a periodic send waits for its next period (no burst).
    if (m.period_ms && now_us >= t.next_periodic)
      t.next_periodic = now_us + static_cast<uint64_t>(m.period_ms) * 1000u;
    return;
  }
  ++tx_st_[i].count;
  tx_st_[i].last_error = 0;
  t.last_sent = now_us;
  t.has_sent = true;
  if (page >= 0) {
    size_t p = static_cast<size_t>(page);
    t.page_sent[p].swap(vals);
    t.page_has_sent[p] = 1;
    return;
  }
  t.trigger_pending = false;
  t.change_pending = false;
  t.next_periodic = now_us + static_cast<uint64_t>(m.period_ms) * 1000u;
  t.sent_values.swap(vals);
}

uint64_t RawEngine::next_event_in(uint64_t now_us) const {
  uint64_t best = UINT64_MAX;
  auto take = [&](uint64_t at) {
    uint64_t in = at > now_us ? at - now_us : 0;
    if (in < best) best = in;
  };
  if (running_ && have_outputs_) {
    for (size_t i = 0; i < cfg_.tx.size(); ++i) {
      const RawTx& m = cfg_.tx[i];
      const TxState& t = tx_[i];
      if (t.trigger_pending) take(now_us);
      for (uint8_t r : t.page_retry)
        if (r) take(now_us);
      if (!enabled(i)) continue;
      if (m.period_ms) take(t.next_periodic);
      bool pending = t.change_pending;
      for (uint8_t p : t.page_pending) pending = pending || p;
      if (pending) take(t.last_sent + static_cast<uint64_t>(m.min_gap_ms) * 1000u);
    }
  }
  for (size_t i = 0; i < cfg_.rx.size(); ++i) {
    const RxStatus& st = rx_[i];
    if (!cfg_.rx[i].timeout_ms) continue;
    uint64_t limit = static_cast<uint64_t>(cfg_.rx[i].timeout_ms) * 1000u;
    if (st.seen && !st.timed_out) take(st.last_us + limit);
    for (size_t k = 0; k < rx_sig_[i].size(); ++k) {
      const SigState& ss = rx_sig_[i][k];
      if (rx_map_[i].valid[k] >= 0 && ss.seen && !ss.timed_out) take(ss.last_us + limit);
    }
  }
  return best;
}

}  // namespace canworks_raw
