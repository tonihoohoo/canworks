// The tutorial ping-pong slave as an LSS device without a node ID, on a
// SocketCAN interface (test/lss/run.sh).
//
//   lss_slave <interface> <eds with LSS_Supported=1 and a serial number>
//
// It starts with node ID 0xFF (unconfigured). Lely's LSS slave needs a
// communication reset to use a node ID it got while it had none; CiA 305
// devices start with it when switched to the LSS waiting state. A second
// channel on the interface watches for "switch state global: waiting"
// (0x7E5 04 00) and does that reset, as in the sim tests. "Store
// configuration" is accepted and only printed.

#include <cstdio>

#include <functional>

#include <lely/co/dev.h>
#include <lely/ev/loop.hpp>
#include <lely/io2/linux/can.hpp>
#include <lely/io2/posix/poll.hpp>
#include <lely/io2/sys/io.hpp>
#include <lely/io2/sys/sigset.hpp>
#include <lely/io2/sys/timer.hpp>

#include "pingpong_slave.hpp"

// From <lely/co/nmt.h> and <lely/co/lss.h>, which do not mix with the C++ headers.
extern "C" {
co_unsigned8_t co_nmt_get_id(const co_nmt_t* nmt);
int co_nmt_cs_ind(co_nmt_t* nmt, co_unsigned8_t cs);
co_lss_t* co_nmt_get_lss(const co_nmt_t* nmt);
typedef int co_lss_store_ind_t(co_lss_t* lss, co_unsigned8_t id, co_unsigned16_t rate, void* data);
void co_lss_set_store_ind(co_lss_t* lss, co_lss_store_ind_t* ind, void* data);
}

using namespace lely;

namespace {

constexpr co_unsigned8_t kCsResetComm = 0x82;

class LssSlave : public PingPongSlave {
 public:
  using PingPongSlave::PingPongSlave;

  void ApplyPendingId() {
    std::lock_guard<util::BasicLockable> lock(*this);
    auto* n = reinterpret_cast<co_nmt_t*>(nmt());
    if (co_dev_get_id(reinterpret_cast<co_dev_t*>(dev())) == 0xFF && co_nmt_get_id(n) != 0xFF) {
      std::printf("lss_slave: starting with node ID %u\n", co_nmt_get_id(n));
      std::fflush(stdout);
      co_nmt_cs_ind(n, kCsResetComm);
    }
  }

 protected:
  void OnCommand(canopen::NmtCommand) noexcept override {
    co_lss_t* lss = co_nmt_get_lss(reinterpret_cast<co_nmt_t*>(nmt()));
    if (lss) co_lss_set_store_ind(lss, &Store, nullptr);
  }

 private:
  static int Store(co_lss_t*, co_unsigned8_t id, co_unsigned16_t, void*) {
    std::printf("lss_slave: stored node ID %u\n", id);
    std::fflush(stdout);
    return 0;
  }
};

}  // namespace

int main(int argc, char* argv[]) {
  if (argc < 3) {
    std::fprintf(stderr, "usage: %s <interface> <eds>\n", argv[0]);
    return 2;
  }
  io::IoGuard io_guard;
  io::Context ctx;
  io::Poll poll(ctx);
  ev::Loop loop(poll.get_poll());
  auto exec = loop.get_executor();
  io::Timer timer(poll, exec, CLOCK_MONOTONIC);
  io::CanController ctrl(argv[1]);
  io::CanChannel chan(poll, exec);
  chan.open(ctrl);
  io::CanChannel sniff(poll, exec);
  sniff.open(ctrl);

  LssSlave slave(timer, chan, argv[2], "", 0xFF);

  can_msg msg = CAN_MSG_INIT;
  std::function<void()> read_next = [&] {
    sniff.submit_read(&msg, nullptr, nullptr, exec, [&](int result, std::error_code ec) {
      if (ec) return;
      if (result == 1 && msg.id == 0x7E5 && msg.len >= 2 && msg.data[0] == 0x04 && msg.data[1] == 0x00)
        exec.post([&] { slave.ApplyPendingId(); });
      read_next();
    });
  };
  read_next();

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
