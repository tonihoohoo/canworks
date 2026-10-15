#include "j1939_socket.h"

#include <cerrno>
#include <cstring>
#include <fcntl.h>
#include <linux/can.h>
#include <linux/can/j1939.h>
#include <linux/errqueue.h>
#include <linux/net_tstamp.h>
#include <net/if.h>
#include <sys/socket.h>
#include <unistd.h>

namespace canopen_plugin {

std::string j1939_socket_problem(int err, const std::string& ifname) {
  if (err < 0) err = -err;
  switch (err) {
    case EPROTONOSUPPORT:
    case EAFNOSUPPORT:
      return "J1939 needs the can-j1939 kernel module (modprobe can-j1939)";
    case ENODEV:
      return "CAN interface " + ifname + " not found";
    case ENETDOWN:
      return "CAN interface " + ifname + " is down";
    case EADDRINUSE:
      return "the J1939 address is in use by another program on " + ifname;
    default:
      return "J1939 socket on " + ifname + ": " + strerror(err);
  }
}

namespace {

class KernelSocket : public J1939Socket {
 public:
  ~KernelSocket() override { close(); }

  int open(const std::string& ifname, const std::vector<uint32_t>& pgns) override {
    close();
    ifindex_ = if_nametoindex(ifname.c_str());
    if (!ifindex_) return -ENODEV;
    rx_ = socket(PF_CAN, SOCK_DGRAM | SOCK_NONBLOCK | SOCK_CLOEXEC, CAN_J1939);
    if (rx_ < 0) return -errno;
    int one = 1;
    if (setsockopt(rx_, SOL_CAN_J1939, SO_J1939_PROMISC, &one, sizeof(one)) < 0 ||
        setsockopt(rx_, SOL_SOCKET, SO_BROADCAST, &one, sizeof(one)) < 0)
      return fail();
    if (apply_filter(pgns, false) < 0) return fail();
    sockaddr_can a = addr(J1939_NO_NAME, J1939_NO_ADDR, J1939_NO_PGN);
    if (::bind(rx_, reinterpret_cast<sockaddr*>(&a), sizeof(a)) < 0) return fail();
    return 0;
  }

  int bind(uint64_t name, uint8_t address) override {
    if (ecu_ >= 0) ::close(ecu_);
    ecu_ = -1;
    close_long();
    int r = open_ecu(name, address, ecu_);
    if (r) return r;
    // The program's long sends: a second socket at the same NAME and
    // address, reporting its transport protocol sessions on its error queue.
    // Without it they go through the ECU socket.
    int lr = open_ecu(name, address, long_);
    if (lr) long_problem_ = std::string("long send socket: ") + strerror(-lr);
    if (lr == 0) {
      int one = 1;
      unsigned flags = SOF_TIMESTAMPING_OPT_ID | SOF_TIMESTAMPING_TX_ACK | SOF_TIMESTAMPING_TX_SCHED |
                       SOF_TIMESTAMPING_SOFTWARE | SOF_TIMESTAMPING_OPT_CMSG | SOF_TIMESTAMPING_OPT_TSONLY;
      if (setsockopt(long_, SOL_CAN_J1939, SO_J1939_ERRQUEUE, &one, sizeof(one)) < 0)
        long_problem_ = std::string("SO_J1939_ERRQUEUE: ") + strerror(errno);
      else if (setsockopt(long_, SOL_SOCKET, SO_TIMESTAMPING, &flags, sizeof(flags)) < 0)
        long_problem_ = std::string("SO_TIMESTAMPING: ") + strerror(errno);
      else
        events_ = true;
      long_prio_ = -1;
      next_id_ = 0;  // OPT_ID counts this socket's sessions from 0
    }
    return 0;
  }

  void close() override {
    if (rx_ >= 0) ::close(rx_);
    if (ecu_ >= 0) ::close(ecu_);
    rx_ = ecu_ = -1;
    close_long();
  }

  int set_filter(const std::vector<uint32_t>& pgns, bool any) override {
    if (rx_ < 0) return -EBADF;
    return apply_filter(pgns, any) < 0 ? -errno : 0;
  }

