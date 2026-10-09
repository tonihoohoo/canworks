// bridge_blocks.cpp - see bridge_blocks.h.

#include "bridge_blocks.h"

#include <algorithm>
#include <cstring>

#include "byte_image.h"

namespace canworks_bridge {

bool OutputSupervisor::set(OutputState s) {
  if (s == state_) return false;
  state_ = s;
  return true;
}

bool OutputSupervisor::write(Clock::time_point now) {
  last_write_ = now;
  return state_ == OutputState::kWatchdog && set(OutputState::kRunning);
}

bool OutputSupervisor::tick(Clock::time_point now) {
  if (state_ != OutputState::kRunning || watchdog_.count() == 0) return false;
  return now - last_write_ >= watchdog_ && set(OutputState::kWatchdog);
}

bool OutputSupervisor::idle() { return set(OutputState::kIdle); }

bool OutputSupervisor::run(Clock::time_point now) {
  last_write_ = now;
  return set(OutputState::kRunning);
}

bool ControlBlock::poll(const uint8_t* block, ControlRequest& req) const {
  uint16_t counter = get_be16(block);
  if (counter == counter_) return false;
  req.counter = counter;
  req.command = block[2];
  req.network = block[3];
  req.node = block[4];
  return true;
}

uint8_t ControlBlock::check(const ControlRequest& req, const std::vector<bool>& is_master) {
  switch (req.command) {
    case kCmdNone:
    case kCmdRun:
    case kCmdIdle:
      return kCtrlOk;
    case kCmdNmtStart:
    case kCmdNmtStop:
    case kCmdNmtPreOperational:
    case kCmdResetNode:
    case kCmdResetCommunication:
      if (req.network >= is_master.size()) return kCtrlBadNetwork;
      if (!is_master[req.network]) return kCtrlNotMaster;
      if (req.node > 127) return kCtrlBadNode;
      return kCtrlOk;
    default:
      return kCtrlUnknownCommand;
  }
}

void encode_status(uint8_t* block, OutputState state, int clients, uint16_t heartbeat, const ControlBlock& control) {
  block[0] = static_cast<uint8_t>(state);
  block[1] = static_cast<uint8_t>(std::min(clients, 255));
  put_be16(block + 2, heartbeat);
  put_be16(block + 4, control.counter());
  block[6] = control.result();
  block[7] = 0;
}

void encode_live_list(uint8_t* block, const std::bitset<128>& operational) {
  std::memset(block, 0, kLiveListBytes);
  for (unsigned n = 1; n < 128; ++n)
    if (operational[n]) block[n / 8] |= static_cast<uint8_t>(1u << (n % 8));
}

SdoRequest SdoBridgeRegisters::decode(const uint8_t* b) {
  SdoRequest r;
  r.counter = get_be16(b);
  r.command = b[2];
  r.network = b[3];
  r.node = b[4];
  r.subindex = b[5];
  r.index = get_be16(b + 6);
  r.length = b[8];
  r.value = get_be32(b + 10);
  return r;
}

void SdoBridgeRegisters::finish(uint8_t status, uint32_t abort, uint32_t value) {
  busy_ = false;
  status_ = status;
  abort_ = abort;
  if (status == kSdoDone && !write_) value_ = value;
}

void SdoBridgeRegisters::service(const uint8_t* request, SdoBackend& backend) {
  if (busy_) {
    uint32_t value = 0, abort = 0;
    int rc = backend.poll(value, abort);
    if (rc > 0)
      finish(kSdoDone, 0, value);
    else if (rc < 0)
      finish(kSdoAborted, abort ? abort : kAbortGeneral, 0);
    if (busy_) return;
  }
  SdoRequest req = decode(request);
  if (req.counter == counter_) return;
  counter_ = req.counter;
  write_ = req.command == 2;
  value_ = 0;
  if (req.command != 1 && req.command != 2) return finish(kSdoAborted, kAbortValueRange, 0);
  if (write_ && !allow_write_) return finish(kSdoAborted, kAbortNoTransfer, 0);
  if (req.node < 1 || req.node > 127 || (write_ && (req.length < 1 || req.length > 4)))
    return finish(kSdoAborted, kAbortGeneral, 0);
  uint32_t abort = 0;
  if (!backend.start(req, abort)) return finish(kSdoAborted, abort ? abort : kAbortGeneral, 0);
  busy_ = true;
  status_ = kSdoBusy;
  abort_ = 0;
}

void SdoBridgeRegisters::encode(uint8_t* b) const {
  std::memset(b, 0, kSdoResponseBytes);
  put_be16(b, counter_);
  b[2] = status_;
  put_be32(b + 4, abort_);
  put_be32(b + 8, value_);
}

}  // namespace canworks_bridge
