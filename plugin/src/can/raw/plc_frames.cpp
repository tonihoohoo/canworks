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
  canworks_can_bus_info down{};
  down.state = 4;
  bus_[0].write(down);
  bus_[1].write(down);
  bus_last_.write(down);
  uint32_t base = g_gen_seed.fetch_add(0x1000, std::memory_order_relaxed) & kGenMask;
  for (Receiver& r : rx_) r.gen.store(base, std::memory_order_relaxed);
  for (TxSlot& t : tx_) t.gen.store(base, std::memory_order_relaxed);
  for (Job& j : jobs_) {
    j.gen.store(base, std::memory_order_relaxed);
    j.data.write(JobData{});
  }
  for (unsigned i = 0; i < kTx; ++i) txq_[i].seq.store(i, std::memory_order_relaxed);
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
  uint8_t state = bus_state_.load(std::memory_order_acquire);
  return state == 3 || state == 4;
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
    uint8_t free = kSlotFree;
    if (r.state.load(std::memory_order_relaxed) != kSlotFree ||
        !r.state.compare_exchange_strong(free, kSlotClaimed, std::memory_order_acq_rel))
      continue;
    // The epoch first: a frame the raw thread matched against the slot's
    // previous filter re-checks it and is dropped (or read and skipped).
    r.epoch.fetch_add(1, std::memory_order_relaxed);
    std::atomic_thread_fence(std::memory_order_release);
    r.id.store(id & max, std::memory_order_relaxed);
    r.mask.store(mask & max, std::memory_order_relaxed);
    r.flags.store(flags, std::memory_order_relaxed);
    r.depth.store(depth ? depth : CANWORKS_CAN_DEPTH_DEFAULT, std::memory_order_relaxed);
    uint32_t gen = next_gen(r.gen.load(std::memory_order_relaxed));
    r.gen.store(gen, std::memory_order_relaxed);
    r.tail.store(r.head.load(std::memory_order_acquire), std::memory_order_relaxed);
    r.dropped_base = r.dropped.load(std::memory_order_relaxed);
    r.state.store(kSlotOpen, std::memory_order_release);
    rx_version_.fetch_add(1, std::memory_order_release);
    return make_handle(kKindRx, i, gen);
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
  if (r.gen.load(std::memory_order_relaxed) != gen || r.state.load(std::memory_order_acquire) != kSlotOpen)
    return -CANWORKS_CAN_ERR_CANCELLED;
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
  if (r.gen.load(std::memory_order_relaxed) != gen) return;
  r.gen.store(next_gen(gen), std::memory_order_relaxed);
  uint8_t open = kSlotOpen;
  if (r.state.compare_exchange_strong(open, kSlotFree, std::memory_order_acq_rel))
    rx_version_.fetch_add(1, std::memory_order_release);
}

void PlcPort::on_frame(const canworks_can_frame& f) {
  for (Receiver& r : rx_) {
    if (r.state.load(std::memory_order_acquire) != kSlotOpen) continue;
    uint32_t epoch = r.epoch.load(std::memory_order_acquire);
    uint8_t flags = r.flags.load(std::memory_order_relaxed);
    uint32_t id = r.id.load(std::memory_order_relaxed), mask = r.mask.load(std::memory_order_relaxed);
    uint16_t depth = r.depth.load(std::memory_order_relaxed);
    if (((flags ^ f.flags) & CANWORKS_CAN_EXTENDED) != 0) continue;
    if ((flags & CANWORKS_CAN_RTR) && !(f.flags & CANWORKS_CAN_RTR)) continue;
    if ((f.id & mask) != (id & mask)) continue;
    // Reopened meanwhile (another filter): the match is not for this one.
    std::atomic_thread_fence(std::memory_order_acquire);
    if (r.state.load(std::memory_order_relaxed) != kSlotOpen || r.epoch.load(std::memory_order_relaxed) != epoch)
      continue;
    uint32_t head = r.head.load(std::memory_order_relaxed);
    uint32_t tail = r.tail.load(std::memory_order_acquire);
    if (head - tail >= depth) {
      r.dropped.fetch_add(1, std::memory_order_relaxed);
      continue;
    }
    // Should it be reopened from here on, the entry carries the old epoch
    // and the new owner skips it.
    Entry& e = r.ring[head % kDepth];
    e.frame = f;
    e.epoch = epoch;
    r.head.store(head + 1, std::memory_order_release);
  }
}

