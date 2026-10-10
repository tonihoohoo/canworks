#include "canopen_runtime.h"

#include <unistd.h>

#include <cerrno>
#include <cstring>

#include "bus.h"
#include "dcf_gen.h"
#include "diag.h"
#include "eds_check.h"
#include "eds_lint.h"
#include "gateway.h"
#include "log.h"
#include "plc_api.h"
#include "process_image.h"
#include "sim_config.h"
#include "sim_trace.h"
#include "slave_bus.h"
#include "slave_state.h"

namespace canopen_plugin {

namespace {

std::string prefix_of(const Config& cfg) { return cfg.log_prefix.empty() ? "" : cfg.log_prefix + ": "; }

// Parameters simulated devices saved (0x1010, LSS store) live as long as the
// runtime, across PLC stop and start (docs/simulator.md).
std::shared_ptr<canopen_sim::StoreMap> g_sim_store = std::make_shared<canopen_sim::StoreMap>();

// The simulation file for `cfg`: next to the config, or in the canworks/
// folder of the runtime's generated conf/ (where an upload puts it). "" = none.
std::string find_sim_file(const Config& cfg) {
  std::vector<std::string> c = {cfg.config_dir + "/simulation.json", cfg.config_dir + "/canworks/simulation.json"};
  std::string fb = default_eds_fallback_dir();
  if (!fb.empty()) {
    c.push_back(fb + "/canworks/simulation.json");
    c.push_back(fb + "/simulation.json");
  }
  for (const auto& p : c)
    if (access(p.c_str(), R_OK) == 0) return p;
  return "";
}

// A CANopen master network: its generated configuration, image, simulated
// devices and bus thread. Bus keeps references into the ConfigSet and this.
class MasterRuntime : public NetworkRuntime {
 public:
  explicit MasterRuntime(const Config& cfg) : cfg_(cfg) {}
  ~MasterRuntime() override { stop(); }

  bool make(uint64_t base_tick_ns, const ConfigSet& set, GatewayLink* gw, const char* version,
            std::vector<std::string>& errors);
  void start() override { bus_->start(); }
  void stop() override {
    if (bus_) bus_->stop();
  }
  void cycle_start(const plugin_runtime_args_t& rt) override {
    image_.copy_to_plc(rt);
    image_.request_sync();  // PLC-cycle SYNC only
  }
  void cycle_end(const plugin_runtime_args_t& rt) override { image_.copy_from_plc(rt); }
  DiagHub* hub() override { return hub_.get(); }
  std::unique_ptr<TraceSource> trace_source() override {
    return sim_ && sim_->tap ? make_sim_trace_source(sim_->tap) : nullptr;
  }
  std::shared_ptr<SimFrameInjector> frame_injector() override {
    return sim_ && sim_->tap ? sim_->injector : nullptr;
  }

 private:
  bool load_sim(const ConfigSet& set, std::vector<std::string>& errors);

  const Config& cfg_;
  GeneratedConfig gen_;
  ProcessImage image_;
  std::unique_ptr<DiagHub> hub_;
  std::shared_ptr<SimSetup> sim_;
  std::unique_ptr<Bus> bus_;
};

// A CANopen slave network (canopen-slave-device spec).
class SlaveRuntime : public NetworkRuntime {
 public:
  explicit SlaveRuntime(const Config& cfg) : cfg_(cfg) {}
  ~SlaveRuntime() override { stop(); }

  void make(const ConfigSet& set, GatewayLink* gw, const char* version);
  void start() override { bus_->start(); }
  void stop() override {
    if (bus_) bus_->stop();
  }
  void cycle_start(const plugin_runtime_args_t& rt) override { image_.copy_to_plc(rt); }
  void cycle_end(const plugin_runtime_args_t& rt) override { image_.copy_from_plc(rt); }
  DiagHub* hub() override { return hub_.get(); }

