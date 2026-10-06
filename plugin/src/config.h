// config.h - canopen_config.json: data model, parser and validator.
//
// The format mirrors the runtime's EtherCAT plugin: one JSON file listing the
// bus, the master and every slave with its EDS file and PDO entries, each PDO
// entry carrying an explicit IEC location. See docs/config.md.

#ifndef CANOPEN_CONFIG_H
#define CANOPEN_CONFIG_H

#include <cstdint>
#include <set>
#include <string>
#include <utility>
#include <vector>

#include "iec_location.h"

namespace canopen_plugin {

struct PdoEntry {
  uint16_t index = 0;
  uint8_t subindex = 0;
  CoType type = CoType::UNSIGNED8;
  IecLocation location;
};

struct PdoConfig {
  // PDO number on the slave, 1-512 (TPDO n uses objects 0x1800+n-1/0x1A00+n-1,
  // RPDO n uses 0x1400+n-1/0x1600+n-1). Defaults to the position in the list.
  unsigned number = 0;
  // 11-bit COB-ID. 0 means the CiA 301 default, which exists for PDOs 1-4.
  // cob_auto: given as "auto"; for PDOs above 4 the parser fills cob_id
  // with a free COB-ID.
  uint32_t cob_id = 0;
  bool cob_auto = false;
  bool has_cob_id = false;  // set in the JSON (a number, or "auto" resolved)
  // Transmission type (CiA 301): 0-240 synchronous, 254/255 event-driven.
  // Without has_transmission the slave keeps its EDS default.
  bool has_transmission = false;
  unsigned transmission = 0;
  // Communication parameters; each written only when has_* is set, so the
  // slave keeps its EDS value otherwise. Inhibit time and SYNC start value
  // are TPDO-only; on an RPDO the event timer is the slave's deadline.
  bool has_inhibit_time = false;
  unsigned inhibit_time_us = 0;  // a multiple of 100
  bool has_event_timer = false;
  unsigned event_timer_ms = 0;
  bool has_sync_start = false;
  unsigned sync_start = 0;
  // Who sets the PDO's mapping object (JSON `mapping`): the plugin writes it
  // from `entries` ("config"), or the node keeps its EDS default mapping
  // ("device"). Unset follows the EDS: "device" when the mapping object is
  // not writable. check_eds_files resolves it into device_mapping.
  enum class Mapping { Unset, Config, Device };
  Mapping mapping = Mapping::Unset;
  bool device_mapping = false;
  std::vector<PdoEntry> entries;
};

// A startup SDO: an object write sent while the node is configured, after
// the PDO parameters and before NMT start.
struct StartupSdo {
  uint16_t index = 0;
  uint8_t subindex = 0;
  CoType type = CoType::UNSIGNED8;
  std::vector<uint8_t> data;  // the value, little-endian, sized by `type`
  std::string value_text;     // the value as written, for messages
};

// An object moved over SDO between the node and one IEC location while the
// network runs (sdo_variables). A read entry lands in an input location after
// each boot of the node, every period_ms and on each trigger edge; a write
// entry comes from an output location, after each boot and on change (the
// PLC owns the object) or, with a trigger, on each rising edge only.
enum class SdoDirection { Read, Write };

struct SdoVariable {
  std::string name;
  uint16_t index = 0;
  uint8_t subindex = 0;
  CoType type = CoType::UNSIGNED8;
  SdoDirection direction = SdoDirection::Read;
  IecLocation location;
  unsigned period_ms = 0;  // read entries: 0 = no periodic read
  bool has_trigger = false;
  IecLocation trigger_location;  // %QX
  bool has_status = false;
  IecLocation status_location;  // %IB, see SdoStatus in network.h
  bool has_abort_code = false;
  IecLocation abort_code_location;  // %ID
  unsigned timeout_ms = 1000;

