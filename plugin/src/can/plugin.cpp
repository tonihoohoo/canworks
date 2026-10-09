// plugin.cpp - OpenPLC Runtime v4 native plugin entry points.
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
// still names the config of the last canworks upload, so init() only keeps the
// runtime's args, and start_loop() loads and checks the config: a project
// without canworks networks logs nothing from this plugin.
//
// cycle_start()/cycle_end() run on the runtime's dispatcher thread without
// the image lock held (core/src/plc_app/plc_state_manager.cpp): cycle_start
// before the fastest task's frame is released, cycle_end after the frame's
// outputs were drained into the image. They only touch preallocated memory.

#include <dlfcn.h>

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

#include "config.h"
#include "diag.h"
#include "log.h"
#include "runtime_version.h"
#include "network_runtime.h"
#include "raw/raw_runtime.h"
#if CANWORKS_WITH_CANOPEN
#include "canopen_runtime.h"
#endif
#if CANWORKS_WITH_J1939
#include "j1939_runtime.h"
#endif

using namespace canopen_plugin;

namespace {

plugin_runtime_args_t g_rt;  // copied by value: the runtime frees args after init()
bool g_have_rt = false;

struct PluginState {
  ConfigSet set;
#if CANWORKS_WITH_CANOPEN
  std::shared_ptr<CanopenShared> canopen;  // the gateway link; outlives the networks
#endif
  // Each network's raw CAN path (raw messages, program frames); destroyed
  // after nets, whose plain CAN networks point into it.
  std::vector<std::unique_ptr<canworks_raw::RawRuntime>> raws;
  std::vector<std::unique_ptr<NetworkRuntime>> nets;  // one per network, in config order
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

void open_plc_requests(const ConfigSet& set) {
#if CANWORKS_WITH_CANOPEN
  canopen_open_plc_requests(set);
#else
  (void)set;
#endif
}

void close_plc_requests() {
#if CANWORKS_WITH_CANOPEN
  canopen_close_plc_requests();
#endif
}

void stop_all() {
  if (!g_state) return;
  if (g_state->server) g_state->server->stop();
  for (auto& r : g_state->raws) r->stop();
  for (auto& n : g_state->nets) n->stop();
}

void teardown() {
  g_exchange.store(false, std::memory_order_release);
  close_plc_requests();
  stop_all();
  if (g_state) {
    g_state->server.reset();
    g_state->nets.clear();  // before the gateway link they use
    g_state->raws.clear();
  }
  g_state.reset();
}

// The first init() after an upload runs before the runtime has read the
// program's tasks, so its args carry the 20 ms default base tick
// (plugin_driver.c). By start_loop() the runtime's own variable holds the
// real one; the runtime is linked with -rdynamic, so it can be looked up.
void refresh_base_tick() {
  const void* p = dlsym(RTLD_DEFAULT, "base_tick_ns");
  if (!p) return;
  uint64_t ns = *static_cast<const uint64_t*>(p);
  if (ns) g_rt.base_tick_ns = ns;
}

std::string prefix_of(const Config& cfg) { return cfg.log_prefix.empty() ? "" : cfg.log_prefix + ": "; }

// Loads the config, checks it and makes the networks. Sets g_state on
// success; logs why not otherwise.
void prepare() {
  std::string path = g_rt.plugin_specific_config_file_path;
  if (path.empty()) {
    log_warn("no configuration file given in plugins.conf; canworks inactive");
    return;
  }
  if (access(path.c_str(), F_OK) != 0) {
    log_warn("no configuration at %s; canworks inactive", path.c_str());
    return;
  }
  std::string mismatch = runtime_version_problem(CANWORKS_PREFIX "/lib/runtime-version", getenv("RUNTIME_VERSION"));
  if (!mismatch.empty()) {
    log_error("%s; canworks inactive, CAN interface not opened", mismatch.c_str());
    return;
  }
  log_info("protocols built in: %s", built_in_protocols().c_str());
  auto st = std::unique_ptr<PluginState>(new PluginState);
  ImageLimits limits;
  limits.buffer_size = g_rt.buffer_size > 0 ? static_cast<unsigned>(g_rt.buffer_size) : 1024;
  limits.force_simulate = force_simulate_from_env(getenv("CANWORKS_FORCE_SIMULATE"));

  std::vector<std::string> errors;
  bool loaded = load_config_set(path, limits, st->set, errors);
  for (const auto& w : st->set.warnings) log_warn("%s", w.c_str());
  for (const auto& m : st->set.notes) log_info("%s", m.c_str());
  for (auto& cfg : st->set.networks) {
    ScopedLogPrefix prefix(prefix_of(cfg));
    for (const auto& w : cfg.warnings) log_warn("%s", w.c_str());
    for (const auto& m : cfg.notes) log_info("%s", m.c_str());
  }
  // Every network is checked before any interface opens: an error in any of
  // them leaves every network inactive (canopen-networks spec).
  bool checked = loaded;
#if CANWORKS_WITH_CANOPEN
  if (checked) checked = canopen_check(st->set, errors);
#endif
  if (!checked) {
    for (const auto& e : errors) log_error("%s", e.c_str());
    log_error("configuration rejected (%zu problem%s); canworks inactive, CAN interface not opened",
              errors.size(), errors.size() == 1 ? "" : "s");
    return;
  }
  for (auto& cfg : st->set.networks) {
    if (cfg.is_plain()) {
      canworks_raw::log_plain_loaded(st->set, cfg);
      continue;
    }
#if CANWORKS_WITH_J1939
    if (cfg.is_j1939()) {
      j1939_log_loaded(st->set, cfg);
      continue;
    }
#endif
#if CANWORKS_WITH_CANOPEN
    canopen_log_loaded(st->set, cfg, g_rt.base_tick_ns);
#endif
  }

  // The raw paths first: a simulated CANopen network's bus thread serves
  // the bridge its raw path registers.
  for (auto& cfg : st->set.networks) {
    ScopedLogPrefix prefix(prefix_of(cfg));
    std::unique_ptr<canworks_raw::RawRuntime> raw(new canworks_raw::RawRuntime(cfg));
    if (!raw->make(st->set, errors)) {
      for (const auto& e : errors) log_error("%s", e.c_str());
      log_error("raw CAN of this network rejected; canworks inactive, CAN interface not opened");
      return;
    }
    st->raws.push_back(std::move(raw));
  }
  st->nets.resize(st->set.networks.size());
  for (size_t i = 0; i < st->set.networks.size(); ++i)
    if (st->set.networks[i].is_plain()) st->nets[i] = canworks_raw::make_plain_runtime(st->raws[i].get(), CANWORKS_PLUGIN_VERSION);
#if CANWORKS_WITH_CANOPEN
  if (!canopen_create(st->set, g_rt.base_tick_ns, CANWORKS_PLUGIN_VERSION, st->canopen, st->nets)) return;
#endif
#if CANWORKS_WITH_J1939
  j1939_create(st->set, CANWORKS_PLUGIN_VERSION, st->nets);
#endif
  for (auto& n : st->nets)
    if (!n) {  // the parser refuses protocols not built in; never here
      log_error("a network has no runtime; canworks inactive");
      return;
    }
  if (st->set.networks[0].master.has_diagnostics) {
    std::vector<DiagHub*> hubs;
    for (size_t i = 0; i < st->nets.size(); ++i) {
      DiagHub* h = st->nets[i]->hub();
      hubs.push_back(h);
      canworks_raw::RawRuntime* raw = st->raws[i].get();
      if (h && !st->set.networks[i].is_plain()) h->set_raw_status([raw] { return raw->status(); });
    }
    st->server.reset(new DiagServer(hubs));
    for (size_t i = 0; i < st->nets.size(); ++i) {
      if (auto src = st->nets[i]->trace_source()) st->server->set_trace_source(std::move(src), i);
      if (auto inj = st->nets[i]->frame_injector()) st->server->set_frame_injector(inj, i);
    }
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
#if CANWORKS_WITH_CANOPEN
  canopen_init_logging();
#endif
  return 0;
}

PLUGIN_API int start_loop(void) {
  if (!g_have_rt) return -1;
  refresh_base_tick();
  teardown();
  prepare();
  if (!g_state) return -1;
  for (auto& n : g_state->nets) n->start();
  for (auto& r : g_state->raws) r->start();
  if (g_state->server) g_state->server->start();
  g_exchange.store(true, std::memory_order_release);
  open_plc_requests(g_state->set);
  return 0;
}

PLUGIN_API void stop_loop(void) {
  g_exchange.store(false, std::memory_order_release);
  close_plc_requests();
  stop_all();
}

PLUGIN_API void cleanup(void) {
  teardown();
  set_log_sink(nullptr);
  g_have_rt = false;
}

PLUGIN_API void cycle_start(void) {
  if (!g_exchange.load(std::memory_order_acquire)) return;
  for (auto& n : g_state->nets) n->cycle_start(g_rt);
  for (auto& r : g_state->raws) r->cycle_start(g_rt);
}

PLUGIN_API void cycle_end(void) {
  if (!g_exchange.load(std::memory_order_acquire)) return;
  for (auto& n : g_state->nets) n->cycle_end(g_rt);
  for (auto& r : g_state->raws) r->cycle_end(g_rt);
}

// The SDO function blocks of the PLC program's CANopen library find this with
// dlopen("libcanworks_plugin.so", RTLD_NOLOAD) + dlsym (spec canopen-plc-sdo).
// Without CANopen built in there is no table; the blocks report that.
PLUGIN_API const void* canopen_plc_api(uint32_t version) {
#if CANWORKS_WITH_CANOPEN
  return canopen_plc_api_table(version);
#else
  (void)version;
  return nullptr;
#endif
}

// The PLC program's CAN_* frame blocks find this the same way
// (spec can-plc-frames, can_plc_api.h).
PLUGIN_API const void* canworks_can_api(uint32_t version) { return canworks_can_api_table(version); }

}  // extern "C"
