#include "eds_check.h"

#include <algorithm>
#include <cstdarg>
#include <cstdio>
#include <fstream>
#include <map>
#include <set>
#include <sstream>
#include <sys/stat.h>

#include <lely/co/dcf.h>
#include <lely/co/dev.h>
#include <lely/co/obj.h>
#include <lely/co/type.h>
#include <lely/util/diag.h>

#include "sha256.h"

namespace canopen_plugin {

namespace {

unsigned lely_type_bits(co_unsigned16_t type) {
  switch (type) {
    case CO_DEFTYPE_BOOLEAN: return 1;
    case CO_DEFTYPE_INTEGER8:
    case CO_DEFTYPE_UNSIGNED8: return 8;
    case CO_DEFTYPE_INTEGER16:
    case CO_DEFTYPE_UNSIGNED16: return 16;
    case CO_DEFTYPE_INTEGER24:
    case CO_DEFTYPE_UNSIGNED24: return 24;
    case CO_DEFTYPE_INTEGER32:
    case CO_DEFTYPE_UNSIGNED32:
    case CO_DEFTYPE_REAL32: return 32;
    case CO_DEFTYPE_INTEGER64:
    case CO_DEFTYPE_UNSIGNED64:
    case CO_DEFTYPE_REAL64: return 64;
    default: return 0;
  }
}

// The EDS AccessType keyword for Lely's access flags.
const char* access_name(unsigned access) {
  switch (access & 0x1F) {
    case CO_ACCESS_RO: return "ro";
    case CO_ACCESS_WO: return "wo";
    case CO_ACCESS_RW: return "rw";
    case CO_ACCESS_RWR: return "rwr";
    case CO_ACCESS_RWW: return "rww";
    case CO_ACCESS_CONST: return "const";
    default: return "?";
  }
}

// The EDS DataType as a name ("UNSIGNED32"), or "0x0009" for types the
// configuration cannot use.
std::string data_type_name(co_unsigned16_t type) {
  CoType t = static_cast<CoType>(type);
  if (lely_type_bits(type) && type != CO_DEFTYPE_INTEGER24 && type != CO_DEFTYPE_UNSIGNED24)
    return co_type_name(t);
  char buf[16];
  std::snprintf(buf, sizeof(buf), "0x%04X", type);
  return buf;
}

std::string where_of(const NodeConfig& n, uint16_t index, uint8_t subindex) {
  char buf[96];
  std::snprintf(buf, sizeof(buf), "node %u, index 0x%04X, subindex %u", n.node_id, index, subindex);
  return buf;
}

// The object's DataType must be the configured type.
void check_type(const std::string& where, const co_sub_t* sub, CoType type, std::vector<std::string>& errors) {
  co_unsigned16_t eds_type = co_sub_get_type(sub);
  if (eds_type != static_cast<co_unsigned16_t>(type))
    errors.push_back(where + ": configured type " + co_type_name(type) + " does not match the EDS data type " +
                     data_type_name(eds_type));
}

// The sub-object's value (ParameterValue, else DefaultValue, with $NODEID
// resolved by co_dev_set_id), for the unsigned types of PDO parameters.
bool sub_value(const co_sub_t* sub, uint64_t& value) {
  switch (co_sub_get_type(sub)) {
    case CO_DEFTYPE_UNSIGNED8: value = co_sub_get_val_u8(sub); return true;
    case CO_DEFTYPE_UNSIGNED16: value = co_sub_get_val_u16(sub); return true;
    case CO_DEFTYPE_UNSIGNED32: value = co_sub_get_val_u32(sub); return true;
    default: return false;
  }
}

// One PDO communication parameter set in the JSON: the sub-index must exist,
// and be writable unless the EDS already has the value (then dcfgen and the
// plugin write nothing).
void check_comm_param(const NodeConfig& n, const co_dev_t* dev, const char* kind, unsigned number,
                      co_unsigned16_t comm, co_unsigned8_t subidx, const char* field, uint64_t value,
                      std::vector<std::string>& errors, bool cob = false) {
  char head[160];
  std::snprintf(head, sizeof(head), "%s: %s %u: '%s' needs object 0x%04X subindex %u", n.label().c_str(), kind,
                number, field, comm, subidx);
  const co_sub_t* sub = co_dev_find_sub(dev, comm, subidx);
  if (!sub) {
    errors.push_back(std::string(head) + ", which " + n.eds + " does not define");
    return;
  }
  unsigned access = co_sub_get_access(sub);
  if (access & CO_ACCESS_WRITE) return;
  uint64_t eds = 0;
  bool known = sub_value(sub, eds);
  // A COB-ID matches when its 11 bits do and the PDO is enabled (bit 31 clear).
  if (known && (cob ? ((eds & 0x7FF) == value && !(eds & 0x80000000u)) : eds == value)) return;
  char tail[96];
  if (known && cob)
    std::snprintf(tail, sizeof(tail), " (EDS value 0x%03llX, config 0x%03llX)", (unsigned long long)(eds & 0x7FF),
                  (unsigned long long)value);
  else if (known)
    std::snprintf(tail, sizeof(tail), " (EDS value %llu)", (unsigned long long)eds);
  else
    tail[0] = 0;
  errors.push_back(std::string(head) + ", but its AccessType in " + n.eds + " is " + access_name(access) + tail +
                   "; leave the field out or set it to the EDS value");
}

void check_comm_params(const NodeConfig& n, const co_dev_t* dev, bool is_tx, const PdoConfig& p,
                       std::vector<std::string>& errors) {
  const char* kind = is_tx ? "TPDO" : "RPDO";
  co_unsigned16_t comm = (is_tx ? 0x1800 : 0x1400) + p.number - 1;
  if (!co_dev_find_obj(dev, comm)) return;  // reported as a missing PDO
  uint32_t cob = is_tx ? n.tpdo_cob_id(p) : n.rpdo_cob_id(p);
  if (p.has_cob_id) {
    check_comm_param(n, dev, kind, p.number, comm, 1, "cob_id", cob, errors, true);
  } else if (const co_sub_t* sub = co_dev_find_sub(dev, comm, 1)) {
    // Left out, the plugin still writes the CiA 301 default COB-ID, which a
    // node with a fixed COB-ID only takes when it is the same.
    uint64_t eds = 0;
    if (!(co_sub_get_access(sub) & CO_ACCESS_WRITE) && sub_value(sub, eds) &&
        ((eds & 0x7FF) != cob || (eds & 0x80000000u))) {
      char buf[320];
      std::snprintf(buf, sizeof(buf),
                    "%s: %s %u: %s fixes the COB-ID at 0x%03llX%s (0x%04X subindex 1 is %s), but the plugin uses "
                    "the CiA 301 default 0x%03X; set 'cob_id' to the EDS value",
                    n.label().c_str(), kind, p.number, n.eds.c_str(), (unsigned long long)(eds & 0x7FF),
                    (eds & 0x80000000u) ? " with the PDO switched off" : "", comm,
                    access_name(co_sub_get_access(sub)), cob);
      errors.push_back(buf);
    }
  }
  if (p.has_transmission) check_comm_param(n, dev, kind, p.number, comm, 2, "transmission", p.transmission, errors);
  if (p.has_inhibit_time)
    check_comm_param(n, dev, kind, p.number, comm, 3, "inhibit_time_us", p.inhibit_time_us / 100, errors);
  if (p.has_event_timer) check_comm_param(n, dev, kind, p.number, comm, 5, "event_timer_ms", p.event_timer_ms, errors);
  if (p.has_sync_start) {
    check_comm_param(n, dev, kind, p.number, comm, 6, "sync_start", p.sync_start, errors);
    // Without a transmission type in the JSON, the EDS one must be synchronous.
    const co_sub_t* tt = co_dev_find_sub(dev, comm, 2);
    uint64_t t = 0;
    if (!p.has_transmission && tt && sub_value(tt, t) && (t < 1 || t > 240)) {
      char buf[200];
      std::snprintf(buf, sizeof(buf),
                    "%s: %s %u: 'sync_start' needs a synchronous transmission type (1-240), but the EDS gives %llu",
                    n.label().c_str(), kind, p.number, (unsigned long long)t);
      errors.push_back(buf);
    }
  }
}

// "timeout_ms": "auto": two times the TPDO's event timer, from the config or
// else the EDS (canopen-pdo-io "Automatic receive timeout from the event
// timer"); refused when there is none.
void resolve_auto_timeout(const NodeConfig& n, const co_dev_t* dev, PdoConfig& p, std::vector<std::string>& errors) {
  uint64_t et = 0;
  bool known = false;
  if (p.has_event_timer) {
    et = p.event_timer_ms;
    known = true;
  } else if (const co_sub_t* sub = co_dev_find_sub(dev, 0x1800 + p.number - 1, 5)) {
    known = sub_value(sub, et);
  }
  if (!known || et == 0) {
    char buf[320];
    std::snprintf(buf, sizeof(buf),
                  "%s: TPDO %u: 'timeout_ms' \"auto\" needs the PDO's event timer, but %s; give the timeout in "
                  "milliseconds instead",
                  n.label().c_str(), p.number,
                  !known ? (p.has_event_timer ? "it is unknown" : "the EDS has no 0x1800+n-1 subindex 5 value")
                         : (p.has_event_timer ? "'event_timer_ms' is 0" : "its EDS value is 0"));
    std::string msg = buf;
    if (!known && !p.has_event_timer) {
      char obj[16];
      std::snprintf(obj, sizeof(obj), "0x%04X", 0x1800 + p.number - 1);
      msg.replace(msg.find("0x1800+n-1"), 10, obj);
    }
    errors.push_back(msg);
    return;
  }
  p.timeout_event_ms = static_cast<unsigned>(et);
  p.timeout_ms = static_cast<unsigned>(std::min<uint64_t>(2 * et, 0xFFFF));
}

bool sub_writable(const co_sub_t* sub) { return co_sub_get_access(sub) & CO_ACCESS_WRITE; }

// A PDO mapping object as the EDS defines it: whether the master can write
// it, and its default mapping (one 0xIIIISSLL value per mapped object).
struct EdsMapping {
  bool writable = true;
  unsigned fixed_sub = 0;     // first sub-index that is not writable
  unsigned fixed_access = 0;  // and its access type
  bool has_default = true;
  unsigned missing_sub = 0;   // first sub-index without a default (0 = sub 0 or none)
  std::vector<uint32_t> defaults;
};

EdsMapping eds_mapping(const co_dev_t* dev, co_unsigned16_t map) {
  EdsMapping m;
  const co_sub_t* sub0 = co_dev_find_sub(dev, map, 0);
  if (!sub0) {
    m.has_default = false;
    return m;
  }
  if (!sub_writable(sub0)) {
    m.writable = false;
    m.fixed_access = co_sub_get_access(sub0);
  }
  unsigned count = co_sub_get_type(sub0) == CO_DEFTYPE_UNSIGNED8 ? co_sub_get_val_u8(sub0) : 0;
  if (count == 0 || count > 64) m.has_default = false;
  for (unsigned k = 1; k <= count && k <= 64; ++k) {
    const co_sub_t* sub = co_dev_find_sub(dev, map, static_cast<co_unsigned8_t>(k));
    uint32_t v = sub && co_sub_get_type(sub) == CO_DEFTYPE_UNSIGNED32 ? co_sub_get_val_u32(sub) : 0;
    if (!v) {
      if (m.has_default) m.missing_sub = k;
      m.has_default = false;
    } else {
      m.defaults.push_back(v);
    }
    if (sub && m.writable && !sub_writable(sub)) {
      m.writable = false;
      m.fixed_sub = k;
      m.fixed_access = co_sub_get_access(sub);
    }
  }
  return m;
}

std::string mapping_list(const std::vector<uint32_t>& defaults) {
  std::string out;
  for (uint32_t v : defaults) {
    char buf[48];
    std::snprintf(buf, sizeof(buf), "%s0x%04X:%u (%u bit)", out.empty() ? "" : ", ", v >> 16, (v >> 8) & 0xFF,
                  v & 0xFF);
    out += buf;
  }
  return out;
}

// Resolves the PDO's mapping mode and checks the entries of a device-mapped
// PDO against the EDS default mapping. Notes and warnings go to the config.
void check_mapping(Config& cfg, NodeConfig& n, const co_dev_t* dev, bool is_tx, PdoConfig& p,
                   std::vector<std::string>& errors) {
  const char* kind = is_tx ? "TPDO" : "RPDO";
  co_unsigned16_t map = (is_tx ? 0x1A00 : 0x1600) + p.number - 1;
  if (!co_dev_find_obj(dev, map)) return;  // reported as a missing PDO
  EdsMapping m = eds_mapping(dev, map);
  char head[96];
  std::snprintf(head, sizeof(head), "%s: %s %u", n.label().c_str(), kind, p.number);
  if (p.mapping == PdoConfig::Mapping::Config && !m.writable) {
    char buf[320];
    std::snprintf(buf, sizeof(buf),
                  "%s: 'mapping' is \"config\", but %s fixes the mapping (0x%04X subindex %u is %s); leave "
                  "'mapping' out or set it to \"device\"",
                  head, n.eds.c_str(), map, m.fixed_sub, access_name(m.fixed_access));
    errors.push_back(buf);
    return;
  }
  p.device_mapping = p.mapping == PdoConfig::Mapping::Device || (p.mapping == PdoConfig::Mapping::Unset && !m.writable);
  if (!p.device_mapping) return;
  if (!m.has_default) {
    char buf[320];
    std::snprintf(buf, sizeof(buf),
                  "%s uses the device mapping, but %s gives no default mapping (0x%04X subindex %u has no "
                  "DefaultValue, or 0)",
                  head, n.eds.c_str(), map, m.missing_sub);
    errors.push_back(buf);
    return;
  }
  std::vector<bool> used(m.defaults.size(), false);
  for (const auto& e : p.entries) {
    bool found = false;
    for (size_t k = 0; k < m.defaults.size(); ++k) {
      uint32_t v = m.defaults[k];
      if ((v >> 16) != e.index || ((v >> 8) & 0xFF) != e.subindex) continue;
      found = true;
      used[k] = true;
      if ((v & 0xFF) != co_type_bits(e.type)) {
        char buf[200];
        std::snprintf(buf, sizeof(buf), ": configured type %s (%u bit) does not match the %u bit the default "
                                        "mapping of %s %u gives it",
                      co_type_name(e.type), co_type_bits(e.type), v & 0xFF, kind, p.number);
        errors.push_back(where_of(n, e.index, e.subindex) + buf);
      }
    }
    if (!found)
      errors.push_back(where_of(n, e.index, e.subindex) + ": not in the default mapping of " + kind + " " +
                       std::to_string(p.number) + " in " + n.eds + " (" + mapping_list(m.defaults) +
                       "); a PDO with the device mapping can only use these objects");
  }
  cfg.notes.push_back(std::string(head) + " uses the device mapping from " + n.eds + ": " + mapping_list(m.defaults));
  if (is_tx) return;
  std::string unnamed;
  for (size_t k = 0; k < m.defaults.size(); ++k) {
    uint32_t v = m.defaults[k];
    if (used[k] || (v >> 16) < 0x0008) continue;  // dummy entries carry nothing
    char buf[24];
    std::snprintf(buf, sizeof(buf), "%s0x%04X:%u", unnamed.empty() ? "" : ", ", v >> 16, (v >> 8) & 0xFF);
    unnamed += buf;
  }
  if (!unnamed.empty())
    cfg.warnings.push_back(std::string(head) + " uses the device mapping; objects not in 'entries' are sent as 0: " +
                           unnamed);
}

// The EDS's read-only PDO communication sub-indices, and the unused PDOs
// whose COB-ID is read-only (left as the node has them).
void find_fixed_pdo_params(Config& cfg, NodeConfig& n, const co_dev_t* dev) {
  n.ro_pdo_comm.clear();
  n.kept_tpdos.clear();
  n.kept_rpdos.clear();
  for (int tx = 0; tx < 2; ++tx) {
    const auto& pdos = tx ? n.tx_pdos : n.rx_pdos;
    for (unsigned num = 1; num <= 512; ++num) {
      co_unsigned16_t comm = (tx ? 0x1800 : 0x1400) + num - 1;
      const co_obj_t* obj = co_dev_find_obj(dev, comm);
      if (!obj) continue;
      for (unsigned k = 1; k <= 0xFF; ++k) {
        const co_sub_t* sub = co_obj_find_sub(obj, static_cast<co_unsigned8_t>(k));
        if (sub && !sub_writable(sub)) n.ro_pdo_comm.insert({comm, static_cast<uint8_t>(k)});
      }
      if (!co_dev_find_obj(dev, comm + 0x200) || !n.ro_pdo_comm.count({comm, 1})) continue;
      bool used = !tx && n.linked_rpdos.count(num);
      for (const auto& p : pdos) used |= p.number == num;
      if (used) continue;
      (tx ? n.kept_tpdos : n.kept_rpdos).insert(num);
      uint64_t cob = 0;
      if (sub_value(co_obj_find_sub(obj, 1), cob) && !(cob & 0x80000000u))
        cfg.notes.push_back(n.label() + ": " + (tx ? "TPDO " : "RPDO ") + std::to_string(num) +
                            " is not configured, but " + n.eds +
                            " fixes its COB-ID; it stays enabled as the node has it");
    }
  }
}

void check_pdos(Config& cfg, NodeConfig& n, const co_dev_t* dev, bool is_tx,
                std::vector<std::string>& errors) {
  auto& pdos = is_tx ? n.tx_pdos : n.rx_pdos;
  const char* kind = is_tx ? "TPDO" : "RPDO";
  const co_unsigned16_t comm_base = is_tx ? 0x1800 : 0x1400;
  for (auto& p : pdos) {
    co_unsigned16_t comm = comm_base + p.number - 1;
    if (!co_dev_find_obj(dev, comm) || !co_dev_find_obj(dev, comm + 0x200)) {
      char buf[160];
      std::snprintf(buf, sizeof(buf), "%s: %s %u does not exist in %s (no object 0x%04X/0x%04X)",
                    n.label().c_str(), kind, p.number, n.eds.c_str(), comm, comm + 0x200);
      errors.push_back(buf);
    }
    check_comm_params(n, dev, is_tx, p, errors);
    if (is_tx && p.timeout_auto) resolve_auto_timeout(n, dev, p, errors);
    // Without SYNC, a PDO left at a synchronous EDS transmission type would
    // never move; the plugin does not pick another type on its own.
    uint64_t tt = 0;
    const co_sub_t* tt_sub = co_dev_find_sub(dev, comm, 2);
    if (!cfg.master.produces_sync() && !p.has_transmission && tt_sub && sub_value(tt_sub, tt) &&
        transmission_needs_sync((unsigned)tt))
      errors.push_back(n.label() + ": " + kind + " " + std::to_string(p.number) + ": " +
                       sync_needed_message((unsigned)tt, true));
    check_mapping(cfg, n, dev, is_tx, p, errors);
    for (const auto& e : p.entries) {
      std::string where = where_of(n, e.index, e.subindex);
      const co_sub_t* sub = co_dev_find_sub(dev, e.index, e.subindex);
      if (!sub) {
        errors.push_back(where + ": object is not defined in " + n.eds);
        continue;
      }
      if (!co_sub_get_pdo_mapping(sub)) {
        errors.push_back(where + ": object is not PDO-mappable in " + n.eds);
        continue;
      }
      // A slave TPDO can carry ro, rw, rwr and const objects; a slave RPDO
      // wo, rw and rww objects (CiA 306).
      unsigned access = co_sub_get_access(sub);
      if (is_tx && !(access & CO_ACCESS_TPDO))
        errors.push_back(where + ": tx_pdos entry needs an object the slave can send (AccessType ro, rw, rwr or "
                                 "const), but its AccessType is " + access_name(access));
      if (!is_tx && !(access & CO_ACCESS_RPDO))
        errors.push_back(where + ": rx_pdos entry needs an object the slave can receive (AccessType wo, rw or "
                                 "rww), but its AccessType is " + access_name(access));
      check_type(where, sub, e.type, errors);
    }
  }
}

void check_sdos(const NodeConfig& n, const co_dev_t* dev, std::vector<std::string>& errors) {
  for (const auto& s : n.sdos) {
    std::string where = where_of(n, s.index, s.subindex);
    const co_sub_t* sub = co_dev_find_sub(dev, s.index, s.subindex);
    if (!sub) {
      errors.push_back(where + ": object is not defined in " + n.eds);
      continue;
    }
    unsigned access = co_sub_get_access(sub);
    if (!(access & CO_ACCESS_WRITE))
      errors.push_back(where + ": startup SDO needs a writable object (AccessType wo, rw, rwr or rww), but its "
                               "AccessType is " + access_name(access));
    check_type(where, sub, s.type, errors);
  }
}

void check_sdo_variables(const NodeConfig& n, const co_dev_t* dev, std::vector<std::string>& errors) {
  for (const auto& sv : n.sdo_variables) {
    std::string where = where_of(n, sv.index, sv.subindex);
    const co_sub_t* sub = co_dev_find_sub(dev, sv.index, sv.subindex);
    if (!sub) {
      errors.push_back(where + ": object is not defined in " + n.eds);
      continue;
    }
    unsigned access = co_sub_get_access(sub);
    if (sv.is_read() && !(access & CO_ACCESS_READ))
      errors.push_back(where + ": SDO variable to read needs a readable object (AccessType ro, rw, rwr, rww or "
                               "const), but its AccessType is " + access_name(access));
    if (!sv.is_read() && !(access & CO_ACCESS_WRITE))
      errors.push_back(where + ": SDO variable to write needs a writable object (AccessType wo, rw, rwr or rww), "
                               "but its AccessType is " + access_name(access));
    check_type(where, sub, sv.type, errors);
  }
}

// Lely's DCF parser reports syntax errors through diag()/diag_at() and still
// returns a (partial) device, so parsing is judged by those reports.
struct ParseErrors {
  int count = 0;
  std::string first;
};

void count_diag_at(void* handle, diag_severity severity, int, const floc* at, const char* format,
                   va_list ap) {
  if (severity < DIAG_ERROR) return;
  auto* pe = static_cast<ParseErrors*>(handle);
  if (pe->count++ == 0) {
    char msg[256];
    std::vsnprintf(msg, sizeof(msg), format, ap);
    char buf[512];
    if (at && at->filename)
      std::snprintf(buf, sizeof(buf), "line %d: %s", at->line, msg);
    else
      std::snprintf(buf, sizeof(buf), "%s", msg);
    pe->first = buf;
  }
}

void count_diag(void* handle, diag_severity severity, int errc, const char* format, va_list ap) {
  count_diag_at(handle, severity, errc, nullptr, format, ap);
}

co_dev_t* parse_eds(const std::string& path, std::string& why) {
  diag_handler_t* old = nullptr;
  void* old_handle = nullptr;
  diag_at_handler_t* old_at = nullptr;
  void* old_at_handle = nullptr;
  diag_get_handler(&old, &old_handle);
  diag_at_get_handler(&old_at, &old_at_handle);
  ParseErrors pe;
  diag_set_handler(&count_diag, &pe);
  diag_at_set_handler(&count_diag_at, &pe);
  co_dev_t* dev = co_dev_create_from_dcf_file(path.c_str());
  diag_set_handler(old, old_handle);
  diag_at_set_handler(old_at, old_at_handle);
  if (dev && pe.count == 0 && co_dev_find_obj(dev, 0x1000) && co_dev_find_obj(dev, 0x1018)) return dev;
  if (dev) co_dev_destroy(dev);
  why = pe.count ? pe.first : "mandatory objects 0x1000/0x1018 missing (not a CiA 306 EDS)";
  return nullptr;
}

// config_check needs the node's configuration date and time (0x1020 sub 1
// and 2) and store_configuration its 0x1010 sub-index, writable and
// UNSIGNED32, so the master can write them after a download.
void check_config_objects(const NodeConfig& n, const co_dev_t* dev, std::vector<std::string>& errors) {
  auto need = [&](uint16_t index, uint8_t subindex, const char* field) {
    std::string where = where_of(n, index, subindex);
    const co_sub_t* sub = co_dev_find_sub(dev, index, subindex);
    if (!sub) {
      errors.push_back(where + ": " + field + " needs this object, but it is not defined in " + n.eds);
      return;
    }
    unsigned access = co_sub_get_access(sub);
    if (!(access & CO_ACCESS_WRITE))
      errors.push_back(where + ": " + field + " needs a writable object (AccessType wo, rw, rwr or rww), but its "
                                              "AccessType is " + access_name(access));
    check_type(where, sub, CoType::UNSIGNED32, errors);
  };
  if (n.config_check) {
    need(0x1020, 1, "config_check");
    need(0x1020, 2, "config_check");
  }
  if (n.has_store_configuration) need(0x1010, static_cast<uint8_t>(n.store_configuration), "store_configuration");
}

// Two nodes with lss.assign must not name the same device: same vendor ID,
// product code and serial number, and the same revision or either revision
// unset (0 = searched for).
void check_lss_addresses(const Config& cfg, std::vector<std::string>& errors) {
  for (size_t i = 0; i < cfg.nodes.size(); ++i) {
    const NodeConfig& a = cfg.nodes[i];
    if (!a.lss_assign) continue;
    for (size_t j = i + 1; j < cfg.nodes.size(); ++j) {
      const NodeConfig& b = cfg.nodes[j];
      if (!b.lss_assign || a.eds_vendor_id != b.eds_vendor_id || a.eds_product_code != b.eds_product_code ||
          a.serial_number != b.serial_number)
        continue;
      if (a.revision_number && b.revision_number && a.revision_number != b.revision_number) continue;
      char addr[96];
      std::snprintf(addr, sizeof addr, "vendor ID 0x%08X, product code 0x%08X, serial number 0x%08X",
                    (unsigned)a.eds_vendor_id, (unsigned)a.eds_product_code, (unsigned)a.serial_number);
      errors.push_back(a.label() + " and " + b.label() + " have the same LSS address (" + addr + ")");
    }
  }
}

// Whether the EDS data type is one a PLC location can hold.
bool bindable_type(co_unsigned16_t type) {
  return lely_type_bits(type) && type != CO_DEFTYPE_INTEGER24 && type != CO_DEFTYPE_UNSIGNED24;
}

std::string hex_object(uint16_t index, uint8_t subindex) {
  char buf[16];
  std::snprintf(buf, sizeof(buf), "0x%04X:%u", index, subindex);
  return buf;
}

std::string file_sha256(const std::string& path) {
  std::ifstream in(path, std::ios::binary);
  std::ostringstream ss;
  ss << in.rdbuf();
  return sha256_hex(ss.str());
}

// A slave network (canopen-slave-device spec): the EDS must parse, each bound
// object must be in it with a type a location holds, and its access type sets
// the direction.
void check_slave(Config& cfg, std::vector<std::string>& errors) {
  SlaveConfig& s = cfg.slave;
  std::string net = cfg.network.empty() ? "" : "network \"" + cfg.network + "\", ";
  struct stat st;
  if (stat(s.eds_path.c_str(), &st) != 0 || !S_ISREG(st.st_mode)) {
    std::string looked;
    for (size_t i = 1; i < s.eds_candidates.size(); ++i)
      looked += (i == 1 ? " (also looked for " : ", ") + s.eds_candidates[i];
    if (!looked.empty()) looked += ")";
    errors.push_back(net + s.label() + ": EDS file " + s.eds_path + " not found" + looked);
    return;
  }
  std::string why;
  co_dev_t* dev = parse_eds(s.eds_path, why);
  if (!dev) {
    errors.push_back(net + s.label() + ": EDS file " + s.eds_path + " cannot be parsed: " + why);
    return;
  }
  s.eds_sha256 = file_sha256(s.eds_path);
  for (auto& o : s.objects) {
    std::string who = net + "slave " + o.label() + ": ";
    const co_sub_t* sub = co_dev_find_sub(dev, o.index, o.subindex);
    if (!sub) {
      errors.push_back(who + "not in the EDS " + s.eds);
      continue;
    }
    co_unsigned16_t type = co_sub_get_type(sub);
    if (!bindable_type(type)) {
      errors.push_back(who + "data type " + data_type_name(type) + " cannot be bound to a PLC location");
      continue;
    }
    o.type = static_cast<CoType>(type);
    unsigned access = co_sub_get_access(sub) & 0x1F;
    std::string obj = hex_object(o.index, o.subindex);
    if (access == CO_ACCESS_CONST || access == CO_ACCESS_WO) {
      errors.push_back(who + "its access type is " + access_name(access) + " in the EDS, so it cannot be bound (use "
                             "rww for a value from the master, ro or rwr for a value to the master)");
      continue;
    }
    o.input = access == CO_ACCESS_RWW || access == CO_ACCESS_RW;
    if (o.input && o.location.area != IecArea::Input) {
      errors.push_back(who + "the master writes " + obj + " (access " + access_name(access) +
                       "), so it needs an %I location, not " + o.location.str() +
                       (access == CO_ACCESS_RW ? " (make it rwr in the EDS for a value the PLC sends)" : ""));
      continue;
    }
    if (!o.input && o.location.area != IecArea::Output) {
      errors.push_back(who + "the master reads " + obj + " (access " + access_name(access) +
                       "), so the PLC writes it and it needs a %Q location, not " + o.location.str());
      continue;
    }
    if (!co_type_fits(o.type, o.location.size))
      errors.push_back(who + "type " + co_type_name(o.type) + " (" + std::to_string(co_type_bits(o.type)) +
                       " bit) does not fit location " + o.location.str() + " (" +
                       std::to_string(iec_size_bits(o.location.size)) + " bit)");
  }
  if ((s.has_emcy_code_location || s.has_error_register_location) && !co_dev_find_obj(dev, 0x1014))
    errors.push_back(net + s.label() + ": emcy_code_location needs the EMCY object 0x1014 in the EDS " + s.eds);
  if (s.lss && !co_dev_get_lss(dev))
    cfg.warnings.push_back(s.label() + ": its EDS does not say LSS_Supported=1; LSS masters may not look for it");
  co_dev_destroy(dev);
}

// A node the master would never see as lost: no heartbeat_ms, no guarding
// and an EDS heartbeat default (0x1017) of 0 (canopen-node-supervision
// "Every node is supervised or says why not"). An explicit "heartbeat_ms": 0
// is accepted; the parser warns about it.
void check_supervision(const NodeConfig& n, const co_dev_t* dev, std::vector<std::string>& errors) {
  if (n.has_heartbeat || n.guard_time_ms) return;
  const co_sub_t* sub = co_dev_find_sub(dev, 0x1017, 0);
  uint64_t period = 0;
  if (sub && sub_value(sub, period) && period) return;
  errors.push_back(n.label() + " has no heartbeat or guarding (its EDS heartbeat 0x1017 defaults to 0): its loss would "
                               "never be detected; set heartbeat_ms, or \"heartbeat_ms\": 0 to accept that");
}

// ---- PDO links and heartbeat watch (canopen-pdo-links) ----

NodeConfig* find_node(Config& cfg, unsigned id) {
  for (auto& n : cfg.nodes)
    if (n.node_id == id) return &n;
  return nullptr;
}

const co_dev_t* dev_of(const std::map<unsigned, co_dev_t*>& devs, unsigned id) {
  auto it = devs.find(id);
  return it == devs.end() ? nullptr : it->second;
}

std::string plural(unsigned n, const char* one, const char* many) {
  return std::to_string(n) + " " + (n == 1 ? one : many);
}

// Each heartbeat_watch entry: the watched node's heartbeat from its EDS when
// the config gives none, the default timeout, and a 0x1016 entry of the
// watching node, found as dcfgen finds the master's (canopen-node-supervision
// "Node-to-node heartbeat watch").
void check_heartbeat_watch(Config& cfg, const std::map<unsigned, co_dev_t*>& devs, std::vector<std::string>& errors) {
  for (auto& n : cfg.nodes) {
    if (n.heartbeat_watch.empty()) continue;
    const co_dev_t* dev = dev_of(devs, n.node_id);
    if (!dev) continue;  // the EDS problem is reported
    bool usable = true;
    for (auto& h : n.heartbeat_watch) {
      const NodeConfig* t = find_node(cfg, h.node);
      if (!t || t->node_id == n.node_id || t->guard_time_ms) continue;  // reported by the parser
      const std::string head = n.label() + ": heartbeat_watch[" + std::to_string(h.position) + "]: ";
      uint64_t period = t->heartbeat_ms;
      if (!t->has_heartbeat) {
        const co_dev_t* tdev = dev_of(devs, t->node_id);
        const co_sub_t* sub = tdev ? co_dev_find_sub(tdev, 0x1017, 0) : nullptr;
        period = 0;
        if (!tdev) continue;
        if (!sub || !sub_value(sub, period) || !period) {
          errors.push_back(head + t->label() + " sends no heartbeat (its EDS heartbeat 0x1017 defaults to 0 and it "
                                               "sets no heartbeat_ms); a heartbeat watch needs the watched node's "
                                               "heartbeat");
          usable = false;
          continue;
        }
      }
      if (!period) continue;  // "heartbeat_ms": 0, reported by the parser
      if (!h.has_timeout) {
        h.timeout_ms = t->has_heartbeat ? t->heartbeat_timeout_ms
                                        : static_cast<unsigned>(std::min<uint64_t>(3 * period, 0xFFFF));
      } else if (!t->has_heartbeat && h.timeout_ms <= period) {
        errors.push_back(head + "timeout_ms " + std::to_string(h.timeout_ms) + " must be above " + t->label() +
                         "'s heartbeat period of " + std::to_string(period) + " ms");
        usable = false;
      }
    }
    if (!usable) continue;
    const co_obj_t* obj = co_dev_find_obj(dev, 0x1016);
    if (!obj) {
      errors.push_back(n.label() + ": heartbeat_watch needs object 0x1016 (consumer heartbeat time), which " + n.eds +
                       " does not define");
      continue;
    }
    // The writable entries and their EDS values, in sub-index order.
    std::vector<std::pair<unsigned, uint32_t>> entries;
    for (unsigned k = 1; k <= 0xFF; ++k) {
      const co_sub_t* sub = co_obj_find_sub(obj, static_cast<co_unsigned8_t>(k));
      uint64_t v = 0;
      if (sub && sub_writable(sub) && sub_value(sub, v)) entries.emplace_back(k, static_cast<uint32_t>(v));
    }
    auto unused = [](uint32_t v) {
      unsigned id = (v >> 16) & 0xFF;
      return (v & 0xFFFF) == 0 || id == 0 || id > 127;
    };
    // The entry dcfgen takes for the master's heartbeat: the one naming the
    // master, else the first unused one.
    unsigned master_sub = 0;
    bool master_entry = n.has_heartbeat_consumer && n.heartbeat_consumer && cfg.master.heartbeat_ms;
    if (master_entry) {
      for (const auto& e : entries)
        if (!master_sub && ((e.second >> 16) & 0xFF) == cfg.master.node_id) master_sub = e.first;
      for (const auto& e : entries)
        if (!master_sub && unused(e.second)) master_sub = e.first;
    }
    size_t need = n.heartbeat_watch.size() + (master_entry ? 1 : 0);
    if (need > entries.size()) {
      std::string why = master_entry ? "1 for the master's heartbeat, " + std::to_string(n.heartbeat_watch.size()) +
                                           " for heartbeat_watch"
                                     : std::to_string(n.heartbeat_watch.size()) + " for heartbeat_watch";
      errors.push_back(n.label() + ": heartbeat_watch: 0x1016 in " + n.eds + " has room for " +
                       plural(static_cast<unsigned>(entries.size()), "entry", "entries") + " where " +
                       std::to_string(need) + (need == 1 ? " is" : " are") + " needed (" + why + ")");
      continue;
    }
    std::set<unsigned> taken;
    if (master_sub) taken.insert(master_sub);
    for (auto& h : n.heartbeat_watch) {
      h.subindex = 0;
      for (const auto& e : entries)
        if (!h.subindex && !taken.count(e.first) && ((e.second >> 16) & 0xFF) == h.node)
          h.subindex = static_cast<uint8_t>(e.first);
      for (const auto& e : entries)
        if (!h.subindex && !taken.count(e.first) && unused(e.second)) h.subindex = static_cast<uint8_t>(e.first);
      if (!h.subindex) {
        errors.push_back(n.label() + ": heartbeat_watch[" + std::to_string(h.position) + "]: no unused 0x1016 entry is "
                                     "left for node " + std::to_string(h.node) + " in " + n.eds);
        continue;
      }
      taken.insert(h.subindex);
    }
  }
}

// One position of a PDO's layout: the object it maps, its size and its
// DataType (-1 for a dummy entry or an object the EDS does not give).
struct LayoutPos {
  uint16_t index = 0;
  uint8_t subindex = 0;
  unsigned bits = 0;
  int type = -1;
};

std::string layout_list(const std::vector<LayoutPos>& l) {
  std::string out;
  for (const auto& p : l) {
    char buf[48];
    std::snprintf(buf, sizeof(buf), "%s0x%04X:%u (%u bit)", out.empty() ? "" : ", ", p.index, p.subindex, p.bits);
    out += buf;
  }
  return out;
}

int eds_type(const co_dev_t* dev, uint16_t index, uint8_t subindex) {
  if (index >= 0x0001 && index <= 0x0007) return -1;  // a dummy entry
  const co_sub_t* sub = co_dev_find_sub(dev, index, subindex);
  return sub ? co_sub_get_type(sub) : -1;
}

std::vector<LayoutPos> default_layout(const co_dev_t* dev, const EdsMapping& m) {
  std::vector<LayoutPos> out;
  for (uint32_t v : m.defaults) {
    LayoutPos p;
    p.index = static_cast<uint16_t>(v >> 16);
    p.subindex = static_cast<uint8_t>(v >> 8);
    p.bits = v & 0xFF;
    p.type = eds_type(dev, p.index, p.subindex);
    out.push_back(p);
  }
  return out;
}

// The transmission type a PDO runs with: the config's, else the EDS's; false
// when neither gives one.
bool effective_transmission(const co_dev_t* dev, uint16_t comm, bool has, unsigned value, unsigned& out) {
  if (has) {
    out = value;
    return true;
  }
  uint64_t v = 0;
  const co_sub_t* sub = co_dev_find_sub(dev, comm, 2);
  if (!sub || !sub_value(sub, v)) return false;
  out = static_cast<unsigned>(v);
  return true;
}

// Every link against both EDS files (canopen-pdo-links "Link layout checked
// against both EDS files", "Link COB-ID rules", "Synchronous links need
// SYNC", "Links on PLC stop"); resolves each consumer's mapping mode and adds
// the link summary to the notes.
void check_links(Config& cfg, const std::map<unsigned, co_dev_t*>& devs, std::vector<std::string>& errors) {
  for (auto& l : cfg.links) {
    const std::string me = l.label() + ": ";
    NodeConfig* p = find_node(cfg, l.producer);
    const PdoConfig* tp = nullptr;
    if (p)
      for (const auto& t : p->tx_pdos)
        if (t.number == l.tpdo) tp = &t;
    const co_dev_t* pdev = p ? dev_of(devs, p->node_id) : nullptr;
    if (!tp || !pdev) continue;  // reported by the parser or the node's EDS checks
    const std::string prod_who = p->label() + " TPDO " + std::to_string(tp->number);
    std::vector<LayoutPos> prod;
    if (tp->device_mapping) {
      EdsMapping m = eds_mapping(pdev, static_cast<co_unsigned16_t>(0x1A00 + tp->number - 1));
      if (!m.has_default) continue;  // reported by check_mapping
      prod = default_layout(pdev, m);
    } else {
      for (const auto& e : tp->entries)
        prod.push_back({e.index, e.subindex, co_type_bits(e.type), static_cast<int>(e.type)});
    }
    unsigned prod_bits = 0;
    for (const auto& x : prod) prod_bits += x.bits;
    unsigned prod_tt = 0;
    bool prod_sync = effective_transmission(pdev, static_cast<uint16_t>(0x1800 + tp->number - 1), tp->has_transmission,
                                            tp->transmission, prod_tt) &&
                     transmission_needs_sync(prod_tt);
    std::string consumers, sync_parts;
    if (prod_sync) sync_parts = prod_who + " sends on SYNC (transmission type " + std::to_string(prod_tt) + ")";
    std::vector<std::string> kept_sync;
    if (prod_sync) kept_sync.push_back(prod_who + " is synchronous (transmission type " + std::to_string(prod_tt) + ")");
    for (auto& c : l.consumers) {
      NodeConfig* n = find_node(cfg, c.node);
      const co_dev_t* dev = n ? dev_of(devs, n->node_id) : nullptr;
      if (!n || !dev || c.node == l.producer) continue;
      const std::string who = n->label() + " RPDO " + std::to_string(c.rpdo);
      consumers += (consumers.empty() ? "" : ", ") + who;
      const co_unsigned16_t comm = static_cast<co_unsigned16_t>(0x1400 + c.rpdo - 1);
      const co_unsigned16_t map = static_cast<co_unsigned16_t>(comm + 0x200);
      if (!co_dev_find_obj(dev, comm) || !co_dev_find_obj(dev, map)) {
        char buf[96];
        std::snprintf(buf, sizeof(buf), " (no object 0x%04X/0x%04X)", comm, map);
        errors.push_back(me + who + " does not exist in " + n->eds + buf);
        continue;
      }
      // The COB-ID: a read-only one must be the link's.
      const co_sub_t* cob = co_dev_find_sub(dev, comm, 1);
      uint64_t eds_cob = 0;
      if (cob && !sub_writable(cob) && sub_value(cob, eds_cob)) {
        char buf[320];
        if (eds_cob & 0x80000000u) {
          std::snprintf(buf, sizeof(buf), "%s fixes its COB-ID with the PDO switched off (0x%04X subindex 1 is %s); it "
                                          "cannot receive the link", n->eds.c_str(), comm,
                        access_name(co_sub_get_access(cob)));
          errors.push_back(me + who + ": " + buf);
        } else if ((eds_cob & 0x7FF) != l.cob_id) {
          std::snprintf(buf, sizeof(buf), " can only receive 0x%03X (%s makes 0x%04X subindex 1 %s); the producer %s "
                                          "needs \"cob_id\": \"0x%03X\"",
                        (unsigned)(eds_cob & 0x7FF), n->eds.c_str(), comm, access_name(co_sub_get_access(cob)),
                        prod_who.c_str(), (unsigned)(eds_cob & 0x7FF));
          errors.push_back(me + who + buf);
        }
      }
      // Read-only transmission type and deadline must hold the configured value.
      std::vector<std::string> comm_errors;
      if (c.has_transmission)
        check_comm_param(*n, dev, "RPDO", c.rpdo, comm, 2, "transmission", c.transmission, comm_errors);
      if (c.has_event_timer)
        check_comm_param(*n, dev, "RPDO", c.rpdo, comm, 5, "event_timer_ms", c.event_timer_ms, comm_errors);
      for (const auto& e : comm_errors) errors.push_back(me + e);
      unsigned tt = 0;
      bool cons_sync = effective_transmission(dev, comm, c.has_transmission, c.transmission, tt) &&
                       transmission_needs_sync(tt);
      if (cons_sync && !c.has_transmission && !cfg.master.produces_sync())
        errors.push_back(me + who + ": " + sync_needed_message(tt, true));
      if (cons_sync) {
        sync_parts += (sync_parts.empty() ? "" : "; ") + who + " applies the data at the next SYNC";
        kept_sync.push_back(who + " is synchronous (transmission type " + std::to_string(tt) + ")");
      }
      // The mapping: the config's entries, or the device's own.
      EdsMapping m = eds_mapping(dev, map);
      if (c.mapping == PdoConfig::Mapping::Config && !m.writable) {
        char buf[320];
        std::snprintf(buf, sizeof(buf),
                      ": 'mapping' is \"config\", but %s fixes the mapping (0x%04X subindex %u is %s); leave "
                      "'mapping' out or set it to \"device\"",
                      n->eds.c_str(), map, m.fixed_sub, access_name(m.fixed_access));
        errors.push_back(me + who + buf);
        continue;
      }
      c.device_mapping =
          c.mapping == PdoConfig::Mapping::Device || (c.mapping == PdoConfig::Mapping::Unset && !m.writable);
      std::vector<LayoutPos> cons;
      if (c.device_mapping) {
        if (!m.has_default) {
          char buf[320];
          std::snprintf(buf, sizeof(buf),
                        " uses the device mapping, but %s gives no default mapping (0x%04X subindex %u has no "
                        "DefaultValue, or 0)",
                        n->eds.c_str(), map, m.missing_sub);
          errors.push_back(me + who + buf);
          continue;
        }
        cons = default_layout(dev, m);
        bool same = c.entries.size() == cons.size();
        for (size_t k = 0; same && k < cons.size(); ++k)
          same = c.entries[k].index == cons[k].index && c.entries[k].subindex == cons[k].subindex;
        if (!c.entries.empty() && !same) {
          errors.push_back(me + who + " uses the device mapping from " + n->eds + " (" + layout_list(cons) +
                           "); its 'entries' must list those objects in that order, or be left out");
          continue;
        }
      } else {
        for (size_t k = 0; k < c.entries.size(); ++k) {
          const PdoEntry& e = c.entries[k];
          LayoutPos pos{e.index, e.subindex, co_type_bits(e.type), static_cast<int>(e.type)};
          if (e.index >= 0x0001 && e.index <= 0x0007) {
            // A dummy entry: its index is its DataType (CiA 301).
            pos.type = -1;
            char at[96];
            std::snprintf(at, sizeof(at), " entries[%zu]: dummy entry 0x%04X", k, e.index);
            if (e.subindex != 0)
              errors.push_back(me + who + at + " takes subindex 0");
            else if (static_cast<unsigned>(e.type) != e.index)
              errors.push_back(me + who + at + " is " + data_type_name(e.index) + ", not " + co_type_name(e.type));
            else if (!(co_dev_get_dummy(dev) & (1u << e.index)))
              errors.push_back(me + who + at + " needs Dummy" + hex_object(e.index, 0).substr(2, 4) +
                               "=1 in [DummyUsage] of " + n->eds);
            cons.push_back(pos);
            continue;
          }
          std::string where = me + where_of(*n, e.index, e.subindex);
          const co_sub_t* sub = co_dev_find_sub(dev, e.index, e.subindex);
          if (!sub) {
            errors.push_back(where + ": object is not defined in " + n->eds);
          } else if (!co_sub_get_pdo_mapping(sub)) {
            errors.push_back(where + ": object is not PDO-mappable in " + n->eds);
          } else {
            unsigned access = co_sub_get_access(sub);
            if (!(access & CO_ACCESS_RPDO))
              errors.push_back(where + ": a link consumer entry needs an object the node can receive (AccessType wo, rw "
                                       "or rww), but its AccessType is " + access_name(access));
            check_type(where, sub, e.type, errors);
          }
          cons.push_back(pos);
        }
      }
      // The layout: the same positions with the same sizes.
      unsigned cons_bits = 0;
      for (const auto& x : cons) cons_bits += x.bits;
      bool match = cons.size() == prod.size();
      for (size_t k = 0; match && k < cons.size(); ++k) match = cons[k].bits == prod[k].bits;
      if (!match && c.device_mapping) {
        errors.push_back(me + who + " uses the default mapping from " + n->eds + " (" + layout_list(cons) +
                         "), which does not match " + prod_who + " (" + layout_list(prod) + ")");
        continue;
      }
      if (!match && (cons.size() != prod.size() || cons_bits != prod_bits)) {
        errors.push_back(me + who + " maps " + std::to_string(cons_bits) + " bits in " +
                         plural(static_cast<unsigned>(cons.size()), "position", "positions") + ", but " + prod_who +
                         " sends " + std::to_string(prod_bits) + " bits in " +
                         plural(static_cast<unsigned>(prod.size()), "position", "positions") +
                         "; the consumer must map the same positions with the same sizes (use dummy entries for "
                         "values it does not need)");
        continue;
      }
      if (!match) {
        for (size_t k = 0; k < cons.size(); ++k)
          if (cons[k].bits != prod[k].bits)
            errors.push_back(me + who + " position " + std::to_string(k + 1) + ": " +
                             layout_list({cons[k]}) + " does not match " + layout_list({prod[k]}) + " of " + prod_who);
        continue;
      }
      for (size_t k = 0; k < cons.size(); ++k)
        if (cons[k].type >= 0 && prod[k].type >= 0 && cons[k].type != prod[k].type)
          cfg.warnings.push_back(me + "position " + std::to_string(k + 1) + ": " + prod_who + " sends " +
                                 hex_object(prod[k].index, prod[k].subindex) + " as " +
                                 data_type_name(static_cast<co_unsigned16_t>(prod[k].type)) + " and " + who +
                                 " receives it in " + hex_object(cons[k].index, cons[k].subindex) + " as " +
                                 data_type_name(static_cast<co_unsigned16_t>(cons[k].type)) +
                                 "; the bits are copied unchanged");
    }
    char cob[16];
    std::snprintf(cob, sizeof(cob), "0x%03X", l.cob_id);
    cfg.notes.push_back(me + "COB-ID " + cob + " from " + prod_who + " to " + consumers);
    if (!sync_parts.empty())
      cfg.notes.push_back(me + "synchronous: " + sync_parts +
                          "; data sampled at one SYNC reach the consumers by the next (1 SYNC period)");
    if (!l.keep_on_plc_stop) continue;
    for (const auto& s : kept_sync)
      cfg.warnings.push_back(me + "\"on_plc_stop\": \"keep\", but " + s +
                             ": the link stops when the PLC stops because SYNC stops");
    std::vector<unsigned> ids{l.producer};
    for (const auto& c : l.consumers) ids.push_back(c.node);
    for (unsigned id : ids) {
      const NodeConfig* n = find_node(cfg, id);
      if (n && n->has_heartbeat_consumer && n->heartbeat_consumer)
        cfg.warnings.push_back(me + "\"on_plc_stop\": \"keep\", but " + n->label() +
                               " watches the master's heartbeat (heartbeat_consumer), which stops when the PLC stops; "
                               "the node reacts as its 0x1029 error behaviour says");
    }
  }
}

}  // namespace

bool check_gateway_eds(ConfigSet& set, std::vector<std::string>& errors) {
  GatewayConfig& g = set.gateway;
  if (!g.enabled) return true;
  size_t before = errors.size();
  Config& upper = set.networks[g.upper];
  std::string why;
  co_dev_t* dev = parse_eds(upper.slave.eds_path, why);
  if (!dev) return true;  // check_eds_files said why
  const std::string eds = upper.slave.eds;
  for (auto& r : g.routes) {
    const Config& field = set.networks[r.field_network];
    std::string sobj = hex_object(r.slave_index, r.slave_subindex), fobj = hex_object(r.index, r.subindex);
    std::string fend = "node " + std::to_string(r.node) + (r.up ? " TPDO" : " RPDO") + " entry " + fobj +
                       " on network \"" + field.network + "\"";
    std::string who = "gateway " + r.label() + ": ";
    const co_sub_t* sub = co_dev_find_sub(dev, r.slave_index, r.slave_subindex);
    if (!sub) {
      errors.push_back(who + "slave object " + sobj + " is not in the EDS " + eds);
      continue;
    }
    unsigned access = co_sub_get_access(sub) & 0x1F;
    if (access == CO_ACCESS_CONST || access == CO_ACCESS_WO) {
      errors.push_back(who + "slave object " + sobj + " has access type " + access_name(access) +
                       "; a route needs ro or rwr (up) or rww or rw (down)");
      continue;
    }
    bool master_writes = access == CO_ACCESS_RWW || access == CO_ACCESS_RW;
    if (!r.up && !master_writes) {
      errors.push_back(who + "the upper master cannot write slave object " + sobj + " (access " +
                       access_name(access) + "), so it cannot feed " + fend);
      continue;
    }
    if (r.up && master_writes) {
      errors.push_back(who + "the upper master writes slave object " + sobj + " (access " + access_name(access) +
                       "), so it cannot take the value of " + fend + " (use an ro or rwr object)");
      continue;
    }
    co_unsigned16_t type = co_sub_get_type(sub);
    if (type != static_cast<co_unsigned16_t>(r.type)) {
      errors.push_back(who + fend + " is " + co_type_name(r.type) + " but slave object " + sobj + " is " +
                       data_type_name(type) + "; both ends need the same type");
      continue;
    }
    if (r.up)
      for (const auto& o : upper.slave.objects)
        if (o.index == r.slave_index && o.subindex == r.slave_subindex)
          errors.push_back(who + "writes slave object " + sobj + ", which is also bound to " + o.location.str() +
                           "; only one of them may write it");
  }
  auto need = [&](uint16_t index, uint8_t subindex, co_unsigned16_t type, const std::string& what) {
    const co_sub_t* sub = co_dev_find_sub(dev, index, subindex);
    if (!sub) {
      errors.push_back("gateway " + what + " needs object " + hex_object(index, subindex) + " in the EDS " + eds +
                       " (generate the slave EDS with the gateway section)");
      return false;
    }
    if (co_sub_get_type(sub) != type) {
      errors.push_back("gateway " + what + ": object " + hex_object(index, subindex) + " must be " +
                       data_type_name(type) + ", not " + data_type_name(co_sub_get_type(sub)));
      return false;
    }
    return true;
  };
  if (g.has_status) {
    unsigned k = 0;
    for (const auto& c : set.networks) {
      if (!g.is_field(c)) continue;  // slave networks and the upper master's stand-in
      if (k >= 4) {
        set.warnings.push_back("gateway status: only the first 4 master networks are published; network \"" +
                               c.network + "\" is not");
        break;
      }
      uint16_t rec = static_cast<uint16_t>(g.status_index + k), bits = static_cast<uint16_t>(g.status_index + 0x10 + k);
      // The first master network's records are required; a later network
      // whose records are both missing (EDS generated for fewer networks)
      // is left out with a warning.
      if (k > 0 && !co_dev_find_obj(dev, rec) && !co_dev_find_obj(dev, bits)) {
        set.warnings.push_back("gateway status of network \"" + c.network + "\" is not published: objects " +
                               hex_object(rec, 0).substr(0, 6) + " and " + hex_object(bits, 0).substr(0, 6) +
                               " are not in the EDS " + eds);
        ++k;
        continue;
      }
      bool ok = true;
      for (const auto& n : c.nodes)
        ok = ok && need(rec, static_cast<uint8_t>(n.node_id), CO_DEFTYPE_UNSIGNED8,
                        "status of network \"" + c.network + "\"");
      for (uint8_t i = 1; ok && i <= 4; ++i)
        ok = need(bits, i, CO_DEFTYPE_UNSIGNED32, "status of network \"" + c.network + "\"");
      ++k;
    }
  }
  if (g.sdo_bridge) {
    static const co_unsigned16_t types[] = {CO_DEFTYPE_UNSIGNED8,  CO_DEFTYPE_UNSIGNED8, CO_DEFTYPE_UNSIGNED16,
                                            CO_DEFTYPE_UNSIGNED8,  CO_DEFTYPE_UNSIGNED32, CO_DEFTYPE_UNSIGNED8,
                                            CO_DEFTYPE_UNSIGNED8,  CO_DEFTYPE_UNSIGNED8, CO_DEFTYPE_UNSIGNED32};
    for (uint8_t i = 1; i <= 9; ++i)
      if (!need(g.sdo_bridge_index, i, types[i - 1], "sdo_bridge")) break;
  }
  co_dev_destroy(dev);
  return errors.size() == before;
}

bool eds_sub_value(const NodeConfig& n, uint16_t index, uint8_t subindex, uint64_t& value) {
  std::string why;
  co_dev_t* dev = parse_eds(n.eds_path, why);
  if (!dev) return false;
  co_dev_set_id(dev, static_cast<co_unsigned8_t>(n.node_id));
  const co_sub_t* sub = co_dev_find_sub(dev, index, subindex);
  bool ok = sub && sub_value(sub, value);
  co_dev_destroy(dev);
  return ok;
}

bool eds_sub_type(const NodeConfig& n, uint16_t index, uint8_t subindex, uint16_t& type) {
  std::string why;
  co_dev_t* dev = parse_eds(n.eds_path, why);
  if (!dev) return false;
  const co_sub_t* sub = co_dev_find_sub(dev, index, subindex);
  if (sub) type = co_sub_get_type(sub);
  co_dev_destroy(dev);
  return sub != nullptr;
}

unsigned co_type_bytes(uint16_t type) {
  switch (type) {
    case CO_DEFTYPE_BOOLEAN:
    case CO_DEFTYPE_INTEGER8:
    case CO_DEFTYPE_UNSIGNED8: return 1;
    case CO_DEFTYPE_INTEGER16:
    case CO_DEFTYPE_UNSIGNED16: return 2;
    case CO_DEFTYPE_INTEGER24:
    case CO_DEFTYPE_UNSIGNED24: return 3;
    case CO_DEFTYPE_INTEGER32:
    case CO_DEFTYPE_UNSIGNED32:
    case CO_DEFTYPE_REAL32: return 4;
    case CO_DEFTYPE_INTEGER40:
    case CO_DEFTYPE_UNSIGNED40: return 5;
    case CO_DEFTYPE_INTEGER48:
    case CO_DEFTYPE_UNSIGNED48:
    case CO_DEFTYPE_TIME_OF_DAY:
    case CO_DEFTYPE_TIME_DIFF: return 6;
    case CO_DEFTYPE_INTEGER56:
    case CO_DEFTYPE_UNSIGNED56: return 7;
    case CO_DEFTYPE_INTEGER64:
    case CO_DEFTYPE_UNSIGNED64:
    case CO_DEFTYPE_REAL64: return 8;
    default: return 0;
  }
}

bool eds_identity(const NodeConfig& n, uint32_t& vendor_id, uint32_t& product_code) {
  std::string why;
  co_dev_t* dev = parse_eds(n.eds_path, why);
  if (!dev) return false;
  vendor_id = co_dev_get_vendor_id(dev);
  product_code = co_dev_get_product_code(dev);
  co_dev_destroy(dev);
  return true;
}

bool check_eds_files(Config& cfg, std::vector<std::string>& errors) {
  size_t before = errors.size();
  if (cfg.is_slave()) {
    check_slave(cfg, errors);
    return errors.size() == before;
  }
  // Kept until the end: the link and heartbeat watch checks read two nodes' EDS files.
  std::map<unsigned, co_dev_t*> devs;
  for (auto& n : cfg.nodes) {
    struct stat st;
    if (stat(n.eds_path.c_str(), &st) != 0 || !S_ISREG(st.st_mode)) {
      std::string looked;
      for (size_t i = 1; i < n.eds_candidates.size(); ++i) looked += (i == 1 ? " (also looked for " : ", ") + n.eds_candidates[i];
      if (!looked.empty()) looked += ")";
      errors.push_back("node " + std::to_string(n.node_id) + ": EDS file " + n.eds_path + " not found" + looked);
      continue;
    }
    std::string why;
    co_dev_t* dev = parse_eds(n.eds_path, why);
    if (!dev) {
      errors.push_back("node " + std::to_string(n.node_id) + ": EDS file " + n.eds_path +
                       " cannot be parsed: " + why);
      continue;
    }
    co_dev_set_id(dev, static_cast<co_unsigned8_t>(n.node_id));
    check_pdos(cfg, n, dev, true, errors);
    check_pdos(cfg, n, dev, false, errors);
    find_fixed_pdo_params(cfg, n, dev);
    check_sdos(n, dev, errors);
    check_sdo_variables(n, dev, errors);
    check_config_objects(n, dev, errors);
    check_supervision(n, dev, errors);
    n.eds_vendor_id = co_dev_get_vendor_id(dev);
    n.eds_product_code = co_dev_get_product_code(dev);
    n.eds_revision_number = co_dev_get_revision(dev);
    if (n.lss_assign && !co_dev_get_lss(dev))
      cfg.warnings.push_back(n.label() + ": its EDS does not say LSS_Supported=1; LSS assignment may not work with "
                                         "this device");
    if (devs.count(n.node_id))
      co_dev_destroy(dev);  // a node ID twice, reported by the parser
    else
      devs[n.node_id] = dev;
  }
  check_lss_addresses(cfg, errors);
  check_heartbeat_watch(cfg, devs, errors);
  check_links(cfg, devs, errors);
  for (auto& d : devs) co_dev_destroy(d.second);
  return errors.size() == before;
}

}  // namespace canopen_plugin
