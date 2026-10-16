// The kernel socket's long sends on a SocketCAN interface (vcan0 by
// default): each send's id is the number the kernel gives its transport
// protocol session (SOF_TIMESTAMPING_OPT_ID), which the session's end
// carries, also for a send refused with EBUSY.
//
//   j1939_long_ids [IFACE]
//
// Address 0x20 is a second socket of this program, so the kernel answers
// its RTS/CTS; nobody is at 0x10 or 0x30, so those sessions end by the
// kernel's timeout (1.25 s). Takes about 1.5 s.
//   1. 200 bytes to 0x10 (id 0), then 200 bytes to 0x20 (id 1), queued
//      behind it: id 0 ends aborted, id 1 completes.
//   2. Another socket at our address starts a session to 0x30; ours to 0x30
//      is refused with EBUSY (the kernel numbered it 2); the next send, to
//      0x20, gets id 3 and completes.
// Exit 0 passed, 1 failed, 77 skipped (no interface or no can-j1939).

#include <cerrno>
#include <chrono>
#include <cstdio>
#include <cstring>
#include <map>
#include <string>
#include <thread>
#include <utility>
#include <vector>

#include <linux/can.h>
#include <linux/can/j1939.h>
#include <linux/net_tstamp.h>
#include <net/if.h>
#include <sys/socket.h>
#include <unistd.h>

#include "j1939_socket.h"

using namespace canopen_plugin;

namespace {

int g_failures = 0;

void check(bool ok, const std::string& what) {
  std::printf("%s %s\n", ok ? "ok  " : "FAIL", what.c_str());
  if (!ok) ++g_failures;
}

// Ends seen on `s` until `want` is among them or `seconds` pass: id -> aborted.
std::map<uint32_t, bool> ends_until(J1939Socket& s, uint32_t want, double seconds) {
  std::map<uint32_t, bool> seen;
  auto until = std::chrono::steady_clock::now() + std::chrono::duration<double>(seconds);
  while (std::chrono::steady_clock::now() < until && !seen.count(want)) {
    uint32_t id = 0;
    bool aborted = false;
    int error = 0;
    while (s.send_event(id, aborted, error) > 0) seen[id] = aborted;
    std::this_thread::sleep_for(std::chrono::milliseconds(5));
  }
  return seen;
}

// Which step of the long socket's setup the kernel refuses, for the log:
// the same sockets as the kernel socket's open and bind, at address 0x81.
void explain_no_events(const std::string& iface) {
  auto step = [](const char* what, int r) {
    std::printf("     %s: %s\n", what, r < 0 ? std::strerror(errno) : "ok");
    return r >= 0;
  };
  sockaddr_can a;
  std::memset(&a, 0, sizeof(a));
  a.can_family = AF_CAN;
  a.can_ifindex = static_cast<int>(if_nametoindex(iface.c_str()));
  a.can_addr.j1939.name = J1939_NO_NAME;
  a.can_addr.j1939.pgn = J1939_NO_PGN;
  int one = 1;
  int rx = socket(PF_CAN, SOCK_DGRAM | SOCK_NONBLOCK | SOCK_CLOEXEC, CAN_J1939);
  step("rx socket", rx);
  step("rx SO_J1939_PROMISC", setsockopt(rx, SOL_CAN_J1939, SO_J1939_PROMISC, &one, sizeof(one)));
  step("rx SO_BROADCAST", setsockopt(rx, SOL_SOCKET, SO_BROADCAST, &one, sizeof(one)));
  a.can_addr.j1939.addr = J1939_NO_ADDR;
  step("rx bind", bind(rx, reinterpret_cast<sockaddr*>(&a), sizeof(a)));
  int fds[2];
  a.can_addr.j1939.addr = 0x81;
  for (int k = 0; k < 2; ++k) {
    fds[k] = socket(PF_CAN, SOCK_DGRAM | SOCK_NONBLOCK | SOCK_CLOEXEC, CAN_J1939);
    step(k ? "long socket" : "ecu socket", fds[k]);
    step(k ? "long SO_BROADCAST" : "ecu SO_BROADCAST", setsockopt(fds[k], SOL_SOCKET, SO_BROADCAST, &one, sizeof(one)));
    step(k ? "long bind at 0x81" : "ecu bind at 0x81", bind(fds[k], reinterpret_cast<sockaddr*>(&a), sizeof(a)));
  }
  unsigned flags = SOF_TIMESTAMPING_OPT_ID | SOF_TIMESTAMPING_TX_ACK | SOF_TIMESTAMPING_TX_SCHED |
                   SOF_TIMESTAMPING_SOFTWARE | SOF_TIMESTAMPING_OPT_CMSG | SOF_TIMESTAMPING_OPT_TSONLY;
  step("long SO_J1939_ERRQUEUE", setsockopt(fds[1], SOL_CAN_J1939, SO_J1939_ERRQUEUE, &one, sizeof(one)));
  step("long SO_TIMESTAMPING", setsockopt(fds[1], SOL_SOCKET, SO_TIMESTAMPING, &flags, sizeof(flags)));
  ::close(rx);
  ::close(fds[0]);
  ::close(fds[1]);
}

}  // namespace

