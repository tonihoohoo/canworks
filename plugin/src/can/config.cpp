#include "config.h"

#include <arpa/inet.h>
#include <cctype>
#include <cerrno>
#include <cfloat>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <map>
#include <set>
#include <sstream>
#include <sys/stat.h>
#include <unistd.h>

#include "cJSON.h"
#include "frame_tx.h"
#include "sha256.h"

namespace canopen_plugin {

uint32_t NodeConfig::tpdo_cob_id(const PdoConfig& pdo) const {
  if (pdo.cob_id) return pdo.cob_id;
  return 0x80 + 0x100 * pdo.number + node_id;  // 0x180, 0x280, 0x380, 0x480
}

uint32_t NodeConfig::rpdo_cob_id(const PdoConfig& pdo) const {
  if (pdo.cob_id) return pdo.cob_id;
  return 0x100 + 0x100 * pdo.number + node_id;  // 0x200, 0x300, 0x400, 0x500
}

std::string SdoVariable::label() const {
  char buf[48];
  std::snprintf(buf, sizeof(buf), "SDO variable 0x%04X:%u", index, subindex);
  std::string s = buf;
  if (!name.empty()) s += " (" + name + ")";
  return s;
}

bool interpolation_code(unsigned period_us, uint8_t& value, int8_t& exponent) {
  static const struct { int8_t exponent; unsigned unit; } units[] = {{-3, 1000}, {-4, 100}, {-5, 10}, {-6, 1}};
  if (!period_us) return false;
  for (const auto& u : units) {
    if (period_us % u.unit == 0 && period_us / u.unit >= 1 && period_us / u.unit <= 255) {
      value = static_cast<uint8_t>(period_us / u.unit);
      exponent = u.exponent;
      return true;
    }
  }
  return false;
}

const char* plugin_owned_object(uint16_t index) {
  if (index >= 0x1400 && index <= 0x1BFF) return "the PDO settings";
  switch (index) {
    case 0x1005:
    case 0x1006:
    case 0x1007: return "the SYNC settings";
    case 0x100C:
    case 0x100D: return "node guarding";
    case 0x1014:
    case 0x1015: return "the EMCY settings";
    case 0x1016: return "the heartbeat consumer";
    case 0x1017: return "the node's heartbeat setting";
    case 0x1F80: return "the NMT start-up settings";
    default: return nullptr;
  }
}

std::string SlaveObject::label() const {
  char buf[32];
  std::snprintf(buf, sizeof(buf), "object 0x%04X:%u", index, subindex);
  std::string s = buf;
  if (!name.empty()) s += " (" + name + ")";
  return s;
}

std::string SlaveConfig::label() const { return lss ? "slave (LSS)" : "slave (node " + std::to_string(node_id) + ")"; }

std::string RouteConfig::label() const {
  return "route " + std::to_string(number) + (name.empty() ? "" : " (" + name + ")");
}

uint32_t NodeConfig::emcy_cob_id() const {
  if (emcy_cob == EmcyCob::Number || emcy_cob_from_sdo) return emcy_cob_config;
  if (eds_emcy_cob_id) return eds_emcy_cob_id;
  return 0x80 + node_id;
}

bool restricted_can_id(uint32_t id) {
  return id <= 0x07F || (id >= 0x101 && id <= 0x180) || (id >= 0x581 && id <= 0x5FF) ||
         (id >= 0x601 && id <= 0x67F) || (id >= 0x6E0 && id <= 0x6FF) || (id >= 0x701 && id <= 0x7FF);
}

std::string emcy_cob_clash(const Config& cfg, const NodeConfig& n, uint32_t id,
                           const std::function<uint32_t(const NodeConfig&)>& in_use) {
  if (id == 0x080) return "SYNC";
  if (id == (cfg.master.time_producer_cob_id() & 0x7FF)) return "TIME";
  if (id == 0x80 + cfg.master.node_id) return "the master's EMCY";
  for (const auto& m : cfg.nodes)
    if (&m != &n && (in_use ? in_use(m) : m.emcy_cob_id()) == id) return "the EMCY of " + m.label();
  for (const auto& m : cfg.nodes) {
    for (const auto& p : m.tx_pdos)
      if ((p.cob_id || p.number <= 4) && m.tpdo_cob_id(p) == id) return m.label() + " TPDO " + std::to_string(p.number);
    for (const auto& p : m.rx_pdos)
      if ((p.cob_id || p.number <= 4) && m.rpdo_cob_id(p) == id) return m.label() + " RPDO " + std::to_string(p.number);
  }
  return "";
}

std::string NodeConfig::label() const {
  std::string s = "node " + std::to_string(node_id);
  if (!name.empty()) s += " (" + name + ")";
  return s;
}

namespace {

bool is_file(const std::string& path) {
  struct stat st;
  return stat(path.c_str(), &st) == 0 && S_ISREG(st.st_mode);
}

// "nodes[0]: tx_pdos[1]" -> "nodes[0].tx_pdos[1]"
std::string json_path(const std::string& where, const std::string& key) {
  std::string p;
  for (size_t i = 0; i < where.size(); ++i) {
    if (where.compare(i, 2, ": ") == 0) {
      p += '.';
      ++i;
    } else {
      p += where[i];
    }
  }
  return p.empty() ? key : p + "." + key;
}

// Little-endian bytes of the low `bytes` bytes of v.
std::vector<uint8_t> le_bytes(uint64_t v, unsigned bytes) {
  std::vector<uint8_t> out(bytes);
  for (unsigned i = 0; i < bytes; ++i) out[i] = uint8_t(v >> (8 * i));
  return out;
}

const char* const kNotBridgeConfig =
    "not a bridge config: canworks-bridge serves a version 2 config with a top-level 'bridge' object";

class Parser {
 public:
  Parser(const std::string& path, const ImageLimits& limits, const std::string& eds_fallback_dir,
         std::vector<std::string>& errors, std::vector<std::string>& warnings)
      : path_(path), limits_(limits), eds_fallback_dir_(eds_fallback_dir), errors_(errors),
        warnings_(warnings) {}

  // `where` inside the network being parsed ("master", "nodes[0]"), with the
  // network's own place in a version 2 file in front ("networks[1]: master").
  std::string full(const std::string& where) const {
    if (prefix_.empty()) return where;
    return where.empty() ? prefix_ : prefix_ + ": " + where;
  }

  void error(const std::string& where, const std::string& msg) {
    std::string s = path_ + ": ";
    std::string w = full(where);
    if (!w.empty()) s += w + ": ";
    errors_.push_back(s + msg);
  }

  void warning(const std::string& where, const std::string& msg) {
    std::string s = path_ + ": ";
    std::string w = full(where);
    if (!w.empty()) s += w + ": ";
    warnings_.push_back(s + msg);
  }

  // Unknown fields are ignored with a warning, so a file written for a newer
  // release of the same schema_version still loads (docs/config.md).
  void check_known(const cJSON* obj, const std::string& where, std::initializer_list<const char*> known) {
    const cJSON* item;
    cJSON_ArrayForEach(item, obj) {
      bool ok = false;
      for (const char* k : known) ok |= std::strcmp(k, item->string) == 0;
      if (!ok)
        warning(where, std::string("unknown field '") + item->string + "' (" + json_path(full(where), item->string) +
                           ") ignored");
    }
  }

  bool get_bool(const cJSON* obj, const char* key, const std::string& where, bool& out) {
    const cJSON* item = cJSON_GetObjectItemCaseSensitive(obj, key);
    if (!item) return false;
    if (!cJSON_IsBool(item)) {
      error(where, std::string("field '") + key + "' must be true or false");
      return false;
    }
    out = cJSON_IsTrue(item);
    return true;
  }

  // Reads an unsigned integer given either as a JSON number or as a string
  // ("0x2001", "8193").
  bool get_uint(const cJSON* obj, const char* key, const std::string& where,
                bool required, uint64_t max, uint64_t& out) {
    const cJSON* item = cJSON_GetObjectItemCaseSensitive(obj, key);
    if (!item) {
      if (required) error(where, std::string("missing required field '") + key + "'");
      return false;
    }
    uint64_t v = 0;
    if (cJSON_IsNumber(item)) {
      if (item->valuedouble < 0 || item->valuedouble != (double)(uint64_t)item->valuedouble) {
        error(where, std::string("field '") + key + "' must be a non-negative integer");
        return false;
      }
      v = (uint64_t)item->valuedouble;
    } else if (cJSON_IsString(item) && item->valuestring[0]) {
      char* end = nullptr;
      v = std::strtoull(item->valuestring, &end, 0);
      if (*end != '\0' || item->valuestring[0] == '-') {
        error(where, std::string("field '") + key + "' is not a valid integer: \"" +
                         item->valuestring + "\"");
        return false;
      }
    } else {
      error(where, std::string("field '") + key + "' must be an integer");
      return false;
    }
    if (v > max) {
      error(where, std::string("field '") + key + "' is out of range (max " +
                       std::to_string(max) + "): " + std::to_string(v));
      return false;
    }
    out = v;
    return true;
  }

  // A number (integer or fraction) in [min, max].
  bool get_number(const cJSON* obj, const char* key, const std::string& where, double min, double max,
                  double& out) {
    const cJSON* item = cJSON_GetObjectItemCaseSensitive(obj, key);
    if (!item) return false;
    if (!cJSON_IsNumber(item) || !std::isfinite(item->valuedouble)) {
      error(where, std::string("field '") + key + "' must be a number");
      return false;
    }
    if (item->valuedouble < min || item->valuedouble > max) {
      std::ostringstream s;
      s << "field '" << key << "' must be between " << min << " and " << max << ": " << item->valuedouble;
      error(where, s.str());
      return false;
    }
    out = item->valuedouble;
    return true;
  }

  // A time in microseconds for an object counted in 100 us (UNSIGNED16).
  bool get_us100(const cJSON* obj, const char* key, const std::string& where, bool& has, unsigned& out) {
    uint64_t v;
    if (!get_uint(obj, key, where, false, 6553500, v)) return false;
    if (v % 100) {
      error(where, std::string("field '") + key + "' must be a multiple of 100: " + std::to_string(v));
      return false;
    }
    has = true;
    out = (unsigned)v;
    return true;
  }

  // 0x1029 error behaviour: {"1": 0, "2": 1, ...}, sub-index 1-254 -> 0-255.
  void get_error_behavior(const cJSON* obj, const std::string& where,
                          std::vector<std::pair<unsigned, unsigned>>& out) {
    const cJSON* eb = cJSON_GetObjectItemCaseSensitive(obj, "error_behavior");
    if (!eb) return;
    if (!cJSON_IsObject(eb)) {
      error(where, "field 'error_behavior' must be an object of sub-index to value, e.g. {\"1\": 1}");
      return;
    }
    std::string ew = where + ": error_behavior";
    const cJSON* item;
    cJSON_ArrayForEach(item, eb) {
      char* end = nullptr;
      unsigned long sub = std::strtoul(item->string, &end, 0);
      if (!item->string[0] || *end != '\0' || item->string[0] == '-' || sub < 1 || sub > 254) {
        error(ew, std::string("sub-index \"") + item->string + "\" must be 1-254");
        continue;
      }
      uint64_t v;
      if (!get_uint(eb, item->string, ew, true, 0xFF, v)) continue;
      out.emplace_back((unsigned)sub, (unsigned)v);
    }
  }

  bool get_string(const cJSON* obj, const char* key, const std::string& where,
                  bool required, std::string& out) {
    const cJSON* item = cJSON_GetObjectItemCaseSensitive(obj, key);
    if (!item) {
      if (required) error(where, std::string("missing required field '") + key + "'");
      return false;
    }
    if (!cJSON_IsString(item) || !item->valuestring[0]) {
      error(where, std::string("field '") + key + "' must be a non-empty string");
      return false;
    }
    out = item->valuestring;
    return true;
  }

  bool get_location(const cJSON* obj, const char* key, const std::string& where,
                    bool required, IecLocation& out) {
    std::string text;
    if (!get_string(obj, key, where, required, text)) return false;
    std::string why;
    if (!parse_iec_location(text, out, why)) {
      error(where, std::string("invalid ") + key + " \"" + text + "\": " + why);
      return false;
    }
    unsigned limit = limits_.buffer_size;
    if (!iec_location_in_image(out, limit, byte_mode_)) {
      error(where, std::string(key) + " " + out.str() +
                       " lies outside the runtime I/O image (index must be below " +
                       std::to_string(limit) + ")");
      return false;
    }
    return true;
  }

  // timeout_ms, on_timeout and timeout_location of one PDO (canopen-pdo-io
  // "Receive timeout setting", "Inputs while a PDO is timed out").
  void parse_timeout(const cJSON* p, const std::string& pw, const std::string& pdo_name, bool is_tx,
                     PdoConfig& pdo) {
    const cJSON* t = cJSON_GetObjectItemCaseSensitive(p, "timeout_ms");
    if (t) {
      uint64_t v;
      if (!is_tx) {
        error(pw, pdo_name + ": field 'timeout_ms' is only for tx_pdos (PDOs the node sends)");
      } else if (cJSON_IsString(t) && std::string(t->valuestring) == "auto") {
        pdo.has_timeout = true;
        pdo.timeout_auto = true;
      } else if (get_uint(p, "timeout_ms", pw, false, 0xFFFF, v)) {
        if (v == 0)
          error(pw, pdo_name + ": field 'timeout_ms' must be 1-65535 or \"auto\"; leave it out for no timeout");
        pdo.has_timeout = true;
        pdo.timeout_ms = (unsigned)v;
      }
    }
    std::string on;
    if (cJSON_GetObjectItemCaseSensitive(p, "on_timeout") && get_string(p, "on_timeout", pw, false, on)) {
      if (on == "zero")
        pdo.timeout_zero = true;
      else if (on != "hold")
        error(pw, pdo_name + ": field 'on_timeout' must be \"hold\" or \"zero\", not \"" + on + "\"");
      if (is_tx && !t) error(pw, pdo_name + ": field 'on_timeout' needs 'timeout_ms'");
    }
    if (cJSON_GetObjectItemCaseSensitive(p, "timeout_location")) {
      IecLocation loc;
      if (get_location(p, "timeout_location", pw, false, loc)) {
        if (loc.area != IecArea::Input || loc.size != IecSize::X) {
          error(pw, pdo_name + ": field 'timeout_location' must be an input bit (%IX...), not " + loc.str());
        } else {
          pdo.has_timeout_location = true;
          pdo.timeout_location = loc;
        }
      }
      if (is_tx && !t) error(pw, pdo_name + ": field 'timeout_location' needs 'timeout_ms'");
    }
    if (!is_tx) {
      if (cJSON_GetObjectItemCaseSensitive(p, "on_timeout"))
        error(pw, pdo_name + ": field 'on_timeout' is only for tx_pdos (PDOs the node sends)");
      if (cJSON_GetObjectItemCaseSensitive(p, "timeout_location"))
        error(pw, pdo_name + ": field 'timeout_location' is only for tx_pdos (PDOs the node sends)");
      pdo.has_timeout_location = false;
    }
  }

  void parse_pdos(const cJSON* node, const char* key, NodeConfig& n,
                  const std::string& where, bool is_tx) {
    const cJSON* arr = cJSON_GetObjectItemCaseSensitive(node, key);
    if (!arr) return;
    if (!cJSON_IsArray(arr)) {
      error(where, std::string("field '") + key + "' must be an array");
      return;
    }
    std::set<unsigned> numbers;
    int i = 0;
    const cJSON* p;
    cJSON_ArrayForEach(p, arr) {
      std::string pw = where + ": " + key + "[" + std::to_string(i) + "]";
      PdoConfig pdo;
      uint64_t v;
      if (!cJSON_IsObject(p)) {
        error(pw, "must be an object");
        ++i;
        continue;
      }
      check_known(p, pw, {"number", "cob_id", "transmission", "inhibit_time_us", "event_timer_ms", "sync_start",
                          "mapping", "entries", "timeout_ms", "on_timeout", "timeout_location"});
      const std::string what = std::string(is_tx ? "TPDO " : "RPDO ");
      pdo.number = i + 1;
      if (get_uint(p, "number", pw, false, 512, v)) {
        if (v == 0) error(pw, "field 'number' must be 1-512");
        pdo.number = (unsigned)v;
      }
      if (!numbers.insert(pdo.number).second)
        error(pw, what + std::to_string(pdo.number) + " is configured twice");
      const cJSON* cob = cJSON_GetObjectItemCaseSensitive(p, "cob_id");
      if (cJSON_IsString(cob) && std::string(cob->valuestring) == "auto") {
        pdo.cob_auto = true;
        pdo.has_cob_id = true;
      } else if (get_uint(p, "cob_id", pw, false, 0x7FF, v)) {
        if (v < 0x80) error(pw, "field 'cob_id' must be an 11-bit COB-ID from 0x80, or \"auto\"");
        pdo.cob_id = (uint32_t)v;
        pdo.has_cob_id = true;
      } else if (pdo.number > 4 && !cob) {
        error(pw, what + std::to_string(pdo.number) + " has no default COB-ID; set 'cob_id' (or \"auto\")");
      }
      if (get_uint(p, "transmission", pw, false, 255, v)) {
        if (v > 240 && v < 254) error(pw, "field 'transmission' must be 0-240, 254 or 255");
        pdo.transmission = (unsigned)v;
        pdo.has_transmission = true;
      }
      if (get_uint(p, "inhibit_time_us", pw, false, 6553500, v)) {
        if (!is_tx)
          error(pw, what + std::to_string(pdo.number) +
                        ": field 'inhibit_time_us' is only for tx_pdos (PDOs the node sends)");
        else if (v % 100)
          error(pw, what + std::to_string(pdo.number) + ": field 'inhibit_time_us' must be a multiple of 100");
        pdo.inhibit_time_us = (unsigned)v;
        pdo.has_inhibit_time = true;
      }
      if (get_uint(p, "event_timer_ms", pw, false, 0xFFFF, v)) {
        pdo.event_timer_ms = (unsigned)v;
        pdo.has_event_timer = true;
      }
      if (get_uint(p, "sync_start", pw, false, 240, v)) {
        if (!is_tx)
          error(pw, what + std::to_string(pdo.number) + ": field 'sync_start' is only for tx_pdos (PDOs the node sends)");
        else if (pdo.has_transmission && (pdo.transmission < 1 || pdo.transmission > 240))
          error(pw, what + std::to_string(pdo.number) +
                        ": field 'sync_start' needs a synchronous transmission type (1-240), not " +
                        std::to_string(pdo.transmission));
        pdo.sync_start = (unsigned)v;
        pdo.has_sync_start = true;
      }
      parse_timeout(p, pw, what + std::to_string(pdo.number), is_tx, pdo);
      std::string mapping;
      if (get_string(p, "mapping", pw, false, mapping)) {
        if (mapping == "config")
          pdo.mapping = PdoConfig::Mapping::Config;
        else if (mapping == "device")
          pdo.mapping = PdoConfig::Mapping::Device;
        else
          error(pw, "field 'mapping' must be \"config\" or \"device\", not \"" + mapping + "\"");
      }

      const cJSON* entries = cJSON_GetObjectItemCaseSensitive(p, "entries");
      if (!entries || !cJSON_IsArray(entries) || cJSON_GetArraySize(entries) == 0) {
        error(pw, "missing required field 'entries' (a non-empty array)");
      } else {
        unsigned bits = 0;
        int j = 0;
        const cJSON* e;
        cJSON_ArrayForEach(e, entries) {
          std::string ew = pw + ": entries[" + std::to_string(j) + "]";
          PdoEntry entry;
          bool ok = true;
          if (!cJSON_IsObject(e)) {
            error(ew, "must be an object");
            ++j;
            continue;
          }
          check_known(e, ew, {"index", "subindex", "type", "iec_location"});
          if (get_uint(e, "index", ew, true, 0xFFFF, v)) entry.index = (uint16_t)v; else ok = false;
          if (get_uint(e, "subindex", ew, false, 0xFF, v)) entry.subindex = (uint8_t)v;
          std::string type;
          if (get_string(e, "type", ew, true, type)) {
            if (!parse_co_type(type, entry.type)) {
              error(ew, "unsupported type \"" + type +
                            "\" (use BOOLEAN, INTEGER8/16/32/64, UNSIGNED8/16/32/64, REAL32, REAL64)");
              ok = false;
            }
          } else {
            ok = false;
          }
          char obj[32];
          std::snprintf(obj, sizeof(obj), "0x%04X:%u", entry.index, entry.subindex);
          if (!cJSON_GetObjectItemCaseSensitive(e, "iec_location")) {
            // Allowed only for an entry a gateway route uses (checked once
            // the gateway section is read).
            entry.has_location = false;
            if (ok) unlocated_.push_back({network_index_, n.node_id, is_tx, entry.index, entry.subindex, full(ew)});
          } else if (!get_location(e, "iec_location", ew, true, entry.location)) {
            ok = false;
          }
          if (ok && entry.has_location) {
            IecArea want = is_tx ? IecArea::Input : IecArea::Output;
            if (entry.location.area != want) {
              error(ew, n.label() + ", object " + obj + ": " +
                            (is_tx ? "data received from the slave (tx_pdos) needs an input location (%I...), not "
                                   : "data sent to the slave (rx_pdos) needs an output location (%Q...), not ") +
                            entry.location.str());
              ok = false;
            } else if (!co_type_fits(entry.type, entry.location.size)) {
              error(ew, n.label() + ", object " + obj + ": type " + co_type_name(entry.type) + " (" +
                            std::to_string(co_type_bits(entry.type)) + " bit) does not fit location " +
                            entry.location.str() + " (" +
                            std::to_string(iec_size_bits(entry.location.size)) + " bit)");
              ok = false;
            }
          }
          bits += co_type_bits(entry.type);
          if (ok) pdo.entries.push_back(entry);
          ++j;
        }
        if (bits > 64)
          error(pw, "mapped objects total " + std::to_string(bits) + " bits; a PDO carries at most 64");
      }
      (is_tx ? n.tx_pdos : n.rx_pdos).push_back(pdo);
      ++i;
    }
  }

