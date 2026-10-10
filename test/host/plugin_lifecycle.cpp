// plugin_lifecycle.cpp - the plugin's entry points as the runtime calls them
// (core/src/drivers/plugin_driver.c): init() for every plugin in plugins.conf,
// enabled or not; start_loop() only for enabled ones.
//
//   plugin_lifecycle <libcanworks_plugin.so> <scratch dir>
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

#include "can/can_plc_api.h"
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

int count_logged(const char* text) {
  std::lock_guard<std::mutex> lock(g_mutex);
  int n = 0;
  for (const auto& l : g_logs)
    if (l.find(text) != std::string::npos) ++n;
  return n;
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
    std::fprintf(stderr, "usage: %s <libcanworks_plugin.so> <scratch dir>\n", argv[0]);
    return 2;
  }
  const std::string config = std::string(argv[2]) + "/canworks.json";
  {
    std::ofstream f(config);
    f << R"({"schema_version": 1,
             "adapter": {"type": "socketcan", "interface": "vcan0", "bitrate": 125000},
             "master": {"node_id": 1, "sync_period_us": 100000},
             "nodes": [{"node_id": 5, "name": "rtd", "eds": "canworks/eds/missing.eds",
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

  const std::string absent = std::string(argv[2]) + "/absent/canworks.json";
  std::printf("enabled plugin, no config file at the configured path:\n");
  g_logs.clear();
  rt = args(absent);
  expect(init(rt.get()) == 0, "init returns 0");
  rt.reset();
  expect(start_loop() != 0, "start_loop reports that canworks did not start");
  expect(logged("WARN") && logged(absent.c_str()) && logged("canworks inactive"),
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
      std::ofstream f(sim_dir + "/canworks.json");
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
    rt = args(sim_dir + "/canworks.json");
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
  setenv("CANWORKS_FORCE_SIMULATE", "1", 1);
  status = run_simulated("", 3, last, "");
  unsetenv("CANWORKS_FORCE_SIMULATE");
  expect(logged("WARN") && logged("simulation forced by the runtime environment"), "a warning says simulation is forced");
  expect(logged("the CAN network is SIMULATED"), "the network is announced as simulated");
  expect(status && last > 5, "the node is operational and the round trip runs");
  expect(!logged("nonexistent0: ") && !logged("ERROR"), "no CAN interface touched, no error");
  std::printf("CANWORKS_FORCE_SIMULATE with another value:\n");
  setenv("CANWORKS_FORCE_SIMULATE", "yes", 1);
  run_simulated("", 1, last);
  unsetenv("CANWORKS_FORCE_SIMULATE");
  expect(logged("WARN") && logged("CANWORKS_FORCE_SIMULATE=\"yes\" is ignored"), "a warning says the value is ignored");
  expect(!logged("simulation forced by the runtime environment"), "simulation is not forced");

  // Several simulated networks and a version 2 simulation file: each
  // section drives its own network's devices only.
  auto run_two = [&](const std::string& sim_json, int seconds) {
    {
      std::ofstream f(sim_dir + "/canworks.json");
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
    rt = args(sim_dir + "/canworks.json");
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

  // A gateway with the upper master as a network of the same config on the
  // upper network's simulated bus (the virtual example's "host"): routes
  // run both ways, field status goes up, and the stand-in is not a field
  // network, so nothing echoes back up.
  std::printf("gateway with the upper master's stand-in on its simulated bus:\n");
  {
    {
      std::ifstream in(std::string(PINGPONG_DIR) + "/../gateway/openplc-gateway.eds", std::ios::binary);
      std::ofstream out(sim_dir + "/openplc-gateway.eds", std::ios::binary);
      out << in.rdbuf();
    }
    std::ofstream f(sim_dir + "/canworks.json");
    f << R"({"schema_version": 2, "networks": [
      {"name": "field", "adapter": {"type": "socketcan", "interface": "sim0", "bitrate": 125000, "simulate": true},
       "master": {"node_id": 1, "sync_period_us": 20000},
       "nodes": [{"node_id": 2, "name": "pingpong", "eds": "cpp-slave.eds", "heartbeat_ms": 50, "state_location": "%IB40",
                  "tx_pdos": [{"entries": [{"index": "0x4001", "type": "UNSIGNED32", "iec_location": "%ID40"}]}],
                  "rx_pdos": [{"entries": [{"index": "0x4000", "type": "UNSIGNED32"}]}]}]},
      {"name": "top", "role": "slave", "adapter": {"type": "socketcan", "interface": "sim1", "bitrate": 250000, "simulate": true},
       "slave": {"node_id": 20, "eds": "openplc-gateway.eds",
                 "objects": [{"index": "0x2100", "subindex": 1, "iec_location": "%QX300.0"}],
                 "comm_ok_location": "%IX300.1", "emcy_code_location": "%QW300", "error_register_location": "%QB300"}},
      {"name": "host", "adapter": {"type": "socketcan", "interface": "sim1", "bitrate": 250000, "simulate": true},
       "master": {"node_id": 1, "heartbeat_ms": 50},
       "nodes": [{"node_id": 20, "name": "gateway", "eds": "openplc-gateway.eds", "simulate": false, "state_location": "%IB41",
                  "tx_pdos": [{"number": 1, "entries": [
                                 {"index": "0x2100", "subindex": 1, "type": "BOOLEAN", "iec_location": "%IX20.0"},
                                 {"index": "0x2101", "subindex": 1, "type": "UNSIGNED32", "iec_location": "%ID20"}]},
                              {"number": 2, "entries": [
                                 {"index": "0x5E10", "subindex": 1, "type": "UNSIGNED32", "iec_location": "%ID21"}]}],
                  "rx_pdos": [{"number": 1, "entries": [
                                 {"index": "0x2000", "subindex": 1, "type": "UNSIGNED32", "iec_location": "%QD20"}]}]}]}],
      "gateway": {"upper": "top",
        "routes": [
          {"slave": {"index": "0x2101", "subindex": 1}, "field": {"network": "field", "node": 2, "index": "0x4001"}, "name": "pong"},
          {"slave": {"index": "0x2000", "subindex": 1}, "field": {"network": "field", "node": 2, "index": "0x4000"}, "name": "ping"}],
        "status": {"index": "0x5E00"}, "emcy_forward": true, "sdo_bridge": true}})";
    f.close();
    {
      // The simulated ping-pong device answers like the Lely slave: 0x4001 follows 0x4000.
      std::ofstream sf(sim_dir + "/simulation.json");
      sf << R"({"schema_version": 2, "networks": {"field": {"nodes": {"2": {"sources": {"0x4001": {"expr": "[0x4000]"}}}}}}})";
    }
    g_logs.clear();
    img.reset(new fake_runtime::Image);
    rt = args(sim_dir + "/canworks.json");
    expect(init(rt.get()) == 0, "init returns 0");
    rt.reset();
    bool started = start_loop() == 0;
    expect(started, "start_loop starts CANopen");
    bool routed = false, status = false;
    for (int i = 0; started && i < 800 && !(routed && status); ++i) {
      cycle_start();
      img->dint_out[20] = 4242;
      cycle_end();
      std::this_thread::sleep_for(std::chrono::milliseconds(10));
      routed = img->dint_in[20] == 4242 && img->dint_in[40] == 4242;
      status = (img->dint_in[21] & 0x4) != 0;
    }
    expect(img->byte_in[41] == 5, "the stand-in master has the gateway (its own slave) operational");
    expect(routed, "the stand-in's output goes down the ping route to node 2 and back up the pong route");
    expect(status, "node 2's operational bit reaches the stand-in through the gateway status");
    // The program's EMCY on the slave reaches the stand-in once; a stand-in
    // fed back into the gateway would forward it up again and again.
    size_t before = g_logs.size();
    for (int i = 0; started && i < 100; ++i) {
      cycle_start();
      img->int_out[300] = 0x6000;
      img->byte_out[300] = 0x04;
      cycle_end();
      std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }
    int emcys = 0;
    for (size_t i = before; i < g_logs.size(); ++i)
      if (g_logs[i].find("host: node 20") != std::string::npos && g_logs[i].find("EMCY 0x6000") != std::string::npos) {
        ++emcys;
        if (emcys < 4) std::printf("  log: %s\n", g_logs[i].c_str());
      }
    expect(emcys == 1, ("the stand-in sees the gateway's EMCY once, not echoed back up (" + std::to_string(emcys) +
                        " EMCY log lines on host)").c_str());
    expect(!logged("gateway status of network \"host\""), "the stand-in has no place in the gateway status");
    if (started) stop_loop();
    cleanup();
    expect(!logged("ERROR"), "no error");
    std::remove((sim_dir + "/simulation.json").c_str());
  }

  // Raw CAN (can-raw-messages): config messages on a simulated CANopen
  // network (through its virtual bus) and a simulated plain CAN network,
  // both fed by the simulation file's plain CAN devices, and the program's
  // frame blocks' table.
  std::printf("raw messages on a simulated CANopen network and a plain CAN network:\n");
  {
    {
      std::ofstream f(sim_dir + "/canworks.json");
      f << R"({"schema_version": 2, "networks": [
        {"name": "io", "adapter": {"type": "socketcan", "interface": "sim0", "bitrate": 125000, "simulate": true},
         "master": {"node_id": 1, "sync_period_us": 20000},
         "nodes": [{"node_id": 2, "name": "a", "eds": "cpp-slave.eds", "heartbeat_ms": 50,
                    "tx_pdos": [{"entries": [{"index": "0x4001", "type": "UNSIGNED32", "iec_location": "%ID100"}]}]}],
         "raw": {"rx": [{"name": "Answer", "id": 768, "signals": [{"start_bit": 0, "length": 8, "iec_location": "%IB60"}]}],
                 "tx": [{"name": "Ask", "id": 769, "dlc": 1, "period_ms": 20, "data_location": "%QL90"}]}},
        {"name": "cab", "protocol": "none",
         "adapter": {"type": "socketcan", "interface": "sim1", "bitrate": 250000, "simulate": true},
         "raw": {"rx": [{"name": "Joystick", "id": 384, "timeout_ms": 200, "status_location": "%IX80.0",
                         "signals": [{"start_bit": 0, "length": 16, "iec_location": "%IW70"}]}]}}]})";
      std::ofstream sf(sim_dir + "/simulation.json");
      sf << R"({"schema_version": 2, "networks": {},
               "raw_devices": [
                 {"name": "echo", "network": "io", "replies": [{"on": {"id": 769, "data": [7]}, "send": {"id": 768, "data": [55]}}]},
                 {"name": "joystick", "network": "cab", "send": [{"id": 384, "dlc": 2, "period_ms": 20, "data": [52, 18]}]}]})";
    }
    g_logs.clear();
    img.reset(new fake_runtime::Image);
    rt = args(sim_dir + "/canworks.json");
    expect(init(rt.get()) == 0, "init returns 0");
    rt.reset();
    bool started = start_loop() == 0;
    expect(started, "start_loop starts both networks");
    typedef const void* (*api_entry)(uint32_t);
    auto api = static_cast<const canworks_can_api_v1*>(sym<api_entry>(h, "canworks_can_api")(CANWORKS_CAN_API_VERSION));
    expect(api != nullptr, "the frame blocks' table is exported");
    uint16_t error_id = 0;
    uint32_t joy = 0;
    bool answered = false, joystick = false, received = false;
    for (int i = 0; started && i < 300 && !(answered && joystick && received); ++i) {
      // As CAN_RECEIVE does: until the network runs, opening answers "not running".
      if (api && !joy) joy = api->rx_open(1, 384, 0x7FF, 0, 8, &error_id);
      cycle_start();
      img->lint_out[90] = 7;
      cycle_end();
      std::this_thread::sleep_for(std::chrono::milliseconds(10));
      answered = img->byte_in[60] == 55;
      joystick = img->int_in[70] == 0x1234 && img->bool_in[80][0];
      canworks_can_frame fr{};
      canworks_can_rx_info info{};
      if (api && api->rx_read(joy, &fr, &info) == 1) received = fr.id == 384 && fr.data[1] == 18;
    }
    expect(joy != 0, "a program receiver opens on the plain network");
    expect(answered, "network io: the raw request goes over the virtual bus and the simulated device's answer comes in");
    expect(joystick, "network cab: the simulated joystick's signal and status reach the PLC");
    expect(received, "network cab: the program's receiver gets the joystick frames");
    expect(count_logged("starting the CANopen master") == 1, "only network io starts a CANopen master; the plain network starts none");
    if (started) stop_loop();
    canworks_can_frame fr{};
    canworks_can_rx_info info{};
    expect(!api || api->rx_read(joy, &fr, &info) == -CANWORKS_CAN_ERR_CANCELLED, "PLC stop cancels the receiver");
    cleanup();
    expect(!logged("ERROR"), "no error");
    std::remove((sim_dir + "/simulation.json").c_str());
  }

  // The first init() after an upload carries the runtime's 20 ms default
  // tick; the program's tasks are read before start_loop().
  std::printf("PLC-cycle SYNC, base tick read at start_loop:\n");
  {
    std::ofstream f(sim_dir + "/canworks.json");
    f << R"({"schema_version": 1,
             "adapter": {"type": "socketcan", "interface": "nonexistent0", "bitrate": 125000, "simulate": true},
             "master": {"node_id": 1, "sync_source": "plc_cycle"},
             "nodes": [{"node_id": 2, "name": "pingpong", "eds": "cpp-slave.eds", "heartbeat_ms": 50,
                        "tx_pdos": [{"entries": [{"index": "0x4001", "type": "UNSIGNED32", "iec_location": "%ID100"}]}]}]})";
  }
  g_logs.clear();
  base_tick_ns = 20000000ULL;
  rt = args(sim_dir + "/canworks.json");
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
