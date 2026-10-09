// j1939_network.h - one J1939 network (j1939-ecu spec): the PLC's ECU on
// the kernel's J1939 stack.
//
// J1939Image binds the network's signals and status bytes to the PLC image
// with the same triple buffers the CANopen side uses. J1939Engine is the
// protocol logic (address claim, received PGNs, sent PGNs, requests,
// supervision, the diagnostics status), driven by the bus thread and tested
// with a fake socket. J1939Network is the bus thread: it prepares the
// adapter, opens the sockets, runs the engine and starts over when the bus
// goes away.

#ifndef CANWORKS_J1939_NETWORK_H
#define CANWORKS_J1939_NETWORK_H

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <map>
#include <memory>
#include <mutex>
#include <set>
#include <string>
#include <thread>
#include <vector>

#include "address_claim.h"
#include "can_adapter.h"
#include "config.h"
#include "diag.h"
#include "image_io.h"
#include "j1939_socket.h"

typedef struct cJSON cJSON;

namespace canopen_plugin {

class J1939Image {
 public:
  void build(const J1939Config& cfg);

  // ---- bus thread ----
  void set_value(size_t rx, size_t signal, uint64_t v) { in_work_[rx_slot_[rx] + 1 + 2 * signal] = v; }
  void set_valid(size_t rx, size_t signal, bool valid) { in_work_[rx_slot_[rx] + 2 + 2 * signal] = valid; }
  void set_status(size_t rx, bool ok) { in_work_[rx_slot_[rx]] = ok; }
  void set_claim(J1939ClaimState state, uint8_t address) {
    in_work_[claim_slot_] = static_cast<uint8_t>(state);
    in_work_[claim_slot_ + 1] = address;
  }
  uint64_t value(size_t rx, size_t signal) const { return in_work_[rx_slot_[rx] + 1 + 2 * signal]; }
  bool valid(size_t rx, size_t signal) const { return in_work_[rx_slot_[rx] + 2 + 2 * signal] != 0; }
  bool status(size_t rx) const { return in_work_[rx_slot_[rx]] != 0; }
  uint8_t claim_state() const { return static_cast<uint8_t>(in_work_[claim_slot_]); }
  uint8_t claim_address() const { return static_cast<uint8_t>(in_work_[claim_slot_ + 1]); }
  void commit();
  // Newest output snapshot: one raw value per sent signal (tx_slot()), then
  // the scan count.
  const uint64_t* latest_outputs(bool* fresh = nullptr) { return out_.latest(fresh); }
  size_t tx_slot(size_t tx, size_t signal) const { return tx_slot_[tx] + signal; }
  uint64_t scan_count(const uint64_t* snap) const { return snap[scan_slot_]; }

  // ---- PLC scan ----
  void copy_to_plc(const plugin_runtime_args_t& rt);
  void copy_from_plc(const plugin_runtime_args_t& rt);

 private:
  const J1939Config* cfg_ = nullptr;
  std::vector<size_t> rx_slot_;  // per rx entry: status, then value and valid per signal
  size_t claim_slot_ = 0;        // claim state, address
  std::vector<size_t> tx_slot_;
  size_t scan_slot_ = 0;
  uint64_t scans_ = 0;
  std::vector<uint64_t> in_work_;
  TripleBuffer in_;
  TripleBuffer out_;
};

class J1939Engine : private AddressClaimer::Actions {
 public:
  using clock = std::chrono::steady_clock;

  J1939Engine(const Config& cfg, J1939Image& image, J1939Socket& socket);

  // The PGNs the receive socket takes.
  std::vector<uint32_t> receive_pgns() const;
  // A session starts on a usable bus (sockets open), or ends.
  void bus_up(clock::time_point now);
  void bus_lost(const std::string& why);
  void on_message(const J1939Message& m, clock::time_point now);
  // Claim, sends due, supervision; commits the inputs when they changed.
  void tick(clock::time_point now);

