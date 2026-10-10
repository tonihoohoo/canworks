// lookup_check.cpp - the library's SDO blocks find the loaded plugin as on a
// device (spec canopen-plc-sdo, "Finding the plugin").
//
//   lookup_check <libcanworks_plugin.so> <program.so> <canopen_config.json> [--stop-check]
//
// The runtime loads plugins and the compiled program with RTLD_LOCAL, so the
// program cannot link against the plugin; its blocks call
// dlopen("libcanworks_plugin.so", RTLD_NOW | RTLD_NOLOAD), which matches the
// plugin's SONAME wherever it was loaded from (here: the build directory,
// not the install prefix). Checks:
//  - without the plugin loaded, a block ends with ERROR_ID 4 and the lookup
//    does not load it;
//  - with the plugin loaded and CANopen started (on an interface that does
//    not exist, so nothing answers), a block runs (BUSY) and ends with
//    ERROR_ID 2 after its timeout: it reached the plugin's request table.
//  - the NMT blocks find their own entry point, canopen_plc_nmt_api, the
//    same way: CO_GET_STATE ends with ERROR_ID 4 without the plugin, reads
//    the master's state while CANopen runs, and ends with 4 after the stop;
//  - with --stop-check (the config's interface exists, e.g. vcan0 in CI): a
//    PLC stop while a transfer to an absent node is in flight cancels it, so
//    the stop is quick and the session ends cleanly.

#include <dlfcn.h>

#include <chrono>
#include <cstdarg>
#include <cstdio>
#include <cstring>
#include <memory>
#include <string>
#include <thread>
#include <vector>

#include "fake_runtime.hpp"

namespace {

int g_failures = 0;
void expect(bool ok, const char* what) {
  std::printf("  %s %s\n", ok ? "ok  " : "FAIL", what);
  if (!ok) ++g_failures;
}

void vlog(const char* level, const char* fmt, va_list ap) {
  std::fprintf(stderr, "    [%s] ", level);
  std::vfprintf(stderr, fmt, ap);
  std::fputc('\n', stderr);
}
void log_i(const char* fmt, ...) { va_list ap; va_start(ap, fmt); vlog("INFO", fmt, ap); va_end(ap); }
void log_d(const char* fmt, ...) { va_list ap; va_start(ap, fmt); vlog("DEBUG", fmt, ap); va_end(ap); }
std::vector<std::string> g_warnings;
void log_w(const char* fmt, ...) {
  va_list ap;
  va_start(ap, fmt);
  char buf[512];
  va_list copy;
  va_copy(copy, ap);
  std::vsnprintf(buf, sizeof buf, fmt, copy);
  va_end(copy);
  g_warnings.push_back(buf);
  vlog("WARN", fmt, ap);
  va_end(ap);
}
void log_e(const char* fmt, ...) { va_list ap; va_start(ap, fmt); vlog("ERROR", fmt, ap); va_end(ap); }

using scan_fn = int (*)(int, unsigned, unsigned, unsigned*);
using nmt_scan_fn = int (*)(int, unsigned, unsigned*, unsigned*);

// CO_GET_STATE for the master (node 0): a rising edge, then EXECUTE FALSE
// again; returns its outcome (1 done, 2 error) with ERROR_ID and the state.
int read_master(nmt_scan_fn scan, unsigned& error_id, unsigned& state) {
  int st = scan(1, 0, &state, &error_id);
  unsigned a, b;
  scan(0, 0, &a, &b);
  scan(0, 0, &a, &b);
  return st;
}

// Raises EXECUTE and scans every 10 ms until the block ends; returns its
// outcome (1 done, 2 error, 0 still busy at the limit) and ERROR_ID, and
// whether it was BUSY on the way.
int run(scan_fn scan, unsigned node, unsigned& error_id, bool& was_busy) {
  was_busy = false;
  int st = 0;
  for (int i = 0; i < 200; ++i) {
    st = scan(1, node, 300, &error_id);
    if (st == 0) was_busy = true;
    if (st == 1 || st == 2) break;
    std::this_thread::sleep_for(std::chrono::milliseconds(10));
  }
  unsigned dummy;
  scan(0, node, 300, &dummy);
  scan(0, node, 300, &dummy);
  return st;
}

}  // namespace

