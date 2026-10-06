// network.h - the CANopen master on top of Lely's BasicMaster.
//
// Network owns the NMT master for one bus session: it boots, configures and
// starts the slaves, moves PDO data between Lely and the ProcessImage, and
// supervises the nodes (loss detection, per-node status, background retry).
// It also serves the program's SDO variables and NMT command bytes.
// It runs entirely on one Lely event loop thread and is transport-agnostic:
// Bus (bus.h) gives it a SocketCAN channel, the tests a virtual one.

#ifndef CANOPEN_NETWORK_H
#define CANOPEN_NETWORK_H

#include <array>
#include <chrono>
#include <deque>
#include <functional>
#include <map>
#include <memory>
#include <set>
#include <string>
#include <system_error>
#include <vector>

#include <lely/coapp/lss_master.hpp>
#include <lely/coapp/master.hpp>
#include <lely/ev/exec.hpp>
#include <lely/io2/posix/poll.hpp>
#include <lely/io2/timer.hpp>

#include "config.h"
#include "dcf_gen.h"
#include "diag.h"
#include "log.h"
#include "plc_api.h"
#include "process_image.h"

namespace canopen_plugin {

class Network;

// Lely's LSS master on the Network's NMT service. Lely calls OnStart() at
// every reset communication of the master, before any slave boots, and holds
// the start-up until it reports back (network_lss.cpp).
class LssAssigner : public lely::canopen::LssMaster {
 public:
  LssAssigner(ev_exec_t* exec, Network& net);

 protected:
  void OnStart(std::function<void(std::error_code ec)> res) noexcept override;

 private:
  Network& net_;
};

// A CiA 301 TIME_OF_DAY message body for a wall-clock time in milliseconds
// since 1970-01-01 UTC: milliseconds after midnight (28 bits) and days since
// 1984-01-01.
void encode_time_of_day(int64_t unix_ms, uint8_t out[6]);

class Network : public lely::canopen::BasicMaster {
 public:
  // `tick` is called from the loop every supervision period; returning false
  // ends the session (the caller then shuts the loop down). `req_timer`, when
  // given, polls the program's SDO variable and NMT requests every
  // kRequestPeriod, and the program's SDO function blocks; without it
  // they are polled on each SYNC and supervision tick. `out_timer`, when
  // given and the master produces no SYNC, sends the outputs every
  // kOutputPeriod instead of on SYNC.
  Network(ev_exec_t* exec, lely::io::TimerBase& timer, lely::io::TimerBase& sup_timer,
          lely::io::CanChannelBase& chan, const Config& cfg, const GeneratedConfig& gen,
          ProcessImage& image, std::function<bool()> tick = nullptr, lely::io::TimerBase* req_timer = nullptr,
          lely::io::TimerBase* out_timer = nullptr);
  ~Network();

  // Starts the NMT master (boots all slaves) and the supervision timer.
  void Start();
  // Marks every node down (inputs hold, outputs off, status FALSE).
  void MarkAllDown();
  // The session ends: no new work, and pending LSS requests are cancelled
  // (Lely's I/O shutdown does not end them, and the loop would wait on them).
  void Stop();

  bool IsOperational(unsigned id) const;

  // PLC-cycle SYNC: sends one SYNC for the requests the scan made since the
  // last call (ProcessImage::request_sync), with the newest outputs. Call on
  // the loop thread when ProcessImage::sync_fd() is readable (SyncWake).
  void ServiceSyncRequests();

  // SYNC statistics (canopen-master-bringup "SYNC statistics").
  struct SyncStats {
    uint64_t count = 0;
    uint64_t last_us = 0, min_us = 0, max_us = 0;  // interval between SYNCs
    uint64_t skipped = 0;  // frames merged into one SYNC
    uint64_t late = 0;     // cyclic synchronous node TPDOs that missed their SYNC
  };
  const SyncStats& sync_stats() const { return sync_stats_; }

  // Serves the diagnostics channel's requests from `hub` (call before
  // Start()); the caller attaches and detaches the hub.
  void SetDiag(DiagHub* hub) { diag_ = hub; }

