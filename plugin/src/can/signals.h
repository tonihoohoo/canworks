// signals.h - integer signals in a CAN message's bytes, whatever the
// protocol: bit positions in DBC convention (little or big byte order),
// extract, insert, sign extension and the J1939-71 not-available and error
// values. Used by J1939 (j1939/j1939_signal.h) and raw CAN messages
// (raw/engine.cpp).

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

// Allocation-free forms for the raw CAN hot paths (one frame at a time on
// the raw thread), with the same bit numbering; also the reference the PC
// tools and the library's CAN_GET_BITS/CAN_SET_BITS are tested against
// (test/fixtures/can_signals.json).
namespace canworks_can {

// True when all `length` bits of the signal lie in the first `bytes` bytes.
bool signal_fits(unsigned start_bit, unsigned length, bool big_endian, unsigned bytes);

// The highest byte index the signal touches.
unsigned signal_last_byte(unsigned start_bit, unsigned length, bool big_endian);

// The raw value (bits outside `bytes` read as 0).
uint64_t unpack_signal(const uint8_t* data, unsigned bytes, unsigned start_bit, unsigned length, bool big_endian);

// Two's complement sign extension of a `length`-bit value.
int64_t sign_extend(uint64_t value, unsigned length);

// Writes the low `length` bits of `value`; the signal must fit 8 bytes.
void pack_signal(uint8_t* data, unsigned start_bit, unsigned length, bool big_endian, uint64_t value);

}  // namespace canworks_can

#endif  // CANWORKS_SIGNALS_H
