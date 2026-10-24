// host_requests.h - what the host asks of the CANopen master networks, and
// what it reads back: NMT commands from the Modbus bridge's control block,
// and each network's operational nodes for its live list (modbus-bridge
// spec).

#ifndef CANWORKS_HOST_REQUESTS_H
#define CANWORKS_HOST_REQUESTS_H

#include <atomic>
#include <bitset>
#include <cstdint>
#include <mutex>
#include <string>
#include <vector>

#include "config.h"

namespace canopen_plugin {

struct HostNmt {
  unsigned network = 0;
  unsigned node = 0;    // 0: every node of the network
  std::string command;  // start, stop, preop, reset, reset-comm (as the diagnostics nmt op)
  std::string by;       // for the log: who asked
};

class HostRequests {
 public:
  static HostRequests& instance();

  // NMT commands that may wait per network.
  static constexpr size_t kMaxQueued = 16;

  // Host: queues an NMT command for a master network's bus thread. False,
  // and nothing queued, while the network has no bus session (a command
  // must not run minutes later when the bus comes back) or kMaxQueued of
  // its commands wait already.
  bool nmt(unsigned network, unsigned node, const std::string& command,
           const std::string& by = "the Modbus control block");
  // Bus thread: the network's queued commands, oldest first.
  void take(unsigned network, std::vector<HostNmt>& out);
  // Bus thread: the network's bus session started or ended; at the end its
  // waiting commands are dropped.
  void set_session(unsigned network, bool up);
  // Host: how many bus sessions of `network` have ended (a session restart,
  // the interface going down): the bridge ends that network's mailbox
  // resources when it changes.
  uint32_t sessions_ended(unsigned network) const {
    return network < kMaxNetworks ? ended_[network].load(std::memory_order_acquire) : 0;
  }

  // Bus thread: node `node` of `network` is operational (or not).
  void set_operational(unsigned network, unsigned node, bool up);
  // Bus thread: the network stopped; none of its nodes is operational.
  void clear(unsigned network);
  // Host: bit n set while node n is operational.
  std::bitset<128> operational(unsigned network) const;

 private:
  std::mutex mu_;
  std::vector<HostNmt> queue_;
  bool session_[kMaxNetworks] = {};  // under mu_
  std::atomic<uint32_t> ended_[kMaxNetworks] = {};
  std::atomic<uint64_t> up_[kMaxNetworks][2] = {};
};

}  // namespace canopen_plugin

#endif  // CANWORKS_HOST_REQUESTS_H
