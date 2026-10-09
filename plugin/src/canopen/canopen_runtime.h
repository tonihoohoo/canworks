// canopen_runtime.h - the CANopen side of the plugin entry points: the checks
// that need the EDS files, the log lines at load, and the running networks
// (master, slave, gateway, simulated devices) behind NetworkRuntime.

#ifndef CANWORKS_CANOPEN_RUNTIME_H
#define CANWORKS_CANOPEN_RUNTIME_H

#include <cstdint>
#include <memory>
#include <string>
#include <vector>

#include "config.h"
#include "network_runtime.h"

namespace canopen_plugin {

// Routes Lely's diagnostics to the plugin log (init()).
void canopen_init_logging();

// The CANopen networks' EDS lint and checks, then the gateway's routes;
// logs what they settled. False with `errors` filled on a problem.
bool canopen_check(ConfigSet& set, std::vector<std::string>& errors);

// The "loaded" and SYNC lines of a CANopen network.
void canopen_log_loaded(const ConfigSet& set, const Config& cfg, uint64_t base_tick_ns);

// Everything the CANopen networks of one start share (the gateway link).
class CanopenShared;

// Makes the CANopen networks of `set`: out[i] for network i, others left
// as they are. Logs and returns false when one cannot be made (dcfgen, the
// simulation file); nothing has started then.
bool canopen_create(ConfigSet& set, uint64_t base_tick_ns, const char* version,
                    std::shared_ptr<CanopenShared>& shared, std::vector<std::unique_ptr<NetworkRuntime>>& out);

// The SDO function blocks' request channel (canopen-plc-sdo): opened for
// `networks` networks while the PLC runs.
void canopen_open_plc_requests(unsigned networks);
void canopen_close_plc_requests();
const void* canopen_plc_api_table(uint32_t version);

}  // namespace canopen_plugin

#endif  // CANWORKS_CANOPEN_RUNTIME_H
