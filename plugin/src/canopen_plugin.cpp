// canopen_plugin.cpp - OpenPLC Runtime v4 native plugin entry points.
//
// Lifecycle (core/src/drivers/plugin_driver.c): init() on every PLC start,
// then start_loop(); stop_loop() on PLC stop; cleanup() on unload. init() may
// run again after stop_loop() without cleanup(), so it starts from scratch.
// start_loop() returns 0 on success: the runtime only calls cycle_start() and
// cycle_end() for a plugin whose start_loop() returned 0.
//
// The runtime calls init() for every plugin in plugins.conf, enabled or not
// (plugin_driver_init: "Initialize ALL plugins regardless of enabled flag"),
// but start_loop() only for enabled ones. A disabled plugin's config path
// still names the config of the last CANopen upload, so init() only keeps the
// runtime's args, and start_loop() loads and checks the config: a project
// without CANopen logs nothing from this plugin.
//
// cycle_start()/cycle_end() run on the runtime's dispatcher thread without
// the image lock held (core/src/plc_app/plc_state_manager.cpp): cycle_start
// before the fastest task's frame is released, cycle_end after the frame's
// outputs were drained into the image. They only touch preallocated memory.

#include <atomic>
#include <cerrno>
#include <cstdlib>
#include <cstring>
#include <memory>
#include <string>
#include <unistd.h>
#include <vector>

extern "C" {
#include "plugin_types.h"
}

#include "bus.h"
#include "config.h"
#include "dcf_gen.h"
#include "diag.h"
#include "eds_check.h"
#include "eds_lint.h"
#include "gateway.h"
#include "log.h"
#include "plc_api.h"
#include "process_image.h"
#include "runtime_version.h"
#include "slave_bus.h"
#include "slave_state.h"
#include "sim_config.h"
#include "sim_trace.h"

using namespace canopen_plugin;

