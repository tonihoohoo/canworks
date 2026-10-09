#include "frame_tx.h"

#include <algorithm>
#include <cerrno>
#include <cstdio>
#include <cstring>
#include <fcntl.h>
#include <linux/can.h>
#include <linux/can/raw.h>
#include <net/if.h>
#include <sys/eventfd.h>
#include <sys/socket.h>
#include <unistd.h>

#if CANWORKS_WITH_CANOPEN
#include <lely/can/msg.h>
#endif

namespace canopen_plugin {

std::string raw_frame_text(const RawFrame& f) {
  char buf[64];
  std::string s;
  std::snprintf(buf, sizeof buf, f.ext ? "0x%08X" : "0x%03X", f.id);
  s = buf;
  if (f.rtr) {
    std::snprintf(buf, sizeof buf, " RTR [%u]", f.dlc);
    return s + buf;
  }
  std::snprintf(buf, sizeof buf, " [%u]", f.dlc);
  s += buf;
  for (unsigned i = 0; i < f.dlc && i < 8; ++i) {
    std::snprintf(buf, sizeof buf, " %02X", f.data[i]);
    s += buf;
  }
  return s;
}

namespace {

std::string node_use(const NodeConfig& n, uint32_t id) {
  const std::string who = " of " + n.label();
  for (const auto& p : n.tx_pdos)
    if (n.tpdo_cob_id(p) == id) return "TPDO" + std::to_string(p.number) + who;
  for (const auto& p : n.rx_pdos)
    if (n.rpdo_cob_id(p) == id) return "RPDO" + std::to_string(p.number) + who;
  const uint32_t nid = n.node_id;
  if (id == 0x80 + nid) return "EMCY" + who;
  for (unsigned k = 0; k < 4; ++k) {
    if (id == 0x180 + 0x100 * k + nid) return "TPDO" + std::to_string(k + 1) + who + " (predefined)";
    if (id == 0x200 + 0x100 * k + nid) return "RPDO" + std::to_string(k + 1) + who + " (predefined)";
  }
  if (id == 0x580 + nid) return "the SDO response channel" + who;
  if (id == 0x600 + nid) return "the SDO request channel" + who;
  if (id == 0x700 + nid) return "the heartbeat" + who;
  return "";
}

}  // namespace

std::string cob_id_use(const Config& cfg, uint32_t id, bool ext) {
  if (ext) return "";
  if (id == 0x000) return "NMT";
  if (id == 0x080) return "SYNC";
  if (id == 0x7E4 || id == 0x7E5) return "LSS";
  if (cfg.is_slave()) {
    if (id == (cfg.master.has_time_cob_id ? cfg.master.time_producer_cob_id() : 0x100u)) return "TIME";
    if (!cfg.slave.lss || cfg.slave.node_id) {
      const uint32_t nid = cfg.slave.node_id;
      const std::string who = " of the plugin's own slave (node " + std::to_string(nid) + ")";
      if (id == 0x80 + nid) return "EMCY" + who;
      for (unsigned k = 0; k < 4; ++k) {
        if (id == 0x180 + 0x100 * k + nid) return "TPDO" + std::to_string(k + 1) + who;
        if (id == 0x200 + 0x100 * k + nid) return "RPDO" + std::to_string(k + 1) + who;
      }
      if (id == 0x580 + nid || id == 0x600 + nid) return "the SDO channel" + who;
      if (id == 0x700 + nid) return "the heartbeat" + who;
    }
    return "";
  }
  if (id == cfg.master.time_producer_cob_id()) return "TIME";
  const uint32_t mid = cfg.master.node_id;
  if (id == 0x700 + mid) return "the master's heartbeat";
  if (id == 0x80 + mid) return "the master's EMCY";
  for (const auto& n : cfg.nodes) {
    std::string use = node_use(n, id);
    if (!use.empty()) return use;
  }
  return "";
}

// ---------------------------------------------------------------------------
// CAN_RAW socket

namespace {

class CanFrameSink : public FrameSink {
 public:
  explicit CanFrameSink(std::string ifname) : ifname_(std::move(ifname)) {}
  ~CanFrameSink() override { close(); }

