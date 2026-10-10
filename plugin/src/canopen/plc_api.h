// plc_api.h - the request slots behind canopen_plc_api (spec
// canopen-plc-sdo): SDO transfers the PLC program starts through the
// library's function blocks; and behind canopen_plc_nmt_api (spec
// canopen-plc-nmt): the NMT blocks' requests and the NMT state snapshot.
//
// The scan thread calls start() and poll() through the C table; the bus
// thread takes queued requests, runs them on the Lely loop and puts the
// results back. All slots live in one static table, so the scan path never
// allocates; the mutex is held only to copy a request or a result. The NMT
// requests have their own 16 slots under the same mutex; the snapshot is
// one atomic word per node, written by the bus thread and read without a lock.

#ifndef CANOPEN_PLC_API_IMPL_H
#define CANOPEN_PLC_API_IMPL_H

#include <atomic>
#include <chrono>
#include <cstdint>
#include <mutex>
#include <vector>

#include "canopen_plc_api.h"
#include "canopen_plc_nmt_api.h"

namespace canopen_plugin {

class PlcRequests {
 public:
  using clock = std::chrono::steady_clock;
  // How long a finished transfer's result waits for its block.
  static constexpr std::chrono::seconds kKeepResult{10};
  static constexpr uint32_t kDefaultTimeoutMs = 1000;
  // A taken request whose network never answers ends with a timeout this
  // long after its TIMEOUT (the network waits at most TIMEOUT plus
  // Network::kAbsentAfter, 3 s, for a booting node), so its slot is freed.
  static constexpr std::chrono::seconds kTakenGrace{5};

  // A request the bus thread runs.
  struct Job {
    uint32_t handle = 0;
    canopen_plc_request req{};  // req.data is null; the payload is in `data`
    std::vector<uint8_t> data;
    clock::time_point deadline;
  };

  static PlcRequests& instance();

  // Scan thread (through the C table).
  uint32_t start(const canopen_plc_request& req, uint16_t& error_id);
  int poll(uint32_t handle, canopen_plc_result* res, uint8_t* data, uint32_t cap) {
    return poll(handle, res, data, cap, clock::now());
  }
  int poll(uint32_t handle, canopen_plc_result* res, uint8_t* data, uint32_t cap, clock::time_point now);

  // Plugin lifecycle: open() when CANopen runs, with the networks that take
  // SDO requests as bits (bit i = network i in the config: the CANopen master
  // networks; a request naming any other ends at once with
  // CANOPEN_PLC_ERR_INPUT); close() when the PLC stops (every request is
  // dropped, so their handles end with CANOPEN_PLC_ERR_CANCELLED).
  void open(uint32_t sdo_networks = 1);
  void close();
  bool running() const { return running_.load(std::memory_order_acquire); }
  // Whether network `network` is one of the CANopen master networks open() named.
  bool takes_network(unsigned network) const {
    return network < 32 && (sdo_networks_.load(std::memory_order_acquire) >> network & 1u);
  }

  // Bus thread: the network's queued requests, oldest first, marked as taken.
  void take(unsigned network, std::vector<Job>& out);
  // Bus thread: the result of a taken request (ignored if it was dropped).
  void finish(uint32_t handle, uint16_t error_id, uint32_t abort_code, const uint8_t* data, size_t size);
  // Bus thread: drops results no block collected in time.
  void expire(clock::time_point now);
  // Bus thread: the network that took requests is gone; they end with
  // CANOPEN_PLC_ERR_CANCELLED.
  void cancel_taken(unsigned network);
  // The API version a block asked for and this plugin does not offer, once
  // (0 = none since the last call).
  uint32_t take_unknown_version();
  void note_unknown_version(uint32_t version);