  bool parse(const cJSON* root, ConfigSet& set) {
    size_t before = errors_.size();
    if (!cJSON_IsObject(root)) {
      error("", "top level must be a JSON object");
      return false;
    }
    uint64_t v;
    if (get_uint(root, "schema_version", "", false, 0xFFFFFFFF, v)) {
      if (v == 0) error("", "field 'schema_version' must be 1 or higher");
      if (v > kSchemaVersion) {
        // A newer format: do not guess at its meaning.
        error("", "schema_version " + std::to_string(v) + " is not supported; the highest supported version is " +
                      std::to_string(kSchemaVersion));
        return false;
      }
      set.schema_version = v ? (unsigned)v : 1;
    } else if (cJSON_GetObjectItemCaseSensitive(root, "schema_version")) {
      return false;
    }
    version_ = set.schema_version;
    if (version_ == 1) {
      for (const char* key : {"role", "slave"})
        if (cJSON_GetObjectItemCaseSensitive(root, key))
          error("", std::string("field '") + key + "': slave networks need schema_version: 2 (networks[] with "
                    "\"role\": \"slave\")");
      if (cJSON_GetObjectItemCaseSensitive(root, "gateway"))
        error("", "field 'gateway' needs schema_version: 2");
      for (const char* key : {"protocol", "j1939", "raw", "bridge"})
        if (cJSON_GetObjectItemCaseSensitive(root, key))
          error("", std::string("field '") + key + "' needs schema_version 2");
      if (limits_.bridge_host && !cJSON_GetObjectItemCaseSensitive(root, "bridge"))
        error("", kNotBridgeConfig);
      check_known(root, "", {"$schema", "schema_version", "adapter", "interface", "bitrate", "master", "nodes",
                             "role", "slave", "gateway", "protocol", "j1939", "raw", "bridge"});
      Config cfg = blank(set);
      cfg.work_dir = set.config_dir + "/.canworks";
      parse_network(root, cfg);
      report_unlocated(set);
      set.networks.push_back(cfg);
      return errors_.size() == before;
    }

    // Version 2: networks[] and one diagnostics object for all of them.
    check_known(root, "", {"$schema", "schema_version", "networks", "diagnostics", "gateway", "bridge"});
    // A bridge config's locations are byte-addressed from the first one on.
    byte_mode_ = cJSON_GetObjectItemCaseSensitive(root, "bridge") != nullptr;
    if (byte_mode_ && !limits_.bridge_host)
      error("", "this is a Modbus bridge config (it has a 'bridge' object): run it with canworks-bridge, not the "
                "OpenPLC plugin");
    if (!byte_mode_ && limits_.bridge_host) error("", kNotBridgeConfig);
    static const char* const kMoved[][2] = {{"adapter", "networks[].adapter"},
                                            {"master", "networks[].master"},
                                            {"nodes", "networks[].nodes"},
                                            {"interface", "networks[].adapter.interface"},
                                            {"bitrate", "networks[].adapter.bitrate"}};
    for (const auto& m : kMoved)
      if (cJSON_GetObjectItemCaseSensitive(root, m[0]))
        error("", std::string("field '") + m[0] + "' belongs in " + m[1] + " in schema_version 2");
    MasterConfig diag;
    parse_diagnostics(root, diag, "");
    const cJSON* nets = cJSON_GetObjectItemCaseSensitive(root, "networks");
    if (!nets || !cJSON_IsArray(nets)) {
      error("", "missing required field 'networks' (an array)");
      return false;
    }
    int count = cJSON_GetArraySize(nets);
    if (count < 1) error("", "field 'networks' lists no networks");
    if (count > (int)kMaxNetworks)
      error("", "field 'networks' lists " + std::to_string(count) + " networks; at most " +
                    std::to_string(kMaxNetworks) + " are supported");
    int i = 0;
    const cJSON* net;
    cJSON_ArrayForEach(net, nets) {
      prefix_ = "networks[" + std::to_string(i) + "]";
      Config cfg = blank(set);
      cfg.network_index = (unsigned)i;
      network_index_ = (unsigned)i;
      copy_diagnostics(diag, cfg.master);
      if (!cJSON_IsObject(net)) {
        error("", "must be an object");
      } else {
        check_known(net, "", {"name", "protocol", "role", "adapter", "master", "nodes", "slave", "j1939", "raw"});
        for (const char* old_key : {"interface", "bitrate"})
          if (cJSON_GetObjectItemCaseSensitive(net, old_key))
            error("", std::string("field '") + old_key + "' belongs in 'adapter' in schema_version 2");
        bool named = get_string(net, "name", "", false, cfg.network);
        if (named && !valid_network_name(cfg.network))
          error("", "network name \"" + cfg.network + "\" must start with a letter and hold only letters, digits "
                    "and '_', at most 16 characters");
        std::string protocol = "canopen";
        const cJSON* pj = cJSON_GetObjectItemCaseSensitive(net, "protocol");
        if (pj && (!cJSON_IsString(pj) || (std::strcmp(pj->valuestring, "canopen") != 0 &&
                                           std::strcmp(pj->valuestring, "j1939") != 0 &&
                                           std::strcmp(pj->valuestring, "none") != 0))) {
          error("", "field 'protocol' must be \"canopen\", \"j1939\" or \"none\"");
        } else if (pj) {
          protocol = pj->valuestring;
        }
        cfg.protocol = protocol == "j1939"  ? Protocol::J1939
                       : protocol == "none" ? Protocol::None
                                            : Protocol::CANopen;
        if (pj && !protocol_built_in(cfg.protocol))
          error("", std::string(cfg.is_j1939() ? "J1939" : "CANopen") + " is not built into this plugin (built with: " +
                        built_in_protocols() + ")");
        else if (!pj && !protocol_built_in(Protocol::CANopen))
          error("", "CANopen is not built into this plugin (built with: " + built_in_protocols() +
                        "); a network without 'protocol' is a CANopen network");
        std::string role = "master";
        if (cfg.is_j1939()) {
          parse_j1939_network(net, cfg);
        } else if (cfg.is_plain()) {
          parse_plain_network(net, cfg);
        } else if (cJSON_GetObjectItemCaseSensitive(net, "j1939")) {
          error("", "field 'j1939' belongs to a J1939 network (\"protocol\": \"j1939\")");
        }
        if (cfg.is_canopen() && get_string(net, "role", "", false, role) && role != "master" && role != "slave")
          error("", "field 'role' must be \"master\" or \"slave\", not \"" + role + "\"");
        if (!cfg.is_canopen()) {
          // Parsed above.
        } else if (role == "slave") {
          cfg.role = NetworkRole::Slave;
          parse_slave_network(net, cfg);
        } else {
          if (cJSON_GetObjectItemCaseSensitive(net, "slave"))
            error("", "field 'slave' belongs to a slave network (\"role\": \"slave\"), not a master network");
          parse_network(net, cfg);
        }
        if (cfg.adapter.listen_only && !cfg.is_plain())
          error("adapter", "field 'listen_only' needs a plain CAN network (\"protocol\": \"none\"): a " +
                               std::string(cfg.is_j1939() ? "J1939" : "CANopen") + " network must send");
        parse_raw_object(net, cfg);
        if (!named && !cfg.adapter.interface.empty()) {
          if (valid_network_name(cfg.adapter.interface))
            cfg.network = cfg.adapter.interface;
          else
            error("", "interface \"" + cfg.adapter.interface + "\" is not usable as a network name; give the "
                      "network a 'name'");
        }
      }
      set.networks.push_back(cfg);
      ++i;
    }
    prefix_.clear();
    if (byte_mode_) parse_bridge(root, set);
    check_networks(set);
    check_raw_ownership(set);
    parse_gateway(root, set);
    report_unlocated(set);
    if (set.networks.size() > 1)
      for (auto& cfg : set.networks) cfg.log_prefix = cfg.network;
    for (auto& cfg : set.networks)
      cfg.work_dir = set.config_dir + "/.canworks/" + (cfg.network.empty() ? std::to_string(cfg.network_index)
                                                                         : cfg.network);
    return errors_.size() == before;
  }

  static Config blank(const ConfigSet& set) {
    Config cfg;
    cfg.path = set.path;
    cfg.config_dir = set.config_dir;
    cfg.schema_version = set.schema_version;
    return cfg;
  }

  // A Linux interface name the plugin can open or create (IFNAMSIZ - 1).
  static bool valid_interface_name(const std::string& name) {
    if (name.empty() || name.size() > 15) return false;
    for (char c : name)
      if (!std::isalnum(static_cast<unsigned char>(c)) && c != '_' && c != '.' && c != ':' && c != '-') return false;
    return true;
  }

  static bool valid_network_name(const std::string& name) {
    if (name.empty() || name.size() > 16 || !std::isalpha(static_cast<unsigned char>(name[0]))) return false;
    for (char c : name)
      if (!std::isalnum(static_cast<unsigned char>(c)) && c != '_') return false;
    return true;
  }

  static void copy_diagnostics(const MasterConfig& from, MasterConfig& to) {
    to.has_diagnostics = from.has_diagnostics;
    to.diag_token_verifier = from.diag_token_verifier;
    to.diag_scram = from.diag_scram;
    to.diag_port = from.diag_port;
    to.diag_bind = from.diag_bind;
    to.diag_allow_changes = from.diag_allow_changes;
    to.diag_allow_config_upload = from.diag_allow_config_upload;
  }

  static std::string lower(std::string s) {
    for (char& c : s) c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    return s;
  }

  // The checks between networks (canopen-networks spec): names, adapters and
  // IEC locations.
  void check_networks(const ConfigSet& set) {
    std::map<std::string, unsigned> names, ifaces, devices;
    std::map<std::string, std::map<bool, unsigned>> simulated;  // interface -> slave? -> network
    // "networks[1] (drives)": the network by index and name.
    auto who = [&set](unsigned i) {
      std::string s = "networks[" + std::to_string(i) + "]";
      for (const auto& c : set.networks)
        if (c.network_index == i && !c.network.empty()) s += " (" + c.network + ")";
      return s;
    };
    for (const auto& cfg : set.networks) {
      std::string me = "networks[" + std::to_string(cfg.network_index) + "]";
      if (!cfg.network.empty()) {
        auto it = names.find(lower(cfg.network));
        if (it != names.end())
          error("networks", "networks[" + std::to_string(it->second) + "] and " + me + " are both named \"" +
                                cfg.network + "\" (names must differ, ignoring case)");
        else
          names[lower(cfg.network)] = cfg.network_index;
      }
      if (!cfg.adapter.interface.empty() && cfg.adapter.simulate) {
        // Simulated networks with one interface name share one in-process
        // bus: one master network and one slave network at most.
        auto& bus = simulated[cfg.adapter.interface];
        const bool slave = cfg.role == NetworkRole::Slave;
        auto it = bus.find(slave);
        if (it != bus.end())
          error("networks", who(it->second) + " and " + who(cfg.network_index) + " are both " +
                                (slave ? "slave" : "master") + " networks on simulated bus " + cfg.adapter.interface +
                                " (a simulated bus takes one master network and one slave network)");
        else
          bus[slave] = cfg.network_index;
      } else if (!cfg.adapter.interface.empty()) {
        auto it = ifaces.find(cfg.adapter.interface);
        if (it != ifaces.end())
          error("networks", who(it->second) + " and " + who(cfg.network_index) + " both use interface " +
                                cfg.adapter.interface);
        else
          ifaces[cfg.adapter.interface] = cfg.network_index;
      }
      if (cfg.adapter.type == "slcan" && !cfg.adapter.device.empty()) {
        auto it = devices.find(cfg.adapter.device);
        if (it != devices.end())
          error("networks", who(it->second) + " and " + who(cfg.network_index) + " both use serial device " +
                                cfg.adapter.device);
        else
          devices[cfg.adapter.device] = cfg.network_index;
      }
    }
    // On a shared simulated bus the master's node for the slave network is
    // the plugin's own slave: a simulated device with that node ID would
    // answer next to it.
    for (const auto& sl : set.networks) {
      if (sl.role != NetworkRole::Slave || !sl.adapter.simulate || sl.adapter.interface.empty() || sl.slave.lss)
        continue;
      for (const auto& m : set.networks) {
        if (m.role == NetworkRole::Slave || !m.adapter.simulate || m.adapter.interface != sl.adapter.interface)
          continue;
        for (size_t i = 0; i < m.nodes.size(); ++i)
          if (m.nodes[i].node_id == sl.slave.node_id && m.nodes[i].simulate)
            error("networks", who(m.network_index) + " node " + std::to_string(sl.slave.node_id) + " is " +
                                  who(sl.network_index) + " on simulated bus " + sl.adapter.interface +
                                  "; set \"simulate\": false on the node, or the simulator answers in its place");
      }
    }
    std::vector<Use> uses;
    for (const auto& cfg : set.networks) {
      std::string who = "networks[" + std::to_string(cfg.network_index) + "]";
      if (!cfg.network.empty()) who += " (" + cfg.network + ")";
      collect_uses(cfg, who + " ", uses);
    }
    bridge_uses(set.bridge, uses);
    report_overlaps(uses, "networks");
  }

  // ---- J1939 networks (j1939-config spec) ----

  // An integer field of a J1939 object; false when it is missing or not a
  // non-negative integer (the latter is an error). Ranges are checked by the
  // caller, so the message can name the J1939 range.
  bool j_uint(const cJSON* obj, const char* key, const std::string& where, uint64_t& out) {
    const cJSON* item = cJSON_GetObjectItemCaseSensitive(obj, key);
    if (!item) return false;
    if (!cJSON_IsNumber(item) || item->valuedouble < 0 ||
        item->valuedouble != (double)(uint64_t)item->valuedouble) {
      error(where, std::string("field '") + key + "' must be a non-negative integer");
      return false;
    }
    out = (uint64_t)item->valuedouble;
    return true;
  }

  // As j_uint, then within lo..hi ("address 254 is out of range 0..253").
  bool j_range(const cJSON* obj, const char* key, const std::string& where, uint64_t lo, uint64_t hi,
               uint64_t& out, const std::string& extra = "") {
    if (!j_uint(obj, key, where, out)) return false;
    if (out < lo || out > hi) {
      error(where, std::string(key) + " " + std::to_string(out) + " is out of range " + std::to_string(lo) + ".." +
                       std::to_string(hi) + extra);
      return false;
    }
    return true;
  }

  // A 64-bit value written as a string ("0x00000000000004D2") or an integer.
  bool j_uint64(const cJSON* obj, const char* key, const std::string& where, uint64_t& out) {
    const cJSON* item = cJSON_GetObjectItemCaseSensitive(obj, key);
    if (!item) return false;
    if (cJSON_IsString(item) && item->valuestring[0] && item->valuestring[0] != '-') {
      errno = 0;
      char* end = nullptr;
      out = std::strtoull(item->valuestring, &end, 0);
      if (*end == '\0' && errno == 0) return true;
    } else if (cJSON_IsNumber(item)) {
      return j_uint(obj, key, where, out);
    }
    error(where, std::string("field '") + key + "' must be a 64-bit unsigned integer, decimal or 0x hex");
    return false;
  }

  bool j_location(const cJSON* obj, const char* key, const std::string& where, IecArea area, IecSize size,
                  const char* what, IecLocation& out) {
    if (!cJSON_GetObjectItemCaseSensitive(obj, key)) return false;
    if (!get_location(obj, key, where, false, out)) return false;
    if (out.area != area || out.size != size) {
      error(where, std::string(key) + " " + out.str() + " must be " + what);
      return false;
    }
    return true;
  }

  bool j_pgn(const cJSON* obj, const std::string& where, uint32_t& out) {
    uint64_t v;
    if (!cJSON_GetObjectItemCaseSensitive(obj, "pgn")) {
      error(where, "field 'pgn' is missing");
      return false;
    }
    if (!j_range(obj, "pgn", where, 0, kJ1939MaxPgn, v, " (0x3FFFF)")) return false;
    out = (uint32_t)v;
    if (j1939_pdu1(out) && (out & 0xFF))
      error(where, "PGN " + j1939_pgn_text(out) +
                       " is a PDU1 PGN: its low byte must be 0 (the destination is given separately)");
    return true;
  }

  bool j_destination(const cJSON* obj, const std::string& where, unsigned& out) {
    uint64_t v;
    if (!j_uint(obj, "destination", where, v)) return false;
    if (v > kJ1939MaxAddress && v != kJ1939Global) {
      error(where, "destination " + std::to_string(v) + " is out of range 0..253 or 255 (global)");
      return false;
    }
    out = (unsigned)v;
    return true;
  }

