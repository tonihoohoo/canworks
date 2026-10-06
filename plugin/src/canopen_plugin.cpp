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
#include "log.h"
#include "plc_api.h"
#include "process_image.h"
#include "runtime_version.h"

using namespace canopen_plugin;

namespace {

plugin_runtime_args_t g_rt;  // copied by value: the runtime frees args after init()
bool g_have_rt = false;

struct PluginState {
  Config cfg;
  GeneratedConfig gen;
  ProcessImage image;
  std::unique_ptr<DiagHub> hub;  // with master.diagnostics only
  std::unique_ptr<DiagServer> server;
  std::unique_ptr<Bus> bus;
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

void teardown() {
  g_exchange.store(false, std::memory_order_release);
  PlcRequests::instance().close();
  if (g_state && g_state->server) g_state->server->stop();
  if (g_state && g_state->bus) g_state->bus->stop();
  g_state.reset();
}

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

  std::vector<std::string> errors;
  bool loaded = load_config(path, limits, st->cfg, errors);
  for (const auto& w : st->cfg.warnings) log_warn("%s", w.c_str());
  for (const auto& m : st->cfg.notes) log_info("%s", m.c_str());
  if (loaded)
    for (const auto& n : st->cfg.nodes) log_info("%s: EDS %s", n.label().c_str(), n.eds_path.c_str());
  size_t warned = st->cfg.warnings.size(), noted = st->cfg.notes.size();
  // dcfgen's EDS lint and the prepared copies, then the EDS checks on them.
  bool checked = loaded &&
                 run_eds_lint(st->cfg, default_edslint_python(), st->cfg.config_dir + "/.canopen", errors) &&
                 check_eds_files(st->cfg, errors);
  // What the lint and the EDS checks settled (prepared copies, accepted
  // findings, device mappings, kept PDOs).
  for (size_t i = warned; i < st->cfg.warnings.size(); ++i) log_warn("%s", st->cfg.warnings[i].c_str());
  for (size_t i = noted; i < st->cfg.notes.size(); ++i) log_info("%s", st->cfg.notes[i].c_str());
  if (!checked) {
    for (const auto& e : errors) log_error("%s", e.c_str());
    log_error("configuration rejected (%zu problem%s); CANopen inactive, CAN interface not opened",
              errors.size(), errors.size() == 1 ? "" : "s");
    return;
  }
  log_info("loaded %s: %s adapter %s, %u bit/s, master node ID %u, %zu slave%s", path.c_str(),
           st->cfg.adapter.type.c_str(), st->cfg.adapter.interface.c_str(), st->cfg.adapter.bitrate,
           st->cfg.master.node_id, st->cfg.nodes.size(),
           st->cfg.nodes.size() == 1 ? "" : "s");
  const MasterConfig& m = st->cfg.master;
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

  if (!generate_device_config(st->cfg, default_dcfgen(), st->gen, errors)) {
    for (const auto& e : errors) log_error("%s", e.c_str());
    log_error("could not generate the device configuration; CANopen inactive, CAN interface not opened");
    return;
  }
  log_info("device configuration %s in %s", st->gen.reused ? "unchanged, reusing" : "generated",
           st->gen.work_dir.c_str());

  st->image.build(st->cfg);
  if (m.sync_plc_cycle && st->image.sync_fd() < 0) {
    log_error("cannot create the PLC-cycle SYNC event (%s); CANopen inactive, CAN interface not opened",
              strerror(errno));
    return;
  }
  if (st->cfg.master.has_diagnostics) {
    st->hub.reset(new DiagHub(st->cfg, CANOPEN_PLUGIN_VERSION));
    st->server.reset(new DiagServer(*st->hub));
  }
  st->bus.reset(new Bus(st->cfg, st->gen, st->image, st->hub.get()));
  log_info("%zu input and %zu output PDO entries bound to the PLC image", st->image.inputs().size(),
           st->image.outputs().size());
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
  g_state->bus->start();
  if (g_state->server) g_state->server->start();
  g_exchange.store(true, std::memory_order_release);
  PlcRequests::instance().open();
  return 0;
}

PLUGIN_API void stop_loop(void) {
  g_exchange.store(false, std::memory_order_release);
  PlcRequests::instance().close();
  if (g_state && g_state->server) g_state->server->stop();
  if (g_state && g_state->bus) g_state->bus->stop();
}

PLUGIN_API void cleanup(void) {
  teardown();
  set_log_sink(nullptr);
  g_have_rt = false;
}

PLUGIN_API void cycle_start(void) {
  if (!g_exchange.load(std::memory_order_acquire)) return;
  g_state->image.copy_to_plc(g_rt);
  g_state->image.request_sync();  // PLC-cycle SYNC only
}

PLUGIN_API void cycle_end(void) {
  if (!g_exchange.load(std::memory_order_acquire)) return;
  g_state->image.copy_from_plc(g_rt);
}

// The SDO function blocks of the PLC program's CANopen library find this with
// dlopen("libcanopen_plugin.so", RTLD_NOLOAD) + dlsym (spec canopen-plc-sdo).
PLUGIN_API const void* canopen_plc_api(uint32_t version) { return plc_api_table(version); }

}  // extern "C"
