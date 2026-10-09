// raw_link.cpp - see raw_link.h.

#include "raw_link.h"

#include <errno.h>
#include <fcntl.h>
#include <linux/can.h>
#include <linux/can/raw.h>
#include <net/if.h>
#include <sys/eventfd.h>
#include <sys/ioctl.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <unistd.h>

#include <cstring>
#include <map>

// net/if.h hides IFF_ECHO; linux/if.h clashes with it.
#ifndef IFF_ECHO
#define IFF_ECHO (1 << 18)
#endif

namespace canworks_raw {

using canopen_plugin::TraceRecord;

namespace {

uint64_t utc_now_us() {
  timeval tv{};
  gettimeofday(&tv, nullptr);
  return static_cast<uint64_t>(tv.tv_sec) * 1000000u + static_cast<uint64_t>(tv.tv_usec);
}

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

uint64_t utc_us(const timeval& tv) {
  return static_cast<uint64_t>(tv.tv_sec) * 1000000u + static_cast<uint64_t>(tv.tv_usec);
}

// --- The CAN_RAW socket ---

class SocketLink : public RawLink {
 public:
  explicit SocketLink(std::string interface) : interface_(std::move(interface)) {}
  ~SocketLink() override { close(); }

  int open() override {
    int fd = socket(PF_CAN, SOCK_RAW | SOCK_NONBLOCK | SOCK_CLOEXEC, CAN_RAW);
    if (fd < 0) return -errno;
    ifreq ifr{};
    std::strncpy(ifr.ifr_name, interface_.c_str(), IFNAMSIZ - 1);
    if (ioctl(fd, SIOCGIFINDEX, &ifr) < 0) {
      int e = errno;
      ::close(fd);
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
      ::close(fd);
      return -e;
    }
    // Nothing until the first set_filters().
    setsockopt(fd, SOL_CAN_RAW, CAN_RAW_FILTER, nullptr, 0);
    fd_ = fd;
    return 0;
  }

  void close() override {
    if (fd_ >= 0) ::close(fd_);
    fd_ = -1;
  }

  int fd() const override { return fd_; }
  Confirm confirm() const override { return confirm_; }

  void set_filters(const std::vector<LinkFilter>& filters, bool all) override {
    if (fd_ < 0) return;
    if (all || filters.size() > 512) {
      can_filter any{0, 0};
      setsockopt(fd_, SOL_CAN_RAW, CAN_RAW_FILTER, &any, sizeof any);
      return;
    }
    std::vector<can_filter> f;
    for (const LinkFilter& l : filters) f.push_back(can_filter{l.can_id, l.can_mask});
    // An empty list receives nothing.
    setsockopt(fd_, SOL_CAN_RAW, CAN_RAW_FILTER, f.empty() ? nullptr : f.data(),
               static_cast<socklen_t>(f.size() * sizeof(can_filter)));
  }

  void read(std::vector<LinkFrame>& out, size_t max) override {
    for (size_t n = 0; n < max; ++n) {
      can_frame c{};
      char ctrl[CMSG_SPACE(sizeof(timeval))];
      iovec iov{&c, sizeof c};
      msghdr msg{};
      msg.msg_iov = &iov;
      msg.msg_iovlen = 1;
      msg.msg_control = ctrl;
      msg.msg_controllen = sizeof ctrl;
      ssize_t r = recvmsg(fd_, &msg, MSG_DONTWAIT);
      if (r < static_cast<ssize_t>(sizeof c)) return;
      if (c.can_id & CAN_ERR_FLAG) continue;
      uint64_t t = 0;
      for (cmsghdr* h = CMSG_FIRSTHDR(&msg); h; h = CMSG_NXTHDR(&msg, h))
        if (h->cmsg_level == SOL_SOCKET && h->cmsg_type == SO_TIMESTAMP) {
          timeval tv;
          std::memcpy(&tv, CMSG_DATA(h), sizeof tv);
          t = utc_us(tv);
        }
      LinkFrame lf;
      lf.frame = from_can(c, t);
      lf.ours = (msg.msg_flags & MSG_CONFIRM) != 0;         // sent from this socket
      lf.this_host = (msg.msg_flags & MSG_DONTROUTE) != 0;  // sent by another socket here (the protocol)
      out.push_back(lf);
    }
  }