  // `switch_mode`: the pages mode ("all", "rotate") of a tx entry whose
  // switches the plugin sets, "" when its `pages` was wrong, else nullptr.
  void parse_j1939_signals(const cJSON* msg, const std::string& where, bool rx, const char* switch_mode,
                           std::vector<J1939Signal>& out) {
    const cJSON* arr = cJSON_GetObjectItemCaseSensitive(msg, "signals");
    if (!arr) {
      error(where, "field 'signals' is missing");
      return;
    }
    if (!cJSON_IsArray(arr)) {
      error(where, "field 'signals' must be an array");
      return;
    }
    int i = 0;
    const cJSON* sj;
    cJSON_ArrayForEach(sj, arr) {
      unsigned index = static_cast<unsigned>(i);
      std::string sw = where + ": signals[" + std::to_string(i++) + "]";
      if (!cJSON_IsObject(sj)) {
        error(sw, "must be an object");
        continue;
      }
      check_known(sj, sw, {"name", "start_bit", "length", "byte_order", "signed", "scale", "offset", "unit",
                           "iec_location", "valid_location", "multiplexer", "mux"});
      J1939Signal s;
      s.index = index;
      {
        std::vector<std::string> errs;
        canworks_can::parse_mux_fields(sj, "signals[" + std::to_string(index) + "]", s.mux, errs);
        for (const auto& e : errs) error(where, e);
      }
      if (!get_string(sj, "name", sw, true, s.name)) continue;
      const std::string me = "signal " + s.name;
      bool ok = true;
      uint64_t v;
      if (!cJSON_GetObjectItemCaseSensitive(sj, "start_bit")) {
        error(where, me + ": field 'start_bit' is missing");
        ok = false;
      } else if (j_range(sj, "start_bit", where + ": " + me, 0, kJ1939MaxLength * 8 - 1, v)) {
        s.start_bit = (unsigned)v;
      } else {
        ok = false;
      }
      if (!cJSON_GetObjectItemCaseSensitive(sj, "length")) {
        error(where, me + ": field 'length' is missing");
        ok = false;
      } else if (j_range(sj, "length", where + ": " + me, 1, 64, v)) {
        s.length = (unsigned)v;
      } else {
        ok = false;
      }
      std::string order;
      if (get_string(sj, "byte_order", sw, false, order)) {
        if (order == "big")
          s.big_endian = true;
        else if (order != "little")
          error(where, me + ": field 'byte_order' must be \"little\" or \"big\", not \"" + order + "\"");
      }
      get_bool(sj, "signed", sw, s.is_signed);
      get_number(sj, "scale", sw, -1e300, 1e300, s.scale);
      get_number(sj, "offset", sw, -1e300, 1e300, s.offset);
      get_string(sj, "unit", sw, false, s.unit);
      if (s.mux.is_switch && switch_mode) {
        // The plugin sets this switch; an empty mode: `pages` was wrong.
        s.has_location = false;
        if (cJSON_GetObjectItemCaseSensitive(sj, "iec_location") && *switch_mode)
          error(where, "signals[" + std::to_string(index) + "].iec_location: the plugin sets switch " + s.name +
                           " when pages is \"" + switch_mode + "\"; leave it out");
      } else if (!cJSON_GetObjectItemCaseSensitive(sj, "iec_location")) {
        error(where, me + ": field 'iec_location' is missing");
        ok = false;
      } else if (get_location(sj, "iec_location", where + ": " + me, false, s.location)) {
        if (rx && s.location.area != IecArea::Input) {
          error(where, me + ": location " + s.location.str() + " must be an input (%I)");
          ok = false;
        } else if (!rx && s.location.area != IecArea::Output) {
          error(where, me + ": location " + s.location.str() + " must be an output (%Q)");
          ok = false;
        } else if (ok && (s.location.size == IecSize::X ? s.length != 1
                                                        : s.length > iec_size_bits(s.location.size))) {
          error(where, me + " (" + std::to_string(s.length) + " bit" + (s.length == 1 ? "" : "s") +
                           ") does not fit location " + s.location.str() + " (" +
                           std::to_string(iec_size_bits(s.location.size)) + " bit)");
          ok = false;
        }
      } else {
        ok = false;
      }
      if (cJSON_GetObjectItemCaseSensitive(sj, "valid_location")) {
        if (!rx)
          error(where, me + ": field 'valid_location' is only for received signals (rx)");
        else
          s.has_valid_location = j_location(sj, "valid_location", where + ": " + me, IecArea::Input, IecSize::X,
                                            "a bit input (%IX)", s.valid_location);
      }
      if (ok) out.push_back(s);
    }
  }

  void parse_j1939_ecu(const cJSON* j, J1939Ecu& ecu) {
    const std::string w = "j1939: ecu";
    const cJSON* e = cJSON_GetObjectItemCaseSensitive(j, "ecu");
    if (!e) {
      error("j1939", "field 'ecu' is missing");
      return;
    }
    if (!cJSON_IsObject(e)) {
      error("j1939", "field 'ecu' must be an object");
      return;
    }
    check_known(e, w, {"name", "address", "address_range", "state_location", "address_location"});
    uint64_t v;
    const cJSON* n = cJSON_GetObjectItemCaseSensitive(e, "name");
    if (!n) {
      error(w, "field 'name' is missing");
    } else if (!cJSON_IsObject(n)) {
      error(w, "field 'name' must be an object of NAME fields");
    } else {
      const std::string nw = w + ": name";
      check_known(n, nw, {"identity_number", "manufacturer_code", "ecu_instance", "function_instance", "function",
                          "vehicle_system", "vehicle_system_instance", "industry_group", "arbitrary_address_capable"});
      J1939Name& nm = ecu.name;
      if (j_range(n, "identity_number", nw, 0, 0x1FFFFF, v)) nm.identity_number = (uint32_t)v;
      if (j_range(n, "manufacturer_code", nw, 0, 2047, v)) nm.manufacturer_code = (uint16_t)v;
      if (j_range(n, "ecu_instance", nw, 0, 7, v)) nm.ecu_instance = (uint8_t)v;
      if (j_range(n, "function_instance", nw, 0, 31, v)) nm.function_instance = (uint8_t)v;
      if (j_range(n, "function", nw, 0, 255, v)) nm.function = (uint8_t)v;
      if (j_range(n, "vehicle_system", nw, 0, 127, v)) nm.vehicle_system = (uint8_t)v;
      if (j_range(n, "vehicle_system_instance", nw, 0, 15, v)) nm.vehicle_system_instance = (uint8_t)v;
      if (j_range(n, "industry_group", nw, 0, 7, v)) nm.industry_group = (uint8_t)v;
      get_bool(n, "arbitrary_address_capable", nw, nm.arbitrary_address_capable);
    }
    if (!cJSON_GetObjectItemCaseSensitive(e, "address"))
      error(w, "field 'address' is missing");
    else if (j_range(e, "address", w, 0, kJ1939MaxAddress, v))
      ecu.address = (unsigned)v;
    const cJSON* r = cJSON_GetObjectItemCaseSensitive(e, "address_range");
    if (r) {
      const cJSON* lo = cJSON_GetArrayItem(r, 0);
      const cJSON* hi = cJSON_GetArrayItem(r, 1);
      auto addr = [](const cJSON* x) { return cJSON_IsNumber(x) && x->valuedouble >= 0 && x->valuedouble <= 253 &&
                                              x->valuedouble == (double)(int)x->valuedouble; };
      char* text = cJSON_PrintUnformatted(r);
      std::string shown = text ? text : "?";
      cJSON_free(text);
      for (size_t k = 0; k < shown.size(); ++k)
        if (shown[k] == ',') shown.insert(++k, " ");
      if (!cJSON_IsArray(r) || cJSON_GetArraySize(r) != 2 || !addr(lo) || !addr(hi) ||
          lo->valuedouble > hi->valuedouble) {
        error(w, "address_range " + shown + " must be [low, high] within 0..253");
      } else {
        ecu.has_range = true;
        ecu.range_low = (unsigned)lo->valuedouble;
        ecu.range_high = (unsigned)hi->valuedouble;
        if (!ecu.name.arbitrary_address_capable)
          error(w, "address_range needs a NAME with arbitrary_address_capable true");
      }
    }
    ecu.has_state_location = j_location(e, "state_location", w, IecArea::Input, IecSize::B, "a byte input (%IB)",
                                        ecu.state_location);
    ecu.has_address_location = j_location(e, "address_location", w, IecArea::Input, IecSize::B,
                                          "a byte input (%IB)", ecu.address_location);
  }

  // ---- Plain CAN networks and raw messages (can-raw-messages spec) ----

  void parse_plain_network(const cJSON* net, Config& cfg) {
    for (const char* key : {"role", "master", "nodes", "slave", "j1939"})
      if (cJSON_GetObjectItemCaseSensitive(net, key))
        error("", std::string("field '") + key + "' does not belong to a plain CAN network (\"protocol\": \"none\"), "
                  "which has only 'adapter' and 'raw'");
    parse_adapter(net, cfg.adapter);
    if (limits_.force_simulate) {
      cfg.adapter.simulate = true;
      cfg.adapter.simulation_forced = true;
    }
  }

  // The network's `raw` object; its messages name their place in the file as
  // "networks[0].raw.rx[1]", as the PC tools' checks do.
  void parse_raw_object(const cJSON* net, Config& cfg) {
    std::vector<std::string> errors, warnings;
    std::string at = "networks[" + std::to_string(cfg.network_index) + "].raw";
    canworks_raw::parse_raw(cJSON_GetObjectItemCaseSensitive(net, "raw"), at, cfg.adapter.listen_only, cfg.raw,
                            errors, warnings);
    for (const auto& e : errors) errors_.push_back(path_ + ": " + e);
    for (const auto& w : warnings) warnings_.push_back(path_ + ": " + w);
    // The same image check as every other location (can-raw-messages "Raw
    // message locations inside the I/O image").
    std::vector<std::pair<IecLocation, std::string>> locs;
    canworks_raw::raw_locations(cfg.raw, locs);
    for (const auto& l : locs)
      if (!iec_location_in_image(l.first, limits_.buffer_size, byte_mode_))
        errors_.push_back(path_ + ": " + l.second + ": " + l.first.str() +
                          " lies outside the runtime I/O image (index must be below " +
                          std::to_string(limits_.buffer_size) + ")");
    if (cfg.is_plain() && cfg.raw.empty())
      cfg.notes.push_back("network has no raw messages; it serves the program's CAN_* blocks, traces and diagnostics");
  }

  // Sent raw messages on identifiers the network's protocol uses need
  // override_protocol (design Decision 7).
  void check_raw_ownership(ConfigSet& set) {
    for (auto& cfg : set.networks) {
      if (cfg.raw.tx.empty()) continue;
      std::vector<std::string> errors, overrides;
      const Config& c = cfg;
      canworks_raw::check_protocol_ids(
          cfg.raw, [&c](uint32_t id, bool ext) { return protocol_id_use(c, id, ext); }, errors, overrides);
      for (const auto& e : errors) errors_.push_back(path_ + ": " + e);
      for (const auto& o : overrides) cfg.notes.push_back(o);
    }
  }

  // The `diagnostics` object (j1939-diagnostics "Diagnostics config").
  void parse_j1939_diagnostics(const cJSON* j, J1939Diagnostics& d) {
    const cJSON* o = cJSON_GetObjectItemCaseSensitive(j, "diagnostics");
    if (!o) return;
    const std::string w = "j1939: diagnostics";
    if (!cJSON_IsObject(o)) {
      error("j1939", "field 'diagnostics' must be an object");
      return;
    }
    check_known(o, w, {"rx", "dtcs", "lamps_location", "clear_location", "accept_clear", "dm13"});
    uint64_t v;
    const cJSON* arr = cJSON_GetObjectItemCaseSensitive(o, "rx");
    if (arr && !cJSON_IsArray(arr)) error(w, "field 'rx' must be an array");
    const cJSON* list = cJSON_IsArray(arr) ? arr : nullptr;
    int i = 0;
    const cJSON* m;
    cJSON_ArrayForEach(m, list) {
      std::string mw = w + ": rx[" + std::to_string(i++) + "]";
      if (!cJSON_IsObject(m)) {
        error(mw, "must be an object");
        continue;
      }
      check_known(m, mw, {"source", "source_name", "source_name_mask", "timeout_ms", "status_location",
                          "lamps_location", "flash_location", "count_location", "dtcs_location", "dtcs"});
      J1939DmRx r;
      bool src = cJSON_GetObjectItemCaseSensitive(m, "source") != nullptr;
      bool src_name = cJSON_GetObjectItemCaseSensitive(m, "source_name") != nullptr;
      if (src && src_name) {
        error(mw, "give 'source' or 'source_name', not both");
      } else if (src) {
        if (j_range(m, "source", mw, 0, kJ1939MaxAddress, v)) {
          r.has_source = true;
          r.source = (unsigned)v;
        }
      } else if (src_name) {
        r.has_source_name = j_uint64(m, "source_name", mw, r.source_name);
      } else {
        error(mw, "give 'source' or 'source_name': the ECU whose DM1 the program sees");
      }
      if (cJSON_GetObjectItemCaseSensitive(m, "source_name_mask")) {
        if (!src_name)
          error(mw, "field 'source_name_mask' needs 'source_name'");
        else
          j_uint64(m, "source_name_mask", mw, r.source_name_mask);
      }
      if (j_range(m, "timeout_ms", mw, 0, kJ1939MaxPeriodMs, v)) r.timeout_ms = (unsigned)v;
      r.has_status_location =
          j_location(m, "status_location", mw, IecArea::Input, IecSize::X, "a bit input (%IX)", r.status_location);
      r.has_lamps_location =
          j_location(m, "lamps_location", mw, IecArea::Input, IecSize::B, "a byte input (%IB)", r.lamps_location);
      r.has_flash_location =
          j_location(m, "flash_location", mw, IecArea::Input, IecSize::B, "a byte input (%IB)", r.flash_location);
      r.has_count_location =
          j_location(m, "count_location", mw, IecArea::Input, IecSize::B, "a byte input (%IB)", r.count_location);
      r.has_dtcs_location = j_location(m, "dtcs_location", mw, IecArea::Input, IecSize::D,
                                       "a double word input (%ID)", r.dtcs_location);
      bool has_n = cJSON_GetObjectItemCaseSensitive(m, "dtcs") != nullptr;
      if (has_n && j_range(m, "dtcs", mw, 1, kJ1939MaxDmRxCodes, v)) r.dtcs = (unsigned)v;
      if (cJSON_GetObjectItemCaseSensitive(m, "dtcs_location") && !has_n)
        error(mw, "field 'dtcs' is missing: the number of codes at dtcs_location (1..32)");
      if (has_n && !cJSON_GetObjectItemCaseSensitive(m, "dtcs_location")) error(mw, "field 'dtcs' needs 'dtcs_location'");
      if (r.has_dtcs_location && r.dtcs) {
        IecLocation last = r.dtc_location(r.dtcs - 1);
        if (!iec_location_in_image(last, limits_.buffer_size, byte_mode_)) {
          error(mw, "dtcs_location " + r.dtcs_location.str() + " with " + std::to_string(r.dtcs) + " codes ends at " +
                        last.str() + ", outside the runtime I/O image (index must be below " +
                        std::to_string(limits_.buffer_size) + ")");
          r.has_dtcs_location = false;
        }
      }
      bool any = false;
      for (const char* key : {"status_location", "lamps_location", "flash_location", "count_location", "dtcs_location"})
        any = any || cJSON_GetObjectItemCaseSensitive(m, key);
      if (!any)
        error(mw, "needs at least one of status_location, lamps_location, flash_location, count_location and "
                  "dtcs_location");
      d.rx.push_back(r);
    }
    arr = cJSON_GetObjectItemCaseSensitive(o, "dtcs");
    if (arr && !cJSON_IsArray(arr)) error(w, "field 'dtcs' must be an array");
    list = cJSON_IsArray(arr) ? arr : nullptr;
    i = 0;
    cJSON_ArrayForEach(m, list) {
      std::string mw = w + ": dtcs[" + std::to_string(i++) + "]";
      if (!cJSON_IsObject(m)) {
        error(mw, "must be an object");
        continue;
      }
      check_known(m, mw, {"spn", "fmi", "active_location", "lamps", "flash"});
      J1939OwnDtc c;
      bool ok = true;
      if (!cJSON_GetObjectItemCaseSensitive(m, "spn")) {
        error(mw, "field 'spn' is missing");
        ok = false;
      } else if (j_range(m, "spn", mw, 0, kJ1939MaxSpn, v)) {
        c.spn = (uint32_t)v;
      } else {
        ok = false;
      }
      if (!cJSON_GetObjectItemCaseSensitive(m, "fmi")) {
        error(mw, "field 'fmi' is missing");
        ok = false;
      } else if (j_range(m, "fmi", mw, 0, 31, v)) {
        c.fmi = (uint8_t)v;
      } else {
        ok = false;
      }
      if (!cJSON_GetObjectItemCaseSensitive(m, "active_location")) {
        error(mw, "field 'active_location' is missing");
        ok = false;
      } else if (!j_location(m, "active_location", mw, IecArea::Output, IecSize::X, "a bit output (%QX)",
                             c.active_location)) {
        ok = false;
      }
      const cJSON* lamps = cJSON_GetObjectItemCaseSensitive(m, "lamps");
      if (lamps) {
        bool good = cJSON_IsArray(lamps);
        const cJSON* names = good ? lamps : nullptr;
        const cJSON* l;
        cJSON_ArrayForEach(l, names) {
          const char* t = cJSON_IsString(l) ? l->valuestring : "";
          if (!std::strcmp(t, "mil"))
            c.lamps |= kJ1939LampMil;
          else if (!std::strcmp(t, "red"))
            c.lamps |= kJ1939LampRed;
          else if (!std::strcmp(t, "amber"))
            c.lamps |= kJ1939LampAmber;
          else if (!std::strcmp(t, "protect"))
            c.lamps |= kJ1939LampProtect;
          else
            good = false;
        }
        if (!good) error(mw, "field 'lamps' must be a list of \"mil\", \"red\", \"amber\" and \"protect\"");
      }
      const cJSON* fl = cJSON_GetObjectItemCaseSensitive(m, "flash");
      if (fl) {
        if (cJSON_IsString(fl) && !std::strcmp(fl->valuestring, "slow"))
          c.flash = 0;
        else if (cJSON_IsString(fl) && !std::strcmp(fl->valuestring, "fast"))
          c.flash = 1;
        else
          error(mw, "field 'flash' must be \"slow\" or \"fast\"");
      }
      if (ok) d.dtcs.push_back(c);
    }
    d.has_lamps_location =
        j_location(o, "lamps_location", w, IecArea::Output, IecSize::B, "a byte output (%QB)", d.lamps_location);
    d.has_clear_location =
        j_location(o, "clear_location", w, IecArea::Input, IecSize::B, "a byte input (%IB)", d.clear_location);
    get_bool(o, "accept_clear", w, d.accept_clear);
    get_bool(o, "dm13", w, d.dm13);
  }

