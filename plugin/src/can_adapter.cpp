#include "can_adapter.h"

#include <cerrno>
#include <cstring>
#include <linux/can/netlink.h>
#include <linux/if_link.h>
#include <linux/netlink.h>
#include <linux/rtnetlink.h>
#include <fcntl.h>
#include <linux/tty.h>
#include <net/if.h>
#include <sys/ioctl.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <termios.h>
#include <unistd.h>

#include "log.h"

namespace canopen_plugin {

namespace {

// ---------------------------------------------------------------------------
// rtnetlink

// A request: header, ifinfomsg, then attributes appended in place.
struct NlRequest {
  explicit NlRequest(uint16_t type, uint16_t flags) {
    std::memset(buf, 0, sizeof(buf));
    nh()->nlmsg_len = NLMSG_LENGTH(sizeof(ifinfomsg));
    nh()->nlmsg_type = type;
    nh()->nlmsg_flags = NLM_F_REQUEST | flags;
    ifi()->ifi_family = AF_UNSPEC;
  }
  nlmsghdr* nh() { return reinterpret_cast<nlmsghdr*>(buf); }
  ifinfomsg* ifi() { return static_cast<ifinfomsg*>(NLMSG_DATA(nh())); }

  rtattr* add(uint16_t type, const void* data, size_t len) {
    size_t at = NLMSG_ALIGN(nh()->nlmsg_len);
    rtattr* rta = reinterpret_cast<rtattr*>(buf + at);
    rta->rta_type = type;
    rta->rta_len = RTA_LENGTH(len);
    if (len) std::memcpy(RTA_DATA(rta), data, len);
    nh()->nlmsg_len = at + RTA_ALIGN(rta->rta_len);
    return rta;
  }
  rtattr* begin_nest(uint16_t type) { return add(type, nullptr, 0); }
  void end_nest(rtattr* nest) {
    nest->rta_len = static_cast<unsigned short>(buf + nh()->nlmsg_len - reinterpret_cast<char*>(nest));
  }

