// mailbox_engine.cpp - see mailbox_engine.h.

#include "mailbox_engine.h"

#include <algorithm>
#include <cstring>

#include "can_plc_api.h"
#if CANWORKS_WITH_CANOPEN
#include "canopen_plc_api.h"
#include "plc_api.h"
#endif
#if CANWORKS_WITH_J1939
#include "j1939_plc_api.h"
#endif

namespace canworks_bridge {

namespace {

const canworks_can_api_v1* can_api() {
  return static_cast<const canworks_can_api_v1*>(canworks_can_api_table(1));
}
#if CANWORKS_WITH_CANOPEN
const canopen_plc_api_v2* co_api() {
  return static_cast<const canopen_plc_api_v2*>(canopen_plugin::plc_api_table(2));
}
#endif
#if CANWORKS_WITH_J1939
const canworks_j1939_api_v2* j1939_api() {
  return static_cast<const canworks_j1939_api_v2*>(canworks_j1939_api_table(2));
}
#endif

uint32_t u32(uint16_t hi, uint16_t lo) { return uint32_t(hi) << 16 | lo; }
void set_u32(uint16_t* r, uint32_t v) {
  r[0] = static_cast<uint16_t>(v >> 16);
  r[1] = static_cast<uint16_t>(v);
}
uint64_t be64(const std::vector<uint8_t>& d, size_t at) {
  uint64_t v = 0;
  for (size_t i = 0; i < 8; ++i) v = v << 8 | (at + i < d.size() ? d[at + i] : 0);
  return v;
}

// ---- CANopen SDO ----
#if CANWORKS_WITH_CANOPEN
class SdoJob : public MbJob {
 public:
  explicit SdoJob(uint32_t h) : handle_(h) {}
  bool poll(MbAnswer& out) override {
    canopen_plc_result res{};
    std::vector<uint8_t> buf(CANOPEN_PLC_MAX_DATA);
    int rc = co_api()->poll(handle_, &res, buf.data(), static_cast<uint32_t>(buf.size()));
    if (rc == 0) return false;
    set_u32(&out.r[0], res.size);
    set_u32(&out.r[2], res.abort_code);
    if (rc == 1) {
      buf.resize(std::min<uint32_t>(res.size, CANOPEN_PLC_MAX_DATA));
      out.data = buf;
      out.error = 0;
    } else {
      out.error = static_cast<uint8_t>(res.error_id ? res.error_id : uint16_t(CANOPEN_PLC_ERR_CANCELLED));
    }
    return true;
  }
  // Still queued or waiting behind another transfer: dropped, never sent.
  void cancel() override { canopen_plugin::PlcRequests::instance().cancel(handle_); }

 private:
  uint32_t handle_;
};
#endif

// ---- CAN frames ----
class CanSendJob : public MbJob {
 public:
  explicit CanSendJob(uint32_t h) : handle_(h) {}
  bool poll(MbAnswer& out) override {
    uint16_t err = 0;
    int rc = can_api()->tx_poll(handle_, &err);
    if (rc == 0) return false;
    out.error = rc == 1 ? 0 : static_cast<uint8_t>(err ? err : uint16_t(CANWORKS_CAN_ERR_CANCELLED));
    return true;
  }
  // Still queued: dropped, never sent.
  void cancel() override { can_api()->tx_cancel(handle_); }

