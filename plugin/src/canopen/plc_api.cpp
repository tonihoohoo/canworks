// plc_api.cpp - request slots for the PLC program's SDO function blocks.

#include "plc_api.h"

#include <algorithm>

#include "plc_emcy.h"
#include <cstring>

namespace canopen_plugin {

constexpr std::chrono::seconds PlcRequests::kKeepResult;
constexpr uint32_t PlcRequests::kDefaultTimeoutMs;
constexpr std::chrono::seconds PlcRequests::kTakenGrace;
constexpr std::chrono::seconds PlcRequests::kNmtTakeLimit;
constexpr uint32_t PlcRequests::kConfigured;
constexpr uint32_t PlcRequests::kStarted;
constexpr unsigned PlcRequests::kSnapshotNetworks;

namespace {

constexpr uint32_t kIndexBits = 6;  // 64 slots
static_assert((1u << kIndexBits) == CANOPEN_PLC_SLOTS, "handle layout");
constexpr uint32_t kSeqMask = (1u << (32 - kIndexBits)) - 1;
// NMT handles: the same layout, slot index in the low bits (16 slots, so
// the upper two of the six bits are always 0).
static_assert(CANOPEN_PLC_NMT_SLOTS <= CANOPEN_PLC_SLOTS, "NMT handle layout");

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
  for (auto& s : nmt_slots_) s.state = State::Free;
  for (auto& m : master_ids_) m.store(0, std::memory_order_relaxed);
  // The snapshot is not cleared here: the networks start before the
  // requests open (Engine::start) and publish theirs at Network::Start.
  sdo_networks_.store(sdo_networks, std::memory_order_release);
  running_.store(true, std::memory_order_release);
}

void PlcRequests::close() {
  std::lock_guard<std::mutex> lock(mutex_);
  running_.store(false, std::memory_order_release);
  for (auto& s : slots_) s.state = State::Free;
  for (auto& s : nmt_slots_) s.state = State::Free;
  for (unsigned n = 0; n < kSnapshotNetworks; ++n)
    for (auto& w : snapshot_[n]) w.store(0, std::memory_order_relaxed);
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
  for (auto& s : nmt_slots_)
    if (s.state == State::Done && now - s.done_at >= kKeepResult) s.state = State::Free;
}

void PlcRequests::cancel_taken(unsigned network) {
  std::lock_guard<std::mutex> lock(mutex_);
  for (auto& s : slots_)
    if (s.state == State::Taken && s.req.network == network) s.state = State::Free;
  for (auto& s : nmt_slots_)
    if (s.state == State::Taken && s.req.network == network) s.state = State::Free;
}

// ---------------------------------------------------------------------------
// NMT blocks

uint16_t PlcRequests::validate_nmt(const canopen_plc_nmt_request& r) const {
  if (r.network >= kSnapshotNetworks || !(sdo_networks_.load(std::memory_order_acquire) >> r.network & 1u))
    return CANOPEN_PLC_ERR_INPUT;
  switch (r.op) {
    case CANOPEN_PLC_NMT_NODE: {
      if (r.node > 127) return CANOPEN_PLC_ERR_INPUT;
      uint8_t master = master_ids_[r.network].load(std::memory_order_acquire);
      if (r.node != 0 && r.node == master) return CANOPEN_PLC_ERR_INPUT;
      switch (r.command) {
        case CANOPEN_PLC_NMT_CS_START:
        case CANOPEN_PLC_NMT_CS_STOP:
        case CANOPEN_PLC_NMT_CS_PREOP:
        case CANOPEN_PLC_NMT_CS_RESET_NODE:
        case CANOPEN_PLC_NMT_CS_RESET_COMM:
          return 0;
        default:
          return CANOPEN_PLC_ERR_INPUT;
      }
    }
    case CANOPEN_PLC_NMT_START:
      return 0;
    case CANOPEN_PLC_NMT_STOP:
      return r.command == CANOPEN_PLC_NMT_NODES_DEFAULT || r.command == CANOPEN_PLC_NMT_CS_STOP ||
                     r.command == CANOPEN_PLC_NMT_CS_PREOP || r.command == CANOPEN_PLC_NMT_NODES_NONE
                 ? 0
                 : CANOPEN_PLC_ERR_INPUT;
    default:
      return CANOPEN_PLC_ERR_INPUT;
  }
}

uint32_t PlcRequests::start_nmt(const canopen_plc_nmt_request& req, uint16_t& error_id) {
  error_id = 0;
  if (!running()) {
    error_id = CANOPEN_PLC_ERR_NOT_RUNNING;
    return 0;
  }
  if ((error_id = validate_nmt(req)) != 0) return 0;
  std::lock_guard<std::mutex> lock(mutex_);
  if (!running()) {
    error_id = CANOPEN_PLC_ERR_NOT_RUNNING;
    return 0;
  }
  for (uint32_t i = 0; i < CANOPEN_PLC_NMT_SLOTS; ++i) {
    NmtSlot& s = nmt_slots_[i];
    if (s.state != State::Free) continue;
    s.seq = next_seq_;
    next_seq_ = (next_seq_ + 1) & kSeqMask;
    if (next_seq_ == 0) next_seq_ = 1;
    s.order = next_order_++;
    s.req = req;
    s.error_id = 0;
    s.started = clock::now();
    s.state = State::Queued;
    return (s.seq << kIndexBits) | i;
  }
  error_id = CANOPEN_PLC_ERR_BUSY;
  return 0;
}

PlcRequests::NmtSlot* PlcRequests::find_nmt(uint32_t handle) {
  uint32_t i = handle & ((1u << kIndexBits) - 1);
  if (i >= CANOPEN_PLC_NMT_SLOTS) return nullptr;
  NmtSlot& s = nmt_slots_[i];
  if (s.state == State::Free || s.seq != handle >> kIndexBits) return nullptr;
  return &s;
}

int PlcRequests::poll_nmt(uint32_t handle, uint16_t& error_id, clock::time_point now) {
  std::lock_guard<std::mutex> lock(mutex_);
  NmtSlot* s = handle ? find_nmt(handle) : nullptr;
  if (!s) {
    error_id = CANOPEN_PLC_ERR_CANCELLED;  // dropped by a stop or a restart
    return 2;
  }
  if (s->state != State::Done && s->req.op == CANOPEN_PLC_NMT_START && s->req.timeout_ms &&
      now - s->started >= std::chrono::milliseconds(s->req.timeout_ms)) {
    // The master is not OPERATIONAL in time; the start stays requested.
    s->error_id = CANOPEN_PLC_ERR_TIMEOUT;
    s->state = State::Done;
  } else if (s->state == State::Queued && now - s->started >= kNmtTakeLimit) {
    s->error_id = CANOPEN_PLC_ERR_NOT_RUNNING;  // no bus session took it
    s->state = State::Done;
  }
  if (s->state != State::Done) return 0;
  error_id = s->error_id;
  s->state = State::Free;
  return error_id ? 2 : 1;
}

void PlcRequests::take_nmt(unsigned network, std::vector<NmtJob>& out) {
  std::lock_guard<std::mutex> lock(mutex_);
  size_t first = out.size();
  for (uint32_t i = 0; i < CANOPEN_PLC_NMT_SLOTS; ++i) {
    NmtSlot& s = nmt_slots_[i];
    if (s.state != State::Queued || s.req.network != network) continue;
    s.state = State::Taken;
    NmtJob j;
    j.handle = (s.seq << kIndexBits) | i;
    j.req = s.req;
    out.push_back(j);
  }
  std::sort(out.begin() + static_cast<long>(first), out.end(), [this](const NmtJob& a, const NmtJob& b) {
    return nmt_slots_[a.handle & (CANOPEN_PLC_NMT_SLOTS - 1)].order <
           nmt_slots_[b.handle & (CANOPEN_PLC_NMT_SLOTS - 1)].order;
  });
}

void PlcRequests::finish_nmt(uint32_t handle, uint16_t error_id) {
  std::lock_guard<std::mutex> lock(mutex_);
  NmtSlot* s = find_nmt(handle);
  if (!s || s->state != State::Taken) return;
  s->error_id = error_id;
  s->done_at = clock::now();
  s->state = State::Done;
}

void PlcRequests::set_master_node(unsigned network, uint8_t node_id) {
  if (network < kSnapshotNetworks) master_ids_[network].store(node_id, std::memory_order_release);
}

void PlcRequests::clear_snapshot(unsigned network) {
  if (network >= kSnapshotNetworks) return;
  for (auto& w : snapshot_[network]) w.store(0, std::memory_order_release);
}

void PlcRequests::publish_node(unsigned network, unsigned node, uint8_t state, uint8_t held, uint8_t boot_error) {
  if (network >= kSnapshotNetworks || node < 1 || node > 127) return;
  snapshot_[network][node].store(pack_node(state, held, boot_error), std::memory_order_release);
}

void PlcRequests::publish_master(unsigned network, uint8_t state, bool started) {
  if (network >= kSnapshotNetworks) return;
  snapshot_[network][0].store((started ? kStarted : 0u) | state, std::memory_order_release);
}

uint16_t PlcRequests::get_state(uint8_t network, uint8_t node, canopen_plc_nmt_state& out) const {
  out = canopen_plc_nmt_state{};
  if (!running()) return CANOPEN_PLC_ERR_NOT_RUNNING;
  if (network >= kSnapshotNetworks || !(sdo_networks_.load(std::memory_order_acquire) >> network & 1u) ||
      node > 127)
    return CANOPEN_PLC_ERR_INPUT;
  uint32_t m = snapshot_[network][0].load(std::memory_order_acquire);
  out.master_state = static_cast<uint8_t>(m);
  out.started = (m & kStarted) ? 1 : 0;
  if (!node) return 0;
  uint32_t w = snapshot_[network][node].load(std::memory_order_acquire);
  if (!(w & kConfigured)) return 0;  // not in the configuration: all 0
  out.configured = 1;
  out.state = static_cast<uint8_t>(w);
  out.held = static_cast<uint8_t>(w >> 8);
  out.boot_error = static_cast<uint8_t>(w >> 16);
  return 0;
}

void PlcRequests::note_unknown_nmt_version(uint32_t version) {
  uint32_t none = 0;
  unknown_nmt_version_.compare_exchange_strong(none, version);
}

uint32_t PlcRequests::take_unknown_nmt_version() {
  uint32_t v = unknown_nmt_version_.load();
  if (!v || unknown_nmt_logged_) return 0;
  unknown_nmt_logged_ = true;
  return v;
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

uint32_t nmt_start(const canopen_plc_nmt_request* req, uint16_t* error_id) {
  uint16_t err = CANOPEN_PLC_ERR_INPUT;
  uint32_t h = req ? PlcRequests::instance().start_nmt(*req, err) : 0;
  if (error_id) *error_id = err;
  return h;
}

int nmt_poll(uint32_t handle, uint16_t* error_id) {
  uint16_t err = 0;
  int st = PlcRequests::instance().poll_nmt(handle, err);
  if (error_id) *error_id = err;
  return st;
}

uint16_t nmt_get_state(uint8_t network, uint8_t node, canopen_plc_nmt_state* out) {
  canopen_plc_nmt_state s{};
  uint16_t err = PlcRequests::instance().get_state(network, node, s);
  if (out) *out = s;
  return err;
}

const canopen_plc_nmt_api_v1 kNmtApiV1 = {sizeof(canopen_plc_nmt_api_v1), nmt_start, nmt_poll, nmt_get_state};

}  // namespace

const void* plc_api_table(uint32_t version) {
  if (version == 1) return &kApiV1;
  if (version == 2) return &kApiV2;
  PlcRequests::instance().note_unknown_version(version);
  return nullptr;
}

const void* plc_nmt_api_table(uint32_t version) {
  if (version == CANOPEN_PLC_NMT_API_VERSION) return &kNmtApiV1;
  PlcRequests::instance().note_unknown_nmt_version(version);
  return nullptr;
}

}  // namespace canopen_plugin
