// signals.h - integer signals in a CAN message's bytes, whatever the
// protocol: bit positions in DBC convention (little or big byte order),
// extract, insert, sign extension and the J1939-71 not-available and error
// values. Used by J1939 (j1939/j1939_signal.h) and raw CAN messages.

#ifndef CANWORKS_SIGNALS_H
#define CANWORKS_SIGNALS_H

#include <cstddef>
#include <cstdint>
#include <vector>

namespace canopen_plugin {

// The bit positions (0 = bit 0 of byte 0) of a signal, in order from its
// least significant bit. `start_bit` as in a DBC file: the least significant
// bit for little byte order, the most significant one for big.
std::vector<unsigned> signal_bits(unsigned start_bit, unsigned length, bool big_endian);

// The signal's raw bits (zero-extended). False when the message is too short.
bool signal_extract(const uint8_t* data, size_t len, const std::vector<unsigned>& bits, uint64_t& raw);
// Writes the low bits.size() bits of `raw`; other bits stay as they are, so
// the caller first fills the message with its unused-bit value.
void signal_insert(uint8_t* data, size_t len, const std::vector<unsigned>& bits, uint64_t raw);
// Two's complement sign extension of a `length`-bit value to 64 bits.
uint64_t signal_sign_extend(uint64_t raw, unsigned length);
// The low `length` bits of `value`.
inline uint64_t signal_truncate(uint64_t value, unsigned length) {
  return length >= 64 ? value : value & ((uint64_t(1) << length) - 1);
}
// All ones (not available) or all ones minus one (error), for 2 bits or more.
bool signal_not_available_or_error(uint64_t raw, unsigned length);

}  // namespace canopen_plugin

#endif  // CANWORKS_SIGNALS_H
