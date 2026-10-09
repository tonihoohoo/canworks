#include "j1939_config.h"

#include <algorithm>
#include <cstdio>

#include "signals.h"

namespace canopen_plugin {

uint64_t J1939Name::value() const {
  return uint64_t(identity_number & 0x1FFFFF) | uint64_t(manufacturer_code & 0x7FF) << 21 |
         uint64_t(ecu_instance & 0x7) << 32 | uint64_t(function_instance & 0x1F) << 35 | uint64_t(function) << 40 |
         uint64_t(vehicle_system & 0x7F) << 49 | uint64_t(vehicle_system_instance & 0xF) << 56 |
         uint64_t(industry_group & 0x7) << 60 | uint64_t(arbitrary_address_capable ? 1 : 0) << 63;
}

std::string j1939_pgn_text(uint32_t pgn) {
  char buf[32];
  std::snprintf(buf, sizeof(buf), "%u (0x%X)", pgn, pgn);
  return buf;
}

std::vector<unsigned> j1939_signal_bits(const J1939Signal& s) {
  return signal_bits(s.start_bit, s.length, s.big_endian);
}

unsigned j1939_bytes_needed(const std::vector<J1939Signal>& signals) {
  unsigned top = 0;
  for (const auto& s : signals)
    for (unsigned b : j1939_signal_bits(s)) top = std::max(top, b / 8 + 1);
  return top;
}

namespace {

using ErrorFn = std::function<void(const std::string&, const std::string&)>;

// Signals inside the message and not overlapping each other.
void check_signals(const std::vector<J1939Signal>& signals, unsigned length, const std::string& where,
                   const ErrorFn& error) {
  std::vector<int> owner(length * 8, -1);
  std::vector<std::pair<int, int>> reported;
  for (size_t i = 0; i < signals.size(); ++i) {
    const J1939Signal& s = signals[i];
    bool fits = true;
    for (unsigned b : j1939_signal_bits(s)) {
      if (b >= length * 8) {
        fits = false;
        continue;
      }
      int o = owner[b];
      if (o >= 0 && std::find(reported.begin(), reported.end(), std::make_pair(o, int(i))) == reported.end()) {
        reported.emplace_back(o, int(i));
        error(where, "signals " + signals[o].name + " and " + s.name + " overlap");
      }
      owner[b] = int(i);
    }
    if (!fits)
      error(where, "signal " + s.name + " (start bit " + std::to_string(s.start_bit) + ", " +
                       std::to_string(s.length) + " bits) does not fit in " + std::to_string(length) + " bytes");
  }
}

bool same_filter(const J1939Rx& a, const J1939Rx& b) {
  if (a.has_source != b.has_source || a.has_source_name != b.has_source_name) return false;
  if (a.has_source) return a.source == b.source;
  if (a.has_source_name) return a.source_name == b.source_name && a.source_name_mask == b.source_name_mask;
  return true;
}

}  // namespace

void check_j1939(J1939Config& cfg, const ErrorFn& error) {
  for (size_t i = 0; i < cfg.rx.size(); ++i) {
    const J1939Rx& r = cfg.rx[i];
    std::string w = "j1939: rx[" + std::to_string(i) + "]";
    // A received message is as long as its sender makes it; the signals
    // only have to fit what the transport protocol can carry.
    check_signals(r.signals, kJ1939MaxLength, w, error);
    for (size_t j = 0; j < i; ++j)
      if (cfg.rx[j].pgn == r.pgn && same_filter(cfg.rx[j], r))
        error("j1939", "rx[" + std::to_string(j) + "] and rx[" + std::to_string(i) + "] both receive PGN " +
                           j1939_pgn_text(r.pgn) + " with the same source filter");
  }
  for (size_t i = 0; i < cfg.tx.size(); ++i) {
    J1939Tx& t = cfg.tx[i];
    std::string w = "j1939: tx[" + std::to_string(i) + "]";
    if (!t.has_length) {
      t.length = std::max(8u, j1939_bytes_needed(t.signals));
      if (t.length > kJ1939MaxLength) {
        error(w, "the signals need " + std::to_string(t.length) + " bytes; a message carries at most " +
                     std::to_string(kJ1939MaxLength));
        t.length = kJ1939MaxLength;
      }
    }
    check_signals(t.signals, t.length, w, error);
    for (size_t j = 0; j < i; ++j)
      if (cfg.tx[j].pgn == t.pgn)
        error("j1939", "tx[" + std::to_string(j) + "] and tx[" + std::to_string(i) + "] both send PGN " +
                           j1939_pgn_text(t.pgn));
  }
}

}  // namespace canopen_plugin
