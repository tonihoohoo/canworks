#include "trace_capture.h"

#include <cerrno>
#include <cstring>
#include <linux/can.h>
#include <linux/can/error.h>
#include <linux/can/raw.h>
#include <net/if.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <unistd.h>

namespace canopen_plugin {

bool TraceFilter::match(uint32_t can_id) const { return ((can_id ^ id) & mask & CAN_EFF_MASK) == 0; }

bool trace_wanted(const TraceRecord& r, const std::vector<TraceFilter>& filters, bool error_frames) {
  if (r.flags & kTraceGap) return true;
  if (r.id & kCanErr) return error_frames;
  if (filters.empty()) return true;
  for (const auto& f : filters)
    if (f.match(r.id)) return true;
  return false;
}

TraceRing::TraceRing(size_t capacity) : buf_(capacity ? capacity : 1) {}

void TraceRing::push(const TraceRecord& r) {
  buf_[(next_seq_ - 1) % buf_.size()] = r;
  ++next_seq_;
  if (count_ < buf_.size()) ++count_;
}

void TraceRing::clear() { count_ = 0; }

uint64_t TraceRing::oldest_seq() const { return next_seq_ - count_; }

TraceRing::Fetch TraceRing::fetch(uint64_t after, size_t max, const std::vector<TraceFilter>& filters,
                                  bool error_frames) const {
  Fetch f;
  uint64_t first = after + 1;
  uint64_t oldest = oldest_seq();
  if (first < oldest) {
    f.lost = oldest - first;
    first = oldest;
  }
  uint64_t seq = first;
  for (; seq < next_seq_ && f.records.size() < max; ++seq) {
    const TraceRecord& r = buf_[(seq - 1) % buf_.size()];
    if (trace_wanted(r, filters, error_frames)) f.records.push_back(r);
  }
  f.next = seq - 1;
  if (f.next < after) f.next = after;
  return f;
}

std::string trace_base64(const std::vector<TraceRecord>& records) {
  static const char* t = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
  const auto* p = reinterpret_cast<const uint8_t*>(records.data());
  size_t n = records.size() * sizeof(TraceRecord);
  std::string out;
  out.reserve((n + 2) / 3 * 4);
  size_t i = 0;
  for (; i + 3 <= n; i += 3) {
    uint32_t v = (uint32_t(p[i]) << 16) | (uint32_t(p[i + 1]) << 8) | p[i + 2];
    out += t[v >> 18];
    out += t[(v >> 12) & 63];
    out += t[(v >> 6) & 63];
    out += t[v & 63];
  }
  if (i < n) {
    uint32_t v = uint32_t(p[i]) << 16;
    if (i + 1 < n) v |= uint32_t(p[i + 1]) << 8;
    out += t[v >> 18];
    out += t[(v >> 12) & 63];
    out += i + 1 < n ? t[(v >> 6) & 63] : '=';
    out += '=';
  }
  return out;
}

namespace {

class CanTraceSource : public TraceSource {
 public:
  ~CanTraceSource() override { close(); }

  int open(const std::string& interface, const std::vector<TraceFilter>& filters, bool error_frames) override {
    close();
    unsigned idx = if_nametoindex(interface.c_str());
    if (!idx) return -ENODEV;
    int fd = socket(PF_CAN, SOCK_RAW | SOCK_CLOEXEC | SOCK_NONBLOCK, CAN_RAW);
    if (fd < 0) return -errno;
    int one = 1;
    int rcvbuf = 1 << 20;
    setsockopt(fd, SOL_SOCKET, SO_RCVBUF, &rcvbuf, sizeof rcvbuf);
    setsockopt(fd, SOL_SOCKET, SO_TIMESTAMP, &one, sizeof one);
    setsockopt(fd, SOL_SOCKET, SO_RXQ_OVFL, &one, sizeof one);
    fd_ = fd;
    int e = set_filters(filters, error_frames);
    sockaddr_can a{};
    a.can_family = AF_CAN;
    a.can_ifindex = static_cast<int>(idx);
    if (!e && bind(fd, reinterpret_cast<sockaddr*>(&a), sizeof a) != 0) e = -errno;
    if (e) {
      close();
      return e;
    }
    drops_base_ = -1;
    return 0;
  }

