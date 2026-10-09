// can_adapter.h - the CAN adapter backend: prepares the interface the master
// opens. Selected by the config's adapter.type: "socketcan" or "slcan".
//
// The SocketCAN backend reads and changes the link over rtnetlink (no
// iproute2): with configure_link it sets the configured bit rate (and
// restart-ms) and brings the link up, taking it down first only when it runs
// at a different rate. A vcan link has no bit rate and is only brought up.
// Changing the link needs CAP_NET_ADMIN. It runs in the bus thread, never in
// the scan path.
//
// The slcan backend creates the interface itself, as slcand does: it opens the
// serial device, attaches the kernel's slcan line discipline (N_SLCAN), renames
// the new slcanN link to the configured name and then sets it up over
// rtnetlink like a SocketCAN link (Linux 6.0+: slcan is a CAN device that
// takes its bit rate over netlink). The interface lives as long as the plugin
// holds the device open: release() and an unplugged adapter remove it.

#ifndef CANOPEN_CAN_ADAPTER_H
#define CANOPEN_CAN_ADAPTER_H

#include <cerrno>
#include <cstddef>
#include <cstdint>
#include <functional>
#include <memory>
#include <string>

#include "config.h"

namespace canopen_plugin {

class SweepListener;  // bitrate_sweep.h

// What rtnetlink says about a link.
struct LinkInfo {
  bool up = false;         // IFF_UP
  std::string kind;        // IFLA_INFO_KIND: "can", "vcan", ... ("" if none)
  unsigned bitrate = 0;    // IFLA_CAN_BITTIMING bitrate, kind "can" only
  // Bus diagnostics, kind "can" only (see bus_monitor.h).
  bool has_can_state = false;  // IFLA_CAN_STATE present
  unsigned can_state = 0;      // enum can_state: 0 error-active ... 3 bus-off, 4 stopped, 5 sleeping
  bool has_berr = false;       // IFLA_CAN_BERR_COUNTER present (driver reports counters)
  unsigned tx_errors = 0;
  unsigned rx_errors = 0;
  bool listen_only = false;    // IFLA_CAN_CTRLMODE has CAN_CTRLMODE_LISTENONLY, kind "can" only
  bool has_stats = false;      // IFLA_INFO_XSTATS (struct can_device_stats) present
  uint32_t bus_off = 0;        // can_device_stats.bus_off: bus-off events since the link was created
};

// Parses one RTM_NEWLINK message (header included) into `out`. Returns false
// if it is not one. Exposed for tests.
bool parse_newlink(const void* msg, size_t len, LinkInfo& out);

// The link operations, behind an interface so tests can mock them. Each
// returns 0 or a negative errno (-ENODEV: no such interface, -EPERM: not
// permitted).
class LinkOps {
 public:
  virtual ~LinkOps() = default;
  virtual int get(const std::string& name, LinkInfo& out) = 0;
  virtual int set_up(const std::string& name, bool up) = 0;
  // Sets the CAN bit timing by bit rate and, if restart_ms >= 0, the bus-off
  // auto-restart delay. The link must be down.
  virtual int set_bitrate(const std::string& name, unsigned bitrate, long restart_ms) = 0;
  // The link must be down.
  virtual int rename(const std::string& name, const std::string& new_name) = 0;
  virtual int set_txqlen(const std::string& name, unsigned len) = 0;
  // Sets or clears listen-only mode (CAN_CTRLMODE_LISTENONLY). The link must
  // be down. -EOPNOTSUPP when the driver has no such mode.
  virtual int set_listen_only(const std::string& name, bool on) {
    (void)name;
    (void)on;
    return -EOPNOTSUPP;
  }
};

// The serial side of the slcan backend, behind an interface so tests can mock
// it. Each returns 0 or a negative errno.
class SerialOps {
 public:
  virtual ~SerialOps() = default;
  // Opens `path` for exclusive use in raw mode, at `baudrate` unless 0.
  virtual int open(const std::string& path, unsigned baudrate, int& fd) = 0;
  // Attaches the slcan line discipline and returns the created interface.
  virtual int attach(int fd, std::string& ifname) = 0;
  virtual void close(int fd) = 0;
};

std::unique_ptr<SerialOps> make_serial_ops();

// rtnetlink implementation.
std::unique_ptr<LinkOps> make_netlink_ops();

enum class AdapterState { Ready, Missing, Down, NotPermitted, Failed };

class CanAdapter {
 public:
  virtual ~CanAdapter() = default;
  // Makes the interface usable as the config says. Called on every bring-up
  // attempt; logs what it changes. Ready means the master can open it.
  virtual AdapterState prepare() = 0;
  // Why the last prepare() did not return Ready, for the log.
  virtual std::string problem() const = 0;
  virtual const std::string& interface() const = 0;
  // Gives back what prepare() acquired (the slcan device, and with it the
  // interface). Called when the bus thread ends.
  virtual void release() {}
  // The link operations the backend uses (bit rate detection), or nullptr.
  virtual LinkOps* link_ops() { return nullptr; }
  // Bit rate detection on the backend's own device rather than the kernel
  // link (slcan, slcan_sweep.h): releases the interface, calls `run` with the
  // device's link operations and listener, and gives the device back;
  // prepare() makes the interface again. False: sweep over link_ops().
  // `error` says why the device could not be opened, or that it does not
  // confirm listen-only (kUnconfirmedListenOnly) unless `disturb_bus`.
  virtual bool sweep_on_device(const std::function<void(LinkOps&, SweepListener&)>& run, bool disturb_bus,
                               std::string& error) {
    (void)run;
    (void)disturb_bus;
    (void)error;
    return false;
  }
};

// The backend for adapter.type (the config parser accepts only known types).
// `ops` defaults to rtnetlink, `serial` to the real serial device.
std::unique_ptr<CanAdapter> make_adapter(const AdapterConfig& cfg, std::unique_ptr<LinkOps> ops = nullptr,
                                         std::unique_ptr<SerialOps> serial = nullptr);

}  // namespace canopen_plugin

#endif  // CANOPEN_CAN_ADAPTER_H
