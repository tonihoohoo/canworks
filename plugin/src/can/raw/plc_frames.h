// plc_frames.h - the plugin side of the PLC program's CAN frame blocks
// (spec can-plc-frames; C interface in ../can_plc_api.h).
//
// One PlcPort per network. Two threads use it:
// - the PLC scan thread, through canworks_can_api(): opens and reads
//   receivers, queues frames, runs cyclic jobs, reads bus info. These calls
//   never wait, allocate or log.
// - the network's raw I/O thread (or the bus thread on a simulated network):
//   hands it every received frame, takes queued and due cyclic frames,
//   reports writes and echoes, and publishes bus info.
// Everything between the two is lock-free: single-producer/single-consumer
// rings and atomics, with epochs so a frame from before a receiver was
// reopened is never shown.

#ifndef CANWORKS_RAW_PLC_FRAMES_H
#define CANWORKS_RAW_PLC_FRAMES_H

#include <array>
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <functional>

#include "../can_plc_api.h"

namespace canworks_raw {

// Microseconds on CLOCK_MONOTONIC.
uint64_t monotonic_us();

// What a network allows program frames to do.
struct PortRules {
  bool listen_only = false;
  // Program frames may use identifiers the protocol owns
  // (raw.program_override_protocol).
  bool override_protocol = false;
  // True when the network's protocol uses this identifier (extended or not).
  // Called on the scan thread: must not allocate or lock.
  std::function<bool(uint32_t id, bool extended)> owned;
};

class PlcPort {
 public:
  explicit PlcPort(uint8_t network);
  PlcPort(const PlcPort&) = delete;
  PlcPort& operator=(const PlcPort&) = delete;

  uint8_t network() const { return network_; }

  // Set while the PLC is stopped (config load); not thread-safe against the
  // scan.
  void set_rules(PortRules rules);

  // --- Scan thread (canworks_can_api) ---
  uint32_t rx_open(uint32_t id, uint32_t mask, uint8_t flags, uint16_t depth, uint16_t* error_id);
  int rx_read(uint32_t handle, canworks_can_frame* frame, canworks_can_rx_info* info);
  void rx_close(uint32_t handle);
  uint32_t tx_send(const canworks_can_frame* frame, uint32_t timeout_ms, uint16_t* error_id);
  int tx_poll(uint32_t handle, uint16_t* error_id);
  uint32_t cyc_start(const canworks_can_frame* frame, uint32_t period_us, uint16_t* error_id);
  int cyc_update(uint32_t handle, const canworks_can_frame* frame, uint32_t period_us, uint32_t* count,
                 uint16_t* error_id);
  void cyc_stop(uint32_t handle);
  int bus_info(canworks_can_bus_info* info, uint16_t* error_id);

  // --- Raw I/O thread ---
  // The network runs (frames can be sent and received) or not.
  void set_running(bool running);
  bool running() const { return running_.load(std::memory_order_acquire); }
  // A frame from the bus that this plugin did not send.
  void on_frame(const canworks_can_frame& frame);
  // True while an open receiver or cyclic job exists: the raw path must run
  // (and its socket filter include the receivers).
  bool active() const;
  // Calls f(id, mask, flags) for every open receiver, for socket filters.
  void for_each_receiver(const std::function<void(uint32_t, uint32_t, uint8_t)>& f) const;
  // Changes each time a receiver opens or closes.
  uint32_t receivers_version() const { return rx_version_.load(std::memory_order_acquire); }
  // The next queued program frame; `tag` names it for tx_done().
  bool next_tx(canworks_can_frame& frame, uint32_t& tag);
  // The frame was written. With `confirmed`, it counts as on the bus now;
  // otherwise the next matching own_echo() confirms it.
  void tx_written(uint32_t tag, bool confirmed);
  // A frame next_tx() gave is still wanted (not given up by the block's
  // TIMEOUT); frees the slot when it was given up.
  bool tx_pending(uint32_t tag);
  // The frame could not be written (error_id: CANWORKS_CAN_ERR_BUS ...).
  void tx_failed(uint32_t tag, uint16_t error_id);
  // An echo of a frame this plugin sent; confirms the oldest written frame
  // with the same identifier, flags, DLC and data. False when none matched
  // (the echo is someone else's, e.g. a config message).
  bool own_echo(const canworks_can_frame& frame);
  // Echoes that did not come within `max_age_us` fail their frames with
  // CANWORKS_CAN_ERR_TIMEOUT (adapters that stopped echoing, bus-off).
  void expire_echoes(uint64_t now_us, uint64_t max_age_us);
  // Fills `out` with up to `max` cyclic frames due at `now_us`; returns how
  // many. Count them with cyclic_sent() once written.
  int cyclic_due(uint64_t now_us, canworks_can_frame* out, uint8_t* jobs, int max);
  void cyclic_sent(uint8_t job);
  // Microseconds until the next cyclic frame is due (UINT64_MAX: none).
  uint64_t next_cyclic_in(uint64_t now_us) const;
  void publish_bus(const canworks_can_bus_info& info);
  // Counted into bus info's rx/tx counts by the raw path.
  void count_rx() { rx_count_.fetch_add(1, std::memory_order_relaxed); }
  void count_tx() { tx_count_.fetch_add(1, std::memory_order_relaxed); }