  // Supervision period and retry backoff limits.
  static constexpr std::chrono::milliseconds kTick{100};
  static constexpr std::chrono::milliseconds kRetryMin{1000};
  static constexpr std::chrono::milliseconds kRetryMax{16000};
  // A node that has not come up this long after start is reported.
  static constexpr std::chrono::milliseconds kAbsentAfter{3000};
  // A boot retry that has not reached the configuration step this long after
  // it started means the node is not answering.
  static constexpr std::chrono::milliseconds kNoAnswerAfter{2000};
  // EMCY messages logged one by one per node and second; the rest of that
  // second goes into one summary line (as the bus state log does).
  static constexpr unsigned kLoggedEmcyPerSecond = 5;
  // How often the program's SDO variable and NMT requests are polled.
  static constexpr std::chrono::milliseconds kRequestPeriod{10};
  // Without SYNC: how often the bus thread looks for new outputs from the scan.
  static constexpr std::chrono::milliseconds kOutputPeriod{1};
  // Late PDO and skipped SYNC warnings: at most one per PDO (and one for
  // skips) in this period.
  static constexpr std::chrono::seconds kSyncWarnPeriod{10};

  // SDO variable transfer status (status_location).
  enum SdoStatus : uint8_t { kSdoNone = 0, kSdoBusy = 1, kSdoDone = 2, kSdoAborted = 3, kSdoUnavailable = 4 };
  // NMT state the program (nmt_command_location) or an operator (manual
  // NMT command on the diagnostics channel) holds a node in.
  enum class Hold : uint8_t { None, Stopped, Preop };
  // Emergency messages kept per node for the diagnostics channel.
  static constexpr size_t kEmcyHistory = 16;
  // Network scan: node IDs probed at a time, and the timeouts.
  static constexpr unsigned kScanParallel = 8;
  static constexpr std::chrono::milliseconds kScanProbeTimeout{100};
  static constexpr std::chrono::milliseconds kScanReadTimeout{200};
  // LSS find (fastscan) limit, well above its worst case (~130 LSS timeouts).
  static constexpr std::chrono::milliseconds kLssFindLimit{20000};

 protected:
  void OnBoot(uint8_t id, lely::canopen::NmtState st, char es, const std::string& what) noexcept override;
  void OnConfig(uint8_t id) noexcept override;
  void OnRpdoWrite(uint8_t id, uint16_t idx, uint8_t subidx) noexcept override;
  void OnHeartbeat(uint8_t id, bool occurred) noexcept override;
  void OnNodeGuarding(uint8_t id, bool occurred) noexcept override;
  void OnState(uint8_t id, lely::canopen::NmtState st) noexcept override;
  void OnSync(uint8_t cnt, const time_point& t) noexcept override;
  void OnRpdo(int num, std::error_code ec, const void* p, std::size_t n) noexcept override;
  void OnCommand(lely::canopen::NmtCommand cs) noexcept override;
  void OnEmcy(uint8_t id, uint16_t eec, uint8_t er, uint8_t msef[5]) noexcept override;

 private:
  using clock = std::chrono::steady_clock;

  struct NodeState {
    const NodeConfig* cfg = nullptr;
    const std::vector<SdoWrite>* sdos = nullptr;
    bool up = false;           // operational and exchanging PDOs
    bool booted = false;       // last boot succeeded
    bool node_op = false;      // the node itself is OPERATIONAL
    bool retry_pending = false;
    clock::time_point next_retry;
    std::chrono::milliseconds backoff{kRetryMin};
    size_t cfg_step = 0;       // next SDO of an ongoing configuration
    bool cfg_ok = false;       // this boot's configuration step succeeded
    bool cfg_ran = false;      // this boot's configuration step started
    bool reset_on_retry = false;
    bool boot_waiting = false;    // a boot retry started and no answer yet
    clock::time_point boot_since;
    bool warned_absent = false;   // "not answering" logged since last up
    std::string identity_logged;  // the wrong identity last logged
    std::vector<unsigned> tpdos;  // master TPDO numbers that feed this node
    std::vector<size_t> inputs;   // ProcessImage input bindings of this node
    // EMCY log throttling: messages in the current one-second window, how
    // many of them were not logged, and the latest one.
    clock::time_point emcy_window{};
    unsigned emcy_count = 0;
    unsigned emcy_unlogged = 0;
    uint16_t emcy_code = 0;
    uint8_t emcy_er = 0;
    // The program's NMT command byte: the level last acted on, the reset
    // requests handled, and the state the node is held in.
    uint8_t nmt_level = 0;
    uint64_t nmt_resets = 0;
    Hold hold = Hold::None;
    bool hold_by_operator = false;  // the hold came from a diagnostics client
    std::vector<size_t> vars;  // ProcessImage::sdo_vars() of this node
    bool sdo_busy = false;     // an SDO variable or program transfer is in flight
    bool last_prog = false;    // the last transfer started was the program's
    // Diagnostics: the boot result text, and the newest emergency messages
    // (ring buffer, newest at emcy_head - 1).
    std::string boot_what;
    struct Emcy {
      std::chrono::system_clock::time_point time;
      uint16_t code = 0;
      uint8_t er = 0;
      std::array<uint8_t, 5> msef{};
    };
    std::array<Emcy, kEmcyHistory> emcy_hist{};
    size_t emcy_head = 0;
    size_t emcy_n = 0;
    // LSS assignment before boot retries (lss.assign): next attempt, backoff,
    // and whether one is running for this node.
    clock::time_point lss_next{};
    std::chrono::milliseconds lss_backoff{kRetryMin};
    bool lss_running = false;
  };