namespace {

plugin_runtime_args_t g_rt;  // copied by value: the runtime frees args after init()
bool g_have_rt = false;

// One CANopen network: its generated configuration, image, diagnostics hub
// and bus thread. Bus keeps references into the ConfigSet and into this.
struct NetworkState {
  bool slave = false;
  GeneratedConfig gen;
  ProcessImage image;
  std::unique_ptr<DiagHub> hub;  // with diagnostics only
  std::shared_ptr<SimSetup> sim;  // simulated devices, if any
  std::unique_ptr<Bus> bus;
  // A slave network (canopen-slave-device spec) instead of the above.
  SlaveImage slave_image;
  std::unique_ptr<SlaveBus> slave_bus;
};

// Parameters simulated devices saved (0x1010, LSS store) live as long as the
// runtime, across PLC stop and start (docs/simulator.md).
std::shared_ptr<canopen_sim::StoreMap> g_sim_store = std::make_shared<canopen_sim::StoreMap>();

// The simulation file for `cfg`: next to the config, or in the canopen/
// folder of the runtime's generated conf/ (where an upload puts it). "" = none.
std::string find_sim_file(const Config& cfg) {
  std::vector<std::string> c = {cfg.config_dir + "/simulation.json", cfg.config_dir + "/canopen/simulation.json"};
  std::string fb = default_eds_fallback_dir();
  if (!fb.empty()) {
    c.push_back(fb + "/canopen/simulation.json");
    c.push_back(fb + "/simulation.json");
  }
  for (const auto& p : c)
    if (access(p.c_str(), R_OK) == 0) return p;
  return "";
}

struct PluginState {
  ConfigSet set;
  std::unique_ptr<GatewayLink> gateway;  // with a gateway section only
  std::vector<std::unique_ptr<NetworkState>> nets;
  std::unique_ptr<DiagServer> server;
};

std::unique_ptr<PluginState> g_state;
std::atomic<bool> g_exchange{false};  // cycle hooks active

void runtime_sink(LogLevel level, const char* msg) {
  if (!g_have_rt) return;
  plugin_log_info_func_t f = nullptr;
  switch (level) {
    case LogLevel::Debug: f = g_rt.log_debug; break;
    case LogLevel::Info: f = g_rt.log_info; break;
    case LogLevel::Warn: f = g_rt.log_warn; break;
    case LogLevel::Error: f = g_rt.log_error; break;
  }
  if (f) f("%s", msg);
}

void stop_all() {
  if (!g_state) return;
  if (g_state->server) g_state->server->stop();
  for (auto& n : g_state->nets) {
    if (n->bus) n->bus->stop();
    if (n->slave_bus) n->slave_bus->stop();
  }
}

void teardown() {
  g_exchange.store(false, std::memory_order_release);
  PlcRequests::instance().close();
  stop_all();
  g_state.reset();
}

std::string prefix_of(const Config& cfg) { return cfg.log_prefix.empty() ? "" : cfg.log_prefix + ": "; }

// Loads the config, checks it and generates the device configuration. Sets
// g_state on success; logs why not otherwise.
void prepare() {
  std::string path = g_rt.plugin_specific_config_file_path;
  if (path.empty()) {
    log_warn("no configuration file given in plugins.conf; CANopen inactive");
    return;
  }
  if (access(path.c_str(), F_OK) != 0) {
    log_warn("no configuration at %s; CANopen inactive", path.c_str());
    return;
  }
  std::string mismatch = runtime_version_problem(CANOPEN_PREFIX "/lib/runtime-version", getenv("RUNTIME_VERSION"));
  if (!mismatch.empty()) {
    log_error("%s; CANopen inactive, CAN interface not opened", mismatch.c_str());
    return;
  }
  auto st = std::unique_ptr<PluginState>(new PluginState);
  ImageLimits limits;
  limits.buffer_size = g_rt.buffer_size > 0 ? static_cast<unsigned>(g_rt.buffer_size) : 1024;
  limits.force_simulate = force_simulate_from_env(getenv("CANOPEN_FORCE_SIMULATE"));

  std::vector<std::string> errors;
  bool loaded = load_config_set(path, limits, st->set, errors);
  for (const auto& w : st->set.warnings) log_warn("%s", w.c_str());
  for (const auto& m : st->set.notes) log_info("%s", m.c_str());
  // Every network is checked before any interface opens: an error in any of
  // them leaves CANopen inactive (canopen-networks spec).
  bool checked = loaded;
  for (auto& cfg : st->set.networks) {
    ScopedLogPrefix prefix(prefix_of(cfg));
    for (const auto& w : cfg.warnings) log_warn("%s", w.c_str());
    for (const auto& m : cfg.notes) log_info("%s", m.c_str());
    if (!loaded) continue;
    if (cfg.is_slave()) log_info("%s: EDS %s", cfg.slave.label().c_str(), cfg.slave.eds_path.c_str());
    if (cfg.adapter.simulation_forced)
      log_warn("simulation forced by the runtime environment (CANOPEN_FORCE_SIMULATE=1): this network runs "
               "simulated, whatever its adapter settings say; no CAN interface is opened");
    for (const auto& n : cfg.nodes) log_info("%s: EDS %s", n.label().c_str(), n.eds_path.c_str());
    size_t warned = cfg.warnings.size(), noted = cfg.notes.size(), failed = errors.size();
    // dcfgen's EDS lint and the prepared copies, then the EDS checks on them.
    bool ok = run_eds_lint(cfg, default_edslint_python(), cfg.work_dir, errors) && check_eds_files(cfg, errors);
    // What the lint and the EDS checks settled (prepared copies, accepted
    // findings, device mappings, kept PDOs).
    for (size_t i = warned; i < cfg.warnings.size(); ++i) log_warn("%s", cfg.warnings[i].c_str());
    for (size_t i = noted; i < cfg.notes.size(); ++i) log_info("%s", cfg.notes[i].c_str());
    for (size_t i = failed; i < errors.size(); ++i) errors[i] = prefix_of(cfg) + errors[i];
    checked = checked && ok;
  }
  if (checked) {
    // The gateway's routes against the upper network's EDS.
    size_t warned = st->set.warnings.size();
    checked = check_gateway_eds(st->set, errors);
    for (size_t i = warned; i < st->set.warnings.size(); ++i) log_warn("%s", st->set.warnings[i].c_str());
  }
  if (!checked) {
    for (const auto& e : errors) log_error("%s", e.c_str());
    log_error("configuration rejected (%zu problem%s); CANopen inactive, CAN interface not opened",
              errors.size(), errors.size() == 1 ? "" : "s");
    return;
  }
  for (auto& cfg : st->set.networks) {
    ScopedLogPrefix prefix(prefix_of(cfg));
    if (cfg.is_slave()) {
      std::string id = cfg.slave.lss ? std::string("from LSS") : std::to_string(cfg.slave.node_id);
      std::string unused = cfg.adapter.simulate ? " (not used: on the simulated bus " + cfg.adapter.interface + ")" : "";
      log_info("loaded %s: %s adapter %s, %u bit/s%s, CANopen slave, node ID %s, %zu bound object%s", path.c_str(),
               cfg.adapter.type.c_str(), cfg.adapter.interface.c_str(), cfg.adapter.bitrate,
               unused.c_str(), id.c_str(),
               cfg.slave.objects.size(), cfg.slave.objects.size() == 1 ? "" : "s");
      continue;
    }
    log_info("loaded %s: %s adapter %s, %u bit/s%s, master node ID %u, %zu slave%s", path.c_str(),
             cfg.adapter.type.c_str(), cfg.adapter.interface.c_str(), cfg.adapter.bitrate,
             cfg.adapter.simulate ? " (not used: the network is simulated)" : "", cfg.master.node_id,
             cfg.nodes.size(), cfg.nodes.size() == 1 ? "" : "s");
    const MasterConfig& m = cfg.master;
    if (m.sync_plc_cycle) {
      unsigned long long tick_us = g_rt.base_tick_ns / 1000;
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

  if (st->set.gateway.enabled) {
    const GatewayConfig& g = st->set.gateway;
    st->gateway.reset(new GatewayLink(st->set));
    log_info("gateway: upper network \"%s\", %zu route%s%s%s%s", st->set.networks[g.upper].network.c_str(),
             g.routes.size(), g.routes.size() == 1 ? "" : "s", g.has_status ? ", node status" : "",
             g.emcy_forward ? ", EMCY forwarding" : "", g.sdo_bridge ? ", SDO bridge" : "");
  }
  for (auto& cfg : st->set.networks) {
    ScopedLogPrefix prefix(prefix_of(cfg));
    std::unique_ptr<NetworkState> net(new NetworkState);
    if (cfg.is_slave()) {
      net->slave = true;
      std::string state_path = slave_state_path(default_slave_state_dir(), cfg.network);
      auto store = std::make_shared<SlaveStore>();
      std::string note;
      load_slave_state(state_path, cfg.slave.eds_sha256, *store, note);
      if (!note.empty()) log_warn("%s", note.c_str());
      else if (!store->saved.empty() || store->lss_id)
        log_info("stored parameters from %s applied after each reset", state_path.c_str());
      net->slave_image.build(cfg);
      if (cfg.adapter.simulate) {
        std::string master;
        for (const auto& other : st->set.networks)
          if (!other.is_slave() && other.adapter.simulate && other.adapter.interface == cfg.adapter.interface)
            master = other.network.empty() ? other.adapter.interface : other.network;
        log_warn("the slave network is SIMULATED (adapter.simulate): no CAN interface is used; it runs on simulated "
                 "bus %s %s", cfg.adapter.interface.c_str(),
                 master.empty() ? "with no master network on it" : ("with master network \"" + master + "\"").c_str());
      }
      if (cfg.master.has_diagnostics) net->hub.reset(new DiagHub(cfg, CANOPEN_PLUGIN_VERSION));
      net->slave_bus.reset(
          new SlaveBus(cfg, net->slave_image, store, state_path, st->gateway.get(), net->hub.get()));
      log_info("%zu input and %zu output objects bound to the PLC image", net->slave_image.input_objects().size(),
               net->slave_image.output_objects().size());
      st->nets.push_back(std::move(net));
      continue;
    }
    size_t failed = errors.size();
    if (!generate_device_config(cfg, default_dcfgen(), net->gen, errors)) {
      for (size_t i = failed; i < errors.size(); ++i) log_error("%s", errors[i].c_str());
      log_error("could not generate the device configuration; CANopen inactive, CAN interface not opened");
      return;
    }
    log_info("device configuration %s in %s", net->gen.reused ? "unchanged, reusing" : "generated",
             net->gen.work_dir.c_str());
    net->image.build(cfg);
    if (cfg.master.sync_plc_cycle && net->image.sync_fd() < 0) {
      log_error("cannot create the PLC-cycle SYNC event (%s); CANopen inactive, CAN interface not opened",
                strerror(errno));
      return;
    }
    // Simulated devices (docs/simulator.md). The simulation file names nodes
    // by node ID alone, so it serves a config with one network only.
    std::shared_ptr<SimSetup> sim;
    if (simulates_anything(cfg)) {
      sim = std::make_shared<SimSetup>();
      sim->store = g_sim_store;
      std::string sim_path = find_sim_file(cfg);
      if (!sim_path.empty() && st->set.several()) {
        log_warn("%s is not used: a simulation file serves a configuration with one network only; the "
                 "simulated devices of this network run with their default behaviour", sim_path.c_str());
      } else if (!sim_path.empty()) {
        if (!canopen_sim::load_sim_file(sim_path, sim->file, errors) || !check_sim_file(cfg, sim->file, errors)) {
          for (const auto& e : errors) log_error("%s", e.c_str());
          log_error("simulation file rejected; CANopen inactive");
          return;
        }
        log_info("simulation file %s", sim_path.c_str());
      }
      std::string shared;
      if (cfg.adapter.simulate && !cfg.adapter.interface.empty())
        for (const auto& other : st->set.networks)
          if (other.is_slave() && other.adapter.simulate && other.adapter.interface == cfg.adapter.interface)
            shared = other.network.empty() ? other.adapter.interface : other.network;
      log_warn("%s", sim_summary(cfg, sim->file, shared).c_str());
      if (cfg.adapter.simulate) sim->tap = std::make_shared<SimTraceTap>();
    }
    net->sim = sim;
    if (cfg.master.has_diagnostics) net->hub.reset(new DiagHub(cfg, CANOPEN_PLUGIN_VERSION));
    net->bus.reset(new Bus(cfg, net->gen, net->image, net->hub.get(), sim, st->gateway.get()));
    log_info("%zu input and %zu output PDO entries bound to the PLC image", net->image.inputs().size(),
             net->image.outputs().size());
    st->nets.push_back(std::move(net));
  }
  if (st->set.networks[0].master.has_diagnostics) {
    std::vector<DiagHub*> hubs;
    for (auto& n : st->nets) hubs.push_back(n->hub.get());
    st->server.reset(new DiagServer(hubs));
    for (size_t i = 0; i < st->nets.size(); ++i)
      if (st->nets[i]->sim && st->nets[i]->sim->tap)
        st->server->set_trace_source(make_sim_trace_source(st->nets[i]->sim->tap), i);
  }
  g_state = std::move(st);
}

}  // namespace

#define PLUGIN_API __attribute__((visibility("default")))

extern "C" {

PLUGIN_API int init(void* args) {
  teardown();
  if (!args) return -1;
  std::memcpy(&g_rt, args, sizeof(g_rt));
  g_have_rt = true;
  set_log_sink(runtime_sink);
  route_lely_diagnostics();
  return 0;
}

PLUGIN_API int start_loop(void) {
  if (!g_have_rt) return -1;
  teardown();
  prepare();
  if (!g_state) return -1;
  for (auto& n : g_state->nets) {
    if (n->bus) n->bus->start();
    if (n->slave_bus) n->slave_bus->start();
  }
  if (g_state->server) g_state->server->start();
  g_exchange.store(true, std::memory_order_release);
  PlcRequests::instance().open(static_cast<unsigned>(g_state->nets.size()));
  return 0;
}

PLUGIN_API void stop_loop(void) {
  g_exchange.store(false, std::memory_order_release);
  PlcRequests::instance().close();
  stop_all();
}

PLUGIN_API void cleanup(void) {
  teardown();
  set_log_sink(nullptr);
  g_have_rt = false;
}

PLUGIN_API void cycle_start(void) {
  if (!g_exchange.load(std::memory_order_acquire)) return;
  for (auto& n : g_state->nets) {
    if (n->slave) {
      n->slave_image.copy_to_plc(g_rt);
      continue;
    }
    n->image.copy_to_plc(g_rt);
    n->image.request_sync();  // PLC-cycle SYNC only
  }
}

PLUGIN_API void cycle_end(void) {
  if (!g_exchange.load(std::memory_order_acquire)) return;
  for (auto& n : g_state->nets) {
    if (n->slave)
      n->slave_image.copy_from_plc(g_rt);
    else
      n->image.copy_from_plc(g_rt);
  }
}

// The SDO function blocks of the PLC program's CANopen library find this with
// dlopen("libcanopen_plugin.so", RTLD_NOLOAD) + dlsym (spec canopen-plc-sdo).
PLUGIN_API const void* canopen_plc_api(uint32_t version) { return plc_api_table(version); }

}  // extern "C"
