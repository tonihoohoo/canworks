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
#include <deque>
#include <functional>
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
#include "dm.h"
#include "image_io.h"
#include "j1939_plc_msgs.h"
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
  // The rx entry's message counter (counter_location), wrapping at 65535.
  void set_counter(size_t rx, uint16_t n) { in_work_[count_slot_ + rx] = n; }
  void set_claim(J1939ClaimState state, uint8_t address) {
    in_work_[claim_slot_] = static_cast<uint8_t>(state);
    in_work_[claim_slot_ + 1] = address;
  }
  uint64_t value(size_t rx, size_t signal) const { return in_work_[rx_slot_[rx] + 1 + 2 * signal]; }
  bool valid(size_t rx, size_t signal) const { return in_work_[rx_slot_[rx] + 2 + 2 * signal] != 0; }
  bool status(size_t rx) const { return in_work_[rx_slot_[rx]] != 0; }
  uint8_t claim_state() const { return static_cast<uint8_t>(in_work_[claim_slot_]); }
  uint8_t claim_address() const { return static_cast<uint8_t>(in_work_[claim_slot_ + 1]); }
  // diagnostics.rx entry `i`: status bit, lamps, flash, count, then one
  // double word per code slot.
  void set_dm_status(size_t i, bool ok) { in_work_[dm_slot_[i]] = ok; }
  bool dm_status(size_t i) const { return in_work_[dm_slot_[i]] != 0; }
  void set_dm(size_t i, uint8_t lamps, uint8_t flash, uint8_t count, const uint32_t* dtcs, size_t n);
  uint64_t dm_value(size_t i, size_t k) const { return in_work_[dm_slot_[i] + 1 + k]; }  // k: 0 lamps .. 3+ codes
  void set_clears(uint8_t n) { in_work_[clear_slot_] = n; }
  uint8_t clears() const { return static_cast<uint8_t>(in_work_[clear_slot_]); }
  void commit();
  // Newest output snapshot: one raw value per sent signal (tx_slot()), the
  // own trouble codes' active bits and the lamps byte, then the scan count.
  const uint64_t* latest_outputs(bool* fresh = nullptr) { return out_.latest(fresh); }
  size_t tx_slot(size_t tx, size_t signal) const { return tx_slot_[tx] + signal; }
  bool own_active(const uint64_t* snap, size_t k) const { return snap[own_slot_ + k] != 0; }
  uint8_t own_lamps(const uint64_t* snap) const { return static_cast<uint8_t>(snap[own_slot_ + own_count_]); }
  uint64_t scan_count(const uint64_t* snap) const { return snap[scan_slot_]; }

  // ---- PLC scan ----
  void copy_to_plc(ImageHost& rt);
  void copy_from_plc(ImageHost& rt);

 private:
  const J1939Config* cfg_ = nullptr;
  std::vector<size_t> rx_slot_;  // per rx entry: status, then value and valid per signal
  size_t claim_slot_ = 0;        // claim state, address
  std::vector<size_t> dm_slot_;  // per diagnostics.rx entry
  size_t clear_slot_ = 0;
  size_t count_slot_ = 0;  // one message counter per rx entry
  std::vector<size_t> tx_slot_;
  size_t own_slot_ = 0;  // own codes' active bits, then the lamps byte
  size_t own_count_ = 0;
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

  // ---- Diagnostic message jobs (design Decisions 7 and 9) ----
  // A Request for DM2 to an address, or for DM3/DM11 to an address or
  // global. One job per destination; the diagnostics channel and the PLC
  // blocks share them.
  enum class DmOp : uint8_t { ReadDm2, ClearDm3, ClearDm11 };
  struct DmResult {
    uint16_t error = 0;  // 0, or a CANWORKS_J1939_ERR_* (j1939_plc_api.h)
    uint8_t address = 0;
    DmList list;  // ReadDm2
  };
  using DmDone = std::function<void(const DmResult&)>;
  // 0 when started: `done` runs when the answer comes, the timeout passes or
  // the bus goes (a global clear: right away, once sent). Otherwise the error
  // (and `done` is not called).
  uint16_t dm_start(DmOp op, uint8_t address, unsigned timeout_ms, clock::time_point now, DmDone done);
  // The latest DM1 of `source`: 0 with `out` and its age filled, else the error.
  uint16_t dm_read_dm1(uint8_t source, DmList& out, clock::duration& age, clock::time_point now) const;
  // Takes the PLC blocks' jobs of network `index` (J1939PlcJobs) and runs them.
  void serve_plc(unsigned index, clock::time_point now);
  // DM13 has suspended the broadcasts.
  bool suspended() const { return dm13_.suspended(); }

  // ---- The program's J1939 message blocks (j1939-plc-blocks) ----
  // The network's place in the config (the blocks' NETWORK).
  void set_plc_index(unsigned index) { plc_index_ = index; }
  // Takes the network's program sends and requests and runs them, follows
  // long sends to their end, opens and closes receivers (widening the
  // receive filter) and publishes the ECU state the blocks read.
  void serve_plc_msgs(clock::time_point now);
  // J1939_SEND may send `pgn`: 0, or CANWORKS_J1939_ERR_PROTOCOL for a PGN
  // the network sends itself (design Decision 6).
  uint16_t program_may_send(uint32_t pgn);
  const DmStore& dm_store() const { return store_; }

 private:
  struct RxState {
    std::vector<std::vector<unsigned>> bits;  // per signal
    bool seen = false;
    clock::time_point last{};
    bool timed_out = false;
    uint64_t timeouts = 0;
    uint64_t count = 0;
    uint16_t counter = 0;  // the counter_location value
    std::set<uint8_t> sources;
    // Multiplexed messages: which signals the last message carried, and per
    // signal when it was last carried (its valid bit times out).
    std::vector<uint8_t> active;
    std::vector<clock::time_point> sig_last;
    std::vector<uint8_t> sig_seen;
    uint64_t unknown_pages = 0;
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
    // Multiplexed: pages "all"/"rotate" (each page's bytes as last sent),
    // and scratch for pages "program".
    std::vector<canworks_can::MuxLayout::Page> pages;
    std::vector<std::vector<uint8_t>> page_data;
    std::vector<uint8_t> page_sent_once;
    size_t cursor = 0;  // rotate: the next page
    bool unknown_page = false;
    std::vector<uint64_t> sw;
    std::vector<uint8_t> act;
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
  // `page`: the page of a tx entry with pages "all" or "rotate" (-1: the
  // entry's only frame, or the page the program's switches select).
  bool build_tx(size_t i, const uint64_t* snap, int page = -1);
  // False when the kernel has not taken the address into use yet: try again.
  // `record` false: a reply to another destination than the entry's own,
  // which does not count as its send (on change, min_gap_ms).
  bool send_tx(size_t i, uint8_t destination, clock::time_point now, int page = -1, bool record = true);
  // Builds and sends what a request or a periodic send of entry `i` sends:
  // its frame, every page ("all") or the next page ("rotate"). False as
  // send_tx.
  bool send_all(size_t i, uint8_t destination, clock::time_point now, const uint64_t* snap, bool record = true);
  void on_request(const J1939Message& m, clock::time_point now);
  // DM requests to a network that sends its own DM1; true when handled.
  bool on_dm_request(const J1939Message& m, uint32_t pgn, bool to_us, clock::time_point now);
  // Diagnostic messages received: DM1 into the store and the image, DM2
  // and acknowledgements for pending jobs, DM13, DM22.
  void on_dm_message(const J1939Message& m, clock::time_point now);
  // Acknowledgement (control 0) or NACK (1) of `pgn` to `requester`.
  void send_ack(uint8_t control, uint32_t pgn, uint8_t requester);
  // The own DM1: periodic and change-driven sends.
  void tick_dm1(clock::time_point now);
  void end_jobs(uint16_t error);
  cJSON* dm_status(clock::time_point now) const;
  // A Request for `pgn` from `requester` may be answered now: at most one
  // answer per PGN and requester every kReplyGap. Records the answer.
  bool reply_allowed(uint32_t pgn, uint8_t requester, clock::time_point now);
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
  static constexpr std::chrono::milliseconds kReplyGap{50};
  static constexpr size_t kRepliedMax = 512;
  // Timed-out long sends whose late end is waited for (the oldest is forgotten).
  static constexpr size_t kProgLateMax = 16;
  std::map<uint32_t, clock::time_point> replied_;  // (PGN << 8 | requester) -> last answer
  bool dirty_ = true;
  // Diagnostic messages.
  struct DmRxState {
    bool seen = false;
    clock::time_point last{};
    bool timed_out = false;
    uint64_t timeouts = 0;
    int source = -1;  // the address of the last DM1 taken
  };
  struct DmJob {
    DmOp op;
    clock::time_point deadline;
    unsigned timeout_ms;
    DmDone done;
  };
  DmStore store_;
  std::vector<DmRxState> dm_rx_;
  std::unique_ptr<OwnDtcs> own_;  // null without own DM1
  Dm13State dm13_;
  bool was_suspended_ = false;
  std::map<uint8_t, DmJob> jobs_;  // by destination
  uint8_t clears_ = 0;
  uint64_t clears_total_ = 0;
  uint64_t dm1_sent_ = 0;
  bool dm1_pending_ = false;  // a change waits for its send
  bool dm1_change_sent_ = false;
  clock::time_point dm1_next_{};
  clock::time_point dm1_change_at_{};
  std::vector<uint8_t> own_bits_;
  uint64_t send_errors_ = 0;
  clock::time_point last_error_log_{};
  // The program's message blocks.
  struct ProgSend {
    uint32_t handle = 0;
    uint32_t pgn = 0;
    uint8_t destination = 255;
    uint8_t priority = 6;
    std::vector<uint8_t> data;
    clock::time_point deadline{};
    bool in_flight = false;  // a long send the kernel is running
    uint32_t id = 0;         // in flight: the kernel's number of its session
  };
  struct ProgRequest {
    uint32_t handle = 0;
    uint32_t pgn = 0;
    uint8_t destination = 255;
    clock::time_point deadline{};
    bool sent = false;
  };
  void prog_end_all(uint16_t error);
  // Ends the long sends the kernel runs (the long socket was reopened).
  void prog_end_long(uint16_t error);
  // Matches the ended long send sessions to their sends.
  void prog_long_events();
  void prog_on_message(const J1939Message& m);
  void prog_sync_filter();
  void prog_publish_ecu(clock::time_point now);
  unsigned plc_index_ = 0;
  std::deque<ProgSend> prog_sends_;
  // The session numbers of long sends that ended by their timeout while the
  // kernel still ran them: their late ends are dropped.
  std::deque<uint32_t> prog_late_;
  std::vector<ProgRequest> prog_requests_;
  std::vector<J1939PlcMsgs::Filter> prog_filters_;
  std::vector<J1939PlcMsgs::Job> prog_taken_;
  std::vector<uint32_t> filter_applied_;  // the receive filter as last set
  bool filter_any_applied_ = false;
  bool filter_valid_ = false;
  uint64_t prog_sent_ = 0;
  uint64_t prog_aborted_ = 0;
  uint64_t prog_requests_sent_ = 0;
  bool override_logged_ = false;
  clock::time_point ecu_published_{};
  bool ecu_dirty_ = true;
};