  bool is_read() const { return direction == SdoDirection::Read; }
  // "SDO variable 0x2020:1 (setpoint)"
  std::string label() const;
};

// What the plugin itself configures in an object of the node (SYNC,
// guarding, EMCY, heartbeat, PDO and NMT start-up objects), or nullptr. A
// startup SDO or SDO variable that writes one of them overrides the plugin.
const char* plugin_owned_object(uint16_t index);

struct NodeConfig {
  unsigned node_id = 0;
  std::string name;
  std::string eds;  // as written in the JSON
  // Resolved EDS path: an absolute `eds` as is; a relative one against the
  // config file's directory, then the runtime's core/generated/conf/ (where
  // the stock runtime extracts an upload). The first that exists, else the
  // first candidate.
  std::string eds_path;
  std::vector<std::string> eds_candidates;
  // dcf.lint's messages for the node's EDS (run_eds_lint), already judged and
  // logged, so dcfgen's own copies in its log are not logged again.
  std::vector<std::string> lint_findings;
  // Error control: heartbeat (heartbeat_ms > 0) or node guarding
  // (guard_time_ms > 0 and life_time_factor > 0). Without has_heartbeat and
  // guarding the slave keeps its EDS default heartbeat (object 0x1017).
  bool has_heartbeat = false;
  unsigned heartbeat_ms = 0;
  unsigned heartbeat_timeout_ms = 0;  // defaults to 3 x heartbeat_ms (0 = 3 x the EDS default)
  unsigned guard_time_ms = 0;
  unsigned life_time_factor = 0;
  bool has_status_location = false;
  IecLocation status_location;
  // Optional %IB byte with the node's NMT state (CiA 301 codes, 0 = no contact).
  bool has_state_location = false;
  IecLocation state_location;
  // Optional %IB byte with the CiA 302 error status letter (ASCII) of the
  // node's last failed boot, 0 while it is operational.
  bool has_boot_error_location = false;
  IecLocation boot_error_location;
  // Optional inputs with the node's latest EMCY: error code (%IW) and error
  // register (%IB); 0 after an error reset or a boot-up message.
  bool has_emcy_code_location = false;
  IecLocation emcy_code_location;
  bool has_error_register_location = false;
  IecLocation error_register_location;
  // Optional %QB byte through which the program sends NMT commands to the
  // node (CiA 301 codes: 0/1 run, 2 keep STOPPED, 128 keep PRE-OPERATIONAL,
  // a change to 129/130 resets the node/its communication once).
  bool has_nmt_command_location = false;
  IecLocation nmt_command_location;
  // dcfgen node options (docs/config.md). Master-only settings (0x1F81 bits)
  // keep today's values when left out; node-side ones (0x1011, 0x1012,
  // 0x1016, 0x1029) write nothing when left out, so the node keeps its EDS
  // values.
  // Set by check_eds_files from the EDS: PDO communication sub-indices
  // (0x1400-0x15FF, 0x1800-0x19FF) that are not writable, which the master
  // never writes; and the PDOs the JSON does not use whose COB-ID is not
  // writable, which stay as the node has them instead of being switched off.
  std::set<std::pair<uint16_t, uint8_t>> ro_pdo_comm;
  std::set<unsigned> kept_tpdos, kept_rpdos;
  bool mandatory = false;
  bool boot = true;
  bool has_reset_communication = false;
  bool reset_communication = true;
  bool has_revision_number = false;
  uint32_t revision_number = 0;  // expected 0x1018 sub 3; 0 = not checked
  bool has_serial_number = false;
  uint32_t serial_number = 0;  // expected 0x1018 sub 4
  bool has_heartbeat_consumer = false;
  bool heartbeat_consumer = false;  // the node watches the master's heartbeat
  bool has_retry_factor = false;
  unsigned retry_factor = 0;
  bool has_time_cob_id = false;
  uint32_t time_cob_id = 0;
  std::vector<std::pair<unsigned, unsigned>> error_behavior;  // 0x1029 sub -> value
  bool has_restore_configuration = false;
  unsigned restore_configuration = 0;  // 0x1011 sub-index
  // Skip the configuration download when the node's 0x1020 holds this
  // configuration's stamp (canopen-master-bringup spec).
  bool config_check = false;
  bool has_store_configuration = false;
  unsigned store_configuration = 0;  // 0x1010 sub-index saved after a download
  // LSS (CiA 305): the master gives the device with this node's identity
  // its node ID at start and before boot retries; store keeps it in the
  // device, only after an actual change (canopen-master-bringup spec).
  bool lss_assign = false;
  bool lss_store = false;
  // From the EDS [DeviceInfo], set by check_eds_files: the LSS address's
  // vendor ID and product code, and the revision tried first when
  // revision_number is not set.
  uint32_t eds_vendor_id = 0;
  uint32_t eds_product_code = 0;
  uint32_t eds_revision_number = 0;
  std::string software_file;           // as written in the JSON
  std::string software_path;           // resolved like `eds`
  bool has_software_version = false;
  uint32_t software_version = 0;
  std::vector<PdoConfig> tx_pdos;  // slave -> master, land in %I*
  std::vector<PdoConfig> rx_pdos;  // master -> slave, fed from %Q*
  std::vector<StartupSdo> sdos;    // startup SDOs, in list order
  std::vector<SdoVariable> sdo_variables;
  // A simulated device runs this node (docs/simulator.md); defaults to
  // adapter.simulate.
  bool simulate = false;

