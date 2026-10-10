// plc_frames.h - the plugin side of the PLC program's CAN frame blocks
// (spec can-plc-frames; C interface in ../can_plc_api.h).
//
// One PlcPort per network. These threads use it:
// - the PLC task threads (one per task), through canworks_can_api(): open
//   and read receivers, queue frames, run cyclic jobs, read bus info. These
//   calls never wait, allocate or log. Several tasks may call at once: free
//   slots are claimed with compare-and-swap, and a handle belongs to the
//   block instance (so the task) that got it.
// - the network's raw I/O thread (or the bus thread on a simulated network):
//   hands it every received frame, takes queued and due cyclic frames,
//   reports writes and echoes, and publishes bus info.
// Everything between them is lock-free: a bounded multi-producer queue of
// frames to send, single-producer/single-consumer receive rings, seqlocks
// over relaxed atomic words, and epochs so a frame from before a receiver
// was reopened is never shown.

#ifndef CANWORKS_RAW_PLC_FRAMES_H
#define CANWORKS_RAW_PLC_FRAMES_H

#include <array>
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <functional>
#include <type_traits>

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

// A trivially copyable value kept as relaxed atomic 32-bit words, so a
// seqlock reader that races a writer reads stale or mixed words, never
// undefined data. Seq guards consistency.
template <typename T>
class AtomicWords {
  static_assert(std::is_trivially_copyable<T>::value, "plain data only");

 public:
  void store(const T& v) {
    uint32_t w[kWords] = {};
    std::memcpy(w, &v, sizeof(T));
    for (size_t i = 0; i < kWords; ++i) words_[i].store(w[i], std::memory_order_relaxed);
  }
  T load() const {
    uint32_t w[kWords];
    for (size_t i = 0; i < kWords; ++i) w[i] = words_[i].load(std::memory_order_relaxed);
    T v;
    std::memcpy(&v, w, sizeof(T));
    return v;
  }

 private:
  static constexpr size_t kWords = (sizeof(T) + 3) / 4;
  std::array<std::atomic<uint32_t>, kWords> words_{};
};

// One writer, any readers; a read fails (false) while a write is under way.
template <typename T>
class SeqBox {
 public:
  void write(const T& v) {
    uint32_t s = seq_.load(std::memory_order_relaxed);
    seq_.store(s + 1, std::memory_order_relaxed);
    std::atomic_thread_fence(std::memory_order_release);
    data_.store(v);
    seq_.store(s + 2, std::memory_order_release);
  }
  // `out` gets what was read, even when it may be mixed (false).
  bool try_read(T& out) const {
    uint32_t a = seq_.load(std::memory_order_acquire);
    out = data_.load();
    std::atomic_thread_fence(std::memory_order_acquire);
    return !(a & 1u) && seq_.load(std::memory_order_relaxed) == a;
  }

 private:
  std::atomic<uint32_t> seq_{0};
  AtomicWords<T> data_;
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

  // --- PLC task threads (canworks_can_api) ---
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

  // --- Either side, with every PLC task stopped or between scans ---
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

  // Slot states of receivers and cyclic jobs: a task claims a free slot
  // (compare-and-swap), sets it up, then publishes it open.
  enum SlotState : uint8_t { kSlotFree = 0, kSlotClaimed, kSlotOpen };

  struct Entry {
    canworks_can_frame frame;
    uint32_t epoch;
  };
  struct Receiver {
    std::atomic<uint8_t> state{kSlotFree};
    // The filter: written by the claiming task after the epoch bump, read
    // by the raw thread, which re-checks the epoch after matching.
    std::atomic<uint32_t> id{0}, mask{0};
    std::atomic<uint8_t> flags{0};
    std::atomic<uint16_t> depth{0};
    std::atomic<uint32_t> gen{0};  // handle generation
    uint32_t dropped_base = 0;     // the owning task
    std::atomic<uint32_t> epoch{0};
    std::atomic<uint32_t> head{0};  // raw thread
    std::atomic<uint32_t> tail{0};  // the owning task
    std::atomic<uint32_t> dropped{0};
    std::array<Entry, kDepth> ring{};
  };
  // kClaimed: a task is filling the slot; the raw thread does not see it yet.
  enum TxState : uint8_t { kFree = 0, kQueued, kWritten, kDone, kFailed, kAbandoned, kClaimed };
  struct TxSlot {
    canworks_can_frame frame{};  // written by the claiming task before kQueued
    std::atomic<uint32_t> gen{0};
    uint64_t deadline_us = 0;   // the owning task
    uint64_t written_us = 0;    // raw thread
    std::atomic<uint8_t> state{kFree};
    std::atomic<uint16_t> error{0};
  };
  struct JobData {
    canworks_can_frame frame;
    uint32_t period_us;
  };
  struct Job {
    std::atomic<uint8_t> state{kSlotFree};
    std::atomic<uint32_t> gen{0};
    std::atomic<uint32_t> start{0};  // bumps on every start; raw thread restarts its timer
    SeqBox<JobData> data;            // written by the owning task
    std::atomic<uint32_t> count{0};
    // Raw thread only.
    uint32_t seen_start = 0;
    uint64_t next_due = 0;
    JobData last{};  // the last consistent read of `data`
  };
  // A cell of the transmit queue (bounded MPSC, per-cell sequence numbers).
  struct TxCell {
    std::atomic<uint32_t> seq{0};
    uint8_t slot = 0;
  };

  uint32_t make_handle(unsigned kind, unsigned slot, uint32_t gen) const;
  bool split_handle(uint32_t handle, unsigned kind, unsigned& slot, uint32_t& gen) const;
  uint16_t check_send(const canworks_can_frame& f) const;
  // The last published bus state is bus-off or down.
  bool bus_down() const;
  // Puts a queued tx_ slot on the transmit queue (any task); false when full.
  bool push_tx(uint8_t slot);

  uint8_t network_;
  PortRules rules_;
  std::atomic<bool> running_{false};
  std::atomic<uint32_t> rx_version_{0};
  std::array<Receiver, kRx> rx_;
  std::array<TxSlot, kTx> tx_;
  // Queue of tx_ indices, PLC tasks to raw thread.
  static_assert((kTx & (kTx - 1)) == 0, "the transmit queue size is a power of two");
  std::array<TxCell, kTx> txq_;
  std::atomic<uint32_t> txq_head_{0}, txq_tail_{0};
  // Written frames waiting for their echo, oldest first (raw thread only).
  std::array<uint8_t, kTx> echo_{};
  uint32_t echo_head_ = 0, echo_tail_ = 0;
  std::array<Job, kJobs> jobs_;
  // Bus info, double-buffered: the raw thread writes the copy readers are
  // not directed to, then switches them over, so a reader always has a
  // complete copy even while the raw thread is stopped in a write.
  std::array<SeqBox<canworks_can_bus_info>, 2> bus_;
  std::atomic<uint32_t> bus_current_{0};
  std::atomic<uint8_t> bus_state_{4};
  // The last complete copy a reader got, for readers the raw thread laps
  // (written by one reader at a time: whoever takes the flag).
  SeqBox<canworks_can_bus_info> bus_last_;
  std::atomic<bool> bus_last_busy_{false};
  std::atomic<uint32_t> rx_count_{0}, tx_count_{0}, sent_{0};
};

// The ports the scan-side table dispatches to, by network number. The core
// sets them at config load (PLC stopped); nullptr = no such network.
void set_port(uint8_t network, PlcPort* port);
PlcPort* port(uint8_t network);
constexpr uint8_t kMaxNetworks = 8;

}  // namespace canworks_raw

#endif  // CANWORKS_RAW_PLC_FRAMES_H
