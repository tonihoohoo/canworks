// j1939_signal.h - J1939 signals in a message's bytes (design Decision 4): raw
// integers of 1 to 64 bits, little (J1939) or big (DBC Motorola) byte order.
// Values reach the PLC raw; scale and offset are for the tools only.

#ifndef CANWORKS_J1939_SIGNAL_H
#define CANWORKS_J1939_SIGNAL_H

#include <cstddef>
#include <cstdint>
#include <vector>

#include "j1939_config.h"

namespace canopen_plugin {

// The signal's raw bits (zero-extended). False when the message is too short
// to hold it.
bool j1939_extract(const uint8_t* data, size_t len, const J1939Signal& s, uint64_t& raw);
// Same with the signal's bit positions computed once (j1939_signal_bits).
bool j1939_extract(const uint8_t* data, size_t len, const std::vector<unsigned>& bits, uint64_t& raw);

// Writes the low `s.length` bits of `raw` into `data` (`len` bytes long);
// bits outside the signal stay as they are.
void j1939_insert(uint8_t* data, size_t len, const J1939Signal& s, uint64_t raw);
void j1939_insert(uint8_t* data, size_t len, const std::vector<unsigned>& bits, uint64_t raw);

// The value as the PLC location receives it: sign-extended to 64 bits for a
// signed signal, else as is.
uint64_t j1939_to_plc(const J1939Signal& s, uint64_t raw);

// J1939-71: for signals of 2 bits or more, all ones is "not available" and
// all ones minus one is "error".
bool j1939_not_valid(const J1939Signal& s, uint64_t raw);

// An output location's value as the signal's raw bits (truncated to its length).
inline uint64_t j1939_from_plc(const J1939Signal& s, uint64_t value) {
  return s.length >= 64 ? value : value & ((uint64_t(1) << s.length) - 1);
}

}  // namespace canopen_plugin

#endif  // CANWORKS_J1939_SIGNAL_H