  // A run of LSS assignments: the node IDs in order, at start or for a retry.
  struct LssJob {
    std::vector<unsigned> ids;
    size_t next = 0;
    bool retry = false;
    std::function<void()> done;
  };

  // A manual SDO transfer from the diagnostics channel.
  struct ManualSdo {
    DiagRequest req;
    clock::time_point deadline;  // give up if it cannot start by then
    bool in_flight = false;
  };

  // One node ID of a network scan.
  struct ScanEntry {
    unsigned id = 0;
    enum Phase : uint8_t { Waiting, Probing, Reading, Done } phase = Waiting;
    bool answered = false;
    bool booting = false;
    unsigned step = 0;  // follow-up read in progress
    uint32_t values[5] = {};  // vendor, product, revision, serial, device type
    bool has[5] = {};
    std::string name;  // 0x1008
    bool has_name = false;
  };

  // Run-time state of one SDO variable.
  struct VarState {
    bool boot_read = false;     // read due after the node's boot
    bool written = false;       // an owned write was done in this boot
    uint64_t last_written = 0;  // its value
    uint64_t trig_seen = 0;     // trigger edges handled
    bool trig_pending = false;  // a triggered transfer waits for its turn
    clock::time_point next_read{};
    uint32_t logged_abort = 0;  // abort code logged since the last success
  };

  // A program transfer (spec canopen-plc-sdo) waiting for or using its node.
  struct ProgJob {
    PlcRequests::Job job;
    bool resolved = false;  // the write payload is in its final form
  };

