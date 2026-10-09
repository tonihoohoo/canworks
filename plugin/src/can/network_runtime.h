// network_runtime.h - what the plugin entry points need from one running
// network, whatever its protocol (design Decision 1). Each protocol folder
// makes its networks (canopen/canopen_runtime.h, j1939/j1939_runtime.h); the
// entry points start and stop them and call the scan hooks.

#ifndef CANWORKS_NETWORK_RUNTIME_H
#define CANWORKS_NETWORK_RUNTIME_H

#include <memory>

#include "frame_tx.h"
#include "plugin_types.h"
#include "trace_capture.h"

namespace canopen_plugin {

class DiagHub;

class NetworkRuntime {
 public:
  virtual ~NetworkRuntime() = default;
  virtual void start() = 0;
  // Ends the bus thread and joins. Idempotent.
  virtual void stop() = 0;
  // The scan hooks: inputs to %I* (cycle_start), %Q* into a snapshot
  // (cycle_end). Never block, allocate or log.
  virtual void cycle_start(const plugin_runtime_args_t& rt) = 0;
  virtual void cycle_end(const plugin_runtime_args_t& rt) = 0;
  // The network's diagnostics hub, nullptr without diagnostics.
  virtual DiagHub* hub() = 0;
  // A simulated network's own frames for traces and hand-sent frames
  // (nullptr: the interface's).
  virtual std::unique_ptr<TraceSource> trace_source() { return nullptr; }
  virtual std::shared_ptr<SimFrameInjector> frame_injector() { return nullptr; }
};

}  // namespace canopen_plugin

#endif  // CANWORKS_NETWORK_RUNTIME_H
