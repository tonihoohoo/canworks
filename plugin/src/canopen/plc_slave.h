// plc_slave.h - a slave network (canopen-slave-device spec): the plugin as
// one CANopen device whose bound objects are PLC inputs and outputs, and,
// as the upper side of a gateway (canopen-gateway spec), the slave end of the
// routes, the field node status record, forwarded EMCYs and the SDO bridge.
//
// SlaveImage moves values between the bus thread and the PLC scan through
// the same lock-free triple buffers as ProcessImage. PlcSlave runs on its
// bus thread's Lely loop: every millisecond it writes changed outputs into
// the dictionary (with TPDO events), copies changed inputs to the image,
// sends the program's EMCY and updates the status locations.

#ifndef CANOPEN_PLC_SLAVE_H
#define CANOPEN_PLC_SLAVE_H

#include <chrono>
#include <cstdint>
#include <functional>
#include <memory>
#include <string>
#include <vector>

#include <lely/io2/timer.hpp>

#include "config.h"
#include "diag.h"
#include "gateway.h"
#include "plugin_types.h"
#include "process_image.h"
#include "slave_device.h"

namespace canopen_plugin {

class SlaveImage {
 public:
  void build(const Config& cfg);
  // Indices into cfg.slave.objects of the inputs and of the outputs.
  const std::vector<size_t>& input_objects() const { return in_objs_; }
  const std::vector<size_t>& output_objects() const { return out_objs_; }

  // ---- bus thread ----
  void set_input(size_t k, uint64_t raw) { in_work_[k] = raw; }
  uint64_t input(size_t k) const { return in_work_[k]; }
  void set_state(uint8_t state) { in_work_[status_slot_] = state; }
  void set_comm_ok(bool ok) { in_work_[status_slot_ + 1] = ok ? 1 : 0; }
  void set_sync_count(uint16_t n) { in_work_[status_slot_ + 2] = n; }
  uint8_t state() const { return static_cast<uint8_t>(in_work_[status_slot_]); }
  bool comm_ok() const { return in_work_[status_slot_ + 1] != 0; }
  void commit_inputs();
  // Newest output snapshot: one raw value per output object, then the EMCY
  // code and error register.
  const uint64_t* latest_outputs(bool* fresh = nullptr) { return out_.latest(fresh); }
  uint16_t emcy_code(const uint64_t* snap) const { return static_cast<uint16_t>(snap[out_objs_.size()]); }
  uint8_t error_register(const uint64_t* snap) const { return static_cast<uint8_t>(snap[out_objs_.size() + 1]); }
  // Scans completed since build() (0 until the program has run once).
  uint64_t scan_count(const uint64_t* snap) const { return snap[out_objs_.size() + 2]; }

  // ---- PLC scan ----
  void copy_to_plc(const plugin_runtime_args_t& rt);
  void copy_from_plc(const plugin_runtime_args_t& rt);

 private:
  const SlaveConfig* cfg_ = nullptr;
  std::vector<size_t> in_objs_, out_objs_;
  size_t status_slot_ = 0;
  uint64_t scans_ = 0;
  std::vector<uint64_t> in_work_;
  TripleBuffer in_;
  TripleBuffer out_;
};

class PlcSlave : public SlaveDevice {
 public:
  // `tick` is called every kTick from the loop; returning false ends the
  // session (the caller shuts the loop down). `gw` is the gateway link when
  // this network is a gateway's upper network. `state_path` is the state
  // file (slave_state.h); `store` what was loaded from it.
  PlcSlave(ev_exec_t* exec, lely::io::TimerBase& timer, lely::io::TimerBase& loop_timer,
           lely::io::CanChannelBase& chan, const Config& cfg, SlaveImage& image, std::shared_ptr<SlaveStore> store,
           std::string state_path, GatewayLink* gw = nullptr, std::function<bool()> tick = nullptr);
  ~PlcSlave();

