// j1939_config.h - the `j1939` object of a J1939 network (j1939-config spec): the
// ECU identity, the PGNs received into %I, the PGNs sent from %Q and the
// periodic requests. Data only; the shared parser (can/config.cpp) reads the
// JSON and check_j1939() checks what only the whole object can tell.

#ifndef CANWORKS_J1939_CONFIG_H
#define CANWORKS_J1939_CONFIG_H

#include <cstdint>
#include <functional>
#include <string>
#include <vector>

#include "iec_location.h"
#include "mux.h"

namespace canopen_plugin {

constexpr uint32_t kJ1939MaxPgn = 0x3FFFF;
constexpr unsigned kJ1939MaxAddress = 253;  // 254 null, 255 global
constexpr uint8_t kJ1939NullAddress = 254;
constexpr uint8_t kJ1939Global = 255;
constexpr unsigned kJ1939MaxLength = 1785;  // bytes, the transport protocol's limit
constexpr unsigned kJ1939MaxPeriodMs = 600000;
constexpr unsigned kJ1939MinRequestPeriodMs = 100;

// The 64-bit NAME, field by field (J1939-81).
struct J1939Name {
  uint32_t identity_number = 0;   // 21 bits
  uint16_t manufacturer_code = 0;  // 11 bits
  uint8_t ecu_instance = 0;        // 3 bits
  uint8_t function_instance = 0;   // 5 bits
  uint8_t function = 0;
  uint8_t vehicle_system = 0;  // 7 bits
  uint8_t vehicle_system_instance = 0;  // 4 bits
  uint8_t industry_group = 0;  // 3 bits
  bool arbitrary_address_capable = false;

  uint64_t value() const;
};

struct J1939Ecu {
  J1939Name name;
  unsigned address = 0;
  bool has_range = false;
  unsigned range_low = 0, range_high = 0;
  bool has_state_location = false;
  IecLocation state_location;  // %IB: 0 claiming, 1 claimed, 2 cannot claim, 3 no bus
  bool has_address_location = false;
  IecLocation address_location;  // %IB: the current address, 254 while none
};

enum class J1939ClaimState : uint8_t { Claiming = 0, Claimed = 1, CannotClaim = 2, NoBus = 3 };

struct J1939Signal {
  std::string name;
  unsigned start_bit = 0;  // as in a DBC file; big byte order: the most significant bit
  unsigned length = 1;     // 1..64 bits
  bool big_endian = false;
  bool is_signed = false;
  double scale = 1, offset = 0;  // for the tools only
  std::string unit;
  IecLocation location;
  bool has_location = true;  // false: a switch the plugin sets (pages "all"/"rotate")
  bool has_valid_location = false;
  IecLocation valid_location;  // %IX, received signals only
  canworks_can::MuxSpec mux;   // multiplexing fields as written
  unsigned index = 0;          // position in the config's signals list
};

struct J1939Rx {
  uint32_t pgn = 0;
  std::string name;
  bool has_source = false;
  unsigned source = 0;
  bool has_source_name = false;
  uint64_t source_name = 0;
  uint64_t source_name_mask = ~uint64_t(0);
  unsigned timeout_ms = 0;  // 0: no supervision
  bool has_status_location = false;
  IecLocation status_location;  // %IX
  std::vector<J1939Signal> signals;
  canworks_can::MuxLayout layout;  // built by check_j1939
};

struct J1939Tx {
  uint32_t pgn = 0;
  std::string name;
  unsigned priority = 6;
  bool has_destination = false;
  unsigned destination = kJ1939Global;
  bool has_length = false;
  unsigned length = 8;  // bytes; without has_length: at least 8, enough for every signal
  unsigned period_ms = 0;  // 0: on change and on request
  unsigned min_gap_ms = 0;
  std::vector<J1939Signal> signals;
  canworks_can::MuxPages pages = canworks_can::MuxPages::Program;
  bool has_pages = false;
  canworks_can::MuxLayout layout;  // built by check_j1939
};

struct J1939Request {
  uint32_t pgn = 0;
  unsigned destination = kJ1939Global;
  unsigned period_ms = 1000;
};

struct J1939Config {
  J1939Ecu ecu;
  std::string dbc;  // for the tools; the plugin does not read it
  std::vector<J1939Rx> rx;
  std::vector<J1939Tx> tx;
  std::vector<J1939Request> requests;
};

// PDU1 (PDU format below 240): addressed, the low byte is the destination.
inline bool j1939_pdu1(uint32_t pgn) { return ((pgn >> 8) & 0xFF) < 240; }
// "65280 (0xFF00)"
std::string j1939_pgn_text(uint32_t pgn);

// The bit positions (0 = bit 0 of byte 0) a signal occupies, in order from
// its least significant bit. Big byte order follows the DBC convention.
std::vector<unsigned> j1939_signal_bits(const J1939Signal& s);

// Bytes the signals need: the highest bit used, rounded up (0 without signals).
unsigned j1939_bytes_needed(const std::vector<J1939Signal>& signals);

// Checks that need the whole object (duplicates, overlaps, message lengths)
// and fills in the default TX lengths. `error(where, message)` gets each
// problem, `where` relative to the network ("j1939: rx[0]").
void check_j1939(J1939Config& cfg, const std::function<void(const std::string&, const std::string&)>& error);

}  // namespace canopen_plugin

#endif  // CANWORKS_J1939_CONFIG_H
