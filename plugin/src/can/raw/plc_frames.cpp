// plc_frames.cpp - see plc_frames.h.

#include "plc_frames.h"

#include <time.h>

#include <cstring>

namespace canworks_raw {

namespace {

constexpr uint32_t kStdMax = 0x7FFu;
constexpr uint32_t kExtMax = 0x1FFFFFFFu;
constexpr uint32_t kDefaultTimeoutMs = 100;

// Handle: network (3 bits) | kind (2 bits) | slot (8 bits) | generation (19 bits).
constexpr unsigned kKindRx = 1, kKindTx = 2, kKindJob = 3;
constexpr uint32_t kGenMask = 0x7FFFFu;

uint32_t next_gen(uint32_t gen) {
  gen = (gen + 1) & kGenMask;
  return gen ? gen : 1;
}

bool frame_ok(const canworks_can_frame& f) {
  if (f.dlc > 8) return false;
  if (f.flags & ~(CANWORKS_CAN_EXTENDED | CANWORKS_CAN_RTR)) return false;
  return f.id <= ((f.flags & CANWORKS_CAN_EXTENDED) ? kExtMax : kStdMax);
}

bool same_frame(const canworks_can_frame& a, const canworks_can_frame& b) {
  if (a.id != b.id || a.flags != b.flags || a.dlc != b.dlc) return false;
  if (a.flags & CANWORKS_CAN_RTR) return true;
  return std::memcmp(a.data, b.data, a.dlc) == 0;
}

std::atomic<PlcPort*> g_ports[kMaxNetworks];

}  // namespace

uint64_t monotonic_us() {
  timespec ts;
  clock_gettime(CLOCK_MONOTONIC, &ts);
  return static_cast<uint64_t>(ts.tv_sec) * 1000000u + static_cast<uint64_t>(ts.tv_nsec) / 1000u;
}

void set_port(uint8_t network, PlcPort* p) {
  if (network < kMaxNetworks) g_ports[network].store(p, std::memory_order_release);
}

PlcPort* port(uint8_t network) {
  return network < kMaxNetworks ? g_ports[network].load(std::memory_order_acquire) : nullptr;
}

// Each port starts its handle generations where the previous ports left
// off, so a handle the program kept from before a PLC restart (a new port)
// answers "cancelled" instead of naming a new receiver or job.
static std::atomic<uint32_t> g_gen_seed{0};

PlcPort::PlcPort(uint8_t network) : network_(network) {
  bus_.state = 4;
  uint32_t base = g_gen_seed.fetch_add(0x1000, std::memory_order_relaxed) & kGenMask;
  for (Receiver& r : rx_) r.gen = base;
  for (TxSlot& t : tx_) t.gen = base;
  for (Job& j : jobs_) j.gen = base;
}

void PlcPort::set_rules(PortRules rules) { rules_ = std::move(rules); }

uint32_t PlcPort::make_handle(unsigned kind, unsigned slot, uint32_t gen) const {
  return (static_cast<uint32_t>(network_ & 7u) << 29) | (kind << 27) | (static_cast<uint32_t>(slot) << 19) |
         (gen & kGenMask);
}

bool PlcPort::split_handle(uint32_t handle, unsigned kind, unsigned& slot, uint32_t& gen) const {
  if ((handle >> 29) != (network_ & 7u) || ((handle >> 27) & 3u) != kind) return false;
  slot = (handle >> 19) & 0xFFu;
  gen = handle & kGenMask;
  return gen != 0;
}

uint16_t PlcPort::check_send(const canworks_can_frame& f) const {
  if (!frame_ok(f)) return CANWORKS_CAN_ERR_INPUT;
  if (!running()) return CANWORKS_CAN_ERR_NOT_RUNNING;
  if (rules_.listen_only) return CANWORKS_CAN_ERR_LISTEN_ONLY;
  if (!rules_.override_protocol && rules_.owned && rules_.owned(f.id, (f.flags & CANWORKS_CAN_EXTENDED) != 0))
    return CANWORKS_CAN_ERR_PROTOCOL;
  if (bus_down()) return CANWORKS_CAN_ERR_BUS;
  return 0;
}

bool PlcPort::bus_down() const {
  uint32_t s = bus_seq_.load(std::memory_order_acquire);
  uint8_t state = bus_.state;
  return !(s & 1u) && (state == 3 || state == 4);
}

// --- Receivers ---

uint32_t PlcPort::rx_open(uint32_t id, uint32_t mask, uint8_t flags, uint16_t depth, uint16_t* error_id) {
  *error_id = 0;
  bool ext = (flags & CANWORKS_CAN_EXTENDED) != 0;
  uint32_t max = ext ? kExtMax : kStdMax;
  if ((flags & ~(CANWORKS_CAN_EXTENDED | CANWORKS_CAN_RTR)) || id > max || depth > kDepth) {
    *error_id = CANWORKS_CAN_ERR_INPUT;
    return 0;
  }
  if (!running()) {
    *error_id = CANWORKS_CAN_ERR_NOT_RUNNING;
    return 0;
  }
  for (unsigned i = 0; i < kRx; ++i) {
    Receiver& r = rx_[i];
    if (r.open.load(std::memory_order_relaxed)) continue;
    r.id = id & max;
    r.mask = mask & max;
    r.flags = flags;
    r.depth = depth ? depth : CANWORKS_CAN_DEPTH_DEFAULT;
    r.gen = next_gen(r.gen);
    r.epoch.fetch_add(1, std::memory_order_relaxed);
    r.tail.store(r.head.load(std::memory_order_acquire), std::memory_order_relaxed);
    r.dropped_base = r.dropped.load(std::memory_order_relaxed);
    r.open.store(true, std::memory_order_release);
    rx_version_.fetch_add(1, std::memory_order_release);
    return make_handle(kKindRx, i, r.gen);
  }
  *error_id = CANWORKS_CAN_ERR_FULL;
  return 0;
}

int PlcPort::rx_read(uint32_t handle, canworks_can_frame* frame, canworks_can_rx_info* info) {
  *info = canworks_can_rx_info{};
  unsigned slot;
  uint32_t gen;
  if (!split_handle(handle, kKindRx, slot, gen) || slot >= kRx) return -CANWORKS_CAN_ERR_CANCELLED;
  Receiver& r = rx_[slot];
  if (r.gen != gen || !r.open.load(std::memory_order_relaxed)) return -CANWORKS_CAN_ERR_CANCELLED;
  uint32_t epoch = r.epoch.load(std::memory_order_relaxed);
  uint32_t head = r.head.load(std::memory_order_acquire);
  uint32_t tail = r.tail.load(std::memory_order_relaxed);
  int got = 0;
  while (tail != head) {
    const Entry& e = r.ring[tail % kDepth];
    ++tail;
    if (e.epoch != epoch) continue;  // pushed before this receiver opened
    *frame = e.frame;
    got = 1;
    break;
  }
  r.tail.store(tail, std::memory_order_release);
  uint32_t dropped = r.dropped.load(std::memory_order_relaxed) - r.dropped_base;
  info->queued = static_cast<uint16_t>(head - tail);
  info->dropped = dropped;
  info->overflow = dropped != 0;
  info->bus_down = bus_down();
  return got;
}

void PlcPort::rx_close(uint32_t handle) {
  unsigned slot;
  uint32_t gen;
  if (!split_handle(handle, kKindRx, slot, gen) || slot >= kRx) return;
  Receiver& r = rx_[slot];
  if (r.gen != gen) return;
  r.gen = next_gen(r.gen);
  if (r.open.exchange(false, std::memory_order_acq_rel)) rx_version_.fetch_add(1, std::memory_order_release);
}

void PlcPort::on_frame(const canworks_can_frame& f) {
  bool ext = (f.flags & CANWORKS_CAN_EXTENDED) != 0;
  for (Receiver& r : rx_) {
    if (!r.open.load(std::memory_order_acquire)) continue;
    if (((r.flags ^ f.flags) & CANWORKS_CAN_EXTENDED) != 0) continue;
    if ((r.flags & CANWORKS_CAN_RTR) && !(f.flags & CANWORKS_CAN_RTR)) continue;
    (void)ext;
    if ((f.id & r.mask) != (r.id & r.mask)) continue;
    uint32_t head = r.head.load(std::memory_order_relaxed);
    uint32_t tail = r.tail.load(std::memory_order_acquire);
    if (head - tail >= r.depth) {
      r.dropped.fetch_add(1, std::memory_order_relaxed);
      continue;
    }
    Entry& e = r.ring[head % kDepth];
    e.frame = f;
    e.epoch = r.epoch.load(std::memory_order_relaxed);
    r.head.store(head + 1, std::memory_order_release);
  }
}

bool PlcPort::active() const {
  for (const Receiver& r : rx_)
    if (r.open.load(std::memory_order_acquire)) return true;
  for (const Job& j : jobs_)
    if (j.active.load(std::memory_order_acquire)) return true;
  return txq_head_.load(std::memory_order_acquire) != txq_tail_.load(std::memory_order_relaxed) ||
         echo_head_ != echo_tail_;
}

void PlcPort::for_each_receiver(const std::function<void(uint32_t, uint32_t, uint8_t)>& f) const {
  for (const Receiver& r : rx_)
    if (r.open.load(std::memory_order_acquire)) f(r.id, r.mask, r.flags);
}

// --- Single frames ---

uint32_t PlcPort::tx_send(const canworks_can_frame* frame, uint32_t timeout_ms, uint16_t* error_id) {
  *error_id = check_send(*frame);
  if (*error_id) return 0;
  for (unsigned i = 0; i < kTx; ++i) {
    TxSlot& s = tx_[i];
    if (s.state.load(std::memory_order_acquire) != kFree) continue;
    s.frame = *frame;
    if (s.frame.flags & CANWORKS_CAN_RTR) std::memset(s.frame.data, 0, sizeof s.frame.data);
    s.gen = next_gen(s.gen);
    s.deadline_us = monotonic_us() + static_cast<uint64_t>(timeout_ms ? timeout_ms : kDefaultTimeoutMs) * 1000u;
    s.error.store(0, std::memory_order_relaxed);
    s.state.store(kQueued, std::memory_order_release);
    uint32_t head = txq_head_.load(std::memory_order_relaxed);
    txq_[head % kTx] = static_cast<uint8_t>(i);
    txq_head_.store(head + 1, std::memory_order_release);
    return make_handle(kKindTx, i, s.gen);
  }
  *error_id = CANWORKS_CAN_ERR_FULL;
  return 0;
}

int PlcPort::tx_poll(uint32_t handle, uint16_t* error_id) {
  *error_id = 0;
  unsigned slot;
  uint32_t gen;
  if (!split_handle(handle, kKindTx, slot, gen) || slot >= kTx || tx_[slot].gen != gen) {
    *error_id = CANWORKS_CAN_ERR_CANCELLED;
    return 2;
  }
  TxSlot& s = tx_[slot];
  uint8_t st = s.state.load(std::memory_order_acquire);
  if (st == kQueued || st == kWritten) {
    if (monotonic_us() < s.deadline_us) return 0;
    // Give the slot to the raw thread to free; if it finished meanwhile, take
    // its result instead.
    if (s.state.compare_exchange_strong(st, kAbandoned, std::memory_order_acq_rel)) {
      s.gen = next_gen(s.gen);
      *error_id = CANWORKS_CAN_ERR_TIMEOUT;
      return 2;
    }
  }
  if (st == kDone || st == kFailed) {
    *error_id = st == kFailed ? s.error.load(std::memory_order_relaxed) : 0;
    s.gen = next_gen(s.gen);
    s.state.store(kFree, std::memory_order_release);
    return st == kDone ? 1 : 2;
  }
  *error_id = CANWORKS_CAN_ERR_CANCELLED;
  return 2;
}

bool PlcPort::next_tx(canworks_can_frame& frame, uint32_t& tag) {
  for (;;) {
    uint32_t tail = txq_tail_.load(std::memory_order_relaxed);
    if (tail == txq_head_.load(std::memory_order_acquire)) return false;
    uint8_t i = txq_[tail % kTx];
    txq_tail_.store(tail + 1, std::memory_order_release);
    TxSlot& s = tx_[i];
    uint8_t st = s.state.load(std::memory_order_acquire);
    if (st == kAbandoned) {  // timed out before it could be written
      s.state.store(kFree, std::memory_order_release);
      continue;
    }
    if (st != kQueued) continue;
    frame = s.frame;
    tag = i;
    return true;
  }
}

namespace {
// Moves `s` from `from` to `to` unless the scan gave up on it, in which case
// the slot is freed.
template <typename Slot>
void finish(Slot& s, uint8_t from, uint8_t to) {
  uint8_t st = from;
  if (!s.state.compare_exchange_strong(st, to, std::memory_order_acq_rel) && st == 5 /* kAbandoned */)
    s.state.store(0 /* kFree */, std::memory_order_release);
}
}  // namespace

void PlcPort::tx_written(uint32_t tag, bool confirmed) {
  if (tag >= kTx) return;
  TxSlot& s = tx_[tag];
  sent_.fetch_add(1, std::memory_order_relaxed);
  if (confirmed) {
    finish(s, kQueued, kDone);
    return;
  }
  s.written_us = monotonic_us();
  uint8_t st = kQueued;
  if (!s.state.compare_exchange_strong(st, kWritten, std::memory_order_acq_rel)) {
    if (st == kAbandoned) s.state.store(kFree, std::memory_order_release);
    return;
  }
  if (echo_head_ - echo_tail_ < kTx) echo_[echo_head_++ % kTx] = static_cast<uint8_t>(tag);
}

bool PlcPort::tx_pending(uint32_t tag) {
  if (tag >= kTx) return false;
  TxSlot& s = tx_[tag];
  uint8_t st = s.state.load(std::memory_order_acquire);
  if (st == kAbandoned) s.state.store(kFree, std::memory_order_release);
  return st == kQueued;
}

void PlcPort::tx_failed(uint32_t tag, uint16_t error_id) {
  if (tag >= kTx) return;
  TxSlot& s = tx_[tag];
  s.error.store(error_id, std::memory_order_relaxed);
  finish(s, kQueued, kFailed);
}

bool PlcPort::own_echo(const canworks_can_frame& frame) {
  for (uint32_t k = echo_tail_; k != echo_head_; ++k) {
    uint8_t i = echo_[k % kTx];
    TxSlot& s = tx_[i];
    uint8_t st = s.state.load(std::memory_order_acquire);
    if (st != kWritten && st != kAbandoned) continue;
    if (!same_frame(s.frame, frame)) continue;
    finish(s, kWritten, kDone);
    // Remove entry k, keeping the order of the rest.
    for (uint32_t m = k; m + 1 != echo_head_; ++m) echo_[m % kTx] = echo_[(m + 1) % kTx];
    --echo_head_;
    return true;
  }
  return false;
}

void PlcPort::expire_echoes(uint64_t now_us, uint64_t max_age_us) {
  while (echo_tail_ != echo_head_) {
    TxSlot& s = tx_[echo_[echo_tail_ % kTx]];
    uint8_t st = s.state.load(std::memory_order_acquire);
    // The caller's `now_us` may predate written_us (read before the write).
    if ((st == kWritten || st == kAbandoned) && (now_us < s.written_us || now_us - s.written_us < max_age_us)) break;
    if (st == kWritten || st == kAbandoned) {
      s.error.store(CANWORKS_CAN_ERR_TIMEOUT, std::memory_order_relaxed);
      finish(s, kWritten, kFailed);
    }
    ++echo_tail_;
  }
}

// --- Cyclic jobs ---

void PlcPort::read_job(const Job& j, canworks_can_frame& f, uint32_t& period_us) const {
  for (;;) {
    uint32_t a = j.seq.load(std::memory_order_acquire);
    if (a & 1u) continue;
    f = j.frame;
    period_us = j.period_us;
    std::atomic_thread_fence(std::memory_order_acquire);
    if (j.seq.load(std::memory_order_relaxed) == a) return;
  }
}

namespace {
constexpr uint32_t kPeriodMin = 1000, kPeriodMax = 60000000;
}

uint32_t PlcPort::cyc_start(const canworks_can_frame* frame, uint32_t period_us, uint16_t* error_id) {
  *error_id = check_send(*frame);
  if (!*error_id && (period_us < kPeriodMin || period_us > kPeriodMax)) *error_id = CANWORKS_CAN_ERR_INPUT;
  if (*error_id) return 0;
  for (unsigned i = 0; i < kJobs; ++i) {
    Job& j = jobs_[i];
    if (j.active.load(std::memory_order_relaxed)) continue;
    j.seq.fetch_add(1, std::memory_order_acq_rel);
    j.frame = *frame;
    j.period_us = period_us;
    j.seq.fetch_add(1, std::memory_order_release);
    j.count.store(0, std::memory_order_relaxed);
    j.gen = next_gen(j.gen);
    j.start.fetch_add(1, std::memory_order_release);
    j.active.store(true, std::memory_order_release);
    return make_handle(kKindJob, i, j.gen);
  }
  *error_id = CANWORKS_CAN_ERR_FULL;
  return 0;
}

int PlcPort::cyc_update(uint32_t handle, const canworks_can_frame* frame, uint32_t period_us, uint32_t* count,
                        uint16_t* error_id) {
  *error_id = 0;
  unsigned slot;
  uint32_t gen;
  if (!split_handle(handle, kKindJob, slot, gen) || slot >= kJobs || jobs_[slot].gen != gen ||
      !jobs_[slot].active.load(std::memory_order_acquire)) {
    *error_id = CANWORKS_CAN_ERR_CANCELLED;
    return 2;
  }
  Job& j = jobs_[slot];
  *count = j.count.load(std::memory_order_relaxed);
  canworks_can_frame f = j.frame;  // identifier and flags stay as started
  f.dlc = frame->dlc;
  std::memcpy(f.data, frame->data, sizeof f.data);
  if (f.dlc > 8 || period_us < kPeriodMin || period_us > kPeriodMax) {
    *error_id = CANWORKS_CAN_ERR_INPUT;
    return 2;
  }
  j.seq.fetch_add(1, std::memory_order_acq_rel);
  j.frame = f;
  j.period_us = period_us;
  j.seq.fetch_add(1, std::memory_order_release);
  if (bus_down()) *error_id = CANWORKS_CAN_ERR_BUS;  // the job stays; COUNT resumes when the bus is back
  return 0;
}

void PlcPort::cyc_stop(uint32_t handle) {
  unsigned slot;
  uint32_t gen;
  if (!split_handle(handle, kKindJob, slot, gen) || slot >= kJobs || jobs_[slot].gen != gen) return;
  jobs_[slot].gen = next_gen(jobs_[slot].gen);
  jobs_[slot].active.store(false, std::memory_order_release);
}

int PlcPort::cyclic_due(uint64_t now_us, canworks_can_frame* out, uint8_t* jobs, int max) {
  int n = 0;
  for (unsigned i = 0; i < kJobs && n < max; ++i) {
    Job& j = jobs_[i];
    if (!j.active.load(std::memory_order_acquire)) continue;
    canworks_can_frame f;
    uint32_t period;
    read_job(j, f, period);
    uint32_t start = j.start.load(std::memory_order_acquire);
    if (start != j.seen_start) {  // a new job: first frame now
      j.seen_start = start;
      j.next_due = now_us;
    }
    if (now_us < j.next_due) continue;
    // Keep the phase; after a long stall, restart from now instead of bursting.
    j.next_due += period;
    if (j.next_due <= now_us) j.next_due = now_us + period;
    out[n] = f;
    jobs[n] = static_cast<uint8_t>(i);
    ++n;
  }
  return n;
}

void PlcPort::cyclic_sent(uint8_t job) {
  if (job < kJobs) {
    jobs_[job].count.fetch_add(1, std::memory_order_relaxed);
    sent_.fetch_add(1, std::memory_order_relaxed);
  }
}

uint64_t PlcPort::next_cyclic_in(uint64_t now_us) const {
  uint64_t best = UINT64_MAX;
  for (const Job& j : jobs_) {
    if (!j.active.load(std::memory_order_acquire)) continue;
    if (j.start.load(std::memory_order_acquire) != j.seen_start || j.next_due <= now_us) return 0;
    uint64_t in = j.next_due - now_us;
    if (in < best) best = in;
  }
  return best;
}

// --- Bus ---

void PlcPort::set_running(bool running) {
  running_.store(running, std::memory_order_release);
  if (running) {
    // Until the raw path reports the bus, take it as active.
    canworks_can_bus_info up{};
    publish_bus(up);
  } else {
    canworks_can_bus_info down{};
    down.state = 4;
    publish_bus(down);
  }
}

void PlcPort::publish_bus(const canworks_can_bus_info& info) {
  bus_seq_.fetch_add(1, std::memory_order_acq_rel);
  bus_ = info;
  bus_seq_.fetch_add(1, std::memory_order_release);
}

int PlcPort::bus_info(canworks_can_bus_info* info, uint16_t* error_id) {
  *error_id = 0;
  for (;;) {
    uint32_t a = bus_seq_.load(std::memory_order_acquire);
    if (a & 1u) continue;
    *info = bus_;
    std::atomic_thread_fence(std::memory_order_acquire);
    if (bus_seq_.load(std::memory_order_relaxed) == a) break;
  }
  info->rx_count = rx_count_.load(std::memory_order_relaxed);
  info->tx_count = tx_count_.load(std::memory_order_relaxed);
  if (!running()) info->state = 4;
  return 0;
}

// --- Lifecycle ---

void PlcPort::cancel_all() {
  bool changed = false;
  for (Receiver& r : rx_) {
    r.gen = next_gen(r.gen);
    if (r.open.exchange(false, std::memory_order_acq_rel)) changed = true;
  }
  if (changed) rx_version_.fetch_add(1, std::memory_order_release);
  for (Job& j : jobs_) {
    j.gen = next_gen(j.gen);
    j.active.store(false, std::memory_order_release);
  }
  // Pending single frames: their handles go stale; slots still owned by the
  // raw thread are freed when it reaches them.
  for (TxSlot& s : tx_) {
    s.gen = next_gen(s.gen);
    uint8_t st = s.state.load(std::memory_order_acquire);
    if (st == kDone || st == kFailed) {
      s.state.store(kFree, std::memory_order_release);
    } else if (st == kQueued || st == kWritten) {
      s.state.compare_exchange_strong(st, kAbandoned, std::memory_order_acq_rel);
    }
  }
}

PlcPort::Stats PlcPort::stats() const {
  Stats s;
  for (const Receiver& r : rx_) {
    if (r.open.load(std::memory_order_acquire)) ++s.receivers;
    s.dropped += r.dropped.load(std::memory_order_relaxed);
  }
  for (const Job& j : jobs_)
    if (j.active.load(std::memory_order_acquire)) ++s.cyclic_jobs;
  s.sent = sent_.load(std::memory_order_relaxed);
  return s;
}

// --- The C table ---

namespace {

uint32_t api_rx_open(uint8_t network, uint32_t id, uint32_t mask, uint8_t flags, uint16_t depth,
                     uint16_t* error_id) {
  PlcPort* p = port(network);
  if (!p) {
    *error_id = CANWORKS_CAN_ERR_NETWORK;
    return 0;
  }
  return p->rx_open(id, mask, flags, depth, error_id);
}

int api_rx_read(uint32_t handle, canworks_can_frame* frame, canworks_can_rx_info* info) {
  PlcPort* p = port(static_cast<uint8_t>(handle >> 29));
  if (!p) {
    *info = canworks_can_rx_info{};
    return -CANWORKS_CAN_ERR_CANCELLED;
  }
  return p->rx_read(handle, frame, info);
}

void api_rx_close(uint32_t handle) {
  if (PlcPort* p = port(static_cast<uint8_t>(handle >> 29))) p->rx_close(handle);
}

uint32_t api_tx_send(uint8_t network, const canworks_can_frame* frame, uint32_t timeout_ms, uint16_t* error_id) {
  PlcPort* p = port(network);
  if (!p) {
    *error_id = CANWORKS_CAN_ERR_NETWORK;
    return 0;
  }
  return p->tx_send(frame, timeout_ms, error_id);
}

int api_tx_poll(uint32_t handle, uint16_t* error_id) {
  PlcPort* p = port(static_cast<uint8_t>(handle >> 29));
  if (!p) {
    *error_id = CANWORKS_CAN_ERR_CANCELLED;
    return 2;
  }
  return p->tx_poll(handle, error_id);
}

uint32_t api_cyc_start(uint8_t network, const canworks_can_frame* frame, uint32_t period_us, uint16_t* error_id) {
  PlcPort* p = port(network);
  if (!p) {
    *error_id = CANWORKS_CAN_ERR_NETWORK;
    return 0;
  }
  return p->cyc_start(frame, period_us, error_id);
}

int api_cyc_update(uint32_t handle, const canworks_can_frame* frame, uint32_t period_us, uint32_t* count,
                   uint16_t* error_id) {
  PlcPort* p = port(static_cast<uint8_t>(handle >> 29));
  if (!p) {
    *count = 0;
    *error_id = CANWORKS_CAN_ERR_CANCELLED;
    return 2;
  }
  return p->cyc_update(handle, frame, period_us, count, error_id);
}

void api_cyc_stop(uint32_t handle) {
  if (PlcPort* p = port(static_cast<uint8_t>(handle >> 29))) p->cyc_stop(handle);
}

int api_bus_info(uint8_t network, canworks_can_bus_info* info, uint16_t* error_id) {
  PlcPort* p = port(network);
  if (!p) {
    *info = canworks_can_bus_info{};
    info->state = 4;
    *error_id = CANWORKS_CAN_ERR_NETWORK;
    return 2;
  }
  return p->bus_info(info, error_id);
}

const canworks_can_api_v1 kApiV1 = {
    sizeof(canworks_can_api_v1), api_rx_open, api_rx_read, api_rx_close, api_tx_send,
    api_tx_poll,                 api_cyc_start, api_cyc_update, api_cyc_stop, api_bus_info,
};

}  // namespace

}  // namespace canworks_raw

// The plugin exports it as canworks_can_api (plugin.cpp).
extern "C" const void* canworks_can_api_table(uint32_t version) {
  return version == 1 ? &canworks_raw::kApiV1 : nullptr;
}
