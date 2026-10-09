// Run mode and test mode of canworks-sim (docs/simulator.md,
// "canworks-sim" and "Test mode").
//
// One thread: the Lely loop runs in 10 ms slices, and between slices the
// control channel is polled and the signal flag checked, so every engine call
// happens on the loop's thread.
//
// Test-only environment overrides (not for users; test/simulator/run.sh uses
// them because CI has only vcan interfaces):
//   CANWORKS_SIM_TREAT_AS_REAL=vcan1[,...]  these interfaces count as
//       real buses (not vcan): --real-bus is required and the 1 s free node
//       ID listen and the conflict guard run, as on a real CAN interface.
//   CANWORKS_SIM_VIRTUAL_BUS=1  no SocketCAN interface at all: the
//       devices run on Lely's in-process virtual bus (nothing outside the
//       process sees them); for tests of the control channel and the test
//       mode on hosts without CAN support in the kernel.

#include <ftw.h>
#include <signal.h>
#include <sys/stat.h>
#include <unistd.h>

#include <cctype>
#include <cerrno>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <fstream>
#include <functional>
#include <map>
#include <memory>
#include <set>
#include <sstream>
#include <thread>

#include <lely/ev/loop.hpp>
#include <lely/io2/ctx.hpp>
#include <lely/io2/posix/poll.hpp>
#include <lely/io2/sys/io.hpp>
#include <lely/io2/sys/timer.hpp>
#include <lely/io2/vcan.hpp>

#include "cJSON.h"
#include "can_adapter.h"
#include "config.h"
#include "control.h"
#include "eds_check.h"
#include "eds_lint.h"
#include "log.h"
#include "sim_config.h"
#include "sim_engine.h"
#include "sim_file.h"
#include "sim_host.h"
#include "sim_tool.h"

