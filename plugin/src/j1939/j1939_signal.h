// j1939_signal.h - J1939 signals in a message's bytes (design Decision 4): raw
// integers of 1 to 64 bits, little (J1939) or big (DBC Motorola) byte order.
// Values reach the PLC raw; scale and offset are for the tools only. The bit
// work is protocol-neutral (can/signals.h); this binds it to J1939Signal.

#ifndef CANWORKS_J1939_SIGNAL_H
#define CANWORKS_J1939_SIGNAL_H

#include <cstddef>
#include <cstdint>
#include <vector>

#include "j1939_config.h"
#include "signals.h"

namespace canopen_plugin {

// The signal's raw bits (zero-extended). False when the message is too short
// to hold it.
bool j1939_extract(const uint8_t* data, size_t len, const J1939Signal& s, uint64_t& raw);
// Same with the signal's bit positions computed once (j1939_signal_bits).
inline bool j1939_extract(const uint8_t* data, size_t len, const std::vector<unsigned>& bits, uint64_t& raw) {
  return signal_extract(data, len, bits, raw);
}
// Writes the low `s.length` bits of `raw` into `data` (`len` bytes long);
// bits outside the signal stay as they are.
void j1939_insert(uint8_t* data, size_t len, const J1939Signal& s, uint64_t raw);
inline void j1939_insert(uint8_t* data, size_t len, const std::vector<unsigned>& bits, uint64_t raw) {
  signal_insert(data, len, bits, raw);
}
// The value as the PLC location receives it: sign-extended to 64 bits for a
// signed signal, else as is.
inline uint64_t j1939_to_plc(const J1939Signal& s, uint64_t raw) {
  return s.is_signed ? signal_sign_extend(raw, s.length) : raw;
}
// J1939-71: for signals of 2 bits or more, all ones is "not available" and
// all ones minus one is "error".
inline bool j1939_not_valid(const J1939Signal& s, uint64_t raw) { return signal_not_available_or_error(raw, s.length); }
// An output location's value as the signal's raw bits (truncated to its length).
inline uint64_t j1939_from_plc(const J1939Signal& s, uint64_t value) { return signal_truncate(value, s.length); }

}  // namespace canopen_plugin

#endif  // CANWORKS_J1939_SIGNAL_H
