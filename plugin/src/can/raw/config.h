// config.h - the `raw` object of a network (spec can-raw-messages): received
// and sent raw messages with their PLC locations, parsed and checked.

#ifndef CANWORKS_RAW_CONFIG_H
#define CANWORKS_RAW_CONFIG_H

#include <cstdint>
#include <functional>
#include <string>
#include <utility>
#include <vector>

#include "iec_location.h"

struct cJSON;

namespace canworks_raw {

using canopen_plugin::IecLocation;

// An optional PLC location.
struct Loc {
  bool set = false;
  IecLocation loc;
};

struct RawSignal {
  std::string name;
  unsigned start_bit = 0;
  unsigned length = 1;
  bool big_endian = false;
  bool is_signed = false;
  IecLocation loc;
};

struct RawRx {
  std::string path;  // "networks[0].raw.rx[1]" for messages
  std::string name;
  uint32_t id = 0;
  uint32_t mask = 0;  // all identifier bits when not given
  bool extended = false;
  bool rtr = false;
  int dlc = -1;  // -1: any
  unsigned need = 0;  // bytes a frame must have (dlc, or what the signals need)
  uint32_t timeout_ms = 0;
  Loc status, counter, id_loc, dlc_loc, data;
  std::vector<RawSignal> signals;
  std::string label() const;
};

struct RawTx {
  std::string path;
  std::string name;
  uint32_t id = 0;
  bool extended = false;
  bool rtr = false;
  unsigned dlc = 0;
  uint8_t fill = 0;
  uint32_t period_ms = 0;
  bool on_change = false;
  uint32_t min_gap_ms = 0;
  bool override_protocol = false;
  Loc trigger, enable, data;
  std::vector<RawSignal> signals;
  std::string label() const;
};

struct RawConfig {
  bool present = false;
  std::string dbc;
  bool program_override_protocol = false;
  std::vector<RawRx> rx;
  std::vector<RawTx> tx;
  bool empty() const { return rx.empty() && tx.empty(); }
};

// Parses `raw` (an object, or null for none) at `path` ("networks[0].raw").
// Errors and warnings are "<path>: <message>". `listen_only` rejects tx
// entries.
bool parse_raw(const cJSON* raw, const std::string& path, bool listen_only, RawConfig& out,
               std::vector<std::string>& errors, std::vector<std::string>& warnings);

// What the network's protocol uses an identifier for ("RPDO1 of node 5"), or
// "" when it is free.
using ProtocolUse = std::function<std::string(uint32_t id, bool extended)>;

// Rejects tx entries on identifiers the protocol uses unless they override
// it; `overrides` gets one start log line per overriding entry.
void check_protocol_ids(const RawConfig& cfg, const ProtocolUse& use, std::vector<std::string>& errors,
                        std::vector<std::string>& overrides);

// Every PLC location of the raw messages with its config path, for the clash
// check.
void raw_locations(const RawConfig& cfg, std::vector<std::pair<IecLocation, std::string>>& out);

}  // namespace canworks_raw

#endif  // CANWORKS_RAW_CONFIG_H