namespace sim_tool {

namespace {

using Clock = std::chrono::steady_clock;
constexpr std::chrono::milliseconds kSlice(10);

volatile sig_atomic_t g_signal = 0;
void on_signal(int s) { g_signal = s; }

void install_signals() {
  struct sigaction sa;
  std::memset(&sa, 0, sizeof sa);
  sa.sa_handler = on_signal;
  sigemptyset(&sa.sa_mask);
  sigaction(SIGINT, &sa, nullptr);
  sigaction(SIGTERM, &sa, nullptr);
  signal(SIGPIPE, SIG_IGN);
}

bool g_quiet = false;

std::string stamp() {
  auto now = std::chrono::system_clock::now();
  std::time_t t = std::chrono::system_clock::to_time_t(now);
  struct tm tm;
  localtime_r(&t, &tm);
  long ms = static_cast<long>(
      std::chrono::duration_cast<std::chrono::milliseconds>(now.time_since_epoch()).count() % 1000);
  char b[32];
  std::snprintf(b, sizeof b, "%02d:%02d:%02d.%03ld", tm.tm_hour, tm.tm_min, tm.tm_sec, ms);
  return b;
}

void say(const std::string& m) {
  if (g_quiet) return;
  std::printf("%s %s\n", stamp().c_str(), m.c_str());
  std::fflush(stdout);
}
// Scenario results: printed with --quiet too.
void say_always(const std::string& m) {
  std::printf("%s %s\n", stamp().c_str(), m.c_str());
  std::fflush(stdout);
}
void warn(const std::string& m) {
  if (g_quiet) return;
  std::fprintf(stderr, "%s warning: %s\n", stamp().c_str(), m.c_str());
}
void error(const std::string& m) { std::fprintf(stderr, "%s error: %s\n", stamp().c_str(), m.c_str()); }
// Before the simulation runs: plain messages.
void fail(const std::string& m) { std::fprintf(stderr, "canworks-sim: %s\n", m.c_str()); }

// The plugin's log (config, EDS lint) and Lely's diagnostics.
void plugin_log(canopen_plugin::LogLevel l, const char* msg) {
  using canopen_plugin::LogLevel;
  std::string m = msg;
  if (m.compare(0, 11, "[CANWORKS] ") == 0) m.erase(0, 11);
  if (m.compare(0, 6, "lely: ") == 0) {
    // Lely's own NMT and EMCY chatter (the engine logs state changes), and
    // the note about frames still queued when a device is powered off.
    if (l == LogLevel::Info || l == LogLevel::Debug || m.find("invoked with pending operations") != std::string::npos)
      return;
  }
  if (l == LogLevel::Error)
    error(m);
  else if (l == LogLevel::Warn)
    warn(m);
  else if (l == LogLevel::Info)
    say(m);
}

bool file_exists(const std::string& p) {
  struct stat st;
  return stat(p.c_str(), &st) == 0 && S_ISREG(st.st_mode);
}

bool make_dirs(const std::string& path) {
  std::string cur;
  std::stringstream ss(path);
  std::string part;
  if (!path.empty() && path[0] == '/') cur = "/";
  while (std::getline(ss, part, '/')) {
    if (part.empty()) continue;
    cur += part + "/";
    if (mkdir(cur.c_str(), 0755) != 0 && errno != EEXIST) return false;
  }
  return true;
}

int remove_entry(const char* p, const struct stat*, int, struct FTW*) { return remove(p); }
void remove_tree(const std::string& dir) {
  if (!dir.empty()) nftw(dir.c_str(), remove_entry, 16, FTW_DEPTH | FTW_PHYS);
}

bool valid_ifname(const std::string& n) {
  if (n.empty() || n.size() > 15) return false;
  for (char c : n)
    if (!std::isalnum(static_cast<unsigned char>(c)) && c != '_' && c != '-' && c != '.') return false;
  return true;
}

bool parse_uint(const std::string& s, unsigned long lo, unsigned long hi, unsigned& out) {
  if (s.empty()) return false;
  char* end = nullptr;
  errno = 0;
  unsigned long v = std::strtoul(s.c_str(), &end, 0);
  if (*end || errno || v < lo || v > hi || s[0] == '-') return false;
  out = static_cast<unsigned>(v);
  return true;
}

bool parse_seconds(const std::string& s, double& out) {
  char* end = nullptr;
  double v = std::strtod(s.c_str(), &end);
  if (s.empty() || *end || !(v > 0) || v > 86400 * 7) return false;
  out = v;
  return true;
}

std::string xml_escape(const std::string& s) {
  std::string o;
  for (char c : s) {
    switch (c) {
      case '&': o += "&amp;"; break;
      case '<': o += "&lt;"; break;
      case '>': o += "&gt;"; break;
      case '"': o += "&quot;"; break;
      case '\'': o += "&apos;"; break;
      case '\n': o += "&#10;"; break;
      default:
        if (static_cast<unsigned char>(c) < 0x20 && c != '\t') o += ' ';
        else o += c;
    }
  }
  return o;
}

// ---- options ----

struct DeviceArg {
  std::string eds;
  bool has_node = false;
  unsigned node = 0;
  std::string name;
};

struct Options {
  std::string config, iface = "vcan0", sim_file, state_dir, bind = "127.0.0.1", token, token_file;
  bool setup_vcan = false, real_bus = false, no_sim_file = false, no_defaults = false, quiet = false;
  unsigned port = kControlPort;
  std::set<unsigned> nodes;
  bool has_nodes = false;
  std::vector<DeviceArg> eds;
  std::vector<std::string> scenarios;
  // test mode
  std::string junit, runtime;
  double timeout_s = 300, start_timeout_s = 30;
  bool parallel = false;
};

bool parse_options(Args& a, Options& o, bool test, std::string& err) {
  while (!a.done()) {
    std::string v;
    bool missing = false;
    auto need = [&](const char* name) {
      if (missing) err = std::string(name) + " needs a value";
      return !missing;
    };
    if (a.option("--iface", v, missing)) {
      if (!need("--iface")) return false;
      if (!valid_ifname(v)) {
        err = "--iface: \"" + v + "\" is not an interface name";
        return false;
      }
      o.iface = v;
    } else if (a.flag("--setup-vcan")) {
      o.setup_vcan = true;
    } else if (a.flag("--real-bus")) {
      o.real_bus = true;
    } else if (a.option("--nodes", v, missing)) {
      if (!need("--nodes")) return false;
      std::stringstream ss(v);
      std::string part;
      while (std::getline(ss, part, ',')) {
        unsigned id = 0;
        if (!parse_uint(part, 1, 127, id)) {
          err = "--nodes takes node IDs 1-127, comma separated, not \"" + v + "\"";
          return false;
        }
        o.nodes.insert(id);
      }
      o.has_nodes = true;
    } else if (a.option("--eds", v, missing)) {
      if (!need("--eds")) return false;
      DeviceArg d;
      d.eds = v;
      o.eds.push_back(d);
    } else if (a.option("--node", v, missing)) {
      if (!need("--node")) return false;
      if (o.eds.empty() || o.eds.back().has_node) {
        err = "--node " + v + " must follow its --eds FILE";
        return false;
      }
      if (!parse_uint(v, 0, 127, o.eds.back().node)) {
        err = "--node takes a node ID 0-127, not \"" + v + "\"";
        return false;
      }
      o.eds.back().has_node = true;
    } else if (a.option("--name", v, missing)) {
      if (!need("--name")) return false;
      if (o.eds.empty()) {
        err = "--name " + v + " must follow its --eds FILE";
        return false;
      }
      o.eds.back().name = v;
    } else if (a.option("--sim", v, missing)) {
      if (!need("--sim")) return false;
      o.sim_file = v;
    } else if (a.flag("--no-sim-file")) {
      o.no_sim_file = true;
    } else if (a.flag("--no-defaults")) {
      o.no_defaults = true;
    } else if (a.option("--state-dir", v, missing)) {
      if (!need("--state-dir")) return false;
      o.state_dir = v;
    } else if (a.option("--scenario", v, missing)) {
      if (!need("--scenario")) return false;
      o.scenarios.push_back(v);
    } else if (!test && a.option("--port", v, missing)) {
      if (!need("--port")) return false;
      if (!parse_uint(v, 1, 65535, o.port)) {
        err = "--port takes 1-65535, not \"" + v + "\"";
        return false;
      }
    } else if (!test && a.option("--bind", v, missing)) {
      if (!need("--bind")) return false;
      o.bind = v;
    } else if (a.option("--token-file", v, missing)) {
      if (!need("--token-file")) return false;
      o.token_file = v;
    } else if (a.option("--token", v, missing)) {
      if (!need("--token")) return false;
      o.token = v;
    } else if (a.flag("--quiet") || a.flag("-q")) {
      o.quiet = true;
    } else if (test && a.option("--junit", v, missing)) {
      if (!need("--junit")) return false;
      o.junit = v;
    } else if (test && a.option("--timeout", v, missing)) {
      if (!need("--timeout")) return false;
      if (!parse_seconds(v, o.timeout_s)) {
        err = "--timeout takes seconds, not \"" + v + "\"";
        return false;
      }
    } else if (test && a.option("--start-timeout", v, missing)) {
      if (!need("--start-timeout")) return false;
      if (!parse_seconds(v, o.start_timeout_s)) {
        err = "--start-timeout takes seconds, not \"" + v + "\"";
        return false;
      }
    } else if (test && a.flag("--parallel")) {
      o.parallel = true;
    } else if (test && a.option("--runtime", v, missing)) {
      if (!need("--runtime")) return false;
      o.runtime = v;
    } else if (a.peek().size() > 1 && a.peek()[0] == '-') {
      err = "unknown option " + a.peek();
      return false;
    } else if (o.config.empty()) {
      o.config = a.next();
    } else {
      err = "unexpected \"" + a.peek() + "\" (one CONFIG only)";
      return false;
    }
  }
  if (!o.runtime.empty()) {
    if (!o.config.empty() || !o.eds.empty()) {
      err = "--runtime runs the scenarios in the plugin's simulated devices; give no CONFIG or --eds with it";
      return false;
    }
    return true;
  }
  if (o.config.empty() && o.eds.empty()) {
    err = "give a CONFIG (canworks.json) or --eds FILE --node ID";
    return false;
  }
  if (o.has_nodes && o.config.empty()) {
    err = "--nodes picks nodes of a CONFIG; there is none";
    return false;
  }
  for (const auto& d : o.eds) {
    if (!d.has_node) {
      err = "--eds " + d.eds + " needs --node ID";
      return false;
    }
    if (d.node == 0 && d.name.empty()) {
      err = "--eds " + d.eds + " --node 0 needs --name NAME (a device without a node ID is addressed by its name)";
      return false;
    }
  }
  if (!o.sim_file.empty() && o.no_sim_file) {
    err = "--sim and --no-sim-file exclude each other";
    return false;
  }
  return true;
}

// ---- the interface ----

bool listed_in_env(const char* var, const std::string& iface) {
  const char* v = std::getenv(var);
  if (!v) return false;
  std::stringstream ss(v);
  std::string part;
  while (std::getline(ss, part, ','))
    if (part == iface) return true;
  return false;
}

// Checks (and with --setup-vcan prepares) the interface. Whether it is vcan
// comes from rtnetlink's IFLA_INFO_KIND (as can_adapter reads it): a vcan
// link reports kind "vcan", a CAN controller "can", slcan "slcan" or "can".
bool prepare_interface(const Options& o, bool& real) {
  auto ops = canopen_plugin::make_netlink_ops();
  canopen_plugin::LinkInfo info;
  int rc = ops->get(o.iface, info);
  if (rc == -ENODEV) {
    if (!o.setup_vcan) {
      fail(o.iface + " does not exist. Create it with --setup-vcan (needs root), or by hand:\n"
           "  sudo ip link add dev " + o.iface + " type vcan\n"
           "  sudo ip link set " + o.iface + " up");
      return false;
    }
    std::string add = "ip link add dev " + o.iface + " type vcan";
    std::printf("canworks-sim: %s\n", add.c_str());
    if (std::system(add.c_str()) != 0) {
      fail("cannot create " + o.iface + " (--setup-vcan needs root and the vcan kernel module: sudo modprobe vcan)");
      return false;
    }
    rc = ops->get(o.iface, info);
  }
  if (rc != 0) {
    fail("cannot read the link " + o.iface + ": " + std::strerror(-rc));
    return false;
  }
  bool is_vcan = info.kind == "vcan" && !listed_in_env("CANWORKS_SIM_TREAT_AS_REAL", o.iface);
  if (!is_vcan && !o.real_bus) {
    fail(o.iface + " is not a vcan interface" + (info.kind.empty() ? "" : " (kind " + info.kind + ")") +
         ": --real-bus is needed to put simulated devices on a real bus, where they can collide with real devices");
    return false;
  }
  real = !is_vcan;
  if (!info.up) {
    if (is_vcan && o.setup_vcan) {
      std::string up = "ip link set " + o.iface + " up";
      std::printf("canworks-sim: %s\n", up.c_str());
      if (std::system(up.c_str()) != 0 || ops->get(o.iface, info) != 0 || !info.up) {
        fail("cannot bring " + o.iface + " up (needs root)");
        return false;
      }
    } else {
      fail(o.iface + " is down; bring it up with: sudo ip link set " + o.iface + " up" +
           (is_vcan ? " (or use --setup-vcan)" : " (with its bit rate: type can bitrate N)"));
      return false;
    }
  }
  return true;
}

// ---- the session: config, devices, loop, engine ----

class Session {
 public:
  ~Session() {
    shutdown();
    remove_tree(work_dir_);
  }