 private:
  uint32_t handle_;
};

// ---- J1939 ----
#if CANWORKS_WITH_J1939
class J1939Job : public MbJob {
 public:
  enum Kind { kSend, kRequest, kDmRead, kDmClear };
  J1939Job(Kind k, uint32_t h) : kind_(k), handle_(h) {}
  ~J1939Job() override {
    if (!ended_) cancel();
  }
  bool poll(MbAnswer& out) override {
    const canworks_j1939_api_v2* t = j1939_api();
    uint16_t err = 0;
    int rc = 0;
    switch (kind_) {
      case kSend: rc = t->send_poll(handle_, &err); break;
      case kRequest: {
        std::unique_ptr<canworks_j1939_msg> m(new canworks_j1939_msg());
        rc = t->request_poll(handle_, m.get(), &err);
        if (rc == 1) {
          out.r[0] = m->source;
          out.r[1] = m->length;
          out.data.assign(m->data, m->data + std::min<uint16_t>(m->length, CANWORKS_J1939_MAX_LENGTH));
        } else if (rc == 2) {
          out.r[2] = m->ack_code;
        }
        break;
      }
      case kDmRead: {
        canworks_j1939_dm dm{};
        rc = t->dm_read_poll(handle_, &dm, &err);
        if (rc == 1) {
          out.r[0] = static_cast<uint16_t>(dm.lamps << 8 | dm.flash);
          out.r[1] = dm.count;
          set_u32(&out.r[2], dm.age_ms);
          for (unsigned i = 0; i < CANWORKS_J1939_DM_CODES; ++i)
            for (int s = 24; s >= 0; s -= 8) out.data.push_back(static_cast<uint8_t>(dm.dtcs[i] >> s));
        }
        break;
      }
      case kDmClear: rc = t->dm_clear_poll(handle_, &err); break;
    }
    if (rc == 0) return false;
    ended_ = true;
    out.error = rc == 1 ? 0 : static_cast<uint8_t>(err ? err : uint16_t(CANWORKS_J1939_ERR_CANCELLED));
    return true;
  }
  void cancel() override {
    ended_ = true;
    const canworks_j1939_api_v2* t = j1939_api();
    if (kind_ == kSend || kind_ == kRequest)
      t->msg_cancel(handle_);
    else
      t->cancel(handle_);
  }

