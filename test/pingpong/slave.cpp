// The ping-pong slave on a SocketCAN interface (the tutorial's slave program).
//
//   pingpong_slave <interface> <cpp-slave.eds> [node-id]

#include <cstdio>
#include <cstdlib>

#include <lely/ev/loop.hpp>
#include <lely/io2/linux/can.hpp>
#include <lely/io2/posix/poll.hpp>
#include <lely/io2/sys/io.hpp>
#include <lely/io2/sys/sigset.hpp>
#include <lely/io2/sys/timer.hpp>

#include "pingpong_slave.hpp"

using namespace lely;

int main(int argc, char* argv[]) {
  if (argc < 3) {
    std::fprintf(stderr, "usage: %s <interface> <eds> [node-id]\n", argv[0]);
    return 2;
  }
  uint8_t id = argc > 3 ? static_cast<uint8_t>(std::atoi(argv[3])) : 2;
  io::IoGuard io_guard;
  io::Context ctx;
  io::Poll poll(ctx);
  ev::Loop loop(poll.get_poll());
  auto exec = loop.get_executor();
  io::Timer timer(poll, exec, CLOCK_MONOTONIC);
  io::CanController ctrl(argv[1]);
  io::CanChannel chan(poll, exec);
  chan.open(ctrl);

  PingPongSlave slave(timer, chan, argv[2], "", id);

  io::SignalSet sigset(poll, exec);
  sigset.insert(SIGHUP);
  sigset.insert(SIGINT);
  sigset.insert(SIGTERM);
  sigset.submit_wait([&](int /*signo*/) {
    sigset.clear();
    ctx.shutdown();
  });

  slave.Reset();
  loop.run();
  return 0;
}
