// sensor_slave.hpp - a simulated measuring device (e.g. a CiA 404 temperature
// or current module) on Lely's slave stack, driven by the device's own vendor
// EDS. The object dictionary, NMT, heartbeat, SDO server and PDO engine all
// come from that EDS; this class only makes the measured values move.
//
// Every `Signal` is a triangle wave written to one object once per period, so
// a test knows the range each value stays in. SendEmcy()/ResetEmcy() make it
// report a fault and clear it again. `blank_pdo_mapping()` turns an
// EDS into one whose PDOs start with nothing mapped, for checking that the
// master builds the whole PDO map from its own configuration.

#ifndef SENSOR_SLAVE_HPP
#define SENSOR_SLAVE_HPP

#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <regex>
#include <sstream>
#include <string>
#include <system_error>
#include <typeinfo>
#include <vector>

#include <lely/coapp/slave.hpp>
#include <lely/co/emcy.hpp>
#include <lely/co/nmt.hpp>
#include <lely/io2/tqueue.hpp>

struct SensorSignal {
  uint16_t index = 0;
  uint8_t subindex = 0;
  int64_t min = 0, max = 0, step = 1;
};

// Parses "0x7130:1=200..260" or "0x7130:1=200..260/2" (step 2).
inline bool parse_signal(const std::string& s, SensorSignal& out) {
  static const std::regex re(R"(^\s*(0x[0-9a-fA-F]+|\d+):(\d+)=(-?\d+)\.\.(-?\d+)(?:/(\d+))?\s*$)");
  std::smatch m;
  if (!std::regex_match(s, m, re)) return false;
  out.index = static_cast<uint16_t>(std::stoul(m[1], nullptr, 0));
  out.subindex = static_cast<uint8_t>(std::stoul(m[2]));
  out.min = std::stoll(m[3]);
  out.max = std::stoll(m[4]);
  out.step = m[5].matched ? std::stoll(m[5]) : 1;
  return out.min <= out.max && out.step > 0;
}

// The EDS text with every PDO mapping parameter (0x1600-0x17FF and
// 0x1A00-0x1BFF) defaulting to zero mapped objects. Everything else, including
// the mapping entries themselves, is left as the vendor wrote it.
inline std::string blank_pdo_mapping(const std::string& eds) {
  std::istringstream in(eds);
  std::ostringstream out;
  std::string line;
  bool in_sub0 = false;
  static const std::regex sect(R"(^\s*\[(1[67]|1[AB])[0-9A-Fa-f]{2}sub0\]\s*$)", std::regex::icase);
  static const std::regex dflt(R"(^\s*DefaultValue\s*=.*$)", std::regex::icase);
  while (std::getline(in, line)) {
    std::string bare = line;
    if (!bare.empty() && bare.back() == '\r') bare.pop_back();
    if (!bare.empty() && bare[0] == '[') in_sub0 = std::regex_match(bare, sect);
    if (in_sub0 && std::regex_match(bare, dflt)) {
      out << "DefaultValue=0\n";
      continue;
    }
    out << line << '\n';
  }
  return out.str();
}

class SensorSlave : public lely::canopen::BasicSlave {
 public:
  SensorSlave(lely::io::TimerBase& timer, lely::io::CanChannelBase& chan, const std::string& eds,
              uint8_t id, std::vector<SensorSignal> signals,
              std::chrono::milliseconds period = std::chrono::milliseconds(100))
      : BasicSlave(timer, chan, eds, "", id), signals_(std::move(signals)), period_(period) {
    for (const auto& s : signals_) values_.push_back(s.min);
    dirs_.assign(signals_.size(), 1);
  }

  // Starts updating the signals. Call from the slave's event loop thread.
  void StartSignals() { Tick(); }

  // The signal's current value (as last written to the object dictionary).
  int64_t value(size_t i) const { return values_.at(i); }

  // A value in the device's own object dictionary. Call from the slave's
  // event loop thread.
  template <class T>
  T Get(uint16_t idx, uint8_t subidx) {
    return (*this)[idx][subidx].template Get<T>();
  }

  // Sends an emergency message, as the device does on a fault (e.g. a sensor
  // break). Call from the slave's event loop thread.
  void SendEmcy(uint16_t eec, uint8_t er, const uint8_t msef[5] = nullptr) { Error(eec, er, msef); }

  // Clears every active error and sends the error reset EMCY (code 0x0000).
  // Call from the slave's event loop thread.
  // (coapp's __co_nmt and the C++ co_nmt_t name the same Lely object.)
  void ResetEmcy() { co_emcy_clear(co_nmt_get_emcy(reinterpret_cast<co_nmt_t*>(nmt()))); }

 private:
  void Tick() {
    for (size_t i = 0; i < signals_.size(); ++i) {
      Write(signals_[i], values_[i]);
      const auto& s = signals_[i];
      int64_t next = values_[i] + dirs_[i] * s.step;
      if (next > s.max || next < s.min) {
        dirs_[i] = -dirs_[i];
        next = values_[i] + dirs_[i] * s.step;
        if (next > s.max || next < s.min) next = values_[i];
      }
      values_[i] = next;
    }
    SubmitWait(period_, [this](std::error_code ec) {
      if (!ec) Tick();
    });
  }

  // Writes v with the object's own data type, as the device firmware would.
  void Write(const SensorSignal& s, int64_t v) {
    ::std::error_code ec;
    const ::std::type_info& t = Type(s.index, s.subindex, ec);
    auto o = (*this)[s.index][s.subindex];
    if (ec) {
      Warn(s, "does not exist");
    } else if (t == typeid(bool)) {
      o = static_cast<bool>(v != 0);
    } else if (t == typeid(int8_t)) {
      o = static_cast<int8_t>(v);
    } else if (t == typeid(int16_t)) {
      o = static_cast<int16_t>(v);
    } else if (t == typeid(int32_t)) {
      o = static_cast<int32_t>(v);
    } else if (t == typeid(int64_t)) {
      o = static_cast<int64_t>(v);
    } else if (t == typeid(uint8_t)) {
      o = static_cast<uint8_t>(v);
    } else if (t == typeid(uint16_t)) {
      o = static_cast<uint16_t>(v);
    } else if (t == typeid(uint32_t)) {
      o = static_cast<uint32_t>(v);
    } else if (t == typeid(uint64_t)) {
      o = static_cast<uint64_t>(v);
    } else if (t == typeid(float)) {
      o = static_cast<float>(v);
    } else if (t == typeid(double)) {
      o = static_cast<double>(v);
    } else {
      Warn(s, "has a type the simulator cannot write");
    }
  }

  void Warn(const SensorSignal& s, const char* what) {
    if (!warned_) std::fprintf(stderr, "sensor_slave: object 0x%04X:%u %s\n", s.index, s.subindex, what);
    warned_ = true;
  }

  std::vector<SensorSignal> signals_;
  std::vector<int64_t> values_;
  std::vector<int> dirs_;
  std::chrono::milliseconds period_;
  bool warned_ = false;
};

#endif  // SENSOR_SLAVE_HPP
