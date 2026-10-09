// slave_device.h - one CANopen device (NMT slave) on Lely's slave stack,
// with what a device needs beyond Lely (canopen-slave-device spec):
// - stored parameters: 0x1010 "save" keeps the selected dictionary ranges,
//   0x1011 "load" drops them; they come back after every reset;
// - an LSS-stored node ID, and LSS bit timing changes refused;
// - waiting in PRE-OPERATIONAL for the master's start;
// - TPDO events after a value changed (Changed());
// - which objects the PDOs in force map;
// - a guard that notices another device using the same node ID.
// The object dictionary, NMT, heartbeat, guarding, SDO server, PDOs, SYNC
// and EMCY all come from Lely, driven by the EDS. Everything runs on the
// event loop thread the device was created on. The device simulator's
// devices (plugin/src/canopen/sim) build on this class too, with Options to behave like
// a free-standing device.

#ifndef CANOPEN_SLAVE_DEVICE_H
#define CANOPEN_SLAVE_DEVICE_H

#include <cstdint>
#include <functional>
#include <memory>
#include <string>
#include <utility>
#include <vector>

#include <lely/coapp/slave.hpp>

#include "slave_state.h"

struct __can_recv;

namespace canopen_plugin {

class SlaveDevice : public lely::canopen::BasicSlave {
 public:
  struct Options {
    // An EDS without 0x1F80 waits in PRE-OPERATIONAL for the master's start
    // (false: Lely's own autostart).
    bool wait_for_start = true;
    // LSS bit timing requests answered "not supported" (false: Lely's own
    // handling).
    bool refuse_lss_bitrate = true;
  };

  // `node_id` 1-127, or 0xFF for a device that waits for LSS.
  SlaveDevice(ev_exec_t* exec, lely::io::TimerBase& timer, lely::io::CanChannelBase& chan, const std::string& eds,
              uint8_t node_id, std::shared_ptr<SlaveStore> store, Options options);
  SlaveDevice(ev_exec_t* exec, lely::io::TimerBase& timer, lely::io::CanChannelBase& chan, const std::string& eds,
              uint8_t node_id, std::shared_ptr<SlaveStore> store)
      : SlaveDevice(exec, timer, chan, eds, node_id, std::move(store), Options()) {}
  ~SlaveDevice();

  __co_dev* od() const { return dev(); }
  uint8_t node_id() const;
  // NMT state: 0 boot-up, 4 stopped, 5 operational, 127 pre-operational.
  uint8_t nmt_state() const;
  const SlaveStore& store() const { return *store_; }

  // Tells the device an object changed (event-driven TPDOs).
  void Changed(uint16_t index, uint8_t subindex);
  // Whether a PDO in force maps the object.
  bool InRpdo(uint16_t index, uint8_t subindex) const;
  bool InTpdo(uint16_t index, uint8_t subindex) const;
  // The PDOs in force: number and mapped objects (index << 16 | subindex << 8 |
  // bits), for diagnostics.
  struct PdoMap {
    unsigned number = 0;
    uint32_t cob_id = 0;
    unsigned transmission = 0;
    std::vector<uint32_t> entries;
  };
  std::vector<PdoMap> Pdos(bool tpdo) const;
  // Watches for frames another device sends with this device's node ID
  // (boot-up or heartbeat, EMCY, SDO answer); `on_conflict` is posted to the
  // loop once.
  void GuardNodeId(std::function<void()> on_conflict);

  std::function<void(const std::string&)> on_log;
  // Called after 0x1010 save, 0x1011 load or an LSS store, to persist store().
  std::function<void()> on_stored;

  // ---- for the hooks in slave_device.cpp ----
  void Save(uint8_t subindex);
  void Load(uint8_t subindex);
  void Foreign();
  void LssWaiting();

 protected:
  // Derived classes call these first when they override them.
  void OnCommand(lely::canopen::NmtCommand cs) noexcept override;
  void OnStore(uint8_t id, int bitrate) override;
  // After a reset restored the EDS values and the stored ones: the
  // dictionary is as it will be at the boot-up message.
  virtual void OnRestored() {}
  __can_net* NetPtr();
  ev_exec_t* exec_;
  std::shared_ptr<SlaveStore> store_;
  // Expires with the device, for work posted to the loop.
  std::shared_ptr<bool> alive_ = std::make_shared<bool>(true);

 private:
  void WaitForNmtStart();
  void ApplyStored(bool node);
  bool InPdo(uint16_t base, uint16_t index, uint8_t subindex) const;
  Options options_;
  std::vector<__can_recv*> recvs_;
  std::function<void()> on_conflict_;
  bool conflict_posted_ = false;
  bool node_reset_ = true;
};

}  // namespace canopen_plugin

#endif  // CANOPEN_SLAVE_DEVICE_H
