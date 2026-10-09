// host_requests.h - what a host other than the PLC program asks of the
// CANopen master networks, and what it reads back: NMT commands from the
// Modbus bridge's control block, and each network's operational nodes for
// its live list (modbus-bridge spec). The OpenPLC plugin never uses it.

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
};

class HostRequests {
 public:
  static HostRequests& instance();

  // Host: queues an NMT command for a master network's bus thread.
  void nmt(unsigned network, unsigned node, const std::string& command);
  // Bus thread: the network's queued commands, oldest first.
  void take(unsigned network, std::vector<HostNmt>& out);

  // Bus thread: node `node` of `network` is operational (or not).
  void set_operational(unsigned network, unsigned node, bool up);
  // Bus thread: the network stopped; none of its nodes is operational.
  void clear(unsigned network);
  // Host: bit n set while node n is operational.
  std::bitset<128> operational(unsigned network) const;

 private:
  std::mutex mu_;
  std::vector<HostNmt> queue_;
  std::atomic<uint64_t> up_[kMaxNetworks][2] = {};
};

}  // namespace canopen_plugin

#endif  // CANWORKS_HOST_REQUESTS_H
