// canopen_host.cpp - loads libcanopen_plugin.so the way the OpenPLC runtime
// does and drives it with a stand-in PLC scan, so the real plugin can be run
// against a real SocketCAN bus without a compiled PLC program.
//
//   canopen_host <libcanopen_plugin.so> <canopen_config.json> [seconds] [pingpong|rtd|bus|fixed|two]
//
// The scan runs every 10 ms. Once a second it prints the inputs and the node
// status bit %IX10.0.
//
// pingpong (default): computes `%QD100 := %ID100 + 1`. Exits 0 if, at the
// end, the status bit is TRUE and %ID100 rose by at least 5 during the last
// half of the run; 1 otherwise.
//
// rtd: reads the four temperatures of config/rtd-sensor (%IW100-%IW103, INT
// in 0.1 degC) as test/sensor/run.sh simulates them and computes the
// starter program's alarm `%QX100.0 := AI0 > 25.0 degC`. Exits 0 if the
// status bit is TRUE at the end and, during the last half of the run, every
// temperature stayed in its simulated range and AI0 changed; 1 otherwise.
//
// two: two networks (config/two-networks), one ping-pong node on each;
// computes `%QD100 := %ID100 + 1` and `%QD101 := %ID101 + 1`. Exits 0 if both
// status bits %IX10.0 and %IX10.1 are TRUE at the end and both counters rose
// by at least 5 during the last half of the run.
//
// slave: test/slave/run.sh, a master network and the plugin's own slave
// network joined by cangw; the master computes `%QW10 := %IW10 + 1` and the
// slave echoes `%QW300 := %IW300`. Exits 0 if the master's status bit
// %IX10.0 and the slave's comm OK bit %IX300.0 are TRUE at the end and %IW10
// rose by at least 5 during the last half of the run.
//
// fixed: the fixed-mapping I/O module of test/fixed/run.sh; computes
// `%QB40 := %IB40`. Exits 0 if the status bit is TRUE at the end and, during
// the last half of the run, %IB40 stayed in 10-50 and changed.

#include <dlfcn.h>
#include <signal.h>

#include <chrono>
#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <memory>
#include <string>
#include <thread>

#include "fake_runtime.hpp"

namespace {

volatile sig_atomic_t g_stop = 0;
void on_signal(int) { g_stop = 1; }

void vlog(const char* level, const char* fmt, va_list ap) {
  std::fprintf(stderr, "[%s] ", level);
  std::vfprintf(stderr, fmt, ap);
  std::fputc('\n', stderr);
}
void log_i(const char* fmt, ...) { va_list ap; va_start(ap, fmt); vlog("INFO", fmt, ap); va_end(ap); }
void log_d(const char* fmt, ...) { va_list ap; va_start(ap, fmt); vlog("DEBUG", fmt, ap); va_end(ap); }
void log_w(const char* fmt, ...) { va_list ap; va_start(ap, fmt); vlog("WARN", fmt, ap); va_end(ap); }
void log_e(const char* fmt, ...) { va_list ap; va_start(ap, fmt); vlog("ERROR", fmt, ap); va_end(ap); }

template <typename F>
F sym(void* h, const char* name) {
  F f = reinterpret_cast<F>(dlsym(h, name));
  if (!f) {
    std::fprintf(stderr, "canopen_host: %s not exported: %s\n", name, dlerror());
    std::exit(2);
  }
  return f;
}

}  // namespace

