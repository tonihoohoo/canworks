#include "sim_od.h"

#include <cmath>
#include <cstring>
#include <limits>

#include <lely/co/dev.h>
#include <lely/co/obj.h>
#include <lely/co/type.h>
#include <lely/co/val.h>

namespace canopen_sim {

namespace {

template <class T>
T clamp_round(double v) {
  if (!std::isfinite(v)) return T(0);
  double r = std::numeric_limits<T>::is_integer ? std::round(v) : v;
  double lo = static_cast<double>(std::numeric_limits<T>::lowest());
  double hi = static_cast<double>(std::numeric_limits<T>::max());
  if (r <= lo) return std::numeric_limits<T>::lowest();
  if (r >= hi) return std::numeric_limits<T>::max();
  return static_cast<T>(r);
}

// Signed/unsigned integer of an odd width (24, 40, 48, 56 bits).
double clamp_bits(double v, int bits, bool is_signed) {
  if (!std::isfinite(v)) return 0;
  double r = std::round(v);
  double lo = is_signed ? -std::ldexp(1.0, bits - 1) : 0;
  double hi = is_signed ? std::ldexp(1.0, bits - 1) - 1 : std::ldexp(1.0, bits) - 1;
  return r < lo ? lo : (r > hi ? hi : r);
}

bool type_range(uint16_t t, double& lo, double& hi) {
  switch (t) {
    case CO_DEFTYPE_BOOLEAN: lo = 0; hi = 1; return true;
    case CO_DEFTYPE_INTEGER8: lo = -128; hi = 127; return true;
    case CO_DEFTYPE_INTEGER16: lo = -32768; hi = 32767; return true;
    case CO_DEFTYPE_INTEGER24: lo = -8388608; hi = 8388607; return true;
    case CO_DEFTYPE_INTEGER32: lo = -2147483648.0; hi = 2147483647.0; return true;
    case CO_DEFTYPE_INTEGER40: lo = -std::ldexp(1.0, 39); hi = std::ldexp(1.0, 39) - 1; return true;
    case CO_DEFTYPE_INTEGER48: lo = -std::ldexp(1.0, 47); hi = std::ldexp(1.0, 47) - 1; return true;
    case CO_DEFTYPE_INTEGER56: lo = -std::ldexp(1.0, 55); hi = std::ldexp(1.0, 55) - 1; return true;
    case CO_DEFTYPE_INTEGER64: lo = -9.223372036854775808e18; hi = 9.223372036854775807e18; return true;
    case CO_DEFTYPE_UNSIGNED8: lo = 0; hi = 255; return true;
    case CO_DEFTYPE_UNSIGNED16: lo = 0; hi = 65535; return true;
    case CO_DEFTYPE_UNSIGNED24: lo = 0; hi = 16777215; return true;
    case CO_DEFTYPE_UNSIGNED32: lo = 0; hi = 4294967295.0; return true;
    case CO_DEFTYPE_UNSIGNED40: lo = 0; hi = std::ldexp(1.0, 40) - 1; return true;
    case CO_DEFTYPE_UNSIGNED48: lo = 0; hi = std::ldexp(1.0, 48) - 1; return true;
    case CO_DEFTYPE_UNSIGNED56: lo = 0; hi = std::ldexp(1.0, 56) - 1; return true;
    case CO_DEFTYPE_UNSIGNED64: lo = 0; hi = 1.8446744073709551615e19; return true;
    case CO_DEFTYPE_REAL32: lo = -3.4e38; hi = 3.4e38; return true;
    case CO_DEFTYPE_REAL64: lo = -1.7e308; hi = 1.7e308; return true;
    default: return false;
  }
}

double number_of(uint16_t t, const void* p) {
  if (!p) return 0;
  switch (t) {
    case CO_DEFTYPE_BOOLEAN: return *static_cast<const co_boolean_t*>(p) ? 1 : 0;
    case CO_DEFTYPE_INTEGER8: return *static_cast<const co_integer8_t*>(p);
    case CO_DEFTYPE_INTEGER16: return *static_cast<const co_integer16_t*>(p);
    case CO_DEFTYPE_INTEGER24: return *static_cast<const co_integer24_t*>(p);
    case CO_DEFTYPE_INTEGER32: return *static_cast<const co_integer32_t*>(p);
    case CO_DEFTYPE_INTEGER40: return static_cast<double>(*static_cast<const co_integer40_t*>(p));
    case CO_DEFTYPE_INTEGER48: return static_cast<double>(*static_cast<const co_integer48_t*>(p));
    case CO_DEFTYPE_INTEGER56: return static_cast<double>(*static_cast<const co_integer56_t*>(p));
    case CO_DEFTYPE_INTEGER64: return static_cast<double>(*static_cast<const co_integer64_t*>(p));
    case CO_DEFTYPE_UNSIGNED8: return *static_cast<const co_unsigned8_t*>(p);
    case CO_DEFTYPE_UNSIGNED16: return *static_cast<const co_unsigned16_t*>(p);
    case CO_DEFTYPE_UNSIGNED24: return *static_cast<const co_unsigned24_t*>(p);
    case CO_DEFTYPE_UNSIGNED32: return *static_cast<const co_unsigned32_t*>(p);
    case CO_DEFTYPE_UNSIGNED40: return static_cast<double>(*static_cast<const co_unsigned40_t*>(p));
    case CO_DEFTYPE_UNSIGNED48: return static_cast<double>(*static_cast<const co_unsigned48_t*>(p));
    case CO_DEFTYPE_UNSIGNED56: return static_cast<double>(*static_cast<const co_unsigned56_t*>(p));
    case CO_DEFTYPE_UNSIGNED64: return static_cast<double>(*static_cast<const co_unsigned64_t*>(p));
    case CO_DEFTYPE_REAL32: return *static_cast<const co_real32_t*>(p);
    case CO_DEFTYPE_REAL64: return *static_cast<const co_real64_t*>(p);
    default: return 0;
  }
}

template <class T>
bool set_typed(co_sub_t* sub, T v, bool* changed) {
  const void* old = co_sub_get_val(sub);
  if (changed) *changed = !old || std::memcmp(old, &v, sizeof v) != 0;
  return co_sub_set_val(sub, &v, sizeof v) == sizeof v;
}

}  // namespace

namespace {
co_sub_t* od_sub(__co_dev* dev, uint16_t index, uint8_t subindex) {
  if (!dev) return nullptr;
  return co_dev_find_sub(reinterpret_cast<co_dev_t*>(dev), index, subindex);
}
}  // namespace

bool od_has(__co_dev* dev, uint16_t index, uint8_t subindex) { return od_sub(dev, index, subindex) != nullptr; }

uint16_t od_type(__co_dev* dev, uint16_t index, uint8_t subindex) {
  co_sub_t* s = od_sub(dev, index, subindex);
  return s ? co_sub_get_type(s) : 0;
}

OdKind od_kind(__co_dev* dev, uint16_t index, uint8_t subindex) {
  co_sub_t* s = od_sub(dev, index, subindex);
  if (!s) return OdKind::Missing;
  uint16_t t = co_sub_get_type(s);
  double lo, hi;
  if (type_range(t, lo, hi)) return OdKind::Number;
  if (t == CO_DEFTYPE_VISIBLE_STRING) return OdKind::String;
  return OdKind::Other;
}

std::string od_type_name(__co_dev* dev, uint16_t index, uint8_t subindex) {
  switch (od_type(dev, index, subindex)) {
    case CO_DEFTYPE_BOOLEAN: return "BOOLEAN";
    case CO_DEFTYPE_INTEGER8: return "INTEGER8";
    case CO_DEFTYPE_INTEGER16: return "INTEGER16";
    case CO_DEFTYPE_INTEGER24: return "INTEGER24";
    case CO_DEFTYPE_INTEGER32: return "INTEGER32";
    case CO_DEFTYPE_INTEGER40: return "INTEGER40";
    case CO_DEFTYPE_INTEGER48: return "INTEGER48";
    case CO_DEFTYPE_INTEGER56: return "INTEGER56";
    case CO_DEFTYPE_INTEGER64: return "INTEGER64";
    case CO_DEFTYPE_UNSIGNED8: return "UNSIGNED8";
    case CO_DEFTYPE_UNSIGNED16: return "UNSIGNED16";
    case CO_DEFTYPE_UNSIGNED24: return "UNSIGNED24";
    case CO_DEFTYPE_UNSIGNED32: return "UNSIGNED32";
    case CO_DEFTYPE_UNSIGNED40: return "UNSIGNED40";
    case CO_DEFTYPE_UNSIGNED48: return "UNSIGNED48";
    case CO_DEFTYPE_UNSIGNED56: return "UNSIGNED56";
    case CO_DEFTYPE_UNSIGNED64: return "UNSIGNED64";
    case CO_DEFTYPE_REAL32: return "REAL32";
    case CO_DEFTYPE_REAL64: return "REAL64";
    case CO_DEFTYPE_VISIBLE_STRING: return "VISIBLE_STRING";
    case CO_DEFTYPE_OCTET_STRING: return "OCTET_STRING";
    case CO_DEFTYPE_UNICODE_STRING: return "UNICODE_STRING";
    case CO_DEFTYPE_DOMAIN: return "DOMAIN";
    case 0: return "";
    default: return "OTHER";
  }
}

bool od_read(__co_dev* dev, uint16_t index, uint8_t subindex, Value& out) {
  co_sub_t* s = od_sub(dev, index, subindex);
  if (!s) return false;
  uint16_t t = co_sub_get_type(s);
  const void* p = co_sub_get_val(s);
  double lo, hi;
  if (type_range(t, lo, hi)) {
    out = Value::number(number_of(t, p));
    return true;
  }
  if (t == CO_DEFTYPE_VISIBLE_STRING) {
    const char* str = p ? *static_cast<const char* const*>(p) : nullptr;
    out = Value::text(str ? std::string(str, co_val_sizeof(t, p)) : "");
    return true;
  }
  return false;
}

double od_number(__co_dev* dev, uint16_t index, uint8_t subindex) {
  Value v;
  if (!od_read(dev, index, subindex, v) || v.is_string) return 0;
  return v.num;
}

bool od_write(__co_dev* dev, uint16_t index, uint8_t subindex, const Value& v, bool* changed) {
  co_sub_t* s = od_sub(dev, index, subindex);
  if (changed) *changed = false;
  if (!s) return false;
  uint16_t t = co_sub_get_type(s);
  if (t == CO_DEFTYPE_VISIBLE_STRING) {
    if (!v.is_string) return false;
    Value old;
    od_read(dev, index, subindex, old);
    if (changed) *changed = !(old == v);
    return co_sub_set_val(s, v.str.data(), v.str.size()) == v.str.size();
  }
  if (v.is_string) return false;
  double x = v.num;
  switch (t) {
    case CO_DEFTYPE_BOOLEAN: return set_typed<co_boolean_t>(s, x != 0 && std::isfinite(x) ? 1 : 0, changed);
    case CO_DEFTYPE_INTEGER8: return set_typed<co_integer8_t>(s, clamp_round<int8_t>(x), changed);
    case CO_DEFTYPE_INTEGER16: return set_typed<co_integer16_t>(s, clamp_round<int16_t>(x), changed);
    case CO_DEFTYPE_INTEGER24: return set_typed<co_integer24_t>(s, static_cast<co_integer24_t>(clamp_bits(x, 24, true)), changed);
    case CO_DEFTYPE_INTEGER32: return set_typed<co_integer32_t>(s, clamp_round<int32_t>(x), changed);
    case CO_DEFTYPE_INTEGER40: return set_typed<co_integer40_t>(s, static_cast<co_integer40_t>(clamp_bits(x, 40, true)), changed);
    case CO_DEFTYPE_INTEGER48: return set_typed<co_integer48_t>(s, static_cast<co_integer48_t>(clamp_bits(x, 48, true)), changed);
    case CO_DEFTYPE_INTEGER56: return set_typed<co_integer56_t>(s, static_cast<co_integer56_t>(clamp_bits(x, 56, true)), changed);
    case CO_DEFTYPE_INTEGER64: return set_typed<co_integer64_t>(s, clamp_round<int64_t>(x), changed);
    case CO_DEFTYPE_UNSIGNED8: return set_typed<co_unsigned8_t>(s, clamp_round<uint8_t>(x), changed);
    case CO_DEFTYPE_UNSIGNED16: return set_typed<co_unsigned16_t>(s, clamp_round<uint16_t>(x), changed);
    case CO_DEFTYPE_UNSIGNED24: return set_typed<co_unsigned24_t>(s, static_cast<co_unsigned24_t>(clamp_bits(x, 24, false)), changed);
    case CO_DEFTYPE_UNSIGNED32: return set_typed<co_unsigned32_t>(s, clamp_round<uint32_t>(x), changed);
    case CO_DEFTYPE_UNSIGNED40: return set_typed<co_unsigned40_t>(s, static_cast<co_unsigned40_t>(clamp_bits(x, 40, false)), changed);
    case CO_DEFTYPE_UNSIGNED48: return set_typed<co_unsigned48_t>(s, static_cast<co_unsigned48_t>(clamp_bits(x, 48, false)), changed);
    case CO_DEFTYPE_UNSIGNED56: return set_typed<co_unsigned56_t>(s, static_cast<co_unsigned56_t>(clamp_bits(x, 56, false)), changed);
    case CO_DEFTYPE_UNSIGNED64: return set_typed<co_unsigned64_t>(s, clamp_round<uint64_t>(x), changed);
    case CO_DEFTYPE_REAL32: return set_typed<co_real32_t>(s, std::isfinite(x) ? clamp_round<float>(x) : 0.0f, changed);
    case CO_DEFTYPE_REAL64: return set_typed<co_real64_t>(s, std::isfinite(x) ? x : 0.0, changed);
    default: return false;
  }
}

bool od_limits(__co_dev* dev, uint16_t index, uint8_t subindex, double& lo, double& hi) {
  co_sub_t* s = od_sub(dev, index, subindex);
  if (!s) return false;
  uint16_t t = co_sub_get_type(s);
  if (!type_range(t, lo, hi)) return false;
  const void* mn = co_sub_get_min(s);
  const void* mx = co_sub_get_max(s);
  // Lely fills absent limits with the type's own range.
  if (mn) lo = number_of(t, mn);
  if (mx) hi = number_of(t, mx);
  if (lo > hi) type_range(t, lo, hi);
  return true;
}

std::string od_access(__co_dev* dev, uint16_t index, uint8_t subindex) {
  co_sub_t* s = od_sub(dev, index, subindex);
  if (!s) return "";
  switch (co_sub_get_access(s)) {
    case CO_ACCESS_RO: return "ro";
    case CO_ACCESS_WO: return "wo";
    case CO_ACCESS_RW: return "rw";
    case CO_ACCESS_RWR: return "rwr";
    case CO_ACCESS_RWW: return "rww";
    case CO_ACCESS_CONST: return "const";
    default: return "";
  }
}

}  // namespace canopen_sim
