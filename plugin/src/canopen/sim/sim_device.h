// sim_device.h - one simulated CANopen device on Lely's slave stack.
//
// The object dictionary, NMT, heartbeat or node guarding, SDO server, PDOs
// and EMCY all come from Lely, driven by the device's EDS or DCF. Stored
// parameters (0x1010 save, 0x1011 load), the LSS-stored node ID, TPDO events
// and the node ID conflict guard come from the plugin's own slave device
// (slave_device.h), the one a slave network runs; a simulated device starts
// like a free-standing one (Lely's autostart, LSS bit timing allowed). This
// class adds what a simulation needs on top (docs/simulator.md):
// - a send hook on the device's CAN network, through which faults drop
//   frames (heartbeat stop, TPDO stop) or hold them (SDO answer delay);
// - SDO indications chained in front of Lely's own, for SDO abort rules and
//   refusing writes while OPERATIONAL;
// - identity / device type overrides, applied after every reset.
// Everything runs on the engine's event loop thread.

#ifndef CANOPEN_SIM_DEVICE_H
#define CANOPEN_SIM_DEVICE_H

#include <chrono>
#include <cstdint>
#include <deque>
#include <functional>
#include <map>
#include <memory>
#include <set>
#include <string>
#include <vector>

#include "slave_device.h"

namespace canopen_sim {

// Parameters saved with 0x1010 and a node ID stored over LSS; they outlive a
// device's power cycles (and, in the plugin, PLC stop and start).
using StoredState = canopen_plugin::SlaveStore;

struct SdoRule {
  uint16_t index = 0;
  uint8_t subindex = 0;
  bool on_read = true, on_write = true;
  uint32_t code = 0;
  int count = -1;  // -1: until removed
};

class SimDevice : public canopen_plugin::SlaveDevice {
 public:
  using Clock = std::chrono::steady_clock;

  // `node_id` 1-127, or 0xFF for a device without a node ID (LSS).
  SimDevice(ev_exec_t* exec, lely::io::TimerBase& timer, lely::io::CanChannelBase& chan, const std::string& dcf,
            uint8_t node_id, std::shared_ptr<StoredState> store);
  ~SimDevice();

  // ---- faults (call from the loop, never from a Lely callback) ----
  std::set<unsigned> stopped_tpdos;
  bool heartbeat_stopped = false;
  unsigned sdo_delay_ms = 0;
  bool sdo_delay_all = true;
  uint16_t sdo_delay_index = 0;
  uint8_t sdo_delay_subindex = 0;
  bool refuse_write_operational = false;
  std::vector<SdoRule> sdo_rules;
  std::map<uint8_t, uint32_t> identity;  // 0x1018 subindex -> value
  bool has_device_type = false;
  uint32_t device_type = 0;

  void SendEmcy(uint16_t code, uint8_t reg, const uint8_t msef[5]);
  void ClearEmcy();
  // NMT command to itself: 0x01 start, 0x02 stop, 0x80 pre-op, 0x81 reset node, 0x82 reset comm.
  void SelfCommand(uint8_t cs);
  void ForgetNodeId();
  // Writes the identity and device type overrides into the dictionary.
  void ApplyOverrides();
  // Sends held SDO answers that are due.
  void FlushDelayed(Clock::time_point now);
  // Objects in the active PDOs: (index, subindex), TPDOs and RPDOs.
  std::vector<std::pair<uint16_t, uint8_t>> PdoObjects() const;

  // Called on every SYNC the device receives.
  std::function<void()> on_sync;
  // Called after an RPDO wrote the dictionary.
  std::function<void()> on_rpdo;
  // False: the device sends nothing (powered off until it is recreated).
  bool powered = true;

 // ---- for the hooks in sim_device.cpp ----
  // True when the frame must not go out (fault filters).
  bool Blocked(uint32_t id, const uint8_t* data, uint8_t len) const;
  // True when the frame (an SDO answer) is held for the delay fault.
  bool Hold(const void* msg, size_t size, uint32_t id, const uint8_t* data, uint8_t len);
  int SendOriginal(const void* msg);
  // The SDO abort code a rule (or the OPERATIONAL refusal) gives a transfer, 0: none.
  uint32_t Rule(uint16_t index, uint8_t subindex, bool write);

  struct IndCtx;

 protected:
  void OnRestored() override;
  void OnSync(uint8_t cnt, const time_point& t) noexcept override;
  void OnRpdoWrite(uint8_t id, uint16_t idx, uint8_t subidx) noexcept override;

 private:
  void InstallIndications();

  std::vector<std::unique_ptr<IndCtx>> inds_;
  void* send_func_ = nullptr;  // can_send_func_t*
  void* send_data_ = nullptr;
  struct Held {
    Clock::time_point due;
    std::vector<uint8_t> raw;  // the struct can_msg
  };
  std::deque<Held> held_;
};

}  // namespace canopen_sim

#endif  // CANOPEN_SIM_DEVICE_H
