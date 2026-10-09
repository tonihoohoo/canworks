// raw_bridge_server.cpp - see raw_bridge_server.h.

#include "raw_bridge_server.h"

#include <cstring>

namespace canopen_plugin {

namespace {

canworks_can_frame from_msg(const can_msg& m) {
  canworks_can_frame f{};
  bool ext = (m.flags & CAN_FLAG_IDE) != 0;
  f.id = m.id & (ext ? 0x1FFFFFFFu : 0x7FFu);
  f.flags = static_cast<uint8_t>((ext ? CANWORKS_CAN_EXTENDED : 0) | ((m.flags & CAN_FLAG_RTR) ? CANWORKS_CAN_RTR : 0));
  f.dlc = m.len > 8 ? 8 : m.len;
  if (!(m.flags & CAN_FLAG_RTR)) std::memcpy(f.data, m.data, f.dlc);
  return f;
}

can_msg to_msg(const canworks_can_frame& f) {
  can_msg m = CAN_MSG_INIT;
  m.id = f.id;
  m.flags = ((f.flags & CANWORKS_CAN_EXTENDED) ? CAN_FLAG_IDE : 0) | ((f.flags & CANWORKS_CAN_RTR) ? CAN_FLAG_RTR : 0);
  m.len = f.dlc > 8 ? 8 : f.dlc;
  if (!(f.flags & CANWORKS_CAN_RTR)) std::memcpy(m.data, f.data, m.len);
  return m;
}

}  // namespace

RawBridgeServer::RawBridgeServer(lely::io::Context& ctx, lely::io::Poll& poll, lely::ev::Executor exec,
                                 lely::io::VirtualCanController& vbus,
                                 std::shared_ptr<canworks_raw::SimBridge> bridge,
                                 std::function<void(const can_msg&, bool)> on_write)
    : bridge_(std::move(bridge)), on_write_(std::move(on_write)), exec_(exec), chan_(ctx, exec) {
  chan_.open(vbus);
  read_next();
  wake_.reset(new FdWake(poll, bridge_->tx_fd(), [this] { write_waiting(); }));
  bridge_->attach(true);
}

RawBridgeServer::~RawBridgeServer() { bridge_->attach(false); }

// Every frame another channel puts on the virtual bus. The channel's own
// writes do not come back: write_waiting() reports those.
void RawBridgeServer::read_next() {
  chan_.submit_read(&msg_, nullptr, nullptr, exec_, [this](int result, std::error_code ec) {
    if (ec) return;
    if (result == 1) bridge_->seen(from_msg(msg_), false);
    read_next();
  });
}

void RawBridgeServer::write_waiting() {
  std::vector<std::pair<canworks_can_frame, bool>> frames;
  bridge_->take(frames);
  for (const auto& p : frames) {
    can_msg m = to_msg(p.first);
    std::error_code ec;
    chan_.write(m, 0, ec);
    if (ec) continue;  // a full virtual bus: lost, as on a real one
    if (on_write_) on_write_(m, p.second);
    bridge_->seen(p.first, p.second);
  }
}

}  // namespace canopen_plugin
