// raw_io.cpp - see raw_io.h.

#include "raw_io.h"

#include <errno.h>
#include <fcntl.h>
#include <linux/can.h>
#include <linux/can/raw.h>
#include <net/if.h>
#include <poll.h>
#include <sys/eventfd.h>
#include <sys/ioctl.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <unistd.h>

#include <cstring>

// net/if.h hides IFF_ECHO; linux/if.h clashes with it.
#ifndef IFF_ECHO
#define IFF_ECHO (1 << 18)
#endif

namespace canworks_raw {

namespace {

constexpr uint64_t kEchoMaxAgeUs = 1000000;  // an echo later than 1 s fails the frame
constexpr int kTickMs = 1;
constexpr int kRetryMs = 1000;

canworks_can_frame from_can(const can_frame& c, uint64_t time_us) {
  canworks_can_frame f{};
  bool ext = (c.can_id & CAN_EFF_FLAG) != 0;
  f.id = c.can_id & (ext ? CAN_EFF_MASK : CAN_SFF_MASK);
  f.flags = static_cast<uint8_t>((ext ? CANWORKS_CAN_EXTENDED : 0) | ((c.can_id & CAN_RTR_FLAG) ? CANWORKS_CAN_RTR : 0));
  f.dlc = c.can_dlc > 8 ? 8 : c.can_dlc;
  if (!(c.can_id & CAN_RTR_FLAG)) std::memcpy(f.data, c.data, f.dlc);
  f.time_us = time_us;
  return f;
}

can_frame to_can(const canworks_can_frame& f) {
  can_frame c{};
  c.can_id = f.id;
  if (f.flags & CANWORKS_CAN_EXTENDED) c.can_id |= CAN_EFF_FLAG;
  if (f.flags & CANWORKS_CAN_RTR) c.can_id |= CAN_RTR_FLAG;
  c.can_dlc = f.dlc > 8 ? 8 : f.dlc;
  if (!(f.flags & CANWORKS_CAN_RTR)) std::memcpy(c.data, f.data, c.can_dlc);
  return c;
}

// Approximate bits on the wire, with worst-case-ish stuffing (one stuff bit
// per 5 of the stuffed part).
uint64_t frame_bits(const canworks_can_frame& f) {
  unsigned data = (f.flags & CANWORKS_CAN_RTR) ? 0 : 8u * f.dlc;
  unsigned stuffed = ((f.flags & CANWORKS_CAN_EXTENDED) ? 54u : 34u) + data;
  return stuffed + stuffed / 5 + 13;  // CRC delimiter, ACK, EOF, interframe space
}

uint64_t utc_us(const timeval& tv) {
  return static_cast<uint64_t>(tv.tv_sec) * 1000000u + static_cast<uint64_t>(tv.tv_usec);
}

}  // namespace

RawIo::RawIo(std::string interface, uint32_t bitrate, bool listen_only, RawEngine* engine, PlcPort* port,
             RawIoHooks hooks)
    : interface_(std::move(interface)),
      bitrate_(bitrate),
      listen_only_(listen_only),
      engine_(engine),
      port_(port),
      hooks_(std::move(hooks)) {
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

int RawIo::open_socket() {
  int fd = socket(PF_CAN, SOCK_RAW | SOCK_NONBLOCK | SOCK_CLOEXEC, CAN_RAW);
  if (fd < 0) return -errno;
  ifreq ifr{};
  std::strncpy(ifr.ifr_name, interface_.c_str(), IFNAMSIZ - 1);
  if (ioctl(fd, SIOCGIFINDEX, &ifr) < 0) {
    int e = errno;
    close(fd);
    return -e;
  }
  int index = ifr.ifr_ifindex;
  // Echo of sent frames: confirmation on the bus when the driver echoes
  // (IFF_ECHO); otherwise the kernel loops them back at once.
  bool echo = ioctl(fd, SIOCGIFFLAGS, &ifr) == 0 && (ifr.ifr_flags & IFF_ECHO);
  confirm_ = echo ? Confirm::Echo : Confirm::Write;
  int on = 1;
  setsockopt(fd, SOL_CAN_RAW, CAN_RAW_RECV_OWN_MSGS, &on, sizeof on);
  setsockopt(fd, SOL_SOCKET, SO_TIMESTAMP, &on, sizeof on);
  sockaddr_can addr{};
  addr.can_family = AF_CAN;
  addr.can_ifindex = index;
  if (bind(fd, reinterpret_cast<sockaddr*>(&addr), sizeof addr) < 0) {
    int e = errno;
    close(fd);
    return -e;
  }
  filters_version_ = ~0u;
  set_filters(fd);
  return fd;
}

// Config receive entries only: kernel filters. With program frames in use
// (receivers, sends waiting for echoes, cyclic jobs) everything is taken and
// matched here, so every echo and receiver sees its frames.
void RawIo::set_filters(int fd) {
  bool all = port_ && port_->active();
  uint32_t version = port_ ? port_->receivers_version() : 0;
  if (all == filters_all_ && version == filters_version_) return;
  filters_all_ = all;
  filters_version_ = version;
  std::vector<can_filter> f;
  if (!all && engine_) {
    for (const RawRx& m : engine_->config().rx) {
      can_filter cf{};
      cf.can_id = m.id | (m.extended ? CAN_EFF_FLAG : 0) | (m.rtr ? CAN_RTR_FLAG : 0);
      cf.can_mask = m.mask | CAN_EFF_FLAG | CAN_RTR_FLAG;
      f.push_back(cf);
    }
    // Own sends come back for the sent counts.
    for (const RawTx& m : engine_->config().tx) {
      can_filter cf{};
      cf.can_id = m.id | (m.extended ? CAN_EFF_FLAG : 0);
      cf.can_mask = (m.extended ? CAN_EFF_MASK : CAN_SFF_MASK) | CAN_EFF_FLAG;
      f.push_back(cf);
    }
  }
  if (all || f.size() > 512) {
    can_filter any{0, 0};
    setsockopt(fd, SOL_CAN_RAW, CAN_RAW_FILTER, &any, sizeof any);
  } else {
    // An empty list receives nothing.
    setsockopt(fd, SOL_CAN_RAW, CAN_RAW_FILTER, f.empty() ? nullptr : f.data(),
               static_cast<socklen_t>(f.size() * sizeof(can_filter)));
  }
}

void RawIo::receive(int fd, uint64_t now) {
  for (int n = 0; n < 256; ++n) {
    can_frame c{};
    char ctrl[CMSG_SPACE(sizeof(timeval))];
    iovec iov{&c, sizeof c};
    msghdr msg{};
    msg.msg_iov = &iov;
    msg.msg_iovlen = 1;
    msg.msg_control = ctrl;
    msg.msg_controllen = sizeof ctrl;
    ssize_t r = recvmsg(fd, &msg, MSG_DONTWAIT);
    if (r < static_cast<ssize_t>(sizeof c)) return;
    if (c.can_id & CAN_ERR_FLAG) continue;
    uint64_t t = 0;
    for (cmsghdr* h = CMSG_FIRSTHDR(&msg); h; h = CMSG_NXTHDR(&msg, h))
      if (h->cmsg_level == SOL_SOCKET && h->cmsg_type == SO_TIMESTAMP) {
        timeval tv;
        std::memcpy(&tv, CMSG_DATA(h), sizeof tv);
        t = utc_us(tv);
      }
    canworks_can_frame f = from_can(c, t);
    bool ours = (msg.msg_flags & MSG_CONFIRM) != 0;         // sent from this socket
    bool this_host = (msg.msg_flags & MSG_DONTROUTE) != 0;  // sent by another socket here (the protocol)
    load_bits_ += frame_bits(f);
    if (ours) {
      if (port_ && port_->own_echo(f)) continue;  // a program frame is on the bus
    } else if (!this_host && port_) {
      port_->on_frame(f);
      port_->count_rx();
    }
    if (engine_ && !ours) {
      std::lock_guard<std::mutex> lock(engine_mutex_);
      if (engine_->on_frame(f, now) && hooks_.publish_inputs) hooks_.publish_inputs(engine_->input_values());
    }
  }
}

bool RawIo::write_frame(int fd, const canworks_can_frame& f, int& error) {
  can_frame c = to_can(f);
  ssize_t w = write(fd, &c, sizeof c);
  if (w == static_cast<ssize_t>(sizeof c)) {
    if (port_) port_->count_tx();
    return true;
  }
  error = w < 0 ? errno : EIO;
  return false;
}

void RawIo::send_due(int fd, uint64_t now) {
  bool running = hooks_.plc_running ? hooks_.plc_running() : true;
  if (engine_) {
    std::lock_guard<std::mutex> lock(engine_mutex_);
    engine_->set_plc_running(running && !listen_only_, now);
    if (hooks_.latest_outputs && hooks_.latest_outputs(outputs_)) engine_->set_outputs(outputs_.data(), now);
    std::vector<canworks_can_frame> frames;
    std::vector<size_t> idx;
    engine_->due(now, frames, idx);
    for (size_t k = 0; k < frames.size(); ++k) {
      int err = 0;
      engine_->sent(idx[k], now, write_frame(fd, frames[k], err) ? 0 : err);
    }
    if (engine_->check_timeouts(now) && hooks_.publish_inputs) hooks_.publish_inputs(engine_->input_values());
  }
  if (!port_) return;
  canworks_can_frame f;
  uint32_t tag;
  while (port_->next_tx(f, tag)) {
    int err = 0;
    if (write_frame(fd, f, err))
      port_->tx_written(tag, false);  // the echo confirms it (also without IFF_ECHO: the kernel loops it back)
    else
      port_->tx_failed(tag, err == ENETDOWN || err == ENODEV ? CANWORKS_CAN_ERR_BUS : CANWORKS_CAN_ERR_FULL);
  }
  canworks_can_frame due[CANWORKS_CAN_CYCLIC_JOBS];
  uint8_t jobs[CANWORKS_CAN_CYCLIC_JOBS];
  int n = port_->cyclic_due(now, due, jobs, CANWORKS_CAN_CYCLIC_JOBS);
  for (int k = 0; k < n; ++k) {
    int err = 0;
    if (write_frame(fd, due[k], err)) port_->cyclic_sent(jobs[k]);
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
  if (hooks_.bus_info) hooks_.bus_info(info);
  info.bus_load = bus_load_;
  port_->publish_bus(info);
}

void RawIo::run() {
  int fd = -1;
  bool reported = false;
  while (!stop_) {
    if (fd < 0) {
      fd = open_socket();
      if (fd < 0) {
        if (!reported && hooks_.log)
          hooks_.log("raw messages on " + interface_ + " wait for the interface: " + std::strerror(-fd));
        reported = true;
        if (port_) port_->set_running(false);
        pollfd w{wake_fd_, POLLIN, 0};
        poll(&w, 1, kRetryMs);
        continue;
      }
      if (reported && hooks_.log) hooks_.log("raw messages on " + interface_ + " running");
      reported = false;
      if (port_) port_->set_running(true);
    }
    uint64_t now = monotonic_us();
    int timeout = kTickMs;
    bool busy = (port_ && port_->active()) || (engine_ && !engine_->config().tx.empty());
    if (!busy && engine_) {
      std::lock_guard<std::mutex> lock(engine_mutex_);
      uint64_t in = engine_->next_event_in(now);
      timeout = in == UINT64_MAX ? 100 : static_cast<int>(in / 1000 + 1);
      if (timeout > 100) timeout = 100;
    } else if (!busy) {
      timeout = 100;
    }
    pollfd p[2] = {{fd, POLLIN, 0}, {wake_fd_, POLLIN, 0}};
    int r = poll(p, 2, timeout);
    if (stop_) break;
    now = monotonic_us();
    if (r > 0 && (p[0].revents & (POLLERR | POLLHUP | POLLNVAL))) {
      // The interface went away (USB unplug): reopen.
      close(fd);
      fd = -1;
      continue;
    }
    set_filters(fd);
    if (r > 0 && (p[0].revents & POLLIN)) receive(fd, now);
    send_due(fd, now);
    update_bus(now);
  }
  if (fd >= 0) close(fd);
  if (port_) {
    port_->set_running(false);
    port_->cancel_all();
  }
}

}  // namespace canworks_raw
