// sim_trace.h - bus trace on a simulated network (docs/simulator.md): the
// bus thread hands every frame of the virtual bus to the diagnostics
// server's capture through a pipe, as the CAN_RAW socket does on a real
// interface. Frames are written only while a trace runs; a full pipe drops
// frames and counts them.

#ifndef CANOPEN_SIM_TRACE_H
#define CANOPEN_SIM_TRACE_H

#include <atomic>
#include <cstdint>
#include <memory>

#include "trace_capture.h"

struct can_msg;

namespace canopen_plugin {

class SimTraceTap {
 public:
  SimTraceTap();
  ~SimTraceTap();
  // Bus thread: one frame seen on the virtual bus.
  void push(const can_msg& msg, bool tx = false);
  // Server thread.
  void enable(bool on) { on_.store(on, std::memory_order_release); }
  int read_fd() const { return pipe_[0]; }
  uint64_t drops() const { return drops_.load(); }

 private:
  int pipe_[2] = {-1, -1};
  std::atomic<bool> on_{false};
  std::atomic<uint64_t> drops_{0};
};

std::unique_ptr<TraceSource> make_sim_trace_source(std::shared_ptr<SimTraceTap> tap);

}  // namespace canopen_plugin

#endif  // CANOPEN_SIM_TRACE_H
