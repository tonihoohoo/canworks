// sim_file.h - the simulation file (docs/simulator.md, "The simulation
// file"): loader, faults and scenario steps.
//
// The loader checks everything it can without the devices: the file's
// structure (unknown keys are errors), every value source, fault and
// scenario step. What needs the devices (objects that exist, expressions,
// node IDs that are simulated) is checked by the engine when it starts.

#ifndef CANOPEN_SIM_FILE_H
#define CANOPEN_SIM_FILE_H

#include <cstdint>
#include <map>
#include <memory>
#include <string>
#include <vector>

#include "sim_od.h"

typedef struct cJSON cJSON;

namespace canopen_sim {

constexpr unsigned kSimSchemaVersion = 2;
constexpr unsigned kDefaultTickMs = 10;

// An object key "0xIIII:S" parsed.
struct ObjKey {
  uint16_t index = 0;
  uint8_t subindex = 0;
  bool operator<(const ObjKey& o) const { return index != o.index ? index < o.index : subindex < o.subindex; }
  bool operator==(const ObjKey& o) const { return index == o.index && subindex == o.subindex; }
  std::string str() const;
};

struct Fault {
  // emcy, heartbeat, power, reset, nmt_state, sdo_abort, sdo_delay,
  // refuse_write_operational, tpdo_stop, identity, device_type,
  // forget_node_id, drive_input
  std::string kind;
  std::string json;  // as given, for status answers
  // emcy
  uint16_t code = 0;
  uint8_t error_register = 0;
  uint8_t msef[5] = {};
  unsigned period_ms = 0;
  // heartbeat ("stop"), power (off/on/cycle), reset (node/comm),
  // nmt_state (stopped/preop/operational)
  std::string mode;
  unsigned off_ms = 1000;
  // sdo_abort, sdo_delay
  bool has_object = false;
  ObjKey object;
  uint32_t abort_code = 0;
  bool on_read = true, on_write = true;
  int count = -1;
  unsigned ms = 0;
  // tpdo_stop
  unsigned tpdo = 0;
  // identity (0x1018 subindex -> value), device_type
  std::map<uint8_t, uint32_t> identity;
  uint32_t value = 0;
  // drive_input: name -> state
  std::map<std::string, bool> inputs;
};

// Parses one fault object.
bool parse_fault(const cJSON* json, Fault& out, std::string& err);
// The names `clear` takes.
bool is_clear_name(const std::string& name);

struct Condition {
  bool is_expr = false;
  std::string expr;
  std::string node;  // device reference ("5" or a name)
  ObjKey object;
  int bit = -1;
  std::string op;  // eq ne lt le gt ge
  Value value;
  std::string text() const;  // for messages
};

struct Step {
  std::string node;  // device reference, "" = none
  bool has_at = false, has_after = false;
  unsigned at_ms = 0, after_ms = 0;
  // set, override, release, source, fault, clear, wait, expect, log, repeat
  std::string action;
  std::vector<std::pair<ObjKey, Value>> values;  // set, override
  bool release_all = false;
  std::vector<ObjKey> release;
  std::vector<std::pair<ObjKey, std::string>> sources;  // JSON text, "" = remove
  Fault fault;
  std::string clear;
  Condition cond;
  unsigned timeout_ms = 0, within_ms = 0, for_ms = 0;
  std::string log;
  unsigned count = 1;  // repeat: 0 = forever
  std::vector<Step> steps;
};

struct Scenario {
  std::string name;
  bool autostart = false;
  bool test = false;
  std::string description;
  std::vector<Step> steps;
};

bool parse_scenario(const cJSON* json, const std::string& name, Scenario& out, std::string& err);

// Behaviour of one device.
struct NodeBehaviour {
  bool default_behaviour = true;
  unsigned tick_ms = 0;  // 0: the file's
  std::vector<std::pair<ObjKey, std::string>> sources;  // source JSON text
  bool has_drive = false;
  std::string drive_json;
  std::vector<Fault> faults;
  std::map<uint8_t, uint32_t> identity;
  bool has_device_type = false;
  uint32_t device_type = 0;
};

struct ExtraDevice {
  unsigned node = 0;  // 0: no node ID (LSS)
  std::string name;
  std::string eds;       // as written
  std::string eds_path;  // resolved against the file
  NodeBehaviour behaviour;
};

// One network's part of a version 2 file (`networks.NAME`).
struct SimSection {
  std::string network;
  std::map<unsigned, NodeBehaviour> nodes;
  std::vector<ExtraDevice> extra;
  std::vector<Scenario> scenarios;
};

struct SimFile {
  std::string path;  // "" when there is no file
  std::string dir;   // where relative paths start
  unsigned schema_version = 1;
  unsigned tick_ms = kDefaultTickMs;
  // Version 1, or one network's section of version 2 (sim_file_section).
  std::map<unsigned, NodeBehaviour> nodes;
  std::vector<ExtraDevice> extra;
  std::vector<Scenario> scenarios;
  // Version 2 only: the sections, in file order.
  std::vector<SimSection> networks;
  // Set by sim_file_section: the network whose section this is.
  std::string section;
};

// What a version 2 file says for network `network`, shaped as a version 1
// file (path, dir and tick_ms kept). False, with `out` holding the file's
// path and tick only, when the file has no section for that network.
bool sim_file_section(const SimFile& file, const std::string& network, SimFile& out);

// Loads `path`; errors name the file and the JSON path.
bool load_sim_file(const std::string& path, SimFile& out, std::vector<std::string>& errors);
bool parse_sim_file(const std::string& json, const std::string& path, SimFile& out, std::vector<std::string>& errors);

// Helpers shared with the engine's control ops.
bool parse_obj_key(const std::string& text, ObjKey& out);
bool parse_u32(const cJSON* v, uint32_t& out);  // number or "0x..." / decimal string
bool parse_value(const cJSON* v, Value& out);   // number, string or boolean
// A device reference: integer 1-127 or a name.
bool parse_device_ref(const cJSON* v, std::string& out);
std::string sim_json_text(const cJSON* v);  // compact JSON

}  // namespace canopen_sim

#endif  // CANOPEN_SIM_FILE_H
