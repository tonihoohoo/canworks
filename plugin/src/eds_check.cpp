#include "eds_check.h"

#include <cstdarg>
#include <cstdio>
#include <sys/stat.h>

#include <lely/co/dcf.h>
#include <lely/co/dev.h>
#include <lely/co/obj.h>
#include <lely/co/type.h>
#include <lely/util/diag.h>

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
      bool used = false;
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
    // Without SYNC, a PDO left at a synchronous EDS transmission type would
    // never move; the plugin does not pick another type on its own.
    uint64_t tt = 0;
    const co_sub_t* tt_sub = co_dev_find_sub(dev, comm, 2);
    if (!cfg.master.sync_period_us && !p.has_transmission && tt_sub && sub_value(tt_sub, tt) &&
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

}  // namespace

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
    n.eds_vendor_id = co_dev_get_vendor_id(dev);
    n.eds_product_code = co_dev_get_product_code(dev);
    n.eds_revision_number = co_dev_get_revision(dev);
    if (n.lss_assign && !co_dev_get_lss(dev))
      cfg.warnings.push_back(n.label() + ": its EDS does not say LSS_Supported=1; LSS assignment may not work with "
                                         "this device");
    co_dev_destroy(dev);
  }
  check_lss_addresses(cfg, errors);
  return errors.size() == before;
}

}  // namespace canopen_plugin