// The diagnostics channel's error text for a DM job's error (j1939_plc_api.h
// codes) and the result of a finished one (j1939_dm_read / j1939_dm_clear).
std::string j1939_dm_error_text(uint16_t error, bool read, uint8_t address, unsigned timeout_ms,
                                J1939ClaimState state);
cJSON* j1939_dm_result_json(const J1939Engine::DmResult& res, bool read);

class J1939Network {
 public:
  // `hub`, when given, gets the status answers. The socket and adapter
  // default to the kernel's and the config's.
  // `index`: the network's place in the config (the PLC blocks' NETWORK).
  J1939Network(const Config& cfg, DiagHub* hub, std::unique_ptr<J1939Socket> socket = nullptr,
               std::unique_ptr<CanAdapter> adapter = nullptr, std::unique_ptr<LinkOps> link = nullptr,
               unsigned index = 0);
  ~J1939Network();

  J1939Image& image() { return image_; }
  void start();
  void stop();

  void cycle_start(ImageHost& rt) { image_.copy_to_plc(rt); }
  void cycle_end(ImageHost& rt) { image_.copy_from_plc(rt); }

 private:
  void thread_main();
  // One session on a ready interface; returns when the bus is lost or on stop.
  void run_session();
  bool wait_for(std::chrono::milliseconds d);
  void serve_diag(std::chrono::steady_clock::time_point now);
  // A j1939_dm_read or j1939_dm_clear request; answered now or when its
  // job ends.
  void serve_dm(const DiagRequest& r, std::chrono::steady_clock::time_point now);
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
  unsigned index_ = 0;
  std::thread thread_;
  std::atomic<bool> stop_{false};
  std::mutex mutex_;
  std::condition_variable cv_;
};

}  // namespace canopen_plugin

#endif  // CANWORKS_J1939_NETWORK_H
