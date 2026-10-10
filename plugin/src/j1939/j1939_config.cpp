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

// Builds the message's multiplexing; signals inside the message and not
// overlapping another signal that can be in the same frame.
void check_signals(const std::vector<J1939Signal>& signals, unsigned length, const std::string& where,
                   canworks_can::MuxLayout& layout, const ErrorFn& error) {
  std::vector<canworks_can::MuxSignalDef> defs;
  for (const J1939Signal& s : signals) {
    canworks_can::MuxSignalDef d;
    d.name = s.name;
    d.path = "signals[" + std::to_string(s.index) + "]";
    d.start_bit = s.start_bit;
    d.length = s.length;
    d.big_endian = s.big_endian;
    d.is_signed = s.is_signed;
    d.mux = s.mux;
    defs.push_back(d);
  }
  std::vector<std::string> errors, warnings;
  layout.build(defs, errors, warnings);
  for (const auto& e : errors) error(where, e);
  // Per bit, the signals on it so far; a signal overlaps the latest earlier
  // one on the bit that can be in the same frame (another page's may not).
  std::vector<std::vector<int>> owners(length * 8);
  std::vector<std::pair<int, int>> reported;
  for (size_t i = 0; i < signals.size(); ++i) {
    const J1939Signal& s = signals[i];
    bool fits = true;
    for (unsigned b : j1939_signal_bits(s)) {
      if (b >= length * 8) {
        fits = false;
        continue;
      }
      auto& on = owners[b];
      for (auto it = on.rbegin(); it != on.rend(); ++it) {
        if (!layout.can_share(static_cast<size_t>(*it), i)) continue;
        if (std::find(reported.begin(), reported.end(), std::make_pair(*it, int(i))) == reported.end()) {
          reported.emplace_back(*it, int(i));
          error(where, "signals " + signals[static_cast<size_t>(*it)].name + " and " + s.name + " overlap");
        }
        break;
      }
      on.push_back(int(i));
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
    check_signals(r.signals, kJ1939MaxLength, w, cfg.rx[i].layout, error);
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
    check_signals(t.signals, t.length, w, t.layout, error);
    bool has_switch = false;
    for (const J1939Signal& s : t.signals) has_switch = has_switch || s.mux.is_switch;
    if (t.has_pages && !has_switch) error(w, "pages: only for a message with a switch (multiplexer: true)");
    if (t.pages != canworks_can::MuxPages::Program && t.layout.multiplexed()) {
      uint64_t n = t.layout.page_count();
      if (n > canworks_can::kMuxMaxPages)
        error(w, std::to_string(n) + " pages; pages \"all\" and \"rotate\" send at most " +
                     std::to_string(canworks_can::kMuxMaxPages) + " (use pages \"program\")");
    }
    for (size_t j = 0; j < i; ++j)
      if (cfg.tx[j].pgn == t.pgn)
        error("j1939", "tx[" + std::to_string(j) + "] and tx[" + std::to_string(i) + "] both send PGN " +
                           j1939_pgn_text(t.pgn));
  }
  const J1939Diagnostics& d = cfg.diagnostics;
  for (size_t i = 0; i < d.rx.size(); ++i)
    for (size_t j = 0; j < i; ++j)
      if (d.rx[i].has_source == d.rx[j].has_source && d.rx[i].has_source_name == d.rx[j].has_source_name &&
          (d.rx[i].has_source ? d.rx[i].source == d.rx[j].source
                              : d.rx[i].source_name == d.rx[j].source_name &&
                                    d.rx[i].source_name_mask == d.rx[j].source_name_mask))
        error("j1939: diagnostics",
              "rx[" + std::to_string(j) + "] and rx[" + std::to_string(i) + "] have the same source filter");
  for (size_t i = 0; i < d.dtcs.size(); ++i)
    for (size_t j = 0; j < i; ++j)
      if (d.dtcs[i].spn == d.dtcs[j].spn && d.dtcs[i].fmi == d.dtcs[j].fmi)
        error("j1939: diagnostics", "dtcs[" + std::to_string(j) + "] and dtcs[" + std::to_string(i) +
                                        "] both report SPN " + std::to_string(d.dtcs[i].spn) + " FMI " +
                                        std::to_string(d.dtcs[i].fmi));
}

}  // namespace canopen_plugin