  template <class F>
  void Defer(F&& f);
  // Runs an SDO submission. Lely's Submit*() first advances the CAN timers,
  // and reports a Client-SDO timeout that expires right then as a
  // std::system_error ("set_time") although the timeout was handled; the
  // submission itself did not happen and is simply repeated.
  template <class F>
  void Submit(F&& submit, std::error_code& ec);
  void HandleBoot(uint8_t id, lely::canopen::NmtState st, char es, const std::string& what);
  void HandleConfig(uint8_t id);
  void HandleRpdoWrite(uint8_t id, uint16_t idx, uint8_t subidx);
  void HandleHeartbeat(uint8_t id, bool occurred);
  void HandleNodeGuarding(uint8_t id, bool occurred);
  void HandleState(uint8_t id, lely::canopen::NmtState st);
  void HandleCommand(lely::canopen::NmtCommand cs);
  void HandleEmcy(uint8_t id, uint16_t eec, uint8_t er, const std::array<uint8_t, 5>& msef);
  void SetEmcy(unsigned id, uint16_t code, uint8_t er);
  void FlushEmcySummary(NodeState& n, clock::time_point now, bool force);
  // Sets the status bit from the node's and the master's state.
  void Update(unsigned id, const char* why);
  void SetUp(unsigned id, bool up, const char* why);
  void SetBootError(unsigned id, uint8_t letter);
  void SetMasterState(uint8_t state);
  void ReportIdentity(uint8_t id, char es);
  void StartHeldMaster();
  void SetState(unsigned id, uint8_t state);
  void ScheduleRetry(NodeState& n, bool quiet = false);
  void ConfigNext(uint8_t id);
  void EnableTpdos(const NodeState& n, bool enable);
  void MapTpdos();
  // Master RPDOs that carry a node's cyclic synchronous TPDO, for the late
  // PDO check; with PLC-cycle SYNC they are switched to event-driven so the
  // inputs reach the image as they arrive.
  void MapSyncRpdos();
  void CountSync();
  void SendSync();
  void ArmTick();
  void OnTick();
  void WriteOutputs();
  // SDO variables and NMT command bytes (see the spec canopen-sdo-variables).
  void ServiceRequests();
  void ApplyNmtCommand(unsigned id, NodeState& n, uint8_t level, uint64_t resets, uint8_t reset_code);
  void SendHold(unsigned id, const NodeState& n);
  bool SdoAvailable(unsigned id, const NodeState& n) const;
  void StartTransfer(unsigned id, NodeState& n, size_t k, const uint64_t* snap);
  void FinishTransfer(unsigned id, size_t k, std::error_code ec, const std::vector<uint8_t>* data, uint64_t value);
  void SetSdoStatus(size_t k, uint8_t status, uint32_t abort, bool set_abort);
  void OnBooted(unsigned id, NodeState& n);
  // Program transfers from the SDO function blocks (spec canopen-plc-sdo).
  void ServiceProgram(clock::time_point now);
  // Whether node `id`'s oldest program transfer can start now; ends it
  // first when it cannot run at all or ran out of time.
  void StartProgram(unsigned id, NodeState* n, clock::time_point now);
  void FinishProgram(unsigned id, uint32_t handle, const PlcRequests::Job& job, std::error_code ec,
                     const std::vector<uint8_t>* data);
  void EndProgram(unsigned id, uint32_t handle, uint16_t error_id, uint32_t abort, const uint8_t* data,
                  size_t size);
  // The payload of a program write as it goes on the bus: sizes from the EDS
  // and REAL32 conversion. Returns an ERROR_ID, or 0.
  uint16_t ResolveWrite(unsigned id, ProgJob& p);
  // The EDS data type of a configured node's object (0 = not in the EDS).
  uint16_t EdsType(const NodeConfig& n, uint16_t index, uint8_t subindex);
  void ResetNode(unsigned id, NodeState& n, bool comm, const char* by);
  // Diagnostics channel (see the spec canopen-online-diagnostics).
  void ServiceDiag();
  void DiagStatus(const DiagRequest& r);
  void DiagEmcy(const DiagRequest& r);
  void DiagNmt(const DiagRequest& r);
  void StartManual(ManualSdo& m);
  void FinishManual(uint64_t seq, std::error_code ec, const std::vector<uint8_t>* data);
  void DiagScan(const DiagRequest& r, bool start);
  void ScanNext(ScanEntry& e);
  void ScanStep(unsigned id, std::error_code ec, uint32_t value, const std::vector<uint8_t>* data);
  void FinishScan();
  void ReleaseForeignSdo(unsigned id);
  // LSS (canopen-master-bringup and canopen-online-diagnostics specs).
  friend class LssAssigner;
  void LssOnStart(std::function<void(std::error_code)> res);
  void LssRun(std::shared_ptr<LssJob> job);
  void LssFound(std::shared_ptr<LssJob> job, unsigned id);
  void LssJobNext(std::shared_ptr<LssJob> job);
  void LssRecover(clock::time_point now);
  void DiagLss(const DiagRequest& r);
  void DiagLssFind(const DiagRequest& r, bool start);
  void LssDiagDone(uint64_t seq, const std::string& line);