  // --- NMT blocks (canopen_plc_nmt_api.h) ---------------------------------
  // A request no network takes this long ends with CANOPEN_PLC_ERR_NOT_RUNNING
  // (the network's bus session is not up).
  static constexpr std::chrono::seconds kNmtTakeLimit{1};
  struct NmtJob {
    uint32_t handle = 0;
    canopen_plc_nmt_request req{};
  };
  // Scan thread (through the C table).
  uint32_t start_nmt(const canopen_plc_nmt_request& req, uint16_t& error_id);
  int poll_nmt(uint32_t handle, uint16_t& error_id) { return poll_nmt(handle, error_id, clock::now()); }
  int poll_nmt(uint32_t handle, uint16_t& error_id, clock::time_point now);
  uint16_t get_state(uint8_t network, uint8_t node, canopen_plc_nmt_state& out) const;
  // The master's node ID on `network`, so CO_NMT refuses it in the call
  // that starts (set after open(); 0: unknown).
  void set_master_node(unsigned network, uint8_t node_id);
  // Bus thread: the network's queued NMT requests, oldest first, marked taken.
  void take_nmt(unsigned network, std::vector<NmtJob>& out);
  // Bus thread: the end of a taken NMT request (ignored if it was dropped).
  void finish_nmt(uint32_t handle, uint16_t error_id);
  // Bus thread: the NMT state snapshot of `network`. Node entries: what the
  // master last saw, the hold it keeps applying (0, 2, 128) and the boot
  // error; master entry: its state and whether the program lets it run.
  // clear_snapshot() empties the network's entries (every node "not
  // configured") before a session publishes its own.
  void clear_snapshot(unsigned network);
  void publish_node(unsigned network, unsigned node, uint8_t state, uint8_t held, uint8_t boot_error);
  void publish_master(unsigned network, uint8_t state, bool started);
  // The NMT API version a block asked for and this plugin does not offer,
  // once (0 = none since the last call).
  uint32_t take_unknown_nmt_version();
  void note_unknown_nmt_version(uint32_t version);

  // Snapshot word layout (exposed for the unit tests).
  static uint32_t pack_node(uint8_t state, uint8_t held, uint8_t boot_error) {
    return kConfigured | uint32_t(boot_error) << 16 | uint32_t(held) << 8 | state;
  }
  static constexpr uint32_t kConfigured = 1u << 24;
  static constexpr uint32_t kStarted = 1u << 25;
  static constexpr unsigned kSnapshotNetworks = 32;

 private:
  enum class State : uint8_t { Free, Queued, Taken, Done };
  struct Slot {
    State state = State::Free;
    uint32_t seq = 0;
    uint64_t order = 0;  // start order, for oldest-first
    canopen_plc_request req{};
    uint32_t length = 0;  // write payload, then reply bytes kept
    uint8_t buf[CANOPEN_PLC_MAX_DATA] = {};
    canopen_plc_result res{};
    clock::time_point started;
    clock::time_point done_at;
  };

  PlcRequests() = default;
  Slot* find(uint32_t handle);
  uint16_t validate(const canopen_plc_request& req) const;

  std::mutex mutex_;
  Slot slots_[CANOPEN_PLC_SLOTS];
  uint32_t next_seq_ = 1;
  uint64_t next_order_ = 1;
  std::atomic<bool> running_{false};
  std::atomic<uint32_t> sdo_networks_{1};
  std::atomic<uint32_t> unknown_version_{0};
  bool unknown_logged_ = false;

  struct NmtSlot {
    State state = State::Free;
    uint32_t seq = 0;
    uint64_t order = 0;
    canopen_plc_nmt_request req{};
    uint16_t error_id = 0;
    clock::time_point started;
    clock::time_point done_at;
  };
  NmtSlot* find_nmt(uint32_t handle);
  uint16_t validate_nmt(const canopen_plc_nmt_request& req) const;
  NmtSlot nmt_slots_[CANOPEN_PLC_NMT_SLOTS];
  std::atomic<uint8_t> master_ids_[kSnapshotNetworks] = {};
  // [network][0] the master, [network][1..127] the nodes.
  std::atomic<uint32_t> snapshot_[kSnapshotNetworks][128] = {};
  std::atomic<uint32_t> unknown_nmt_version_{0};
  bool unknown_nmt_logged_ = false;
};

// What canopen_plc_api(version) returns: the function table for `version`,
// or null (noted for the log) when this plugin does not offer it.
const void* plc_api_table(uint32_t version);
// The same for canopen_plc_nmt_api(version).
const void* plc_nmt_api_table(uint32_t version);

}  // namespace canopen_plugin

#endif  // CANOPEN_PLC_API_IMPL_H
