// sim_od.h - reading and writing a simulated device's object dictionary by
// number, whatever the object's data type (Lely's C object dictionary API).
//
// Values are doubles for the numeric types (64-bit integers beyond 2^53 lose
// precision, which a simulation can live with) and strings for
// VISIBLE_STRING. Writes convert as docs/simulator.md says: rounded for
// integer types, clamped to the type's range, BOOLEAN is value != 0. These
// writes bypass the SDO indications, as device firmware writing its own
// dictionary does.

#ifndef CANOPEN_SIM_OD_H
#define CANOPEN_SIM_OD_H

#include <cstdint>
#include <string>
#include <utility>
#include <vector>

struct __co_dev;
struct __co_sub;

namespace canopen_sim {

struct Value {
  bool is_string = false;
  double num = 0;
  std::string str;
  static Value number(double v) {
    Value x;
    x.num = v;
    return x;
  }
  static Value text(const std::string& s) {
    Value x;
    x.is_string = true;
    x.str = s;
    return x;
  }
  bool operator==(const Value& o) const { return is_string == o.is_string && (is_string ? str == o.str : num == o.num); }
};

enum class OdKind { Missing, Number, String, Other };

bool od_has(__co_dev* dev, uint16_t index, uint8_t subindex);
OdKind od_kind(__co_dev* dev, uint16_t index, uint8_t subindex);
// The CiA 301 data type name ("UNSIGNED16", ...), "" when missing.
std::string od_type_name(__co_dev* dev, uint16_t index, uint8_t subindex);
uint16_t od_type(__co_dev* dev, uint16_t index, uint8_t subindex);
// The name of a data type code (CO_DEFTYPE_*), "" for 0.
std::string type_name(uint16_t type);
// Why `v` cannot be set on an object of data type `type`, "" when it fits:
// text for a number, a number for text, or a number outside the type's range
// (an explicit value is refused where a source's is clamped).
std::string value_misfit(uint16_t type, const Value& v);

bool od_read(__co_dev* dev, uint16_t index, uint8_t subindex, Value& out);
// Numeric read; 0 when missing or not numeric.
double od_number(__co_dev* dev, uint16_t index, uint8_t subindex);
// Writes with conversion. Returns false when the object is missing or the
// value does not fit its kind (a string for a number, ...). `changed` tells
// whether the stored value differs from before.
bool od_write(__co_dev* dev, uint16_t index, uint8_t subindex, const Value& v, bool* changed = nullptr);
// The EDS LowLimit/HighLimit, or the type's range; false for non-numeric.
bool od_limits(__co_dev* dev, uint16_t index, uint8_t subindex, double& lo, double& hi);
// Access type letters as in the EDS: "ro", "wo", "rw", "rwr", "rww", "const".
std::string od_access(__co_dev* dev, uint16_t index, uint8_t subindex);
// Every sub-object of the dictionary, in order.
std::vector<std::pair<uint16_t, uint8_t>> od_objects(__co_dev* dev);

}  // namespace canopen_sim

#endif  // CANOPEN_SIM_OD_H
