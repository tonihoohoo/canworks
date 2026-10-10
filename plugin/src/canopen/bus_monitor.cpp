#include "bus_monitor.h"

#include <linux/can/netlink.h>

#include "log.h"

namespace canopen_plugin {

namespace {

constexpr unsigned kLoggedChangesPerSecond = 5;

uint8_t code_of(const LinkInfo& li) {
  if (!li.up) return kBusNone;
  if (li.kind != "can" || !li.has_can_state) return kBusActive;
  switch (li.can_state) {
    case CAN_STATE_ERROR_ACTIVE: return kBusActive;
    case CAN_STATE_ERROR_WARNING: return kBusWarning;
    case CAN_STATE_ERROR_PASSIVE: return kBusPassive;
    case CAN_STATE_BUS_OFF: return kBusOff;
    default: return kBusNone;  // stopped, sleeping
  }
}

uint8_t clamp8(unsigned v) { return v > 255 ? 255 : static_cast<uint8_t>(v); }

}  // namespace

const char* bus_code_name(uint8_t code) {
  switch (code) {
    case kBusActive: return "error-active";
    case kBusWarning: return "error-warning";
    case kBusPassive: return "error-passive";
    case kBusOff: return "bus-off";
    default: return "no bus";
  }
}

BusMonitor::BusMonitor(const Config& cfg, ProcessImage& image, std::unique_ptr<LinkOps> ops)
    : cfg_(cfg),
      image_(image),
      ops_(ops ? std::move(ops) : make_netlink_ops()),
      map_errors_(cfg.master.has_tx_error_count_location || cfg.master.has_rx_error_count_location) {}

void BusMonitor::reset() {
  warned_slcan_ = false;
  bus_offs_ = 0;
  have_bus_off_base_ = false;
  image_.set_bus_off_count(0);
}

bool BusMonitor::no_bus() {
  if (state_ == kBusNone) return false;
  state_ = kBusNone;
  image_.set_bus_state(kBusNone);
  return true;
}

bool BusMonitor::simulated() {
  if (state_ == kBusActive) return false;
  state_ = kBusActive;
  image_.set_bus_state(kBusActive);
  return true;
}

bool BusMonitor::poll(clock::time_point now) {
  const char* name = cfg_.adapter.interface.c_str();
  // Never waits on the kernel (this is the bus thread): asks now and takes
  // the answer to an earlier request, so a reading is one tick old.
  LinkInfo li;
  ops_->request_get(cfg_.adapter.interface);
  if (ops_->take_get(li) < 0) {
    // No answer yet, or the supervision tick notices a missing or down
    // interface and ends the session; until then keep the last reading.
    flush_summary(now, false);
    return false;
  }
  bool changed = false;
  bool is_can = li.kind == "can";
  if (cfg_.adapter.type == "slcan" && !warned_slcan_ &&
      (cfg_.master.has_bus_state_location || map_errors_ || cfg_.master.has_bus_off_count_location)) {
    warned_slcan_ = true;
    log_warn("slcan adapter on %s does not report the CAN error state; the bus state input shows only whether the "
             "link is up; flash candleLight firmware and use adapter type socketcan for error state and counters",
             name);
  }

  // Bus-off events since the last reading, from the kernel's statistics, so
  // a bus-off the controller left again between two ticks is still counted.
  uint32_t new_bus_offs = 0;
  if (is_can && li.has_stats) {
    if (have_bus_off_base_ && li.bus_off >= last_bus_off_) new_bus_offs = li.bus_off - last_bus_off_;
    have_bus_off_base_ = true;
    last_bus_off_ = li.bus_off;  // a re-created link restarts from its own count
  }
  if (new_bus_offs) {
    bus_offs_ = static_cast<uint16_t>(bus_offs_ + new_bus_offs);
    image_.set_bus_off_count(bus_offs_);
    changed = true;
  }

  uint8_t code = code_of(li);
  if (code != state_) {
    uint8_t from = state_;
    state_ = code;
    image_.set_bus_state(code);
    changed = true;
    on_change(from, code, now);
  }
  if (new_bus_offs && code != kBusOff) {
    // Went bus-off and came back between two readings.
    log_error("CAN interface %s went bus-off %u time%s and recovered", name, new_bus_offs,
              new_bus_offs == 1 ? "" : "s");
  }
  flush_summary(now, false);

  uint8_t tx = 0, rx = 0;
  if (is_can && li.has_berr) {
    tx = clamp8(li.tx_errors);
    rx = clamp8(li.rx_errors);
  } else if (is_can && map_errors_ && !warned_no_counters_) {
    warned_no_counters_ = true;
    log_warn("CAN interface %s does not report error counters (driver limitation); the error count inputs read 0",
             name);
  }
  if (tx != tx_ || rx != rx_) {
    tx_ = tx;
    rx_ = rx;
    image_.set_bus_errors(tx, rx);
    changed = true;
  }
  return changed;
}

void BusMonitor::on_change(uint8_t from, uint8_t to, clock::time_point now) {
  // Leaving "no bus" for a healthy bus is the session (re)opening, which the
  // bus thread logs already; entering "no bus" too.
  if (to == kBusNone || (from == kBusNone && to == kBusActive)) return;

  if (now - window_start_ >= std::chrono::seconds(1)) {
    flush_summary(now, true);
    window_start_ = now;
    window_changes_ = 0;
  }
  if (++window_changes_ > kLoggedChangesPerSecond) {
    suppressed_ = true;
    return;
  }
  const char* name = cfg_.adapter.interface.c_str();
  switch (to) {
    case kBusActive: log_info("CAN interface %s is error-active again", name); break;
    case kBusWarning:
    case kBusPassive:
      log_warn("CAN interface %s is %s (TX/RX error counters high; check wiring, termination and bit rate)", name,
               bus_code_name(to));
      break;
    case kBusOff:
      if (cfg_.adapter.has_restart_ms)
        log_error("CAN interface %s is bus-off; the kernel restarts it after %u ms", name, cfg_.adapter.restart_ms);
      else
        log_error("CAN interface %s is bus-off; it stays bus-off unless the adapter recovers by itself or is "
                  "restarted (set adapter.restart_ms to let the kernel restart it)",
                  name);
      break;
  }
}

void BusMonitor::flush_summary(clock::time_point now, bool force) {
  if (!suppressed_) return;
  if (!force && now - window_start_ < std::chrono::seconds(1)) return;
  log_warn("CAN interface %s: bus state changed %u times in one second, now %s", cfg_.adapter.interface.c_str(),
           window_changes_, bus_code_name(state_));
  suppressed_ = false;
  window_start_ = now;
  window_changes_ = 0;
}

}  // namespace canopen_plugin