 private:
  Kind kind_;
  uint32_t handle_;
  bool ended_ = false;
};
#endif

}  // namespace

struct EngineMailboxBackend::Rx {
  uint8_t kind = 0;
  uint8_t network = 0;
  uint32_t handle = 0;  // CAN, J1939
#if CANWORKS_WITH_CANOPEN
  uint8_t node = 0;
  canopen_plc_emcy_cursor cursor{};
#endif
};

struct EngineMailboxBackend::Cyclic {
  uint32_t handle = 0;
  canworks_can_frame frame{};
  uint32_t period_us = 0;
};

EngineMailboxBackend::EngineMailboxBackend(unsigned networks) : networks_(networks) {}

EngineMailboxBackend::~EngineMailboxBackend() {
  for (uint32_t i = 0; i < rx_.size(); ++i)
    if (rx_[i]) rx_close(i + 1);
  for (uint32_t i = 0; i < cyc_.size(); ++i)
    if (cyc_[i]) cyc_stop(i + 1);
}

std::unique_ptr<MbJob> EngineMailboxBackend::start(const MbCall& c, MbAnswer& now) {
  const uint16_t* a = c.a;
  switch (c.op) {
    case kOpSdoRead:
    case kOpSdoWrite: {
#if CANWORKS_WITH_CANOPEN
      canopen_plc_request q{};
      q.network = c.network;
      q.node = static_cast<uint8_t>(a[0] >> 8);
      q.subindex = static_cast<uint8_t>(a[0]);
      q.index = a[1];
      q.kind = static_cast<uint8_t>(a[2] >> 8);
      q.size = static_cast<uint8_t>(a[2]);
      q.timeout_ms = a[3];
      q.write = c.op == kOpSdoWrite ? 1 : 0;
      if (q.write) {
        q.data = c.data.data();
        q.length = static_cast<uint32_t>(c.data.size());
      }
      uint16_t err = 0;
      uint32_t h = co_api()->start(&q, &err);
      if (!h) {
        now.error = static_cast<uint8_t>(err ? err : uint16_t(CANOPEN_PLC_ERR_NOT_RUNNING));
        return nullptr;
      }
      return std::unique_ptr<MbJob>(new SdoJob(h));
#else
      now.error = 4;  // CANopen is not running: not in this build
      return nullptr;
#endif
    }
    case kOpCanSend: {
      canworks_can_frame f{};
      f.id = u32(a[0], a[1]);
      f.flags = static_cast<uint8_t>(a[2] >> 8);
      f.dlc = static_cast<uint8_t>(a[2]);
      for (unsigned i = 0; i < 8 && i < c.data.size(); ++i) f.data[i] = c.data[i];
      uint16_t err = 0;
      uint32_t h = can_api()->tx_send(c.network, &f, a[3], &err);
      if (!h) {
        now.error = static_cast<uint8_t>(err ? err : uint16_t(CANWORKS_CAN_ERR_NOT_RUNNING));
        return nullptr;
      }
      return std::unique_ptr<MbJob>(new CanSendJob(h));
    }
#if CANWORKS_WITH_J1939
    case kOpJ1939Send: {
      uint16_t err = 0;
      uint32_t h = j1939_api()->send_start(c.network, u32(a[0], a[1]), static_cast<uint8_t>(a[2] >> 8),
                                           static_cast<uint8_t>(a[2]), c.data.data(),
                                           static_cast<uint16_t>(c.data.size()), a[4], &err);
      if (!h) {
        now.error = static_cast<uint8_t>(err ? err : 1);
        return nullptr;
      }
      return std::unique_ptr<MbJob>(new J1939Job(J1939Job::kSend, h));
    }
    case kOpJ1939Request: {
      uint16_t err = 0;
      uint32_t h = j1939_api()->request_start(c.network, u32(a[0], a[1]), static_cast<uint8_t>(a[2]), a[3], &err);
      if (!h) {
        now.error = static_cast<uint8_t>(err ? err : 1);
        return nullptr;
      }
      return std::unique_ptr<MbJob>(new J1939Job(J1939Job::kRequest, h));
    }
    case kOpDmRead: {
      uint16_t err = 0;
      uint32_t h = j1939_api()->dm_read_start(c.network, static_cast<uint8_t>(a[0]), a[1] ? 1 : 0, a[2], &err);
      if (!h) {
        now.error = static_cast<uint8_t>(err ? err : 1);
        return nullptr;
      }
      return std::unique_ptr<MbJob>(new J1939Job(J1939Job::kDmRead, h));
    }
    case kOpDmClear: {
      uint16_t err = 0;
      uint32_t h = j1939_api()->dm_clear_start(c.network, static_cast<uint8_t>(a[0]), a[1] ? 1 : 0, a[2], &err);
      if (!h) {
        now.error = static_cast<uint8_t>(err ? err : 1);
        return nullptr;
      }
      return std::unique_ptr<MbJob>(new J1939Job(J1939Job::kDmClear, h));
    }
    case kOpFindEcu: {
      canworks_j1939_ecu_found found{};
      uint16_t err = 0;
      if (j1939_api()->find_ecu(c.network, be64(c.data, 0), be64(c.data, 8), &found, &err) != 0) {
        now.error = static_cast<uint8_t>(err ? err : 1);
        return nullptr;
      }
      now.r[0] = found.found;
      now.r[1] = found.address;
      now.r[2] = found.count;
      for (int s = 56; s >= 0; s -= 8) now.data.push_back(static_cast<uint8_t>(found.name >> s));
      return nullptr;
    }
#else
    case kOpJ1939Send:
    case kOpJ1939Request:
    case kOpDmRead:
    case kOpDmClear:
    case kOpFindEcu: now.error = 10; return nullptr;  // not a J1939 network: not in this build
#endif
    default: now.error = 3; return nullptr;
  }
}

uint32_t EngineMailboxBackend::rx_open(const RxSpec& s, uint8_t& error) {
  std::unique_ptr<Rx> rx(new Rx);
  rx->kind = s.kind;
  rx->network = s.network;
  uint16_t err = 0;
  switch (s.kind) {
    case kRxCan:
      rx->handle = can_api()->rx_open(s.network, s.id, s.mask, s.flags & CANWORKS_CAN_EXTENDED, s.depth, &err);
      if (!rx->handle) {
        error = static_cast<uint8_t>(err ? err : uint16_t(CANWORKS_CAN_ERR_NOT_RUNNING));
        return 0;
      }
      break;
    case kRxJ1939:
#if CANWORKS_WITH_J1939
      rx->handle = j1939_api()->rx_open(s.network, s.id, static_cast<uint8_t>(s.mask), s.flags, s.depth, &err);
      if (!rx->handle) {
        error = static_cast<uint8_t>(err ? err : uint16_t(CANWORKS_J1939_ERR_NOT_RUNNING));
        return 0;
      }
      break;
#else
      error = 10;
      return 0;
#endif
    case kRxEmcy: {
#if CANWORKS_WITH_CANOPEN
      rx->node = static_cast<uint8_t>(s.mask);
      int rc = co_api()->emcy_begin(s.network, rx->node, s.flags & kRxEmcySkipOld ? 1 : 0, &rx->cursor);
      if (rc < 0) {
        error = static_cast<uint8_t>(-rc);
        return 0;
      }
      break;
#else
      error = 4;
      return 0;
#endif
    }
    default: error = 3; return 0;
  }
  for (uint32_t i = 0; i < rx_.size(); ++i)
    if (!rx_[i]) {
      rx_[i] = std::move(rx);
      return i + 1;
    }
  rx_.push_back(std::move(rx));
  return static_cast<uint32_t>(rx_.size());
}

int EngineMailboxBackend::rx_read(uint32_t handle, RxRecord& rec, uint8_t& error) {
  if (!handle || handle > rx_.size() || !rx_[handle - 1]) {
    error = 8;
    return -1;
  }
  Rx& rx = *rx_[handle - 1];
  rec = RxRecord();
  switch (rx.kind) {
    case kRxCan: {
      canworks_can_frame f{};
      canworks_can_rx_info info{};
      int rc = can_api()->rx_read(rx.handle, &f, &info);
      if (rc < 0) {
        error = static_cast<uint8_t>(-rc);
        return -1;
      }
      if (rc == 0) return 0;
      rec.queued = info.queued;
      rec.dropped = info.dropped;
      if (info.overflow) rec.flags |= kRecOverflow;
      rec.time_us = f.time_us;
      rec.id = f.id;
      rec.can_flags = f.flags;
      rec.dlc = f.dlc;
      rec.data.assign(f.data, f.data + 8);
      return 1;
    }
#if CANWORKS_WITH_J1939
    case kRxJ1939: {
      std::unique_ptr<canworks_j1939_msg> m(new canworks_j1939_msg());
      canworks_j1939_rx_info info{};
      int rc = j1939_api()->rx_read(rx.handle, m.get(), &info);
      if (rc < 0) {
        error = static_cast<uint8_t>(-rc);
        return -1;
      }
      if (rc == 0) return 0;
      rec.queued = info.queued;
      rec.dropped = info.dropped;
      if (info.overflow) rec.flags |= kRecOverflow;
      rec.time_us = m->time_us;
      rec.pgn = m->pgn;
      rec.source = m->source;
      rec.destination = m->destination;
      rec.priority = m->priority;
      rec.data.assign(m->data, m->data + std::min<uint16_t>(m->length, CANWORKS_J1939_MAX_LENGTH));
      return 1;
    }
#endif
#if CANWORKS_WITH_CANOPEN
    case kRxEmcy: {
      canopen_plc_emcy e{};
      canopen_plc_emcy_info info{};
      int rc = co_api()->emcy_read(rx.network, rx.node, &rx.cursor, &e, &info);
      if (rc == -CANOPEN_PLC_ERR_CANCELLED) {
        // A new CANopen session: the block shows ERROR_ID 8 once and goes on.
        rec.flags |= kRecRestart;
        rec.time_us = 0;
        rec.data.assign(5, 0);
        return 1;
      }
      if (rc < 0) {
        error = static_cast<uint8_t>(-rc);
        return -1;
      }
      if (rc == 0) return 0;
      rec.queued = info.queued;
      rec.dropped = info.lost;
      if (info.lost) rec.flags |= kRecOverflow;
      rec.time_us = e.time_us;
      rec.node = e.node;
      rec.error_register = e.error_register;
      rec.error_code = e.error_code;
      rec.data.assign(e.msef, e.msef + 5);
      return 1;
    }
#endif
    default: error = 8; return -1;
  }
}

void EngineMailboxBackend::rx_close(uint32_t handle) {
  if (!handle || handle > rx_.size() || !rx_[handle - 1]) return;
  Rx& rx = *rx_[handle - 1];
  if (rx.kind == kRxCan) can_api()->rx_close(rx.handle);
#if CANWORKS_WITH_J1939
  if (rx.kind == kRxJ1939) j1939_api()->rx_close(rx.handle);
#endif
  rx_[handle - 1].reset();
}

namespace {
canworks_can_frame can_frame(const CyclicFrame& f) {
  canworks_can_frame c{};
  c.id = f.id;
  c.flags = f.flags & CANWORKS_CAN_EXTENDED;
  c.dlc = f.dlc;
  std::memcpy(c.data, f.data, 8);
  return c;
}
}  // namespace

uint32_t EngineMailboxBackend::cyc_start(uint8_t network, const CyclicFrame& f, uint8_t& error) {
  std::unique_ptr<Cyclic> c(new Cyclic);
  c->frame = can_frame(f);
  c->period_us = f.period_ms * 1000u;
  uint16_t err = 0;
  c->handle = can_api()->cyc_start(network, &c->frame, c->period_us, &err);
  if (!c->handle) {
    error = static_cast<uint8_t>(err ? err : uint16_t(CANWORKS_CAN_ERR_NOT_RUNNING));
    return 0;
  }
  for (uint32_t i = 0; i < cyc_.size(); ++i)
    if (!cyc_[i]) {
      cyc_[i] = std::move(c);
      return i + 1;
    }
  cyc_.push_back(std::move(c));
  return static_cast<uint32_t>(cyc_.size());
}

bool EngineMailboxBackend::cyc_update(uint32_t handle, const CyclicFrame* f, uint32_t& count, uint8_t& error) {
  if (!handle || handle > cyc_.size() || !cyc_[handle - 1]) {
    error = CANWORKS_CAN_ERR_CANCELLED;
    return false;
  }
  Cyclic& c = *cyc_[handle - 1];
  if (f) {
    c.frame = can_frame(*f);
    c.period_us = f->period_ms * 1000u;
  }
  uint16_t err = 0;
  int rc = can_api()->cyc_update(c.handle, &c.frame, c.period_us, &count, &err);
  error = static_cast<uint8_t>(err);
  if (rc != 0) {
    cyc_[handle - 1].reset();
    if (!error) error = CANWORKS_CAN_ERR_CANCELLED;
    return false;
  }
  return true;
}

void EngineMailboxBackend::cyc_stop(uint32_t handle) {
  if (!handle || handle > cyc_.size() || !cyc_[handle - 1]) return;
  can_api()->cyc_stop(cyc_[handle - 1]->handle);
  cyc_[handle - 1].reset();
}

bool EngineMailboxBackend::net_info(unsigned network, NetInfo& out) {
  if (network >= networks_) return false;
  canworks_can_bus_info b{};
  uint16_t err = 0;
  if (can_api()->bus_info(static_cast<uint8_t>(network), &b, &err) == 0) {
    out.can_state = b.state;
    out.bus_load = b.bus_load;
    out.tx_errors = b.tx_errors;
    out.rx_errors = b.rx_errors;
    out.bus_off_count = b.bus_off_count;
    out.rx_count = b.rx_count;
    out.tx_count = b.tx_count;
    out.error_frames = b.error_frames;
  }
#if CANWORKS_WITH_J1939
  canworks_j1939_ecu_info e{};
  err = 0;
  if (j1939_api()->ecu_info(static_cast<uint8_t>(network), &e, &err) == 0) {
    out.j1939 = true;
    out.j1939_state = e.state;
    out.address = e.address;
    out.name = e.name;
    out.ecu_count = e.ecu_count;
  } else {
    out.j1939_error = static_cast<uint8_t>(err ? err : uint16_t(CANWORKS_J1939_ERR_NOT_RUNNING));
  }
#endif
  return true;
}

}  // namespace canworks_bridge