  alignas(nlmsghdr) char buf[512];
};

class Socket {
 public:
  Socket() {
    fd_ = socket(AF_NETLINK, SOCK_RAW | SOCK_CLOEXEC, NETLINK_ROUTE);
    if (fd_ >= 0) {
      timeval tv{2, 0};
      setsockopt(fd_, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
    }
  }
  ~Socket() {
    if (fd_ >= 0) close(fd_);
  }
  int fd() const { return fd_; }

 private:
  int fd_;
};

void parse_linkinfo(const rtattr* linkinfo, LinkInfo& out) {
  int len = RTA_PAYLOAD(linkinfo);
  for (const rtattr* a = static_cast<const rtattr*>(RTA_DATA(linkinfo)); RTA_OK(a, len); a = RTA_NEXT(a, len)) {
    if (a->rta_type == IFLA_INFO_KIND) {
      out.kind.assign(static_cast<const char*>(RTA_DATA(a)), strnlen(static_cast<const char*>(RTA_DATA(a)),
                                                                     RTA_PAYLOAD(a)));
    } else if (a->rta_type == IFLA_INFO_DATA) {
      int dlen = RTA_PAYLOAD(a);
      for (const rtattr* d = static_cast<const rtattr*>(RTA_DATA(a)); RTA_OK(d, dlen); d = RTA_NEXT(d, dlen)) {
        if (d->rta_type == IFLA_CAN_BITTIMING && RTA_PAYLOAD(d) >= sizeof(can_bittiming)) {
          can_bittiming bt;
          std::memcpy(&bt, RTA_DATA(d), sizeof(bt));
          out.bitrate = bt.bitrate;
        } else if (d->rta_type == IFLA_CAN_STATE && RTA_PAYLOAD(d) >= sizeof(uint32_t)) {
          uint32_t st;
          std::memcpy(&st, RTA_DATA(d), sizeof(st));
          out.has_can_state = true;
          out.can_state = st;
        } else if (d->rta_type == IFLA_CAN_BERR_COUNTER && RTA_PAYLOAD(d) >= sizeof(can_berr_counter)) {
          can_berr_counter bc;
          std::memcpy(&bc, RTA_DATA(d), sizeof(bc));
          out.has_berr = true;
          out.tx_errors = bc.txerr;
          out.rx_errors = bc.rxerr;
        }
      }
    } else if (a->rta_type == IFLA_INFO_XSTATS && out.kind == "can" && RTA_PAYLOAD(a) >= sizeof(can_device_stats)) {
      // The kernel puts IFLA_INFO_KIND first; other kinds have other xstats.
      can_device_stats cs;
      std::memcpy(&cs, RTA_DATA(a), sizeof(cs));
      out.has_stats = true;
      out.bus_off = cs.bus_off;
    }
  }
}

void parse_ifinfo(const nlmsghdr* nh, LinkInfo& out) {
  const ifinfomsg* ifi = static_cast<const ifinfomsg*>(NLMSG_DATA(nh));
  out.up = (ifi->ifi_flags & IFF_UP) != 0;
  int alen = IFLA_PAYLOAD(nh);
  for (const rtattr* a = IFLA_RTA(ifi); RTA_OK(a, alen); a = RTA_NEXT(a, alen))
    if (a->rta_type == IFLA_LINKINFO) parse_linkinfo(a, out);
}

// Sends `req` and reads the reply. With `info`, expects an RTM_NEWLINK and
// parses it; otherwise expects an ACK. Returns 0 or -errno.
int transact(NlRequest& req, LinkInfo* info) {
  Socket s;
  if (s.fd() < 0) return -errno;
  sockaddr_nl addr{};
  addr.nl_family = AF_NETLINK;
  static unsigned seq = 0;
  req.nh()->nlmsg_seq = ++seq;
  if (sendto(s.fd(), req.buf, req.nh()->nlmsg_len, 0, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) < 0)
    return -errno;
  alignas(nlmsghdr) char reply[16384];
  for (;;) {
    ssize_t n = recv(s.fd(), reply, sizeof(reply), 0);
    if (n < 0) {
      if (errno == EINTR) continue;
      return -errno;
    }
    int len = static_cast<int>(n);
    for (nlmsghdr* nh = reinterpret_cast<nlmsghdr*>(reply); NLMSG_OK(nh, len); nh = NLMSG_NEXT(nh, len)) {
      if (nh->nlmsg_seq != req.nh()->nlmsg_seq) continue;
      if (nh->nlmsg_type == NLMSG_ERROR) {
        const nlmsgerr* err = static_cast<const nlmsgerr*>(NLMSG_DATA(nh));
        return err->error;  // 0 = ACK
      }
      if (info && nh->nlmsg_type == RTM_NEWLINK) {
        parse_ifinfo(nh, *info);
        return 0;
      }
      if (nh->nlmsg_type == NLMSG_DONE) return -ENODEV;
    }
  }
}

class NetlinkOps : public LinkOps {
 public:
  int get(const std::string& name, LinkInfo& out) override {
    out = LinkInfo();
    if (name.size() >= IFNAMSIZ) return -ENODEV;
    NlRequest req(RTM_GETLINK, 0);
    req.add(IFLA_IFNAME, name.c_str(), name.size() + 1);
    return transact(req, &out);
  }

  int set_up(const std::string& name, bool up) override {
    unsigned index = if_nametoindex(name.c_str());
    if (!index) return -ENODEV;
    NlRequest req(RTM_NEWLINK, NLM_F_ACK);
    req.ifi()->ifi_index = static_cast<int>(index);
    req.ifi()->ifi_change = IFF_UP;
    req.ifi()->ifi_flags = up ? IFF_UP : 0;
    return transact(req, nullptr);
  }

  int set_bitrate(const std::string& name, unsigned bitrate, long restart_ms) override {
    unsigned index = if_nametoindex(name.c_str());
    if (!index) return -ENODEV;
    // What `ip link set <name> type can bitrate <rate> [restart-ms <ms>]` sends.
    NlRequest req(RTM_NEWLINK, NLM_F_ACK);
    req.ifi()->ifi_index = static_cast<int>(index);
    rtattr* linkinfo = req.begin_nest(IFLA_LINKINFO);
    req.add(IFLA_INFO_KIND, "can", 3);
    rtattr* data = req.begin_nest(IFLA_INFO_DATA);
    can_bittiming bt{};
    bt.bitrate = bitrate;
    req.add(IFLA_CAN_BITTIMING, &bt, sizeof(bt));
    if (restart_ms >= 0) {
      uint32_t ms = static_cast<uint32_t>(restart_ms);
      req.add(IFLA_CAN_RESTART_MS, &ms, sizeof(ms));
    }
    req.end_nest(data);
    req.end_nest(linkinfo);
    return transact(req, nullptr);
  }

