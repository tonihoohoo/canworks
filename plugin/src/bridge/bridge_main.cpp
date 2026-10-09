// canworks-bridge - the networks of a canworks.json served as Modbus TCP
// registers (docs/modbus-bridge.md).
//
//   canworks-bridge --config FILE [--check-only]

#include <csignal>
#include <cstdio>
#include <cstring>
#include <string>
#include <unistd.h>

#include "bridge_host.h"
#include "log.h"
#if CANWORKS_WITH_CANOPEN
#include "canopen_runtime.h"
#endif

namespace {

volatile std::sig_atomic_t g_stop = 0;

void on_signal(int) { g_stop = 1; }

void usage(FILE* f) {
  std::fprintf(f,
               "usage: canworks-bridge --config FILE [--check-only]\n"
               "  Runs the CAN networks of FILE (a canworks.json with a \"bridge\" object) and serves\n"
               "  their values as Modbus TCP registers. docs/modbus-bridge.md describes the register map.\n"
               "  --check-only   check the config and exit (0 accepted, 1 rejected)\n"
               "  --version, --help\n");
}

}  // namespace

int main(int argc, char** argv) {
  std::string config;
  bool check_only = false;
  for (int i = 1; i < argc; ++i) {
    const char* a = argv[i];
    if (!std::strcmp(a, "--config") && i + 1 < argc) {
      config = argv[++i];
    } else if (!std::strncmp(a, "--config=", 9)) {
      config = a + 9;
    } else if (!std::strcmp(a, "--check-only")) {
      check_only = true;
    } else if (!std::strcmp(a, "--version")) {
      std::printf("canworks-bridge %s\n", CANWORKS_PLUGIN_VERSION);
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
    bool ok = canworks_bridge::BridgeHost::check(config);
    std::fprintf(stderr, "canworks-bridge: config %s\n", ok ? "accepted" : "rejected");
    return ok ? 0 : 1;
  }

  struct sigaction sa;
  std::memset(&sa, 0, sizeof(sa));
  sa.sa_handler = on_signal;
  sigaction(SIGINT, &sa, nullptr);
  sigaction(SIGTERM, &sa, nullptr);
  std::signal(SIGPIPE, SIG_IGN);

  canworks_bridge::BridgeHost host;
  if (!host.start(config, CANWORKS_PLUGIN_VERSION)) return 1;
  while (!g_stop) {
    usleep(50000);
    if (host.upload_pending()) {
      usleep(300000);  // the put_config answer goes out first
      host.apply_upload();
    }
  }
  canopen_plugin::log_info("canworks-bridge: stopping");
  host.stop();
  return 0;
}