int main(int argc, char** argv) {
  if (argc < 4) {
    std::fprintf(stderr, "usage: %s <libcanworks_plugin.so> <program.so> <canopen_config.json> [--stop-check]\n",
                 argv[0]);
    return 2;
  }
  bool stop_check = argc > 4 && std::strcmp(argv[4], "--stop-check") == 0;
  void* prog = dlopen(argv[2], RTLD_NOW | RTLD_LOCAL);
  if (!prog) {
    std::fprintf(stderr, "lookup_check: %s\n", dlerror());
    return 2;
  }
  auto scan = reinterpret_cast<scan_fn>(dlsym(prog, "sdo_program_scan"));
  auto nmt_scan = reinterpret_cast<nmt_scan_fn>(dlsym(prog, "nmt_program_scan"));
  if (!scan || !nmt_scan) return 2;
  unsigned master = 0;

  std::printf("program without the plugin:\n");
  unsigned err = 0;
  bool busy = false;
  int st = run(scan, 5, err, busy);
  expect(st == 2 && err == 4, "the block ends with ERROR_ID 4 (CANopen not running)");
  st = read_master(nmt_scan, err, master);
  expect(st == 2 && err == 4, "an NMT block ends with ERROR_ID 4");
  expect(dlopen("libcanworks_plugin.so", RTLD_NOW | RTLD_NOLOAD) == nullptr, "the lookup loaded nothing");

  std::printf("plugin loaded from the build directory and started:\n");
  void* h = dlopen(argv[1], RTLD_NOW | RTLD_LOCAL);
  if (!h) {
    std::fprintf(stderr, "lookup_check: %s\n", dlerror());
    return 2;
  }
  auto init = reinterpret_cast<int (*)(void*)>(dlsym(h, "init"));
  auto start_loop = reinterpret_cast<int (*)()>(dlsym(h, "start_loop"));
  auto stop_loop = reinterpret_cast<void (*)()>(dlsym(h, "stop_loop"));
  auto cleanup = reinterpret_cast<void (*)()>(dlsym(h, "cleanup"));
  std::unique_ptr<fake_runtime::Image> img(new fake_runtime::Image);
  std::unique_ptr<plugin_runtime_args_t> rt(new plugin_runtime_args_t);
  fake_runtime::attach(*img, *rt);
  std::snprintf(rt->plugin_specific_config_file_path, sizeof(rt->plugin_specific_config_file_path), "%s", argv[3]);
  rt->log_info = log_i;
  rt->log_debug = log_d;
  rt->log_warn = log_w;
  rt->log_error = log_e;
  expect(init(rt.get()) == 0, "init");
  rt.reset();
  expect(start_loop() == 0, "start_loop");
  st = run(scan, 5, err, busy);
  expect(busy && st == 2 && err == 2, "the block reached the plugin: BUSY, then ERROR_ID 2 (no answer)");
  st = run(scan, 0, err, busy);
  expect(st == 2 && err == 6, "a bad node ID ends with ERROR_ID 6 from the plugin");
  st = read_master(nmt_scan, err, master);
  expect(st == 1 && err == 0, "CO_GET_STATE reached the plugin's NMT entry point (DONE)");

  if (stop_check) {
    std::printf("PLC stopped during a transfer:\n");
    // A read of node 99 (absent) with a 5 s timeout, stopped after 300 ms.
    int s0 = scan(1, 99, 5000, &err);
    std::this_thread::sleep_for(std::chrono::milliseconds(300));
    int s1 = scan(1, 99, 5000, &err);
    expect(s0 == 0 && s1 == 0, "the read is in progress (BUSY)");
    auto t0 = std::chrono::steady_clock::now();
    stop_loop();
    auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now() - t0).count();
    std::printf("    stop took %lld ms\n", static_cast<long long>(ms));
    expect(ms < 1000, "the stop does not wait for the transfer's timeout");
    bool unclean = false;
    for (auto& w : g_warnings) unclean = unclean || w.find("did not end cleanly") != std::string::npos;
    expect(!unclean, "the session ended cleanly");
    st = scan(1, 99, 5000, &err);
    expect(st == 2 && err == 8, "the block ends with ERROR_ID 8 (cancelled)");
    scan(0, 99, 5000, &err);
    scan(0, 99, 5000, &err);
  } else {
    std::printf("PLC stopped:\n");
    stop_loop();
  }
  st = run(scan, 5, err, busy);
  expect(st == 2 && err == 4, "the block ends with ERROR_ID 4");
  st = read_master(nmt_scan, err, master);
  expect(st == 2 && err == 4, "CO_GET_STATE ends with ERROR_ID 4");
  cleanup();
  dlclose(prog);
  std::printf("%s\n", g_failures ? "FAILED" : "passed");
  return g_failures ? 1 : 0;
}
