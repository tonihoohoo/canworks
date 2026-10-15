// j1939_plc_msgs.cpp - the slots of the J1939 message blocks
// (j1939_plc_msgs.h).

#include "j1939_plc_msgs.h"

#include <algorithm>
#include <cstddef>
#include <cstring>

#include "j1939_config.h"

namespace canopen_plugin {

constexpr std::chrono::seconds J1939PlcMsgs::kKeepResult;
constexpr std::chrono::seconds J1939PlcMsgs::kGrace;
void (*J1939PlcMsgs::sync_gap_for_test)() = nullptr;

namespace {

constexpr uint32_t kIndexBits = 5;  // 32 message slots
static_assert((1u << kIndexBits) == CANWORKS_J1939_MSG_SLOTS, "handle layout");
constexpr uint32_t kRxIndexBits = 6;  // 64 receivers
constexpr uint32_t kSeqMask = (1u << 24) - 1;
constexpr uint32_t kMaxPgn = 0x3FFFF;

bool pdu1(uint32_t pgn) { return ((pgn >> 8) & 0xFF) < 240; }

// The PGN as the kernel reports it: a PDU1 PGN without its destination byte.
uint32_t normal_pgn(uint32_t pgn) { return pdu1(pgn) ? pgn & 0x3FF00 : pgn; }

}  // namespace

J1939PlcMsgs::J1939PlcMsgs() : slots_(new Slot[CANWORKS_J1939_MSG_SLOTS]) {}

J1939PlcMsgs& J1939PlcMsgs::instance() {
  static J1939PlcMsgs msgs;
  return msgs;
}

void J1939PlcMsgs::open(const std::vector<bool>& j1939_networks) {
  std::lock_guard<std::mutex> lock(mutex_);
  for (unsigned i = 0; i < CANWORKS_J1939_MSG_SLOTS; ++i) slots_[i].state = State::Free;
  for (auto& r : receivers_) {
    r.state = RxState::Free;
    r.cancelled = false;
  }
  for (unsigned n = 0; n < kMaxNetworks; ++n) {
    ecu_[n] = EcuView();
    ++filter_gen_[n];
  }
  uint32_t bits = 0;
  for (size_t i = 0; i < j1939_networks.size() && i < kMaxNetworks; ++i)
    if (j1939_networks[i]) bits |= 1u << i;
  j1939_.store(bits, std::memory_order_release);
  networks_.store(static_cast<uint32_t>(j1939_networks.size()), std::memory_order_release);
  running_.store(true, std::memory_order_release);
}

void J1939PlcMsgs::close() {
  std::lock_guard<std::mutex> lock(mutex_);
  running_.store(false, std::memory_order_release);
  for (unsigned i = 0; i < CANWORKS_J1939_MSG_SLOTS; ++i) slots_[i].state = State::Free;
  // A receiver's block learns of the stop on its next read.
  for (auto& r : receivers_)
    if (r.state != RxState::Free) r.cancelled = true;
  for (unsigned n = 0; n < kMaxNetworks; ++n) ++filter_gen_[n];
}

void J1939PlcMsgs::set_attached(unsigned network, bool attached) {
  if (network >= kMaxNetworks) return;
  if (attached)
    attached_.fetch_or(1u << network, std::memory_order_acq_rel);
  else
    attached_.fetch_and(~(1u << network), std::memory_order_acq_rel);
}

void J1939PlcMsgs::note_unknown_version(uint32_t v) {
  uint32_t expected = 0;
  unknown_version_.compare_exchange_strong(expected, v, std::memory_order_acq_rel);
}

uint32_t J1939PlcMsgs::take_unknown_version() { return unknown_version_.exchange(0, std::memory_order_acq_rel); }

uint16_t J1939PlcMsgs::check_network(uint8_t network) const {
  if (!running()) return CANWORKS_J1939_ERR_NOT_RUNNING;
  if (network >= networks_.load(std::memory_order_acquire) || network >= kMaxNetworks)
    return CANWORKS_J1939_ERR_NETWORK;
  if (!(j1939_.load(std::memory_order_acquire) >> network & 1u)) return CANWORKS_J1939_ERR_NOT_J1939;
  if (!(attached_.load(std::memory_order_acquire) >> network & 1u)) return CANWORKS_J1939_ERR_NOT_RUNNING;
  return 0;
}

uint32_t J1939PlcMsgs::send_start(uint8_t network, uint32_t pgn, uint8_t destination, uint8_t priority,
                                  const uint8_t* data, uint16_t length, uint32_t timeout_ms, uint16_t& error_id) {
  error_id = check_network(network);
  if (error_id) return 0;
  if (pgn > kMaxPgn || destination == kJ1939NullAddress || priority > 7 || length > CANWORKS_J1939_MAX_LENGTH ||
      (length && !data)) {
    error_id = CANWORKS_J1939_ERR_INPUT;
    return 0;
  }
  std::lock_guard<std::mutex> lock(mutex_);
  if (!running()) {
    error_id = CANWORKS_J1939_ERR_NOT_RUNNING;
    return 0;
  }
  for (uint32_t i = 0; i < CANWORKS_J1939_MSG_SLOTS; ++i) {
    Slot& s = slots_[i];
    if (s.state != State::Free) continue;
    s.seq = next_seq_;
    next_seq_ = (next_seq_ + 1) & kSeqMask;
    if (!next_seq_) next_seq_ = 1;
    s.order = next_order_++;
    s.network = network;
    s.kind = Kind::Send;
    s.pgn = normal_pgn(pgn);
    s.destination = pdu1(pgn) ? destination : kJ1939Global;
    s.priority = priority;
    s.length = length;
    s.timeout_ms = timeout_ms ? timeout_ms : (length > 8 ? 10000 : 1000);
    if (length) std::memcpy(s.msg.data, data, length);
    s.error_id = 0;
    s.started = clock::now();
    s.state = State::Queued;
    return (s.seq << kIndexBits) | i;
  }
  error_id = CANWORKS_J1939_ERR_FULL;
  return 0;
}

uint32_t J1939PlcMsgs::request_start(uint8_t network, uint32_t pgn, uint8_t destination, uint32_t timeout_ms,
                                     uint16_t& error_id) {
  error_id = check_network(network);
  if (error_id) return 0;
  if (pgn > kMaxPgn || destination == kJ1939NullAddress) {
    error_id = CANWORKS_J1939_ERR_INPUT;
    return 0;
  }
  std::lock_guard<std::mutex> lock(mutex_);
  if (!running()) {
    error_id = CANWORKS_J1939_ERR_NOT_RUNNING;
    return 0;
  }
  for (uint32_t i = 0; i < CANWORKS_J1939_MSG_SLOTS; ++i) {
    Slot& s = slots_[i];
    if (s.state != State::Free) continue;
    s.seq = next_seq_;
    next_seq_ = (next_seq_ + 1) & kSeqMask;
    if (!next_seq_) next_seq_ = 1;
    s.order = next_order_++;
    s.network = network;
    s.kind = Kind::Request;
    s.pgn = normal_pgn(pgn);
    s.destination = destination;
    s.priority = 6;
    s.length = 0;
    s.timeout_ms = timeout_ms ? timeout_ms : 1000;
    s.error_id = 0;
    s.started = clock::now();
    s.state = State::Queued;
    return (s.seq << kIndexBits) | i;
  }
  error_id = CANWORKS_J1939_ERR_FULL;
  return 0;
}

J1939PlcMsgs::Slot* J1939PlcMsgs::find(uint32_t handle) {
  if (!handle) return nullptr;
  Slot& s = slots_[handle & (CANWORKS_J1939_MSG_SLOTS - 1)];
  if (s.state == State::Free || s.seq != handle >> kIndexBits) return nullptr;
  return &s;
}

int J1939PlcMsgs::poll(uint32_t handle, Kind kind, canworks_j1939_msg* out, uint16_t& error_id,
                       clock::time_point now) {
  std::lock_guard<std::mutex> lock(mutex_);
  Slot* s = find(handle);
  if (!s || s->kind != kind) {
    error_id = CANWORKS_J1939_ERR_CANCELLED;
    return 2;
  }
  if ((s->state == State::Queued || s->state == State::Taken) &&
      now - s->started >= std::chrono::milliseconds(s->timeout_ms) + kGrace) {
    s->error_id = CANWORKS_J1939_ERR_TIMEOUT;
    s->state = State::Done;
  }
  if (s->state != State::Done) {
    error_id = 0;
    return 0;
  }
  error_id = s->error_id;
  if (out && kind == Kind::Request) {
    if (!s->error_id) {
      std::memcpy(out, &s->msg, offsetof(canworks_j1939_msg, data) + s->msg.length);
    } else {
      out->ack_code = s->msg.ack_code;
      out->length = 0;
    }
  }
  s->state = State::Free;
  return error_id ? 2 : 1;
}

void J1939PlcMsgs::cancel(uint32_t handle) {
  std::lock_guard<std::mutex> lock(mutex_);
  if (Slot* s = find(handle)) s->state = State::Free;
}

void J1939PlcMsgs::take(unsigned network, std::vector<Job>& out) {
  std::lock_guard<std::mutex> lock(mutex_);
  auto now = clock::now();
  std::vector<std::pair<uint64_t, uint32_t>> order;
  for (uint32_t i = 0; i < CANWORKS_J1939_MSG_SLOTS; ++i) {
    Slot& s = slots_[i];
    if (s.state == State::Done && now - s.done_at >= kKeepResult) s.state = State::Free;
    if (s.state != State::Queued || s.network != network) continue;
    s.state = State::Taken;
    order.emplace_back(s.order, i);
  }
  std::sort(order.begin(), order.end());
  for (const auto& o : order) {
    const Slot& s = slots_[o.second];
    Job j;
    j.handle = (s.seq << kIndexBits) | o.second;
    j.kind = s.kind;
    j.pgn = s.pgn;
    j.destination = s.destination;
    j.priority = s.priority;
    j.timeout_ms = s.timeout_ms;
    j.data.assign(s.msg.data, s.msg.data + s.length);
    out.push_back(std::move(j));
  }
}

void J1939PlcMsgs::finish(uint32_t handle, uint16_t error_id, const canworks_j1939_msg* answer) {
  std::lock_guard<std::mutex> lock(mutex_);
  Slot* s = find(handle);
  if (!s || s->state != State::Taken) return;
  s->error_id = error_id;
  s->msg.length = 0;
  s->msg.ack_code = 0;
  if (answer) {
    std::memcpy(&s->msg, answer, offsetof(canworks_j1939_msg, data) + std::min<size_t>(answer->length,
                                                                                         CANWORKS_J1939_MAX_LENGTH));
  }
  s->done_at = clock::now();
  s->state = State::Done;
}

// ---- Receivers ----

J1939PlcMsgs::Receiver* J1939PlcMsgs::find_rx(uint32_t handle) {
  if (!handle) return nullptr;
  Receiver& r = receivers_[handle & (kReceiverSlots - 1)];
  if (r.state == RxState::Free || r.seq != handle >> kRxIndexBits) return nullptr;
  return &r;
}

uint32_t J1939PlcMsgs::rx_open(uint8_t network, uint32_t pgn, uint8_t source, uint8_t flags, uint16_t depth,
                               uint16_t& error_id) {
  error_id = check_network(network);
  if (error_id) return 0;
  const bool any = flags & CANWORKS_J1939_RX_ANY;
  if ((!any && pgn > kMaxPgn) || source == kJ1939NullAddress || depth > CANWORKS_J1939_DEPTH_MAX) {
    error_id = CANWORKS_J1939_ERR_INPUT;
    return 0;
  }
  std::lock_guard<std::mutex> lock(mutex_);
  if (!running()) {
    error_id = CANWORKS_J1939_ERR_NOT_RUNNING;
    return 0;
  }
  unsigned in_use = 0;
  int free_slot = -1;
  for (unsigned i = 0; i < kReceiverSlots; ++i) {
    const Receiver& r = receivers_[i];
    if (r.state == RxState::Free) {
      if (free_slot < 0) free_slot = static_cast<int>(i);
    } else if (r.network == network && !r.cancelled) {
      ++in_use;
    }
  }
  if (free_slot < 0 || in_use >= CANWORKS_J1939_RECEIVERS) {
    error_id = CANWORKS_J1939_ERR_FULL;
    return 0;
  }
  Receiver& r = receivers_[free_slot];
  r.seq = next_seq_;
  next_seq_ = (next_seq_ + 1) & kSeqMask;
  if (!next_seq_) next_seq_ = 1;
  r.network = network;
  r.filter.handle = (r.seq << kRxIndexBits) | static_cast<uint32_t>(free_slot);
  r.filter.pgn = any ? 0 : normal_pgn(pgn);
  r.filter.any = any;
  r.filter.source = source;
  r.filter.all_destinations = flags & CANWORKS_J1939_RX_ALL_DESTINATIONS;
  r.depth = depth ? depth : CANWORKS_J1939_DEPTH_DEFAULT;
  r.cancelled = false;
  r.head = r.count = 0;
  r.overflow = false;
  r.dropped = 0;
  r.state = RxState::Opening;
  ++filter_gen_[network];
  return r.filter.handle;
}

int J1939PlcMsgs::rx_read(uint32_t handle, canworks_j1939_msg* msg, canworks_j1939_rx_info* info) {
  std::lock_guard<std::mutex> lock(mutex_);
  Receiver* r = find_rx(handle);
  if (info) *info = canworks_j1939_rx_info{};
  if (!r) return -static_cast<int>(CANWORKS_J1939_ERR_CANCELLED);
  if (r->cancelled) {
    r->state = RxState::Free;  // the bus thread frees its queue
    return -static_cast<int>(CANWORKS_J1939_ERR_CANCELLED);
  }
  int got = 0;
  if (r->state == RxState::Open && r->count) {
    const canworks_j1939_msg& m = r->queue[r->head];
    if (msg) std::memcpy(msg, &m, offsetof(canworks_j1939_msg, data) + m.length);
    r->head = static_cast<uint16_t>((r->head + 1) % r->capacity);
    --r->count;
    got = 1;
  }
  if (info) {
    info->queued = r->count;
    info->overflow = r->overflow;
    info->dropped = r->dropped;
    info->bus_down = (bus_down_.load(std::memory_order_acquire) >> r->network) & 1u;
  }
  return got;
}

void J1939PlcMsgs::rx_close(uint32_t handle) {
  std::lock_guard<std::mutex> lock(mutex_);
  Receiver* r = find_rx(handle);
  if (!r) return;
  // The bus thread frees the queue; the slot is free for a new receiver now.
  r->state = RxState::Free;
  ++filter_gen_[r->network];
}

bool J1939PlcMsgs::sync_receivers(unsigned network, std::vector<Filter>& out) {
  if (network >= kMaxNetworks) return false;
  std::vector<std::pair<unsigned, uint16_t>> grow;
  // The generation this call takes in: a receiver opened or closed after the
  // first section bumps it past this, and the next call sees it.
  uint32_t gen;
  {
    std::lock_guard<std::mutex> lock(mutex_);
    gen = filter_gen_[network];
    if (filter_seen_[network] == gen) return false;
    for (unsigned i = 0; i < kReceiverSlots; ++i) {
      Receiver& r = receivers_[i];
      if (r.network != network) continue;
      if (r.state == RxState::Free && r.queue) {
        r.queue.reset();
        r.capacity = 0;
      }
      if (r.state == RxState::Opening && r.capacity < r.depth) grow.emplace_back(i, r.depth);
    }
  }
  // Allocate outside the lock, then swap in.
  std::vector<std::unique_ptr<canworks_j1939_msg[]>> queues;
  for (const auto& g : grow) queues.emplace_back(new canworks_j1939_msg[g.second]);
  if (sync_gap_for_test) sync_gap_for_test();
  std::lock_guard<std::mutex> lock(mutex_);
  for (size_t k = 0; k < grow.size(); ++k) {
    Receiver& r = receivers_[grow[k].first];
    if (r.state != RxState::Opening || r.depth != grow[k].second) continue;
    r.queue = std::move(queues[k]);
    r.capacity = grow[k].second;
  }
  out.clear();
  for (auto& r : receivers_) {
    if (r.network != network || r.cancelled) continue;
    if (r.state == RxState::Opening && r.capacity >= r.depth) {
      r.head = r.count = 0;
      r.state = RxState::Open;
    }
    if (r.state == RxState::Open) out.push_back(r.filter);
  }
  filter_seen_[network] = gen;
  return true;
}

void J1939PlcMsgs::deliver(unsigned network, uint32_t pgn, uint8_t source, uint8_t destination, uint8_t priority,
                           const uint8_t* data, size_t length, uint64_t time_us, uint8_t own) {
  if (length > CANWORKS_J1939_MAX_LENGTH) length = CANWORKS_J1939_MAX_LENGTH;
  std::lock_guard<std::mutex> lock(mutex_);
  for (auto& r : receivers_) {
    if (r.state != RxState::Open || r.network != network || r.cancelled) continue;
    const Filter& f = r.filter;
    if (!f.any && f.pgn != pgn) continue;
    if (f.source != kJ1939Global && f.source != source) continue;
    if (!f.all_destinations && destination != kJ1939Global && destination != own) continue;
    if (r.count >= r.depth) {
      r.overflow = true;
      ++r.dropped;
      continue;
    }
    canworks_j1939_msg& m = r.queue[(r.head + r.count) % r.capacity];
    m.pgn = pgn;
    m.source = source;
    m.destination = destination;
    m.priority = priority;
    m.ack_code = 0;
    m.length = static_cast<uint16_t>(length);
    m.time_us = time_us;
    if (length) std::memcpy(m.data, data, length);
    ++r.count;
  }
}

void J1939PlcMsgs::set_bus_down(unsigned network, bool down) {
  if (network >= kMaxNetworks) return;
  if (down)
    bus_down_.fetch_or(1u << network, std::memory_order_acq_rel);
  else
    bus_down_.fetch_and(~(1u << network), std::memory_order_acq_rel);
}

void J1939PlcMsgs::receiver_status(unsigned network, std::vector<RxStatus>& out) {
  out.clear();
  std::lock_guard<std::mutex> lock(mutex_);
  for (const auto& r : receivers_) {
    if (r.state != RxState::Open || r.network != network || r.cancelled) continue;
    RxStatus s;
    s.filter = r.filter;
    s.queued = r.count;
    s.dropped = r.dropped;
    out.push_back(s);
  }
}

// ---- ECU state ----

void J1939PlcMsgs::publish_ecu(unsigned network, uint8_t state, uint8_t address, uint64_t name,
                               const std::vector<Ecu>& ecus) {
  if (network >= kMaxNetworks) return;
  std::lock_guard<std::mutex> lock(mutex_);
  EcuView& v = ecu_[network];
  v.valid = true;
  v.state = state;
  v.address = address;
  v.name = name;
  v.ecus = ecus;
}

int J1939PlcMsgs::ecu_info(uint8_t network, canworks_j1939_ecu_info& out, uint16_t& error_id) {
  out = canworks_j1939_ecu_info{};
  out.state = 3;
  out.address = kJ1939NullAddress;
  error_id = check_network(network);
  if (error_id) return 2;
  std::lock_guard<std::mutex> lock(mutex_);
  const EcuView& v = ecu_[network];
  if (!v.valid) {
    error_id = CANWORKS_J1939_ERR_NOT_RUNNING;
    return 2;
  }
  out.state = v.state;
  out.address = v.address;
  out.name = v.name;
  out.ecu_count = static_cast<uint16_t>(v.ecus.size());
  return 0;
}

int J1939PlcMsgs::find_ecu(uint8_t network, uint64_t name, uint64_t mask, canworks_j1939_ecu_found& out,
                           uint16_t& error_id) {
  out = canworks_j1939_ecu_found{};
  error_id = check_network(network);
  if (error_id) return 2;
  std::lock_guard<std::mutex> lock(mutex_);
  const EcuView& v = ecu_[network];
  if (!v.valid) {
    error_id = CANWORKS_J1939_ERR_NOT_RUNNING;
    return 2;
  }
  // The list is sorted by address: the first match is the lowest.
  for (const auto& e : v.ecus) {
    if (((e.name ^ name) & mask) != 0) continue;
    if (!out.found) {
      out.found = 1;
      out.address = e.address;
      out.name = e.name;
    }
    ++out.count;
  }
  return 0;
}

}  // namespace canopen_plugin