  void parse_j1939_network(const cJSON* net, Config& cfg) {
    for (const char* key : {"role", "master", "nodes", "slave"})
      if (cJSON_GetObjectItemCaseSensitive(net, key))
        error("", std::string("field '") + key + "' belongs to a CANopen network; a J1939 network has 'j1939'");
    parse_adapter(net, cfg.adapter);
    if (cfg.adapter.simulate)
      error("", "J1939 networks run on SocketCAN or slcan interfaces; use a vcan interface for simulation, not "
                "adapter.simulate");
    else if (limits_.force_simulate)
      error("", "J1939 networks need the Linux kernel's J1939 support and cannot run on the simulated bus this "
                "runtime forces (CANWORKS_FORCE_SIMULATE=1); run them on a vcan interface on a Linux runtime");
    const cJSON* j = cJSON_GetObjectItemCaseSensitive(net, "j1939");
    if (!j) {
      error("", "a J1939 network needs a 'j1939' object");
      return;
    }
    if (!cJSON_IsObject(j)) {
      error("", "field 'j1939' must be an object");
      return;
    }
    check_known(j, "j1939", {"ecu", "dbc", "rx", "tx", "requests", "diagnostics"});
    J1939Config& jc = cfg.j1939;
    parse_j1939_ecu(j, jc.ecu);
    get_string(j, "dbc", "j1939", false, jc.dbc);
    uint64_t v;
    for (const char* list : {"rx", "tx", "requests"}) {
      const cJSON* arr = cJSON_GetObjectItemCaseSensitive(j, list);
      if (arr && !cJSON_IsArray(arr)) {
        error("j1939", std::string("field '") + list + "' must be an array");
        continue;
      }
      int i = 0;
      const cJSON* m;
      cJSON_ArrayForEach(m, arr) {
        std::string w = std::string("j1939: ") + list + "[" + std::to_string(i++) + "]";
        if (!cJSON_IsObject(m)) {
          error(w, "must be an object");
          continue;
        }
        if (std::strcmp(list, "rx") == 0) {
          check_known(m, w, {"pgn", "name", "source", "source_name", "source_name_mask", "timeout_ms",
                             "status_location", "signals"});
          J1939Rx r;
          j_pgn(m, w, r.pgn);
          get_string(m, "name", w, false, r.name);
          bool src = cJSON_GetObjectItemCaseSensitive(m, "source") != nullptr;
          bool src_name = cJSON_GetObjectItemCaseSensitive(m, "source_name") != nullptr;
          if (src && src_name) {
            error(w, "give 'source' or 'source_name', not both");
          } else if (src) {
            if (j_range(m, "source", w, 0, kJ1939MaxAddress, v)) {
              r.has_source = true;
              r.source = (unsigned)v;
            }
          } else if (src_name) {
            r.has_source_name = j_uint64(m, "source_name", w, r.source_name);
          }
          if (cJSON_GetObjectItemCaseSensitive(m, "source_name_mask")) {
            if (!src_name)
              error(w, "field 'source_name_mask' needs 'source_name'");
            else
              j_uint64(m, "source_name_mask", w, r.source_name_mask);
          }
          if (j_range(m, "timeout_ms", w, 0, kJ1939MaxPeriodMs, v)) r.timeout_ms = (unsigned)v;
          r.has_status_location = j_location(m, "status_location", w, IecArea::Input, IecSize::X,
                                             "a bit input (%IX)", r.status_location);
          parse_j1939_signals(m, w, true, nullptr, r.signals);
          jc.rx.push_back(r);
        } else if (std::strcmp(list, "tx") == 0) {
          check_known(m, w, {"pgn", "name", "priority", "destination", "length", "period_ms", "min_gap_ms",
                             "pages", "signals"});
          J1939Tx t;
          bool pgn_ok = j_pgn(m, w, t.pgn);
          get_string(m, "name", w, false, t.name);
          if (j_range(m, "priority", w, 0, 7, v)) t.priority = (unsigned)v;
          if (j_destination(m, w, t.destination)) {
            t.has_destination = true;
            if (pgn_ok && !j1939_pdu1(t.pgn))
              error(w, "PGN " + j1939_pgn_text(t.pgn) + " is a PDU2 PGN and always broadcast; remove 'destination'");
          }
          if (j_range(m, "length", w, 1, kJ1939MaxLength, v)) {
            t.has_length = true;
            t.length = (unsigned)v;
          }
          if (j_range(m, "period_ms", w, 0, kJ1939MaxPeriodMs, v)) t.period_ms = (unsigned)v;
          if (j_range(m, "min_gap_ms", w, 0, kJ1939MaxPeriodMs, v)) t.min_gap_ms = (unsigned)v;
          std::string pages;
          bool pages_bad = false;
          if (cJSON_GetObjectItemCaseSensitive(m, "pages")) {
            t.has_pages = true;
            const cJSON* pj = cJSON_GetObjectItemCaseSensitive(m, "pages");
            pages_bad = !cJSON_IsString(pj) || !canworks_can::parse_mux_pages(pj->valuestring, t.pages);
            if (pages_bad) error(w, "pages: must be \"program\", \"all\" or \"rotate\"");
          }
          const char* mode = pages_bad ? ""
                             : t.pages == canworks_can::MuxPages::Program ? nullptr
                                                                           : canworks_can::mux_pages_name(t.pages);
          parse_j1939_signals(m, w, false, mode, t.signals);
          jc.tx.push_back(t);
        } else {
          check_known(m, w, {"pgn", "destination", "period_ms"});
          J1939Request q;
          j_pgn(m, w, q.pgn);
          j_destination(m, w, q.destination);
          if (!cJSON_GetObjectItemCaseSensitive(m, "period_ms"))
            error(w, "field 'period_ms' is missing");
          else if (j_range(m, "period_ms", w, kJ1939MinRequestPeriodMs, kJ1939MaxPeriodMs, v))
            q.period_ms = (unsigned)v;
          jc.requests.push_back(q);
        }
      }
    }
    parse_j1939_diagnostics(j, jc.diagnostics);
    check_j1939(jc, [this](const std::string& where, const std::string& msg) { error(where, msg); });
  }

  // Parses one network: the version 1 top level, or one networks[] entry.
  void parse_network(const cJSON* root, Config& cfg) {
    uint64_t v;
    parse_adapter(root, cfg.adapter);
    if (limits_.force_simulate) {
      // Before the nodes: they take the simulated-network default from it.
      cfg.adapter.simulate = true;
      cfg.adapter.simulation_forced = true;
    }

    const cJSON* master = cJSON_GetObjectItemCaseSensitive(root, "master");
    if (!master || !cJSON_IsObject(master)) {
      error("", "missing required field 'master' (an object)");
    } else {
      check_known(master, "master",
                  {"node_id", "sync_period_us", "sync_source", "sync_cycles", "heartbeat_ms", "eds_lint", "strict_eds",
                   "bus_state_location", "tx_error_count_location", "rx_error_count_location",
                   "bus_off_count_location", "state_location", "vendor_id", "product_code", "revision_number", "serial_number", "sync_window_us",
                   "sync_counter_overflow", "time_cob_id", "emcy_inhibit_time_us", "heartbeat_consumer",
                   "heartbeat_multiplier", "error_behavior", "nmt_inhibit_time_us", "start", "start_nodes",
                   "start_all_nodes", "reset_all_nodes", "stop_all_nodes", "boot_time_ms", "sdo_timeout_ms",
                   "time_period_ms", "on_plc_stop", "scan_watchdog_ms", "diagnostics"});
      if (get_uint(master, "node_id", "master", true, 0xFFFF, v)) {
        if (v < 1 || v > 127) error("master", "node ID " + std::to_string(v) + " is out of range (1-127)");
        cfg.master.node_id = (unsigned)v;
      }
      // Left out or 0: the master produces no SYNC.
      if (get_uint(master, "sync_period_us", "master", false, 0xFFFFFFFF, v)) cfg.master.sync_period_us = (unsigned)v;
      parse_sync_source(master, cfg.master);
      if (get_uint(master, "heartbeat_ms", "master", false, 0xFFFF, v)) cfg.master.heartbeat_ms = (unsigned)v;
      bool has_lint = cJSON_GetObjectItemCaseSensitive(master, "eds_lint") != nullptr;
      bool has_strict = cJSON_GetObjectItemCaseSensitive(master, "strict_eds") != nullptr;
      if (has_lint && has_strict) {
        error("master", "give either 'eds_lint' or the deprecated 'strict_eds', not both");
      } else if (has_lint) {
        const cJSON* lint = cJSON_GetObjectItemCaseSensitive(master, "eds_lint");
        std::string mode = cJSON_IsString(lint) ? lint->valuestring : "";
        if (mode == "communication" || mode == "all" || mode == "off")
          cfg.master.eds_lint = mode;
        else
          error("master", "field 'eds_lint' must be \"communication\", \"all\" or \"off\"");
      } else {
        bool strict = true;
        if (get_bool(master, "strict_eds", "master", strict)) cfg.master.eds_lint = strict ? "all" : "off";
      }
      MasterConfig& m = cfg.master;
      get_input_location(master, "bus_state_location", "master", IecSize::B, m.has_bus_state_location,
                         m.bus_state_location);
      get_input_location(master, "tx_error_count_location", "master", IecSize::B, m.has_tx_error_count_location,
                         m.tx_error_count_location);
      get_input_location(master, "rx_error_count_location", "master", IecSize::B, m.has_rx_error_count_location,
                         m.rx_error_count_location);
      get_input_location(master, "bus_off_count_location", "master", IecSize::W, m.has_bus_off_count_location,
                         m.bus_off_count_location);
      get_input_location(master, "state_location", "master", IecSize::B, m.has_state_location, m.state_location);
      parse_master_options(master, m);
    }

    const cJSON* nodes = cJSON_GetObjectItemCaseSensitive(root, "nodes");
    if (!nodes || !cJSON_IsArray(nodes)) {
      error("", "missing required field 'nodes' (an array)");
    } else {
      int i = 0;
      const cJSON* node;
      cJSON_ArrayForEach(node, nodes) {
        std::string w = "nodes[" + std::to_string(i) + "]";
        NodeConfig n;
        if (!cJSON_IsObject(node)) {
          error(w, "must be an object");
          ++i;
          continue;
        }
        check_known(node, w,
                    {"node_id", "name", "eds", "heartbeat_ms", "heartbeat_timeout_ms", "guard_time_ms",
                     "life_time_factor", "status_location", "state_location", "boot_error_location",
                     "emcy_code_location", "error_register_location", "nmt_command_location", "mandatory",
                     "boot", "reset_communication", "revision_number", "serial_number", "heartbeat_consumer",
                     "retry_factor", "time_cob_id", "error_behavior", "restore_configuration", "config_check",
                     "store_configuration", "lss", "axis", "software_file", "software_version", "tx_pdos",
                     "rx_pdos", "sdo", "sdo_variables", "simulate", "emcy_cob_id"});
        n.simulate = cfg.adapter.simulate;
        get_bool(node, "simulate", w, n.simulate);
        if (get_uint(node, "node_id", w, true, 0xFFFF, v)) n.node_id = (unsigned)v;
        get_string(node, "name", w, false, n.name);
        if (get_string(node, "eds", w, true, n.eds)) resolve_eds(cfg, n);
        if (get_uint(node, "heartbeat_ms", w, false, 0xFFFF, v)) {
          n.heartbeat_ms = (unsigned)v;
          n.has_heartbeat = true;
        }
        if (get_uint(node, "heartbeat_timeout_ms", w, false, 0xFFFF, v)) {
          n.heartbeat_timeout_ms = (unsigned)v;
          if (n.heartbeat_ms == 0) error(w, "'heartbeat_timeout_ms' needs 'heartbeat_ms'");
          else if (v < n.heartbeat_ms) error(w, "'heartbeat_timeout_ms' must not be shorter than 'heartbeat_ms'");
        } else if (n.heartbeat_ms) {
          n.heartbeat_timeout_ms = n.heartbeat_ms * 3 > 0xFFFF ? 0xFFFF : n.heartbeat_ms * 3;
        }
        if (get_uint(node, "guard_time_ms", w, false, 0xFFFF, v)) n.guard_time_ms = (unsigned)v;
        if (get_uint(node, "life_time_factor", w, false, 0xFF, v)) n.life_time_factor = (unsigned)v;
        if ((n.guard_time_ms == 0) != (n.life_time_factor == 0))
          error(w, "node guarding needs both 'guard_time_ms' and 'life_time_factor'");
        if (n.heartbeat_ms && n.guard_time_ms)
          error(w, "use either heartbeat ('heartbeat_ms') or node guarding ('guard_time_ms'), not both");
        // An explicit 0 accepts an unsupervised node (canopen-node-supervision
        // "Every node is supervised or says why not"); check_eds_files refuses
        // one that is unsupervised only through its EDS default.
        if (n.has_heartbeat && n.heartbeat_ms == 0 && n.guard_time_ms == 0)
          warning(w, "node " + std::to_string(n.node_id) + (n.name.empty() ? "" : " (" + n.name + ")") +
                         ": \"heartbeat_ms\": 0 and no guarding: its loss is not detected");
        if (cJSON_GetObjectItemCaseSensitive(node, "status_location")) {
          IecLocation loc;
          if (get_location(node, "status_location", w, false, loc)) {
            if (loc.area != IecArea::Input || loc.size != IecSize::X)
              error(w, "status_location must be an input bit (%IX...), not " + loc.str());
            else {
              n.has_status_location = true;
              n.status_location = loc;
            }
          }
        }
        if (cJSON_GetObjectItemCaseSensitive(node, "state_location")) {
          IecLocation loc;
          if (get_location(node, "state_location", w, false, loc)) {
            if (loc.area != IecArea::Input || loc.size != IecSize::B)
              error(w, "state_location must be an input byte (%IB...), not " + loc.str());
            else {
              n.has_state_location = true;
              n.state_location = loc;
            }
          }
        }
        get_input_location(node, "boot_error_location", w, IecSize::B, n.has_boot_error_location,
                           n.boot_error_location);
        get_input_location(node, "emcy_code_location", w, IecSize::W, n.has_emcy_code_location,
                           n.emcy_code_location);
        get_input_location(node, "error_register_location", w, IecSize::B, n.has_error_register_location,
                           n.error_register_location);
        if (cJSON_GetObjectItemCaseSensitive(node, "nmt_command_location")) {
          IecLocation loc;
          if (get_location(node, "nmt_command_location", w, false, loc)) {
            if (loc.area != IecArea::Output || loc.size != IecSize::B)
              error(w, n.label() + ": nmt_command_location must be an output byte (%QB...), not " + loc.str());
            else {
              n.has_nmt_command_location = true;
              n.nmt_command_location = loc;
            }
          }
        }
        parse_node_options(node, cfg, n, w);
        parse_pdos(node, "tx_pdos", n, w, true);
        parse_pdos(node, "rx_pdos", n, w, false);
        parse_sdos(node, n, w);
        parse_sdo_variables(node, n, w);
        cfg.nodes.push_back(n);
        ++i;
      }
      // An empty list is a scan-only configuration, which needs the
      // diagnostics channel to be of any use.
      if (cfg.nodes.empty() && !cfg.master.has_diagnostics)
        error("", std::string("field 'nodes' lists no slave nodes (an empty list needs ") +
                      (version_ == 1 ? "master.diagnostics" : "a top-level 'diagnostics'") +
                      ", for a scan-only configuration)");
    }

    check_node_ids(cfg);
    resolve_auto_cob_ids(cfg);
    check_emcy_cob_ids(cfg);
    // A version 2 file checks the locations of all networks at once.
    if (version_ == 1) check_overlaps(cfg);
    check_sdo_overrides(cfg);
    check_sdo_variable_overrides(cfg);
    check_time_consumers(cfg);
    check_sync_needs(cfg);
    check_cyclic_axes(cfg);
  }

  // A cyclic CiA 402 axis needs one SYNC every PLC cycle: with the master's
  // timer, scan and SYNC drift and a set-point is applied twice or skipped.
  void check_cyclic_axes(const Config& cfg) {
    for (size_t i = 0; i < cfg.nodes.size(); ++i) {
      const NodeConfig& n = cfg.nodes[i];
      if (!n.axis_cyclic) continue;
      std::string w = "nodes[" + std::to_string(i) + "]";
      if (!cfg.master.sync_plc_cycle)
        error(w, n.label() + ": a cyclic CiA 402 axis needs SYNC from the PLC cycle (\"sync_source\": \"plc_cycle\")");
      else if (cfg.master.sync_cycles != 1)
        error(w, n.label() + ": a cyclic CiA 402 axis needs one SYNC every PLC cycle ('sync_cycles' 1, not " +
                     std::to_string(cfg.master.sync_cycles) + ")");
    }
  }

  // sync_source / sync_cycles; sync_period_us is already read.
  void parse_sync_source(const cJSON* master, MasterConfig& m) {
    const std::string w = "master";
    const cJSON* src = cJSON_GetObjectItemCaseSensitive(master, "sync_source");
    if (src) {
      std::string s = cJSON_IsString(src) ? src->valuestring : "";
      if (s == "plc_cycle")
        m.sync_plc_cycle = true;
      else if (s != "timer")
        error(w, "field 'sync_source' must be \"timer\" or \"plc_cycle\"");
    }
    uint64_t v;
    if (get_uint(master, "sync_cycles", w, false, 1000, v)) {
      if (v < 1) error(w, "field 'sync_cycles' must be 1-1000");
      m.has_sync_cycles = true;
      m.sync_cycles = v < 1 ? 1 : (unsigned)v;
      if (!m.sync_plc_cycle) error(w, "field 'sync_cycles' needs \"sync_source\": \"plc_cycle\"");
    }
    if (m.sync_plc_cycle && m.sync_period_us)
      error(w, "field 'sync_period_us' cannot be used with \"sync_source\": \"plc_cycle\": the SYNC period comes "
               "from the PLC cycle");
  }