  std::function<void(const canopen_sim::ScenarioResult&)> on_end;

  // Builds and starts everything; false after printing why.
  bool setup(const Options& o, bool control) {
    using namespace canopen_plugin;
    std::vector<std::string> errors;
    auto report = [&](const std::string& what) {
      for (const auto& e : errors) fail(e);
      if (errors.empty()) fail(what);
      return false;
    };
    // Prepared EDS copies of the lint live here while the simulator runs.
    const char* tmpdir = std::getenv("TMPDIR");
    std::string t = std::string(tmpdir && *tmpdir ? tmpdir : "/tmp") + "/canworks-sim.XXXXXX";
    std::vector<char> buf(t.begin(), t.end());
    buf.push_back(0);
    if (!mkdtemp(buf.data())) return report("cannot create a work directory " + t + ": " + std::strerror(errno));
    work_dir_ = buf.data();
    const std::string python = default_edslint_python();

    // The config's nodes, checked as the plugin checks them.
    std::vector<canopen_sim::DeviceSpec> specs;
    Config cfg;
    bool have_cfg = !o.config.empty();
    if (have_cfg) {
      if (!load_config(o.config, ImageLimits(), cfg, errors)) return report("cannot load " + o.config);
      for (const auto& w : cfg.warnings) warn(w);
      if (!run_eds_lint(cfg, python, work_dir_ + "/config", errors) || !check_eds_files(cfg, errors))
        return report("the EDS files of " + o.config + " do not load");
      for (unsigned id : o.nodes) {
        bool found = false;
        for (const auto& n : cfg.nodes) found = found || n.node_id == id;
        if (!found) errors.push_back("--nodes: node " + std::to_string(id) + " is not in " + o.config);
      }
      if (!errors.empty()) return report("");
      specs = sim_device_specs(cfg, false, o.nodes);
    }
    // --eds devices, linted like a config node's EDS.
    std::set<unsigned> cli_nodes;
    for (size_t i = 0; i < o.eds.size(); ++i) {
      const DeviceArg& a = o.eds[i];
      if (!file_exists(a.eds)) {
        errors.push_back("--eds " + a.eds + ": no such file");
        continue;
      }
      for (const auto& s : specs)
        if (a.node && s.node == a.node)
          errors.push_back("--eds " + a.eds + " --node " + std::to_string(a.node) + ": node " + std::to_string(a.node) +
                           " is already simulated");
      if (a.node && !cli_nodes.insert(a.node).second)
        errors.push_back("--node " + std::to_string(a.node) + " is given twice");
      Config one;
      NodeConfig n;
      n.node_id = a.node ? a.node : 1;
      n.name = a.name;
      n.eds = a.eds;
      n.eds_path = a.eds;
      one.nodes.push_back(n);
      if (!run_eds_lint(one, python, work_dir_ + "/eds-" + std::to_string(i), errors)) continue;
      for (const auto& w : one.warnings) warn(w);
      canopen_sim::DeviceSpec d;
      d.node = a.node;
      d.name = a.name;
      d.extra = true;  // not a node of a config: addressed by its name when it has no node ID
      d.eds_path = one.nodes[0].eds_path;
      specs.push_back(d);
    }
    if (!errors.empty()) return report("");

    // The simulation file.
    canopen_sim::SimFile file;
    std::string sim_path = o.sim_file;
    if (sim_path.empty() && have_cfg && !o.no_sim_file && file_exists(cfg.config_dir + "/simulation.json"))
      sim_path = cfg.config_dir + "/simulation.json";
    if (!sim_path.empty()) {
      if (!canopen_sim::load_sim_file(sim_path, file, errors)) return report("cannot load " + sim_path);
      if (file.schema_version >= 2) {
        // A version 2 file: the config's network, or the file's only section.
        std::string name;
        if (have_cfg) {
          name = sim_network_name(cfg);
        } else if (file.networks.size() == 1) {
          name = file.networks[0].network;
        } else {
          return report(sim_path + ": a version 2 file with " + std::to_string(file.networks.size()) +
                        " network sections needs --config to say which network to simulate");
        }
        canopen_sim::SimFile all = file;
        if (!canopen_sim::sim_file_section(all, name, file))
          say(sim_path + " has no section for network \"" + name + "\": default behaviour");
      }
      canopen_sim::SimFile check = file;
      for (unsigned id : cli_nodes) check.nodes.erase(id);
      if (have_cfg) {
        check_sim_file(cfg, check, errors);
      } else {
        for (const auto& kv : check.nodes) {
          bool known = false;
          for (const auto& x : file.extra) known = known || x.node == kv.first;
          if (!known)
            errors.push_back(file.path + ": nodes." + std::to_string(kv.first) + ": node " + std::to_string(kv.first) +
                             " is neither an --eds device nor an extra device");
        }
      }
      if (!errors.empty()) return report("");
      say("simulation file " + sim_path);
    }
    if (specs.empty() && file.extra.empty()) return report("no device to simulate");

    // The interface, and the free node ID check on a real bus.
    const bool virtual_bus = std::getenv("CANWORKS_SIM_VIRTUAL_BUS") != nullptr &&
                             std::string(std::getenv("CANWORKS_SIM_VIRTUAL_BUS")) == "1";
    bool real = false;
    if (!virtual_bus && !prepare_interface(o, real)) return false;
    if (real) {
      say("listening 1 s on " + o.iface + " for node IDs in use (real bus)");
      std::set<unsigned> seen;
      std::string err;
      if (!listen_node_ids(o.iface, 1000, seen, err)) return report(err);
      unsigned left = 0;
      for (auto& s : specs) {
        if (s.node && seen.count(s.node)) s.conflict = true;
        else ++left;
      }
      // Extra devices of the file whose node ID is taken: started (and
      // skipped) as conflicting specs, so the engine reports them too.
      for (auto it = file.extra.begin(); it != file.extra.end();) {
        if (it->node && seen.count(it->node)) {
          canopen_sim::DeviceSpec d;
          d.node = it->node;
          d.name = it->name;
          d.extra = true;
          d.eds_path = it->eds_path;
          d.has_behaviour = true;
          d.behaviour = it->behaviour;
          d.conflict = true;
          specs.push_back(d);
          it = file.extra.erase(it);
        } else {
          ++it;
          ++left;
        }
      }
      if (!seen.empty()) {
        std::string ids;
        for (unsigned id : seen) ids += (ids.empty() ? "" : ", ") + std::to_string(id);
        say("node IDs in use on " + o.iface + ": " + ids);
      }
      if (!left) return report("every node ID to simulate is taken on " + o.iface + "; nothing to simulate");
    }

    // The control channel.
    if (control) {
      std::string token, err;
      if (!resolve_token(o.token, o.token_file, nullptr, token, err)) return report(err);
      if (!is_loopback(o.bind) && token.empty())
        return report("--bind " + o.bind + " is not a loopback address: the control channel needs a token there "
                      "(--token or --token-file)");
      server_.reset(new ControlServer(CANWORKS_PLUGIN_VERSION, token, [this](const cJSON* req, const std::string& id,
                                                                            const std::string& peer) {
        return sim_->Handle(req, id, peer);
      }));
      if (!server_->listen(o.bind, o.port, err)) return report(err);
    }

    if (!o.state_dir.empty() && !make_dirs(o.state_dir)) return report("cannot create --state-dir " + o.state_dir);

    // The loop and the engine.
    try {
      io_guard_.reset(new lely::io::IoGuard);
      ctx_.reset(new lely::io::Context);
      poll_.reset(new lely::io::Poll(*ctx_));
      loop_.reset(new lely::ev::Loop(poll_->get_poll()));
      exec_.reset(new lely::ev::Executor(loop_->get_executor()));
      auto log = [](canopen_sim::Host::Level l, const std::string& m) {
        if (l == canopen_sim::Host::Level::Error)
          error(m);
        else if (l == canopen_sim::Host::Level::Warn)
          warn(m);
        else
          say(m);
      };
      if (virtual_bus) {
        clock_timer_.reset(new lely::io::Timer(*poll_, *exec_, CLOCK_MONOTONIC));
        vbus_.reset(new lely::io::VirtualCanController(clock_timer_->get_clock()));
        host_.reset(new canopen_sim::LoopHost(*ctx_, *poll_, *exec_, *vbus_, log));
      } else {
        host_.reset(new canopen_sim::LoopHost(*ctx_, *poll_, *exec_, o.iface, real, log));
      }
      canopen_sim::SimOptions opt;
      opt.defaults = !o.no_defaults;
      opt.state_dir = o.state_dir;
      opt.version = CANWORKS_PLUGIN_VERSION;
      opt.simulated_network = virtual_bus;
      size_t count = specs.size() + file.extra.size();
      sim_.reset(new canopen_sim::Simulator(*host_, specs, file, opt));
      sim_->on_scenario_end = [this](const canopen_sim::ScenarioResult& r) {
        if (on_end) on_end(r);
      };
      say(std::string("canworks-sim ") + CANWORKS_PLUGIN_VERSION + ": " + std::to_string(count) + " device" +
          (count == 1 ? "" : "s") + " on " + (virtual_bus ? std::string("an in-process virtual bus") : o.iface) +
          (real ? " (REAL bus)" : "") + (server_ ? ", control on " + server_->address() : ""));
      if (!sim_->Start(errors)) return report("the simulation does not start");
    } catch (const std::exception& e) {
      return report(std::string("cannot start on ") + o.iface + ": " + e.what());
    }
    return true;
  }

