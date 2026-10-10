// dm.cpp - see dm.h.

#include "dm.h"

#include <algorithm>

#include "log.h"

namespace canopen_plugin {

uint32_t dtc_value(const J1939Dtc& d) {
  return (d.spn & kJ1939MaxSpn) | uint32_t(d.fmi & 0x1F) << 19 | uint32_t(d.oc & 0x7F) << 24 |
         (d.cm ? 0x80000000u : 0u);
}

J1939Dtc dtc_from_value(uint32_t v) {
  J1939Dtc d;
  d.spn = v & kJ1939MaxSpn;
  d.fmi = static_cast<uint8_t>((v >> 19) & 0x1F);
  d.oc = static_cast<uint8_t>((v >> 24) & 0x7F);
  d.cm = (v & 0x80000000u) != 0;
  return d;
}

J1939Dtc dtc_from_bytes(const uint8_t* b) {
  J1939Dtc d;
  d.spn = b[0] | uint32_t(b[1]) << 8 | uint32_t(b[2] & 0xE0) << 11;
  d.fmi = b[2] & 0x1F;
  d.oc = b[3] & 0x7F;
  d.cm = (b[3] & 0x80) != 0;
  return d;
}

void dtc_to_bytes(const J1939Dtc& d, uint8_t* b) {
  b[0] = static_cast<uint8_t>(d.spn);
  b[1] = static_cast<uint8_t>(d.spn >> 8);
  b[2] = static_cast<uint8_t>(((d.spn >> 11) & 0xE0) | (d.fmi & 0x1F));
  b[3] = static_cast<uint8_t>((d.cm ? 0x80 : 0) | (d.oc & 0x7F));
}

bool dm_parse(const uint8_t* data, size_t len, DmList& out, size_t keep) {
  out = DmList();
  if (len < 6) return false;
  out.lamps = data[0];
  out.flash = data[1];
  for (size_t k = 2; k + 4 <= len; k += 4) {
    const uint8_t* b = data + k;
    // The all-zero "no code", and the 0xFF filler of a short message.
    if ((b[0] | b[1] | b[2] | b[3]) == 0) continue;
    if ((b[0] & b[1] & b[2] & b[3]) == 0xFF) continue;
    if (out.dtcs.size() < keep) out.dtcs.push_back(dtc_from_bytes(b));
    ++out.count;
  }
  return true;
}

std::vector<uint8_t> dm_build(uint8_t lamps, uint8_t flash, const std::vector<J1939Dtc>& dtcs) {
  std::vector<uint8_t> out = {lamps, flash};
  if (dtcs.empty()) {
    out.insert(out.end(), {0, 0, 0, 0, 0xFF, 0xFF});
    return out;
  }
  for (const auto& d : dtcs) {
    uint8_t b[4];
    dtc_to_bytes(d, b);
    out.insert(out.end(), b, b + 4);
  }
  if (out.size() < 8) out.resize(8, 0xFF);
  return out;
}

Dm13 dm13_decode(const uint8_t* data, size_t len) {
  Dm13 m;
  if (len < 1) return m;
  switch ((data[0] >> 6) & 3) {
    case 0: m.command = Dm13Command::Stop; break;
    case 1: m.command = Dm13Command::Start; break;
    default: break;
  }
  m.hold = len >= 4 && ((data[3] >> 4) & 0xF) != 0xF;
  return m;
}

std::vector<uint8_t> dm22_nack(const uint8_t* data, size_t len) {
  if (len < 8 || (data[0] != 0x01 && data[0] != 0x11)) return {};
  return {static_cast<uint8_t>(data[0] + 2), 0, 0xFF, 0xFF, 0xFF, data[5], data[6], data[7]};
}

uint8_t dm_flash_byte(const std::vector<std::pair<uint8_t, int>>& codes) {
  uint8_t out = 0xFF;
  for (const auto& c : codes) {
    if (c.second < 0) continue;
    for (unsigned shift = 0; shift < 8; shift += 2) {
      if (!((c.first >> shift) & 1)) continue;
      unsigned cur = (out >> shift) & 3;
      unsigned now = c.second == 1 ? 1 : 0;
      if (cur == 3 || (cur == 0 && now == 1))
        out = static_cast<uint8_t>((out & ~(3u << shift)) | (now << shift));
    }
  }
  return out;
}

// ---------------------------------------------------------------------------
// DmStore

const DmStore::Source* DmStore::on_dm1(uint8_t source, const uint8_t* data, size_t len, clock::time_point now) {
  DmList l;
  if (!dm_parse(data, len, l, kDmStoredCodes)) return nullptr;
  Source& s = sources_[source];
  s.lamps = l.lamps;
  s.flash = l.flash;
  s.count = l.count;
  s.dtcs = std::move(l.dtcs);
  s.last = now;
  ++s.dm1_count;
  // Codes beyond the stored ones are not looked at for CM.
  size_t old = static_cast<size_t>(std::count_if(s.dtcs.begin(), s.dtcs.end(), [](const J1939Dtc& d) { return d.cm; }));
  s.old_format += old;
  if (old && !s.logged) {
    s.logged = true;
    log_warn("J1939: ECU at address %u sends trouble codes in the older SPN format (CM 1); they reach the PLC "
             "unchanged, with bit 31 set",
             source);
  }
  return &s;
}

const DmStore::Source* DmStore::find(uint8_t source) const {
  auto it = sources_.find(source);
  return it == sources_.end() ? nullptr : &it->second;
}

// ---------------------------------------------------------------------------
// OwnDtcs

OwnDtcs::OwnDtcs(const J1939Diagnostics& d) : d_(d) {
  active_.assign(d.dtcs.size(), 0);
  oc_.assign(d.dtcs.size(), 0);
}

void OwnDtcs::recompute() {
  uint8_t lamps = lamps_output_;
  std::vector<std::pair<uint8_t, int>> fl;
  for (size_t k = 0; k < d_.dtcs.size(); ++k) {
    if (!active_[k]) continue;
    lamps |= d_.dtcs[k].lamps;
    fl.emplace_back(d_.dtcs[k].lamps, d_.dtcs[k].flash);
  }
  lamps_ = lamps;
  flash_ = dm_flash_byte(fl);
}

bool OwnDtcs::update(const std::vector<uint8_t>& active, uint8_t lamps_output) {
  bool changed = lamps_output != lamps_output_;
  lamps_output_ = lamps_output;
  for (size_t k = 0; k < active_.size() && k < active.size(); ++k) {
    uint8_t a = active[k] ? 1 : 0;
    if (a == active_[k]) continue;
    changed = true;
    active_[k] = a;
    if (a) {
      if (oc_[k] < kOwnMaxOc) ++oc_[k];
    } else if (std::find(prev_.begin(), prev_.end(), k) == prev_.end()) {
      prev_.push_back(k);
    }
  }
  uint8_t lamps = lamps_, flash = flash_;
  recompute();
  return changed || lamps != lamps_ || flash != flash_;
}

bool OwnDtcs::clear(bool all) {
  prev_.clear();
  if (!all) return false;
  bool changed = false;
  for (size_t k = 0; k < oc_.size(); ++k) {
    uint8_t want = active_[k] ? 1 : 0;
    if (active_[k] && oc_[k] != want) changed = true;
    oc_[k] = want;
  }
  return changed;
}

std::vector<J1939Dtc> OwnDtcs::active() const {
  std::vector<J1939Dtc> out;
  for (size_t k = 0; k < active_.size(); ++k)
    if (active_[k]) out.push_back(J1939Dtc{d_.dtcs[k].spn, d_.dtcs[k].fmi, oc_[k], false});
  return out;
}

std::vector<J1939Dtc> OwnDtcs::previous() const {
  std::vector<J1939Dtc> out;
  for (size_t k : prev_) out.push_back(J1939Dtc{d_.dtcs[k].spn, d_.dtcs[k].fmi, oc_[k], false});
  return out;
}

// ---------------------------------------------------------------------------
// Dm13State

void Dm13State::on_dm13(const Dm13& m, clock::time_point now) {
  if (m.command == Dm13Command::Start) {
    suspended_ = false;
  } else if (m.command == Dm13Command::Stop) {
    suspended_ = true;
    last_ = now;
  } else if (m.hold && suspended_) {
    last_ = now;
  }
}

bool Dm13State::suspended(clock::time_point now) {
  if (suspended_ && now - last_ >= kDm13Resume) suspended_ = false;
  return suspended_;
}

}  // namespace canopen_plugin
