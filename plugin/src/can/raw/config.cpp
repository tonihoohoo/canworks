// config.cpp - see config.h.

#include "config.h"

#include <cstdio>
#include <set>

#include "../signals.h"
#include "cJSON.h"

namespace canworks_raw {

using canopen_plugin::IecArea;
using canopen_plugin::IecSize;
using canopen_plugin::parse_iec_location;

namespace {

constexpr uint32_t kStdMax = 0x7FFu;
constexpr uint32_t kExtMax = 0x1FFFFFFFu;

std::string hex_id(uint32_t id) {
  char buf[16];
  std::snprintf(buf, sizeof buf, "0x%X", id);
  return buf;
}

std::string at(const std::string& path, const char* key) { return path + "." + key; }

// Reads the object's members, warning about unknown ones.
struct Obj {
  const cJSON* o;
  std::string path;
  std::vector<std::string>& errors;
  std::vector<std::string>& warnings;
  std::set<std::string> known;

  const cJSON* get(const char* key) {
    known.insert(key);
    return cJSON_GetObjectItemCaseSensitive(o, key);
  }
  void finish() {
    for (const cJSON* it = o->child; it; it = it->next)
      if (it->string && !known.count(it->string))
        warnings.push_back(at(path, it->string) + ": unknown field '" + it->string + "' is ignored");
  }
  bool uint(const char* key, uint64_t lo, uint64_t hi, uint64_t& out, bool required = false) {
    const cJSON* v = get(key);
    if (!v) {
      if (required) errors.push_back(at(path, key) + ": missing");
      return false;
    }
    double d = v->valuedouble;
    if (!cJSON_IsNumber(v) || d < static_cast<double>(lo) || d > static_cast<double>(hi) ||
        d != static_cast<double>(static_cast<uint64_t>(d))) {
      errors.push_back(at(path, key) + ": must be a whole number " + std::to_string(lo) + ".." + std::to_string(hi));
      return false;
    }
    out = static_cast<uint64_t>(d);
    return true;
  }
  bool flag(const char* key, bool& out) {
    const cJSON* v = get(key);
    if (!v) return false;
    if (!cJSON_IsBool(v)) {
      errors.push_back(at(path, key) + ": must be true or false");
      return false;
    }
    out = cJSON_IsTrue(v);
    return true;
  }
  bool text(const char* key, std::string& out) {
    const cJSON* v = get(key);
    if (!v) return false;
    if (!cJSON_IsString(v)) {
      errors.push_back(at(path, key) + ": must be a string");
      return false;
    }
    out = v->valuestring;
    return true;
  }
  // A location of `area` and `size` (size X/B/W/D/L, or 0 for any).
  bool location(const char* key, IecArea area, IecSize size, const char* what, Loc& out) {
    std::string t;
    if (!text(key, t)) return false;
    std::string err;
    IecLocation loc;
    if (!parse_iec_location(t, loc, err)) {
      errors.push_back(at(path, key) + ": " + err);
      return false;
    }
    if (loc.area != area) {
      errors.push_back(at(path, key) + ": " + what + " must be " + (area == IecArea::Input ? "an input (%I)" : "an output (%Q)"));
      return false;
    }
    if (loc.size != size) {
      errors.push_back(at(path, key) + ": " + what + " must be a %" + static_cast<char>(area) + static_cast<char>(size) +
                       " location");
      return false;
    }
    out.set = true;
    out.loc = loc;
    return true;
  }
};

IecSize size_for_bits(unsigned bits) {
  if (bits == 1) return IecSize::X;
  if (bits <= 8) return IecSize::B;
  if (bits <= 16) return IecSize::W;
  if (bits <= 32) return IecSize::D;
  return IecSize::L;
}

const char* size_word(IecSize s) {
  switch (s) {
    case IecSize::X: return "a bit (%IX/%QX)";
    case IecSize::B: return "a byte";
    case IecSize::W: return "a word";
    case IecSize::D: return "a double word";
    default: return "a long word";
  }
}

// `switch_mode`: the pages mode of a send entry whose switches the plugin
// sets ("all" or "rotate"), else nullptr.
bool parse_signals(const cJSON* list, const std::string& path, IecArea area, unsigned frame_bytes, bool dlc_given,
                   const char* switch_mode, std::vector<RawSignal>& out, canworks_can::MuxLayout& layout,
                   std::vector<std::string>& errors, std::vector<std::string>& warnings) {
  if (!list) return true;
  if (!cJSON_IsArray(list)) {
    errors.push_back(path + ": must be a list");
    return false;
  }
  bool ok = true;
  int k = 0;
  std::vector<uint64_t> masks;  // frame bits of each signal (0: not checked)
  for (const cJSON* s = list->child; s; s = s->next, ++k) {
    std::string p = path + "[" + std::to_string(k) + "]";
    if (!cJSON_IsObject(s)) {
      errors.push_back(p + ": must be an object");
      ok = false;
      continue;
    }
    Obj o{s, p, errors, warnings, {}};
    size_t before = errors.size();
    RawSignal sig;
    o.text("name", sig.name);
    uint64_t v = 0;
    if (o.uint("start_bit", 0, 63, v, true)) sig.start_bit = static_cast<unsigned>(v);
    if (o.uint("length", 1, 64, v, true)) sig.length = static_cast<unsigned>(v);
    std::string order = "little";
    if (o.text("byte_order", order) && order != "little" && order != "big")
      errors.push_back(at(p, "byte_order") + ": must be \"little\" or \"big\"");
    sig.big_endian = order == "big";
    o.flag("signed", sig.is_signed);
    o.get("multiplexer");
    o.get("mux");
    canworks_can::parse_mux_fields(s, p, sig.mux, errors);
    // Tool-only fields.
    for (const char* key : {"scale", "offset", "unit", "minimum", "maximum", "comment"}) o.get(key);
    std::string label = sig.name.empty() ? p : sig.name;
    std::string t;
    if (sig.mux.is_switch && switch_mode) {
      sig.has_loc = false;
      // An empty mode: `pages` itself was wrong (reported there).
      if (o.get("iec_location") && *switch_mode)
        errors.push_back(at(p, "iec_location") + ": the plugin sets switch " + label + " when pages is \"" +
                         switch_mode + "\"; leave it out");
    } else if (o.text("iec_location", t)) {
      std::string err;
      if (!parse_iec_location(t, sig.loc, err)) {
        errors.push_back(at(p, "iec_location") + ": " + err);
      } else if (sig.loc.area != area) {
        errors.push_back(at(p, "iec_location") + ": a " + (area == IecArea::Input ? "received" : "sent") +
                         " signal needs " + (area == IecArea::Input ? "an input (%I)" : "an output (%Q)"));
      } else if (sig.loc.size != size_for_bits(sig.length)) {
        errors.push_back(at(p, "iec_location") + ": signal " + label + " of " + std::to_string(sig.length) +
                         " bits needs " + size_word(size_for_bits(sig.length)));
      }
    } else {
      errors.push_back(at(p, "iec_location") + ": missing");
    }
    if (area == IecArea::Input) {
      o.location("valid_location", IecArea::Input, IecSize::X, "valid bit", sig.valid);
    } else if (o.get("valid_location")) {
      errors.push_back(at(p, "valid_location") + ": only received signals have a valid bit");
    }
    o.finish();
    uint64_t mine = 0;
    if (errors.size() == before) {
      if (!canworks_can::signal_fits(sig.start_bit, sig.length, sig.big_endian, frame_bytes)) {
        errors.push_back(p + ": signal " + label + " reaches past " +
                         (dlc_given ? "the message's dlc (" + std::to_string(frame_bytes) + " bytes)" : std::string("8 bytes")));
      } else {
        int pos = static_cast<int>(sig.start_bit);
        for (unsigned i = 0; i < sig.length; ++i) {
          mine |= uint64_t{1} << pos;
          pos = sig.big_endian ? (pos % 8 == 0 ? pos + 15 : pos - 1) : pos + 1;
        }
      }
    }
    if (errors.size() != before) ok = false;
    out.push_back(sig);
    masks.push_back(mine);
  }
  std::vector<canworks_can::MuxSignalDef> defs;
  for (size_t i = 0; i < out.size(); ++i) {
    canworks_can::MuxSignalDef d;
    d.name = out[i].name;
    d.path = path + "[" + std::to_string(i) + "]";
    d.start_bit = out[i].start_bit;
    d.length = out[i].length;
    d.big_endian = out[i].big_endian;
    d.is_signed = out[i].is_signed;
    d.mux = out[i].mux;
    defs.push_back(d);
  }
  if (!layout.build(defs, errors, warnings)) ok = false;
  // Overlaps with an earlier signal that can be in the same frame.
  for (size_t i = 0; i < out.size() && i < masks.size(); ++i)
    for (size_t j = 0; j < i; ++j)
      if ((masks[i] & masks[j]) && layout.can_share(i, j)) {
        warnings.push_back(defs[i].path + ": signal " + (out[i].name.empty() ? defs[i].path : out[i].name) +
                           " overlaps another signal");
        break;
      }
  return ok;
}

bool parse_id(Obj& o, uint32_t& id, bool& extended) {
  o.flag("extended", extended);
  uint64_t v = 0;
  uint32_t max = extended ? kExtMax : kStdMax;
  const cJSON* j = o.get("id");
  if (!j) {
    o.errors.push_back(at(o.path, "id") + ": missing");
    return false;
  }
  if (!cJSON_IsNumber(j) || j->valuedouble < 0 || j->valuedouble > max ||
      j->valuedouble != static_cast<double>(static_cast<uint64_t>(j->valuedouble))) {
    o.errors.push_back(at(o.path, "id") + ": must be 0.." + hex_id(max) +
                       (extended ? " (29-bit identifier)" : " (11-bit identifier; set extended for 29 bits)"));
    return false;
  }
  v = static_cast<uint64_t>(j->valuedouble);
  id = static_cast<uint32_t>(v);
  return true;
}

}  // namespace

std::string RawRx::label() const { return name.empty() ? hex_id(id) : name; }
std::string RawTx::label() const { return name.empty() ? hex_id(id) : name; }

bool parse_raw(const cJSON* raw, const std::string& path, bool listen_only, RawConfig& out,
               std::vector<std::string>& errors, std::vector<std::string>& warnings) {
  out = RawConfig{};
  if (!raw || cJSON_IsNull(raw)) return true;
  if (!cJSON_IsObject(raw)) {
    errors.push_back(path + ": must be an object");
    return false;
  }
  size_t before = errors.size();
  out.present = true;
  Obj top{raw, path, errors, warnings, {}};
  top.text("dbc", out.dbc);
  top.flag("program_override_protocol", out.program_override_protocol);

  const cJSON* rx = top.get("rx");
  if (rx && !cJSON_IsArray(rx)) errors.push_back(at(path, "rx") + ": must be a list");
  int k = 0;
  for (const cJSON* e = rx && cJSON_IsArray(rx) ? rx->child : nullptr; e; e = e->next, ++k) {
    std::string p = at(path, "rx") + "[" + std::to_string(k) + "]";
    if (!cJSON_IsObject(e)) {
      errors.push_back(p + ": must be an object");
      continue;
    }
    Obj o{e, p, errors, warnings, {}};
    RawRx m;
    m.path = p;
    o.text("name", m.name);
    parse_id(o, m.id, m.extended);
    uint32_t max = m.extended ? kExtMax : kStdMax;
    uint64_t v = 0;
    m.mask = max;
    if (o.uint("mask", 0, max, v)) m.mask = static_cast<uint32_t>(v);
    o.flag("rtr", m.rtr);
    if (o.uint("dlc", 0, 8, v)) m.dlc = static_cast<int>(v);
    if (o.uint("timeout_ms", 0, 600000, v)) m.timeout_ms = static_cast<uint32_t>(v);
    o.location("status_location", IecArea::Input, IecSize::X, "status_location", m.status);
    o.location("counter_location", IecArea::Input, IecSize::W, "counter_location", m.counter);
    o.location("id_location", IecArea::Input, IecSize::D, "id_location", m.id_loc);
    o.location("dlc_location", IecArea::Input, IecSize::B, "dlc_location", m.dlc_loc);
    o.location("data_location", IecArea::Input, IecSize::L, "data_location", m.data);
    unsigned bytes = m.dlc >= 0 ? static_cast<unsigned>(m.dlc) : 8;
    parse_signals(o.get("signals"), at(p, "signals"), IecArea::Input, bytes, m.dlc >= 0, nullptr, m.signals, m.layout,
                  errors, warnings);
    if (m.rtr && !m.signals.empty()) errors.push_back(at(p, "signals") + ": a remote frame carries no data");
    // The bytes every frame needs; a multiplexed frame's own page may need
    // more (checked per frame).
    m.need = m.dlc >= 0 ? static_cast<unsigned>(m.dlc) : 0;
    for (size_t i = 0; i < m.signals.size(); ++i) {
      const RawSignal& s = m.signals[i];
      if (m.layout.multiplexed() && !m.layout.always(i)) continue;
      unsigned last = canworks_can::signal_last_byte(s.start_bit, s.length, s.big_endian) + 1;
      if (last > m.need) m.need = last;
    }
    o.finish();
    out.rx.push_back(m);
  }

  const cJSON* tx = top.get("tx");
  if (tx && !cJSON_IsArray(tx)) errors.push_back(at(path, "tx") + ": must be a list");
  if (listen_only && tx && cJSON_GetArraySize(tx) > 0)
    errors.push_back(at(path, "tx") + ": a listen-only network cannot send");
  k = 0;
  for (const cJSON* e = tx && cJSON_IsArray(tx) ? tx->child : nullptr; e; e = e->next, ++k) {
    std::string p = at(path, "tx") + "[" + std::to_string(k) + "]";
    if (!cJSON_IsObject(e)) {
      errors.push_back(p + ": must be an object");
      continue;
    }
    Obj o{e, p, errors, warnings, {}};
    RawTx m;
    m.path = p;
    o.text("name", m.name);
    parse_id(o, m.id, m.extended);
    o.flag("rtr", m.rtr);
    uint64_t v = 0;
    bool dlc_given = o.uint("dlc", 0, 8, v);
    if (dlc_given) m.dlc = static_cast<unsigned>(v);
    if (o.uint("fill", 0, 255, v)) m.fill = static_cast<uint8_t>(v);
    if (o.uint("period_ms", 1, 60000, v)) m.period_ms = static_cast<uint32_t>(v);
    o.flag("on_change", m.on_change);
    if (o.uint("min_gap_ms", 0, 60000, v)) m.min_gap_ms = static_cast<uint32_t>(v);
    o.flag("override_protocol", m.override_protocol);
    o.location("trigger_location", IecArea::Output, IecSize::X, "trigger_location", m.trigger);
    o.location("enable_location", IecArea::Output, IecSize::X, "enable_location", m.enable);
    o.location("data_location", IecArea::Output, IecSize::L, "data_location", m.data);
    std::string pages;
    bool pages_set = o.text("pages", pages);
    bool pages_bad = pages_set && !canworks_can::parse_mux_pages(pages, m.pages);
    if (pages_bad) errors.push_back(at(p, "pages") + ": must be \"program\", \"all\" or \"rotate\"");
    const char* mode = pages_bad ? ""
                       : m.pages == canworks_can::MuxPages::Program ? nullptr
                                                                     : canworks_can::mux_pages_name(m.pages);
    parse_signals(o.get("signals"), at(p, "signals"), IecArea::Output, dlc_given ? m.dlc : 8, dlc_given, mode,
                  m.signals, m.layout, errors, warnings);
    bool has_switch = false;
    for (const RawSignal& s : m.signals) has_switch = has_switch || s.mux.is_switch;
    if (pages_set && !has_switch)
      errors.push_back(at(p, "pages") + ": only for a message with a switch (multiplexer: true)");
    if (mode && *mode && m.layout.multiplexed()) {
      uint64_t n = m.layout.page_count();
      if (n > canworks_can::kMuxMaxPages)
        errors.push_back(p + ": " + std::to_string(n) + " pages; pages \"all\" and \"rotate\" send at most " +
                         std::to_string(canworks_can::kMuxMaxPages) + " (use pages \"program\")");
    }
    if (m.rtr && (!m.signals.empty() || m.data.set))
      errors.push_back(p + ": a remote frame carries no data (no signals or data_location)");
    if (!dlc_given && !m.rtr) {
      // The smallest DLC that holds every signal, at least 1; 8 with data_location.
      unsigned need = m.data.set ? 8 : 1;
      for (const RawSignal& s : m.signals) {
        unsigned last = canworks_can::signal_last_byte(s.start_bit, s.length, s.big_endian) + 1;
        if (last > need) need = last;
      }
      m.dlc = need;
    }
    if (!m.period_ms && !m.on_change && !m.trigger.set)
      errors.push_back(p + ": needs period_ms, on_change or trigger_location to be sent");
    o.finish();
    out.tx.push_back(m);
  }
  top.finish();

  // Sent identifiers are unique.
  for (size_t i = 0; i < out.tx.size(); ++i)
    for (size_t j = 0; j < i; ++j)
      if (out.tx[i].id == out.tx[j].id && out.tx[i].extended == out.tx[j].extended)
        errors.push_back(out.tx[i].path + ": identifier " + hex_id(out.tx[i].id) + " is also sent by " + out.tx[j].path);
  return errors.size() == before;
}

void check_protocol_ids(const RawConfig& cfg, const ProtocolUse& use, std::vector<std::string>& errors,
                        std::vector<std::string>& overrides) {
  if (!use) return;
  for (const RawTx& m : cfg.tx) {
    std::string what = use(m.id, m.extended);
    if (what.empty()) continue;
    if (m.override_protocol) {
      overrides.push_back("raw message " + m.label() + " (" + hex_id(m.id) + ") overrides " + what);
    } else {
      errors.push_back(m.path + ": " + hex_id(m.id) + " is " + what + "; set override_protocol to send it as a raw message");
    }
  }
}

void raw_locations(const RawConfig& cfg, std::vector<std::pair<IecLocation, std::string>>& out) {
  auto add = [&](const Loc& l, const std::string& p) {
    if (l.set) out.emplace_back(l.loc, p);
  };
  for (const RawRx& m : cfg.rx) {
    add(m.status, m.path + ".status_location");
    add(m.counter, m.path + ".counter_location");
    add(m.id_loc, m.path + ".id_location");
    add(m.dlc_loc, m.path + ".dlc_location");
    add(m.data, m.path + ".data_location");
    for (size_t k = 0; k < m.signals.size(); ++k) {
      out.emplace_back(m.signals[k].loc, m.path + ".signals[" + std::to_string(k) + "].iec_location");
      add(m.signals[k].valid, m.path + ".signals[" + std::to_string(k) + "].valid_location");
    }
  }
  for (const RawTx& m : cfg.tx) {
    add(m.trigger, m.path + ".trigger_location");
    add(m.enable, m.path + ".enable_location");
    add(m.data, m.path + ".data_location");
    for (size_t k = 0; k < m.signals.size(); ++k)
      if (m.signals[k].has_loc)
        out.emplace_back(m.signals[k].loc, m.path + ".signals[" + std::to_string(k) + "].iec_location");
  }
}

}  // namespace canworks_raw
