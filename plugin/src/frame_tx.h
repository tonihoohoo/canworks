// frame_tx.h - raw frames sent by hand through the diagnostics channel
// (canopen-online-diagnostics spec, "Send raw frames" and "Guards on raw
// frames").
//
// Frames are sent from the diagnostics server thread on a CAN_RAW socket of
// their own; Lely's socket keeps local loopback on, so the master receives
// them like any frame on the bus and a trace marks them Tx. On a simulated
// network they go through a pipe to the bus thread, which writes them onto
// the virtual bus. Neither path touches the PLC scan.

#ifndef CANOPEN_FRAME_TX_H
#define CANOPEN_FRAME_TX_H

#include <chrono>
#include <cstdint>
#include <memory>
#include <mutex>
#include <string>
#include <vector>

#include "config.h"

struct can_msg;

namespace canopen_plugin {

// One frame to send: SocketCAN-style identifier (without flags), format and
// data.
struct RawFrame {
  uint32_t id = 0;
  bool ext = false;
  bool rtr = false;
  uint8_t dlc = 0;
  uint8_t data[8] = {};
};

// "40 18 10 01" for the log.
std::string raw_frame_text(const RawFrame& f);

// What the running network uses `id` for ("RPDO1 of node 5", "NMT", ...), or
// "" when it is free. Covers NMT, SYNC, TIME, LSS, the master's (or the
// plugin's own slave's) heartbeat and EMCY, and for every configured node its
// predefined connection set (EMCY, TPDO1-4, RPDO1-4, SDO both ways,
// heartbeat) plus the COB-IDs its configured PDOs use. Extended identifiers
// are never in the map.
std::string cob_id_use(const Config& cfg, uint32_t id, bool ext);

// Where frames go: a CAN_RAW socket on the interface, or the simulated bus.
class FrameSink {
 public:
  virtual ~FrameSink() = default;
  // Opens on first use; 0 or a negative errno.
  virtual int open() = 0;
  // Writes one frame without blocking; 0 or a negative errno (-ENOBUFS:
  // transmit queue full).
  virtual int send(const RawFrame& f) = 0;
  virtual void close() = 0;
  virtual bool is_open() const = 0;
};

std::unique_ptr<FrameSink> make_can_frame_sink(const std::string& interface);

// The simulated network's side: the diagnostics thread queues frames and
// wakes the bus thread through an eventfd (FdWake on read_fd(), which drains
// it); the bus thread takes them and writes them onto the virtual bus.
class SimFrameInjector {
 public:
  static constexpr size_t kMaxQueued = 256;
  SimFrameInjector();
  ~SimFrameInjector();
  // Server thread; -ENOBUFS when kMaxQueued frames wait.
  int push(const RawFrame& f);
  // Bus thread: the frames waiting.
  void drain(std::vector<RawFrame>& out);
  int read_fd() const { return fd_; }

 private:
  int fd_ = -1;
  std::mutex mutex_;
  std::vector<RawFrame> queue_;
};

std::unique_ptr<FrameSink> make_sim_frame_sink(std::shared_ptr<SimFrameInjector> injector);

// can_msg for Lely from a RawFrame.
void raw_frame_to_msg(const RawFrame& f, can_msg& msg);

// Token bucket: `rate` tokens per second, at most `burst` saved up.
class RateLimit {
 public:
  RateLimit(double rate, double burst) : rate_(rate), burst_(burst), tokens_(burst) {}
  bool take(std::chrono::steady_clock::time_point now);

 private:
  double rate_, burst_, tokens_;
  std::chrono::steady_clock::time_point last_{};
  bool started_ = false;
};

}  // namespace canopen_plugin

#endif  // CANOPEN_FRAME_TX_H
