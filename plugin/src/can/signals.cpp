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

namespace canworks_can {

namespace {
int next_pos(int pos, bool big_endian) {
  if (!big_endian) return pos + 1;
  return pos % 8 == 0 ? pos + 15 : pos - 1;
}
}  // namespace

bool signal_fits(unsigned start_bit, unsigned length, bool big_endian, unsigned bytes) {
  if (length == 0 || length > 64) return false;
  int pos = static_cast<int>(start_bit);
  for (unsigned i = 0; i < length; ++i) {
    if (pos < 0 || pos >= static_cast<int>(8 * bytes)) return false;
    pos = next_pos(pos, big_endian);
  }
  return true;
}

unsigned signal_last_byte(unsigned start_bit, unsigned length, bool big_endian) {
  int pos = static_cast<int>(start_bit);
  unsigned last = 0;
  for (unsigned i = 0; i < length; ++i) {
    if (pos >= 0 && static_cast<unsigned>(pos / 8) > last) last = static_cast<unsigned>(pos / 8);
    pos = next_pos(pos, big_endian);
  }
  return last;
}

uint64_t unpack_signal(const uint8_t* data, unsigned bytes, unsigned start_bit, unsigned length, bool big_endian) {
  uint64_t v = 0;
  int pos = static_cast<int>(start_bit);
  for (unsigned i = 0; i < length && i < 64; ++i) {
    uint64_t bit = 0;
    if (pos >= 0 && pos < static_cast<int>(8 * bytes)) bit = (data[pos / 8] >> (pos % 8)) & 1u;
    if (big_endian)
      v = (v << 1) | bit;
    else
      v |= bit << i;
    pos = next_pos(pos, big_endian);
  }
  return v;
}

int64_t sign_extend(uint64_t value, unsigned length) {
  if (length == 0 || length >= 64) return static_cast<int64_t>(value);
  uint64_t sign = uint64_t{1} << (length - 1);
  value &= (uint64_t{1} << length) - 1;
  return static_cast<int64_t>((value ^ sign) - sign);
}

void pack_signal(uint8_t* data, unsigned start_bit, unsigned length, bool big_endian, uint64_t value) {
  int pos = static_cast<int>(start_bit);
  for (unsigned i = 0; i < length && i < 64; ++i) {
    unsigned shift = big_endian ? length - 1 - i : i;
    if (pos >= 0 && pos < 64) {
      uint8_t mask = static_cast<uint8_t>(1u << (pos % 8));
      if ((value >> shift) & 1u)
        data[pos / 8] |= mask;
      else
        data[pos / 8] &= static_cast<uint8_t>(~mask);
    }
    pos = next_pos(pos, big_endian);
  }
}

}  // namespace canworks_can
