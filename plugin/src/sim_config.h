// sim_config.h - simulated devices from a canopen_config.json
// (docs/simulator.md): which nodes, built how, and the free node ID check on
// a real interface. Shared by the plugin and openplc-canopen-sim.

#ifndef CANOPEN_SIM_CONFIG_H
#define CANOPEN_SIM_CONFIG_H

#include <set>
#include <string>
#include <vector>

#include "config.h"
#include "sim_engine.h"

namespace canopen_plugin {

// Device specs for the nodes of `cfg` that are simulated: those with
// `simulate` (only_flagged), or those in `only` (empty: every node).
std::vector<canopen_sim::DeviceSpec> sim_device_specs(const Config& cfg, bool only_flagged,
                                                      const std::set<unsigned>& only = {});

// The simulation file's node entries must name nodes of the config (or
// extra devices).
bool check_sim_file(const Config& cfg, const canopen_sim::SimFile& file, std::vector<std::string>& errors);

// What simulated devices there are, for the start warning ("" = none).
// `slave_network`: the slave network that shares the simulated bus, if any.
std::string sim_summary(const Config& cfg, const canopen_sim::SimFile& file, const std::string& slave_network = "");

// Listens on a SocketCAN interface for `ms` and returns the node IDs that
// sent a heartbeat, boot-up, EMCY or SDO answer. False with `err` when the
// interface cannot be opened.
bool listen_node_ids(const std::string& iface, unsigned ms, std::set<unsigned>& seen, std::string& err);

}  // namespace canopen_plugin

#endif  // CANOPEN_SIM_CONFIG_H