  int rename(const std::string& name, const std::string& new_name) override {
    unsigned index = if_nametoindex(name.c_str());
    if (!index) return -ENODEV;
    if (new_name.size() >= IFNAMSIZ) return -EINVAL;
    NlRequest req(RTM_NEWLINK, NLM_F_ACK);
    req.ifi()->ifi_index = static_cast<int>(index);
    req.add(IFLA_IFNAME, new_name.c_str(), new_name.size() + 1);
    return transact(req, nullptr);
  }

  int set_txqlen(const std::string& name, unsigned len) override {
    unsigned index = if_nametoindex(name.c_str());
    if (!index) return -ENODEV;
    NlRequest req(RTM_NEWLINK, NLM_F_ACK);
    req.ifi()->ifi_index = static_cast<int>(index);
    uint32_t v = len;
    req.add(IFLA_TXQLEN, &v, sizeof(v));
    return transact(req, nullptr);
  }

  int set_listen_only(const std::string& name, bool on) override {
    unsigned index = if_nametoindex(name.c_str());
    if (!index) return -ENODEV;
    // What `ip link set <name> type can listen-only on|off` sends.
    NlRequest req(RTM_NEWLINK, NLM_F_ACK);
    req.ifi()->ifi_index = static_cast<int>(index);
    rtattr* linkinfo = req.begin_nest(IFLA_LINKINFO);
    req.add(IFLA_INFO_KIND, "can", 3);
    rtattr* data = req.begin_nest(IFLA_INFO_DATA);
    can_ctrlmode cm{};
    cm.mask = CAN_CTRLMODE_LISTENONLY;
    cm.flags = on ? CAN_CTRLMODE_LISTENONLY : 0;
    req.add(IFLA_CAN_CTRLMODE, &cm, sizeof(cm));
    req.end_nest(data);
    req.end_nest(linkinfo);
    return transact(req, nullptr);
  }
};

// ---------------------------------------------------------------------------
// Serial device (slcan)

speed_t speed_of(unsigned baudrate) {
  static const struct {
    unsigned rate;
    speed_t speed;
  } speeds[] = {{1200, B1200},       {2400, B2400},       {4800, B4800},       {9600, B9600},
                {19200, B19200},     {38400, B38400},     {57600, B57600},     {115200, B115200},
                {230400, B230400},   {460800, B460800},   {500000, B500000},   {576000, B576000},
                {921600, B921600},   {1000000, B1000000}, {1152000, B1152000}, {1500000, B1500000},
                {2000000, B2000000}, {2500000, B2500000}, {3000000, B3000000}, {3500000, B3500000},
                {4000000, B4000000}};
  for (const auto& s : speeds)
    if (s.rate == baudrate) return s.speed;
  return 0;
}

class TtySerialOps : public SerialOps {
 public:
  int open(const std::string& path, unsigned baudrate, int& fd) override {
    // O_NONBLOCK: do not wait for a modem carrier; cleared again below.
    fd = ::open(path.c_str(), O_RDWR | O_NOCTTY | O_CLOEXEC | O_NONBLOCK);
    if (fd < 0) return -errno;
    int rc = setup(fd, baudrate);
    if (rc < 0) {
      ::close(fd);
      fd = -1;
    }
    return rc;
  }

  int attach(int fd, std::string& ifname) override {
    int ldisc = N_SLCAN;
    if (ioctl(fd, TIOCSETD, &ldisc) < 0) return -errno;
    char name[IFNAMSIZ] = {};
    if (ioctl(fd, SIOCGIFNAME, name) < 0) return -errno;
    ifname = name;
    return 0;
  }

