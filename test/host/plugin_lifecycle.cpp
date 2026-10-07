// plugin_lifecycle.cpp - the plugin's entry points as the runtime calls them
// (core/src/drivers/plugin_driver.c): init() for every plugin in plugins.conf,
// enabled or not; start_loop() only for enabled ones.
//
//   plugin_lifecycle <libcanopen_plugin.so> <scratch dir>
//
// With a config whose EDS is missing (what the last CANopen upload leaves next
// to the library once a project without CANopen is uploaded), a disabled
// plugin, init() only, must log nothing; an enabled one, init() then
// start_loop(), must reject the config with an error and not start.
// With no config file at the configured path, or no path at all, an enabled
// plugin warns, opens no CAN interface, and its scan hooks do nothing.
// With a simulated network (adapter.simulate), the plugin runs the master and
// its simulated devices without any CAN interface, and says so at start.

#include <dlfcn.h>

#include <chrono>
#include <mutex>
#include <thread>

#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <memory>
#include <string>
#include <vector>

#include "fake_runtime.hpp"

// The runtime's own base tick (core/src/plc_app/utils/utils.c), exported as
// the runtime exports it (-rdynamic).
extern "C" uint64_t base_tick_ns;
__attribute__((visibility("default"))) uint64_t base_tick_ns = 20000000ULL;

namespace {

std::vector<std::string> g_logs;
std::mutex g_mutex;  // the plugin logs from its bus thread too

void vlog(const char* level, const char* fmt, va_list ap) {
  char buf[1024];
  std::vsnprintf(buf, sizeof(buf), fmt, ap);
  std::lock_guard<std::mutex> lock(g_mutex);
  g_logs.push_back(std::string(level) + " " + buf);
  std::fprintf(stderr, "    [%s] %s\n", level, buf);
}
void log_i(const char* fmt, ...) { va_list ap; va_start(ap, fmt); vlog("INFO", fmt, ap); va_end(ap); }
void log_d(const char* fmt, ...) { va_list ap; va_start(ap, fmt); vlog("DEBUG", fmt, ap); va_end(ap); }
void log_w(const char* fmt, ...) { va_list ap; va_start(ap, fmt); vlog("WARN", fmt, ap); va_end(ap); }
void log_e(const char* fmt, ...) { va_list ap; va_start(ap, fmt); vlog("ERROR", fmt, ap); va_end(ap); }

int g_failures = 0;
void expect(bool ok, const char* what) {
  std::printf("%s %s\n", ok ? "ok  " : "FAIL", what);
  if (!ok) ++g_failures;
}

bool logged(const char* text) {
  std::lock_guard<std::mutex> lock(g_mutex);
  for (const auto& l : g_logs)
    if (l.find(text) != std::string::npos) return true;
  return false;
}

template <typename F>
F sym(void* h, const char* name) {
  F f = reinterpret_cast<F>(dlsym(h, name));
  if (!f) {
    std::fprintf(stderr, "plugin_lifecycle: %s not exported: %s\n", name, dlerror());
    std::exit(2);
  }
  return f;
}

}  // namespace