  // --- Either side, with the scan stopped or between scans ---
  // PLC stop or network restart: every receiver closes, every job stops, and
  // every handle from before answers CANWORKS_CAN_ERR_CANCELLED.
  void cancel_all();

  // Counters for diagnostics status.
  struct Stats {
    uint32_t receivers = 0;
    uint32_t cyclic_jobs = 0;
    uint32_t dropped = 0;
    uint32_t sent = 0;
  };
  Stats stats() const;

 private:
  static constexpr unsigned kRx = CANWORKS_CAN_RECEIVERS;
  static constexpr unsigned kJobs = CANWORKS_CAN_CYCLIC_JOBS;
  static constexpr unsigned kTx = CANWORKS_CAN_TX_QUEUE;
  static constexpr unsigned kDepth = CANWORKS_CAN_DEPTH_MAX;

  struct Entry {
    canworks_can_frame frame;
    uint32_t epoch;
  };
  struct Receiver {
    // Written by the scan thread before `open` is published.
    uint32_t id = 0, mask = 0;
    uint8_t flags = 0;
    uint16_t depth = 0;
    uint32_t gen = 0;            // handle generation (scan thread)
    uint32_t dropped_base = 0;   // scan thread
    std::atomic<uint32_t> epoch{0};
    std::atomic<bool> open{false};
    std::atomic<uint32_t> head{0};  // raw thread
    std::atomic<uint32_t> tail{0};  // scan thread
    std::atomic<uint32_t> dropped{0};
    std::array<Entry, kDepth> ring{};
  };
  enum TxState : uint8_t { kFree = 0, kQueued, kWritten, kDone, kFailed, kAbandoned };
  struct TxSlot {
    canworks_can_frame frame{};
    uint32_t gen = 0;           // scan thread
    uint64_t deadline_us = 0;   // scan thread
    uint64_t written_us = 0;    // raw thread
    std::atomic<uint8_t> state{kFree};
    std::atomic<uint16_t> error{0};
  };
  struct Job {
    uint32_t gen = 0;  // scan thread
    std::atomic<bool> active{false};
    std::atomic<uint32_t> start{0};  // bumps on every start; raw thread restarts its timer
    std::atomic<uint32_t> seq{0};    // seqlock over frame and period
    canworks_can_frame frame{};
    uint32_t period_us = 0;
    std::atomic<uint32_t> count{0};
    // Raw thread only.
    uint32_t seen_start = 0;
    uint64_t next_due = 0;
  };

  uint32_t make_handle(unsigned kind, unsigned slot, uint32_t gen) const;
  bool split_handle(uint32_t handle, unsigned kind, unsigned& slot, uint32_t& gen) const;
  uint16_t check_send(const canworks_can_frame& f) const;
  // The last published bus state is bus-off or down.
  bool bus_down() const;
  void read_job(const Job& j, canworks_can_frame& f, uint32_t& period_us) const;

  uint8_t network_;
  PortRules rules_;
  std::atomic<bool> running_{false};
  std::atomic<uint32_t> rx_version_{0};
  std::array<Receiver, kRx> rx_;
  std::array<TxSlot, kTx> tx_;
  // Ring of tx_ indices, scan thread to raw thread.
  std::array<uint8_t, kTx> txq_{};
  std::atomic<uint32_t> txq_head_{0}, txq_tail_{0};
  // Written frames waiting for their echo, oldest first (raw thread only).
  std::array<uint8_t, kTx> echo_{};
  uint32_t echo_head_ = 0, echo_tail_ = 0;
  std::array<Job, kJobs> jobs_;
  std::atomic<uint32_t> bus_seq_{0};
  canworks_can_bus_info bus_{};
  std::atomic<uint32_t> rx_count_{0}, tx_count_{0}, sent_{0};
};

// The ports the scan-side table dispatches to, by network number. The core
// sets them at config load (PLC stopped); nullptr = no such network.
void set_port(uint8_t network, PlcPort* port);
PlcPort* port(uint8_t network);
constexpr uint8_t kMaxNetworks = 8;

}  // namespace canworks_raw

#endif  // CANWORKS_RAW_PLC_FRAMES_H