  void close(int fd) override {
    // Back to the normal line discipline first, as slcand does on exit: that
    // removes the interface now. Closing alone does not when another end
    // still holds the tty (a pty's master), and fails harmlessly after a
    // hangup.
    int ldisc = N_TTY;
    ioctl(fd, TIOCSETD, &ldisc);
    ::close(fd);
  }

 private:
  static int setup(int fd, unsigned baudrate) {
    // Exclusive: a second slcand or terminal cannot open the device while
    // the plugin owns it.
    if (ioctl(fd, TIOCEXCL) < 0) return -errno;
    termios tio;
    if (tcgetattr(fd, &tio) < 0) return -errno;
    cfmakeraw(&tio);
    tio.c_cflag |= CLOCAL | CREAD;
    tio.c_cflag &= ~CRTSCTS;
    if (baudrate) {
      speed_t sp = speed_of(baudrate);
      if (!sp) return -EINVAL;
      cfsetispeed(&tio, sp);
      cfsetospeed(&tio, sp);
    }
    if (tcsetattr(fd, TCSANOW, &tio) < 0) return -errno;
    int flags = fcntl(fd, F_GETFL);
    if (flags < 0 || fcntl(fd, F_SETFL, flags & ~O_NONBLOCK) < 0) return -errno;
    return 0;
  }
};

// ---------------------------------------------------------------------------
// SocketCAN backend

class SocketCanAdapter : public CanAdapter {
 public:
  SocketCanAdapter(const AdapterConfig& cfg, std::unique_ptr<LinkOps> ops) : cfg_(cfg), ops_(std::move(ops)) {}

  const std::string& interface() const override { return cfg_.interface; }
  std::string problem() const override { return problem_; }
  LinkOps* link_ops() override { return ops_.get(); }

  AdapterState prepare() override {
    const char* name = cfg_.interface.c_str();
    LinkInfo li;
    int rc = ops_->get(cfg_.interface, li);
    if (rc == -ENODEV) {
      problem_ = "CAN interface " + cfg_.interface + " is missing";
      return AdapterState::Missing;
    }
    if (rc < 0) return failed("cannot read", rc);

    if (!cfg_.configure_link) {
      if (li.kind == "can" && li.bitrate && li.bitrate != cfg_.bitrate) {
        if (!warned_rate_)
          log_warn("CAN interface %s runs at %u bit/s but the config says %u bit/s; configure_link is false, so "
                   "the link is left as it is",
                   name, li.bitrate, cfg_.bitrate);
        warned_rate_ = true;
      }
      if (li.up) return AdapterState::Ready;
      problem_ = "CAN interface " + cfg_.interface + " is down (configure_link is false)";
      return AdapterState::Down;
    }

    if (li.kind != "can") {
      // vcan (or another CAN-capable device without bit timing): only up.
      if (li.up) return AdapterState::Ready;
      if ((rc = ops_->set_up(cfg_.interface, true)) < 0) return failed("cannot bring up", rc);
      log_info("brought CAN interface %s up", name);
      return AdapterState::Ready;
    }

    if (li.up && li.bitrate == cfg_.bitrate) return AdapterState::Ready;
    if (li.up) {
      log_warn("CAN interface %s runs at %u bit/s but the config says %u bit/s; taking it down to change the "
               "bit rate",
               name, li.bitrate, cfg_.bitrate);
      if ((rc = ops_->set_up(cfg_.interface, false)) < 0) return failed("cannot take down", rc);
    }
    long restart = cfg_.has_restart_ms ? static_cast<long>(cfg_.restart_ms) : -1;
    if ((rc = ops_->set_bitrate(cfg_.interface, cfg_.bitrate, restart)) < 0) return failed("cannot configure", rc);
    if ((rc = ops_->set_up(cfg_.interface, true)) < 0) return failed("cannot bring up", rc);
    if (cfg_.has_restart_ms)
      log_info("set CAN interface %s to %u bit/s (restart-ms %u) and brought it up", name, cfg_.bitrate,
               cfg_.restart_ms);
    else
      log_info("set CAN interface %s to %u bit/s and brought it up", name, cfg_.bitrate);
    return AdapterState::Ready;
  }