  int send_long(uint32_t pgn, uint8_t destination, uint8_t priority, const uint8_t* data, size_t len,
                uint32_t& id) override {
    id = 0;
    if (long_ < 0) return send(pgn, destination, priority, data, len);
    if (priority != long_prio_) {
      int p = priority;
      if (setsockopt(long_, SOL_CAN_J1939, SO_J1939_SEND_PRIO, &p, sizeof(p)) < 0) return -errno;
      long_prio_ = priority;
    }
    sockaddr_can a = addr(J1939_NO_NAME, destination, pgn);
    ssize_t n = sendto(long_, data, len, MSG_DONTWAIT, reinterpret_cast<sockaddr*>(&a), sizeof(a));
    int r = n < 0 ? -errno : 0;
    // The kernel numbers each session it creates on the socket, also one it
    // then cannot start next to another socket's session to the same
    // address (EBUSY); other refusals come before the session exists.
    if (r == 0) id = next_id_;
    if (r == 0 || r == -EBUSY) ++next_id_;
    return r;
  }

  bool long_send_events() const override { return long_ >= 0 && events_; }
  std::string long_send_problem() const override { return long_problem_; }

  int send_event(uint32_t& id, bool& aborted, int& error) override {
    if (long_ < 0 || !events_) return 0;
    // The kernel puts a "scheduled" note when a session starts, then an
    // acknowledgement when it completed or an abort, each with the
    // session's number in ee_data.
    for (int k = 0; k < 16; ++k) {
      char data[8];
      iovec iov = {data, sizeof(data)};
      alignas(cmsghdr) char control[512];
      msghdr msg;
      std::memset(&msg, 0, sizeof(msg));
      msg.msg_iov = &iov;
      msg.msg_iovlen = 1;
      msg.msg_control = control;
      msg.msg_controllen = sizeof(control);
      if (recvmsg(long_, &msg, MSG_ERRQUEUE | MSG_DONTWAIT) < 0) return 0;
      for (cmsghdr* c = CMSG_FIRSTHDR(&msg); c; c = CMSG_NXTHDR(&msg, c)) {
        if (c->cmsg_level != SOL_CAN_J1939 || c->cmsg_type != SCM_J1939_ERRQUEUE) continue;
        sock_extended_err serr;
        std::memcpy(&serr, CMSG_DATA(c), sizeof(serr));
        if (serr.ee_origin == SO_EE_ORIGIN_TIMESTAMPING && serr.ee_info == SCM_TSTAMP_ACK) {
          id = serr.ee_data;
          aborted = false;
          error = 0;
          return 1;
        }
        if (serr.ee_origin == SO_EE_ORIGIN_LOCAL && serr.ee_info == J1939_EE_INFO_TX_ABORT) {
          id = serr.ee_data;
          aborted = true;
          error = static_cast<int>(serr.ee_errno);
          return 1;
        }
      }
    }
    return 0;
  }

  int fd() const override { return rx_; }

  int receive(J1939Message& out) override {
    if (rx_ < 0) return -EBADF;
    buf_.resize(kJ1939MaxLength);
    sockaddr_can src;
    std::memset(&src, 0, sizeof(src));
    iovec iov = {buf_.data(), buf_.size()};
    alignas(cmsghdr) char control[128];
    msghdr msg;
    std::memset(&msg, 0, sizeof(msg));
    msg.msg_name = &src;
    msg.msg_namelen = sizeof(src);
    msg.msg_iov = &iov;
    msg.msg_iovlen = 1;
    msg.msg_control = control;
    msg.msg_controllen = sizeof(control);
    ssize_t n = recvmsg(rx_, &msg, 0);
    if (n < 0) return errno == EWOULDBLOCK ? -EAGAIN : -errno;
    out.pgn = src.can_addr.j1939.pgn;
    out.source = src.can_addr.j1939.addr;
    out.source_name = src.can_addr.j1939.name;
    out.destination = kJ1939Global;
    out.priority = 6;
    for (cmsghdr* c = CMSG_FIRSTHDR(&msg); c; c = CMSG_NXTHDR(&msg, c)) {
      if (c->cmsg_level != SOL_CAN_J1939) continue;
      if (c->cmsg_type == SCM_J1939_DEST_ADDR) out.destination = *CMSG_DATA(c);
      if (c->cmsg_type == SCM_J1939_PRIO) out.priority = *CMSG_DATA(c);
    }
    out.data.assign(buf_.begin(), buf_.begin() + n);
    return 0;
  }

