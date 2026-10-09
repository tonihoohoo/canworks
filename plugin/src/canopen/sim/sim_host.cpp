#include "sim_host.h"

#include <lely/io2/sys/timer.hpp>

namespace canopen_sim {

LoopHost::LoopHost(lely::io::Context& ctx, lely::io::Poll& poll, ev_exec_t* exec, lely::io::VirtualCanController& bus,
                   LogFn log)
    : ctx_(ctx), poll_(poll), exec_(exec), vbus_(&bus), iface_("simulated"), log_(std::move(log)) {}

LoopHost::LoopHost(lely::io::Context& ctx, lely::io::Poll& poll, ev_exec_t* exec, const std::string& iface, bool real,
                   LogFn log)
    : ctx_(ctx), poll_(poll), exec_(exec), ctrl_(new lely::io::CanController(iface.c_str())), iface_(iface),
      real_(real), log_(std::move(log)) {}

LoopHost::~LoopHost() = default;

std::shared_ptr<lely::io::TimerBase> LoopHost::make_timer() {
  return std::make_shared<lely::io::Timer>(poll_, exec_, CLOCK_MONOTONIC);
}

std::shared_ptr<lely::io::CanChannelBase> LoopHost::make_channel() {
  if (vbus_) {
    auto c = std::make_shared<lely::io::VirtualCanChannel>(ctx_, exec_);
    c->open(*vbus_);
    return c;
  }
  auto c = std::make_shared<lely::io::CanChannel>(poll_, exec_);
  c->open(*ctrl_);
  return c;
}

}  // namespace canopen_sim
