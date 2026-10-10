// j1939_plc_api.cpp - the job slots of the trouble code blocks and the C
// table canworks_j1939_api returns (j1939_plc_jobs.h, j1939_plc_api.h).

#include <cstring>

#include "j1939_config.h"
#include "j1939_plc_jobs.h"

namespace canopen_plugin {

constexpr uint32_t J1939PlcJobs::kDefaultTimeoutMs;
constexpr std::chrono::seconds J1939PlcJobs::kKeepResult;
constexpr std::chrono::seconds J1939PlcJobs::kGrace;

namespace {

constexpr uint32_t kIndexBits = 6;  // 64 slots
static_assert((1u << kIndexBits) == CANWORKS_J1939_SLOTS, "handle layout");
constexpr uint32_t kSeqMask = (1u << (32 - kIndexBits)) - 1;

bool is_read(J1939PlcJobs::Kind k) {
  return k == J1939PlcJobs::Kind::ReadDm1 || k == J1939PlcJobs::Kind::ReadDm2;
}

}  // namespace

J1939PlcJobs& J1939PlcJobs::instance() {
  static J1939PlcJobs jobs;
  return jobs;
}

void J1939PlcJobs::open(const std::vector<bool>& j1939_networks) {
  std::lock_guard<std::mutex> lock(mutex_);
  for (auto& s : slots_) s.state = State::Free;
  uint32_t bits = 0;
  for (size_t i = 0; i < j1939_networks.size() && i < kMaxNetworks; ++i)
    if (j1939_networks[i]) bits |= 1u << i;
  j1939_.store(bits, std::memory_order_release);
  networks_.store(static_cast<uint32_t>(j1939_networks.size()), std::memory_order_release);
  running_.store(true, std::memory_order_release);
}

void J1939PlcJobs::close() {
  std::lock_guard<std::mutex> lock(mutex_);
  running_.store(false, std::memory_order_release);
  for (auto& s : slots_) s.state = State::Free;
}

void J1939PlcJobs::set_attached(unsigned network, bool attached) {
  if (network >= kMaxNetworks) return;
  if (attached)
    attached_.fetch_or(1u << network, std::memory_order_acq_rel);
  else
    attached_.fetch_and(~(1u << network), std::memory_order_acq_rel);
}

uint32_t J1939PlcJobs::start(uint8_t network, Kind kind, uint8_t address, uint32_t timeout_ms,
                             uint16_t& error_id) {
  error_id = 0;
  if (!running()) {
    error_id = CANWORKS_J1939_ERR_NOT_RUNNING;
    return 0;
  }
  if (network >= networks_.load(std::memory_order_acquire) || network >= kMaxNetworks) {
    error_id = CANWORKS_J1939_ERR_NETWORK;
    return 0;
  }
  if (!(j1939_.load(std::memory_order_acquire) >> network & 1u)) {
    error_id = CANWORKS_J1939_ERR_NOT_J1939;
    return 0;
  }
  // A read names a source (0..253); a clear an address or 255 (global).
  if ((is_read(kind) && address > kJ1939MaxAddress) || (!is_read(kind) && address == kJ1939NullAddress)) {
    error_id = CANWORKS_J1939_ERR_INPUT;
    return 0;
  }
  if (!(attached_.load(std::memory_order_acquire) >> network & 1u)) {
    error_id = CANWORKS_J1939_ERR_NOT_RUNNING;
    return 0;
  }
  std::lock_guard<std::mutex> lock(mutex_);
  if (!running()) {
    error_id = CANWORKS_J1939_ERR_NOT_RUNNING;
    return 0;
  }
  for (uint32_t i = 0; i < CANWORKS_J1939_SLOTS; ++i) {
    Slot& s = slots_[i];
    if (s.state != State::Free) continue;
    s.seq = next_seq_;
    next_seq_ = (next_seq_ + 1) & kSeqMask;
    if (next_seq_ == 0) next_seq_ = 1;
    s.order = next_order_++;
    s.network = network;
    s.job.handle = (s.seq << kIndexBits) | i;
    s.job.kind = kind;
    s.job.address = address;
    s.job.timeout_ms = timeout_ms ? timeout_ms : kDefaultTimeoutMs;
    s.error_id = 0;
    s.started = clock::now();
    s.state = State::Queued;
    return s.job.handle;
  }
  // Every slot is in use: as many jobs wait as there can be addresses.
  error_id = CANWORKS_J1939_ERR_PENDING;
  return 0;
}

J1939PlcJobs::Slot* J1939PlcJobs::find(uint32_t handle) {
  Slot& s = slots_[handle & (CANWORKS_J1939_SLOTS - 1)];
  if (s.state == State::Free || s.seq != handle >> kIndexBits) return nullptr;
  return &s;
}

int J1939PlcJobs::poll(uint32_t handle, bool read, canworks_j1939_dm* out, uint16_t& error_id,
                       clock::time_point now) {
  std::lock_guard<std::mutex> lock(mutex_);
  Slot* s = handle ? find(handle) : nullptr;
  if (!s || is_read(s->job.kind) != read) {
    // Dropped by a stop, cancelled, or not collected in time.
    error_id = CANWORKS_J1939_ERR_CANCELLED;
    return 2;
  }
  if ((s->state == State::Queued || s->state == State::Taken) &&
      now - s->started >= std::chrono::milliseconds(s->job.timeout_ms) + kGrace) {
    s->error_id = CANWORKS_J1939_ERR_TIMEOUT;
    s->state = State::Done;
  }
  if (s->state != State::Done) {
    error_id = 0;
    return 0;
  }
  error_id = s->error_id;
  if (out && read && !s->error_id) *out = s->result;
  s->state = State::Free;
  return error_id ? 2 : 1;
}

void J1939PlcJobs::cancel(uint32_t handle) {
  std::lock_guard<std::mutex> lock(mutex_);
  if (Slot* s = handle ? find(handle) : nullptr) s->state = State::Free;
}

void J1939PlcJobs::take(unsigned network, std::vector<Job>& out) {
  std::lock_guard<std::mutex> lock(mutex_);
  auto now = clock::now();
  size_t first = out.size();
  for (auto& s : slots_) {
    if (s.state == State::Done && now - s.done_at >= kKeepResult) s.state = State::Free;
    if (s.state != State::Queued || s.network != network) continue;
    s.state = State::Taken;
    out.push_back(s.job);
  }
  // Oldest first.
  for (size_t a = first + 1; a < out.size(); ++a)
    for (size_t b = a; b > first && slots_[out[b].handle & (CANWORKS_J1939_SLOTS - 1)].order <
                                        slots_[out[b - 1].handle & (CANWORKS_J1939_SLOTS - 1)].order;
         --b)
      std::swap(out[b], out[b - 1]);
}

void J1939PlcJobs::finish(uint32_t handle, uint16_t error_id, const canworks_j1939_dm* result) {
  std::lock_guard<std::mutex> lock(mutex_);
  Slot* s = find(handle);
  if (!s || s->state != State::Taken) return;
  s->error_id = error_id;
  if (result)
    s->result = *result;
  else
    std::memset(&s->result, 0, sizeof s->result);
  s->done_at = clock::now();
  s->state = State::Done;
}

// --- The C table ---

namespace {

uint32_t api_dm_read_start(uint8_t network, uint8_t source, uint8_t previous, uint32_t timeout_ms,
                           uint16_t* error_id) {
  uint16_t err = 0;
  uint32_t h = J1939PlcJobs::instance().start(
      network, previous ? J1939PlcJobs::Kind::ReadDm2 : J1939PlcJobs::Kind::ReadDm1, source, timeout_ms, err);
  if (error_id) *error_id = err;
  return h;
}

int api_dm_read_poll(uint32_t handle, canworks_j1939_dm* out, uint16_t* error_id) {
  uint16_t err = 0;
  int r = J1939PlcJobs::instance().poll(handle, true, out, err);
  if (error_id) *error_id = err;
  return r;
}

uint32_t api_dm_clear_start(uint8_t network, uint8_t destination, uint8_t previous_only, uint32_t timeout_ms,
                            uint16_t* error_id) {
  uint16_t err = 0;
  uint32_t h = J1939PlcJobs::instance().start(
      network, previous_only ? J1939PlcJobs::Kind::ClearDm3 : J1939PlcJobs::Kind::ClearDm11, destination,
      timeout_ms, err);
  if (error_id) *error_id = err;
  return h;
}

int api_dm_clear_poll(uint32_t handle, uint16_t* error_id) {
  uint16_t err = 0;
  int r = J1939PlcJobs::instance().poll(handle, false, nullptr, err);
  if (error_id) *error_id = err;
  return r;
}

void api_cancel(uint32_t handle) { J1939PlcJobs::instance().cancel(handle); }

const canworks_j1939_api_v1 kApiV1 = {sizeof(canworks_j1939_api_v1), api_dm_read_start, api_dm_read_poll,
                                      api_dm_clear_start, api_dm_clear_poll, api_cancel};

}  // namespace

}  // namespace canopen_plugin

// The plugin exports it as canworks_j1939_api (plugin.cpp).
extern "C" const void* canworks_j1939_api_table(uint32_t version) {
  return version == 1 ? &canopen_plugin::kApiV1 : nullptr;
}