  int send(uint32_t pgn, uint8_t destination, uint8_t priority, const uint8_t* data, size_t len) override {
    if (ecu_ < 0) return -EBADF;
    if (priority != prio_) {
      int p = priority;
      if (setsockopt(ecu_, SOL_CAN_J1939, SO_J1939_SEND_PRIO, &p, sizeof(p)) < 0) return -errno;
      prio_ = priority;
    }
    sockaddr_can a = addr(J1939_NO_NAME, destination, pgn);
    ssize_t n = sendto(ecu_, data, len, MSG_DONTWAIT, reinterpret_cast<sockaddr*>(&a), sizeof(a));
    return n < 0 ? -errno : 0;
  }

 private:
  int open_ecu(uint64_t name, uint8_t address, int& fd) {
    fd = socket(PF_CAN, SOCK_DGRAM | SOCK_NONBLOCK | SOCK_CLOEXEC, CAN_J1939);
    if (fd < 0) return -errno;
    int one = 1;
    int r = 0;
    if (setsockopt(fd, SOL_SOCKET, SO_BROADCAST, &one, sizeof(one)) < 0) r = -errno;
    sockaddr_can a = addr(name, address, J1939_NO_PGN);
    if (!r && ::bind(fd, reinterpret_cast<sockaddr*>(&a), sizeof(a)) < 0) r = -errno;
    if (r) {
      ::close(fd);
      fd = -1;
    }
    return r;
  }

  void close_long() {
    if (long_ >= 0) ::close(long_);
    long_ = -1;
    events_ = false;
    long_problem_.clear();
  }

  // The receive socket's filter: `pgns`, or none (every PGN) with `any`.
  // -1 with errno set on failure.
  int apply_filter(const std::vector<uint32_t>& pgns, bool any) {
    if (any) return setsockopt(rx_, SOL_CAN_J1939, SO_J1939_FILTER, nullptr, 0);
    std::vector<j1939_filter> filters;
    for (uint32_t pgn : pgns) {
      j1939_filter f;
      std::memset(&f, 0, sizeof(f));
      f.pgn = pgn;
      f.pgn_mask = J1939_PGN_MAX;
      filters.push_back(f);
    }
    if (filters.empty()) return 0;
    return setsockopt(rx_, SOL_CAN_J1939, SO_J1939_FILTER, filters.data(),
                      static_cast<socklen_t>(filters.size() * sizeof(j1939_filter)));
  }

  sockaddr_can addr(uint64_t name, uint8_t address, uint32_t pgn) const {
    sockaddr_can a;
    std::memset(&a, 0, sizeof(a));
    a.can_family = AF_CAN;
    a.can_ifindex = static_cast<int>(ifindex_);
    a.can_addr.j1939.name = name;
    a.can_addr.j1939.addr = address;
    a.can_addr.j1939.pgn = pgn;
    return a;
  }

  int fail() {
    int e = errno;
    close();
    return -e;
  }

  unsigned ifindex_ = 0;
  int rx_ = -1;
  int ecu_ = -1;
  int prio_ = -1;
  int long_ = -1;
  int long_prio_ = -1;
  bool events_ = false;
  std::string long_problem_;  // why events_ is false after a bind
  uint32_t next_id_ = 0;  // the number the kernel gives the long socket's next session
  std::vector<uint8_t> buf_;
};

}  // namespace

std::unique_ptr<J1939Socket> make_kernel_j1939_socket() { return std::unique_ptr<J1939Socket>(new KernelSocket); }

}  // namespace canopen_plugin
