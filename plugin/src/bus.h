// bus.h - the bus thread: prepares the CAN adapter (bit rate, link up), opens
// the SocketCAN interface, runs a Network on a Lely event loop, and keeps
// retrying while the interface is missing, down or cannot be configured.

#ifndef CANOPEN_BUS_H
#define CANOPEN_BUS_H

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <memory>
#include <mutex>
#include <string>
#include <thread>

#include "bus_monitor.h"
#include "can_adapter.h"
#include "config.h"
#include "dcf_gen.h"
#include "diag.h"
#include "gateway.h"
#include "process_image.h"

namespace canopen_plugin {

enum class IfaceState { Missing, Down, Up };
IfaceState iface_state(const std::string& name);

class Bus {
 public:
  // `hub`, when given, is served by each bus session's Network (the
  // diagnostics channel); between sessions it answers "no bus".
  // `gw`, when given, links the network into a gateway (canopen-gateway spec).
  Bus(const Config& cfg, const GeneratedConfig& gen, ProcessImage& image, DiagHub* hub = nullptr,
      GatewayLink* gw = nullptr);
  ~Bus();

  void start();
  // Ends the session (within one supervision tick) and joins. Idempotent.
  void stop();
  bool running() const { return thread_.joinable(); }

 private:
  // How long one run of the session's event loop lasts before the bus thread
  // checks for a stop or a lost interface itself, and how many such slices it
  // waits for the loop to finish after shutting it down.
  static constexpr std::chrono::milliseconds kLoopSlice{200};
  static constexpr int kShutdownSlices = 10;
  // SCHED_FIFO priority of the bus thread with PLC-cycle SYNC: the runtime's
  // highest task level (PLC_FIFO_TASK_MAX), below its dispatcher.
  static constexpr int kSyncPriority = 49;

  void thread_main();
  void run_session();
  bool wait_for(std::chrono::milliseconds d);  // false if stop was requested

  const Config& cfg_;
  const GeneratedConfig& gen_;
  ProcessImage& image_;
  DiagHub* hub_;
  GatewayLink* gw_;
  std::unique_ptr<CanAdapter> adapter_;
  BusMonitor monitor_;
  std::thread thread_;
  std::atomic<bool> stop_{false};
  std::mutex mutex_;
  std::condition_variable cv_;
};

}  // namespace canopen_plugin

#endif  // CANOPEN_BUS_H
