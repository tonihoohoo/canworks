// cia402_slave.hpp - a CiA 402 drive played by a Lely slave, for the
// virtual-bus test of the CiA 402 example (sim_tests: sim_cia402_demo).
//
// The same drive as test/cia402/drive_model.st: the power state machine,
// profile position (mode 1), profile velocity (mode 3) and homing (mode 6,
// method 35: the current position is home), halt (controlword bit 8) and a
// fault that the test raises. The drive moves every 10 ms and sends its
// statusword (TPDO 1, event-driven) whenever it changes; position and velocity
// go out with their TPDO event timers.

#ifndef CIA402_SLAVE_HPP
#define CIA402_SLAVE_HPP

#include <lely/coapp/slave.hpp>

#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <string>

class Cia402Slave : public lely::canopen::BasicSlave {
 public:
  Cia402Slave(lely::io::TimerBase& timer, lely::io::CanChannelBase& chan, const std::string& eds, uint8_t id)
      : BasicSlave(timer, chan, eds, "", id) {}

  // Call on the slave's thread once it runs.
  void Start() { Tick(); }

  std::atomic<bool> fault{false};
  std::atomic<int> state{1};  // 1 switch on disabled, 2 ready, 3 switched on, 4 enabled, 5 quick stop, 6 fault
  std::atomic<int32_t> position{0};
  std::atomic<int32_t> velocity{0};
  std::atomic<int> fault_resets{0};

 private:
  static constexpr double kDt = 0.01;

  void Tick() {
    Step();
    SubmitWait(std::chrono::milliseconds(10), [this](std::error_code ec) {
      if (!ec) Tick();
    });
  }

  void Step() {
    auto& self = *this;
    uint16_t cw = self[0x6040][0];
    int8_t mode = self[0x6060][0];
    int s = state;

    if (fault && s != 6) {
      s = 6;
    } else if (s == 6) {
      if ((cw & 0x80) && !(last_cw_ & 0x80) && !fault) {
        s = 1;
        ++fault_resets;
      }
    } else if ((cw & 0x82) == 0x00) {
      s = 1;
    } else if ((cw & 0x86) == 0x02) {
      s = s == 4 ? 5 : 1;
    } else if ((cw & 0x87) == 0x06) {
      s = 2;
    } else if ((cw & 0x8F) == 0x07) {
      if (s == 2 || s == 4) s = 3;
    } else if ((cw & 0x8F) == 0x0F) {
      if (s == 3 || s == 5) s = 4;
    }

    double vel = 0;
    if (s != 4) {
      ack_ = false;
      target_ = pos_;
    } else if (cw & 0x100) {
      vel = 0;
    } else if (mode == 1) {
      if ((cw & 0x10) && !(last_cw_ & 0x10)) {
        int32_t t = self[0x607A][0];
        target_ = (cw & 0x40) ? target_ + t : t;
        ack_ = true;
      } else if (!(cw & 0x10)) {
        ack_ = false;
      }
      uint32_t pv = self[0x6081][0];
      double step = pv * kDt;
      if (std::fabs(target_ - pos_) <= step)
        vel = (target_ - pos_) / kDt;
      else
        vel = target_ > pos_ ? pv : -static_cast<double>(pv);
    } else if (mode == 3) {
      int32_t tv = self[0x60FF][0];
      vel = tv;
    } else if (mode == 6) {
      if ((cw & 0x10) && !(last_cw_ & 0x10)) {
        pos_ = 0;
        target_ = 0;
        homed_ = true;
      } else if (!(cw & 0x10)) {
        homed_ = false;
      }
    }
    pos_ += vel * kDt;

    static const uint16_t kWords[] = {0, 0x0250, 0x0231, 0x0233, 0x0237, 0x0217, 0x0218};
    uint16_t sw = kWords[s];
    if (vel == 0) sw |= 0x4000;
    if (s == 4) {
      if (mode == 1) {
        if (ack_) sw |= 0x1000;
        if (pos_ == target_) sw |= 0x0400;
      } else if (mode == 3) {
        if (vel == 0) sw |= 0x1000;
        if (vel == static_cast<double>(static_cast<int32_t>(self[0x60FF][0]))) sw |= 0x0400;
      } else if (mode == 6 && homed_) {
        sw |= 0x1400;
      }
    }
    int32_t p = static_cast<int32_t>(std::lround(pos_));
    int32_t v = static_cast<int32_t>(std::lround(vel));
    self[0x6064][0] = p;
    self[0x606C][0] = v;
    if (static_cast<int8_t>(self[0x6061][0]) != mode) {
      self[0x6061][0] = mode;
      SetEvent(0x6061, 0);
    }
    if (static_cast<uint16_t>(self[0x6041][0]) != sw) {
      self[0x6041][0] = sw;
      SetEvent(0x6041, 0);
    }
    state = s;
    position = p;
    velocity = v;
    last_cw_ = cw;
  }

  uint16_t last_cw_ = 0;
  double pos_ = 0, target_ = 0;
  bool ack_ = false, homed_ = false;
};

#endif  // CIA402_SLAVE_HPP
