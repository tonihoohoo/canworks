// bus_monitor.h - CAN bus diagnostics: follows the controller's error state,
// error counters and bus-off count over rtnetlink, logs state changes and
// writes the master's bus diagnostic inputs (canopen-bus-diagnostics spec).
//
// Runs in the bus thread: poll() on every supervision tick while a session
// runs, no_bus() between sessions. It only writes the process image's working
// copy; the caller commits.

#ifndef CANOPEN_BUS_MONITOR_H
#define CANOPEN_BUS_MONITOR_H

#include <chrono>
#include <cstdint>
#include <memory>

#include "can_adapter.h"
#include "config.h"
#include "process_image.h"

namespace canopen_plugin {

// Bus state byte codes, ordered by severity.
enum BusCode : uint8_t {
  kBusNone = 0,     // no usable bus: interface missing, down, stopped, or no session
  kBusActive = 1,   // error-active (also a vcan that is up)
  kBusWarning = 2,  // error-warning (a counter >= 96)
  kBusPassive = 3,  // error-passive (a counter >= 128); a pulled cable ends here
  kBusOff = 4,
};

const char* bus_code_name(uint8_t code);

class BusMonitor {
 public:
  using clock = std::chrono::steady_clock;

  // `ops` defaults to rtnetlink.
  BusMonitor(const Config& cfg, ProcessImage& image, std::unique_ptr<LinkOps> ops = nullptr);

  // At PLC start: the bus-off count starts again from 0.
  void reset();
  // Reads the link (without blocking: LinkOps::request_get / take_get) and
  // updates the image; returns true if an input changed.
  bool poll(clock::time_point now);
  // No session: state 0; the counters keep their last values.
  bool no_bus();
  // A simulated network: error-active, no errors.
  bool simulated();

  uint8_t state() const { return state_; }

 private:
  void on_change(uint8_t from, uint8_t to, clock::time_point now);
  void flush_summary(clock::time_point now, bool force);

  const Config& cfg_;
  ProcessImage& image_;
  std::unique_ptr<LinkOps> ops_;
  bool map_errors_;

  uint8_t state_ = kBusNone;
  uint8_t tx_ = 0;
  uint8_t rx_ = 0;
  uint16_t bus_offs_ = 0;
  bool have_bus_off_base_ = false;
  uint32_t last_bus_off_ = 0;
  bool warned_no_counters_ = false;
  bool warned_slcan_ = false;

  // Flap throttling: changes within the current one-second window.
  clock::time_point window_start_{};
  unsigned window_changes_ = 0;
  bool suppressed_ = false;
};

}  // namespace canopen_plugin

#endif  // CANOPEN_BUS_MONITOR_H