  canopen_sim::Simulator& sim() { return *sim_; }

  // One slice of the loop, then the control channel.
  void slice() {
    loop_->run_for(kSlice);
    if (server_) server_->poll_once();
  }

  void shutdown() {
    if (done_ || !loop_) return;
    done_ = true;
    server_.reset();
    if (sim_) sim_->Stop();
    ctx_->shutdown();
    for (int i = 0; i < 100 && !loop_->stopped(); ++i) loop_->run_for(kSlice);
    loop_->stop();
    sim_.reset();
    host_.reset();
    vbus_.reset();
    clock_timer_.reset();
  }

 private:
  std::string work_dir_;
  std::unique_ptr<lely::io::IoGuard> io_guard_;
  std::unique_ptr<lely::io::Context> ctx_;
  std::unique_ptr<lely::io::Poll> poll_;
  std::unique_ptr<lely::ev::Loop> loop_;
  std::unique_ptr<lely::ev::Executor> exec_;
  std::unique_ptr<lely::io::Timer> clock_timer_;
  std::unique_ptr<lely::io::VirtualCanController> vbus_;
  std::unique_ptr<canopen_sim::LoopHost> host_;
  std::unique_ptr<canopen_sim::Simulator> sim_;
  std::unique_ptr<ControlServer> server_;
  bool done_ = false;
};

// ---- test runs ----

struct Outcome {
  std::string name;
  bool passed = false;
  std::string message;
  double seconds = 0;
};

// Runs scenarios one after another (or all at once) and collects their
// outcomes, whatever runs them: local devices or a remote simulator.
class TestQueue {
 public:
  using StartFn = std::function<bool(const std::string&, std::string&)>;
  using StopFn = std::function<void(const std::string&)>;
  using PumpFn = std::function<void()>;

