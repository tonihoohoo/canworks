#include "signals.h"

#include <algorithm>

namespace canopen_plugin {

std::vector<unsigned> signal_bits(unsigned start_bit, unsigned length, bool big_endian) {
  std::vector<unsigned> bits;
  bits.reserve(length);
  if (!big_endian) {
    for (unsigned k = 0; k < length; ++k) bits.push_back(start_bit + k);
    return bits;
  }
  // DBC big byte order: the start bit is the most significant bit; the next
  // lower bit is the next lower bit of the same byte, or bit 7 of the next byte.
  long pos = start_bit;
  for (unsigned k = 0; k < length; ++k) {
    bits.push_back(static_cast<unsigned>(pos));
    pos = (pos % 8 == 0) ? pos + 15 : pos - 1;
  }
  std::reverse(bits.begin(), bits.end());
  return bits;
}

bool signal_extract(const uint8_t* data, size_t len, const std::vector<unsigned>& bits, uint64_t& raw) {
  raw = 0;
  for (size_t k = 0; k < bits.size(); ++k) {
    unsigned b = bits[k];
    if (b / 8 >= len) return false;
    if (data[b / 8] >> (b % 8) & 1) raw |= uint64_t(1) << k;
  }
  return true;
}

void signal_insert(uint8_t* data, size_t len, const std::vector<unsigned>& bits, uint64_t raw) {
  for (size_t k = 0; k < bits.size(); ++k) {
    unsigned b = bits[k];
    if (b / 8 >= len) continue;
    uint8_t mask = uint8_t(1u << (b % 8));
    if (raw >> k & 1)
      data[b / 8] |= mask;
    else
      data[b / 8] &= uint8_t(~mask);
  }
}

uint64_t signal_sign_extend(uint64_t raw, unsigned length) {
  if (length >= 64 || length == 0 || !(raw >> (length - 1) & 1)) return raw;
  return raw | ~((uint64_t(1) << length) - 1);
}

bool signal_not_available_or_error(uint64_t raw, unsigned length) {
  if (length < 2) return false;
  uint64_t ones = signal_truncate(~uint64_t(0), length);
  return raw == ones || raw == ones - 1;
}

}  // namespace canopen_plugin
