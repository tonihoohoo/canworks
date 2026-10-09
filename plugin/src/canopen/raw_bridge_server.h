// raw_bridge_server.h - the bus thread's side of a simulated CANopen
// network's raw path (can/raw/raw_link.h SimBridge): a channel on the virtual
// bus that hands every frame there to the raw I/O thread and writes the
// frames it sends (config messages, program frames, plain CAN devices).

#ifndef CANOPEN_RAW_BRIDGE_SERVER_H
#define CANOPEN_RAW_BRIDGE_SERVER_H

#include <deque>
#include <functional>
#include <memory>

#include <lely/can/msg.h>
#include <lely/ev/exec.hpp>
#include <lely/io2/vcan.hpp>

#include "network.h"
#include "raw/raw_link.h"

namespace canopen_plugin {

class RawBridgeServer {
 public:
  // `on_write` gets each frame written to the bus (the trace marks them Tx).
  RawBridgeServer(lely::io::Context& ctx, lely::io::Poll& poll, lely::ev::Executor exec,
                  lely::io::VirtualCanController& vbus, std::shared_ptr<canworks_raw::SimBridge> bridge,
                  std::function<void(const can_msg&, bool own)> on_write);
  ~RawBridgeServer();
  RawBridgeServer(const RawBridgeServer&) = delete;
  RawBridgeServer& operator=(const RawBridgeServer&) = delete;

 private:
  void read_next();
  void write_waiting();

  std::shared_ptr<canworks_raw::SimBridge> bridge_;
  std::function<void(const can_msg&, bool)> on_write_;
  lely::ev::Executor exec_;
  lely::io::VirtualCanChannel chan_;
  can_msg msg_ = CAN_MSG_INIT;
  std::unique_ptr<FdWake> wake_;
};

}  // namespace canopen_plugin

#endif  // CANOPEN_RAW_BRIDGE_SERVER_H