bool PlcPort::active() const {
  for (const Receiver& r : rx_)
    if (r.state.load(std::memory_order_acquire) == kSlotOpen) return true;
  for (const Job& j : jobs_)
    if (j.state.load(std::memory_order_acquire) == kSlotOpen) return true;
  return txq_head_.load(std::memory_order_acquire) != txq_tail_.load(std::memory_order_relaxed) ||
         echo_head_ != echo_tail_;
}

void PlcPort::for_each_receiver(const std::function<void(uint32_t, uint32_t, uint8_t)>& f) const {
  for (const Receiver& r : rx_)
    if (r.state.load(std::memory_order_acquire) == kSlotOpen)
      f(r.id.load(std::memory_order_relaxed), r.mask.load(std::memory_order_relaxed),
        r.flags.load(std::memory_order_relaxed));
}

// --- Single frames ---

uint32_t PlcPort::tx_send(const canworks_can_frame* frame, uint32_t timeout_ms, uint16_t* error_id) {
  *error_id = check_send(*frame);
  if (*error_id) return 0;
  for (unsigned i = 0; i < kTx; ++i) {
    TxSlot& s = tx_[i];
    uint8_t free = kFree;
    if (s.state.load(std::memory_order_relaxed) != kFree ||
        !s.state.compare_exchange_strong(free, kClaimed, std::memory_order_acq_rel))
      continue;
    s.frame = *frame;
    if (s.frame.flags & CANWORKS_CAN_RTR) std::memset(s.frame.data, 0, sizeof s.frame.data);
    uint32_t gen = next_gen(s.gen.load(std::memory_order_relaxed));
    s.gen.store(gen, std::memory_order_relaxed);
    s.deadline_us = monotonic_us() + static_cast<uint64_t>(timeout_ms ? timeout_ms : kDefaultTimeoutMs) * 1000u;
    s.error.store(0, std::memory_order_relaxed);
    s.state.store(kQueued, std::memory_order_release);
    if (!push_tx(static_cast<uint8_t>(i))) {  // cannot happen: one cell per slot
      s.state.store(kFree, std::memory_order_release);
      break;
    }
    return make_handle(kKindTx, i, gen);
  }
  *error_id = CANWORKS_CAN_ERR_FULL;
  return 0;
}

bool PlcPort::push_tx(uint8_t slot) {
  uint32_t pos = txq_head_.load(std::memory_order_relaxed);
  for (;;) {
    TxCell& c = txq_[pos % kTx];
    uint32_t seq = c.seq.load(std::memory_order_acquire);
    int32_t dif = static_cast<int32_t>(seq - pos);
    if (dif == 0) {
      if (txq_head_.compare_exchange_weak(pos, pos + 1, std::memory_order_relaxed)) break;
    } else if (dif < 0) {
      return false;
    } else {
      pos = txq_head_.load(std::memory_order_relaxed);
    }
  }
  TxCell& c = txq_[pos % kTx];
  c.slot = slot;
  c.seq.store(pos + 1, std::memory_order_release);
  return true;
}

