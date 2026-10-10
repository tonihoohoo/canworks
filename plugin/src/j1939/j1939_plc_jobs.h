// j1939_plc_jobs.h - the job slots behind canworks_j1939_api (spec
// j1939-plc-diagnostics): DM1/DM2 reads and DM3/DM11 clears the PLC program
// starts through the library's trouble code blocks.
//
// The PLC task threads call start(), poll() and cancel() through the C table
// (j1939_plc_api.h); each J1939 network's bus thread takes the queued jobs of
// its network, runs them in its J1939Engine and puts the results back. All
// slots live in one static table, so the scan path never allocates; the
// mutex is held only to copy a job or a result, as in the SDO blocks'
// PlcRequests (canopen/plc_api.h).

#ifndef CANWORKS_J1939_PLC_JOBS_H
#define CANWORKS_J1939_PLC_JOBS_H

#include <atomic>
#include <chrono>
#include <cstdint>
#include <mutex>
#include <vector>

#include "j1939_plc_api.h"

namespace canopen_plugin {

class J1939PlcJobs {
 public:
  using clock = std::chrono::steady_clock;
  static constexpr uint32_t kDefaultTimeoutMs = 1000;
  static constexpr unsigned kMaxNetworks = 32;
  // How long a finished job's result waits for its block.
  static constexpr std::chrono::seconds kKeepResult{10};
  // A job no bus thread finishes ends with a timeout this long after its
  // timeout, so its slot is freed (the bus thread's own timeout comes first).
  static constexpr std::chrono::seconds kGrace{2};

  enum class Kind : uint8_t { ReadDm1, ReadDm2, ClearDm3, ClearDm11 };
  struct Job {
    uint32_t handle = 0;
    Kind kind = Kind::ReadDm1;
    uint8_t address = 0;
    uint32_t timeout_ms = kDefaultTimeoutMs;
  };

  static J1939PlcJobs& instance();

  // Plugin lifecycle: open() when the networks start, with one flag per
  // network of the config (true: J1939); close() when the PLC stops (every
  // job is dropped, so its handle ends with CANWORKS_J1939_ERR_CANCELLED).
  void open(const std::vector<bool>& j1939_networks);
  void close();
  bool running() const { return running_.load(std::memory_order_acquire); }
  // Bus thread: its network runs (takes jobs) or not.
  void set_attached(unsigned network, bool attached);

  // PLC task threads (through the C table).
  uint32_t start(uint8_t network, Kind kind, uint8_t address, uint32_t timeout_ms, uint16_t& error_id);
  int poll(uint32_t handle, bool read, canworks_j1939_dm* out, uint16_t& error_id) {
    return poll(handle, read, out, error_id, clock::now());
  }
  int poll(uint32_t handle, bool read, canworks_j1939_dm* out, uint16_t& error_id, clock::time_point now);
  void cancel(uint32_t handle);

  // Bus thread: the network's queued jobs, oldest first, marked as taken
  // (results nobody collected in time are dropped meanwhile).
  void take(unsigned network, std::vector<Job>& out);
  // Bus thread: the result of a taken job (ignored if it was dropped).
  void finish(uint32_t handle, uint16_t error_id, const canworks_j1939_dm* result = nullptr);

 private:
  enum class State : uint8_t { Free, Queued, Taken, Done };
  struct Slot {
    State state = State::Free;
    uint32_t seq = 0;
    uint64_t order = 0;
    uint8_t network = 0;
    Job job;
    uint16_t error_id = 0;
    canworks_j1939_dm result{};
    clock::time_point started;
    clock::time_point done_at;
  };

  J1939PlcJobs() = default;
  Slot* find(uint32_t handle);

  std::mutex mutex_;
  Slot slots_[CANWORKS_J1939_SLOTS];
  uint32_t next_seq_ = 1;
  uint64_t next_order_ = 1;
  std::atomic<bool> running_{false};
  std::atomic<uint32_t> j1939_{0};    // bit i: network i is J1939
  std::atomic<uint32_t> networks_{0};  // networks in the config
  std::atomic<uint32_t> attached_{0};  // bit i: network i's bus thread runs
};

}  // namespace canopen_plugin

#endif  // CANWORKS_J1939_PLC_JOBS_H
