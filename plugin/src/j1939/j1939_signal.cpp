#include "j1939_signal.h"

namespace canopen_plugin {

bool j1939_extract(const uint8_t* data, size_t len, const J1939Signal& s, uint64_t& raw) {
  return j1939_extract(data, len, j1939_signal_bits(s), raw);
}

bool j1939_extract(const uint8_t* data, size_t len, const std::vector<unsigned>& bits, uint64_t& raw) {
  raw = 0;
  for (size_t k = 0; k < bits.size(); ++k) {
    unsigned b = bits[k];
    if (b / 8 >= len) return false;
    if (data[b / 8] >> (b % 8) & 1) raw |= uint64_t(1) << k;
  }
  return true;
}

void j1939_insert(uint8_t* data, size_t len, const J1939Signal& s, uint64_t raw) {
  j1939_insert(data, len, j1939_signal_bits(s), raw);
}

void j1939_insert(uint8_t* data, size_t len, const std::vector<unsigned>& bits, uint64_t raw) {
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

uint64_t j1939_to_plc(const J1939Signal& s, uint64_t raw) {
  if (!s.is_signed || s.length >= 64 || !(raw >> (s.length - 1) & 1)) return raw;
  return raw | ~((uint64_t(1) << s.length) - 1);
}

bool j1939_not_valid(const J1939Signal& s, uint64_t raw) {
  if (s.length < 2) return false;
  uint64_t ones = s.length >= 64 ? ~uint64_t(0) : (uint64_t(1) << s.length) - 1;
  return raw == ones || raw == ones - 1;
}

}  // namespace canopen_plugin