  // COB-ID a PDO uses on the bus (explicit or the CiA 301 default).
  uint32_t tpdo_cob_id(const PdoConfig& pdo) const;
  uint32_t rpdo_cob_id(const PdoConfig& pdo) const;
  std::string label() const;  // "node 2 (pingpong)"
};

struct MasterConfig {
  unsigned node_id = 1;
  unsigned sync_period_us = 0;  // 0 (or left out): the master produces no SYNC
  unsigned heartbeat_ms = 0;  // master heartbeat producer (0 = off)
  // Which dcfgen EDS lint findings stop the load (eds_lint.h):
  // "communication", "all" or "off"; strict_eds true/false reads as all/off.
  std::string eds_lint = "communication";
  // Optional bus diagnostics (see bus_monitor.h): %IB bus state code, %IB
  // transmit and receive error counters, %IW bus-off count.
  bool has_bus_state_location = false;
  IecLocation bus_state_location;
  bool has_tx_error_count_location = false;
  IecLocation tx_error_count_location;
  bool has_rx_error_count_location = false;
  IecLocation rx_error_count_location;
  bool has_bus_off_count_location = false;
  IecLocation bus_off_count_location;
  // Optional %IB byte with the master's own NMT state (same codes as a
  // node's state byte).
  bool has_state_location = false;
  IecLocation state_location;
  // dcfgen master options (docs/config.md); each has_* means set in the JSON.
  bool has_vendor_id = false, has_product_code = false, has_revision_number = false, has_serial_number = false;
  uint32_t vendor_id = 0, product_code = 0, revision_number = 0, serial_number = 0;
  bool has_sync_window = false;
  unsigned sync_window_us = 0;
  bool has_sync_counter_overflow = false;
  unsigned sync_counter_overflow = 0;
  bool has_time_cob_id = false;
  uint32_t time_cob_id = 0;
  bool has_emcy_inhibit_time = false;
  unsigned emcy_inhibit_time_us = 0;  // a multiple of 100
  bool heartbeat_consumer = true;
  bool has_heartbeat_multiplier = false;
  double heartbeat_multiplier = 3.0;
  std::vector<std::pair<unsigned, unsigned>> error_behavior;  // 0x1029 sub -> value
  bool has_nmt_inhibit_time = false;
  unsigned nmt_inhibit_time_us = 0;  // a multiple of 100
  bool start = true;
  bool start_nodes = true;
  bool start_all_nodes = false;
  bool reset_all_nodes = false;
  bool stop_all_nodes = false;
  bool has_boot_time = false;
  unsigned boot_time_ms = 0;
  // Timeout of every SDO the master sends to boot and configure a node.
  unsigned sdo_timeout_ms = 1000;
  // TIME producer period (canopen-master-bringup "TIME producer"); 0 = the
  // master sends no TIME.
  unsigned time_period_ms = 0;
  // The COB-ID the master produces TIME on: time_cob_id, else 0x100.
  uint32_t time_producer_cob_id() const { return (has_time_cob_id ? time_cob_id : 0x100u) & 0x1FFFFFFFu; }
  // Diagnostics channel (canopen-online-diagnostics spec); off without
  // `diagnostics`.
  bool has_diagnostics = false;
  std::string diag_token_sha256;  // lower-case hex
  unsigned diag_port = 7531;
  std::string diag_bind = "0.0.0.0";
  bool diag_allow_changes = false;
};

// The CAN adapter: "socketcan" (an existing interface) or "slcan" (the plugin
// creates the interface from a serial-line adapter such as a CANable).
struct AdapterConfig {
  std::string type = "socketcan";
  std::string interface;       // e.g. "can0"
  unsigned bitrate = 0;        // bit/s
  bool configure_link = true;  // set the bit rate and bring the link up
  unsigned restart_ms = 0;     // bus-off auto-restart delay (0 = not set)
  bool has_restart_ms = false;
  // type "slcan": the serial device the plugin creates `interface` from.
  std::string device;
  unsigned serial_baudrate = 0;  // 0 = leave the UART speed as it is
  // The network is simulated: the master runs on an in-process virtual bus
  // and nothing above is opened (docs/simulator.md). The fields are still
  // checked, so switching back needs only this one.
  bool simulate = false;
};

// Highest config schema_version this plugin reads.
constexpr unsigned kSchemaVersion = 1;

struct Config {
  std::string path;        // the JSON file
  std::string config_dir;  // its directory
  std::string file_sha256;  // SHA-256 of the file's bytes (lower-case hex)
  unsigned schema_version = 1;
  AdapterConfig adapter;
  MasterConfig master;
  std::vector<NodeConfig> nodes;
  // Non-fatal findings (deprecated keys, unknown fields), each naming the
  // file and the JSON path. The plugin logs them as warnings.
  std::vector<std::string> warnings;
  // Facts worth logging at start (automatic COB-IDs), logged as info.
  std::vector<std::string> notes;
};

// Whether anything is simulated: a simulated network or a simulated node.
bool simulates_anything(const Config& cfg);

// Limits of the runtime's I/O image, from plugin_runtime_args_t.
struct ImageLimits {
  unsigned buffer_size = 1024;
};

// Where the stock runtime extracts an upload's conf/ tree:
// $CANOPEN_GENERATED_CONF if set, else <working directory>/core/generated/conf
// (the runtime runs from its checkout).
// Transmission types that only act on SYNC (CiA 301): 0-240 synchronous,
// 252 synchronous RTR.
inline bool transmission_needs_sync(unsigned t) { return t <= 240 || t == 252; }
// "transmission type 1 (from the EDS) needs SYNC, but ..." for a PDO error.
std::string sync_needed_message(unsigned transmission, bool from_eds);

std::string default_eds_fallback_dir();

// Parses and validates `path`. On failure returns false and fills `errors`
// with one message per problem, each naming the file and the offending field,
// node, object or location. Does not touch the EDS files (see eds_check.h).
bool load_config(const std::string& path, const ImageLimits& limits,
                 Config& out, std::vector<std::string>& errors,
                 const std::string& eds_fallback_dir = default_eds_fallback_dir());

// Same, from a JSON string (for tests). `path` is only used in messages and to
// resolve relative EDS paths.
bool parse_config(const std::string& json, const std::string& path,
                  const ImageLimits& limits, Config& out,
                  std::vector<std::string>& errors,
                  const std::string& eds_fallback_dir = default_eds_fallback_dir());

}  // namespace canopen_plugin

#endif  // CANOPEN_CONFIG_H
