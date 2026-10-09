// plc_api.h - the request slots behind canopen_plc_api (spec
// canopen-plc-sdo): SDO transfers the PLC program starts through the
// library's function blocks.
//
// The scan thread calls start() and poll() through the C table; the bus
// thread takes queued requests, runs them on the Lely loop and puts the
// results back. All slots live in one static table, so the scan path never
// allocates; the mutex is held only to copy a request or a result.

#ifndef CANOPEN_PLC_API_IMPL_H
#define CANOPEN_PLC_API_IMPL_H

#include <atomic>
#include <chrono>
#include <cstdint>
#include <mutex>
#include <vector>

#include "canopen_plc_api.h"

namespace canopen_plugin {

class PlcRequests {
 public:
  using clock = std::chrono::steady_clock;
  // How long a finished transfer's result waits for its block.
  static constexpr std::chrono::seconds kKeepResult{10};
  static constexpr uint32_t kDefaultTimeoutMs = 1000;

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
  int poll(uint32_t handle, canopen_plc_result* res, uint8_t* data, uint32_t cap);

  // Plugin lifecycle: open() when CANopen runs, with the number of networks
  // (a request names one of them, 0 = the first in the config); close() when
  // the PLC stops (every request is dropped, so their handles end with
  // CANOPEN_PLC_ERR_CANCELLED).
  void open(unsigned networks = 1);
  void close();
  bool running() const { return running_.load(std::memory_order_acquire); }

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
  std::atomic<unsigned> networks_{1};
  std::atomic<uint32_t> unknown_version_{0};
  bool unknown_logged_ = false;
};

// What canopen_plc_api(version) returns: the function table for `version`,
// or null (noted for the log) when this plugin does not offer it.
const void* plc_api_table(uint32_t version);

}  // namespace canopen_plugin

#endif  // CANOPEN_PLC_API_IMPL_H
