// dcf_gen.h - turns the validated JSON config into Lely device configuration
// files by running Lely's dcfgen on the device.
//
// Output goes to <config_dir>/.canopen/: dcfgen.yml (the generated input),
// master.dcf, one <node>.bin concise DCF per slave, dcfgen.log and
// inputs.hash. dcfgen reads each node's eds_path, the prepared copy in
// eds/node_<id>.eds when run_eds_lint made one (eds_lint.h), and runs with
// --no-strict: the plugin's lint has already judged the findings. If the
// hash of the YAML, the startup SDOs and every EDS file matches the last run,
// dcfgen is skipped.
//
// Startup SDOs (the JSON's per-node `sdo` list) are not passed to dcfgen,
// whose `sdo` key reads only integer values; they are appended to the node's
// configuration downloads after dcfgen's PDO parameters, in list order.
//
// The master DCF gets an EMCY consumer entry (1028) for every node ID, not only
// the configured slaves dcfgen lists, so EMCY messages from unknown nodes are
// seen and reported.

#ifndef CANOPEN_DCF_GEN_H
#define CANOPEN_DCF_GEN_H

#include <cstdint>
#include <map>
#include <string>
#include <vector>

#include "config.h"

namespace canopen_plugin {

// One SDO download from a concise DCF.
struct SdoWrite {
  uint16_t index = 0;
  uint8_t subindex = 0;
  std::vector<uint8_t> data;
};

struct GeneratedConfig {
  std::string work_dir;
  std::string master_dcf;
  // node ID -> SDO downloads that configure the slave (from <node>.bin).
  std::map<unsigned, std::vector<SdoWrite>> slave_sdos;
  // node ID -> configuration date and time (0x1020 sub 1, 2) the master
  // expects, for nodes with config_check; never 0.
  std::map<unsigned, std::pair<uint32_t, uint32_t>> config_stamps;
  bool reused = false;  // true if dcfgen was skipped (inputs unchanged)
};

// The configuration date and time for a node with config_check: a hash of
// the downloads it gets (index, sub-index, bytes, in order) and the 0x1010
// sub-index it saves to, so it changes exactly when that download changes.
// Neither half is 0 (Lely skips the check when one is 0).
std::pair<uint32_t, uint32_t> config_stamp(const std::vector<SdoWrite>& sdos, unsigned store_subindex);

// A stable text form of every startup SDO, part of the input hash.
std::string startup_sdo_key(const Config& cfg);

// The dcfgen YAML for a config (exposed for tests).
std::string make_dcfgen_yaml(const Config& cfg, const std::string& work_dir);

// Generates (or reuses) the device configuration. `dcfgen` is the program to
// run. Returns false and appends messages to `errors` on failure.
bool generate_device_config(const Config& cfg, const std::string& dcfgen,
                            GeneratedConfig& out, std::vector<std::string>& errors);

// Parses a concise DCF (.bin) file. Exposed for tests.
bool read_concise_dcf(const std::string& path, std::vector<SdoWrite>& out,
                      std::string& error);

// The dcfgen to run: $CANOPEN_DCFGEN, else the installer's venv, else PATH.
std::string default_dcfgen();

}  // namespace canopen_plugin

#endif  // CANOPEN_DCF_GEN_H
