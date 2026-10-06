// pingpong_slave.hpp - the slave of the Lely CANopen C++ tutorial: whatever
// the master writes to 0x4000 (RPDO 1) is copied to 0x4001 (TPDO 1).

#ifndef PINGPONG_SLAVE_HPP
#define PINGPONG_SLAVE_HPP

#include <lely/coapp/slave.hpp>

class PingPongSlave : public lely::canopen::BasicSlave {
 public:
  using BasicSlave::BasicSlave;

 protected:
  void OnWrite(uint16_t idx, uint8_t subidx) noexcept override {
    if (idx == 0x4000 && subidx == 0) {
      uint32_t val = (*this)[idx][subidx];
      (*this)[0x4001][0] = val;
    }
  }
};

#endif  // PINGPONG_SLAVE_HPP