int main(int argc, char** argv) {
  const std::string iface = argc > 1 ? argv[1] : "vcan0";
  auto a = make_kernel_j1939_socket();
  auto b = make_kernel_j1939_socket();
  auto c = make_kernel_j1939_socket();
  int r = a->open(iface, {});
  if (r == -EPROTONOSUPPORT || r == -EAFNOSUPPORT || r == -ENODEV || r == -ENETDOWN) {
    std::printf("skipped: %s\n", j1939_socket_problem(r, iface).c_str());
    return 77;
  }
  int ra = r < 0 ? r : a->bind(0, 0x80);
  std::printf("     a bound (%d), events %d\n", ra, a->long_send_events() ? 1 : 0);
  if (ra < 0 || b->open(iface, {}) < 0 || c->open(iface, {}) < 0 || b->bind(0, 0x20) < 0 || c->bind(0, 0x80) < 0) {
    std::printf("FAIL setting up the sockets on %s\n", iface.c_str());
    return 1;
  }
  if (!a->long_send_events()) {
    std::this_thread::sleep_for(std::chrono::milliseconds(300));
    int again = a->bind(0, 0x80);
    std::printf("     a bound again after 300 ms (%d), events %d\n", again, a->long_send_events() ? 1 : 0);
  }
  if (!a->long_send_events()) {
    std::printf("FAIL the kernel does not report the long socket's sessions (%s)\n", a->long_send_problem().c_str());
    explain_no_events(iface);
    return 1;
  }
  std::vector<uint8_t> data(200);
  for (size_t k = 0; k < data.size(); ++k) data[k] = static_cast<uint8_t>(k);

  uint32_t id0 = 99, id1 = 99;
  r = a->send_long(0xEF00, 0x10, 6, data.data(), data.size(), id0);
  check(r == 0 && id0 == 0, "send to 0x10: id 0 (r " + std::to_string(r) + ", id " + std::to_string(id0) + ")");
  r = a->send_long(0xEF00, 0x20, 6, data.data(), data.size(), id1);
  check(r == 0 && id1 == 1, "send to 0x20: id 1 (r " + std::to_string(r) + ", id " + std::to_string(id1) + ")");
  auto seen = ends_until(*a, 1, 4.0);
  if (!seen.count(0)) {
    auto more = ends_until(*a, 0, 1.0);
    seen.insert(more.begin(), more.end());
  }
  check(seen.count(0) && seen[0], "id 0 (nobody at 0x10) ended aborted");
  check(seen.count(1) && !seen[1], "id 1 (0x20) completed");

  uint32_t idc = 0, id2 = 99, id3 = 99;
  r = c->send_long(0xEF00, 0x30, 6, data.data(), data.size(), idc);
  check(r == 0, "another socket's session to 0x30 started (r " + std::to_string(r) + ")");
  r = a->send_long(0xEF00, 0x30, 6, data.data(), data.size(), id2);
  check(r == -EBUSY, "ours to 0x30 refused with EBUSY (r " + std::to_string(r) + ")");
  r = a->send_long(0xEF00, 0x20, 6, data.data(), data.size(), id3);
  check(r == 0 && id3 == 3, "next send to 0x20: id 3 (r " + std::to_string(r) + ", id " + std::to_string(id3) + ")");
  seen = ends_until(*a, 3, 2.0);
  check(seen.count(3) && !seen[3], "id 3 completed");

  a->close();
  b->close();
  c->close();
  std::printf("%s\n", g_failures ? "FAILED" : "passed");
  return g_failures ? 1 : 0;
}
