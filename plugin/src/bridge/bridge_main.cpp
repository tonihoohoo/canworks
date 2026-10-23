// canworks-bridge - the networks of a canworks.json served as Modbus TCP
// registers (docs/modbus-bridge.md).
//
//   canworks-bridge --config FILE [--check-only | --wait]

#include <chrono>
#include <csignal>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <sys/stat.h>
#include <unistd.h>

#include "bridge_host.h"
#include "log.h"
#include "supervisor.h"
#if CANWORKS_WITH_CANOPEN
#include "canopen_runtime.h"
#endif

namespace {

volatile std::sig_atomic_t g_stop = 0;

void on_signal(int) { g_stop = 1; }

void usage(FILE* f) {
  std::fprintf(f,
               "usage: canworks-bridge --config FILE [--check-only | --wait]\n"
               "  Runs the CAN networks of FILE (a canworks.json with a \"bridge\" object) and serves\n"
               "  their values as Modbus TCP registers. docs/modbus-bridge.md describes the register map.\n"
               "  --check-only   check the config and exit (0 accepted, 1 rejected)\n"
               "  --wait         while FILE does not exist, wait for it (a container started before its config)\n"
               "  --version, --help\n");
}

}  // namespace

int main(int argc, char** argv) {
  std::string config;
  bool check_only = false;
  bool wait = false;
  for (int i = 1; i < argc; ++i) {
    const char* a = argv[i];
    if (!std::strcmp(a, "--config") && i + 1 < argc) {
      config = argv[++i];
    } else if (!std::strncmp(a, "--config=", 9)) {
      config = a + 9;
    } else if (!std::strcmp(a, "--check-only")) {
      check_only = true;
    } else if (!std::strcmp(a, "--wait")) {
      wait = true;
    } else if (!std::strcmp(a, "--version")) {
      std::printf("canworks-bridge %s\n", CANWORKS_VERSION);
      return 0;
    } else if (!std::strcmp(a, "--help") || !std::strcmp(a, "-h")) {
      usage(stdout);
      return 0;
    } else {
      std::fprintf(stderr, "canworks-bridge: unknown argument '%s'\n", a);
      usage(stderr);
      return 2;
    }
  }
  if (config.empty()) {
    usage(stderr);
    return 2;
  }
#if CANWORKS_WITH_CANOPEN
  canopen_plugin::canopen_init_logging();
#endif
  if (check_only) {
    uint32_t hash = 0;
    bool ok = canworks_bridge::BridgeHost::check(config, nullptr, &hash);
    std::fprintf(stderr, "canworks-bridge: config %s\n", ok ? "accepted" : "rejected");
    if (ok) std::printf("map hash 0x%08x\n", hash);
    return ok ? 0 : 1;
  }

  struct sigaction sa;
  std::memset(&sa, 0, sizeof(sa));
  sa.sa_handler = on_signal;
  sigaction(SIGINT, &sa, nullptr);
  sigaction(SIGTERM, &sa, nullptr);
  std::signal(SIGPIPE, SIG_IGN);

  if (wait) {
    struct stat st;
    bool said = false;
    while (!g_stop && stat(config.c_str(), &st) != 0) {
      if (!said) canopen_plugin::log_info("canworks-bridge: waiting for a config at %s", config.c_str());
      said = true;
      usleep(500000);
    }
    if (g_stop) return 0;
    if (said) usleep(500000);  // the rest of an upload lands first
  }

  canworks_bridge::BridgeHost host;
  if (!host.start(config, CANWORKS_VERSION)) return 1;
  // modbus-bridge "Stall watchdog": a thread that stops making progress
  // aborts the process, so the service (or the container) restarts it.
  canworks_bridge::Supervisor::Options opt;
  if (const char* ms = std::getenv("CANWORKS_STALL_MS")) opt.stall = std::chrono::milliseconds(std::atol(ms));  // tests
  opt.on_stall = [&opt](const std::string& who) {
    canopen_plugin::log_error("canworks-bridge: the %s made no progress for %lld s; aborting so the service restarts",
                              who.c_str(), static_cast<long long>(opt.stall.count() / 1000));
    std::abort();
  };
  canworks_bridge::Supervisor supervisor(opt);
  supervisor.start();
  canworks_bridge::sd_notify_state("READY=1");
  while (!g_stop) {
    usleep(50000);
    if (host.upload_pending()) {
      usleep(300000);  // the put_config answer goes out first
      supervisor.pause(true);
      bool runs = host.apply_upload();
      supervisor.pause(false);
      if (!runs) return 1;
    }
  }
  canopen_plugin::log_info("canworks-bridge: stopping");
  canworks_bridge::sd_notify_state("STOPPING=1");
  supervisor.stop();
  host.stop();
  return 0;
}
