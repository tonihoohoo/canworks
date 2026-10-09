// bridge_blocks.h - the bridge's own registers: output watchdog and outputs
// off, the status block, the control block with its counter handshake, the
// live list and the SDO bridge registers. All of it works on plain byte
// blocks of the image, so the bridge host only copies blocks in and out.

#ifndef CANWORKS_BRIDGE_BRIDGE_BLOCKS_H
#define CANWORKS_BRIDGE_BRIDGE_BLOCKS_H

#include <bitset>
#include <chrono>
#include <cstdint>
#include <vector>

namespace canworks_bridge {

using Clock = std::chrono::steady_clock;

constexpr unsigned kStatusBytes = 8;
constexpr unsigned kControlBytes = 6;
constexpr unsigned kLiveListBytes = 16;
constexpr unsigned kSdoRequestBytes = 14;
constexpr unsigned kSdoResponseBytes = 14;

// Status block byte 0.
enum class OutputState : uint8_t { kRunning = 1, kWatchdog = 2, kIdle = 3 };
// on_client_loss: what outputs off means.
enum class LossAction : uint8_t { kStop, kZero, kHold };

// Output watchdog and the idle command. Outputs run until no accepted write
// came for `watchdog_ms` (0: never) or the idle command; the next accepted
// write ends the watchdog state, only the run command ends idle.
class OutputSupervisor {
 public:
  OutputSupervisor(uint32_t watchdog_ms, Clock::time_point start) : watchdog_(watchdog_ms), last_write_(start) {}

  // Each returns true when the state changed.
  bool write(Clock::time_point now);
  bool tick(Clock::time_point now);
  bool idle();
  bool run(Clock::time_point now);

  OutputState state() const { return state_; }
  bool running() const { return state_ == OutputState::kRunning; }

 private:
  bool set(OutputState s);
  std::chrono::milliseconds watchdog_;
  Clock::time_point last_write_;
  OutputState state_ = OutputState::kRunning;
};

// Control block: counter (word), command, network index, node, reserved.
enum ControlCommandCode : uint8_t {
  kCmdNone = 0,
  kCmdRun = 1,
  kCmdIdle = 2,
  kCmdNmtStart = 3,
  kCmdNmtStop = 4,
  kCmdNmtPreOperational = 5,
  kCmdResetNode = 6,
  kCmdResetCommunication = 7,
};
enum ControlResult : uint8_t {
  kCtrlOk = 0,
  kCtrlUnknownCommand = 1,
  kCtrlBadNetwork = 2,
  kCtrlBadNode = 3,
  kCtrlNotMaster = 4,
};

struct ControlRequest {
  uint16_t counter = 0;
  uint8_t command = 0;
  uint8_t network = 0;
  uint8_t node = 0;
};

class ControlBlock {
 public:
  // True once for each new counter value in `block` (kControlBytes).
  bool poll(const uint8_t* block, ControlRequest& req) const;
  // Checks a request against the bridge's networks (true: CANopen master).
  static uint8_t check(const ControlRequest& req, const std::vector<bool>& is_master);
  void handled(uint16_t counter, uint8_t result) {
    counter_ = counter;
    result_ = result;
  }
  uint16_t counter() const { return counter_; }
  uint8_t result() const { return result_; }

 private:
  uint16_t counter_ = 0;  // the output image starts at 0
  uint8_t result_ = kCtrlOk;
};

// Status block: state, clients, 100 ms heartbeat, control echo and result.
void encode_status(uint8_t* block, OutputState state, int clients, uint16_t heartbeat, const ControlBlock& control);

// Live list: bit n set while node n is OPERATIONAL; bit 0 always 0.
void encode_live_list(uint8_t* block, const std::bitset<128>& operational);

// SDO bridge registers.
enum SdoStatus : uint8_t { kSdoIdle = 0, kSdoBusy = 1, kSdoDone = 2, kSdoAborted = 3 };

constexpr uint32_t kAbortValueRange = 0x06090030u;  // unknown command
constexpr uint32_t kAbortGeneral = 0x08000000u;
constexpr uint32_t kAbortNoTransfer = 0x08000020u;  // write not allowed

struct SdoRequest {
  uint16_t counter = 0;
  uint8_t command = 0;  // 1 read, 2 write
  uint8_t network = 0;
  uint8_t node = 0;
  uint8_t subindex = 0;
  uint16_t index = 0;
  uint8_t length = 0;
  uint32_t value = 0;
};

// The SDO path behind the registers (the queue the SDO function blocks and
// the gateway's SDO bridge use).
class SdoBackend {
 public:
  virtual ~SdoBackend() = default;
  // Starts a transfer; false ends the request aborted with `abort`.
  virtual bool start(const SdoRequest& req, uint32_t& abort) = 0;
  // 0 still running, 1 done (`value` for a read), -1 aborted with `abort`.
  virtual int poll(uint32_t& value, uint32_t& abort) = 0;
};

class SdoBridgeRegisters {
 public:
  explicit SdoBridgeRegisters(bool allow_write) : allow_write_(allow_write) {}

  static SdoRequest decode(const uint8_t* request);
  // Starts the request when its counter differs from the last one taken,
  // and polls a running one. A new counter while busy starts after the
  // running request ends.
  void service(const uint8_t* request, SdoBackend& backend);
  void encode(uint8_t* response) const;

  uint8_t status() const { return status_; }

 private:
  void finish(uint8_t status, uint32_t abort, uint32_t value);
  bool allow_write_;
  bool busy_ = false;
  bool write_ = false;
  uint16_t counter_ = 0;
  uint8_t status_ = kSdoIdle;
  uint32_t abort_ = 0;
  uint32_t value_ = 0;
};

}  // namespace canworks_bridge

#endif
