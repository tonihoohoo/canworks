// canopen_check - validates a canopen_config.json the way the plugin does at
// PLC start (JSON, EDS lint, EDS files, dcfgen), without opening the CAN
// interface. The EDS lint needs the deploy tool (default_edslint_python()).
//
//   canopen_check [--buffer-size N] [--no-dcfgen] [--dump-writes] <canopen_config.json>
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
    std::fprintf(stderr, "usage: %s [--buffer-size N] [--no-dcfgen] [--dump-writes] <canopen_config.json>\n", argv[0]);
    return 2;
  }
  route_lely_diagnostics();
  Config cfg;
  std::vector<std::string> errors;
  bool loaded = load_config(path, limits, cfg, errors);
  bool checked = loaded && run_eds_lint(cfg, default_edslint_python(), cfg.config_dir + "/.canopen", errors) &&
                 check_eds_files(cfg, errors);
  for (const auto& w : cfg.warnings) std::printf("warning: %s\n", w.c_str());
  for (const auto& m : cfg.notes) std::printf("note: %s\n", m.c_str());
  if (!checked) {
    for (const auto& e : errors) std::printf("error: %s\n", e.c_str());
    return 1;
  }
  std::printf("ok: %s adapter %s, %u bit/s, master node ID %u, %zu slave(s)\n", cfg.adapter.type.c_str(),
              cfg.adapter.interface.c_str(), cfg.adapter.bitrate, cfg.master.node_id, cfg.nodes.size());
  for (const auto& n : cfg.nodes) std::printf("    %s: EDS %s\n", n.label().c_str(), n.eds_path.c_str());
  if (!run_dcfgen) return 0;
  GeneratedConfig gen;
  if (!generate_device_config(cfg, default_dcfgen(), gen, errors)) {
    for (const auto& e : errors) std::printf("error: %s\n", e.c_str());
    return 1;
  }
  std::printf("ok: device configuration %s in %s\n", gen.reused ? "unchanged" : "generated", gen.work_dir.c_str());
  for (const auto& s : gen.slave_sdos) std::printf("    node %u: %zu SDO downloads at boot\n", s.first, s.second.size());
  if (!dump_writes) return 0;
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
  return 0;
}
