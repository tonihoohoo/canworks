// A simulated measuring device on a SocketCAN interface, driven by the
// device's EDS (test/sensor/run.sh uses the RTD-8 8x RTD module).
//
//   sensor_slave <interface> <eds> <node-id> [--blank-pdos] [--period-ms N]
//                [--signal 0x7130:1=200..260[/step]]...
//
// --blank-pdos starts the device with no PDO mapped at all, so every mapping
// the master ends up with comes from its configuration.
//
// SIGUSR1 makes the device report a sensor break on channel 1: EMCY code
// 0x5000 (device hardware), manufacturer byte 0 = 1. SIGUSR2 clears it (EMCY
// error reset, code 0x0000).

#include <cstdio>
#include <functional>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <sstream>
#include <unistd.h>

#include <lely/ev/loop.hpp>
#include <lely/io2/linux/can.hpp>
#include <lely/io2/posix/poll.hpp>
#include <lely/io2/sys/io.hpp>
#include <lely/io2/sys/sigset.hpp>
#include <lely/io2/sys/timer.hpp>

#include "sensor_slave.hpp"

using namespace lely;

int main(int argc, char* argv[]) {
  if (argc < 4) {
    std::fprintf(stderr,
                 "usage: %s <interface> <eds> <node-id> [--blank-pdos] [--period-ms N] "
                 "[--signal IDX:SUB=MIN..MAX[/STEP]]...\n",
                 argv[0]);
    return 2;
  }
  const char* iface = argv[1];
  std::string eds = argv[2];
  uint8_t id = static_cast<uint8_t>(std::atoi(argv[3]));
  bool blank = false;
  int period_ms = 100;
  std::vector<SensorSignal> signals;
  for (int i = 4; i < argc; ++i) {
    if (!std::strcmp(argv[i], "--blank-pdos")) {
      blank = true;
    } else if (!std::strcmp(argv[i], "--period-ms") && i + 1 < argc) {
      period_ms = std::atoi(argv[++i]);
    } else if (!std::strcmp(argv[i], "--signal") && i + 1 < argc) {
      SensorSignal s;
      if (!parse_signal(argv[++i], s)) {
        std::fprintf(stderr, "bad --signal '%s' (want 0x7130:1=200..260[/step])\n", argv[i]);
        return 2;
      }
      signals.push_back(s);
    } else {
      std::fprintf(stderr, "unknown option: %s\n", argv[i]);
      return 2;
    }
  }

  std::string tmp;
  if (blank) {
    std::ifstream in(eds);
    if (!in) {
      std::fprintf(stderr, "cannot read %s\n", eds.c_str());
      return 2;
    }
    std::stringstream ss;
    ss << in.rdbuf();
    char tmpl[] = "/tmp/sensor-slave-XXXXXX.eds";
    int fd = mkstemps(tmpl, 4);
    if (fd < 0) return 2;
    close(fd);
    tmp = tmpl;
    std::ofstream(tmp) << blank_pdo_mapping(ss.str());
    eds = tmp;
  }

  io::IoGuard io_guard;
  io::Context ctx;
  io::Poll poll(ctx);
  ev::Loop loop(poll.get_poll());
  auto exec = loop.get_executor();
  io::Timer timer(poll, exec, CLOCK_MONOTONIC);
  io::CanController ctrl(iface);
  io::CanChannel chan(poll, exec);
  chan.open(ctrl);

  SensorSlave slave(timer, chan, eds, id, signals, std::chrono::milliseconds(period_ms));
  if (!tmp.empty()) unlink(tmp.c_str());

  io::SignalSet sigset(poll, exec);
  sigset.insert(SIGHUP);
  sigset.insert(SIGINT);
  sigset.insert(SIGTERM);
  sigset.submit_wait([&](int /*signo*/) {
    sigset.clear();
    ctx.shutdown();
  });

  io::SignalSet emcy_sigs(poll, exec);
  emcy_sigs.insert(SIGUSR1);
  emcy_sigs.insert(SIGUSR2);
  std::function<void(int)> on_emcy_sig = [&](int signo) {
    if (signo != SIGUSR1 && signo != SIGUSR2) return;  // 0: the wait was cancelled at shutdown
    if (signo == SIGUSR1) {
      const uint8_t msef[5] = {1, 0, 0, 0, 0};
      slave.SendEmcy(0x5000, 0x01, msef);
      std::printf("sensor_slave: sent EMCY 0x5000 (sensor break, channel 1)\n");
    } else {
      slave.ResetEmcy();
      std::printf("sensor_slave: sent EMCY error reset\n");
    }
    std::fflush(stdout);
    emcy_sigs.submit_wait(on_emcy_sig);
  };
  emcy_sigs.submit_wait(on_emcy_sig);

  slave.Reset();
  slave.StartSignals();
  std::printf("sensor_slave: node %u on %s, %zu signal(s)%s; SIGUSR1 sends a sensor-break EMCY, SIGUSR2 resets it\n",
              id, iface, signals.size(), blank ? ", PDO mapping blank" : "");
  std::fflush(stdout);
  loop.run();
  return 0;
}
