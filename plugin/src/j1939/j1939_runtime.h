// j1939_runtime.h - the J1939 side of the plugin entry points: the "loaded"
// line and the running networks behind NetworkRuntime.

#ifndef CANWORKS_J1939_RUNTIME_H
#define CANWORKS_J1939_RUNTIME_H

#include <memory>
#include <vector>

#include "config.h"
#include "network_runtime.h"

namespace canopen_plugin {

// The "loaded" line of a J1939 network.
void j1939_log_loaded(const ConfigSet& set, const Config& cfg);

// Makes the J1939 networks of `set`: out[i] for network i, others left as
// they are.
void j1939_create(const ConfigSet& set, const char* version, std::vector<std::unique_ptr<NetworkRuntime>>& out);

// The trouble code blocks' job table (j1939_plc_jobs.h): open while the
// networks run, closed (every job cancelled) when the PLC stops.
void j1939_open_plc_jobs(const ConfigSet& set);
void j1939_close_plc_jobs();

}  // namespace canopen_plugin

#endif  // CANWORKS_J1939_RUNTIME_H