  int set_filters(const std::vector<TraceFilter>& filters, bool error_frames) override {
    if (fd_ < 0) return -EBADF;
    std::vector<can_filter> f;
    for (const auto& x : filters) f.push_back({x.id & CAN_EFF_MASK, x.mask & CAN_EFF_MASK});
    if (f.empty()) f.push_back({0, 0});  // everything
    if (setsockopt(fd_, SOL_CAN_RAW, CAN_RAW_FILTER, f.data(), static_cast<socklen_t>(f.size() * sizeof f[0])) != 0)
      return -errno;
    can_err_mask_t err = error_frames ? CAN_ERR_MASK : 0;
    if (setsockopt(fd_, SOL_CAN_RAW, CAN_RAW_ERR_FILTER, &err, sizeof err) != 0) return -errno;
    return 0;
  }

  int fd() const override { return fd_; }

  bool drain(std::vector<TraceRecord>& out, uint64_t& kernel_drops) override {
    constexpr unsigned kBatch = 256;
    struct Slot {
      can_frame frame;
      iovec iov;
      alignas(cmsghdr) char ctrl[CMSG_SPACE(sizeof(timeval)) + CMSG_SPACE(sizeof(uint32_t))];
    };
    static thread_local Slot slots[kBatch];
    static thread_local mmsghdr msgs[kBatch];
    for (int rounds = 0; rounds < 64; ++rounds) {
      for (unsigned i = 0; i < kBatch; ++i) {
        slots[i].iov = {&slots[i].frame, sizeof slots[i].frame};
        msgs[i] = {};
        msgs[i].msg_hdr.msg_iov = &slots[i].iov;
        msgs[i].msg_hdr.msg_iovlen = 1;
        msgs[i].msg_hdr.msg_control = slots[i].ctrl;
        msgs[i].msg_hdr.msg_controllen = sizeof slots[i].ctrl;
      }
      int n = recvmmsg(fd_, msgs, kBatch, MSG_DONTWAIT, nullptr);
      if (n < 0) {
        if (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR) return true;
        return false;  // ENETDOWN, ENODEV: interface gone
      }
      for (int i = 0; i < n; ++i) {
        const can_frame& cf = slots[i].frame;
        TraceRecord r;
        r.id = cf.can_id;
        r.dlc = cf.can_dlc > 8 ? 8 : cf.can_dlc;
        std::memcpy(r.data, cf.data, 8);
        if (!(cf.can_id & CAN_RTR_FLAG)) std::memset(r.data + r.dlc, 0, 8 - r.dlc);
        if (msgs[i].msg_hdr.msg_flags & MSG_DONTROUTE) r.flags |= kTraceTx;
        timeval tv{};
        for (cmsghdr* c = CMSG_FIRSTHDR(&msgs[i].msg_hdr); c; c = CMSG_NXTHDR(&msgs[i].msg_hdr, c)) {
          if (c->cmsg_level != SOL_SOCKET) continue;
          if (c->cmsg_type == SO_TIMESTAMP) {
            std::memcpy(&tv, CMSG_DATA(c), sizeof tv);
          } else if (c->cmsg_type == SO_RXQ_OVFL) {
            uint32_t d;
            std::memcpy(&d, CMSG_DATA(c), sizeof d);
            // The counter covers the socket's life; count from the first value seen.
            if (drops_base_ < 0) drops_base_ = d;
            kernel_drops = d - static_cast<uint32_t>(drops_base_);
          }
        }
        if (!tv.tv_sec) gettimeofday(&tv, nullptr);
        r.time_us = uint64_t(tv.tv_sec) * 1000000u + uint64_t(tv.tv_usec);
        out.push_back(r);
      }
      if (n < static_cast<int>(kBatch)) return true;
    }
    return true;
  }

  void close() override {
    if (fd_ >= 0) ::close(fd_);
    fd_ = -1;
  }

 private:
  int fd_ = -1;
  int64_t drops_base_ = -1;
};

}  // namespace

std::unique_ptr<TraceSource> make_can_trace_source() { return std::unique_ptr<TraceSource>(new CanTraceSource); }

}  // namespace canopen_plugin
