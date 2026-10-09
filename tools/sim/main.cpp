// canworks-sim - simulated CANopen devices on a SocketCAN interface
// (docs/simulator.md, "canworks-sim").
//
//   canworks-sim [CONFIG] [options]          run mode (sim_run.cpp)
//   canworks-sim test [CONFIG] [options]     test mode (sim_run.cpp)
//   canworks-sim status|get|set|...          control subcommands (sim_commands.cpp)

#include <cstdio>
#include <cstring>

#include "sim_tool.h"

namespace sim_tool {

bool Args::option(const char* name, std::string& value, bool& missing) {
  if (done()) return false;
  const std::string& w = words_[i_];
  size_t n = std::strlen(name);
  if (w.compare(0, n, name) != 0) return false;
  if (w.size() == n) {
    ++i_;
    if (done()) {
      missing = true;
      return true;
    }
    value = words_[i_++];
    return true;
  }
  if (w[n] != '=') return false;
  value = w.substr(n + 1);
  ++i_;
  return true;
}

bool Args::flag(const char* name) {
  if (done() || words_[i_] != name) return false;
  ++i_;
  return true;
}

void print_usage(bool full) {
  std::printf(
      "usage: canworks-sim [CONFIG] [options]           simulate devices on a SocketCAN interface\n"
      "       canworks-sim test [CONFIG] [test options]  run scenarios as tests\n"
      "       canworks-sim COMMAND ...                   control a running simulator\n");
  if (!full) {
    std::printf("Run canworks-sim --help for the options; docs/simulator.md describes everything.\n");
    return;
  }
  std::printf(
      "\n"
      "Run mode (CONFIG: a canopen_config.json; every node of it is simulated):\n"
      "  --iface NAME             SocketCAN interface (default vcan0)\n"
      "  --setup-vcan             create and bring up a missing vcan interface (needs root)\n"
      "  --real-bus               allow an interface that is not vcan (free node ID check, conflict guard)\n"
      "  --nodes LIST             only these nodes of the config (comma separated)\n"
      "  --eds FILE --node ID     a device that is not in a config (may repeat; --name NAME names it;\n"
      "                           --node 0: no node ID, waits for LSS, needs --name)\n"
      "  --sim FILE               the simulation file (default: simulation.json next to CONFIG)\n"
      "  --no-sim-file            no simulation file\n"
      "  --no-defaults            no default behaviour for any device\n"
      "  --state-dir DIR          keep stored parameters and LSS node IDs in DIR\n"
      "  --scenario NAME          start this scenario once the devices are up (may repeat)\n"
      "  --port N, --bind ADDR    control channel (default 127.0.0.1:7532; other addresses need a token)\n"
      "  --token T, --token-file F  the control channel's token\n"
      "  --quiet                  only errors and scenario results\n"
      "  --version, --help\n"
      "\n"
      "Test mode: canworks-sim test [CONFIG] [run options] [--scenario NAME]... [--junit FILE]\n"
      "           [--timeout S] [--start-timeout S] [--parallel]\n"
      "           canworks-sim test --runtime HOST[:PORT] (--token T | --token-file F) [--scenario NAME]...\n"
      "  Runs the named scenarios (default: those with \"test\": true); exit 0 all passed, 1 one failed,\n"
      "  2 usage or start-up error. --timeout default 300 s, --start-timeout default 30 s.\n"
      "  --runtime runs them in the plugin's simulated devices (diagnostics channel, port 7531);\n"
      "  --sim HOST[:PORT] in a running standalone simulator.\n"
      "\n"
      "Commands (--sim HOST[:PORT] default 127.0.0.1:7532, --token T, --token-file F, --json):\n"
      "  status\n"
      "  get NODE OBJECT...                    (no OBJECT: every object in the node's PDOs)\n"
      "  set NODE OBJECT VALUE [OBJECT VALUE]...\n"
      "  override NODE OBJECT VALUE [OBJECT VALUE]...\n"
      "  release NODE [OBJECT...]              (no OBJECT: all overrides of the node)\n"
      "  source NODE OBJECT JSON|none\n"
      "  fault NODE KIND ARGS...               emcy CODE [--register R] [--msef HEX] [--period-ms MS]\n"
      "                                        heartbeat-stop | power off|on|cycle [--off-ms MS]\n"
      "                                        reset node|comm | nmt-state stopped|preop|operational\n"
      "                                        sdo-abort OBJECT CODE [--on read|write|both] [--count N]\n"
      "                                        sdo-delay MS [--object OBJECT] | refuse-write-operational\n"
      "                                        tpdo-stop N | identity [--vendor-id V] [--product-code P]\n"
      "                                        [--revision-number R] [--serial-number S] | device-type V\n"
      "                                        forget-node-id | drive-input [--blocked] [--positive-limit]\n"
      "                                        [--negative-limit] [--home-switch] | json '{...}'\n"
      "  clear NODE FAULT [OBJECT|TPDO]        FAULT: a fault name (dashes or underscores) or all\n"
      "  scenario list | start NAME | stop NAME\n");
}

}  // namespace sim_tool

int main(int argc, char** argv) {
  using namespace sim_tool;
  std::vector<std::string> words(argv + 1, argv + argc);
  if (!words.empty() && (words[0] == "--version" || words[0] == "-V")) {
    std::printf("canworks-sim %s\n", CANOPEN_PLUGIN_VERSION);
    return kExitOk;
  }
  if (!words.empty() && (words[0] == "--help" || words[0] == "-h" || words[0] == "help")) {
    print_usage(true);
    return kExitOk;
  }
  if (!words.empty() && words[0] == "test") {
    Args a(std::vector<std::string>(words.begin() + 1, words.end()));
    return test_main(a);
  }
  if (!words.empty() && is_command(words[0])) {
    Args a(std::vector<std::string>(words.begin() + 1, words.end()));
    return command_main(words[0], a);
  }
  Args a(words);
  return run_main(a);
}
