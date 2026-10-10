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
#include <map>
#include <memory>
#include <mutex>
#include <string>
#include <vector>

#include "config.h"

struct can_msg;
struct __co_dev;

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
// plugin's own slave's) heartbeat, EMCY and SDO server, and for every
// configured node its predefined connection set (EMCY, TPDO1-4, RPDO1-4, SDO
// both ways, heartbeat) plus the COB-IDs its configured PDOs use; a PDO
// COB-ID with bit 29 set is the extended identifier. A slave network's own
// PDOs come from its dictionary at run time (dictionary_id_uses()).
std::string cob_id_use(const Config& cfg, uint32_t id, bool ext);

// The EMCY COB-ID a CANopen master network listens on for a node when it
// read another one from the node's 0x1014 than its configuration gives
// (canopen-online-diagnostics "EMCY COB-ID in the status"): the bus thread
// sets it (0 clears), cob_id_use() names that COB-ID as the node's EMCY.
// clear_emcy_cob_in_use() drops a network's entries (a new session).
void set_emcy_cob_in_use(unsigned network, unsigned node, uint32_t cob);
void clear_emcy_cob_in_use(unsigned network);
// The COB-ID in use for node `n` of `cfg`: the one set, else n.emcy_cob_id().
uint32_t emcy_cob_in_use(const Config& cfg, const NodeConfig& n);

// The key of an identifier in a map of identifiers: `id` with bit 31 set for
// an extended one.
inline uint32_t id_use_key(uint32_t id, bool ext) { return (id & 0x1FFFFFFFu) | (ext ? 0x80000000u : 0u); }

// The identifiers a CANopen dictionary uses, by id_use_key(): the COB-IDs
// of its valid RPDOs (0x1400-0x15FF) and TPDOs (0x1800-0x19FF), extended
// when bit 29 is set, and of its SDO servers (0x1200-0x127F). `owner` names
// the dictionary in the texts ("TPDO1 of the plugin's own slave").
std::map<uint32_t, std::string> dictionary_id_uses(const __co_dev* dev, const std::string& owner);

// What the network's protocol uses `id` for, whatever the protocol: the
// CANopen map above, on a J1939 network every 29-bit frame from the ECU's
// address (or address range), nothing on a plain CAN network. The guard of
// raw messages and program sends (can-raw-messages "Protocol identifiers").
std::string protocol_id_use(const Config& cfg, uint32_t id, bool ext);

// The raw `tx` message of the network that sends `id` ("raw message Lamps"),
// or "" (the guard map of hand-sent frames).
std::string raw_id_use(const Config& cfg, uint32_t id, bool ext);

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