 private:
  const Config& cfg_;
  SlaveImage image_;
  std::unique_ptr<DiagHub> hub_;
  std::unique_ptr<SlaveBus> bus_;
};

void SlaveRuntime::make(const ConfigSet& set, GatewayLink* gw, const char* version) {
  std::string state_path = slave_state_path(default_slave_state_dir(), cfg_.network);
  auto store = std::make_shared<SlaveStore>();
  std::string note;
  load_slave_state(state_path, cfg_.slave.eds_sha256, *store, note);
  if (!note.empty())
    log_warn("%s", note.c_str());
  else if (!store->saved.empty() || store->lss_id)
    log_info("stored parameters from %s applied after each reset", state_path.c_str());
  image_.build(cfg_);
  if (cfg_.adapter.simulate) {
    std::string master;
    for (const auto& other : set.networks)
      if (!other.is_slave() && other.is_canopen() && other.adapter.simulate &&
          other.adapter.interface == cfg_.adapter.interface)
        master = other.network.empty() ? other.adapter.interface : other.network;
    log_warn("the slave network is SIMULATED (%s): no CAN interface is used; it runs on simulated "
             "bus %s %s", cfg_.adapter.simulation_forced ? "forced by the runtime" : "adapter.simulate",
             cfg_.adapter.interface.c_str(),
             master.empty() ? "with no master network on it" : ("with master network \"" + master + "\"").c_str());
  }
  if (cfg_.master.has_diagnostics || cfg_.master.cia309.enabled) hub_.reset(new DiagHub(cfg_, version));
  bus_.reset(new SlaveBus(cfg_, image_, store, state_path, gw, hub_.get()));
  log_info("%zu input and %zu output objects bound to the PLC image", image_.input_objects().size(),
           image_.output_objects().size());
}

bool MasterRuntime::load_sim(const ConfigSet& set, std::vector<std::string>& errors) {
  // A version 1 simulation file names nodes by node ID alone, so it serves a
  // config with one network only; version 2 has a section per network.
  sim_ = std::make_shared<SimSetup>();
  sim_->store = g_sim_store;
  std::string sim_path = find_sim_file(cfg_);
  canopen_sim::SimFile loaded;
  if (!sim_path.empty() && !canopen_sim::load_sim_file(sim_path, loaded, errors, cfg_.config_dir)) return false;
  if (!sim_path.empty() && loaded.schema_version >= 2) {
    if (!check_sim_sections(set, loaded, errors)) return false;
    std::string name = sim_network_name(cfg_);
    if (canopen_sim::sim_file_section(loaded, name, sim_->file)) {
      if (!check_sim_file(cfg_, sim_->file, errors)) return false;
      log_info("simulation file %s, section \"%s\"", sim_path.c_str(), name.c_str());
    } else {
      log_info("simulation file %s has no section for network \"%s\": its simulated devices run with their "
               "default behaviour", sim_path.c_str(), name.c_str());
    }
  } else if (!sim_path.empty() && set.several()) {
    log_warn("%s is not used: a version 1 simulation file serves a configuration with one network only (version 2 "
             "has a section per network); the simulated devices of this network run with their default behaviour",
             sim_path.c_str());
  } else if (!sim_path.empty()) {
    sim_->file = std::move(loaded);
    if (!check_sim_file(cfg_, sim_->file, errors)) return false;
    log_info("simulation file %s", sim_path.c_str());
  }
  std::string shared;
  if (cfg_.adapter.simulate && !cfg_.adapter.interface.empty())
    for (const auto& other : set.networks)
      if (other.is_slave() && other.adapter.simulate && other.adapter.interface == cfg_.adapter.interface)
        shared = other.network.empty() ? other.adapter.interface : other.network;
  log_warn("%s", sim_summary(cfg_, sim_->file, shared).c_str());
  if (cfg_.adapter.simulate) {
    sim_->tap = std::make_shared<SimTraceTap>();
    sim_->injector = std::make_shared<SimFrameInjector>();
  }
  return true;
}

bool MasterRuntime::make(uint64_t base_tick_ns, const ConfigSet& set, GatewayLink* gw, const char* version,
                         std::vector<std::string>& errors) {
  Config& cfg = const_cast<Config&>(cfg_);
  size_t failed = errors.size();
  resolve_interpolation_periods(cfg, base_tick_ns / 1000);
  if (!generate_device_config(cfg, default_dcfgen(), gen_, errors)) {
    for (size_t i = failed; i < errors.size(); ++i) log_error("%s", errors[i].c_str());
    log_error("could not generate the device configuration; canworks inactive, CAN interface not opened");
    return false;
  }
  log_info("device configuration %s in %s", gen_.reused ? "unchanged, reusing" : "generated", gen_.work_dir.c_str());
  image_.build(cfg_);
  if (cfg_.master.sync_plc_cycle && image_.sync_fd() < 0) {
    log_error("cannot create the PLC-cycle SYNC event (%s); canworks inactive, CAN interface not opened",
              strerror(errno));
    return false;
  }
  if (simulates_anything(cfg_)) {
    std::vector<std::string> sim_errors;
    if (!load_sim(set, sim_errors)) {
      for (const auto& e : sim_errors) log_error("%s", e.c_str());
      log_error("simulation file rejected; canworks inactive");
      return false;
    }
  }
  if (cfg_.master.has_diagnostics || cfg_.master.cia309.enabled) hub_.reset(new DiagHub(cfg_, version));
  bus_.reset(new Bus(cfg_, gen_, image_, hub_.get(), sim_, gw));
  log_info("%zu input and %zu output PDO entries bound to the PLC image", image_.inputs().size(),
           image_.outputs().size());
  return true;
}

}  // namespace

class CanopenShared {
 public:
  std::unique_ptr<GatewayLink> gateway;  // with a gateway section only
};

void canopen_init_logging() { route_lely_diagnostics(); }

bool canopen_check(ConfigSet& set, std::vector<std::string>& errors) {
  bool ok = true;
  for (auto& cfg : set.networks) {
    if (!cfg.is_canopen()) continue;  // J1939 and plain CAN networks have their own runtimes
    ScopedLogPrefix prefix(prefix_of(cfg));
    if (cfg.is_slave()) log_info("%s: EDS %s", cfg.slave.label().c_str(), cfg.slave.eds_path.c_str());
    if (cfg.adapter.simulation_forced)
      log_warn("simulation forced by the runtime environment (CANWORKS_FORCE_SIMULATE=1): this network runs "
               "simulated, whatever its adapter settings say; no CAN interface is opened");
    for (const auto& n : cfg.nodes) log_info("%s: EDS %s", n.label().c_str(), n.eds_path.c_str());
    size_t warned = cfg.warnings.size(), noted = cfg.notes.size(), failed = errors.size();
    // dcfgen's EDS lint and the prepared copies, then the EDS checks on them.
    bool net_ok = run_eds_lint(cfg, default_edslint_python(), cfg.work_dir, errors) && check_eds_files(cfg, errors);
    // What the lint and the EDS checks settled (prepared copies, accepted
    // findings, device mappings, kept PDOs).
    for (size_t i = warned; i < cfg.warnings.size(); ++i) log_warn("%s", cfg.warnings[i].c_str());
    for (size_t i = noted; i < cfg.notes.size(); ++i) log_info("%s", cfg.notes[i].c_str());
    for (size_t i = failed; i < errors.size(); ++i) errors[i] = prefix_of(cfg) + errors[i];
    ok = ok && net_ok;
  }
  if (ok) {
    // The gateway's routes against the upper network's EDS.
    size_t warned = set.warnings.size();
    ok = check_gateway_eds(set, errors);
    for (size_t i = warned; i < set.warnings.size(); ++i) log_warn("%s", set.warnings[i].c_str());
  }
  return ok;
}

void canopen_log_loaded(const ConfigSet& set, const Config& cfg, uint64_t base_tick_ns) {
  ScopedLogPrefix prefix(prefix_of(cfg));
  const std::string& path = set.path;
  if (cfg.is_slave()) {
    std::string id = cfg.slave.lss ? std::string("from LSS") : std::to_string(cfg.slave.node_id);
    std::string unused = cfg.adapter.simulate ? " (not used: on the simulated bus " + cfg.adapter.interface + ")" : "";
    log_info("loaded %s: %s adapter %s, %u bit/s%s, CANopen slave, node ID %s, %zu bound object%s", path.c_str(),
             cfg.adapter.type.c_str(), cfg.adapter.interface.c_str(), cfg.adapter.bitrate, unused.c_str(), id.c_str(),
             cfg.slave.objects.size(), cfg.slave.objects.size() == 1 ? "" : "s");
    return;
  }
  log_info("loaded %s: %s adapter %s, %u bit/s%s, master node ID %u, %zu slave%s", path.c_str(),
           cfg.adapter.type.c_str(), cfg.adapter.interface.c_str(), cfg.adapter.bitrate,
           cfg.adapter.simulate ? " (not used: the network is simulated)" : "", cfg.master.node_id, cfg.nodes.size(),
           cfg.nodes.size() == 1 ? "" : "s");
  const MasterConfig& m = cfg.master;
  if (m.sync_plc_cycle) {
    unsigned long long tick_us = base_tick_ns / 1000;
    if (!tick_us)
      log_info("SYNC from the PLC cycle, every %u PLC cycle%s (the runtime does not report its base tick)",
               m.sync_cycles, m.sync_cycles == 1 ? "" : "s");
    else
      log_info("SYNC from the PLC cycle, every %u PLC cycle%s (base tick %llu us)", m.sync_cycles,
               m.sync_cycles == 1 ? "" : "s", tick_us);
    if (tick_us && tick_us * m.sync_cycles < 1000)
      log_warn("a SYNC period of %llu us is below 1 ms; the bus may not carry all PDOs in one period",
               tick_us * m.sync_cycles);
  } else if (m.sync_period_us) {
    log_info("SYNC every %u us", m.sync_period_us);
  } else {
    log_info("no SYNC period: the master produces no SYNC and sends outputs when they change");
  }
}

bool canopen_create(ConfigSet& set, uint64_t base_tick_ns, const char* version,
                    std::shared_ptr<CanopenShared>& shared, std::vector<std::unique_ptr<NetworkRuntime>>& out) {
  shared = std::make_shared<CanopenShared>();
  if (set.gateway.enabled) {
    const GatewayConfig& g = set.gateway;
    shared->gateway.reset(new GatewayLink(set));
    log_info("gateway: upper network \"%s\", %zu route%s%s%s%s", set.networks[g.upper].network.c_str(),
             g.routes.size(), g.routes.size() == 1 ? "" : "s", g.has_status ? ", node status" : "",
             g.emcy_forward ? ", EMCY forwarding" : "", g.sdo_bridge ? ", SDO bridge" : "");
  }
  for (size_t i = 0; i < set.networks.size(); ++i) {
    Config& cfg = set.networks[i];
    if (!cfg.is_canopen()) continue;  // J1939 and plain CAN networks have their own runtimes
    ScopedLogPrefix prefix(prefix_of(cfg));
    if (cfg.is_slave()) {
      std::unique_ptr<SlaveRuntime> s(new SlaveRuntime(cfg));
      s->make(set, shared->gateway.get(), version);
      out[i] = std::move(s);
      continue;
    }
    std::unique_ptr<MasterRuntime> m(new MasterRuntime(cfg));
    std::vector<std::string> errors;
    if (!m->make(base_tick_ns, set, shared->gateway.get(), version, errors)) return false;
    out[i] = std::move(m);
  }
  return true;
}

void canopen_open_plc_requests(const ConfigSet& set) {
  uint32_t masters = 0;
  for (size_t i = 0; i < set.networks.size() && i < 32; ++i)
    if (set.networks[i].is_canopen() && !set.networks[i].is_slave()) masters |= 1u << i;
  PlcRequests::instance().open(masters);
}
void canopen_close_plc_requests() { PlcRequests::instance().close(); }
const void* canopen_plc_api_table(uint32_t version) { return plc_api_table(version); }

}  // namespace canopen_plugin
