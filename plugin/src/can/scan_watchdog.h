// scan_watchdog.h - the scan watchdog of a J1939 or plain CAN network
// (j1939.scan_watchdog_ms, raw.scan_watchdog_ms; canopen-pdo-io "Scan
// watchdog for every protocol"). Like a CANopen master's
// master.scan_watchdog_ms it closes the shared outputs gate while the PLC
// scan has not finished a cycle for that long, and opens it at the next one.
// The engine keeps one per such network for the PLC run and checks them all
// from one thread.

#ifndef CANWORKS_SCAN_WATCHDOG_H
#define CANWORKS_SCAN_WATCHDOG_H

#include <atomic>
#include <chrono>
#include <cstdint>
#include <string>

#include "config.h"

namespace canopen_plugin {

// The network's own scan watchdog setting (0: none): J1939 and plain CAN
// networks; a CANopen master runs its own (master.scan_watchdog_ms).
unsigned own_scan_watchdog_ms(const Config& cfg);

class ScanWatchdog {
 public:
  using clock = std::chrono::steady_clock;
  // `key` names the setting in the log ("j1939.scan_watchdog_ms"); `prefix`
  // is the network's log prefix.
  ScanWatchdog(unsigned ms, std::string key, std::string prefix);
  ~ScanWatchdog() { release(); }
  ScanWatchdog(const ScanWatchdog&) = delete;
  ScanWatchdog& operator=(const ScanWatchdog&) = delete;

  // The PLC scan finished a cycle (cycle_end: never blocks or allocates).
  void scan_done() { scans_.fetch_add(1, std::memory_order_relaxed); }
  // The watchdog thread: trips or clears at `now`.
  void check(clock::time_point now);
  // The PLC stops: a trip ends with it, and the next run starts afresh.
  void release();
  bool hung() const { return hung_; }

 private:
  unsigned ms_;
  std::string key_, prefix_;
  std::atomic<uint64_t> scans_{0};
  uint64_t seen_ = 0;
  clock::time_point moved_{};
  bool hung_ = false;
};

}  // namespace canopen_plugin

#endif  // CANWORKS_SCAN_WATCHDOG_H
