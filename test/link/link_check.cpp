// link_check - runs the SocketCAN adapter's link setup on a real interface,
// the way the bus thread does at PLC start (CI, on vcan0).
//
//   link_check <interface> --expect ready|not-permitted
//
// As root on a down vcan0 it must bring the link up (ready). As a user
// without CAP_NET_ADMIN it must report not-permitted and leave the link alone.
// Exit status 0 when the outcome matches.

#include <cstdio>
#include <cstring>
#include <string>

#include "can_adapter.h"
#include "log.h"

using namespace canopen_plugin;

static void print(LogLevel, const char* msg) { std::printf("  log: %s\n", msg); }

int main(int argc, char** argv) {
  if (argc != 4 || std::strcmp(argv[2], "--expect") != 0) {
    std::fprintf(stderr, "usage: %s <interface> --expect ready|not-permitted\n", argv[0]);
    return 2;
  }
  set_log_sink(print);
  AdapterConfig cfg;
  cfg.interface = argv[1];
  cfg.bitrate = 125000;
  auto ops = make_netlink_ops();
  LinkInfo before;
  if (ops->get(cfg.interface, before) != 0) {
    std::printf("FAIL: cannot read %s\n", argv[1]);
    return 1;
  }
  std::printf("before: %s, kind '%s'\n", before.up ? "up" : "down", before.kind.c_str());
  auto adapter = make_adapter(cfg);
  AdapterState st = adapter->prepare();
  LinkInfo after;
  ops->get(cfg.interface, after);
  std::printf("after: %s; state %d %s\n", after.up ? "up" : "down", static_cast<int>(st), adapter->problem().c_str());

  std::string expect = argv[3];
  if (expect == "ready") {
    if (st == AdapterState::Ready && after.up) return std::printf("OK: link brought up\n"), 0;
  } else if (expect == "not-permitted") {
    if (st == AdapterState::NotPermitted && after.up == before.up &&
        adapter->problem().find("CAP_NET_ADMIN") != std::string::npos)
      return std::printf("OK: not permitted, link unchanged\n"), 0;
  }
  std::printf("FAIL: expected %s\n", expect.c_str());
  return 1;
}