  void parse_master_options(const cJSON* master, MasterConfig& m) {
    const std::string w = "master";
    uint64_t v;
    if (get_uint(master, "vendor_id", w, false, 0xFFFFFFFF, v)) m.has_vendor_id = true, m.vendor_id = (uint32_t)v;
    if (get_uint(master, "product_code", w, false, 0xFFFFFFFF, v))
      m.has_product_code = true, m.product_code = (uint32_t)v;
    if (get_uint(master, "revision_number", w, false, 0xFFFFFFFF, v))
      m.has_revision_number = true, m.revision_number = (uint32_t)v;
    if (get_uint(master, "serial_number", w, false, 0xFFFFFFFF, v))
      m.has_serial_number = true, m.serial_number = (uint32_t)v;
    if (get_uint(master, "sync_window_us", w, false, 0xFFFFFFFF, v))
      m.has_sync_window = true, m.sync_window_us = (unsigned)v;
    if (get_uint(master, "sync_counter_overflow", w, false, 240, v)) {
      if (v == 1) error(w, "field 'sync_counter_overflow' must be 0 (no counter) or 2-240");
      m.has_sync_counter_overflow = true;
      m.sync_counter_overflow = (unsigned)v;
    }
    if (get_uint(master, "time_cob_id", w, false, 0xFFFFFFFF, v)) m.has_time_cob_id = true, m.time_cob_id = (uint32_t)v;
    get_us100(master, "emcy_inhibit_time_us", w, m.has_emcy_inhibit_time, m.emcy_inhibit_time_us);
    get_bool(master, "heartbeat_consumer", w, m.heartbeat_consumer);
    if (get_number(master, "heartbeat_multiplier", w, 1.0, 100.0, m.heartbeat_multiplier))
      m.has_heartbeat_multiplier = true;
    get_error_behavior(master, w, m.error_behavior);
    get_us100(master, "nmt_inhibit_time_us", w, m.has_nmt_inhibit_time, m.nmt_inhibit_time_us);
    get_bool(master, "start", w, m.start);
    get_bool(master, "start_nodes", w, m.start_nodes);
    get_bool(master, "start_all_nodes", w, m.start_all_nodes);
    get_bool(master, "reset_all_nodes", w, m.reset_all_nodes);
    get_bool(master, "stop_all_nodes", w, m.stop_all_nodes);
    if (get_uint(master, "boot_time_ms", w, false, 0xFFFFFFFF, v)) m.has_boot_time = true, m.boot_time_ms = (unsigned)v;
    if (get_uint(master, "sdo_timeout_ms", w, false, 0xFFFFFFFF, v)) {
      if (v < 10 || v > 60000)
        error(w, "field 'sdo_timeout_ms' must be 10-60000: " + std::to_string(v));
      else
        m.sdo_timeout_ms = (unsigned)v;
    }
    if (get_uint(master, "time_period_ms", w, false, 0xFFFFFFFF, v)) {
      if (v < 100 || v > 3600000)
        error(w, "field 'time_period_ms' must be 100-3600000: " + std::to_string(v));
      else
        m.time_period_ms = (unsigned)v;
    }
    std::string stop;
    if (get_string(master, "on_plc_stop", w, false, stop)) {
      if (stop == "preop")
        m.on_plc_stop = OnPlcStop::Preop;
      else if (stop == "stop")
        m.on_plc_stop = OnPlcStop::Stop;
      else if (stop == "keep")
        m.on_plc_stop = OnPlcStop::Keep;
      else
        error(w, "field 'on_plc_stop' must be \"preop\", \"stop\" or \"keep\"");
    }
    if (get_uint(master, "scan_watchdog_ms", w, false, 0xFFFFFFFF, v)) {
      if (v != 0 && (v < 10 || v > 60000))
        error(w, "field 'scan_watchdog_ms' must be 0 or 10-60000: " + std::to_string(v));
      else
        m.scan_watchdog_ms = (unsigned)v;
    }
    if (version_ == 1)
      parse_diagnostics(master, m, "master");
    else if (cJSON_GetObjectItemCaseSensitive(master, "diagnostics"))
      error(w, "field 'diagnostics' is a top-level object in schema_version 2, not part of a network's master");
    if (!m.start)
      warning(w, "'start' is false: the master stays PRE-OPERATIONAL and no PDOs are exchanged "
                 "until it is started");
  }

  // `parent_where`: "master" in version 1, "" (the top level) in version 2.
  void parse_diagnostics(const cJSON* parent, MasterConfig& m, const std::string& parent_where) {
    const cJSON* d = cJSON_GetObjectItemCaseSensitive(parent, "diagnostics");
    if (!d) return;
    const std::string w = parent_where.empty() ? "diagnostics" : parent_where + ".diagnostics";
    if (!cJSON_IsObject(d)) {
      error(parent_where, "field 'diagnostics' must be an object");
      return;
    }
    // Set even when a field is wrong, so the empty-node-list check adds no
    // second error.
    m.has_diagnostics = true;
    if (cJSON_GetObjectItemCaseSensitive(d, "token_sha256")) {
      error(w + ".token_sha256",
            "the diagnostics channel is encrypted now and needs a 'token_verifier' instead: set the token again "
            "(configurator: Online access, Upgrade or New token; or canworks-diag hash-token)");
      return;
    }
    check_known(d, w, {"token_verifier", "port", "bind", "allow_changes", "allow_config_upload", "remote_link"});
    parse_remote_link(d, w);
    std::string text;
    if (get_string(d, "token_verifier", w, true, text)) {
      std::string why;
      if (!parse_scram_verifier(text, m.diag_scram, why)) error(w, "field 'token_verifier' " + why);
      m.diag_token_verifier = text;
    }
    uint64_t v;
    if (get_uint(d, "port", w, false, 65535, v)) {
      if (v < 1024) error(w, "field 'port' must be 1024-65535");
      m.diag_port = (unsigned)v;
    }
    std::string bind;
    if (get_string(d, "bind", w, false, bind)) {
      in_addr a;
      if (inet_pton(AF_INET, bind.c_str(), &a) != 1)
        error(w, "field 'bind' must be an IPv4 address such as 0.0.0.0 or 192.168.1.10");
      m.diag_bind = bind;
    }
    get_bool(d, "allow_changes", w, m.diag_allow_changes);
    get_bool(d, "allow_config_upload", w, m.diag_allow_config_upload);
  }

  // diagnostics.remote_link belongs to the canworks-link service on the
  // device (docs/remote-access.md): checked here so a wrong value is found at
  // upload, otherwise unused.
  void parse_remote_link(const cJSON* d, const std::string& parent_where) {
    const cJSON* rl = cJSON_GetObjectItemCaseSensitive(d, "remote_link");
    if (!rl) return;
    if (!cJSON_IsObject(rl)) {
      error(parent_where, "field 'remote_link' must be an object");
      return;
    }
    const std::string w = parent_where + ".remote_link";
    check_known(rl, w, {"internet", "relays", "pairing"});
    bool internet = false;
    get_bool(rl, "internet", w, internet);
    const cJSON* relays = cJSON_GetObjectItemCaseSensitive(rl, "relays");
    if (relays) {
      if (!cJSON_IsArray(relays)) {
        error(w, "field 'relays' must be an array of https URLs");
      } else {
        if (cJSON_GetArraySize(relays) > 8) error(w, "field 'relays' lists more than 8 relays");
        const cJSON* r;
        cJSON_ArrayForEach(r, relays) {
          if (!cJSON_IsString(r) || std::strncmp(r->valuestring, "https://", 8) != 0 || !r->valuestring[8]) {
            error(w, "relay URLs must use https, like https://relay.example.com");
            break;
          }
        }
      }
    }
    const cJSON* pairing = cJSON_GetObjectItemCaseSensitive(rl, "pairing");
    if (pairing && !(cJSON_IsString(pairing) && (std::strcmp(pairing->valuestring, "lan") == 0 ||
                                                 std::strcmp(pairing->valuestring, "anywhere") == 0 ||
                                                 std::strcmp(pairing->valuestring, "off") == 0)))
      error(w, "field 'pairing' must be lan, anywhere or off");
  }

  void parse_node_options(const cJSON* node, const Config& cfg, NodeConfig& n, const std::string& w) {
    uint64_t v;
    if (const cJSON* e = cJSON_GetObjectItemCaseSensitive(node, "emcy_cob_id")) {
      std::string s = cJSON_IsString(e) ? e->valuestring : "";
      bool ok = true;
      if (s == "device") {
        n.emcy_cob = NodeConfig::EmcyCob::Device;
      } else if (s == "eds") {
        n.emcy_cob = NodeConfig::EmcyCob::Eds;
      } else {
        uint64_t num = 0;
        if (cJSON_IsNumber(e)) {
          ok = e->valuedouble >= 0 && e->valuedouble == (double)(uint64_t)e->valuedouble;
          num = ok ? (uint64_t)e->valuedouble : 0;
        } else if (!s.empty() && s[0] != '-') {
          char* end = nullptr;
          num = std::strtoull(s.c_str(), &end, 0);
          ok = *end == '\0';
        } else {
          ok = false;
        }
        ok = ok && num <= 0xFFFFFFFFu;
        if (ok) {
          n.emcy_cob = NodeConfig::EmcyCob::Number;
          n.emcy_cob_config = static_cast<uint32_t>(num);
        }
      }
      if (!ok) error(w, n.label() + ": field 'emcy_cob_id' must be \"device\", \"eds\" or a COB-ID");
    }
    get_bool(node, "mandatory", w, n.mandatory);
    get_bool(node, "boot", w, n.boot);
    n.has_reset_communication = get_bool(node, "reset_communication", w, n.reset_communication);
    if (get_uint(node, "revision_number", w, false, 0xFFFFFFFF, v))
      n.has_revision_number = true, n.revision_number = (uint32_t)v;
    if (get_uint(node, "serial_number", w, false, 0xFFFFFFFF, v))
      n.has_serial_number = true, n.serial_number = (uint32_t)v;
    n.has_heartbeat_consumer = get_bool(node, "heartbeat_consumer", w, n.heartbeat_consumer);
    if (n.has_heartbeat_consumer && n.heartbeat_consumer && cfg.master.heartbeat_ms == 0)
      error(w, "'heartbeat_consumer' needs a master heartbeat (master 'heartbeat_ms' above 0)");
    if (get_uint(node, "retry_factor", w, false, 0xFF, v)) n.has_retry_factor = true, n.retry_factor = (unsigned)v;
    if (get_uint(node, "time_cob_id", w, false, 0xFFFFFFFF, v)) n.has_time_cob_id = true, n.time_cob_id = (uint32_t)v;
    get_error_behavior(node, w, n.error_behavior);
    if (get_uint(node, "restore_configuration", w, false, 0xFF, v))
      n.has_restore_configuration = true, n.restore_configuration = (unsigned)v;
    get_bool(node, "config_check", w, n.config_check);
    if (get_uint(node, "store_configuration", w, false, 0xFF, v)) {
      if (v < 1 || v > 127)
        error(w, n.label() + ": field 'store_configuration' must be a 0x1010 sub-index 1-127: " + std::to_string(v));
      else if (!n.config_check)
        error(w, n.label() + ": 'store_configuration' needs 'config_check', so the node saves only after a download");
      else
        n.has_store_configuration = true, n.store_configuration = (unsigned)v;
    }
    parse_lss(node, n, w);
    parse_axis(node, w, n);
    if (get_string(node, "software_file", w, false, n.software_file)) {
      std::vector<std::string> candidates;
      n.software_path = resolve_file(cfg, n.software_file, candidates);
      if (!is_file(n.software_path))
        error(w, n.label() + ": software_file \"" + n.software_file + "\" not found (looked at " +
                     n.software_path + ")");
    }
    if (get_uint(node, "software_version", w, false, 0xFFFFFFFF, v)) {
      n.has_software_version = true;
      n.software_version = (uint32_t)v;
      if (n.software_file.empty()) error(w, n.label() + ": 'software_version' needs 'software_file'");
    }
    if (!n.software_file.empty() && !n.has_software_version)
      warning(w, n.label() + ": 'software_file' without 'software_version': the master never downloads it");
  }

  void parse_lss(const cJSON* node, NodeConfig& n, const std::string& w) {
    const cJSON* lss = cJSON_GetObjectItemCaseSensitive(node, "lss");
    if (!lss) return;
    std::string lw = w + ": lss";
    if (!cJSON_IsObject(lss)) {
      error(w, "field 'lss' must be an object");
      return;
    }
    check_known(lss, lw, {"assign", "store"});
    get_bool(lss, "assign", lw, n.lss_assign);
    get_bool(lss, "store", lw, n.lss_store);
    if (n.lss_store && !n.lss_assign)
      error(w, n.label() + ": 'lss.store' needs 'lss.assign'");
    if (n.lss_assign && !n.has_serial_number)
      error(w, n.label() + ": LSS assignment ('lss.assign') needs 'serial_number'");
    if (n.lss_assign && !n.reset_communication)
      error(w, n.label() + ": 'lss.assign' needs 'reset_communication' true: a node ID set by LSS becomes active "
                           "only on a communication reset");
  }

  // A CiA 402 axis is for the PLC program (the editor's motion blocks); the
  // bus does nothing different, so only its form is checked here. A cyclic
  // axis gets its interpolation period written (canopen-cia402-axis
  // "Interpolation time period"), checked in check_cyclic_axes.
  void parse_axis(const cJSON* node, const std::string& w, NodeConfig& n) {
    const cJSON* axis = cJSON_GetObjectItemCaseSensitive(node, "axis");
    if (!axis) return;
    if (!cJSON_IsObject(axis)) {
      error(w, "field 'axis' must be an object");
      return;
    }
    std::string aw = w + ": axis";
    check_known(axis, aw, {"scale_numerator", "scale_denominator", "scale_factor", "cyclic",
                           "interpolation_period_us"});
    get_bool(axis, "cyclic", aw, n.axis_cyclic);
    uint64_t period;
    if (get_uint(axis, "interpolation_period_us", aw, false, 255000, period)) {
      uint8_t value;
      int8_t exponent;
      if (period < 100 || !interpolation_code((unsigned)period, value, exponent))
        error(aw, "field 'interpolation_period_us' " + std::to_string(period) +
                      " cannot be written to 0x60C2: it must be 1-255 times 1 ms, 100 us, 10 us or 1 us");
      else
        n.interpolation_period_us = (unsigned)period;
    }
    double v = 0;
    if (get_number(axis, "scale_numerator", aw, -2147483648.0, 2147483647.0, v)) {
      if (v != std::floor(v))
        error(aw, "field 'scale_numerator' must be an integer");
      else if (v == 0)
        error(aw, "field 'scale_numerator' must not be 0");
    }
    if (get_number(axis, "scale_denominator", aw, 1.0, 4294967295.0, v) && v != std::floor(v))
      error(aw, "field 'scale_denominator' must be an integer");
    if (get_number(axis, "scale_factor", aw, -DBL_MAX, DBL_MAX, v) && v == 0)
      error(aw, "field 'scale_factor' must not be 0");
  }

  void parse_adapter(const cJSON* root, AdapterConfig& a) {
    const cJSON* adapter = cJSON_GetObjectItemCaseSensitive(root, "adapter");
    bool old_iface = cJSON_GetObjectItemCaseSensitive(root, "interface") != nullptr;
    bool old_rate = cJSON_GetObjectItemCaseSensitive(root, "bitrate") != nullptr;
    if (adapter && (old_iface || old_rate)) {
      error("", std::string("give either 'adapter' or the deprecated top-level '") +
                    (old_iface ? "interface" : "bitrate") + "', not both");
      return;
    }
    const cJSON* src = root;
    std::string w;
    if (adapter) {
      w = "adapter";
      if (!cJSON_IsObject(adapter)) {
        error("", "field 'adapter' must be an object");
        return;
      }
      check_known(adapter, w,
                  {"type", "interface", "bitrate", "configure_link", "restart_ms", "device", "serial_baudrate", "simulate",
                   "listen_only"});
      get_bool(adapter, "simulate", w, a.simulate);
      get_bool(adapter, "listen_only", w, a.listen_only);
      if (!get_string(adapter, "type", w, true, a.type)) return;
      if (a.type != "socketcan" && a.type != "slcan") {
        error(w, "adapter type \"" + a.type + "\" is not supported (supported: socketcan, slcan)");
        return;
      }
      // Fields of the other type are an error, not ignored: they would
      // silently not do what the user expects.
      static const char* const kSocketcanOnly[] = {"configure_link", "restart_ms"};
      static const char* const kSlcanOnly[] = {"device", "serial_baudrate"};
      const char* const* other = a.type == "slcan" ? kSocketcanOnly : kSlcanOnly;
      for (int i = 0; i < 2; ++i)
        if (cJSON_GetObjectItemCaseSensitive(adapter, other[i]))
          error(w, std::string("field '") + other[i] + "' does not apply to adapter type " + a.type);
      src = adapter;
    } else if (old_iface || old_rate) {
      warning("", "top-level 'interface' and 'bitrate' are deprecated; move them into "
                  "\"adapter\": {\"type\": \"socketcan\", ...}");
      // Same meaning as before the contract: the plugin did not touch the link.
      a.configure_link = false;
    } else {
      error("", "missing required field 'adapter'");
      return;
    }
    if (get_string(src, "interface", w, true, a.interface) && !valid_interface_name(a.interface))
      error(w, "interface \"" + a.interface + "\" must be 1-15 characters of letters, digits, '_', '.', ':' and '-' "
               "(the 15-character limit of Linux interface names)");
    uint64_t v;
    if (get_uint(src, "bitrate", w, true, 1000000, v)) {
      static const unsigned rates[] = {10000, 20000, 50000, 125000, 250000, 500000, 800000, 1000000};
      bool ok = false;
      for (unsigned r : rates) ok |= (r == v);
      if (!ok) error(w, "field 'bitrate' must be a CiA 301 bit rate (10000 ... 1000000): " + std::to_string(v));
      a.bitrate = (unsigned)v;
    }
    if (adapter && a.type == "slcan") {
      if (get_string(adapter, "device", w, true, a.device) && a.device[0] != '/')
        error(w, "field 'device' must be an absolute path such as /dev/ttyACM0");
      if (get_uint(adapter, "serial_baudrate", w, false, 4000000, v)) {
        if (v == 0) error(w, "field 'serial_baudrate' must be 1 or higher");
        a.serial_baudrate = (unsigned)v;
      }
    } else if (adapter) {
      get_bool(adapter, "configure_link", w, a.configure_link);
      if (get_uint(adapter, "restart_ms", w, false, 0xFFFFFFFF, v)) {
        a.restart_ms = (unsigned)v;
        a.has_restart_ms = true;
      }
    }
  }

  void resolve_eds(const Config& cfg, NodeConfig& n) { n.eds_path = resolve_file(cfg, n.eds, n.eds_candidates); }

  // A file named in the JSON: an absolute path as is; a relative one against
  // the config file's directory, then the runtime's generated conf/ folder.
  // The first that exists, else the first candidate.
  std::string resolve_file(const Config& cfg, const std::string& name, std::vector<std::string>& candidates) {
    candidates.clear();
    if (name[0] == '/') {
      candidates.push_back(name);
    } else {
      candidates.push_back(cfg.config_dir.empty() ? name : cfg.config_dir + "/" + name);
      if (!eds_fallback_dir_.empty()) candidates.push_back(eds_fallback_dir_ + "/" + name);
    }
    for (const auto& c : candidates)
      if (is_file(c)) return c;
    return candidates[0];
  }

  // Reads a startup SDO value and checks that it fits the type.
  bool sdo_value(const cJSON* item, StartupSdo& sdo, std::string& why) {
    char* text = cJSON_PrintUnformatted(item);
    sdo.value_text = text ? text : "?";
    cJSON_free(text);
    if (sdo.value_text.size() >= 2 && sdo.value_text.front() == '"')
      sdo.value_text = sdo.value_text.substr(1, sdo.value_text.size() - 2);
    unsigned bits = co_type_bits(sdo.type);
    unsigned bytes = bits == 1 ? 1 : bits / 8;
    if (sdo.type == CoType::REAL32 || sdo.type == CoType::REAL64) {
      if (!cJSON_IsNumber(item) || !std::isfinite(item->valuedouble)) {
        why = "must be a number";
        return false;
      }
      if (sdo.type == CoType::REAL32) {
        if (std::fabs(item->valuedouble) > FLT_MAX) {
          why = "does not fit REAL32";
          return false;
        }
        float f = (float)item->valuedouble;
        uint32_t u;
        std::memcpy(&u, &f, 4);
        sdo.data = le_bytes(u, 4);
      } else {
        uint64_t u;
        std::memcpy(&u, &item->valuedouble, 8);
        sdo.data = le_bytes(u, 8);
      }
      return true;
    }
    bool is_signed = sdo.type == CoType::INTEGER8 || sdo.type == CoType::INTEGER16 ||
                     sdo.type == CoType::INTEGER32 || sdo.type == CoType::INTEGER64;
    // The value as a signed 128-bit-ish pair: negative flag and magnitude.
    bool neg = false;
    uint64_t mag = 0;
    if (cJSON_IsBool(item)) {
      mag = cJSON_IsTrue(item) ? 1 : 0;
    } else if (cJSON_IsNumber(item)) {
      double d = item->valuedouble;
      if (d != std::floor(d) || std::fabs(d) >= 18446744073709551616.0) {
        why = "is not an integer";
        return false;
      }
      neg = d < 0;
      mag = (uint64_t)std::fabs(d);
    } else if (cJSON_IsString(item) && item->valuestring[0]) {
      const char* s = item->valuestring;
      neg = *s == '-';
      if (neg) ++s;
      char* end = nullptr;
      errno = 0;
      mag = std::strtoull(s, &end, 0);
      if (*s == '-' || *s == '+' || *end != '\0' || errno == ERANGE) {
        why = "is not a valid integer";
        return false;
      }
    } else {
      why = "must be a number";
      return false;
    }
    bool fits;
    if (sdo.type == CoType::BOOLEAN) {
      fits = !neg && mag <= 1;
    } else if (is_signed) {
      uint64_t max_pos = (uint64_t(1) << (bits - 1)) - 1;
      fits = neg ? mag <= max_pos + 1 : mag <= max_pos;
    } else {
      fits = !neg && (bits == 64 || mag <= (uint64_t(1) << bits) - 1);
    }
    if (!fits) {
      why = std::string("does not fit ") + co_type_name(sdo.type);
      return false;
    }
    sdo.data = le_bytes(neg ? uint64_t(0) - mag : mag, bytes);
    return true;
  }

