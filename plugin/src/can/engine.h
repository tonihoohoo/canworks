// engine.h - the networks of one config, whatever runs them: the OpenPLC
// plugin (plugin.cpp) or the Modbus bridge (bridge/bridge_host.cpp). The host
// gives the engine a config and a plugin_runtime_args_t for the image
// exchange: the OpenPLC host passes the runtime's own, the bridge one over
// its byte image (modbus-bridge design Decision 1).

#ifndef CANWORKS_ENGINE_H
#define CANWORKS_ENGINE_H

#include <cstdint>
#include <memory>
#include <string>
#include <vector>

#include "config.h"
#include "diag.h"
#include "network_runtime.h"
#include "plugin_types.h"

namespace canworks_raw {
class RawRuntime;
}

namespace canopen_plugin {

class DiagServer;
class CanopenShared;

class Engine {
 public:
  Engine();
  ~Engine();

  // Loads the config, checks every network and makes them; false (with the
  // reasons logged) when the config is rejected. Nothing is opened yet.
  bool prepare(const std::string& path, const ImageLimits& limits, uint64_t base_tick_ns, const char* version);
  // Before prepare(): the host's part of the diagnostics channel.
  void set_diag_host(DiagHost host) { diag_host_ = std::move(host); }
  // Only loads and checks a config, logging as prepare() does; makes nothing.
  // `problems`, when given, gets the reasons of a rejection.
  static bool check(const std::string& path, const ImageLimits& limits, std::vector<std::string>* problems = nullptr);
  // Starts the networks, raw paths and diagnostics channel, and opens the
  // PLC request tables.
  void start();
  // Stops everything started; idempotent.
  void stop();

  // The scan hooks of every network and raw path.
  void cycle_start(const plugin_runtime_args_t& rt);
  void cycle_end(const plugin_runtime_args_t& rt);

  const ConfigSet& set() const { return set_; }
  ConfigSet& set() { return set_; }
  DiagServer* server() { return server_.get(); }

 private:
  static bool load(const std::string& path, const ImageLimits& limits, ConfigSet& set,
                   std::vector<std::string>* problems);
  ConfigSet set_;
#if CANWORKS_WITH_CANOPEN
  std::shared_ptr<CanopenShared> canopen_;  // the gateway link; outlives the networks
#endif
  // Each network's raw CAN path (raw messages, program frames); destroyed
  // after nets_, whose plain CAN networks point into it.
  std::vector<std::unique_ptr<canworks_raw::RawRuntime>> raws_;
  std::vector<std::unique_ptr<NetworkRuntime>> nets_;  // one per network, in config order
  std::unique_ptr<DiagServer> server_;
  DiagHost diag_host_;
  bool started_ = false;
};

}  // namespace canopen_plugin

#endif  // CANWORKS_ENGINE_H
