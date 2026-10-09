// bridge_host.h - the Modbus bridge's host (modbus-bridge spec): the engine
// of the OpenPLC plugin (can/engine.h) with a byte image served to Modbus
// TCP clients in place of a PLC program.
//
// The engine exchanges values through a plugin_runtime_args_t, as under
// OpenPLC. The bridge fills one in whose journal writes land in its input
// bytes (most significant byte first, word order from the config) and whose
// output tables are decoded from the newest output snapshot. There is no
// scan:
// - a loop thread takes the inputs every millisecond and publishes them as
//   one snapshot, with the bridge's own blocks (status, live lists, SDO
//   response); it also runs the control block, the SDO bridge registers and
//   the watchdog;
// - every accepted write request publishes its output snapshot to the
//   networks at once (the engine's cycle_end), so edges are seen between
//   consecutive writes.

#ifndef CANWORKS_BRIDGE_HOST_H
#define CANWORKS_BRIDGE_HOST_H

#include <atomic>
#include <chrono>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#include "bridge_blocks.h"
#include "byte_image.h"
#include "config.h"
#include "engine.h"
#include "modbus_server.h"

typedef struct cJSON cJSON;

namespace canworks_bridge {

class BridgeHost {
 public:
  // The largest byte address a bridge config may use (+1), per direction.
  static constexpr unsigned kImageLimit = 8192;

  BridgeHost();
  ~BridgeHost();

  // Loads and checks the config, makes the networks, binds the Modbus port
  // and starts everything. False (with the reasons logged) when the config
  // is rejected or the port cannot be bound; nothing runs then.
  bool start(const std::string& config_path, const char* version);
  // Tests: listen here instead (127.0.0.1:0 for a free port).
  std::string listen_override;
  void stop();
  // Only loads and checks the config (canworks-bridge --check-only);
  // `problems`, when given, gets the reasons of a rejection.
  static bool check(const std::string& config_path, std::vector<std::string>* problems = nullptr);

  // A config uploaded over the diagnostics channel (put_config) was checked
  // and staged: the main thread calls apply_upload(), which restarts on it,
  // or on the previous files when it does not start.
  bool upload_pending() const;
  void apply_upload();
  bool running() const { return running_; }

  const canopen_plugin::ConfigSet& set() const { return engine_->set(); }
  ByteImage& image() { return image_; }
  uint16_t modbus_port() const { return server_.port(); }
  // The "bridge" part of the diagnostics status answer.
  cJSON* status_json() const;

 private:
  void loop();
  void on_write();
  // With exchange_mu_ held: the newest output snapshot to the networks.
  void push_outputs();
  void enter_off(OutputState why, Clock::time_point now);
  void leave_off(const char* why);
  void service_control(const uint8_t* out, Clock::time_point now);
  void write_blocks(Clock::time_point now);
  unsigned put_config(const std::vector<std::pair<std::string, std::string>>& files, std::string& why);
  std::string staged_path(const std::string& name) const;

  std::unique_ptr<canopen_plugin::Engine> engine_;
  ByteImage image_;
  ModbusServer server_{image_};
  std::thread thread_;
  std::atomic<bool> stop_{false};
  bool running_ = false;

  // Guards the engine's scan hooks, the supervisor and the blocks' state.
  mutable std::mutex exchange_mu_;
  canopen_plugin::BridgeConfig cfg_;
  std::vector<canopen_plugin::ImageUse> data_outputs_;  // output locations to zero
  std::vector<bool> is_master_;                         // per network: a CANopen master
  std::unique_ptr<OutputSupervisor> supervisor_;
  ControlBlock control_;
  std::unique_ptr<SdoBridgeRegisters> sdo_;
  Clock::time_point started_;
  Clock::time_point zero_until_{};  // "zero": the gate closes then
  bool zero_pending_ = false;
  std::chrono::milliseconds zero_settle_{100};
  uint64_t outputs_seen_ = ~0ull;
  std::vector<uint8_t> out_copy_;

  std::string config_path_, version_;
  mutable std::mutex upload_mu_;
  bool upload_pending_ = false;
  std::vector<std::string> staged_;  // relative paths in the staging folder
  std::string upload_result_;        // "", "started" or "restored"
  std::string upload_detail_;
  unsigned upload_number_ = 0;  // uploads accepted since the process started
};

}  // namespace canworks_bridge

#endif  // CANWORKS_BRIDGE_HOST_H
