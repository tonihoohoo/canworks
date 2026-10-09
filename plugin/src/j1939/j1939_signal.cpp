#include "j1939_signal.h"

namespace canopen_plugin {

bool j1939_extract(const uint8_t* data, size_t len, const J1939Signal& s, uint64_t& raw) {
  return signal_extract(data, len, j1939_signal_bits(s), raw);
}

void j1939_insert(uint8_t* data, size_t len, const J1939Signal& s, uint64_t raw) {
  signal_insert(data, len, j1939_signal_bits(s), raw);
}

}  // namespace canopen_plugin