  int write(const canworks_can_frame& f, Origin) override {
    can_frame c = to_can(f);
    ssize_t w = ::write(fd_, &c, sizeof c);
    if (w == static_cast<ssize_t>(sizeof c)) return 0;
    return w < 0 ? errno : EIO;
  }

  std::string where() const override { return interface_; }

 private:
  std::string interface_;
  int fd_ = -1;
  Confirm confirm_ = Confirm::Unknown;
};

// --- The bridge ---

class BridgeLink : public RawLink {
 public:
  explicit BridgeLink(std::shared_ptr<SimBridge> b) : bridge_(std::move(b)) {}
  int open() override { return bridge_->rx_fd() < 0 ? -EIO : 0; }
  void close() override {}
  int fd() const override { return bridge_->rx_fd(); }
  Confirm confirm() const override { return Confirm::Echo; }
  void set_filters(const std::vector<LinkFilter>&, bool) override {}  // matched by the raw path
  void read(std::vector<LinkFrame>& out, size_t max) override { bridge_->drain(out, max); }
  int write(const canworks_can_frame& f, Origin origin) override { return bridge_->write(f, origin); }
  std::string where() const override { return "the simulated network"; }

 private:
  std::shared_ptr<SimBridge> bridge_;
};

}  // namespace

TraceRecord trace_record(const canworks_can_frame& f, bool tx) {
  TraceRecord r;
  r.time_us = f.time_us ? f.time_us : utc_now_us();
  r.id = f.id;
  if (f.flags & CANWORKS_CAN_EXTENDED) r.id |= canopen_plugin::kCanEff;
  if (f.flags & CANWORKS_CAN_RTR) r.id |= canopen_plugin::kCanRtr;
  r.dlc = f.dlc > 8 ? 8 : f.dlc;
  if (tx) r.flags |= canopen_plugin::kTraceTx;
  std::memcpy(r.data, f.data, r.dlc);
  return r;
}

std::unique_ptr<RawLink> make_socket_link(const std::string& interface) {
  return std::unique_ptr<RawLink>(new SocketLink(interface));
}

std::unique_ptr<RawLink> make_bridge_link(std::shared_ptr<SimBridge> bridge) {
  return std::unique_ptr<RawLink>(new BridgeLink(std::move(bridge)));
}

namespace {
std::mutex g_bridges_mutex;
std::map<unsigned, std::shared_ptr<SimBridge>> g_bridges;
}  // namespace

void set_sim_bridge(unsigned network, std::shared_ptr<SimBridge> bridge) {
  std::lock_guard<std::mutex> lock(g_bridges_mutex);
  if (bridge)
    g_bridges[network] = std::move(bridge);
  else
    g_bridges.erase(network);
}

std::shared_ptr<SimBridge> sim_bridge(unsigned network) {
  std::lock_guard<std::mutex> lock(g_bridges_mutex);
  auto it = g_bridges.find(network);
  return it == g_bridges.end() ? nullptr : it->second;
}

SimBridge::SimBridge(bool loopback) : loopback_(loopback) {
  rx_fd_ = eventfd(0, EFD_NONBLOCK | EFD_CLOEXEC);
  tx_fd_ = eventfd(0, EFD_NONBLOCK | EFD_CLOEXEC);
  if (loopback_ && pipe2(trace_pipe_, O_NONBLOCK | O_CLOEXEC) != 0) trace_pipe_[0] = trace_pipe_[1] = -1;
  attached_ = loopback_;
}

SimBridge::~SimBridge() {
  for (int fd : {rx_fd_, tx_fd_, trace_pipe_[0], trace_pipe_[1]})
    if (fd >= 0) ::close(fd);
}

void SimBridge::wake(int fd) {
  uint64_t one = 1;
  if (fd >= 0 && ::write(fd, &one, sizeof one) < 0) {
  }
}

int SimBridge::write(const canworks_can_frame& f, Origin origin) {
  if (!attached_.load(std::memory_order_acquire)) return ENETDOWN;
  bool own = origin == Origin::Own;
  if (loopback_) {
    canworks_can_frame t = f;
    t.time_us = utc_now_us();
    trace(t, origin != Origin::Device);
    seen(t, own);
    return 0;
  }
  {
    std::lock_guard<std::mutex> lock(mutex_);
    if (tx_.size() >= kMax) return ENOBUFS;
    tx_.emplace_back(f, own);
  }
  wake(tx_fd_);
  return 0;
}

void SimBridge::drain(std::vector<LinkFrame>& out, size_t max) {
  uint64_t v;
  if (::read(rx_fd_, &v, sizeof v) < 0) {
  }
  std::lock_guard<std::mutex> lock(mutex_);
  size_t n = 0;
  while (!rx_.empty() && n++ < max) {
    out.push_back(rx_.front());
    rx_.pop_front();
  }
  if (!rx_.empty()) wake(rx_fd_);  // more next time
}

void SimBridge::attach(bool on) {
  if (loopback_) return;
  attached_.store(on, std::memory_order_release);
  if (!on) {
    std::lock_guard<std::mutex> lock(mutex_);
    tx_.clear();
  }
}

void SimBridge::take(std::vector<std::pair<canworks_can_frame, bool>>& out) {
  uint64_t v;
  if (::read(tx_fd_, &v, sizeof v) < 0) {
  }
  std::lock_guard<std::mutex> lock(mutex_);
  out.insert(out.end(), tx_.begin(), tx_.end());
  tx_.clear();
}

void SimBridge::seen(const canworks_can_frame& f, bool ours) {
  LinkFrame lf;
  lf.frame = f;
  if (!lf.frame.time_us) lf.frame.time_us = utc_now_us();
  lf.ours = ours;
  {
    std::lock_guard<std::mutex> lock(mutex_);
    if (rx_.size() >= kMax) rx_.pop_front();  // the raw thread fell behind: oldest first
    rx_.push_back(lf);
  }
  wake(rx_fd_);
}

void SimBridge::trace(const canworks_can_frame& f, bool tx) {
  if (!trace_on_.load(std::memory_order_acquire) || trace_pipe_[1] < 0) return;
  TraceRecord r = trace_record(f, tx);
  // A record is far below PIPE_BUF, so it is written whole or not at all.
  if (::write(trace_pipe_[1], &r, sizeof r) != static_cast<ssize_t>(sizeof r)) trace_drops_.fetch_add(1);
}

class BridgeTraceSource : public canopen_plugin::TraceSource {
 public:
  explicit BridgeTraceSource(std::shared_ptr<SimBridge> b) : b_(std::move(b)) {}
  int open(const std::string&, const std::vector<canopen_plugin::TraceFilter>&, bool) override {
    if (b_->trace_pipe_[0] < 0) return -EIO;
    flush();
    b_->trace_on_.store(true, std::memory_order_release);
    open_ = true;
    return 0;
  }
  int set_filters(const std::vector<canopen_plugin::TraceFilter>&, bool) override { return 0; }  // the ring filters
  int fd() const override { return open_ ? b_->trace_pipe_[0] : -1; }
  bool drain(std::vector<TraceRecord>& out, uint64_t& kernel_drops) override {
    TraceRecord r;
    while (::read(b_->trace_pipe_[0], &r, sizeof r) == static_cast<ssize_t>(sizeof r)) out.push_back(r);
    kernel_drops = b_->trace_drops_.load();
    return true;
  }
  void close() override {
    b_->trace_on_.store(false, std::memory_order_release);
    open_ = false;
    flush();
  }

 private:
  void flush() {
    TraceRecord r;
    while (::read(b_->trace_pipe_[0], &r, sizeof r) > 0) {
    }
  }
  std::shared_ptr<SimBridge> b_;
  bool open_ = false;
};

std::unique_ptr<canopen_plugin::TraceSource> SimBridge::trace_source() {
  if (!loopback_) return nullptr;
  return std::unique_ptr<canopen_plugin::TraceSource>(new BridgeTraceSource(shared_from_this()));
}

}  // namespace canworks_raw