int main(int argc, char** argv) {
  if (argc != 3) {
    std::fprintf(stderr, "usage: %s <libcanopen_plugin.so> <scratch dir>\n", argv[0]);
    return 2;
  }
  const std::string config = std::string(argv[2]) + "/canopen.json";
  {
    std::ofstream f(config);
    f << R"({"schema_version": 1,
             "adapter": {"type": "socketcan", "interface": "vcan0", "bitrate": 125000},
             "master": {"node_id": 1, "sync_period_us": 100000},
             "nodes": [{"node_id": 5, "name": "rtd", "eds": "canopen/eds/missing.eds",
                        "tx_pdos": [{"entries": [{"index": "0x7130", "subindex": 1, "type": "INTEGER16",
                                                  "iec_location": "%IW100"}]}]}]})";
  }

  void* h = dlopen(argv[1], RTLD_NOW | RTLD_LOCAL);
  if (!h) {
    std::fprintf(stderr, "plugin_lifecycle: %s\n", dlerror());
    return 2;
  }
  auto init = sym<int (*)(void*)>(h, "init");
  auto start_loop = sym<int (*)()>(h, "start_loop");
  auto cleanup = sym<void (*)()>(h, "cleanup");
  auto cycle_start = sym<void (*)()>(h, "cycle_start");
  auto cycle_end = sym<void (*)()>(h, "cycle_end");

  std::unique_ptr<fake_runtime::Image> img(new fake_runtime::Image);
  auto args = [&](const std::string& path) {
    std::unique_ptr<plugin_runtime_args_t> rt(new plugin_runtime_args_t);
    fake_runtime::attach(*img, *rt);
    std::snprintf(rt->plugin_specific_config_file_path, sizeof(rt->plugin_specific_config_file_path), "%s",
                  path.c_str());
    rt->log_info = log_i;
    rt->log_debug = log_d;
    rt->log_warn = log_w;
    rt->log_error = log_e;
    return rt;
  };

  std::printf("disabled plugin (init only):\n");
  auto rt = args(config);
  expect(init(rt.get()) == 0, "init returns 0");
  rt.reset();  // the runtime frees the args after init
  expect(g_logs.empty(), "nothing logged");
  cleanup();

  std::printf("enabled plugin (init, then start_loop):\n");
  g_logs.clear();
  rt = args(config);
  expect(init(rt.get()) == 0, "init returns 0");
  rt.reset();
  expect(start_loop() != 0, "start_loop reports that CANopen did not start");
  expect(logged("ERROR") && logged("missing.eds"), "an error names the missing EDS");
  expect(logged("configuration rejected"), "the config is rejected");
  cleanup();

  const std::string absent = std::string(argv[2]) + "/absent/canopen.json";
  std::printf("enabled plugin, no config file at the configured path:\n");
  g_logs.clear();
  rt = args(absent);
  expect(init(rt.get()) == 0, "init returns 0");
  rt.reset();
  expect(start_loop() != 0, "start_loop reports that CANopen did not start");
  expect(logged("WARN") && logged(absent.c_str()) && logged("CANopen inactive"),
         "a warning names the expected path");
  expect(!logged("ERROR") && !logged("vcan0"), "no error, no CAN interface opened");
  cycle_start();
  cycle_end();
  cleanup();

  std::printf("enabled plugin, no config path in plugins.conf:\n");
  g_logs.clear();
  rt = args("");
  expect(init(rt.get()) == 0, "init returns 0");
  rt.reset();
  expect(start_loop() != 0, "start_loop reports that CANopen did not start");
  expect(logged("WARN") && logged("no configuration file given"), "a warning says no config was given");
  expect(!logged("ERROR"), "no error");
  cycle_start();
  cycle_end();
  cleanup();

  // A simulated network: no interface, the ping-pong node simulated, its
  // TPDO object following the program's output.
  auto stop_loop = sym<void (*)()>(h, "stop_loop");
  const std::string sim_dir = std::string(argv[2]) + "/simulated";
  if (std::system(("mkdir -p '" + sim_dir + "'").c_str()) != 0) expect(false, "scratch dir");
  {
    std::ifstream in(std::string(PINGPONG_DIR) + "/cpp-slave.eds", std::ios::binary);
    std::ofstream out(sim_dir + "/cpp-slave.eds", std::ios::binary);
    out << in.rdbuf();
  }
  unsigned mid = 0;
  long long stop_ms = 0;
  auto run_simulated = [&](const std::string& node_extra, int seconds, unsigned& last,
                           const std::string& adapter_extra = R"(, "simulate": true)") {
    {
      std::ofstream f(sim_dir + "/canopen.json");
      f << R"({"schema_version": 1,
               "adapter": {"type": "socketcan", "interface": "nonexistent0", "bitrate": 125000)"
        << adapter_extra << R"(},
               "master": {"node_id": 1, "sync_period_us": 20000},
               "nodes": [{"node_id": 2, "name": "pingpong", "eds": "cpp-slave.eds", "heartbeat_ms": 50,)"
        << node_extra << R"( "status_location": "%IX10.0",
                          "tx_pdos": [{"entries": [{"index": "0x4001", "type": "UNSIGNED32", "iec_location": "%ID100"}]}],
                          "rx_pdos": [{"entries": [{"index": "0x4000", "type": "UNSIGNED32", "iec_location": "%QD100"}]}]}]})";
      std::ofstream s(sim_dir + "/simulation.json");
      s << R"({"nodes": {"2": {"sources": {"0x4001": {"expr": "[0x4000]"}}}}})";
    }
    g_logs.clear();
    img.reset(new fake_runtime::Image);
    rt = args(sim_dir + "/canopen.json");
    expect(init(rt.get()) == 0, "init returns 0");
    rt.reset();
    expect(start_loop() == 0, "start_loop starts CANopen");
    for (int i = 0; i < seconds * 100; ++i) {
      cycle_start();
      img->dint_out[100] = img->dint_in[100] + 1;
      cycle_end();
      std::this_thread::sleep_for(std::chrono::milliseconds(10));
      if (i == (seconds - 1) * 100) mid = img->dint_in[100];
    }
    last = img->dint_in[100];
    bool status = img->bool_in[10][0] != 0;
    auto t = std::chrono::steady_clock::now();
    stop_loop();
    stop_ms = std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now() - t).count();
    cleanup();
    return status;
  };
  // Long enough for more frames than a virtual bus channel queues (1024):
  // a channel nobody reads would block the bus by then.
  std::printf("simulated network, every node simulated:\n");
  unsigned last = 0;
  bool status = run_simulated("", 10, last);
  expect(logged("WARN") && logged("the CAN network is SIMULATED") && logged("simulated nodes: 2"),
         "a warning names what is simulated");
  expect(logged("simulation file "), "the simulation file is loaded");
  expect(status && last > 5, "the node is operational and the round trip runs");
  expect(last > mid, "the round trip still runs after 1024 frames on the bus");
  expect(stop_ms < 3000, "stop_loop returns promptly");
  expect(!logged("nonexistent0: ") && !logged("ERROR"), "no CAN interface touched, no error");

  std::printf("simulated network, the node not simulated:\n");
  status = run_simulated(R"( "simulate": false,)", 2, last);
  expect(logged("no node is simulated"), "the warning says no node is simulated");
  expect(!status, "the node stays absent");

  // The local simulator runtime image: a real-adapter config runs simulated.
  std::printf("simulation forced by the environment:\n");
  setenv("CANOPEN_FORCE_SIMULATE", "1", 1);
  status = run_simulated("", 3, last, "");
  unsetenv("CANOPEN_FORCE_SIMULATE");
  expect(logged("WARN") && logged("simulation forced by the runtime environment"), "a warning says simulation is forced");
  expect(logged("the CAN network is SIMULATED"), "the network is announced as simulated");
  expect(status && last > 5, "the node is operational and the round trip runs");
  expect(!logged("nonexistent0: ") && !logged("ERROR"), "no CAN interface touched, no error");

  // Several simulated networks and a version 2 simulation file: each
  // section drives its own network's devices only.
  auto run_two = [&](const std::string& sim_json, int seconds) {
    {
      std::ofstream f(sim_dir + "/canopen.json");
      f << R"({"schema_version": 2, "networks": [
               {"name": "io", "adapter": {"type": "socketcan", "interface": "sim0", "bitrate": 125000, "simulate": true},
                "master": {"node_id": 1, "sync_period_us": 20000},
                "nodes": [{"node_id": 2, "name": "a", "eds": "cpp-slave.eds", "heartbeat_ms": 50, "status_location": "%IX10.0",
                           "tx_pdos": [{"entries": [{"index": "0x4001", "type": "UNSIGNED32", "iec_location": "%ID100"}]}],
                           "rx_pdos": [{"entries": [{"index": "0x4000", "type": "UNSIGNED32", "iec_location": "%QD100"}]}]}]},
               {"name": "line", "adapter": {"type": "socketcan", "interface": "sim1", "bitrate": 125000, "simulate": true},
                "master": {"node_id": 1, "sync_period_us": 20000},
                "nodes": [{"node_id": 2, "name": "b", "eds": "cpp-slave.eds", "heartbeat_ms": 50, "status_location": "%IX10.1",
                           "tx_pdos": [{"entries": [{"index": "0x4001", "type": "UNSIGNED32", "iec_location": "%ID101"}]}]}]}]})";
      std::ofstream s(sim_dir + "/simulation.json");
      s << sim_json;
    }
    g_logs.clear();
    img.reset(new fake_runtime::Image);
    rt = args(sim_dir + "/canopen.json");
    expect(init(rt.get()) == 0, "init returns 0");
    rt.reset();
    bool started = start_loop() == 0;
    for (int i = 0; started && i < seconds * 100; ++i) {
      cycle_start();
      img->dint_out[100] = img->dint_in[100] + 1;
      cycle_end();
      std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }
    if (started) stop_loop();
    cleanup();
    return started;
  };
  std::printf("two simulated networks, a version 2 simulation file:\n");
  bool started = run_two(R"({"schema_version": 2, "networks": {
                              "io": {"nodes": {"2": {"sources": {"0x4001": {"expr": "[0x4000]"}}}}},
                              "line": {"nodes": {"2": {"sources": {"0x4001": {"constant": 777}}}}}}})", 3);
  expect(started, "start_loop starts CANopen");
  expect(logged("section \"io\"") && logged("section \"line\""), "each network uses its own section");
  expect(img->dint_in[100] > 5, "network io: node 2 follows its section (round trip)");
  expect(img->dint_in[101] == 777, "network line: node 2 follows its own section (constant 777)");
  expect(!logged("ERROR"), "no error");

  std::printf("two simulated networks, a section for a network not in the config:\n");
  started = run_two(R"({"schema_version": 2, "networks": {"drives": {}}})", 0);
  expect(!started, "start_loop reports that CANopen did not start");
  expect(logged("networks.drives: there is no network \"drives\"") && logged("networks: io, line"),
         "the error names the section and the config's networks");

  std::printf("two simulated networks, a version 1 simulation file:\n");
  started = run_two(R"({"nodes": {"2": {"sources": {"0x4001": {"constant": 777}}}}})", 2);
  expect(started, "start_loop starts CANopen");
  expect(logged("WARN") && logged("is not used: a version 1 simulation file") && logged("version 2"),
         "a warning says the version 1 file is not used and names version 2");
  expect(img->dint_in[101] != 777, "the devices run with their default behaviour");

  // The first init() after an upload carries the runtime's 20 ms default
  // tick; the program's tasks are read before start_loop().
  std::printf("PLC-cycle SYNC, base tick read at start_loop:\n");
  {
    std::ofstream f(sim_dir + "/canopen.json");
    f << R"({"schema_version": 1,
             "adapter": {"type": "socketcan", "interface": "nonexistent0", "bitrate": 125000, "simulate": true},
             "master": {"node_id": 1, "sync_source": "plc_cycle"},
             "nodes": [{"node_id": 2, "name": "pingpong", "eds": "cpp-slave.eds",
                        "tx_pdos": [{"entries": [{"index": "0x4001", "type": "UNSIGNED32", "iec_location": "%ID100"}]}]}]})";
  }
  g_logs.clear();
  base_tick_ns = 20000000ULL;
  rt = args(sim_dir + "/canopen.json");
  rt->base_tick_ns = base_tick_ns;
  expect(init(rt.get()) == 0, "init returns 0");
  rt.reset();
  base_tick_ns = 10000000ULL;  // symbols_init: a 10 ms task
  expect(start_loop() == 0, "start_loop starts CANopen");
  expect(logged("(base tick 10000 us)"), "the master uses the program's base tick");
  stop_loop();
  cleanup();

  std::printf(g_failures ? "%d failure(s)\n" : "OK\n", g_failures);
  return g_failures ? 1 : 0;
}
