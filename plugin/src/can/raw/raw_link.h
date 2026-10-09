// raw_link.h - where a network's raw I/O thread (raw_io.h) reads and writes
// frames: its own CAN_RAW socket on a SocketCAN interface, or a bridge to a
// simulated bus. The bridge connects either to a CANopen network's virtual
// bus (its bus thread copies frames both ways) or, on a simulated plain CAN
// network, loops frames back by itself: that network has no other bus.

#ifndef CANWORKS_RAW_LINK_H
#define CANWORKS_RAW_LINK_H

#include <atomic>
#include <cstdint>
#include <deque>
#include <memory>
#include <mutex>
#include <string>
#include <utility>
#include <vector>

#include "../can_plc_api.h"
#include "../trace_capture.h"

namespace canworks_raw {

// How program frames are confirmed (diagnostics status).
enum class Confirm { Unknown, Echo, Write };

// Who writes a frame through a link.
enum class Origin {
  Own,     // the raw path (config messages, program frames): comes back as its echo
  Device,  // a simulated plain CAN device: comes back as a frame from the bus
  Hand,    // sent by hand through the diagnostics channel: from the bus, but Tx in a trace
};

// A frame from the link.
struct LinkFrame {
  canworks_can_frame frame;
  bool ours = false;       // written through this link (its echo)
  bool this_host = false;  // written by another socket on this host (the protocol, or another program)
};

// A kernel-style receive filter: frames whose identifier matches `id` under
// `mask`, with the extended and RTR flags as in SocketCAN.
struct LinkFilter {
  uint32_t can_id = 0;
  uint32_t can_mask = 0;
};

class RawLink {
 public:
  virtual ~RawLink() = default;
  // 0 or a negative errno.
  virtual int open() = 0;
  virtual void close() = 0;
  // Polled for POLLIN; POLLERR/POLLHUP mean the link is gone (reopen).
  virtual int fd() const = 0;
  virtual Confirm confirm() const = 0;
  // `all`: every frame (the filters are ignored); otherwise only these.
  virtual void set_filters(const std::vector<LinkFilter>& filters, bool all) = 0;
  // Appends what is waiting (at most `max`).
  virtual void read(std::vector<LinkFrame>& out, size_t max) = 0;
  // Writes without blocking: 0 or an errno.
  virtual int write(const canworks_can_frame& f, Origin origin = Origin::Own) = 0;
  // For log lines: "can0" or "the simulated network".
  virtual std::string where() const = 0;
};

std::unique_ptr<RawLink> make_socket_link(const std::string& interface);

// Frames between the raw path and a simulated bus.
class SimBridge : public std::enable_shared_from_this<SimBridge> {
 public:
  // `loopback`: no bus thread; what the raw side writes is on the bus at once.
  explicit SimBridge(bool loopback);
  ~SimBridge();
  SimBridge(const SimBridge&) = delete;
  SimBridge& operator=(const SimBridge&) = delete;

  bool loopback() const { return loopback_; }

  // --- Raw side ---
  // 0, ENETDOWN (no bus thread attached) or ENOBUFS.
  int write(const canworks_can_frame& f, Origin origin);
  int rx_fd() const { return rx_fd_; }
  void drain(std::vector<LinkFrame>& out, size_t max);

  // --- Bus side (a CANopen network's bus thread) ---
  // The bus thread runs a session on the virtual bus (frames can be written).
  void attach(bool on);
  int tx_fd() const { return tx_fd_; }
  // The frames the raw side wrote, with whether each is its own (Origin::Own).
  void take(std::vector<std::pair<canworks_can_frame, bool>>& out);
  // A frame on the bus: one written for the raw side (`ours` for its own),
  // or one from anyone else.
  void seen(const canworks_can_frame& f, bool ours);

  // A bus trace of a simulated plain CAN network (the loopback is its bus);
  // nullptr unless loopback. The bridge must be owned by a shared_ptr.
  std::unique_ptr<canopen_plugin::TraceSource> trace_source();
  void trace(const canworks_can_frame& f, bool tx);

 private:
  static constexpr size_t kMax = 4096;
  void wake(int fd);
  bool loopback_;
  int rx_fd_ = -1, tx_fd_ = -1;
  std::atomic<bool> attached_{false};
  std::mutex mutex_;
  std::deque<LinkFrame> rx_;
  std::deque<std::pair<canworks_can_frame, bool>> tx_;
  // Bus trace (loopback only): a pipe of TraceRecords while a trace runs.
  int trace_pipe_[2] = {-1, -1};
  std::atomic<bool> trace_on_{false};
  std::atomic<uint64_t> trace_drops_{0};
  friend class BridgeTraceSource;
};

std::unique_ptr<RawLink> make_bridge_link(std::shared_ptr<SimBridge> bridge);

// The bridge of a simulated CANopen network, by network index, for its bus
// thread to serve: set at config load, cleared at teardown (nullptr: none).
void set_sim_bridge(unsigned network, std::shared_ptr<SimBridge> bridge);
std::shared_ptr<SimBridge> sim_bridge(unsigned network);

// canworks_can_frame <-> the TraceRecord id field.
canopen_plugin::TraceRecord trace_record(const canworks_can_frame& f, bool tx);

}  // namespace canworks_raw

#endif  // CANWORKS_RAW_LINK_H