  void parse_sdos(const cJSON* node, NodeConfig& n, const std::string& where) {
    const cJSON* arr = cJSON_GetObjectItemCaseSensitive(node, "sdo");
    if (!arr) return;
    if (!cJSON_IsArray(arr)) {
      error(where, "field 'sdo' must be an array");
      return;
    }
    int i = 0;
    const cJSON* item;
    cJSON_ArrayForEach(item, arr) {
      std::string sw = where + ": sdo[" + std::to_string(i++) + "]";
      if (!cJSON_IsObject(item)) {
        error(sw, "must be an object");
        continue;
      }
      check_known(item, sw, {"index", "subindex", "type", "value"});
      StartupSdo sdo;
      uint64_t v;
      bool ok = true;
      if (get_uint(item, "index", sw, true, 0xFFFF, v)) sdo.index = (uint16_t)v; else ok = false;
      if (get_uint(item, "subindex", sw, false, 0xFF, v)) sdo.subindex = (uint8_t)v;
      std::string type;
      if (get_string(item, "type", sw, true, type)) {
        if (!parse_co_type(type, sdo.type)) {
          error(sw, "unsupported type \"" + type +
                        "\" (use BOOLEAN, INTEGER8/16/32/64, UNSIGNED8/16/32/64, REAL32, REAL64)");
          ok = false;
        }
      } else {
        ok = false;
      }
      const cJSON* value = cJSON_GetObjectItemCaseSensitive(item, "value");
      if (!value) {
        error(sw, "missing required field 'value'");
        ok = false;
      }
      if (!ok) continue;
      std::string why;
      if (!sdo_value(value, sdo, why)) {
        char obj[64];
        std::snprintf(obj, sizeof(obj), "node %u, index 0x%04X, subindex %u", n.node_id, sdo.index, sdo.subindex);
        error(sw, std::string(obj) + ": value " + sdo.value_text + " " + why);
        continue;
      }
      n.sdos.push_back(sdo);
    }
  }

  // One location of a given area and size for an SDO variable field.
  bool sdo_var_location(const cJSON* item, const char* key, const std::string& where, const NodeConfig& n,
                        const SdoVariable& sv, IecArea area, int size, const char* what, IecLocation& out) {
    if (!cJSON_GetObjectItemCaseSensitive(item, key)) return false;
    IecLocation loc;
    if (!get_location(item, key, where, false, loc)) return false;
    if (loc.area != area || (size && loc.size != static_cast<IecSize>(size))) {
      error(where, n.label() + ", " + sv.label() + ": " + key + " must be " + what + ", not " + loc.str());
      return false;
    }
    out = loc;
    return true;
  }

  void parse_sdo_variables(const cJSON* node, NodeConfig& n, const std::string& where) {
    const cJSON* arr = cJSON_GetObjectItemCaseSensitive(node, "sdo_variables");
    if (!arr) return;
    if (!cJSON_IsArray(arr)) {
      error(where, "field 'sdo_variables' must be an array");
      return;
    }
    int i = 0;
    const cJSON* item;
    cJSON_ArrayForEach(item, arr) {
      std::string vw = where + ": sdo_variables[" + std::to_string(i++) + "]";
      if (!cJSON_IsObject(item)) {
        error(vw, "must be an object");
        continue;
      }
      check_known(item, vw, {"name", "index", "subindex", "type", "direction", "iec_location", "period_ms",
                             "trigger_location", "status_location", "abort_code_location", "timeout_ms"});
      SdoVariable sv;
      uint64_t v;
      bool ok = true;
      get_string(item, "name", vw, false, sv.name);
      if (get_uint(item, "index", vw, true, 0xFFFF, v)) sv.index = (uint16_t)v; else ok = false;
      if (get_uint(item, "subindex", vw, false, 0xFF, v)) sv.subindex = (uint8_t)v;
      std::string text;
      if (get_string(item, "type", vw, true, text)) {
        if (!parse_co_type(text, sv.type)) {
          error(vw, "unsupported type \"" + text +
                        "\" (use BOOLEAN, INTEGER8/16/32/64, UNSIGNED8/16/32/64, REAL32, REAL64)");
          ok = false;
        }
      } else {
        ok = false;
      }
      if (get_string(item, "direction", vw, true, text)) {
        if (text == "read") {
          sv.direction = SdoDirection::Read;
        } else if (text == "write") {
          sv.direction = SdoDirection::Write;
        } else {
          error(vw, "field 'direction' must be \"read\" or \"write\", not \"" + text + "\"");
          ok = false;
        }
      } else {
        ok = false;
      }
      if (get_location(item, "iec_location", vw, true, sv.location)) {
        if (ok) {
          IecArea want = sv.is_read() ? IecArea::Input : IecArea::Output;
          if (sv.location.area != want) {
            error(vw, n.label() + ", " + sv.label() + ": " +
                          (sv.is_read() ? "a read entry needs an input location (%I...), not "
                                        : "a write entry needs an output location (%Q...), not ") +
                          sv.location.str());
            ok = false;
          } else if (!co_type_fits(sv.type, sv.location.size)) {
            error(vw, n.label() + ", " + sv.label() + ": type " + co_type_name(sv.type) + " (" +
                          std::to_string(co_type_bits(sv.type)) + " bit) does not fit location " +
                          sv.location.str() + " (" + std::to_string(iec_size_bits(sv.location.size)) + " bit)");
            ok = false;
          }
        }
      } else {
        ok = false;
      }
      if (get_uint(item, "period_ms", vw, false, 0xFFFFFFFF, v)) {
        if (!sv.is_read())
          error(vw, n.label() + ", " + sv.label() + ": field 'period_ms' is only for read entries"), ok = false;
        else if (v < 10)
          error(vw, n.label() + ", " + sv.label() + ": field 'period_ms' must be 10 or more: " + std::to_string(v)),
              ok = false;
        sv.period_ms = (unsigned)v;
      }
      if (get_uint(item, "timeout_ms", vw, false, 0xFFFFFFFF, v)) {
        if (v < 10 || v > 60000)
          error(vw, n.label() + ", " + sv.label() + ": field 'timeout_ms' must be 10-60000: " + std::to_string(v)),
              ok = false;
        sv.timeout_ms = (unsigned)v;
      }
      sv.has_trigger = sdo_var_location(item, "trigger_location", vw, n, sv, IecArea::Output, 'X',
                                        "an output bit (%QX...)", sv.trigger_location);
      sv.has_status = sdo_var_location(item, "status_location", vw, n, sv, IecArea::Input, 'B',
                                       "an input byte (%IB...)", sv.status_location);
      sv.has_abort_code = sdo_var_location(item, "abort_code_location", vw, n, sv, IecArea::Input, 'D',
                                           "an input double word (%ID...)", sv.abort_code_location);
      if (ok) n.sdo_variables.push_back(sv);
    }
  }

  // TIME produced but no configured node set to consume it (bit 31 of its
  // time_cob_id). Only a warning: a device may consume TIME by its EDS default.
  // Without a SYNC period or PLC-cycle SYNC the master produces no SYNC, so settings that only
  // act on SYNC would never take effect. A PDO's transmission type from the
  // EDS is checked with the EDS (eds_check.cpp).
  // An optional output location of one size (%QW or %QB).
  void get_output_location(const cJSON* obj, const char* key, const std::string& where, IecSize size, bool& has,
                           IecLocation& out) {
    if (!cJSON_GetObjectItemCaseSensitive(obj, key)) return;
    IecLocation loc;
    if (!get_location(obj, key, where, false, loc)) return;
    if (loc.area != IecArea::Output || loc.size != size) {
      error(where, std::string(key) + (size == IecSize::B ? " must be an output byte (%QB...), not "
                                                           : " must be an output word (%QW...), not ") +
                       loc.str());
      return;
    }
    has = true;
    out = loc;
  }

  // A version 2 network with "role": "slave" (canopen-slave-device spec).
  void parse_slave_network(const cJSON* net, Config& cfg) {
    parse_adapter(net, cfg.adapter);
    if (limits_.force_simulate) {
      cfg.adapter.simulate = true;
      cfg.adapter.simulation_forced = true;
    }
    for (const char* key : {"master", "nodes"})
      if (cJSON_GetObjectItemCaseSensitive(net, key))
        error("", std::string("field '") + key +
                      "' belongs to a master network; a slave network (\"role\": \"slave\") has 'adapter' and "
                      "'slave' only");
    const cJSON* sl = cJSON_GetObjectItemCaseSensitive(net, "slave");
    if (!sl || !cJSON_IsObject(sl)) {
      error("", "missing required field 'slave' (an object) for a slave network");
      return;
    }
    const std::string w = "slave";
    SlaveConfig& s = cfg.slave;
    check_known(sl, w, {"node_id", "eds", "objects", "inputs_on_loss", "state_location", "comm_ok_location",
                        "sync_count_location", "emcy_code_location", "error_register_location", "eds_lint"});
    uint64_t v;
    const cJSON* id = cJSON_GetObjectItemCaseSensitive(sl, "node_id");
    if (!id) {
      error(w, "missing required field 'node_id' (1-127, or null to get it over LSS)");
    } else if (cJSON_IsNull(id)) {
      s.lss = true;
    } else if (get_uint(sl, "node_id", w, true, 0xFFFF, v)) {
      if (v < 1 || v > 127) error(w, "node ID " + std::to_string(v) + " is out of range (1-127, or null for LSS)");
      s.node_id = (unsigned)v;
    }
    if (get_string(sl, "eds", w, true, s.eds)) s.eds_path = resolve_file(cfg, s.eds, s.eds_candidates);
    std::string text;
    if (get_string(sl, "inputs_on_loss", w, false, text)) {
      if (text == "zero")
        s.inputs_on_loss_zero = true;
      else if (text != "hold")
        error(w, "field 'inputs_on_loss' must be \"hold\" or \"zero\", not \"" + text + "\"");
    }
    if (get_string(sl, "eds_lint", w, false, text)) {
      if (text == "communication" || text == "all" || text == "off")
        s.eds_lint = text;
      else
        error(w, "field 'eds_lint' must be \"communication\", \"all\" or \"off\"");
    }
    get_input_location(sl, "state_location", w, IecSize::B, s.has_state_location, s.state_location);
    if (cJSON_GetObjectItemCaseSensitive(sl, "comm_ok_location")) {
      IecLocation loc;
      if (get_location(sl, "comm_ok_location", w, false, loc)) {
        if (loc.area != IecArea::Input || loc.size != IecSize::X) {
          error(w, "comm_ok_location must be an input bit (%IX...), not " + loc.str());
        } else {
          s.has_comm_ok_location = true;
          s.comm_ok_location = loc;
        }
      }
    }
    get_input_location(sl, "sync_count_location", w, IecSize::W, s.has_sync_count_location, s.sync_count_location);
    get_output_location(sl, "emcy_code_location", w, IecSize::W, s.has_emcy_code_location, s.emcy_code_location);
    get_output_location(sl, "error_register_location", w, IecSize::B, s.has_error_register_location,
                        s.error_register_location);
    const cJSON* objs = cJSON_GetObjectItemCaseSensitive(sl, "objects");
    if (objs && !cJSON_IsArray(objs)) {
      error(w, "field 'objects' must be an array");
    } else if (objs) {
      std::set<uint32_t> seen;
      int i = 0;
      const cJSON* o;
      cJSON_ArrayForEach(o, objs) {
        std::string ow = w + ": objects[" + std::to_string(i++) + "]";
        if (!cJSON_IsObject(o)) {
          error(ow, "must be an object");
          continue;
        }
        check_known(o, ow, {"index", "subindex", "iec_location", "name"});
        SlaveObject so;
        bool ok = true;
        if (get_uint(o, "index", ow, true, 0xFFFF, v)) so.index = (uint16_t)v; else ok = false;
        if (get_uint(o, "subindex", ow, false, 0xFF, v)) so.subindex = (uint8_t)v;
        get_string(o, "name", ow, false, so.name);
        if (!get_location(o, "iec_location", ow, true, so.location)) ok = false;
        if (!ok) continue;
        if (!seen.insert(uint32_t(so.index) << 8 | so.subindex).second) {
          error(ow, so.label() + " is bound twice");
          continue;
        }
        s.objects.push_back(so);
      }
    }
  }

  // The top-level gateway section (canopen-gateway spec). The checks that
  // need the EDS files (slave object access and types) are in
  // check_gateway_eds().
  void parse_gateway(const cJSON* root, ConfigSet& set) {
    const cJSON* gw = cJSON_GetObjectItemCaseSensitive(root, "gateway");
    if (!gw) return;
    const std::string w = "gateway";
    if (!cJSON_IsObject(gw)) {
      error(w, "must be an object");
      return;
    }
    check_known(gw, w, {"upper", "routes", "status", "emcy_forward", "on_upper_loss", "sdo_bridge",
                        "sdo_bridge_index", "sdo_bridge_write"});
    GatewayConfig& g = set.gateway;
    auto find = [&set](const std::string& name) -> int {
      for (const auto& c : set.networks)
        if (lower(c.network) == lower(name)) return (int)c.network_index;
      return -1;
    };
    std::string upper;
    if (!get_string(gw, "upper", w, true, upper)) return;
    int up = find(upper);
    if (up < 0) {
      error(w, "upper network \"" + upper + "\" is not in 'networks'");
      return;
    }
    if (!set.networks[up].is_slave()) {
      error(w, "upper network \"" + upper + "\" must be a slave network (\"role\": \"slave\"); it is a " +
                   (set.networks[up].is_j1939()   ? "J1939 network"
                    : set.networks[up].is_plain() ? "plain CAN network"
                                                  : "master network"));
      return;
    }
    g.enabled = true;
    g.upper = (unsigned)up;
    const Config& upc = set.networks[up];
    for (const auto& c : set.networks)
      if (!c.is_slave() && c.adapter.simulate && upc.adapter.simulate && c.adapter.interface == upc.adapter.interface)
        g.upper_master = (int)c.network_index;
    bool any_master = false;
    for (const auto& c : set.networks) any_master |= g.is_field(c);
    if (!any_master) error(w, "a gateway needs at least one master network (its field network) besides \"" + upper + "\"" +
                                  (g.upper_master >= 0 ? " and the upper master's stand-in \"" +
                                                             set.networks[g.upper_master].network + "\""
                                                       : ""));
    get_bool(gw, "emcy_forward", w, g.emcy_forward);
    get_bool(gw, "sdo_bridge", w, g.sdo_bridge);
    get_bool(gw, "sdo_bridge_write", w, g.sdo_bridge_write);
    if (g.sdo_bridge_write && !g.sdo_bridge) warning(w, "'sdo_bridge_write' has no effect without 'sdo_bridge'");
    uint64_t v;
    if (get_uint(gw, "sdo_bridge_index", w, false, 0xFFFF, v)) {
      if (v < 0x2000 || v > 0x5FFF) error(w, "field 'sdo_bridge_index' must be in the manufacturer area 0x2000-0x5FFF");
      g.sdo_bridge_index = (uint16_t)v;
    }
    std::string loss;
    if (get_string(gw, "on_upper_loss", w, false, loss)) {
      if (loss == "hold")
        g.on_upper_loss = GatewayConfig::UpperLoss::Hold;
      else if (loss == "zero")
        g.on_upper_loss = GatewayConfig::UpperLoss::Zero;
      else if (loss == "stop_nodes")
        g.on_upper_loss = GatewayConfig::UpperLoss::StopNodes;
      else
        error(w, "field 'on_upper_loss' must be \"hold\", \"zero\" or \"stop_nodes\", not \"" + loss + "\"");
    }
    const cJSON* st = cJSON_GetObjectItemCaseSensitive(gw, "status");
    if (st) {
      if (!cJSON_IsObject(st)) {
        error(w, "field 'status' must be an object, e.g. {\"index\": \"0x5E00\"}");
      } else {
        check_known(st, w + ": status", {"index"});
        g.has_status = true;
        if (get_uint(st, "index", w + ": status", false, 0xFFFF, v)) {
          if (v < 0x2000 || v > 0x5FEF) error(w + ": status", "field 'index' must be in 0x2000-0x5FEF");
          g.status_index = (uint16_t)v;
        }
      }
    }
    const cJSON* routes = cJSON_GetObjectItemCaseSensitive(gw, "routes");
    if (routes && !cJSON_IsArray(routes)) {
      error(w, "field 'routes' must be an array");
      return;
    }
    std::map<uint32_t, unsigned> slave_ends;
    std::map<std::string, unsigned> field_ends;
    int i = 0;
    const cJSON* r;
    cJSON_ArrayForEach(r, routes) {
      std::string rw = w + ": routes[" + std::to_string(i) + "]";
      RouteConfig rc;
      rc.number = (unsigned)++i;
      if (!cJSON_IsObject(r)) {
        error(rw, "must be an object");
        continue;
      }
      check_known(r, rw, {"slave", "field", "name"});
      get_string(r, "name", rw, false, rc.name);
      const cJSON* se = cJSON_GetObjectItemCaseSensitive(r, "slave");
      const cJSON* fe = cJSON_GetObjectItemCaseSensitive(r, "field");
      if (!cJSON_IsObject(se) || !cJSON_IsObject(fe)) {
        error(rw, "a route needs 'slave' ({index, subindex}) and 'field' ({network, node, index, subindex})");
        continue;
      }
      std::string sw = rw + ": slave", fw = rw + ": field";
      check_known(se, sw, {"index", "subindex"});
      check_known(fe, fw, {"network", "node", "index", "subindex"});
      bool ok = true;
      if (get_uint(se, "index", sw, true, 0xFFFF, v)) rc.slave_index = (uint16_t)v; else ok = false;
      if (get_uint(se, "subindex", sw, false, 0xFF, v)) rc.slave_subindex = (uint8_t)v;
      if (get_uint(fe, "node", fw, true, 127, v)) rc.node = (unsigned)v; else ok = false;
      if (get_uint(fe, "index", fw, true, 0xFFFF, v)) rc.index = (uint16_t)v; else ok = false;
      if (get_uint(fe, "subindex", fw, false, 0xFF, v)) rc.subindex = (uint8_t)v;
      std::string fnet;
      if (!get_string(fe, "network", fw, true, fnet)) ok = false;
      if (!ok) continue;
      int fn = find(fnet);
      if (fn < 0) {
        error(fw, "network \"" + fnet + "\" is not in 'networks'");
        continue;
      }
      const Config& field = set.networks[fn];
      if (!field.is_canopen() || field.is_slave()) {
        error(fw, "network \"" + fnet + "\" is a " +
                      (field.is_j1939() ? "J1939" : field.is_plain() ? "plain CAN" : "slave") +
                      " network; a route's field end is on a CANopen master network");
        continue;
      }
      if ((int)fn == g.upper_master) {
        error(fw, "network \"" + fnet + "\" shares the upper network's simulated bus: it stands in for the upper "
                  "master and is not a field network");
        continue;
      }
      rc.field_network = (unsigned)fn;
      const NodeConfig* node = nullptr;
      for (const auto& n : field.nodes)
        if (n.node_id == rc.node) node = &n;
      char obj[32];
      std::snprintf(obj, sizeof(obj), "0x%04X:%u", rc.index, rc.subindex);
      if (!node) {
        error(fw, "node " + std::to_string(rc.node) + " is not configured on network \"" + field.network + "\"");
        continue;
      }
      const PdoEntry* entry = nullptr;
      for (bool tx : {true, false})
        for (const auto& p : tx ? node->tx_pdos : node->rx_pdos)
          for (const auto& e : p.entries)
            if (!entry && e.index == rc.index && e.subindex == rc.subindex) {
              entry = &e;
              rc.up = tx;
            }
      if (!entry) {
        error(fw, node->label() + " on network \"" + field.network + "\" has no PDO entry " + obj +
                      " (a route's field end must be an entry of its tx_pdos or rx_pdos)");
        continue;
      }
      rc.type = entry->type;
      char skey[32];
      std::snprintf(skey, sizeof(skey), "0x%04X:%u", rc.slave_index, rc.slave_subindex);
      auto sdup = slave_ends.find(uint32_t(rc.slave_index) << 8 | rc.slave_subindex);
      if (sdup != slave_ends.end()) {
        error(rw, rc.label() + " and route " + std::to_string(sdup->second) + " both use slave object " + skey);
        continue;
      }
      slave_ends[uint32_t(rc.slave_index) << 8 | rc.slave_subindex] = rc.number;
      std::string fkey = std::to_string(fn) + "/" + std::to_string(rc.node) + "/" + obj;
      auto fdup = field_ends.find(fkey);
      if (fdup != field_ends.end() && !rc.up) {
        error(rw, rc.label() + " and route " + std::to_string(fdup->second) + " both write " + node->label() + " " +
                      obj + " on network \"" + field.network + "\"");
        continue;
      }
      field_ends[fkey] = rc.number;
      // One writer per object: the route writes a field RPDO entry, so the
      // PLC must not (an input on a TPDO entry is fine: the PLC only reads).
      if (!rc.up && entry->has_location)
        error(rw, rc.label() + " writes " + node->label() + " RPDO entry " + obj + " on network \"" + field.network +
                      "\", which also has " + entry->location.str() + "; only one of them may write it (remove the "
                      "entry's iec_location)");
      g.routes.push_back(rc);
    }
  }