int PlcPort::tx_poll(uint32_t handle, uint16_t* error_id) {
  *error_id = 0;
  unsigned slot;
  uint32_t gen;
  if (!split_handle(handle, kKindTx, slot, gen) || slot >= kTx ||
      tx_[slot].gen.load(std::memory_order_relaxed) != gen) {
    *error_id = CANWORKS_CAN_ERR_CANCELLED;
    return 2;
  }
  TxSlot& s = tx_[slot];
  uint8_t st = s.state.load(std::memory_order_acquire);
  if (st == kQueued || st == kWritten) {
    if (monotonic_us() < s.deadline_us) return 0;
    // Give the slot to the raw thread to free; if it finished meanwhile, take
    // its result instead. The handle goes stale first: once abandoned, the
    // slot may be freed and claimed by another task at once.
    s.gen.store(next_gen(gen), std::memory_order_relaxed);
    while ((st == kQueued || st == kWritten) &&
           !s.state.compare_exchange_weak(st, kAbandoned, std::memory_order_acq_rel)) {
    }
    if (st == kQueued || st == kWritten) {
      *error_id = CANWORKS_CAN_ERR_TIMEOUT;
      return 2;
    }
  }
  if (st == kDone || st == kFailed) {
    *error_id = st == kFailed ? s.error.load(std::memory_order_relaxed) : 0;
    s.gen.store(next_gen(gen), std::memory_order_relaxed);
    s.state.store(kFree, std::memory_order_release);
    return st == kDone ? 1 : 2;
  }
  *error_id = CANWORKS_CAN_ERR_CANCELLED;
  return 2;
}

