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
#include "process_image.h"
#include "sim_engine.h"
#include "sim_trace.h"

namespace canopen_plugin {

enum class IfaceState { Missing, Down, Up };

// Simulated devices (docs/simulator.md): the simulation file, the stored
// parameters that outlive a session, and on a simulated network the trace tap.
struct SimSetup {
  canopen_sim::SimFile file;
  std::shared_ptr<canopen_sim::StoreMap> store;
  std::shared_ptr<SimTraceTap> tap;
};
IfaceState iface_state(const std::string& name);

class Bus {
 public:
  // `hub`, when given, is served by each bus session's Network (the
  // diagnostics channel); between sessions it answers "no bus".
  Bus(const Config& cfg, const GeneratedConfig& gen, ProcessImage& image, DiagHub* hub = nullptr,
      std::shared_ptr<const SimSetup> sim = nullptr);
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

  void thread_main();
  void run_session();
  bool wait_for(std::chrono::milliseconds d);  // false if stop was requested

  const Config& cfg_;
  const GeneratedConfig& gen_;
  ProcessImage& image_;
  DiagHub* hub_;
  std::shared_ptr<const SimSetup> sim_;
  std::unique_ptr<CanAdapter> adapter_;
  BusMonitor monitor_;
  std::thread thread_;
  std::atomic<bool> stop_{false};
  std::mutex mutex_;
  std::condition_variable cv_;
};

}  // namespace canopen_plugin

#endif  // CANOPEN_BUS_H