  // PDO entries without iec_location: allowed only when a route uses them.
  void report_unlocated(const ConfigSet& set) {
    for (const auto& u : unlocated_) {
      bool routed = false;
      for (const auto& r : set.gateway.routes)
        routed |= r.field_network == u.network && r.node == u.node && r.index == u.index && r.subindex == u.subindex;
      if (!routed)
        errors_.push_back(path_ + ": " + u.where +
                          ": missing required field 'iec_location' (only an entry a gateway route uses may leave it "
                          "out)");
    }
    unlocated_.clear();
  }

  void check_sync_needs(const Config& cfg) {
    if (cfg.master.produces_sync()) return;
    const char* why =
        "' needs 'sync_period_us' or \"sync_source\": \"plc_cycle\" (without them the master produces no SYNC)";
    if (cfg.master.has_sync_window) error("master", std::string("field 'sync_window_us") + why);
    if (cfg.master.has_sync_counter_overflow) error("master", std::string("field 'sync_counter_overflow") + why);
    for (size_t i = 0; i < cfg.nodes.size(); ++i) {
      const NodeConfig& n = cfg.nodes[i];
      for (int tx = 1; tx >= 0; --tx) {
        const auto& pdos = tx ? n.tx_pdos : n.rx_pdos;
        for (size_t j = 0; j < pdos.size(); ++j) {
          const PdoConfig& p = pdos[j];
          std::string pw = "nodes[" + std::to_string(i) + "]." + (tx ? "tx_pdos[" : "rx_pdos[") + std::to_string(j) + "]";
          std::string what = n.label() + (tx ? " TPDO " : " RPDO ") + std::to_string(p.number);
          if (p.has_transmission && transmission_needs_sync(p.transmission))
            error(pw, what + ": " + sync_needed_message(p.transmission, false));
          if (p.has_sync_start) error(pw, what + ": field 'sync_start" + why);
        }
      }
    }
  }

  void check_time_consumers(const Config& cfg) {
    if (!cfg.master.time_period_ms) return;
    for (const auto& n : cfg.nodes)
      if (n.has_time_cob_id && (n.time_cob_id & 0x80000000u)) return;
    warning("master", "the master produces TIME, but no configured node is set to consume it (time_cob_id with "
                      "bit 31)");
  }

  // A write entry to an object the plugin sets up from the node's settings
  // lets the program override that setting.
  void check_sdo_variable_overrides(const Config& cfg) {
    for (const auto& n : cfg.nodes)
      for (const auto& sv : n.sdo_variables) {
        const char* what = sv.is_read() ? nullptr : plugin_owned_object(sv.index);
        if (!what) continue;
        warning(n.label(), sv.label() + " writes an object the plugin configures itself; the program can override " +
                               what);
      }
  }

  // "auto" COB-IDs above PDO 4: the highest COB-ID in 0x181-0x57F that is
  // not in any configured node's predefined set and not used by another PDO.
  // Resolved in config order, so the result is stable for an unchanged file.
  void resolve_auto_cob_ids(Config& cfg) {
    std::set<uint32_t> taken;
    for (const auto& n : cfg.nodes) {
      if (n.node_id < 1 || n.node_id > 127) continue;
      for (uint32_t base = 0x180; base <= 0x500; base += 0x80) taken.insert(base + n.node_id);
      for (const auto& p : n.tx_pdos)
        if (!p.cob_auto || p.number <= 4) taken.insert(n.tpdo_cob_id(p));
      for (const auto& p : n.rx_pdos)
        if (!p.cob_auto || p.number <= 4) taken.insert(n.rpdo_cob_id(p));
    }
    for (auto& n : cfg.nodes)
      for (int tx = 1; tx >= 0; --tx)
        for (auto& p : tx ? n.tx_pdos : n.rx_pdos) {
          if (!p.cob_auto || p.number <= 4) continue;
          uint32_t cob = 0x57F;
          while (cob > 0x180 && taken.count(cob)) --cob;
          if (cob == 0x180) {
            error("nodes", n.label() + (tx ? " TPDO " : " RPDO ") + std::to_string(p.number) +
                               ": no free COB-ID left for \"auto\"");
            continue;
          }
          taken.insert(cob);
          p.cob_id = cob;
          char hex[16];
          std::snprintf(hex, sizeof(hex), "0x%03X", cob);
          cfg.notes.push_back(n.label() + (tx ? " TPDO " : " RPDO ") + std::to_string(p.number) +
                              ": automatic COB-ID " + hex);
        }
  }

  // The configured EMCY COB-IDs (emcy_cob_id numbers, else a startup SDO to
  // 0x1014 sub-index 0) and the checks of canopen-node-supervision "EMCY
  // COB-ID setting": run after the "auto" PDO COB-IDs are resolved.
  void check_emcy_cob_ids(Config& cfg) {
    for (auto& n : cfg.nodes) {
      if (n.emcy_cob == NodeConfig::EmcyCob::Number) continue;
      for (const auto& s : n.sdos) {
        if (s.index != 0x1014 || s.subindex != 0) continue;
        uint64_t v = 0;
        for (size_t b = 0; b < s.data.size() && b < 8; ++b) v |= uint64_t(s.data[b]) << (8 * b);
        // A value with bit 31 switches the device's EMCY off (or is the first
        // step of moving it): not a COB-ID to listen on.
        n.emcy_cob_from_sdo = !(v & 0x80000000u);
        n.emcy_cob_config = n.emcy_cob_from_sdo ? static_cast<uint32_t>(v) : 0;
      }
    }
    for (size_t i = 0; i < cfg.nodes.size(); ++i) {
      const NodeConfig& n = cfg.nodes[i];
      if (n.emcy_cob != NodeConfig::EmcyCob::Number && !n.emcy_cob_from_sdo) continue;
      std::string msg = emcy_cob_problem(cfg, n);
      if (!msg.empty()) error("nodes[" + std::to_string(i) + "]", n.label() + ": " + msg);
    }
  }

  // Why a node's configured EMCY COB-ID cannot be used, or "".
  static std::string emcy_cob_problem(const Config& cfg, const NodeConfig& n) {
    uint32_t v = n.emcy_cob_config;
    char buf[96];
    if (n.emcy_cob == NodeConfig::EmcyCob::Number && (v & 0x80000000u)) {
      std::snprintf(buf, sizeof buf, "emcy_cob_id 0x%08X has bit 31 set (EMCY not valid); ", v);
      return std::string(buf) + "give the COB-ID the device sends on";
    }
    if (n.emcy_cob == NodeConfig::EmcyCob::Number)
      std::snprintf(buf, sizeof buf, v > 0x7FF ? "emcy_cob_id 0x%X" : "emcy_cob_id 0x%03X", v);
    else
      std::snprintf(buf, sizeof buf,
                    v > 0x7FF ? "EMCY COB-ID 0x%X from the startup SDO to 0x1014" : "EMCY COB-ID 0x%03X from the startup SDO to 0x1014", v);
    std::string what = buf;
    if (v > 0x7FF) return what + " is not an 11-bit CAN-ID (29-bit EMCY COB-IDs are not supported)";
    if (restricted_can_id(v)) return what + " is a restricted CAN-ID (CiA 301)";
    std::string who = emcy_cob_clash(cfg, n, v, nullptr);
    if (!who.empty()) return what + " clashes with " + who;
    return "";
  }

  // A startup SDO runs after everything the plugin writes from the node's
  // settings, so writing one of those objects overrides that setting (a
  // supervision object written with the same value is harmless).
  void check_sdo_overrides(const Config& cfg) {
    for (const auto& n : cfg.nodes)
      for (const auto& s : n.sdos) {
        uint64_t v = 0;
        for (size_t b = 0; b < s.data.size() && b < 8; ++b) v |= uint64_t(s.data[b]) << (8 * b);
        const char* what = nullptr;
        if (s.index >= 0x1400 && s.index <= 0x1BFF)
          what = "the PDO settings (the plugin sets up every PDO of the node)";
        else if (s.index == 0x1017 && s.subindex == 0 && n.has_heartbeat && v != n.heartbeat_ms)
          what = "heartbeat_ms";
        else if (s.index == 0x100C && s.subindex == 0 && n.guard_time_ms && v != n.guard_time_ms)
          what = "guard_time_ms";
        else if (s.index == 0x100D && s.subindex == 0 && n.guard_time_ms && v != n.life_time_factor)
          what = "life_time_factor";
        else if (s.index == 0x1012 && s.subindex == 0 && n.has_time_cob_id && v != n.time_cob_id)
          what = "time_cob_id";
        else if (s.index == 0x1016 && n.has_heartbeat_consumer)
          what = "heartbeat_consumer";
        else if (s.index == 0x1011 && n.has_restore_configuration && s.subindex == n.restore_configuration)
          what = "restore_configuration";
        else if (s.index == 0x1029)
          for (const auto& eb : n.error_behavior)
            if (eb.first == s.subindex && eb.second != v) what = "error_behavior";
        if (!what) continue;
        char obj[64];
        std::snprintf(obj, sizeof(obj), "startup SDO to 0x%04X subindex %u", s.index, s.subindex);
        warning(n.label(), std::string(obj) + " runs last and overrides " + what);
      }
  }

  void check_node_ids(const Config& cfg) {
    std::map<unsigned, int> seen;
    for (const auto& n : cfg.nodes) {
      if (n.node_id < 1 || n.node_id > 127) {
        error("nodes", "node ID " + std::to_string(n.node_id) + " is out of range (1-127)");
        continue;
      }
      if (n.node_id == cfg.master.node_id)
        error("nodes", "node ID " + std::to_string(n.node_id) + " is the master's node ID");
      if (++seen[n.node_id] == 2)
        error("nodes", "node ID " + std::to_string(n.node_id) + " is used by more than one slave");
    }
    // Two PDOs on the same COB-ID would collide on the bus.
    std::map<uint32_t, std::string> cobs;
    for (const auto& n : cfg.nodes) {
      for (const auto& p : n.tx_pdos) add_cob(cobs, n.tpdo_cob_id(p), n.label() + " TPDO " + std::to_string(p.number));
      for (const auto& p : n.rx_pdos) add_cob(cobs, n.rpdo_cob_id(p), n.label() + " RPDO " + std::to_string(p.number));
    }
  }

  void add_cob(std::map<uint32_t, std::string>& cobs, uint32_t cob, const std::string& who) {
    char hex[16];
    std::snprintf(hex, sizeof(hex), "0x%03X", cob);
    auto it = cobs.find(cob);
    if (it != cobs.end())
      error("nodes", who + " and " + it->second + " both use COB-ID " + hex);
    else
      cobs[cob] = who;
  }

  // An optional input location of one size (%IB or %IW); `has` is set only
  // when the field is present and valid.
  void get_input_location(const cJSON* obj, const char* key, const std::string& where, IecSize size, bool& has,
                          IecLocation& out) {
    if (!cJSON_GetObjectItemCaseSensitive(obj, key)) return;
    IecLocation loc;
    if (!get_location(obj, key, where, false, loc)) return;
    if (loc.area != IecArea::Input || loc.size != size) {
      error(where, std::string(key) + (size == IecSize::B ? " must be an input byte (%IB...), not "
                                                           : " must be an input word (%IW...), not ") +
                       loc.str());
      return;
    }
    has = true;
    out = loc;
  }

  struct Use {
    IecLocation loc;
    std::string who;
    unsigned nbytes = 0;  // a bridge block's size; 0: the location's own
  };

  void check_overlaps(const Config& cfg) {
    std::vector<Use> uses;
    collect_uses(cfg, "", uses);
    report_overlaps(uses, "nodes");
  }

  void report_overlaps(const std::vector<Use>& uses, const std::string& where) {
    if (byte_mode_) return report_byte_overlaps(uses, where);
    for (size_t i = 0; i < uses.size(); ++i)
      for (size_t j = i + 1; j < uses.size(); ++j)
        if (uses[i].loc.overlaps(uses[j].loc))
          error(where, uses[i].who + " and " + uses[j].who + " both map to " + uses[i].loc.str());
  }

  // A bridge config (modbus-bridge "Byte-addressed locations"): word and
  // larger locations start at an even byte; two locations clash when their
  // bytes overlap, except bits of one byte with different bit numbers.
  void report_byte_overlaps(const std::vector<Use>& uses, const std::string& where) {
    auto first = [](const Use& u) { return u.loc.index; };
    auto count = [](const Use& u) { return u.nbytes ? u.nbytes : location_bytes(u.loc); };
    for (const Use& u : uses)
      if (!u.nbytes && u.loc.size != IecSize::X && u.loc.size != IecSize::B && u.loc.index % 2)
        error(where, u.who + " " + u.loc.str() + " must start at an even byte: word locations are whole Modbus "
                                                "registers");
    for (size_t i = 0; i < uses.size(); ++i)
      for (size_t j = i + 1; j < uses.size(); ++j) {
        const Use& a = uses[i];
        const Use& b = uses[j];
        if (a.loc.area != b.loc.area) continue;
        if (a.loc.size == IecSize::X && b.loc.size == IecSize::X) {
          if (a.loc.overlaps(b.loc)) error(where, a.who + " and " + b.who + " both map to " + a.loc.str());
          continue;
        }
        uint32_t lo = std::max(first(a), first(b));
        uint32_t hi = std::min(first(a) + count(a), first(b) + count(b));
        if (lo >= hi) continue;
        std::string bytes;
        for (uint32_t k = lo; k < hi; ++k) bytes += (k == lo ? "" : " and ") + std::to_string(k);
        error(where, a.who + " (" + a.loc.str() + ") and " + b.who + " (" + b.loc.str() + ") overlap in " +
                         (a.loc.area == IecArea::Input ? "input" : "output") + " byte" + (hi - lo > 1 ? "s " : " ") +
                         bytes);
      }
  }

  // The bridge's own blocks as location uses.
  static void bridge_uses(const BridgeConfig& b, std::vector<Use>& uses) {
    if (b.has_status) uses.push_back({b.status_location, "bridge status_location", kBridgeStatusBytes});
    if (b.has_control) uses.push_back({b.control_location, "bridge control_location", kBridgeControlBytes});
    for (const auto& l : b.live_lists)
      uses.push_back({l.location, "bridge live list of " + l.network_name, kBridgeLiveListBytes});
    if (b.has_sdo_bridge) {
      uses.push_back({b.sdo_request, "bridge sdo_bridge_location.request", kBridgeSdoBytes});
      uses.push_back({b.sdo_response, "bridge sdo_bridge_location.response", kBridgeSdoBytes});
    }
  }

  // ---- the Modbus bridge (modbus-bridge spec) ----

  // A byte location of a bridge block in the right area.
  bool block_location(const cJSON* obj, const char* key, const std::string& w, IecArea area, unsigned nbytes,
                      IecLocation& out) {
    if (!cJSON_GetObjectItemCaseSensitive(obj, key)) return false;
    if (!get_location(obj, key, w, false, out)) return false;
    if (out.size != IecSize::B || out.area != area) {
      error(w, std::string(key) + " must be " + (area == IecArea::Input ? "an input" : "an output") +
                   " byte location (%" + (area == IecArea::Input ? "I" : "Q") + "B...) where its " +
                   std::to_string(nbytes) + "-byte block starts, not " + out.str());
      return false;
    }
    if (!bytes_in_image(out.index, nbytes, limits_.buffer_size)) {
      error(w, std::string(key) + " " + out.str() + ": its " + std::to_string(nbytes) +
                   "-byte block ends outside the image (" + std::to_string(limits_.buffer_size) + " bytes)");
      return false;
    }
    return true;
  }

  static bool valid_address_or_prefix(const std::string& text) {
    std::string host = text;
    size_t slash = text.find('/');
    long max_bits = 32;
    if (slash != std::string::npos) host = text.substr(0, slash);
    unsigned char buf[16];
    if (inet_pton(AF_INET, host.c_str(), buf) == 1)
      max_bits = 32;
    else if (inet_pton(AF_INET6, host.c_str(), buf) == 1)
      max_bits = 128;
    else
      return false;
    if (slash == std::string::npos) return true;
    std::string p = text.substr(slash + 1);
    char* end = nullptr;
    long bits = std::strtol(p.c_str(), &end, 10);
    return !p.empty() && !*end && bits >= 0 && bits <= max_bits;
  }

