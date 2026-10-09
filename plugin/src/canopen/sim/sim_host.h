// sim_host.h - the engine's host on a Lely event loop (sim_engine.h): timers
// from the loop's poll, channels on Lely's in-process virtual bus or on a
// SocketCAN interface. Used by the plugin's bus thread, the standalone
// simulator and the tests.

#ifndef CANOPEN_SIM_HOST_H
#define CANOPEN_SIM_HOST_H

#include <functional>
#include <memory>
#include <string>

#include <lely/io2/ctx.hpp>
#include <lely/io2/linux/can.hpp>
#include <lely/io2/posix/poll.hpp>
#include <lely/io2/vcan.hpp>

#include "sim_engine.h"

namespace canopen_sim {

class LoopHost : public Host {
 public:
  using LogFn = std::function<void(Level, const std::string&)>;
  // Channels on a virtual bus.
  LoopHost(lely::io::Context& ctx, lely::io::Poll& poll, ev_exec_t* exec, lely::io::VirtualCanController& bus, LogFn log);
  // Channels on a SocketCAN interface; `real` marks a network with real
  // devices (the conflict guard runs).
  LoopHost(lely::io::Context& ctx, lely::io::Poll& poll, ev_exec_t* exec, const std::string& iface, bool real, LogFn log);
  ~LoopHost() override;

  ev_exec_t* exec() override { return exec_; }
  std::shared_ptr<lely::io::TimerBase> make_timer() override;
  std::shared_ptr<lely::io::CanChannelBase> make_channel() override;
  void log(Level level, const std::string& message) override { if (log_) log_(level, message); }
  bool real_network() const override { return real_; }
  std::string interface_name() const override { return iface_; }

 private:
  lely::io::Context& ctx_;
  lely::io::Poll& poll_;
  ev_exec_t* exec_;
  lely::io::VirtualCanController* vbus_ = nullptr;
  std::unique_ptr<lely::io::CanController> ctrl_;
  std::string iface_;
  bool real_ = false;
  LogFn log_;
};

}  // namespace canopen_sim

#endif  // CANOPEN_SIM_HOST_H