 private:
  AdapterState failed(const char* what, int rc) {
    if (rc == -EPERM || rc == -EACCES) {
      problem_ = std::string(what) + " CAN interface " + cfg_.interface +
                 ": permission denied (setting the bit rate and link state needs CAP_NET_ADMIN; run the runtime "
                 "as root or set configure_link to false)";
      return AdapterState::NotPermitted;
    }
    if (rc == -ENODEV) {
      problem_ = "CAN interface " + cfg_.interface + " is missing";
      return AdapterState::Missing;
    }
    problem_ = std::string(what) + " CAN interface " + cfg_.interface + ": " + std::strerror(-rc);
    return AdapterState::Failed;
  }

  AdapterConfig cfg_;
  std::unique_ptr<LinkOps> ops_;
  std::string problem_;
  bool warned_rate_ = false;
};

// ---------------------------------------------------------------------------
// slcan backend

constexpr unsigned kSlcanTxQueueLen = 1000;  // the driver's default of 10 overflows on SDO/PDO bursts

class SlcanAdapter : public CanAdapter {
 public:
  SlcanAdapter(const AdapterConfig& cfg, std::unique_ptr<LinkOps> ops, std::unique_ptr<SerialOps> serial)
      : cfg_(cfg), ops_(std::move(ops)), serial_(std::move(serial)) {}
  ~SlcanAdapter() override { release(); }

  const std::string& interface() const override { return cfg_.interface; }
  std::string problem() const override { return problem_; }
  LinkOps* link_ops() override { return ops_.get(); }

  AdapterState prepare() override {
    LinkInfo li;
    int rc = ops_->get(cfg_.interface, li);
    if (fd_ >= 0) {
      if (rc == 0) return configure(li);
      if (rc != -ENODEV) return failed("cannot read", rc);
      // Our interface went away: the adapter was unplugged (the tty hung up).
      log_warn("CAN interface %s (slcan on %s) is gone; reopening the serial device", cfg_.interface.c_str(),
               cfg_.device.c_str());
      close_device();
      rc = ops_->get(cfg_.interface, li);
    }
    if (rc == 0) {
      problem_ = "CAN interface " + cfg_.interface +
                 " already exists and was not created by the plugin; stop the program that created it (such as an "
                 "slcand service) or use adapter type socketcan with configure_link false";
      return AdapterState::Failed;
    }
    if (rc != -ENODEV) return failed("cannot read", rc);

    int fd = -1;
    if ((rc = serial_->open(cfg_.device, cfg_.serial_baudrate, fd)) < 0) return open_failed(rc);
    std::string created;
    if ((rc = serial_->attach(fd, created)) < 0) {
      serial_->close(fd);
      if (rc == -EPERM || rc == -EACCES) {
        problem_ = "cannot attach the slcan driver to " + cfg_.device +
                   ": permission denied (needs CAP_NET_ADMIN; run the runtime as root)";
        return AdapterState::NotPermitted;
      }
      problem_ = "cannot attach the slcan driver to " + cfg_.device + ": " + std::strerror(-rc) +
                 " (is the kernel's slcan module available?)";
      return AdapterState::Failed;
    }
    fd_ = fd;
    if (created != cfg_.interface && (rc = ops_->rename(created, cfg_.interface)) < 0) {
      AdapterState st = failed(("cannot rename " + created + " to").c_str(), rc);
      close_device();
      return st;
    }
    log_info("attached the slcan driver to %s as CAN interface %s", cfg_.device.c_str(), cfg_.interface.c_str());
    if ((rc = ops_->get(cfg_.interface, li)) < 0) return failed("cannot read", rc);
    return configure(li);
  }

  void release() override {
    if (fd_ < 0) return;
    ops_->set_up(cfg_.interface, false);  // sends "C" so the adapter leaves the bus cleanly
    close_device();
    log_info("released %s; CAN interface %s removed", cfg_.device.c_str(), cfg_.interface.c_str());
  }