  J1939ClaimState state() const { return claimer_.state(); }
  uint8_t address() const { return claimer_.address(); }
  // The status answer's "j1939" object (design Decision 11).
  cJSON* status(clock::time_point now) const;
  // Why the network has no bus ("" while it runs).
  const std::string& problem() const { return problem_; }
  // Sending failed this many times (for tests and the log throttle).
  uint64_t send_errors() const { return send_errors_; }

 private:
  struct RxState {
    std::vector<std::vector<unsigned>> bits;  // per signal
    bool seen = false;
    clock::time_point last{};
    bool timed_out = false;
    uint64_t timeouts = 0;
    uint64_t count = 0;
    std::set<uint8_t> sources;
  };
  struct TxState {
    std::vector<std::vector<unsigned>> bits;
    std::vector<uint8_t> data;  // the message as last sent
    std::vector<uint8_t> next;  // as built from the newest outputs
    bool sent_once = false;
    clock::time_point next_due{};
    clock::time_point last_sent{};
    uint64_t sent = 0;
    uint64_t answered = 0;
  };
  struct RequestState {
    clock::time_point next_due{};
    uint64_t sent = 0;
  };
  struct Ecu {
    uint64_t name = 0;
    clock::time_point last{};
  };

  void send_claim(uint8_t address) override;
  void send_claim_request() override;
  bool can_send(clock::time_point now) const;
  // Builds tx entry `i` from the output snapshot; true when its bytes differ
  // from the last sent (or it was not sent yet).
  bool build_tx(size_t i, const uint64_t* snap);
  // False when the kernel has not taken the address into use yet: try again.
  bool send_tx(size_t i, uint8_t destination, clock::time_point now);
  void on_request(const J1939Message& m, clock::time_point now);
  int send(uint32_t pgn, uint8_t destination, uint8_t priority, const uint8_t* data, size_t len);
  void rebind(uint8_t address);

  const Config& cfg_;
  const J1939Config& j_;
  J1939Image& image_;
  J1939Socket& socket_;
  AddressClaimer claimer_;
  uint8_t bound_ = 0xFF;  // the address the ECU socket is bound to (0xFF: none)
  bool bus_ = false;
  clock::time_point session_start_{};
  clock::time_point claimed_at_{};
  bool was_claimed_ = false;
  bool gate_was_open_ = true;  // the outputs gate at the last tick
  bool settling_ = false;  // within 1 s of the claim
  std::string problem_ = "not started";
  std::vector<RxState> rx_;
  std::vector<TxState> tx_;
  std::vector<RequestState> req_;
  std::map<uint8_t, Ecu> ecus_;
  bool dirty_ = true;
  uint64_t send_errors_ = 0;
  clock::time_point last_error_log_{};
};

class J1939Network {
 public:
  // `hub`, when given, gets the status answers. The socket and adapter
  // default to the kernel's and the config's.
  J1939Network(const Config& cfg, DiagHub* hub, std::unique_ptr<J1939Socket> socket = nullptr,
               std::unique_ptr<CanAdapter> adapter = nullptr, std::unique_ptr<LinkOps> link = nullptr);
  ~J1939Network();

  J1939Image& image() { return image_; }
  void start();
  void stop();

  void cycle_start(const plugin_runtime_args_t& rt) { image_.copy_to_plc(rt); }
  void cycle_end(const plugin_runtime_args_t& rt) { image_.copy_from_plc(rt); }

 private:
  void thread_main();
  // One session on a ready interface; returns when the bus is lost or on stop.
  void run_session();
  bool wait_for(std::chrono::milliseconds d);
  void serve_diag(std::chrono::steady_clock::time_point now);
  void offline(const std::string& why);

  const Config& cfg_;
  DiagHub* hub_;
  J1939Image image_;
  std::unique_ptr<J1939Socket> socket_;
  std::unique_ptr<CanAdapter> adapter_;
  std::unique_ptr<LinkOps> link_;
  J1939Engine engine_;
  LinkInfo link_info_;
  uint8_t bus_state_ = 0;  // bus_monitor.h codes
  std::thread thread_;
  std::atomic<bool> stop_{false};
  std::mutex mutex_;
  std::condition_variable cv_;
};

}  // namespace canopen_plugin

#endif  // CANWORKS_J1939_NETWORK_H
