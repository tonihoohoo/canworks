// bridge_host.h - the Modbus bridge's host (modbus-bridge spec): the
// canworks engine (can/engine.h) with a byte image served to Modbus TCP
// clients.
//
// The engine exchanges values through a ByteImageHost (image_io.h): its
// writes land in the input bytes (most significant byte first, word order
// from the config) and it reads the newest output snapshot. There is no
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
#include "mailbox_engine.h"
#include "mailboxes.h"
#include "modbus_server.h"

typedef struct cJSON cJSON;

namespace canworks_bridge {

// The server settings of a bridge config; false with `err` when an entry of
// `readers` or `writers` cannot be used.
bool server_config(const canopen_plugin::BridgeConfig& b, ServerConfig& out, std::string& err);

// The input and output image sizes the locations need, counted in 64 bits;
// false with `err` when one ends past `limit`.
bool image_sizes(const std::vector<canopen_plugin::ImageUse>& uses, uint64_t limit, size_t& in, size_t& out,
                 std::string& err);

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
  static bool check(const std::string& config_path, std::vector<std::string>* problems = nullptr,
                    uint32_t* map_hash = nullptr);

  // A config uploaded over the diagnostics channel (put_config) was checked
  // and staged: the main thread calls apply_upload(), which puts its files
  // in place atomically and restarts on it, or on the previous files when
  // they cannot be put in place or it does not start. False when nothing
  // runs afterwards (the previous files did not start either).
  bool upload_pending() const;
  bool apply_upload();
  bool running() const { return running_; }
  // How the previous run of this config ended (modbus-bridge "Unclean stop
  // reported"): "clean", "unclean" or "unknown" (first start), decided at
  // the first start of the process.
  const std::string& last_stop() const { return last_stop_; }

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
  // The program's mailbox operations, receivers and cyclic jobs end.
  void end_program_resources(const char* why);
  // Every data output location of the image to 0 (the blocks keep theirs).
  void clear_outputs();
  // on_client_loss "safe": the data outputs from safe_out_.
  void write_safe_outputs();
  void leave_off(const char* why);
  // plc_link: the PLC link header turned outputs off (PLC stopped or mismatch).
  void link_off(OutputState why, Clock::time_point now);
  // NMT `command` with node 0 to every CANopen master network.
  void all_nodes(const char* command);
  void service_control(const uint8_t* out, Clock::time_point now);
  // The control block and SDO request a client left in place when the
  // bridge started are not run: the first written counters become the
  // last ones handled. `wrote_*`: the client had written them before the
  // output snapshot `out` was taken.
  void take_baselines(const uint8_t* out, bool wrote_control, bool wrote_sdo);
  void write_blocks(Clock::time_point now);
  // Every 100 ms: which CAN networks have their interface down or missing,
  // or their controller bus-off (status block byte 7 bit 1).
  void read_bus_states(Clock::time_point now);
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
  std::unique_ptr<EngineMailboxBackend> mailbox_backend_;
  std::unique_ptr<Mailboxes> mailboxes_;
  std::vector<uint32_t> sessions_ended_;  // per network, as last seen (end_network)
  uint32_t mb_written_ = 0;  // request mailboxes whose words a client wrote (Mailboxes::service)
  uint64_t first_out_version_ = 0;  // the output version before any client wrote
  // Whether the control block / SDO request counters are known: at once,
  // except for openplc configs, where a client's first write is the
  // baseline (restart baseline).
  bool control_known_ = false;
  bool sdo_known_ = false;
  Clock::time_point started_;
  Clock::time_point zero_until_{};  // "zero": the gate closes then
  bool zero_pending_ = false;
  std::chrono::milliseconds zero_settle_{100};
  uint64_t outputs_seen_ = ~0ull;
  std::vector<uint8_t> out_copy_;
  std::vector<uint8_t> safe_out_;  // the output image of the safe values
  std::chrono::milliseconds safe_stop_wait_{20};  // a clean stop's last SYNC with the safe values
  uint32_t map_hash_ = 0;
  bool mismatch_logged_ = false;
  uint32_t mismatch_seen_ = 0;

  // The run marker (.canworks/running): written after a start, removed by
  // stop(); found at the first start, the previous run did not stop.
  std::string marker_path() const;
  void write_marker();
  std::string last_stop_;
  bool unclean_start_ = false;
  bool bus_not_ok_ = false;
  Clock::time_point next_bus_read_{};
  mutable std::mutex bus_mu_;
  std::vector<std::string> bus_down_;  // names of the networks whose bus is not ok

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
