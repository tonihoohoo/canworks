// raw_io.cpp - see raw_io.h.

#include "raw_io.h"

#include <errno.h>
#include <poll.h>
#include <sys/eventfd.h>
#include <unistd.h>

#include <cstring>

#include "../frame_tx.h"
#include "../outputs_gate.h"

namespace canworks_raw {

namespace {

constexpr uint64_t kEchoMaxAgeUs = 1000000;  // an echo later than 1 s fails the frame
constexpr int kTickMs = 1;
constexpr int kIdleMs = 100;
constexpr int kRetryMs = 1000;
constexpr size_t kReadBatch = 256;

// Approximate bits on the wire, with worst-case-ish stuffing (one stuff bit
// per 5 of the stuffed part).
uint64_t frame_bits(const canworks_can_frame& f) {
  unsigned data = (f.flags & CANWORKS_CAN_RTR) ? 0 : 8u * f.dlc;
  unsigned stuffed = ((f.flags & CANWORKS_CAN_EXTENDED) ? 54u : 34u) + data;
  return stuffed + stuffed / 5 + 13;  // CRC delimiter, ACK, EOF, interframe space
}

canworks_can_frame from_raw_frame(const canopen_plugin::RawFrame& r) {
  canworks_can_frame f{};
  f.id = r.id;
  f.flags = static_cast<uint8_t>((r.ext ? CANWORKS_CAN_EXTENDED : 0) | (r.rtr ? CANWORKS_CAN_RTR : 0));
  f.dlc = r.dlc > 8 ? 8 : r.dlc;
  std::memcpy(f.data, r.data, 8);
  return f;
}

}  // namespace

RawIo::RawIo(std::unique_ptr<RawLink> link, uint32_t bitrate, bool listen_only, RawEngine* engine, PlcPort* port,
             RawIoHooks hooks, RawSimDevices* devices, std::shared_ptr<canopen_plugin::SimFrameInjector> injector)
    : link_(std::move(link)),
      bitrate_(bitrate),
      listen_only_(listen_only),
      engine_(engine),
      port_(port),
      hooks_(std::move(hooks)),
      devices_(devices && devices->size() ? devices : nullptr),
      injector_(std::move(injector)) {
  if (engine_) outputs_.assign(engine_->output_locations().size(), 0);
}

RawIo::~RawIo() { stop(); }

void RawIo::start() {
  if (thread_.joinable()) return;
  stop_ = false;
  wake_fd_ = eventfd(0, EFD_NONBLOCK | EFD_CLOEXEC);
  thread_ = std::thread([this] { run(); });
}

void RawIo::stop() {
  if (!thread_.joinable()) return;
  stop_ = true;
  uint64_t one = 1;
  if (wake_fd_ >= 0 && write(wake_fd_, &one, sizeof one) < 0) {
  }
  thread_.join();
  if (wake_fd_ >= 0) close(wake_fd_);
  wake_fd_ = -1;
}

void RawIo::with_engine(const std::function<void(const RawEngine&)>& f) {
  std::lock_guard<std::mutex> lock(engine_mutex_);
  if (engine_) f(*engine_);
}

// Config receive entries only: kernel filters. With program frames in use
// (receivers, sends waiting for echoes, cyclic jobs) or simulated devices
// listening, everything is taken and matched here.
void RawIo::set_filters() {
  bool all = (port_ && port_->active()) || devices_;
  uint32_t version = port_ ? port_->receivers_version() : 0;
  if (all == filters_all_ && version == filters_version_) return;
  filters_all_ = all;
  filters_version_ = version;
  std::vector<LinkFilter> f;
  if (!all && engine_) {
    constexpr uint32_t kEff = 0x80000000u, kRtr = 0x40000000u;
    constexpr uint32_t kSffMask = 0x7FFu, kEffMask = 0x1FFFFFFFu;
    for (const RawRx& m : engine_->config().rx)
      f.push_back({m.id | (m.extended ? kEff : 0) | (m.rtr ? kRtr : 0), m.mask | kEff | kRtr});
    // Own sends come back for the sent counts.
    for (const RawTx& m : engine_->config().tx)
      f.push_back({m.id | (m.extended ? kEff : 0), (m.extended ? kEffMask : kSffMask) | kEff});
  }
  link_->set_filters(f, all);
}

void RawIo::handle(const LinkFrame& lf, uint64_t now) {
  if (lf.error) {
    ++error_frames_;
    if (lf.error_class & kErrBusOff) ++bus_offs_;
    if (lf.tx_errors >= 0) {
      frame_tx_errors_ = lf.tx_errors;
      frame_rx_errors_ = lf.rx_errors;
    }
    return;
  }
  const canworks_can_frame& f = lf.frame;
  load_bits_ += frame_bits(f);
  if (devices_) devices_->on_frame(f, now / 1000);
  if (lf.ours) {
    if (port_ && port_->own_echo(f)) return;  // a program frame is on the bus
  } else if (!lf.this_host || hooks_.host_frames_received) {
    received_.fetch_add(1, std::memory_order_relaxed);
    if (port_) {
      port_->on_frame(f);
      port_->count_rx();
    }
  }
  if (engine_ && !lf.ours) {
    std::lock_guard<std::mutex> lock(engine_mutex_);
    if (engine_->on_frame(f, now) && hooks_.publish_inputs) hooks_.publish_inputs(engine_->input_values());
  }
}

void RawIo::receive(uint64_t now) {
  rx_buf_.clear();
  link_->read(rx_buf_, kReadBatch);
  for (const LinkFrame& lf : rx_buf_) handle(lf, now);
}

bool RawIo::write_frame(const canworks_can_frame& f, int& error, Origin origin) {
  error = link_->write(f, origin);
  if (error) return false;
  if (origin == Origin::Own) {
    sent_.fetch_add(1, std::memory_order_relaxed);
    if (port_) port_->count_tx();
  }
  return true;
}

void RawIo::send_due(uint64_t now) {
  // The host's outputs gate (the bridge's outputs off) stops transmit messages like a PLC stop.
  bool running = (hooks_.plc_running ? hooks_.plc_running() : true) && canopen_plugin::outputs_enabled();
  if (devices_) {
    dev_buf_.clear();
    devices_->due(now / 1000, dev_buf_);
    for (const canworks_can_frame& f : dev_buf_) {
      int err = 0;
      write_frame(f, err, Origin::Device);
    }
  }
  if (injector_) {
    std::vector<canopen_plugin::RawFrame> hand;
    injector_->drain(hand);
    for (const auto& r : hand) {
      int err = 0;
      write_frame(from_raw_frame(r), err, Origin::Hand);
    }
  }
  if (engine_) {
    std::lock_guard<std::mutex> lock(engine_mutex_);
    engine_->set_plc_running(running && !listen_only_, now);
    if (hooks_.latest_outputs && hooks_.latest_outputs(outputs_)) engine_->set_outputs(outputs_.data(), now);
    std::vector<canworks_can_frame> frames;
    std::vector<size_t> idx;
    engine_->due(now, frames, idx);
    for (size_t k = 0; k < frames.size(); ++k) {
      int err = 0;
      engine_->sent(idx[k], now, write_frame(frames[k], err) ? 0 : err);
    }
    if (engine_->check_timeouts(now) && hooks_.publish_inputs) hooks_.publish_inputs(engine_->input_values());
  }
  if (!port_) return;
  // False: the kernel had no room; hold the frame and try again next pass.
  auto send_program = [this](const canworks_can_frame& f, uint32_t tag) {
    int err = 0;
    if (write_frame(f, err)) {
      port_->tx_written(tag, false);  // the echo confirms it (also without IFF_ECHO: the kernel loops it back)
      return true;
    }
    if (err == ENOBUFS || err == EAGAIN) return false;
    port_->tx_failed(tag, err == ENETDOWN || err == ENODEV ? CANWORKS_CAN_ERR_BUS : CANWORKS_CAN_ERR_FULL);
    return true;
  };
  if (held_ && (!port_->tx_pending(held_tag_) || send_program(held_frame_, held_tag_))) held_ = false;
  canworks_can_frame f;
  uint32_t tag;
  while (!held_ && port_->next_tx(f, tag)) {
    if (send_program(f, tag)) continue;
    held_ = true;
    held_frame_ = f;
    held_tag_ = tag;
  }
  canworks_can_frame due[CANWORKS_CAN_CYCLIC_JOBS];
  uint8_t jobs[CANWORKS_CAN_CYCLIC_JOBS];
  int n = port_->cyclic_due(now, due, jobs, CANWORKS_CAN_CYCLIC_JOBS);
  for (int k = 0; k < n; ++k) {
    int err = 0;
    if (write_frame(due[k], err)) port_->cyclic_sent(jobs[k]);
  }
  port_->expire_echoes(now, kEchoMaxAgeUs);
}

void RawIo::update_bus(uint64_t now) {
  if (now - load_window_start_ >= 1000000) {
    uint64_t span = now - load_window_start_;
    if (bitrate_ && load_window_start_) {
      uint64_t pct = load_bits_ * 100u * 1000000u / (static_cast<uint64_t>(bitrate_) * span);
      bus_load_ = static_cast<uint8_t>(pct > 100 ? 100 : pct);
    }
    load_window_start_ = now;
    load_bits_ = 0;
  }
  if (now < next_bus_update_ || !port_) return;
  next_bus_update_ = now + 100000;
  canworks_can_bus_info info{};
  bool counters = hooks_.bus_info && hooks_.bus_info(info);
  // Without driver counters, the last error frame's counters while the bus
  // is not error-active (once it is, they are stale).
  if (!counters && info.state != 0 && frame_tx_errors_ >= 0) {
    info.tx_errors = static_cast<uint16_t>(frame_tx_errors_);
    info.rx_errors = static_cast<uint16_t>(frame_rx_errors_);
  }
  if (!info.error_frames) info.error_frames = error_frames_;
  if (!info.bus_off_count) info.bus_off_count = bus_offs_;
  info.bus_load = bus_load_;
  port_->publish_bus(info);
  if (hooks_.log_bus) log_bus_state(info, now);
}

namespace {
constexpr unsigned kBusLogsPerSecond = 5;
const char* const kStateNames[] = {"error-active", "error-warning", "error-passive", "bus-off", "down"};
}  // namespace

void RawIo::log_bus_state(const canworks_can_bus_info& info, uint64_t now) {
  const std::string where = "CAN interface " + link_->where();
  bool window_over = now - log_window_start_ >= 1000000;
  if (log_suppressed_ && window_over) {
    hooks_.log_bus(1, where + ": bus state changed " + std::to_string(log_window_changes_) +
                          " times in one second, now " + kStateNames[logged_state_ > 4 ? 4 : logged_state_]);
    log_suppressed_ = false;
  }
  if (window_over) {
    log_window_start_ = now;
    log_window_changes_ = 0;
  }
  uint8_t to = info.state > 4 ? 4 : info.state;
  uint8_t from = logged_state_;
  uint32_t new_offs = have_bus_offs_ && info.bus_off_count >= logged_bus_offs_ ? info.bus_off_count - logged_bus_offs_ : 0;
  have_bus_offs_ = true;
  logged_bus_offs_ = info.bus_off_count;
  bool change = to != from;
  logged_state_ = to;
  // Down and back up is the link's own business (logged when it reopens).
  bool quiet = !change || to == 4 || (from == 4 && to == 0);
  bool hidden_off = new_offs && to != 3;
  if (quiet && !hidden_off) return;
  if (++log_window_changes_ > kBusLogsPerSecond) {
    log_suppressed_ = true;
    return;
  }
  // One line per reading, so the limit above holds per line.
  int level = 0;
  std::string line;
  if (!quiet) {
    if (to == 0) {
      line = where + " is error-active again";
    } else if (to == 3) {
      level = 2;
      line = where + " is bus-off; " +
             (hooks_.restart_ms ? "the kernel restarts it after " + std::to_string(hooks_.restart_ms) + " ms"
                                : std::string("without adapter.restart_ms it stays bus-off unless the adapter "
                                              "recovers by itself"));
    } else {
      level = 1;
      line = where + " is " + kStateNames[to] + " (TX/RX error counters high; check wiring, termination and bit rate)";
    }
  }
  if (hidden_off) {
    std::string offs = "went bus-off " + std::to_string(new_offs) + (new_offs == 1 ? " time" : " times") +
                       " and recovered";
    line = line.empty() ? where + " " + offs : line + "; since the last reading it " + offs;
    level = 2;
  }
  hooks_.log_bus(level, line);
}

int RawIo::next_timeout(uint64_t now) {
  if ((port_ && port_->active()) || (engine_ && !engine_->config().tx.empty())) return kTickMs;
  uint64_t in_us = UINT64_MAX;
  if (engine_) {
    std::lock_guard<std::mutex> lock(engine_mutex_);
    in_us = engine_->next_event_in(now);
  }
  if (devices_) {
    uint64_t d = devices_->next_in(now / 1000);
    if (d != UINT64_MAX && d * 1000 < in_us) in_us = d * 1000;
  }
  if (in_us == UINT64_MAX) return kIdleMs;
  uint64_t ms = in_us / 1000 + 1;
  return ms > static_cast<uint64_t>(kIdleMs) ? kIdleMs : static_cast<int>(ms);
}

void RawIo::run() {
  bool open = false;
  bool reported = false;
  while (!stop_) {
    if (!open) {
      int r = hooks_.prepare && !hooks_.prepare() ? -ENETDOWN : link_->open();
      if (r < 0) {
        if (!reported && hooks_.log)
          hooks_.log("raw CAN on " + link_->where() + " waits for the interface: " + std::strerror(-r));
        reported = true;
        if (port_) port_->set_running(false);
        pollfd w{wake_fd_, POLLIN, 0};
        poll(&w, 1, kRetryMs);
        continue;
      }
      if (reported && hooks_.log) hooks_.log("raw CAN on " + link_->where() + " running");
      reported = false;
      open = true;
      confirm_ = link_->confirm();
      filters_version_ = ~0u;
      set_filters();
      if (port_) port_->set_running(true);
      if (devices_) devices_->start(monotonic_us() / 1000);
    }
    uint64_t now = monotonic_us();
    pollfd p[2] = {{link_->fd(), POLLIN, 0}, {wake_fd_, POLLIN, 0}};
    int r = poll(p, 2, next_timeout(now));
    if (stop_) break;
    now = monotonic_us();
    if (r > 0 && (p[0].revents & (POLLERR | POLLHUP | POLLNVAL))) {
      // The interface went away (USB unplug): reopen.
      link_->close();
      open = false;
      continue;
    }
    set_filters();
    if (r > 0 && (p[0].revents & POLLIN)) receive(now);
    send_due(now);
    update_bus(now);
  }
  link_->close();
  if (port_) {
    port_->set_running(false);
    port_->cancel_all();
  }
}

}  // namespace canworks_raw