int main(int argc, char** argv) {
  if (argc < 3) {
    std::fprintf(stderr, "usage: %s <libcanopen_plugin.so> <canopen_config.json> [seconds] [pingpong|rtd|bus|fixed|two|slave]\n",
                 argv[0]);
    return 2;
  }
  const int seconds = argc > 3 ? std::atoi(argv[3]) : 10;
  const bool rtd = argc > 4 && std::strcmp(argv[4], "rtd") == 0;
  // bus: the ping-pong program, but passes when the bus state byte %IB110
  // went 1 -> 0 -> 1 (test/bus/run.sh takes the interface down and up).
  const bool bus = argc > 4 && std::strcmp(argv[4], "bus") == 0;
  const bool fixed = argc > 4 && std::strcmp(argv[4], "fixed") == 0;
  const bool two = argc > 4 && std::strcmp(argv[4], "two") == 0;
  const bool slave = argc > 4 && std::strcmp(argv[4], "slave") == 0;
  bool fixed_in_range = true, fixed_moved = false;
  uint8_t fixed_first = 0;
  if (argc > 4 && !rtd && !bus && !fixed && !two && !slave && std::strcmp(argv[4], "pingpong") != 0) {
    std::fprintf(stderr, "canopen_host: unknown program '%s'\n", argv[4]);
    return 2;
  }
  // The ranges test/sensor/run.sh gives the simulated channels, in 0.1 degC.
  const int lo[4] = {200, 300, 400, -100}, hi[4] = {260, 360, 460, -40};
  bool rtd_in_range = true, rtd_moved = false, rtd_alarm_seen = false;
  int16_t rtd_first = 0;
  signal(SIGINT, on_signal);
  signal(SIGTERM, on_signal);

  void* h = dlopen(argv[1], RTLD_NOW | RTLD_LOCAL);
  if (!h) {
    std::fprintf(stderr, "canopen_host: %s\n", dlerror());
    return 2;
  }
  auto init = sym<int (*)(void*)>(h, "init");
  auto start_loop = sym<int (*)()>(h, "start_loop");
  auto stop_loop = sym<void (*)()>(h, "stop_loop");
  auto cleanup = sym<void (*)()>(h, "cleanup");
  auto cycle_start = sym<void (*)()>(h, "cycle_start");
  auto cycle_end = sym<void (*)()>(h, "cycle_end");

  std::unique_ptr<fake_runtime::Image> img(new fake_runtime::Image);
  std::unique_ptr<plugin_runtime_args_t> rt(new plugin_runtime_args_t);
  fake_runtime::attach(*img, *rt);
  std::snprintf(rt->plugin_specific_config_file_path, sizeof(rt->plugin_specific_config_file_path), "%s",
                argv[2]);
  rt->log_info = log_i;
  rt->log_debug = log_d;
  rt->log_warn = log_w;
  rt->log_error = log_e;
  rt->base_tick_ns = 10000000;  // the 10 ms loop below

  if (init(rt.get()) != 0) {
    std::fprintf(stderr, "canopen_host: init failed\n");
    return 1;
  }
  rt.reset();  // the runtime frees the args after init, too
  if (start_loop() != 0) {  // the runtime skips the cycle hooks of a plugin that did not start
    std::fprintf(stderr, "canopen_host: start_loop failed\n");
    cleanup();
    return 1;
  }

  using clock = std::chrono::steady_clock;
  const auto t0 = clock::now();
  auto next = t0;
  auto next_print = t0 + std::chrono::seconds(1);
  const auto half = t0 + std::chrono::milliseconds(seconds * 500);
  bool have_mid = false;
  IEC_UDINT mid = 0, mid2 = 0;
  std::string bus_states;  // distinct successive values of %IB110
  int last_bus = -1;

  while (!g_stop && clock::now() - t0 < std::chrono::seconds(seconds)) {
    cycle_start();
    auto ai = [&](int ch) { return static_cast<int16_t>(img->int_in[100 + ch]); };
    if (rtd)
      img->bool_out[100][0] = ai(0) > 250;  // %QX100.0 := AI0 > 25.0 degC
    else if (fixed)
      img->byte_out[40] = img->byte_in[40];  // %QB40 := %IB40
    else if (slave) {
      img->int_out[10] = static_cast<IEC_UINT>(img->int_in[10] + 1);  // master: %QW10 := %IW10 + 1
      img->int_out[300] = img->int_in[300];                            // slave: %QW300 := %IW300
    } else
      img->dint_out[100] = img->dint_in[100] + 1;  // %QD100 := %ID100 + 1
    if (two) img->dint_out[101] = img->dint_in[101] + 1;  // %QD101 := %ID101 + 1
    cycle_end();

    if (bus && img->byte_in[110] != last_bus) {
      last_bus = img->byte_in[110];
      bus_states += (bus_states.empty() ? "" : " ") + std::to_string(last_bus);
      const long ms = (long)std::chrono::duration_cast<std::chrono::milliseconds>(clock::now() - t0).count();
      std::printf("t=%5ldms  bus state %%IB110=%d\n", ms, last_bus);
      std::fflush(stdout);
    }
    if (!have_mid && clock::now() >= half) {
      mid = img->dint_in[100];
      mid2 = slave ? img->int_in[10] : img->dint_in[101];
      rtd_first = ai(0);
      fixed_first = img->byte_in[40];
      have_mid = true;
    }
    if (fixed && have_mid) {
      fixed_in_range = fixed_in_range && img->byte_in[40] >= 10 && img->byte_in[40] <= 50;
      fixed_moved = fixed_moved || img->byte_in[40] != fixed_first;
    }
    if (rtd && have_mid) {
      for (int ch = 0; ch < 4; ++ch) rtd_in_range = rtd_in_range && ai(ch) >= lo[ch] && ai(ch) <= hi[ch];
      rtd_moved = rtd_moved || ai(0) != rtd_first;
      rtd_alarm_seen = rtd_alarm_seen || img->bool_out[100][0];
    }
    if (clock::now() >= next_print) {
      const long t = (long)std::chrono::duration_cast<std::chrono::seconds>(clock::now() - t0).count();
      if (fixed)
        std::printf("t=%2lds  %%IB40=%u  %%IX10.0=%d\n", t, (unsigned)img->byte_in[40], img->bool_in[10][0]);
      else if (rtd)
        std::printf("t=%2lds  AI0..AI3=%.1f %.1f %.1f %.1f degC  alarm=%d  %%IX10.0=%d\n", t, ai(0) / 10.0,
                    ai(1) / 10.0, ai(2) / 10.0, ai(3) / 10.0, img->bool_out[100][0], img->bool_in[10][0]);
      else if (slave)
        std::printf("t=%2lds  %%IW10=%u  %%IX10.0=%d  %%IW300=%u  %%IX300.0=%d\n", t, (unsigned)img->int_in[10],
                    img->bool_in[10][0], (unsigned)img->int_in[300], img->bool_in[300][0]);
      else if (two)
        std::printf("t=%2lds  %%ID100=%u  %%IX10.0=%d  %%ID101=%u  %%IX10.1=%d\n", t, (unsigned)img->dint_in[100],
                    img->bool_in[10][0], (unsigned)img->dint_in[101], img->bool_in[10][1]);
      else
        std::printf("t=%2lds  %%ID100=%u  %%IX10.0=%d\n", t, (unsigned)img->dint_in[100], img->bool_in[10][0]);
      std::fflush(stdout);
      next_print += std::chrono::seconds(1);
    }
    next += std::chrono::milliseconds(10);
    std::this_thread::sleep_until(next);
  }

  const IEC_UDINT last = img->dint_in[100], last2 = slave ? img->int_in[10] : img->dint_in[101];
  const bool slave_ok = img->bool_in[300][0] != 0;
  const bool up = img->bool_in[10][0] != 0, up2 = img->bool_in[10][1] != 0;
  stop_loop();
  cleanup();
  dlclose(h);

  if (bus) {
    const bool ok = (" " + bus_states + " ").find(" 1 0 1 ") != std::string::npos;
    std::printf("%s: bus state byte went %s\n", ok ? "PASS" : "FAIL", bus_states.c_str());
    return ok ? 0 : 1;
  }
  if (fixed) {
    const bool ok = up && have_mid && fixed_in_range && fixed_moved;
    std::printf("%s: status bit %s, %%IB40 %s 10-50 and %s\n", ok ? "PASS" : "FAIL", up ? "TRUE" : "FALSE",
                fixed_in_range ? "stayed in" : "left", fixed_moved ? "changed" : "did not change");
    return ok ? 0 : 1;
  }
  if (rtd) {
    const bool ok = up && have_mid && rtd_in_range && rtd_moved;
    std::printf("%s: status bit %s, temperatures %s their simulated ranges, AI0 %s, alarm %s\n",
                ok ? "PASS" : "FAIL", up ? "TRUE" : "FALSE", rtd_in_range ? "stayed in" : "left",
                rtd_moved ? "changed" : "did not change", rtd_alarm_seen ? "seen" : "not seen");
    return ok ? 0 : 1;
  }
  if (slave) {
    const bool ok = up && slave_ok && have_mid && last2 >= mid2 + 5;
    std::printf("%s: master status bit %s, slave comm OK %s, %%IW10 went from %u to %u in the last half\n",
                ok ? "PASS" : "FAIL", up ? "TRUE" : "FALSE", slave_ok ? "TRUE" : "FALSE", (unsigned)mid2,
                (unsigned)last2);
    return ok ? 0 : 1;
  }
  if (two) {
    const bool ok = up && up2 && have_mid && last >= mid + 5 && last2 >= mid2 + 5;
    std::printf("%s: status bits %s/%s, %%ID100 went from %u to %u and %%ID101 from %u to %u in the last half\n",
                ok ? "PASS" : "FAIL", up ? "TRUE" : "FALSE", up2 ? "TRUE" : "FALSE", (unsigned)mid, (unsigned)last,
                (unsigned)mid2, (unsigned)last2);
    return ok ? 0 : 1;
  }
  const bool ok = up && have_mid && last >= mid + 5;
  std::printf("%s: status bit %s, %%ID100 went from %u to %u in the last half of the run\n",
              ok ? "PASS" : "FAIL", up ? "TRUE" : "FALSE", (unsigned)mid, (unsigned)last);
  return ok ? 0 : 1;
}