  // Boots the device (boot-up message) and starts the loop timer.
  void Start();
  // The session ends: no new work.
  void Stop();
  // Inputs as when communication is lost (status FALSE, state 0).
  void MarkDown();
  // Gateway: routes up, field states and EMCYs arrived (GatewayLink::fd()).
  void ServiceGateway();
  void SetDiag(DiagHub* hub) { diag_ = hub; }

  static constexpr std::chrono::milliseconds kPeriod{1};
  static constexpr std::chrono::milliseconds kTick{100};

  // The SDO bridge record's status sub-object (canopen-gateway spec).
  enum BridgeStatus : uint8_t { kBridgeIdle = 0, kBridgeBusy = 1, kBridgeDone = 2, kBridgeAborted = 3 };

 protected:
  void OnCommand(lely::canopen::NmtCommand cs) noexcept override;
  void OnRestored() override;
  void OnRpdoWrite(uint8_t id, uint16_t idx, uint8_t subidx) noexcept override;
  void OnSync(uint8_t cnt, const time_point& t) noexcept override;
  void OnHeartbeat(uint8_t id, bool occurred) noexcept override;
  void OnLifeGuarding(bool occurred) noexcept override;

 private:
  void Period();
  void WriteOutputs(const uint64_t* snap);
  void SendProgramEmcy(const uint64_t* snap);
  void ReadInputs();
  void UpdateStatus();
  void ReadRoutesDown();
  void WriteStatusRecord(bool all);
  void ForwardEmcy();
  // Active errors behind 0x1001 and the EMCY stack, newest first: the
  // program's own (key 0) and each field node's (network << 8 | node, + 1).
  void PushError(uint32_t key, uint16_t code, uint8_t er, const uint8_t msef[5]);
  void RemoveError(uint32_t key);
  void ServiceBridge();
  uint32_t BridgeCommand(uint8_t command);
  void ServiceDiag();
  void DiagStatus(const DiagRequest& r);
  void DiagSdo(const DiagRequest& r);
  void RefusePlcRequests();
  void SetObject(uint16_t index, uint8_t subindex, uint64_t raw, CoType type, bool event);

  const Config& cfg_;
  SlaveImage& image_;
  lely::io::TimerBase& loop_timer_;
  lely::io::TimerWait loop_wait_;
  std::string state_path_;
  GatewayLink* gw_;
  std::function<bool()> tick_;
  DiagHub* diag_ = nullptr;
  bool stopped_ = false;
  unsigned periods_ = 0;
  bool restored_ = true;  // a reset just restored the dictionary: write every output again
  std::vector<uint64_t> last_out_;
  std::vector<uint64_t> last_in_;
  bool zeroed_ = false;  // inputs_on_loss zero is in force
  bool hb_error_ = false, lg_error_ = false;
  uint8_t hb_master_ = 0;
  uint16_t sync_count_ = 0;
  uint8_t last_state_ = 0xFF;
  bool last_comm_ = false;
  bool ever_started_ = false;
  uint16_t emcy_code_ = 0;
  uint8_t emcy_er_ = 0;
  struct ActiveError {
    uint32_t key;
    uint16_t code;
    uint8_t er;
  };
  std::vector<ActiveError> errors_;  // newest first, as Lely's EMCY stack
  // Gateway
  std::vector<uint32_t> route_seen_;  // GatewayLink versions read (routes up)
  std::vector<uint64_t> route_last_;  // last value put (routes down) / written (up)
  std::vector<bool> route_have_;
  uint64_t states_seen_ = ~0ull;
  std::vector<GatewayLink::Emcy> emcy_scratch_;
  struct Bridge {
    bool busy = false;
    uint32_t handle = 0;
    bool write = false;
    std::chrono::steady_clock::time_point started;
  } bridge_;
};

}  // namespace canopen_plugin

#endif  // CANOPEN_PLC_SLAVE_H
