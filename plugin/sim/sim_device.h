// sim_device.h - one simulated CANopen device on Lely's slave stack.
//
// The object dictionary, NMT, heartbeat or node guarding, SDO server, PDOs
// and EMCY all come from Lely, driven by the device's EDS or DCF. This class
// adds what a simulation needs on top (docs/simulator.md):
// - a send hook on the device's CAN network, through which faults drop
//   frames (heartbeat stop, TPDO stop) or hold them (SDO answer delay);
// - SDO indications chained in front of Lely's own, for SDO abort rules and
//   refusing writes while OPERATIONAL;
// - stored parameters (0x1010 save, 0x1011 load) and an LSS-stored node ID,
//   applied after every reset, and identity / device type overrides;
// - a receiver that notices another device with the same node ID (conflict
//   guard on a real network).
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

#include <lely/coapp/slave.hpp>

struct __can_recv;

namespace canopen_sim {

// Parameters saved with 0x1010 and a node ID stored over LSS; they outlive a
// device's power cycles (and, in the plugin, PLC stop and start).
struct StoredState {
  // Saved ranges: 'C' communication (0x1000-0x1FFF), 'M' manufacturer
  // (0x2000-0x5FFF), 'A' application (0x6000-0x9FFF), as concise DCFs.
  std::map<char, std::vector<uint8_t>> saved;
  uint8_t lss_id = 0;                             // 0: none stored
  bool lss_bitrate_stored = false;
};

struct SdoRule {
  uint16_t index = 0;
  uint8_t subindex = 0;
  bool on_read = true, on_write = true;
  uint32_t code = 0;
  int count = -1;  // -1: until removed
};

class SimDevice : public lely::canopen::BasicSlave {
 public:
  using Clock = std::chrono::steady_clock;

  // `node_id` 1-127, or 0xFF for a device without a node ID (LSS).
  SimDevice(ev_exec_t* exec, lely::io::TimerBase& timer, lely::io::CanChannelBase& chan, const std::string& dcf,
            uint8_t node_id, std::shared_ptr<StoredState> store);
  ~SimDevice();

  __co_dev* od() const { return dev(); }
  uint8_t node_id() const;
  // NMT state: 0 boot-up, 4 stopped, 5 operational, 127 pre-operational.
  uint8_t nmt_state() const;

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
  // Watches for heartbeats, boot-ups and EMCY of its own node ID sent by
  // another device; `on_conflict` is posted to the loop when one comes.
  void GuardNodeId(std::function<void()> on_conflict);
  // Tells the device an object changed (event-driven TPDOs).
  void Changed(uint16_t index, uint8_t subindex);
  // Whether an active RPDO maps the object.
  bool InRpdo(uint16_t index, uint8_t subindex) const;
  bool InTpdo(uint16_t index, uint8_t subindex) const;
  // Objects in the active PDOs: (index, subindex), TPDOs and RPDOs.
  std::vector<std::pair<uint16_t, uint8_t>> PdoObjects() const;

  std::function<void(const std::string&)> on_log;
  // Called after 0x1010 save, 0x1011 load or an LSS store.
  std::function<void()> on_stored;
  // Called on every SYNC the device receives.
  std::function<void()> on_sync;
  // False: the device sends nothing (powered off until it is recreated).
  bool powered = true;

 // ---- for the hooks in sim_device.cpp ----
  // True when the frame must not go out (fault filters).
  bool Blocked(uint32_t id, const uint8_t* data, uint8_t len) const;
  // True when the frame (an SDO answer) is held for the delay fault.
  bool Hold(const void* msg, size_t size, uint32_t id, const uint8_t* data, uint8_t len);
  int SendOriginal(const void* msg);
  void Foreign();
  void LssWaiting();
  void LssStored(uint8_t id);
  // The SDO abort code a rule (or the OPERATIONAL refusal) gives a transfer, 0: none.
  uint32_t Rule(uint16_t index, uint8_t subindex, bool write);
  void Save(uint8_t subindex);
  void Load(uint8_t subindex);

  struct IndCtx;

 protected:
  void OnCommand(lely::canopen::NmtCommand cs) noexcept override;
  void OnStore(uint8_t id, int bitrate) override;
  void OnSync(uint8_t cnt, const time_point& t) noexcept override;

 private:
  void InstallIndications();
  void ApplyStored(bool node);

  bool InPdo(uint16_t base, uint16_t index, uint8_t subindex) const;
  __can_net* NetPtr();
  std::vector<std::unique_ptr<IndCtx>> inds_;
  void* send_func_ = nullptr;  // can_send_func_t*
  void* send_data_ = nullptr;
  struct Held {
    Clock::time_point due;
    std::vector<uint8_t> raw;  // the struct can_msg
  };
  std::deque<Held> held_;
  std::vector<__can_recv*> recvs_;
  std::function<void()> on_conflict_;
  bool conflict_posted_ = false;
  ev_exec_t* exec_;
  std::shared_ptr<StoredState> store_;
  bool node_reset_ = true;
  // Expires with the device, for work posted to the loop.
  std::shared_ptr<bool> alive_ = std::make_shared<bool>(true);
};

}  // namespace canopen_sim

#endif  // CANOPEN_SIM_DEVICE_H