  TestQueue(std::vector<std::string> names, bool parallel, double timeout_s)
      : names_(std::move(names)), parallel_(parallel), timeout_s_(timeout_s) {}

  // A scenario ended (from the engine's callback or a poll).
  void finished(const std::string& name, bool passed, const std::string& message) {
    auto it = running_.find(name);
    if (it == running_.end()) return;
    record(name, passed, message, std::chrono::duration<double>(Clock::now() - it->second).count());
    running_.erase(it);
  }

  // Exit code: 0 every scenario passed, 1 one failed, 2 interrupted.
  int run(const StartFn& start, const StopFn& stop, const PumpFn& pump) {
    const auto t0 = Clock::now();
    const auto deadline = t0 + std::chrono::milliseconds(static_cast<long long>(timeout_s_ * 1000));
    size_t next = 0;
    auto start_next = [&]() {
      const std::string name = names_[next++];
      running_[name] = Clock::now();
      std::string err;
      if (!start(name, err)) finished(name, false, "cannot start: " + err);
    };
    while (outcomes_.size() < names_.size()) {
      if (parallel_) {
        while (next < names_.size()) start_next();
      } else if (running_.empty() && next < names_.size()) {
        start_next();
        continue;
      }
      if (g_signal || Clock::now() >= deadline) {
        std::string why = g_signal ? std::string("interrupted")
                                   : "timed out: --timeout of " + fmt_seconds(timeout_s_) + " s reached";
        std::vector<std::string> names;
        for (const auto& kv : running_) names.push_back(kv.first);
        for (const auto& n : names) {
          finished(n, false, why);
          stop(n);
        }
        while (next < names_.size()) record(names_[next++], false, "not run: " + why, 0);
        interrupted_ = g_signal != 0;
        break;
      }
      pump();
    }
    total_ = std::chrono::duration<double>(Clock::now() - t0).count();
    size_t failed = 0;
    for (const auto& o : outcomes_) failed += o.passed ? 0 : 1;
    say_always(std::to_string(outcomes_.size() - failed) + " passed, " + std::to_string(failed) + " failed");
    if (interrupted_) return kExitUsage;
    return failed ? kExitFailed : kExitOk;
  }