bool PlcPort::next_tx(canworks_can_frame& frame, uint32_t& tag) {
  for (;;) {
    uint32_t tail = txq_tail_.load(std::memory_order_relaxed);
    TxCell& c = txq_[tail % kTx];
    // Empty, or the next cell's task has not finished putting it in yet.
    if (c.seq.load(std::memory_order_acquire) != tail + 1) return false;
    uint8_t i = c.slot;
    c.seq.store(tail + kTx, std::memory_order_release);
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

namespace {
constexpr uint32_t kPeriodMin = 1000, kPeriodMax = 60000000;
}

uint32_t PlcPort::cyc_start(const canworks_can_frame* frame, uint32_t period_us, uint16_t* error_id) {
  *error_id = check_send(*frame);
  if (!*error_id && (period_us < kPeriodMin || period_us > kPeriodMax)) *error_id = CANWORKS_CAN_ERR_INPUT;
  if (*error_id) return 0;
  for (unsigned i = 0; i < kJobs; ++i) {
    Job& j = jobs_[i];
    uint8_t free = kSlotFree;
    if (j.state.load(std::memory_order_relaxed) != kSlotFree ||
        !j.state.compare_exchange_strong(free, kSlotClaimed, std::memory_order_acq_rel))
      continue;
    j.data.write(JobData{*frame, period_us});
    j.count.store(0, std::memory_order_relaxed);
    uint32_t gen = next_gen(j.gen.load(std::memory_order_relaxed));
    j.gen.store(gen, std::memory_order_relaxed);
    j.start.fetch_add(1, std::memory_order_release);
    j.state.store(kSlotOpen, std::memory_order_release);
    return make_handle(kKindJob, i, gen);
  }
  *error_id = CANWORKS_CAN_ERR_FULL;
  return 0;
}

int PlcPort::cyc_update(uint32_t handle, const canworks_can_frame* frame, uint32_t period_us, uint32_t* count,
                        uint16_t* error_id) {
  *error_id = 0;
  unsigned slot;
  uint32_t gen;
  if (!split_handle(handle, kKindJob, slot, gen) || slot >= kJobs ||
      jobs_[slot].gen.load(std::memory_order_relaxed) != gen ||
      jobs_[slot].state.load(std::memory_order_acquire) != kSlotOpen) {
    *error_id = CANWORKS_CAN_ERR_CANCELLED;
    return 2;
  }
  Job& j = jobs_[slot];
  *count = j.count.load(std::memory_order_relaxed);
  JobData d;
  j.data.try_read(d);  // the owning task is the only writer: always complete
  canworks_can_frame f = d.frame;  // identifier and flags stay as started
  f.dlc = frame->dlc;
  std::memcpy(f.data, frame->data, sizeof f.data);
  if (f.dlc > 8 || period_us < kPeriodMin || period_us > kPeriodMax) {
    *error_id = CANWORKS_CAN_ERR_INPUT;
    return 2;
  }
  j.data.write(JobData{f, period_us});
  if (bus_down()) *error_id = CANWORKS_CAN_ERR_BUS;  // the job stays; COUNT resumes when the bus is back
  return 0;
}

void PlcPort::cyc_stop(uint32_t handle) {
  unsigned slot;
  uint32_t gen;
  if (!split_handle(handle, kKindJob, slot, gen) || slot >= kJobs ||
      jobs_[slot].gen.load(std::memory_order_relaxed) != gen)
    return;
  jobs_[slot].gen.store(next_gen(gen), std::memory_order_relaxed);
  uint8_t open = kSlotOpen;
  jobs_[slot].state.compare_exchange_strong(open, kSlotFree, std::memory_order_acq_rel);
}

int PlcPort::cyclic_due(uint64_t now_us, canworks_can_frame* out, uint8_t* jobs, int max) {
  int n = 0;
  for (unsigned i = 0; i < kJobs && n < max; ++i) {
    Job& j = jobs_[i];
    if (j.state.load(std::memory_order_acquire) != kSlotOpen) continue;
    uint32_t start = j.start.load(std::memory_order_acquire);
    // The task is changing the frame right now: its last consistent copy
    // (none for a job not seen yet: next pass).
    JobData d;
    bool fresh = j.data.try_read(d);
    if (fresh) j.last = d;
    if (start != j.seen_start) {  // a new job: first frame now
      if (!fresh) continue;
      j.seen_start = start;
      j.next_due = now_us;
    }
    const canworks_can_frame& f = j.last.frame;
    uint32_t period = j.last.period_us;
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
    if (j.state.load(std::memory_order_acquire) != kSlotOpen) continue;
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
  uint32_t next = bus_current_.load(std::memory_order_relaxed) ^ 1u;
  bus_[next].write(info);
  bus_current_.store(next, std::memory_order_release);
  bus_state_.store(info.state, std::memory_order_release);
}

int PlcPort::bus_info(canworks_can_bus_info* info, uint16_t* error_id) {
  *error_id = 0;
  // A read fails only when the raw thread published twice meanwhile. After
  // kBusReadTries the last complete copy any reader got is returned instead
  // of waiting (or, should that be being written right now, the state alone).
  constexpr int kBusReadTries = 4;
  bool good = false;
  for (int k = 0; k < kBusReadTries && !good; ++k)
    good = bus_[bus_current_.load(std::memory_order_acquire)].try_read(*info);
  if (good) {
    bool busy = false;
    if (bus_last_busy_.compare_exchange_strong(busy, true, std::memory_order_acquire)) {
      bus_last_.write(*info);
      bus_last_busy_.store(false, std::memory_order_release);
    }
  } else if (!bus_last_.try_read(*info)) {
    *info = canworks_can_bus_info{};
    info->state = bus_state_.load(std::memory_order_acquire);
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
    r.gen.store(next_gen(r.gen.load(std::memory_order_relaxed)), std::memory_order_relaxed);
    if (r.state.exchange(kSlotFree, std::memory_order_acq_rel) == kSlotOpen) changed = true;
  }
  if (changed) rx_version_.fetch_add(1, std::memory_order_release);
  for (Job& j : jobs_) {
    j.gen.store(next_gen(j.gen.load(std::memory_order_relaxed)), std::memory_order_relaxed);
    j.state.store(kSlotFree, std::memory_order_release);
  }
  // Pending single frames: their handles go stale; slots still owned by the
  // raw thread are freed when it reaches them.
  for (TxSlot& s : tx_) {
    s.gen.store(next_gen(s.gen.load(std::memory_order_relaxed)), std::memory_order_relaxed);
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
    if (r.state.load(std::memory_order_acquire) == kSlotOpen) ++s.receivers;
    s.dropped += r.dropped.load(std::memory_order_relaxed);
  }
  for (const Job& j : jobs_)
    if (j.state.load(std::memory_order_acquire) == kSlotOpen) ++s.cyclic_jobs;
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
