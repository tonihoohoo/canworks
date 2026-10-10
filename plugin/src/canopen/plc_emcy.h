// plc_emcy.h - the per-network EMCY queues behind CO_RECV_EMCY (spec
// canopen-plc-sdo "Per-network EMCY queue").
//
// The bus thread pushes every EMCY of a configured node into its network's
// ring of the last CANOPEN_PLC_EMCY_QUEUE messages; the scan thread reads them
// through the C table, each block instance from its own cursor, so several
// readers each get every message. The rings are static (allocated with the
// plugin), and the mutex is held only to copy one entry, as in PlcRequests.

#ifndef CANOPEN_PLC_EMCY_H
#define CANOPEN_PLC_EMCY_H

#include <cstdint>
#include <mutex>

#include "canopen_plc_api.h"

namespace canopen_plugin {

class EmcyQueues {
 public:
  // Networks a config can have (kMaxNetworks in config.h).
  static constexpr unsigned kNetworks = 8;
  static constexpr uint32_t kDepth = CANOPEN_PLC_EMCY_QUEUE;

  static EmcyQueues& instance();

  // Bus thread: a CANopen session of `network` starts; its ring is emptied and
  // readers of the earlier session see CANOPEN_PLC_ERR_CANCELLED once.
  void reset(unsigned network);
  // Bus thread: one EMCY of a configured node.
  void push(unsigned network, uint8_t node, uint16_t code, uint8_t error_register, const uint8_t msef[5],
            uint64_t time_us);

  // Scan thread (through the C table, which checks the running state and
  // the inputs first). `network` must be below kNetworks.
  void begin(unsigned network, bool skip_old, canopen_plc_emcy_cursor& cursor);
  // 1 delivered, 0 nothing, -CANOPEN_PLC_ERR_CANCELLED after a session change.
  int read(unsigned network, uint8_t node, canopen_plc_emcy_cursor& cursor, canopen_plc_emcy& entry,
           canopen_plc_emcy_info& info);

 private:
  struct Ring {
    canopen_plc_emcy entries[kDepth] = {};
    uint32_t session = 1;
    uint32_t next = 1;  // sequence number of the next message pushed
    uint32_t oldest() const { return next > kDepth ? next - kDepth : 1u; }
  };

  EmcyQueues() = default;

  std::mutex mutex_;
  Ring rings_[kNetworks];
  uint32_t sessions_ = 1;  // last session number handed out
};

}  // namespace canopen_plugin

#endif  // CANOPEN_PLC_EMCY_H
