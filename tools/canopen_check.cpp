// canopen_check - validates a canworks.json the way the plugin does at
// PLC start (JSON, EDS lint, EDS files, dcfgen), without opening the CAN
// interface. The EDS lint needs the deploy tool (default_edslint_python()).
//
//   canopen_check [--buffer-size N] [--no-dcfgen] [--dump-writes] <canworks.json>
//
// Exit status 0 if the configuration would load.
//
// --dump-writes also prints each node's configuration download as the
// plugin performs it, one write per line in download order:
//   write <node ID> 0x<index> <sub-index> <data bytes, hex>
// followed by the boot steps that are not object writes:
//   step <node ID> restore <0x1011 sub-index>
//   step <node ID> firmware <software_file>
// The deploy tool's DCF export is tested against this list.
//
// A file with several networks (schema_version 2) is checked network by
// network; its output then puts "network <name>" before each network's lines.
// A slave network (canopen-slave-device spec) runs no dcfgen; its line says
// "slave node ID <n>" (or "LSS") and lists the bound objects. A gateway
// section is checked against the upper network's EDS. A J1939 network is
// checked as the plugin does; its line names the ECU's address and its PGNs.

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

#include "config.h"
#include "dcf_gen.h"
#include "eds_check.h"
#include "eds_lint.h"
#include "log.h"

using namespace canopen_plugin;

int main(int argc, char** argv) {
  ImageLimits limits;
  bool run_dcfgen = true;
  bool dump_writes = false;
  const char* path = nullptr;
  for (int i = 1; i < argc; ++i) {
    if (!std::strcmp(argv[i], "--buffer-size") && i + 1 < argc)
      limits.buffer_size = std::atoi(argv[++i]);
    else if (!std::strcmp(argv[i], "--no-dcfgen"))
      run_dcfgen = false;
    else if (!std::strcmp(argv[i], "--dump-writes"))
      dump_writes = true;
    else
      path = argv[i];
  }
  if (!path) {
    std::fprintf(stderr, "usage: %s [--buffer-size N] [--no-dcfgen] [--dump-writes] <canworks.json>\n", argv[0]);
    return 2;
  }
  route_lely_diagnostics();
  ConfigSet set;
  std::vector<std::string> errors;
  bool checked = load_config_set(path, limits, set, errors);
  for (const auto& w : set.warnings) std::printf("warning: %s\n", w.c_str());
  for (const auto& m : set.notes) std::printf("note: %s\n", m.c_str());
  for (auto& cfg : set.networks) {
    // A J1939 network has no EDS files.
    bool ok = checked && (cfg.is_j1939() || (run_eds_lint(cfg, default_edslint_python(), cfg.work_dir, errors) &&
                                             check_eds_files(cfg, errors)));
    for (const auto& w : cfg.warnings) std::printf("warning: %s%s\n", set.several() ? (cfg.network + ": ").c_str() : "", w.c_str());
    for (const auto& m : cfg.notes) std::printf("note: %s%s\n", set.several() ? (cfg.network + ": ").c_str() : "", m.c_str());
    checked = checked && ok;
  }
  if (checked) {
    checked = check_gateway_eds(set, errors);
    for (const auto& w : set.warnings) std::printf("warning: %s\n", w.c_str());
  }
  if (!checked) {
    for (const auto& e : errors) std::printf("error: %s\n", e.c_str());
    return 1;
  }
  for (const auto& cfg : set.networks) {
    if (set.several()) std::printf("network %s\n", cfg.network.c_str());
    if (cfg.is_j1939()) {
      const J1939Config& j = cfg.j1939;
      std::printf("ok: %s adapter %s, %u bit/s, J1939 ECU at address %u, %zu received, %zu sent, %zu requested PGN(s)\n",
                  cfg.adapter.type.c_str(), cfg.adapter.interface.c_str(), cfg.adapter.bitrate, j.ecu.address,
                  j.rx.size(), j.tx.size(), j.requests.size());
      continue;
    }
    if (cfg.is_slave()) {
      std::string id = cfg.slave.lss ? std::string("LSS") : std::to_string(cfg.slave.node_id);
      std::printf("ok: %s adapter %s, %u bit/s, slave node ID %s, %zu bound object(s)\n", cfg.adapter.type.c_str(),
                  cfg.adapter.interface.c_str(), cfg.adapter.bitrate, id.c_str(), cfg.slave.objects.size());
      std::printf("    slave: EDS %s\n", cfg.slave.eds_path.c_str());
      for (const auto& o : cfg.slave.objects)
        std::printf("    %s %s %s\n", o.label().c_str(), o.input ? "->" : "<-", o.location.str().c_str());
      continue;
    }
    std::printf("ok: %s adapter %s, %u bit/s, master node ID %u, %zu slave(s)\n", cfg.adapter.type.c_str(),
                cfg.adapter.interface.c_str(), cfg.adapter.bitrate, cfg.master.node_id, cfg.nodes.size());
    for (const auto& n : cfg.nodes) std::printf("    %s: EDS %s\n", n.label().c_str(), n.eds_path.c_str());
  }
  if (set.gateway.enabled)
    std::printf("ok: gateway, upper network %s, %zu route(s)\n", set.networks[set.gateway.upper].network.c_str(),
                set.gateway.routes.size());
  if (!run_dcfgen) return 0;
  for (const auto& cfg : set.networks) {
    if (cfg.is_slave() || cfg.is_j1939()) continue;  // the slave runs its EDS as it is; J1939 has none
    if (set.several()) std::printf("network %s\n", cfg.network.c_str());
    GeneratedConfig gen;
    if (!generate_device_config(cfg, default_dcfgen(), gen, errors)) {
      for (const auto& e : errors) std::printf("error: %s\n", e.c_str());
      return 1;
    }
    std::printf("ok: device configuration %s in %s\n", gen.reused ? "unchanged" : "generated", gen.work_dir.c_str());
    for (const auto& s : gen.slave_sdos) std::printf("    node %u: %zu SDO downloads at boot\n", s.first, s.second.size());
    if (!dump_writes) continue;
    for (const auto& n : cfg.nodes) {
      auto it = gen.slave_sdos.find(n.node_id);
      if (it != gen.slave_sdos.end())
        for (const auto& w : it->second) {
          std::printf("write %u 0x%04X %u ", n.node_id, w.index, unsigned(w.subindex));
          for (uint8_t b : w.data) std::printf("%02x", b);
          std::printf("\n");
        }
      if (n.has_restore_configuration) std::printf("step %u restore %u\n", n.node_id, n.restore_configuration);
      if (!n.software_file.empty()) std::printf("step %u firmware %s\n", n.node_id, n.software_file.c_str());
    }
  }
  return 0;
}