  int open() override {
    if (fd_ >= 0) return 0;
    int fd = socket(PF_CAN, SOCK_RAW | SOCK_NONBLOCK | SOCK_CLOEXEC, CAN_RAW);
    if (fd < 0) return -errno;
    // Send only: no receive filter, so nothing queues up on this socket.
    if (setsockopt(fd, SOL_CAN_RAW, CAN_RAW_FILTER, nullptr, 0) < 0) {
      int e = -errno;
      ::close(fd);
      return e;
    }
    unsigned index = if_nametoindex(ifname_.c_str());
    if (!index) {
      ::close(fd);
      return -ENODEV;
    }
    sockaddr_can addr{};
    addr.can_family = AF_CAN;
    addr.can_ifindex = static_cast<int>(index);
    if (bind(fd, reinterpret_cast<sockaddr*>(&addr), sizeof addr) < 0) {
      int e = -errno;
      ::close(fd);
      return e;
    }
    fd_ = fd;
    return 0;
  }

  int send(const RawFrame& f) override {
    if (fd_ < 0) return -EBADF;
    can_frame cf{};
    cf.can_id = f.id | (f.ext ? CAN_EFF_FLAG : 0) | (f.rtr ? CAN_RTR_FLAG : 0);
    cf.can_dlc = f.dlc;
    if (!f.rtr) std::memcpy(cf.data, f.data, f.dlc);
    ssize_t n = write(fd_, &cf, sizeof cf);
    if (n == static_cast<ssize_t>(sizeof cf)) return 0;
    int e = n < 0 ? -errno : -EIO;
    // A socket on an interface that went away stays broken: reopen next time.
    if (e == -ENODEV || e == -ENETDOWN || e == -ENXIO) close();
    return e;
  }

  void close() override {
    if (fd_ >= 0) ::close(fd_);
    fd_ = -1;
  }

  bool is_open() const override { return fd_ >= 0; }

 private:
  std::string ifname_;
  int fd_ = -1;
};

class SimFrameSink : public FrameSink {
 public:
  explicit SimFrameSink(std::shared_ptr<SimFrameInjector> inj) : inj_(std::move(inj)) {}
  int open() override { return inj_->read_fd() >= 0 ? 0 : -EIO; }
  int send(const RawFrame& f) override { return inj_->push(f); }
  void close() override {}
  bool is_open() const override { return true; }

 private:
  std::shared_ptr<SimFrameInjector> inj_;
};

}  // namespace

std::unique_ptr<FrameSink> make_can_frame_sink(const std::string& interface) {
  return std::unique_ptr<FrameSink>(new CanFrameSink(interface));
}

std::unique_ptr<FrameSink> make_sim_frame_sink(std::shared_ptr<SimFrameInjector> injector) {
  return std::unique_ptr<FrameSink>(new SimFrameSink(std::move(injector)));
}

// ---------------------------------------------------------------------------
// Simulated bus

SimFrameInjector::SimFrameInjector() { fd_ = eventfd(0, EFD_NONBLOCK | EFD_CLOEXEC); }

SimFrameInjector::~SimFrameInjector() {
  if (fd_ >= 0) ::close(fd_);
}

int SimFrameInjector::push(const RawFrame& f) {
  if (fd_ < 0) return -EIO;
  {
    std::lock_guard<std::mutex> lock(mutex_);
    if (queue_.size() >= kMaxQueued) return -ENOBUFS;
    queue_.push_back(f);
  }
  uint64_t one = 1;
  if (write(fd_, &one, sizeof one) < 0 && errno != EAGAIN) return -EIO;
  return 0;
}

void SimFrameInjector::drain(std::vector<RawFrame>& out) {
  std::lock_guard<std::mutex> lock(mutex_);
  out.insert(out.end(), queue_.begin(), queue_.end());
  queue_.clear();
}

#if CANWORKS_WITH_CANOPEN
void raw_frame_to_msg(const RawFrame& f, can_msg& msg) {
  msg = CAN_MSG_INIT;
  msg.id = f.id;
  msg.flags = (f.ext ? CAN_FLAG_IDE : 0) | (f.rtr ? CAN_FLAG_RTR : 0);
  msg.len = f.dlc;
  if (!f.rtr) std::memcpy(msg.data, f.data, f.dlc);
}
#endif

// ---------------------------------------------------------------------------

bool RateLimit::take(std::chrono::steady_clock::time_point now) {
  if (started_) {
    double dt = std::chrono::duration<double>(now - last_).count();
    tokens_ = std::min(burst_, tokens_ + dt * rate_);
  }
  started_ = true;
  last_ = now;
  if (tokens_ < 1.0) return false;
  tokens_ -= 1.0;
  return true;
}

}  // namespace canopen_plugin
