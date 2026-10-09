// j1939_socket.h - the kernel's CAN_J1939 sockets for one J1939 network
// (design Decision 2): a receive socket in promiscuous mode with a PGN
// filter, which gets every message (transport protocol sessions already
// reassembled by the kernel), and the ECU socket bound to our NAME and
// address, which sends. Behind an interface so the engine can be tested
// without the kernel module.

#ifndef CANWORKS_J1939_SOCKET_H
#define CANWORKS_J1939_SOCKET_H

#include <cstddef>
#include <cstdint>
#include <memory>
#include <string>
#include <vector>

#include "j1939_config.h"

namespace canopen_plugin {

constexpr uint32_t kPgnRequest = 0xEA00;         // 59904
constexpr uint32_t kPgnAddressClaimed = 0xEE00;  // 60928
constexpr uint32_t kPgnAcknowledgement = 0xE800;  // 59392

// One received message.
struct J1939Message {
  uint32_t pgn = 0;  // PDU1: the low byte is 0
  uint8_t source = kJ1939NullAddress;
  uint8_t destination = kJ1939Global;
  uint64_t source_name = 0;  // 0 when the kernel does not know the sender's NAME
  uint8_t priority = 6;
  std::vector<uint8_t> data;
};

class J1939Socket {
 public:
  virtual ~J1939Socket() = default;
  // Opens the receive socket on `ifname`, taking the PGNs in `pgns`. 0 or
  // a negative errno.
  virtual int open(const std::string& ifname, const std::vector<uint32_t>& pgns) = 0;
  // (Re)binds the ECU socket to our NAME at `address` (254: the null
  // address, for Cannot Claim and the first Request for Address Claimed).
  virtual int bind(uint64_t name, uint8_t address) = 0;
  virtual void close() = 0;
  // The receive socket's descriptor, for poll().
  virtual int fd() const = 0;
  // The next message, 0, -EAGAIN when there is none, or another negative errno.
  virtual int receive(J1939Message& out) = 0;
  // Sends from the bound address. `destination` 255 is global. 0 or a
  // negative errno.
  virtual int send(uint32_t pgn, uint8_t destination, uint8_t priority, const uint8_t* data, size_t len) = 0;
};

std::unique_ptr<J1939Socket> make_kernel_j1939_socket();

// What a socket error means for the log ("J1939 needs the can-j1939 kernel
// module (modprobe can-j1939)" for EPROTONOSUPPORT).
std::string j1939_socket_problem(int err, const std::string& ifname);

}  // namespace canopen_plugin

#endif  // CANWORKS_J1939_SOCKET_H
