// raw_runtime.h - the raw CAN path of one network (spec can-raw-messages,
// can-plc-frames): the config messages, the program's frame port and the I/O
// thread that serves them, next to whatever protocol the network runs. A
// plain CAN network ("protocol": "none") has nothing else: make_plain_runtime
// gives it the diagnostics hub and simulated bus a protocol would.

#ifndef CANWORKS_RAW_RUNTIME_H
#define CANWORKS_RAW_RUNTIME_H

#include <atomic>
#include <memory>
#include <string>
#include <vector>

#include "../config.h"
#include "../image_io.h"
#include "../network_runtime.h"
#include "engine.h"
#include "plc_frames.h"
#include "raw_devices.h"
#include "raw_io.h"
#include "raw_link.h"

struct cJSON;

namespace canopen_plugin {
class CanAdapter;
class LinkOps;
}

namespace canworks_raw {

class RawRuntime {
 public:
  explicit RawRuntime(const canopen_plugin::Config& cfg);
  ~RawRuntime();

  // Builds the engine and port, reads the simulation file's plain CAN
  // devices on a simulated network, and registers the port for the
  // program's blocks. False with `errors` (the config is then rejected).
  bool make(const canopen_plugin::ConfigSet& set, std::vector<std::string>& errors);
  void start();
  // Ends the I/O thread; every program handle answers "cancelled".
  void stop();
  // The scan hooks (never block, allocate or log).
  void cycle_start(const plugin_runtime_args_t& rt);
  void cycle_end(const plugin_runtime_args_t& rt);

  // The I/O thread has its link open (frames can be sent).
  bool running() const { return port_ && port_->running(); }
  // The "raw" object of a diagnostics status (any thread).
  cJSON* status();
  // A simulated plain CAN network's bus trace and hand-sent frames.
  std::unique_ptr<canopen_plugin::TraceSource> trace_source();
  std::shared_ptr<canopen_plugin::SimFrameInjector> frame_injector() { return injector_; }
  const canopen_plugin::Config& config() const { return cfg_; }

 private:
  bool bus_info(canworks_can_bus_info& info);
  bool prepare_adapter();

  const canopen_plugin::Config& cfg_;
  uint8_t index_;
  std::string prefix_;
  std::unique_ptr<RawEngine> engine_;
  std::unique_ptr<PlcPort> port_;
  std::unique_ptr<RawSimDevices> devices_;
  std::shared_ptr<SimBridge> bridge_;
  std::shared_ptr<canopen_plugin::SimFrameInjector> injector_;
  std::unique_ptr<canopen_plugin::CanAdapter> adapter_;  // plain CAN networks on an interface
  std::unique_ptr<canopen_plugin::LinkOps> link_ops_;
  std::string adapter_problem_;
  std::unique_ptr<RawIo> io_;
  canopen_plugin::TripleBuffer in_, out_;
  std::vector<uint8_t> owned_std_;  // 2048 entries: the protocol uses the 11-bit identifier
};

// The NetworkRuntime of a plain CAN network: `raw` does the work (the plugin
// starts it and calls its scan hooks), this adds the diagnostics hub.
std::unique_ptr<canopen_plugin::NetworkRuntime> make_plain_runtime(RawRuntime* raw, const char* version);

void log_plain_loaded(const canopen_plugin::ConfigSet& set, const canopen_plugin::Config& cfg);

}  // namespace canworks_raw

#endif  // CANWORKS_RAW_RUNTIME_H
