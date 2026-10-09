#include "j1939_runtime.h"

#include "diag.h"
#include "j1939_network.h"
#include "log.h"

namespace canopen_plugin {

namespace {

class J1939Runtime : public NetworkRuntime {
 public:
  J1939Runtime(const Config& cfg, const char* version) {
    if (cfg.master.has_diagnostics) hub_.reset(new DiagHub(cfg, version));
    net_.reset(new J1939Network(cfg, hub_.get()));
  }
  ~J1939Runtime() override { stop(); }

  void start() override { net_->start(); }
  void stop() override { net_->stop(); }
  void cycle_start(const plugin_runtime_args_t& rt) override { net_->cycle_start(rt); }
  void cycle_end(const plugin_runtime_args_t& rt) override { net_->cycle_end(rt); }
  DiagHub* hub() override { return hub_.get(); }

 private:
  std::unique_ptr<DiagHub> hub_;  // before net_: the bus thread uses it
  std::unique_ptr<J1939Network> net_;
};

const char* plural(size_t n) { return n == 1 ? "" : "s"; }

}  // namespace

void j1939_log_loaded(const ConfigSet& set, const Config& cfg) {
  ScopedLogPrefix prefix(cfg.log_prefix.empty() ? "" : cfg.log_prefix + ": ");
  const J1939Config& j = cfg.j1939;
  std::string range;
  if (j.ecu.has_range)
    range = ", else " + std::to_string(j.ecu.range_low) + ".." + std::to_string(j.ecu.range_high);
  log_info("loaded %s: %s adapter %s, %u bit/s, J1939 ECU at address %u%s, %zu received PGN%s, %zu sent PGN%s, "
           "%zu requested PGN%s",
           set.path.c_str(), cfg.adapter.type.c_str(), cfg.adapter.interface.c_str(), cfg.adapter.bitrate,
           j.ecu.address, range.c_str(), j.rx.size(), plural(j.rx.size()), j.tx.size(), plural(j.tx.size()),
           j.requests.size(), plural(j.requests.size()));
}

void j1939_create(const ConfigSet& set, const char* version, std::vector<std::unique_ptr<NetworkRuntime>>& out) {
  for (size_t i = 0; i < set.networks.size(); ++i)
    if (set.networks[i].is_j1939()) out[i].reset(new J1939Runtime(set.networks[i], version));
}

}  // namespace canopen_plugin