  void parse_bridge(const cJSON* root, ConfigSet& set) {
    const cJSON* b = cJSON_GetObjectItemCaseSensitive(root, "bridge");
    const std::string w = "bridge";
    if (!cJSON_IsObject(b)) {
      error("", "field 'bridge' must be an object");
      return;
    }
    BridgeConfig& c = set.bridge;
    c.enabled = true;
    check_known(b, w, {"listen", "unit_id", "word_order", "max_clients", "max_clients_per_address", "writers",
                       "readers", "watchdog_ms",
                       "on_client_loss", "status_location", "control_location", "live_lists",
                       "sdo_bridge_location", "sdo_bridge_write"});
    if (get_string(b, "listen", w, true, c.listen)) {
      bool v6 = !c.listen.empty() && c.listen[0] == '[';
      size_t colon = v6 ? c.listen.find("]:") : c.listen.rfind(':');
      std::string host = colon == std::string::npos ? "" : c.listen.substr(v6 ? 1 : 0, v6 ? colon - 1 : colon);
      std::string port = colon == std::string::npos ? "" : c.listen.substr(colon + (v6 ? 2 : 1));
      char* end = nullptr;
      long pn = std::strtol(port.c_str(), &end, 10);
      unsigned char buf[16];
      bool host_ok = inet_pton(v6 ? AF_INET6 : AF_INET, host.c_str(), buf) == 1;
      if (!host_ok || port.empty() || *end || pn < 1 || pn > 65535)
        error(w, "field 'listen' must be address:port with a numeric address, such as 0.0.0.0:502 or [::]:502, not \"" +
                     c.listen + "\"");
    }
    uint64_t v;
    if (get_uint(b, "unit_id", w, false, 255, v)) c.unit_id = (unsigned)v;
    std::string order;
    if (get_string(b, "word_order", w, false, order)) {
      if (order == "low_first")
        c.low_first = true;
      else if (order != "high_first")
        error(w, "field 'word_order' must be \"high_first\" or \"low_first\"");
    }
    if (get_uint(b, "max_clients", w, false, 64, v)) {
      if (v < 1) error(w, "field 'max_clients' must be 1-64");
      c.max_clients = (unsigned)v;
    }
    if (get_uint(b, "max_clients_per_address", w, false, 64, v)) {
      if (v < 1) error(w, "field 'max_clients_per_address' must be 1-64");
      c.max_clients_per_address = (unsigned)v;
    }
    if (!cJSON_GetObjectItemCaseSensitive(b, "writers"))
      error(w, "missing required field 'writers': list the addresses that may write, or [\"0.0.0.0/0\", \"::/0\"] "
               "to let every address write");
    for (const char* key : {"writers", "readers"}) {
      const cJSON* list = cJSON_GetObjectItemCaseSensitive(b, key);
      if (!list) continue;
      if (!cJSON_IsArray(list)) {
        error(w, std::string("field '") + key + "' must be a list of addresses or prefixes");
        continue;
      }
      const cJSON* it;
      cJSON_ArrayForEach(it, list) {
        if (!cJSON_IsString(it) || !valid_address_or_prefix(it->valuestring)) {
          error(w, std::string("field '") + key + "': " + (cJSON_IsString(it) ? "\"" + std::string(it->valuestring) + "\"" : "an entry") +
                       " is not an IPv4 or IPv6 address or prefix");
          continue;
        }
        (std::strcmp(key, "writers") == 0 ? c.writers : c.readers).push_back(it->valuestring);
      }
    }
    if (get_uint(b, "watchdog_ms", w, false, 60000, v)) c.watchdog_ms = (unsigned)v;
    std::string loss;
    if (get_string(b, "on_client_loss", w, false, loss)) {
      if (loss == "zero")
        c.on_client_loss = BridgeConfig::Loss::Zero;
      else if (loss == "hold")
        c.on_client_loss = BridgeConfig::Loss::Hold;
      else if (loss != "stop")
        error(w, "field 'on_client_loss' must be \"stop\", \"zero\" or \"hold\"");
    }
    c.has_status = block_location(b, "status_location", w, IecArea::Input, kBridgeStatusBytes, c.status_location);
    c.has_control =
        block_location(b, "control_location", w, IecArea::Output, kBridgeControlBytes, c.control_location);
    const cJSON* lists = cJSON_GetObjectItemCaseSensitive(b, "live_lists");
    if (lists && !cJSON_IsArray(lists)) error(w, "field 'live_lists' must be a list");
    int li = 0;
    const cJSON* l;
    const cJSON* list_items = cJSON_IsArray(lists) ? lists : nullptr;
    cJSON_ArrayForEach(l, list_items) {
      std::string lw = w + ".live_lists[" + std::to_string(li++) + "]";
      if (!cJSON_IsObject(l)) {
        error(lw, "must be an object");
        continue;
      }
      check_known(l, lw, {"network", "location"});
      BridgeLiveList ll;
      bool ok = get_string(l, "network", lw, true, ll.network_name);
      if (ok) {
        int found = -1;
        for (const auto& n : set.networks)
          if (n.network == ll.network_name) found = (int)n.network_index;
        if (found < 0) {
          error(lw, "network \"" + ll.network_name + "\" is not in the config");
          ok = false;
        } else if (!set.networks[found].is_canopen() || set.networks[found].is_slave()) {
          error(lw, "network \"" + ll.network_name + "\" is not a CANopen master network; a live list lists a "
                    "master's nodes");
          ok = false;
        } else {
          ll.network = (unsigned)found;
        }
      }
      if (!cJSON_GetObjectItemCaseSensitive(l, "location")) {
        error(lw, "missing required field 'location'");
        ok = false;
      } else if (!block_location(l, "location", lw, IecArea::Input, kBridgeLiveListBytes, ll.location)) {
        ok = false;
      }
      if (ok) c.live_lists.push_back(ll);
    }
    const cJSON* sdo = cJSON_GetObjectItemCaseSensitive(b, "sdo_bridge_location");
    if (sdo) {
      std::string sw = w + ".sdo_bridge_location";
      if (!cJSON_IsObject(sdo)) {
        error(w, "field 'sdo_bridge_location' must be an object with 'request' and 'response'");
      } else {
        check_known(sdo, sw, {"request", "response"});
        for (const char* key : {"request", "response"})
          if (!cJSON_GetObjectItemCaseSensitive(sdo, key)) error(sw, std::string("missing required field '") + key + "'");
        bool rq = block_location(sdo, "request", sw, IecArea::Output, kBridgeSdoBytes, c.sdo_request);
        bool rs = block_location(sdo, "response", sw, IecArea::Input, kBridgeSdoBytes, c.sdo_response);
        c.has_sdo_bridge = rq && rs;
      }
    }
    get_bool(b, "sdo_bridge_write", w, c.sdo_bridge_write);
    if (c.sdo_bridge_write && !sdo) warning(w, "'sdo_bridge_write' has no effect without 'sdo_bridge_location'");
    // The bridge has no PLC cycle.
    for (const auto& n : set.networks)
      if (n.is_canopen() && !n.is_slave() && n.master.sync_plc_cycle)
        error("networks[" + std::to_string(n.network_index) + "]: master",
              "\"sync_source\": \"plc_cycle\" needs a PLC cycle, which the Modbus bridge does not have: use "
              "\"sync_period_us\" (timer SYNC)");
  }

  // Every IEC location of one network; `p` goes in front of each name.
  void collect_uses(const Config& cfg, const std::string& p, std::vector<Use>& uses) {
    std::vector<std::pair<IecLocation, std::string>> raw;
    canworks_raw::raw_locations(cfg.raw, raw);
    for (const auto& r : raw) uses.push_back({r.first, r.second});
    if (cfg.is_plain()) return;
    if (cfg.is_j1939()) {
      const J1939Config& j = cfg.j1939;
      if (j.ecu.has_state_location) uses.push_back({j.ecu.state_location, p + "ECU state"});
      if (j.ecu.has_address_location) uses.push_back({j.ecu.address_location, p + "ECU address"});
      for (const auto& r : j.rx) {
        std::string m = p + "PGN " + std::to_string(r.pgn);
        if (r.has_status_location) uses.push_back({r.status_location, m + " status_location"});
        for (const auto& s : r.signals) {
          uses.push_back({s.location, m + " signal " + s.name});
          if (s.has_valid_location) uses.push_back({s.valid_location, m + " signal " + s.name + " valid_location"});
        }
      }
      for (const auto& t : j.tx)
        for (const auto& s : t.signals)
          if (s.has_location) uses.push_back({s.location, p + "PGN " + std::to_string(t.pgn) + " signal " + s.name});
      const J1939Diagnostics& d = j.diagnostics;
      for (size_t i = 0; i < d.rx.size(); ++i) {
        const J1939DmRx& r = d.rx[i];
        std::string m = p + "diagnostics rx[" + std::to_string(i) + "]";
        if (r.has_status_location) uses.push_back({r.status_location, m + " status_location"});
        if (r.has_lamps_location) uses.push_back({r.lamps_location, m + " lamps_location"});
        if (r.has_flash_location) uses.push_back({r.flash_location, m + " flash_location"});
        if (r.has_count_location) uses.push_back({r.count_location, m + " count_location"});
        if (r.has_dtcs_location)
          for (unsigned k = 0; k < r.dtcs; ++k)
            uses.push_back({r.dtc_location(k), m + " code " + std::to_string(k)});
      }
      for (const auto& c : d.dtcs)
        uses.push_back({c.active_location, p + "diagnostics SPN " + std::to_string(c.spn) + " FMI " +
                                               std::to_string(c.fmi) + " active_location"});
      if (d.has_lamps_location) uses.push_back({d.lamps_location, p + "diagnostics lamps_location"});
      if (d.has_clear_location) uses.push_back({d.clear_location, p + "diagnostics clear_location"});
      return;
    }
    if (cfg.is_slave()) {
      const SlaveConfig& s = cfg.slave;
      if (s.has_state_location) uses.push_back({s.state_location, p + "slave state_location"});
      if (s.has_comm_ok_location) uses.push_back({s.comm_ok_location, p + "slave comm_ok_location"});
      if (s.has_sync_count_location) uses.push_back({s.sync_count_location, p + "slave sync_count_location"});
      if (s.has_emcy_code_location) uses.push_back({s.emcy_code_location, p + "slave emcy_code_location"});
      if (s.has_error_register_location)
        uses.push_back({s.error_register_location, p + "slave error_register_location"});
      for (const auto& o : s.objects) uses.push_back({o.location, p + "slave " + o.label()});
      return;
    }
    const MasterConfig& m = cfg.master;
    if (m.has_bus_state_location) uses.push_back({m.bus_state_location, p + "master bus_state_location"});
    if (m.has_tx_error_count_location) uses.push_back({m.tx_error_count_location, p + "master tx_error_count_location"});
    if (m.has_rx_error_count_location) uses.push_back({m.rx_error_count_location, p + "master rx_error_count_location"});
    if (m.has_bus_off_count_location) uses.push_back({m.bus_off_count_location, p + "master bus_off_count_location"});
    if (m.has_state_location) uses.push_back({m.state_location, p + "master state_location"});
    for (const auto& n : cfg.nodes) {
      const std::string nl = p + n.label();
      if (n.has_status_location) uses.push_back({n.status_location, nl + " status_location"});
      if (n.has_state_location) uses.push_back({n.state_location, nl + " state_location"});
      if (n.has_boot_error_location) uses.push_back({n.boot_error_location, nl + " boot_error_location"});
      if (n.has_emcy_code_location) uses.push_back({n.emcy_code_location, nl + " emcy_code_location"});
      if (n.has_error_register_location)
        uses.push_back({n.error_register_location, nl + " error_register_location"});
      if (n.has_nmt_command_location)
        uses.push_back({n.nmt_command_location, nl + " nmt_command_location"});
      for (const auto& sv : n.sdo_variables) {
        std::string who = nl + " " + sv.label();
        uses.push_back({sv.location, who});
        if (sv.has_trigger) uses.push_back({sv.trigger_location, who + " trigger_location"});
        if (sv.has_status) uses.push_back({sv.status_location, who + " status_location"});
        if (sv.has_abort_code) uses.push_back({sv.abort_code_location, who + " abort_code_location"});
      }
      for (const auto& pdo : n.tx_pdos)
        if (pdo.has_timeout_location)
          uses.push_back({pdo.timeout_location, nl + " TPDO " + std::to_string(pdo.number) + " timeout_location"});
      auto add = [&](const std::vector<PdoConfig>& pdos, const char* dir) {
        for (const auto& p : pdos)
          for (const auto& e : p.entries) {
            if (!e.has_location) continue;
            char obj[64];
            std::snprintf(obj, sizeof(obj), " %s %u object 0x%04X:%u", dir, p.number, e.index, e.subindex);
            uses.push_back({e.location, nl + obj});
          }
      };
      add(n.tx_pdos, "TPDO");
      add(n.rx_pdos, "RPDO");
    }
  }

 private:
  std::string path_;
  ImageLimits limits_;
  std::string eds_fallback_dir_;
  std::vector<std::string>& errors_;
  std::vector<std::string>& warnings_;
  std::string prefix_;  // "networks[i]" while parsing a version 2 network
  unsigned version_ = 1;
  bool byte_mode_ = false;  // a bridge config: byte-addressed locations
  unsigned network_index_ = 0;  // the network being parsed
  // PDO entries without iec_location, for report_unlocated().
  struct Unlocated {
    unsigned network = 0;
    unsigned node = 0;
    bool tx = false;
    uint16_t index = 0;
    uint8_t subindex = 0;
    std::string where;
  };
  std::vector<Unlocated> unlocated_;
};

std::string dir_of(const std::string& path) {
  size_t slash = path.find_last_of('/');
  if (slash == std::string::npos) return ".";
  if (slash == 0) return "/";
  return path.substr(0, slash);
}

}  // namespace

std::vector<ImageUse> image_uses(const ConfigSet& set) {
  std::vector<std::string> errors, warnings;
  Parser p(set.path, ImageLimits(), "", errors, warnings);
  std::vector<Parser::Use> uses;
  for (const auto& cfg : set.networks) p.collect_uses(cfg, "", uses);
  size_t data = uses.size();
  Parser::bridge_uses(set.bridge, uses);
  std::vector<ImageUse> out;
  for (size_t i = 0; i < uses.size(); ++i) {
    const auto& u = uses[i];
    out.push_back({u.loc, u.nbytes ? u.nbytes : location_bytes(u.loc), i >= data, u.who});
  }
  return out;
}

unsigned location_bytes(const IecLocation& loc) { return loc.size == IecSize::X ? 1 : iec_size_bits(loc.size) / 8; }

std::string sync_needed_message(unsigned transmission, bool from_eds) {
  return "transmission type " + std::to_string(transmission) + (from_eds ? " (from the EDS)" : "") +
         " needs SYNC, but the master produces none; set master.sync_period_us, \"sync_source\": \"plc_cycle\" or "
         "\"transmission\": 254 or 255";
}

std::string default_eds_fallback_dir() {
  const char* env = std::getenv("CANWORKS_GENERATED_CONF");
  if (env && *env) return env;
  char cwd[4096];
  if (!getcwd(cwd, sizeof(cwd))) return "core/generated/conf";
  return std::string(cwd) + "/core/generated/conf";
}

bool parse_config_set(const std::string& json, const std::string& path, const ImageLimits& limits,
                      ConfigSet& out, std::vector<std::string>& errors, const std::string& eds_fallback_dir) {
  out = ConfigSet();
  out.path = path;
  out.config_dir = dir_of(path);
  out.file_sha256 = sha256_hex(json);
  cJSON* root = cJSON_Parse(json.c_str());
  if (!root) {
    const char* at = cJSON_GetErrorPtr();
    std::string near = at ? std::string(at).substr(0, 20) : "";
    errors.push_back(path + ": not valid JSON (near \"" + near + "\")");
    return false;
  }
  Parser parser(path, limits, eds_fallback_dir, errors, out.warnings);
  bool ok = parser.parse(root, out);
  cJSON_Delete(root);
  for (auto& cfg : out.networks) cfg.file_sha256 = out.file_sha256;
  return ok;
}

bool load_config_set(const std::string& path, const ImageLimits& limits, ConfigSet& out,
                     std::vector<std::string>& errors, const std::string& eds_fallback_dir) {
  std::ifstream in(path);
  if (!in) {
    out = ConfigSet();
    errors.push_back(path + ": cannot open the configuration file");
    return false;
  }
  std::stringstream ss;
  ss << in.rdbuf();
  return parse_config_set(ss.str(), path, limits, out, errors, eds_fallback_dir);
}

namespace {

bool only_network(ConfigSet& set, bool ok, Config& out, std::vector<std::string>& errors) {
  if (ok && set.networks.size() != 1) {
    errors.push_back(set.path + ": holds " + std::to_string(set.networks.size()) +
                     " networks; this tool takes a file with one");
    ok = false;
  }
  out = set.networks.empty() ? Config() : set.networks[0];
  if (set.networks.empty()) {
    out.path = set.path;
    out.config_dir = set.config_dir;
    out.file_sha256 = set.file_sha256;
  }
  out.warnings.insert(out.warnings.begin(), set.warnings.begin(), set.warnings.end());
  out.notes.insert(out.notes.begin(), set.notes.begin(), set.notes.end());
  return ok;
}

}  // namespace

bool parse_config(const std::string& json, const std::string& path,
                  const ImageLimits& limits, Config& out,
                  std::vector<std::string>& errors, const std::string& eds_fallback_dir) {
  ConfigSet set;
  bool ok = parse_config_set(json, path, limits, set, errors, eds_fallback_dir);
  return only_network(set, ok, out, errors);
}

bool load_config(const std::string& path, const ImageLimits& limits,
                 Config& out, std::vector<std::string>& errors,
                 const std::string& eds_fallback_dir) {
  ConfigSet set;
  bool ok = load_config_set(path, limits, set, errors, eds_fallback_dir);
  return only_network(set, ok, out, errors);
}

bool GatewayConfig::is_field(const Config& c) const {
  return !c.is_slave() && c.is_canopen() && (int)c.network_index != upper_master;
}

const char* protocol_name(Protocol p) {
  return p == Protocol::J1939 ? "j1939" : p == Protocol::None ? "none" : "canopen";
}

bool protocol_built_in(Protocol p) {
  if (p == Protocol::None) return true;  // raw CAN is part of the core
#if CANWORKS_WITH_CANOPEN
  if (p == Protocol::CANopen) return true;
#endif
#if CANWORKS_WITH_J1939
  if (p == Protocol::J1939) return true;
#endif
  return false;
}

std::string built_in_protocols() {
  std::string s;
  for (Protocol p : {Protocol::CANopen, Protocol::J1939})
    if (protocol_built_in(p)) s += std::string(s.empty() ? "" : ", ") + protocol_name(p);
  return s;
}

bool force_simulate_from_env(const char* value) { return value && std::strcmp(value, "1") == 0; }

bool simulates_anything(const Config& cfg) {
  if (cfg.adapter.simulate) return true;
  for (const auto& n : cfg.nodes)
    if (n.simulate) return true;
  return false;
}

}  // namespace canopen_plugin