  // JUnit XML: one testsuite, one testcase per scenario.
  bool write_junit(const std::string& path) const {
    size_t failed = 0;
    for (const auto& o : outcomes_) failed += o.passed ? 0 : 1;
    std::ofstream out(path);
    out << "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n";
    out << "<testsuite name=\"canworks-sim\" tests=\"" << outcomes_.size() << "\" failures=\"" << failed
        << "\" errors=\"0\" skipped=\"0\" time=\"" << fmt_seconds(total_) << "\">\n";
    for (const auto& name : names_) {
      for (const auto& o : outcomes_) {
        if (o.name != name) continue;
        out << "  <testcase classname=\"canworks-sim\" name=\"" << xml_escape(o.name) << "\" time=\""
            << fmt_seconds(o.seconds) << "\"";
        if (o.passed) {
          out << "/>\n";
        } else {
          out << ">\n    <failure message=\"" << xml_escape(o.message) << "\">" << xml_escape(o.message)
              << "</failure>\n  </testcase>\n";
        }
      }
    }
    out << "</testsuite>\n";
    out.close();
    return static_cast<bool>(out);
  }

  static std::string fmt_seconds(double s) {
    char b[32];
    std::snprintf(b, sizeof b, "%.3f", s);
    return b;
  }

 private:
  void record(const std::string& name, bool passed, const std::string& message, double seconds) {
    Outcome o;
    o.name = name;
    o.passed = passed;
    o.message = message;
    o.seconds = seconds;
    outcomes_.push_back(o);
    say_always(std::string(passed ? "PASS " : "FAIL ") + name + " (" + fmt_seconds(seconds) + " s)" +
               (passed ? "" : ": " + message));
  }

