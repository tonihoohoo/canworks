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
// 4: the PLC link header names another map hash, 5: the PLC link header says
// the PLC stopped (PLC link configs).
enum class OutputState : uint8_t { kRunning = 1, kWatchdog = 2, kIdle = 3, kMismatch = 4, kPlcStopped = 5 };
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
  // The PLC link header's state (plc_link): off for mismatch or PLC stopped,
  // and back to running on an ok header.
  bool link_off(OutputState why) { return set(why); }

  OutputState state() const { return state_; }
  bool running() const { return state_ == OutputState::kRunning; }
  // Milliseconds until the watchdog fires (0 when off, idle or already fired).
  uint64_t left_ms(Clock::time_point now) const {
    if (watchdog_.count() == 0 || state_ != OutputState::kRunning) return 0;
    auto end = last_write_ + watchdog_;
    if (now >= end) return 0;
    return std::chrono::duration_cast<std::chrono::milliseconds>(end - now).count();
  }

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
  // An NMT command while the network's bus is down, or with 16 of its
  // commands still waiting.
  kCtrlRefused = 5,
  // The block held this counter when the bridge started: not run, so a
  // restart never repeats the client's last command.
  kCtrlRestarted = 6,
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
  // The first block a client wrote after the bridge started: its counter
  // becomes the last one handled, and a request in it is not run.
  // Returns true when it held one (counter not 0).
  bool baseline(const uint8_t* block);
  uint16_t counter() const { return counter_; }
  uint8_t result() const { return result_; }

 private:
  uint16_t counter_ = 0;  // the output image starts at 0
  uint8_t result_ = kCtrlOk;
};

// Status block byte 7.
enum StatusFlag : uint8_t {
  kStatusUncleanStart = 0x01,  // the previous run of this config did not stop cleanly
  kStatusBusNotOk = 0x02,      // a CAN network's interface is down or missing, or its controller bus-off
};

// Status block: state, clients, 100 ms heartbeat, control echo and result,
// flags.
void encode_status(uint8_t* block, OutputState state, int clients, uint16_t heartbeat, const ControlBlock& control,
                   uint8_t flags = 0);

// Live list: bit n set while node n is OPERATIONAL; bit 0 always 0.
void encode_live_list(uint8_t* block, const std::bitset<128>& operational);

// SDO bridge registers.
enum SdoStatus : uint8_t { kSdoIdle = 0, kSdoBusy = 1, kSdoDone = 2, kSdoAborted = 3 };

constexpr uint32_t kAbortValueRange = 0x06090030u;  // unknown command
constexpr uint32_t kAbortGeneral = 0x08000000u;
constexpr uint32_t kAbortNoTransfer = 0x08000020u;  // write not allowed
constexpr uint32_t kAbortLocalControl = 0x08000021u;  // held when the bridge started: not sent

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
  // The first request a client wrote after the bridge started: taken as the
  // last one handled and, when it holds one (counter not 0), ended aborted
  // with kAbortLocalControl without being sent. Returns true then.
  bool baseline(const uint8_t* request);

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