 private:
  AdapterState configure(const LinkInfo& li) {
    if (li.kind != "can") return old_kernel();
    if (li.up && li.bitrate == cfg_.bitrate) return AdapterState::Ready;
    int rc;
    if (li.up && (rc = ops_->set_up(cfg_.interface, false)) < 0) return failed("cannot take down", rc);
    if ((rc = ops_->set_bitrate(cfg_.interface, cfg_.bitrate, -1)) < 0) {
      if (rc == -EOPNOTSUPP) return old_kernel();
      return failed("cannot configure", rc);
    }
    if ((rc = ops_->set_txqlen(cfg_.interface, kSlcanTxQueueLen)) < 0) return failed("cannot configure", rc);
    if ((rc = ops_->set_up(cfg_.interface, true)) < 0) return failed("cannot bring up", rc);
    log_info("set CAN interface %s (slcan on %s) to %u bit/s, txqueuelen %u, and brought it up",
             cfg_.interface.c_str(), cfg_.device.c_str(), cfg_.bitrate, kSlcanTxQueueLen);
    return AdapterState::Ready;
  }

  AdapterState old_kernel() {
    close_device();
    problem_ = "the kernel's slcan driver does not take a bit rate over netlink (needs Linux 6.0 or newer); create " +
               cfg_.interface + " with slcand and use adapter type socketcan with configure_link false";
    return AdapterState::Failed;
  }

  AdapterState open_failed(int rc) {
    const std::string& dev = cfg_.device;
    if (rc == -ENOENT || rc == -ENODEV || rc == -ENXIO) {
      problem_ = "serial device " + dev + " is missing";
      return AdapterState::Missing;
    }
    if (rc == -EPERM || rc == -EACCES) {
      problem_ = "cannot open serial device " + dev + ": permission denied";
      return AdapterState::NotPermitted;
    }
    if (rc == -EBUSY)
      problem_ = "serial device " + dev + " is in use by another program (such as an slcand service)";
    else if (rc == -EINVAL && cfg_.serial_baudrate)
      problem_ = "serial device " + dev + " does not support serial_baudrate " + std::to_string(cfg_.serial_baudrate);
    else if (rc == -ENOTTY)
      problem_ = dev + " is not a serial device";
    else
      problem_ = "cannot open serial device " + dev + ": " + std::strerror(-rc);
    return AdapterState::Failed;
  }

  AdapterState failed(const char* what, int rc) {
    if (rc == -EPERM || rc == -EACCES) {
      problem_ = std::string(what) + " CAN interface " + cfg_.interface +
                 ": permission denied (needs CAP_NET_ADMIN; run the runtime as root)";
      return AdapterState::NotPermitted;
    }
    problem_ = std::string(what) + " CAN interface " + cfg_.interface + ": " + std::strerror(-rc);
    return AdapterState::Failed;
  }

  void close_device() {
    if (fd_ < 0) return;
    serial_->close(fd_);
    fd_ = -1;
  }

  AdapterConfig cfg_;
  std::unique_ptr<LinkOps> ops_;
  std::unique_ptr<SerialOps> serial_;
  int fd_ = -1;
  std::string problem_;
};

}  // namespace

bool parse_newlink(const void* msg, size_t len, LinkInfo& out) {
  const nlmsghdr* nh = static_cast<const nlmsghdr*>(msg);
  if (len < NLMSG_LENGTH(sizeof(ifinfomsg)) || nh->nlmsg_len > len || nh->nlmsg_type != RTM_NEWLINK) return false;
  out = LinkInfo();
  parse_ifinfo(nh, out);
  return true;
}

std::unique_ptr<LinkOps> make_netlink_ops() { return std::unique_ptr<LinkOps>(new NetlinkOps); }

std::unique_ptr<SerialOps> make_serial_ops() { return std::unique_ptr<SerialOps>(new TtySerialOps); }

std::unique_ptr<CanAdapter> make_adapter(const AdapterConfig& cfg, std::unique_ptr<LinkOps> ops,
                                         std::unique_ptr<SerialOps> serial) {
  if (!ops) ops = make_netlink_ops();
  if (cfg.type == "slcan") {
    if (!serial) serial = make_serial_ops();
    return std::unique_ptr<CanAdapter>(new SlcanAdapter(cfg, std::move(ops), std::move(serial)));
  }
  return std::unique_ptr<CanAdapter>(new SocketCanAdapter(cfg, std::move(ops)));
}

}  // namespace canopen_plugin