  std::vector<std::string> names_;
  bool parallel_;
  double timeout_s_;
  std::map<std::string, Clock::time_point> running_;
  std::vector<Outcome> outcomes_;
  bool interrupted_ = false;
  double total_ = 0;
};

// The scenarios to run: those named, or those marked "test". Empty after
// printing why.
std::vector<std::string> pick_scenarios(const std::vector<std::string>& wanted,
                                        const std::vector<std::pair<std::string, bool>>& known) {
  std::vector<std::string> names;
  if (wanted.empty()) {
    for (const auto& k : known)
      if (k.second) names.push_back(k.first);
    if (names.empty())
      fail("no scenario to run: name one with --scenario, or mark scenarios with \"test\": true");
    return names;
  }
  for (const auto& w : wanted) {
    bool found = false;
    for (const auto& k : known) found = found || k.first == w;
    if (!found) {
      std::string list;
      for (const auto& k : known) list += (list.empty() ? "" : ", ") + k.first;
      fail("no scenario \"" + w + "\"" + (list.empty() ? " (there are none)" : " (there are: " + list + ")"));
      return {};
    }
    names.push_back(w);
  }
  return names;
}

int finish_test(const TestQueue& q, const Options& o, int rc) {
  if (!o.junit.empty() && !q.write_junit(o.junit)) {
    fail("cannot write " + o.junit);
    return kExitUsage;
  }
  return rc;
}

int test_local(const Options& o) {
  Session s;
  TestQueue* queue = nullptr;
  s.on_end = [&](const canopen_sim::ScenarioResult& r) {
    if (queue) queue->finished(r.name, r.passed, r.message);
  };
  if (!s.setup(o, false)) return kExitUsage;
  std::vector<std::pair<std::string, bool>> known;
  for (const auto& sc : s.sim().Scenarios()) known.emplace_back(sc.name, sc.test);
  std::vector<std::string> names = pick_scenarios(o.scenarios, known);
  if (names.empty()) return kExitUsage;

  // Until every device is OPERATIONAL (the master configured and started
  // them), or --start-timeout.
  const auto until = Clock::now() + std::chrono::milliseconds(static_cast<long long>(o.start_timeout_s * 1000));
  while (!g_signal && !s.sim().AllOperational() && Clock::now() < until) s.slice();
  if (g_signal) return kExitUsage;
  if (s.sim().AllOperational())
    say("every device is OPERATIONAL; running " + std::to_string(names.size()) + " scenario(s)");
  else
    warn("not every device is OPERATIONAL after " + TestQueue::fmt_seconds(o.start_timeout_s) +
         " s (--start-timeout); running the scenarios anyway");

  TestQueue q(names, o.parallel, o.timeout_s);
  queue = &q;
  int rc = q.run([&](const std::string& n, std::string& err) { return s.sim().StartScenario(n, err); },
                 [&](const std::string& n) { s.sim().StopScenario(n); }, [&]() { s.slice(); });
  queue = nullptr;
  s.shutdown();
  return finish_test(q, o, rc);
}

std::string jstr(const cJSON* o, const char* k) {
  const cJSON* v = cJSON_GetObjectItemCaseSensitive(o, k);
  return cJSON_IsString(v) ? v->valuestring : "";
}

// --runtime: the scenarios run in the plugin's simulated devices (or, with an
// explicit port, in another standalone simulator), over the diagnostics
// channel's sim_ requests.
int test_remote(const Options& o) {
  std::string host, err, token;
  unsigned port = 0;
  if (!split_host_port(o.runtime, kDiagPort, host, port)) {
    fail("--runtime takes HOST[:PORT], not \"" + o.runtime + "\"");
    return kExitUsage;
  }
  if (!resolve_token(o.token, o.token_file, "CANWORKS_TOKEN", token, err)) {
    fail(err);
    return kExitUsage;
  }
  ControlClient c;
  if (!c.connect(host, port, token, err)) {
    fail(err);
    return kExitUsage;
  }
  auto ask = [&](const char* op, const std::string& name, std::string& e) -> cJSON* {
    cJSON* req = cJSON_CreateObject();
    cJSON_AddStringToObject(req, "op", op);
    if (!name.empty()) cJSON_AddStringToObject(req, "name", name.c_str());
    cJSON* a = c.request(req, e);
    cJSON_Delete(req);
    if (a && !answer_error(a).empty()) {
      e = answer_error(a);
      cJSON_Delete(a);
      return nullptr;
    }
    return a;
  };
  cJSON* list = ask("sim_scenario_list", "", err);
  if (!list) {
    fail(o.runtime + ": " + err);
    return kExitUsage;
  }
  std::vector<std::pair<std::string, bool>> known;
  const cJSON* s;
  cJSON_ArrayForEach(s, cJSON_GetObjectItemCaseSensitive(cJSON_GetObjectItemCaseSensitive(list, "result"), "scenarios"))
    known.emplace_back(jstr(s, "name"), cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(s, "test")));
  cJSON_Delete(list);
  std::vector<std::string> names = pick_scenarios(o.scenarios, known);
  if (names.empty()) return kExitUsage;