  const Config& cfg_;
  const GeneratedConfig& gen_;
  ProcessImage& image_;
  lely::io::TimerBase& sup_timer_;
  ev_exec_t* exec_;
  std::function<bool()> tick_;
  std::map<unsigned, NodeState> nodes_;
  lely::io::TimerWait tick_wait_;
  lely::io::TimerBase* req_timer_;
  lely::io::TimerWait req_wait_;
  lely::io::TimerBase* out_timer_;
  lely::io::TimerWait out_wait_;
  bool has_requests_ = false;  // any SDO variable or NMT command byte
  std::vector<VarState> vars_;
  std::map<unsigned, uint32_t> tpdo_cob_;  // master TPDO number -> COB-ID
  std::set<unsigned> tpdo_event_;          // event-driven master TPDOs
  std::vector<uint64_t> last_out_;
  // A master RPDO fed by a node's cyclic synchronous TPDO (type 1-240).
  struct SyncRpdo {
    unsigned node_id = 0;
    unsigned pdo = 0;      // the node's TPDO number (0 = unknown)
    unsigned trans = 1;    // the node's transmission type
    unsigned since = 0;    // SYNCs since it last arrived
    bool armed = false;    // arrived once since the node came up
    clock::time_point warned{};
  };
  std::map<unsigned, SyncRpdo> sync_rpdos_;  // master RPDO number ->
  SyncStats sync_stats_;
  clock::time_point last_sync_{};
  clock::time_point skip_warned_{};
  uint64_t sync_seen_ = 0;    // ProcessImage::sync_requests() handled
  uint8_t sync_cnt_ = 1;      // next SYNC counter value (with 0x1019 > 1)
  std::set<unsigned> emcy_unknown_;  // unconfigured node IDs already warned about
  DiagHub* diag_ = nullptr;
  std::vector<ManualSdo> manual_;
  std::map<unsigned, std::deque<ProgJob>> prog_;  // node ID -> program transfers, oldest first
  std::set<unsigned> prog_foreign_busy_;          // unconfigured node IDs with a transfer in flight
  std::vector<PlcRequests::Job> prog_taken_;      // scratch for PlcRequests::take
  std::map<uint32_t, uint16_t> eds_types_;        // node<<24 | index<<8 | subindex -> EDS DataType
  std::set<uint64_t> prog_aborts_logged_;         // node, object and abort code logged
  std::set<uint32_t> prog_owned_warned_;          // node<<24 | index<<8 | subindex warned about
  std::map<unsigned, unsigned> foreign_sdo_;  // unconfigured node ID -> transfers in flight
  bool scan_running_ = false;
  bool scan_have_result_ = false;
  std::vector<ScanEntry> scan_;
  size_t scan_next_ = 0;
  unsigned scan_active_ = 0;
  clock::time_point scan_started_;
  std::chrono::system_clock::time_point scan_finished_at_;
  double scan_seconds_ = 0;
  std::unique_ptr<LssAssigner> lss_;
  bool lss_busy_ = false;  // an LSS sequence (assignment or diagnostics) runs
  bool lss_find_running_ = false;
  bool lss_find_have_ = false;
  bool lss_find_found_ = false;
  uint32_t lss_find_addr_[4] = {};
  int lss_find_node_id_ = -1;  // node ID of the found device (-1 unknown)
  std::string lss_find_error_;
  clock::time_point lss_find_started_;
  double lss_find_seconds_ = 0;
  // TIME producer (master.time_period_ms): sent from the host's real-time
  // clock, since Lely's own producer stamps the bus timer's monotonic clock.
  void SendTime();
  clock::time_point next_time_;
  bool stopped_ = false;
  bool master_op_ = false;  // the master itself is OPERATIONAL (PDOs run)
  uint8_t master_state_ = 0;
  clock::time_point started_;
};

// PLC-cycle SYNC: calls Network::ServiceSyncRequests() on the loop thread
// each time the scan requests a SYNC (ProcessImage::sync_fd() readable).
// Does nothing when `fd` is -1.
class SyncWake {
 public:
  SyncWake(lely::io::Poll& poll, int fd, Network& net);
  ~SyncWake();
  SyncWake(const SyncWake&) = delete;
  SyncWake& operator=(const SyncWake&) = delete;

 private:
  static void OnEvent(struct ::io_poll_watch* watch, int events) noexcept;
  void Arm();

  struct Watch {
    struct ::io_poll_watch w;
    SyncWake* self;
  } watch_;
  lely::io::Poll& poll_;
  int fd_;
  Network& net_;
};

template <class F>
void Network::Defer(F&& f) {
  try {
    lely::ev::Executor(exec_).post(std::forward<F>(f));
  } catch (const std::exception& e) {
    log_error("cannot queue work on the bus thread: %s", e.what());
  }
}

template <class F>
void Network::Submit(F&& submit, std::error_code& ec) {
  for (int attempt = 0;; ++attempt) {
    try {
      submit();
      return;
    } catch (const std::system_error& e) {
      if (attempt == 2) {
        ec = e.code() ? e.code() : std::make_error_code(std::errc::io_error);
        return;
      }
    }
  }
}

}  // namespace canopen_plugin

#endif  // CANOPEN_NETWORK_H
