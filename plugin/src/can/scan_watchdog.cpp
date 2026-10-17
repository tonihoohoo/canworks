// scan_watchdog.cpp - see scan_watchdog.h.

#include "scan_watchdog.h"

#include "log.h"
#include "outputs_gate.h"

namespace canopen_plugin {

unsigned own_scan_watchdog_ms(const Config& cfg) {
  if (cfg.is_j1939()) return cfg.j1939.scan_watchdog_ms;
  if (cfg.is_plain()) return cfg.raw.scan_watchdog_ms;
  return 0;
}

ScanWatchdog::ScanWatchdog(unsigned ms, std::string key, std::string prefix)
    : ms_(ms), key_(std::move(key)), prefix_(std::move(prefix)) {}

void ScanWatchdog::check(clock::time_point now) {
  uint64_t count = scans_.load(std::memory_order_relaxed);
  if (count != seen_ || moved_ == clock::time_point{}) {
    seen_ = count;
    moved_ = now;
    if (hung_) {
      hung_ = false;
      set_scan_hung(false);
      ScopedLogPrefix p(prefix_);
      log_info("scan watchdog: the PLC scan finishes cycles again; outputs on");
    }
    return;
  }
  // Armed once the program has finished its first cycle.
  if (!ms_ || !count || hung_ || now - moved_ < std::chrono::milliseconds(ms_)) return;
  hung_ = true;
  set_scan_hung(true);
  ScopedLogPrefix p(prefix_);
  log_error("scan watchdog: the PLC scan has not finished a cycle for %u ms (%s); outputs off until it does", ms_,
            key_.c_str());
}

void ScanWatchdog::release() {
  moved_ = clock::time_point{};  // a new run starts timing at its first check
  if (!hung_) return;
  hung_ = false;
  set_scan_hung(false);
}

}  // namespace canopen_plugin