  // Until every simulated device there is OPERATIONAL, or --start-timeout.
  const auto until = Clock::now() + std::chrono::milliseconds(static_cast<long long>(o.start_timeout_s * 1000));
  bool all_op = false;
  while (!g_signal && Clock::now() < until) {
    cJSON* st = ask("sim_status", "", err);
    if (!st) {
      fail(o.runtime + ": " + err);
      return kExitUsage;
    }
    all_op = true;
    const cJSON* d;
    cJSON_ArrayForEach(d, cJSON_GetObjectItemCaseSensitive(cJSON_GetObjectItemCaseSensitive(st, "result"), "devices")) {
      if (cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(d, "conflict")) || jstr(d, "power") != "on") continue;
      all_op = all_op && jstr(d, "nmt") == "operational";
    }
    cJSON_Delete(st);
    if (all_op) break;
    std::this_thread::sleep_for(std::chrono::milliseconds(200));
  }
  if (g_signal) return kExitUsage;
  if (!all_op)
    warn("not every simulated device on " + o.runtime + " is OPERATIONAL after " +
         TestQueue::fmt_seconds(o.start_timeout_s) + " s (--start-timeout); running the scenarios anyway");

  TestQueue q(names, o.parallel, o.timeout_s);
  std::set<std::string> started;
  bool lost = false;
  auto pump = [&]() {
    std::this_thread::sleep_for(std::chrono::milliseconds(200));
    std::string e;
    cJSON* l = ask("sim_scenario_list", "", e);
    if (!l) {
      if (!lost) error(o.runtime + ": " + e);
      lost = true;
      for (const auto& n : started) q.finished(n, false, "connection lost: " + e);
      return;
    }
    const cJSON* x;
    cJSON_ArrayForEach(x, cJSON_GetObjectItemCaseSensitive(cJSON_GetObjectItemCaseSensitive(l, "result"), "scenarios")) {
      std::string st = jstr(x, "state"), n = jstr(x, "name");
      if (!started.count(n)) continue;
      if (st == "passed" || st == "failed" || st == "stopped")
        q.finished(n, st == "passed", st == "stopped" ? "stopped" : jstr(x, "message"));
    }
    cJSON_Delete(l);
  };
  int rc = q.run(
      [&](const std::string& n, std::string& e) {
        if (lost) {
          e = "connection lost";
          return false;
        }
        cJSON* a = ask("sim_scenario_start", n, e);
        if (!a) return false;
        cJSON_Delete(a);
        started.insert(n);
        return true;
      },
      [&](const std::string& n) {
        std::string e;
        cJSON_Delete(ask("sim_scenario_stop", n, e));
      },
      pump);
  return finish_test(q, o, rc);
}

}  // namespace

int run_main(Args& args) {
  Options o;
  std::string err;
  if (args.done()) {
    print_usage(false);
    return kExitUsage;
  }
  if (!parse_options(args, o, false, err)) {
    fail(err);
    return kExitUsage;
  }
  g_quiet = o.quiet;
  canopen_plugin::set_log_sink(plugin_log);
  canopen_plugin::route_lely_diagnostics();
  install_signals();
  Session s;
  s.on_end = [](const canopen_sim::ScenarioResult& r) {
    // Failures come as error lines from the engine; with --quiet the other
    // results still need a line.
    if (g_quiet && r.passed) say_always("scenario " + r.name + ": passed");
    if (g_quiet && r.stopped) say_always("scenario " + r.name + ": stopped");
  };
  if (!s.setup(o, true)) return kExitUsage;
  for (const auto& name : o.scenarios) {
    if (!s.sim().StartScenario(name, err)) {
      error("--scenario " + name + ": " + err);
      return kExitUsage;
    }
  }
  while (!g_signal) s.slice();
  say(std::string("stopping (") + (g_signal == SIGINT ? "SIGINT" : "SIGTERM") + ")");
  s.shutdown();
  say("stopped");
  return kExitOk;
}

int test_main(Args& args) {
  Options o;
  std::string err;
  if (!parse_options(args, o, true, err)) {
    fail(err);
    return kExitUsage;
  }
  g_quiet = o.quiet;
  canopen_plugin::set_log_sink(plugin_log);
  canopen_plugin::route_lely_diagnostics();
  install_signals();
  return o.runtime.empty() ? test_local(o) : test_remote(o);
}

}  // namespace sim_tool
