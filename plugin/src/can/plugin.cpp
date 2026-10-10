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

#include "can_plc_api.h"
#include "config.h"
#include "engine.h"
#include "log.h"
#include "runtime_version.h"
#if CANWORKS_WITH_CANOPEN
#include "canopen_runtime.h"
#endif

using namespace canopen_plugin;

namespace {

plugin_runtime_args_t g_rt;  // copied by value: the runtime frees args after init()
bool g_have_rt = false;

std::unique_ptr<Engine> g_engine;
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
  g_engine.reset();
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

// Loads the config, checks it and makes the networks. Sets g_engine on
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
  ImageLimits limits;
  limits.buffer_size = g_rt.buffer_size > 0 ? static_cast<unsigned>(g_rt.buffer_size) : 1024;
  const char* force = getenv("CANWORKS_FORCE_SIMULATE");
  limits.force_simulate = force_simulate_from_env(force);
  if (force && *force && !limits.force_simulate)
    log_warn("CANWORKS_FORCE_SIMULATE=\"%.32s\" is ignored: only 1 forces simulation", force);
  std::unique_ptr<Engine> e(new Engine);
  if (e->prepare(path, limits, g_rt.base_tick_ns, CANWORKS_PLUGIN_VERSION)) g_engine = std::move(e);
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
  if (!g_engine) return -1;
  g_engine->start();
  g_exchange.store(true, std::memory_order_release);
  return 0;
}

PLUGIN_API void stop_loop(void) {
  g_exchange.store(false, std::memory_order_release);
  if (g_engine) g_engine->stop();
}

PLUGIN_API void cleanup(void) {
  teardown();
  set_log_sink(nullptr);
  g_have_rt = false;
}

PLUGIN_API void cycle_start(void) {
  if (!g_exchange.load(std::memory_order_acquire)) return;
  g_engine->cycle_start(g_rt);
}

PLUGIN_API void cycle_end(void) {
  if (!g_exchange.load(std::memory_order_acquire)) return;
  g_engine->cycle_end(g_rt);
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
