// plc_api.cpp - request slots for the PLC program's SDO function blocks.

#include "plc_api.h"

#include <algorithm>

#include "plc_emcy.h"
#include <cstring>

namespace canopen_plugin {

constexpr std::chrono::seconds PlcRequests::kKeepResult;
constexpr uint32_t PlcRequests::kDefaultTimeoutMs;
constexpr std::chrono::seconds PlcRequests::kTakenGrace;

namespace {

constexpr uint32_t kIndexBits = 6;  // 64 slots
static_assert((1u << kIndexBits) == CANOPEN_PLC_SLOTS, "handle layout");
constexpr uint32_t kSeqMask = (1u << (32 - kIndexBits)) - 1;

}  // namespace

PlcRequests& PlcRequests::instance() {
  static PlcRequests requests;
  return requests;
}

uint16_t PlcRequests::validate(const canopen_plc_request& r) const {
  if (r.network >= 32 || !(sdo_networks_.load(std::memory_order_acquire) >> r.network & 1u) || r.node < 1 ||
      r.node > 127)
    return CANOPEN_PLC_ERR_INPUT;
  if (r.kind > CANOPEN_PLC_BYTES) return CANOPEN_PLC_ERR_INPUT;
  if (!r.write) return 0;
  if (r.length > CANOPEN_PLC_MAX_DATA || (r.length && !r.data)) return CANOPEN_PLC_ERR_INPUT;
  switch (r.kind) {
    case CANOPEN_PLC_INT:
      if (r.length != 8 || r.size > 8) return CANOPEN_PLC_ERR_INPUT;
      break;
    case CANOPEN_PLC_REAL:
      if (r.length != 8 || (r.size != 0 && r.size != 4 && r.size != 8)) return CANOPEN_PLC_ERR_INPUT;
      break;
    default:
      break;
  }
  return 0;
}

uint32_t PlcRequests::start(const canopen_plc_request& req, uint16_t& error_id) {
  error_id = 0;
  if (!running()) {
    error_id = CANOPEN_PLC_ERR_NOT_RUNNING;
    return 0;
  }
  if ((error_id = validate(req)) != 0) return 0;
  std::lock_guard<std::mutex> lock(mutex_);
  if (!running()) {
    error_id = CANOPEN_PLC_ERR_NOT_RUNNING;
    return 0;
  }
  for (uint32_t i = 0; i < CANOPEN_PLC_SLOTS; ++i) {
    Slot& s = slots_[i];
    if (s.state != State::Free) continue;
    s.seq = next_seq_;
    next_seq_ = (next_seq_ + 1) & kSeqMask;
    if (next_seq_ == 0) next_seq_ = 1;
    s.order = next_order_++;
    s.req = req;
    s.req.data = nullptr;
    if (!s.req.timeout_ms) s.req.timeout_ms = kDefaultTimeoutMs;
    s.length = req.write ? req.length : 0;
    if (s.length) std::memcpy(s.buf, req.data, s.length);
    s.res = canopen_plc_result{};
    s.started = clock::now();
    s.state = State::Queued;
    return (s.seq << kIndexBits) | i;
  }
  error_id = CANOPEN_PLC_ERR_BUSY;
  return 0;
}

PlcRequests::Slot* PlcRequests::find(uint32_t handle) {
  Slot& s = slots_[handle & (CANOPEN_PLC_SLOTS - 1)];
  if (s.state == State::Free || s.seq != handle >> kIndexBits) return nullptr;
  return &s;
}

int PlcRequests::poll(uint32_t handle, canopen_plc_result* res, uint8_t* data, uint32_t cap,
                      clock::time_point now) {
  std::lock_guard<std::mutex> lock(mutex_);
  Slot* s = handle ? find(handle) : nullptr;
  if (!s) {
    // Dropped by a stop or a restart, or not collected in time.
    if (res) *res = canopen_plc_result{CANOPEN_PLC_ERR_CANCELLED, 0, 0};
    return 2;
  }
  if (s->state == State::Queued &&
      now - s->started >= std::chrono::milliseconds(s->req.timeout_ms)) {
    // No network took it in time (the CAN interface is not up).
    s->res = canopen_plc_result{CANOPEN_PLC_ERR_TIMEOUT, 0x05040000u, 0};
    s->state = State::Done;
  } else if (s->state == State::Taken &&
             now - s->started >= std::chrono::milliseconds(s->req.timeout_ms) + kTakenGrace) {
    // Taken, and the network never answered: a backstop, so the slot frees.
    s->res = canopen_plc_result{CANOPEN_PLC_ERR_TIMEOUT, 0x05040000u, 0};
    s->state = State::Done;
  }
  if (s->state != State::Done) return 0;
  if (res) *res = s->res;
  if (data && !s->req.write) std::memcpy(data, s->buf, std::min<uint32_t>(cap, s->length));
  s->state = State::Free;
  return s->res.error_id ? 2 : 1;
}

void PlcRequests::open(uint32_t sdo_networks) {
  std::lock_guard<std::mutex> lock(mutex_);
  for (auto& s : slots_) s.state = State::Free;
  sdo_networks_.store(sdo_networks, std::memory_order_release);
  running_.store(true, std::memory_order_release);
}

void PlcRequests::close() {
  std::lock_guard<std::mutex> lock(mutex_);
  running_.store(false, std::memory_order_release);
  for (auto& s : slots_) s.state = State::Free;
}

void PlcRequests::take(unsigned network, std::vector<Job>& out) {
  std::lock_guard<std::mutex> lock(mutex_);
  size_t first = out.size();
  for (uint32_t i = 0; i < CANOPEN_PLC_SLOTS; ++i) {
    Slot& s = slots_[i];
    if (s.state != State::Queued || s.req.network != network) continue;
    s.state = State::Taken;
    Job j;
    j.handle = (s.seq << kIndexBits) | i;
    j.req = s.req;
    if (s.req.write) j.data.assign(s.buf, s.buf + s.length);
    j.deadline = s.started + std::chrono::milliseconds(s.req.timeout_ms);
    out.push_back(std::move(j));
  }
  // Oldest first: a node's requests run in the order they were started.
  std::sort(out.begin() + static_cast<long>(first), out.end(), [this](const Job& a, const Job& b) {
    return slots_[a.handle & (CANOPEN_PLC_SLOTS - 1)].order < slots_[b.handle & (CANOPEN_PLC_SLOTS - 1)].order;
  });
}

void PlcRequests::finish(uint32_t handle, uint16_t error_id, uint32_t abort_code, const uint8_t* data, size_t size) {
  std::lock_guard<std::mutex> lock(mutex_);
  Slot* s = find(handle);
  if (!s || s->state != State::Taken) return;
  s->res.error_id = error_id;
  s->res.abort_code = abort_code;
  s->res.size = static_cast<uint32_t>(size);
  s->length = 0;
  if (!error_id && data && !s->req.write) {
    s->length = static_cast<uint32_t>(std::min<size_t>(size, CANOPEN_PLC_MAX_DATA));
    std::memcpy(s->buf, data, s->length);
  }
  s->done_at = clock::now();
  s->state = State::Done;
}

void PlcRequests::expire(clock::time_point now) {
  std::lock_guard<std::mutex> lock(mutex_);
  for (auto& s : slots_)
    if (s.state == State::Done && now - s.done_at >= kKeepResult) s.state = State::Free;
}

void PlcRequests::cancel_taken(unsigned network) {
  std::lock_guard<std::mutex> lock(mutex_);
  for (auto& s : slots_)
    if (s.state == State::Taken && s.req.network == network) s.state = State::Free;
}

void PlcRequests::note_unknown_version(uint32_t version) {
  uint32_t none = 0;
  unknown_version_.compare_exchange_strong(none, version);
}

uint32_t PlcRequests::take_unknown_version() {
  uint32_t v = unknown_version_.load();
  if (!v || unknown_logged_) return 0;
  unknown_logged_ = true;
  return v;
}

namespace {

uint32_t api_start(const canopen_plc_request* req, uint16_t* error_id) {
  uint16_t err = CANOPEN_PLC_ERR_INPUT;
  uint32_t h = req ? PlcRequests::instance().start(*req, err) : 0;
  if (error_id) *error_id = err;
  return h;
}

int api_poll(uint32_t handle, canopen_plc_result* res, uint8_t* data, uint32_t cap) {
  return PlcRequests::instance().poll(handle, res, data, cap);
}

// EMCY reads (CO_RECV_EMCY): CANopen must run and the network must be one of
// its master networks.
int emcy_check(uint8_t network, uint8_t node) {
  const PlcRequests& r = PlcRequests::instance();
  if (!r.running()) return -CANOPEN_PLC_ERR_NOT_RUNNING;
  if (!r.takes_network(network) || network >= EmcyQueues::kNetworks || node > 127) return -CANOPEN_PLC_ERR_INPUT;
  return 0;
}

int api_emcy_begin(uint8_t network, uint8_t node, uint8_t skip_old, canopen_plc_emcy_cursor* cursor) {
  if (int e = emcy_check(network, node)) return e;
  if (!cursor) return -CANOPEN_PLC_ERR_INPUT;
  EmcyQueues::instance().begin(network, skip_old != 0, *cursor);
  return 0;
}

int api_emcy_read(uint8_t network, uint8_t node, canopen_plc_emcy_cursor* cursor, canopen_plc_emcy* entry,
                  canopen_plc_emcy_info* info) {
  if (int e = emcy_check(network, node)) return e;
  if (!cursor || !entry || !info) return -CANOPEN_PLC_ERR_INPUT;
  return EmcyQueues::instance().read(network, node, *cursor, *entry, *info);
}

const canopen_plc_api_v1 kApiV1 = {sizeof(canopen_plc_api_v1), api_start, api_poll};
const canopen_plc_api_v2 kApiV2 = {sizeof(canopen_plc_api_v2), api_start, api_poll, api_emcy_begin, api_emcy_read};

}  // namespace

const void* plc_api_table(uint32_t version) {
  if (version == 1) return &kApiV1;
  if (version == 2) return &kApiV2;
  PlcRequests::instance().note_unknown_version(version);
  return nullptr;
}

}  // namespace canopen_plugin
