// queue_client.hpp - a small client of the engine's SDO and NMT request
// queues (plc_api.h) for the simulator tests.
//
// The PLC function blocks that used the queues went with the OpenPLC plugin;
// the queues stay for the bridge (its SDO bridge registers) and for the
// bridge's mailboxes. These stand-ins keep the blocks' handshake (PLCopen
// style: a rising EXECUTE starts, BUSY while it runs, DONE or ERROR until
// EXECUTE drops) and their pin names, so a test's fake program calls them
// every scan the way a program called the blocks. Integer SDO transfers only.

#ifndef QUEUE_CLIENT_HPP
#define QUEUE_CLIENT_HPP

#include <cstdint>

#include "canopen_plc_api.h"
#include "canopen_plc_nmt_api.h"
#include "plc_api.h"

namespace queue_client {

// An output: reads like the value, and get() as the blocks' pins did.
template <class T>
struct Out {
  T v{};
  Out& operator=(T x) {
    v = x;
    return *this;
  }
  operator T() const { return v; }
  T get() const { return v; }
};

// The handshake of one instance.
struct Handshake {
  bool prev = false;
  int phase = 0;  // 0 idle, 1 busy, 2 ended
  uint32_t handle = 0;
  // True on a rising EXECUTE (when not busy); clears DONE and ERROR once
  // the result was shown and EXECUTE is FALSE.
  template <class B>
  bool begin(B& b) {
    bool rising = b.EXECUTE && !prev;
    prev = b.EXECUTE;
    if (phase == 2 && !b.EXECUTE) {
      b.DONE = false;
      b.ERROR = false;
      phase = 0;
    }
    if (!rising || phase == 1) return false;
    b.DONE = false;
    b.ERROR = false;
    b.ERROR_ID = 0;
    return true;
  }
  template <class B>
  void started(B& b, uint32_t h, uint16_t err) {
    handle = h;
    b.BUSY = h != 0;
    b.ERROR = h == 0;
    b.ERROR_ID = h ? 0 : err;
    phase = h ? 1 : 2;
  }
  template <class B>
  void ended(B& b, bool ok, uint16_t err) {
    b.BUSY = false;
    handle = 0;
    phase = 2;
    b.DONE = ok;
    b.ERROR = !ok;
    b.ERROR_ID = ok ? 0 : err;
  }
};

inline uint32_t timeout_ms(int64_t ns) {
  if (ns <= 0) return 0;
  int64_t ms = (ns + 999999) / 1000000;
  return ms > 3600000 ? 3600000u : static_cast<uint32_t>(ms);
}

struct SdoCommon {
  bool EXECUTE = false;
  uint8_t NETWORK = 0, NODE = 0, SUBINDEX = 0;
  uint16_t INDEX = 0;
  int64_t TIMEOUT = 0;  // ns, 0: the queue's default
  Out<bool> BUSY, DONE, ERROR;
  Out<uint16_t> ERROR_ID;
  Out<uint32_t> ABORT_CODE;
  Handshake hs;
};

struct CO_SDO_READ_INST : SdoCommon {
  Out<uint64_t> DATA;
  Out<uint16_t> SIZE;
};

struct CO_SDO_WRITE_INST : SdoCommon {
  uint64_t DATA = 0;
  uint8_t SIZE = 0;  // 0: the object's own size
};

inline void sdo_call(SdoCommon& b, bool write, uint64_t wdata, uint8_t wsize, Out<uint64_t>* rdata,
                     Out<uint16_t>* rsize) {
  using canopen_plugin::PlcRequests;
  if (b.hs.begin(b)) {
    b.ABORT_CODE = 0;
    if (rdata) *rdata = 0;
    if (rsize) *rsize = 0;
    canopen_plc_request q{};
    q.network = b.NETWORK;
    q.node = b.NODE;
    q.index = b.INDEX;
    q.subindex = b.SUBINDEX;
    q.write = write ? 1 : 0;
    q.kind = CANOPEN_PLC_INT;
    q.timeout_ms = timeout_ms(b.TIMEOUT);
    uint8_t data[8];
    for (int i = 0; i < 8; ++i) data[i] = static_cast<uint8_t>(wdata >> (8 * i));
    if (write) {
      q.data = data;
      q.length = 8;
      q.size = wsize;
    }
    uint16_t err = 0;
    uint32_t h = PlcRequests::instance().start(q, err);
    b.hs.started(b, h, err);
  }
  if (b.hs.phase != 1) return;
  canopen_plc_result res{};
  uint8_t reply[9] = {};
  int st = PlcRequests::instance().poll(b.hs.handle, &res, reply, sizeof reply);
  if (st == 0) return;
  uint16_t err = st == 2 ? res.error_id : 0;
  if (!err && rdata) {
    if (res.size > 8) {
      err = CANOPEN_PLC_ERR_TOO_BIG;
    } else {
      uint64_t v = 0;
      for (unsigned i = 0; i < res.size; ++i) v |= uint64_t(reply[i]) << (8 * i);
      *rdata = v;
      *rsize = static_cast<uint16_t>(res.size);
    }
  }
  b.hs.ended(b, err == 0, err);
  if (err == 1 || err == 2) b.ABORT_CODE = res.abort_code;
}

inline void co_sdo_read_call(CO_SDO_READ_INST* b) { sdo_call(*b, false, 0, 0, &b->DATA, &b->SIZE); }
inline void co_sdo_write_call(CO_SDO_WRITE_INST* b) { sdo_call(*b, true, b->DATA, b->SIZE, nullptr, nullptr); }

struct NmtCommon {
  bool EXECUTE = false;
  uint8_t NETWORK = 0;
  Out<bool> BUSY, DONE, ERROR;
  Out<uint16_t> ERROR_ID;
  Handshake hs;
};

inline void nmt_call(NmtCommon& b, const canopen_plc_nmt_request& q) {
  using canopen_plugin::PlcRequests;
  if (b.hs.begin(b)) {
    uint16_t err = 0;
    uint32_t h = PlcRequests::instance().start_nmt(q, err);
    b.hs.started(b, h, err);
  }
  if (b.hs.phase != 1) return;
  uint16_t err = 0;
  int st = PlcRequests::instance().poll_nmt(b.hs.handle, err);
  if (st != 0) b.hs.ended(b, st == 1, err);
}

struct CO_NMT_INST : NmtCommon {
  uint8_t NODE = 0, COMMAND = 0;
};
inline void co_nmt_call(CO_NMT_INST* b) {
  canopen_plc_nmt_request q{};
  q.network = b->NETWORK;
  q.op = CANOPEN_PLC_NMT_NODE;
  q.node = b->NODE;
  q.command = b->COMMAND;
  nmt_call(*b, q);
}

struct CO_NETWORK_START_INST : NmtCommon {
  int64_t TIMEOUT = 0;  // ns, 0: no limit
};
inline void co_network_start_call(CO_NETWORK_START_INST* b) {
  canopen_plc_nmt_request q{};
  q.network = b->NETWORK;
  q.op = CANOPEN_PLC_NMT_START;
  q.timeout_ms = timeout_ms(b->TIMEOUT);
  nmt_call(*b, q);
}

struct CO_NETWORK_STOP_INST : NmtCommon {
  uint8_t NODE_COMMAND = 0;
};
inline void co_network_stop_call(CO_NETWORK_STOP_INST* b) {
  canopen_plc_nmt_request q{};
  q.network = b->NETWORK;
  q.op = CANOPEN_PLC_NMT_STOP;
  q.command = b->NODE_COMMAND;
  nmt_call(*b, q);
}

// The state read answers in the call that starts it.
struct CO_GET_STATE_INST : NmtCommon {
  uint8_t NODE = 0;
  Out<uint8_t> STATE, MASTER_STATE, HELD, BOOT_ERROR;
  Out<bool> CONFIGURED, STARTED;
};
inline void co_get_state_call(CO_GET_STATE_INST* b) {
  if (!b->hs.begin(*b)) return;
  canopen_plc_nmt_state st{};
  uint16_t err = canopen_plugin::PlcRequests::instance().get_state(b->NETWORK, b->NODE, st);
  b->STATE = st.state;
  b->MASTER_STATE = st.master_state;
  b->HELD = st.held;
  b->BOOT_ERROR = st.boot_error;
  b->CONFIGURED = st.configured != 0;
  b->STARTED = st.started != 0;
  b->hs.ended(*b, err == 0, err);
}

}  // namespace queue_client

#endif  // QUEUE_CLIENT_HPP
