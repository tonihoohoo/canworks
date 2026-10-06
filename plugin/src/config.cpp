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
    if (out.index >= limit) {
      error(where, std::string(key) + " " + out.str() +
                       " lies outside the runtime I/O image (index must be below " +
                       std::to_string(limit) + ")");
      return false;
    }
    return true;
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
                          "mapping", "entries"});
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
          if (!get_location(e, "iec_location", ew, true, entry.location)) ok = false;
          char obj[32];
          std::snprintf(obj, sizeof(obj), "0x%04X:%u", entry.index, entry.subindex);
          if (ok) {
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
      check_known(root, "", {"$schema", "schema_version", "adapter", "interface", "bitrate", "master", "nodes"});
      Config cfg = blank(set);
      cfg.work_dir = set.config_dir + "/.canopen";
      parse_network(root, cfg);
      set.networks.push_back(cfg);
      return errors_.size() == before;
    }

    // Version 2: networks[] and one diagnostics object for all of them.
    check_known(root, "", {"$schema", "schema_version", "networks", "diagnostics"});
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
      copy_diagnostics(diag, cfg.master);
      if (!cJSON_IsObject(net)) {
        error("", "must be an object");
      } else {
        check_known(net, "", {"name", "adapter", "master", "nodes"});
        for (const char* old_key : {"interface", "bitrate"})
          if (cJSON_GetObjectItemCaseSensitive(net, old_key))
            error("", std::string("field '") + old_key + "' belongs in 'adapter' in schema_version 2");
        bool named = get_string(net, "name", "", false, cfg.network);
        if (named && !valid_network_name(cfg.network))
          error("", "network name \"" + cfg.network + "\" must start with a letter and hold only letters, digits "
                    "and '_', at most 16 characters");
        parse_network(net, cfg);
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
    check_networks(set);
    if (set.networks.size() > 1)
      for (auto& cfg : set.networks) cfg.log_prefix = cfg.network;
    for (auto& cfg : set.networks)
      cfg.work_dir = set.config_dir + "/.canopen/" + (cfg.network.empty() ? std::to_string(cfg.network_index)
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

  static bool valid_network_name(const std::string& name) {
    if (name.empty() || name.size() > 16 || !std::isalpha(static_cast<unsigned char>(name[0]))) return false;
    for (char c : name)
      if (!std::isalnum(static_cast<unsigned char>(c)) && c != '_') return false;
    return true;
  }

  static void copy_diagnostics(const MasterConfig& from, MasterConfig& to) {
    to.has_diagnostics = from.has_diagnostics;
    to.diag_token_sha256 = from.diag_token_sha256;
    to.diag_port = from.diag_port;
    to.diag_bind = from.diag_bind;
    to.diag_allow_changes = from.diag_allow_changes;
  }

  static std::string lower(std::string s) {
    for (char& c : s) c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    return s;
  }

  // The checks between networks (canopen-networks spec): names, adapters and
  // IEC locations.
  void check_networks(const ConfigSet& set) {
    std::map<std::string, unsigned> names, ifaces, devices;
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
      if (!cfg.adapter.interface.empty()) {
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
    std::vector<Use> uses;
    for (const auto& cfg : set.networks) {
      std::string who = "networks[" + std::to_string(cfg.network_index) + "]";
      if (!cfg.network.empty()) who += " (" + cfg.network + ")";
      collect_uses(cfg, who + " ", uses);
    }
    report_overlaps(uses, "networks");
  }

  // Parses one network: the version 1 top level, or one networks[] entry.
  void parse_network(const cJSON* root, Config& cfg) {
    uint64_t v;
    parse_adapter(root, cfg.adapter);

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
                   "time_period_ms", "diagnostics"});
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
                     "store_configuration", "lss", "software_file", "software_version", "tx_pdos", "rx_pdos",
                     "sdo", "sdo_variables"});
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
    // A version 2 file checks the locations of all networks at once.
    if (version_ == 1) check_overlaps(cfg);
    check_sdo_overrides(cfg);
    check_sdo_variable_overrides(cfg);
    check_time_consumers(cfg);
    check_sync_needs(cfg);
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
    check_known(d, w, {"token_sha256", "port", "bind", "allow_changes"});
    // Set even when a field is wrong, so the empty-node-list check adds no
    // second error.
    m.has_diagnostics = true;
    std::string hash;
    if (get_string(d, "token_sha256", w, true, hash)) {
      bool hex = hash.size() == 64;
      for (char& c : hash) {
        hex = hex && std::isxdigit(static_cast<unsigned char>(c));
        c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
      }
      if (!hex)
        error(w, "field 'token_sha256' must be 64 hexadecimal characters (the SHA-256 of the access token; "
                 "openplc-canopen-diag hash-token prints it)");
      m.diag_token_sha256 = hash;
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
  }

  void parse_node_options(const cJSON* node, const Config& cfg, NodeConfig& n, const std::string& w) {
    uint64_t v;
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
                  {"type", "interface", "bitrate", "configure_link", "restart_ms", "device", "serial_baudrate"});
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
    get_string(src, "interface", w, true, a.interface);
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
  };

  void check_overlaps(const Config& cfg) {
    std::vector<Use> uses;
    collect_uses(cfg, "", uses);
    report_overlaps(uses, "nodes");
  }

  void report_overlaps(const std::vector<Use>& uses, const std::string& where) {
    for (size_t i = 0; i < uses.size(); ++i)
      for (size_t j = i + 1; j < uses.size(); ++j)
        if (uses[i].loc.overlaps(uses[j].loc))
          error(where, uses[i].who + " and " + uses[j].who + " both map to " + uses[i].loc.str());
  }

  // Every IEC location of one network; `p` goes in front of each name.
  void collect_uses(const Config& cfg, const std::string& p, std::vector<Use>& uses) {
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
      auto add = [&](const std::vector<PdoConfig>& pdos, const char* dir) {
        for (const auto& p : pdos)
          for (const auto& e : p.entries) {
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
};

std::string dir_of(const std::string& path) {
  size_t slash = path.find_last_of('/');
  if (slash == std::string::npos) return ".";
  if (slash == 0) return "/";
  return path.substr(0, slash);
}

}  // namespace

std::string sync_needed_message(unsigned transmission, bool from_eds) {
  return "transmission type " + std::to_string(transmission) + (from_eds ? " (from the EDS)" : "") +
         " needs SYNC, but the master produces none; set master.sync_period_us, \"sync_source\": \"plc_cycle\" or "
         "\"transmission\": 254 or 255";
}

std::string default_eds_fallback_dir() {
  const char* env = std::getenv("CANOPEN_GENERATED_CONF");
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

}  // namespace canopen_plugin
