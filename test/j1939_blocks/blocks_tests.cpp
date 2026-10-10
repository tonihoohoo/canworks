// The library's J1939_DM_READ and J1939_DM_CLEAR blocks (spec
// j1939-plc-diagnostics) with the editor's glue (test/plc_sdo/bridge.py),
// against the plugin's job table and a J1939 engine on a fake socket in the
// same process (-DJ1939_DM_TEST_ENTRY=canworks_j1939_api_table). The test
// plays the bus thread by hand.

#include <cerrno>
#include <chrono>
#include <string>
#include <vector>

#include "c_blocks.h"
#include "check.hpp"
#include "dm.h"
#include "j1939_network.h"
#include "j1939_plc_api.h"
#include "j1939_plc_jobs.h"

using namespace canopen_plugin;
using std::chrono::milliseconds;

// The SDO blocks are linked in with the others; this test has no master.
extern "C" const void* canopen_plc_api_test(uint32_t) { return nullptr; }
extern "C" const void* canopen_plc_nmt_api_test(uint32_t) { return nullptr; }

namespace {

class FakeSocket : public J1939Socket {
 public:
  struct Sent {
    uint32_t pgn;
    uint8_t destination;
    std::vector<uint8_t> data;
  };
  std::vector<Sent> sent;
  int open(const std::string&, const std::vector<uint32_t>&) override { return 0; }
  int bind(uint64_t, uint8_t) override { return 0; }
  void close() override {}
  int fd() const override { return -1; }
  int receive(J1939Message&) override { return -EAGAIN; }
  int send(uint32_t pgn, uint8_t destination, uint8_t, const uint8_t* data, size_t len) override {
    sent.push_back(Sent{pgn, destination, std::vector<uint8_t>(data, data + len)});
    return 0;
  }
  size_t requests_to(uint8_t destination, uint32_t pgn) const {
    size_t n = 0;
    for (const auto& s : sent)
      if (s.pgn == kPgnRequest && s.destination == destination && s.data.size() == 3 &&
          (s.data[0] | uint32_t(s.data[1]) << 8 | uint32_t(s.data[2]) << 16) == pgn)
        ++n;
    return n;
  }
};

Config net_config() {
  Config cfg;
  cfg.protocol = Protocol::J1939;
  cfg.adapter.interface = "vcan0";
  cfg.j1939.ecu.name.identity_number = 77;
  cfg.j1939.ecu.address = 128;
  return cfg;
}

// Network 0 is J1939 (claimed at 128), network 1 CANopen.
struct Net {
  Config cfg = net_config();
  J1939Image image;
  FakeSocket socket;
  J1939Engine engine{cfg, image, socket};
  std::chrono::steady_clock::time_point t0 = std::chrono::steady_clock::now();
  int ms = 500;
  Net() {
    image.build(cfg.j1939);
    J1939PlcJobs::instance().open({true, false});
    J1939PlcJobs::instance().set_attached(0, true);
    engine.bus_up(t0);
    engine.tick(t0 + milliseconds(250));
    engine.tick(t0 + milliseconds(500));
  }
  ~Net() {
    J1939PlcJobs::instance().close();
    J1939PlcJobs::instance().set_attached(0, false);
  }
  // One pass of the bus thread.
  void serve() {
    ms += 1;
    engine.tick(t0 + milliseconds(ms));
    engine.serve_plc(0, t0 + milliseconds(ms));
  }
  void message(uint32_t pgn, uint8_t source, std::vector<uint8_t> data) {
    J1939Message m;
    m.pgn = pgn;
    m.source = source;
    m.destination = 255;
    m.data = std::move(data);
    ms += 1;
    engine.on_message(m, t0 + milliseconds(ms));
  }
};

TEST(j1939_dm_read_dm1) {
  Net n;
  n.message(kPgnDm1, 0, {0x14, 0xDF, 0x00, 0xF0, 0xE3, 0x02, 0x01, 0xF0, 0xE1, 0x01});
  J1939_DM_READ_INST rd;
  for (auto& v : rd.DTCS) v = 0xDEAD;
  rd.EXECUTE = true;
  j1939_dm_read_call(&rd);
  CHECK(rd.BUSY && !rd.DONE && !rd.ERROR);
  size_t sent = n.socket.sent.size();
  n.ms += 120;
  n.serve();
  j1939_dm_read_call(&rd);
  CHECK(rd.DONE && !rd.BUSY && !rd.ERROR && rd.COUNT == 2 && rd.LAMPS == 0x14 && rd.FLASH == 0xDF);
  CHECK(rd.DTCS[0] == 35647488u && rd.DTCS[1] == 17821697u && rd.DTCS[2] == 0 && rd.DTCS[31] == 0);
  CHECK(static_cast<long long>(rd.AGE) >= 120LL * 1000000);
  CHECK(n.socket.sent.size() == sent);  // nothing sent for a DM1 read
  rd.EXECUTE = false;
  j1939_dm_read_call(&rd);
  CHECK(!rd.DONE);
}

TEST(j1939_dm_read_dm2) {
  Net n;
  J1939_DM_READ_INST rd;
  rd.SOURCE = 0;
  rd.PREVIOUS = true;
  rd.EXECUTE = true;
  j1939_dm_read_call(&rd);
  n.serve();
  CHECK(n.socket.requests_to(0, kPgnDm2) == 1);
  j1939_dm_read_call(&rd);
  CHECK(rd.BUSY);
  n.message(kPgnDm2, 0, {0x04, 0xFF, 0x00, 0xF0, 0xE3, 0x02, 0xFF, 0xFF});
  j1939_dm_read_call(&rd);
  CHECK(rd.DONE && rd.COUNT == 1 && rd.DTCS[0] == 35647488u && rd.DTCS[1] == 0);
}

TEST(j1939_dm_clear_ack_and_nack) {
  Net n;
  J1939_DM_CLEAR_INST cl;
  cl.DESTINATION = 0;
  cl.PREVIOUS_ONLY = true;
  cl.EXECUTE = true;
  j1939_dm_clear_call(&cl);
  n.serve();
  CHECK(n.socket.requests_to(0, kPgnDm3) == 1);
  n.message(kPgnAcknowledgement, 0, {0, 0xFF, 0xFF, 0xFF, 128, 0xCC, 0xFE, 0x00});
  j1939_dm_clear_call(&cl);
  CHECK(cl.DONE && !cl.ERROR);
  cl.EXECUTE = false;
  j1939_dm_clear_call(&cl);
  // DM11, refused.
  cl.PREVIOUS_ONLY = false;
  cl.EXECUTE = true;
  j1939_dm_clear_call(&cl);
  n.serve();
  CHECK(n.socket.requests_to(0, kPgnDm11) == 1);
  n.message(kPgnAcknowledgement, 0, {1, 0xFF, 0xFF, 0xFF, 128, 0xD3, 0xFE, 0x00});
  j1939_dm_clear_call(&cl);
  CHECK(cl.ERROR && cl.ERROR_ID == CANWORKS_J1939_ERR_NACK);
  cl.EXECUTE = false;
  j1939_dm_clear_call(&cl);
  // Global: done once sent.
  cl.DESTINATION = 255;
  cl.EXECUTE = true;
  j1939_dm_clear_call(&cl);
  n.serve();
  j1939_dm_clear_call(&cl);
  CHECK(cl.DONE && n.socket.requests_to(255, kPgnDm11) == 1);
}

TEST(j1939_dm_block_errors) {
  Net n;
  // A CANopen network: 10, nothing sent.
  J1939_DM_READ_INST co;
  co.NETWORK = 1;
  co.EXECUTE = true;
  size_t sent = n.socket.sent.size();
  j1939_dm_read_call(&co);
  CHECK(co.ERROR && co.ERROR_ID == CANWORKS_J1939_ERR_NOT_J1939 && n.socket.sent.size() == sent);
  // No such network, invalid inputs.
  J1939_DM_READ_INST none;
  none.NETWORK = 5;
  none.EXECUTE = true;
  j1939_dm_read_call(&none);
  CHECK(none.ERROR_ID == CANWORKS_J1939_ERR_NETWORK);
  J1939_DM_READ_INST bad;
  bad.SOURCE = 254;
  bad.EXECUTE = true;
  j1939_dm_read_call(&bad);
  CHECK(bad.ERROR_ID == CANWORKS_J1939_ERR_INPUT);
  J1939_DM_CLEAR_INST badc;
  badc.DESTINATION = 254;
  badc.EXECUTE = true;
  j1939_dm_clear_call(&badc);
  CHECK(badc.ERROR_ID == CANWORKS_J1939_ERR_INPUT);
  // An ECU never seen: 13.
  J1939_DM_READ_INST unseen;
  unseen.SOURCE = 7;
  unseen.EXECUTE = true;
  j1939_dm_read_call(&unseen);
  n.serve();
  j1939_dm_read_call(&unseen);
  CHECK(unseen.ERROR && unseen.ERROR_ID == CANWORKS_J1939_ERR_NO_DM1);
  // No answer within TIMEOUT (T#0s: 1 s).
  J1939_DM_READ_INST slow;
  slow.SOURCE = 9;
  slow.PREVIOUS = true;
  slow.TIMEOUT = 200LL * 1000000;
  slow.EXECUTE = true;
  j1939_dm_read_call(&slow);
  n.serve();
  n.ms += 200;
  n.serve();
  j1939_dm_read_call(&slow);
  CHECK(slow.ERROR && slow.ERROR_ID == CANWORKS_J1939_ERR_TIMEOUT);
}

TEST(j1939_dm_blocks_from_two_tasks) {
  Net n;
  // Two instances for one address: the second gets 5 and the first is not disturbed.
  J1939_DM_READ_INST a, b, c;
  a.SOURCE = b.SOURCE = 0;
  c.SOURCE = 3;
  a.PREVIOUS = b.PREVIOUS = c.PREVIOUS = true;
  a.EXECUTE = b.EXECUTE = c.EXECUTE = true;
  j1939_dm_read_call(&a);
  j1939_dm_read_call(&b);
  j1939_dm_read_call(&c);
  n.serve();
  j1939_dm_read_call(&a);
  j1939_dm_read_call(&b);
  j1939_dm_read_call(&c);
  CHECK(a.BUSY && b.ERROR && b.ERROR_ID == CANWORKS_J1939_ERR_PENDING && c.BUSY);
  n.message(kPgnDm2, 3, {0x00, 0xFF, 0x00, 0x00, 0x00, 0x00, 0xFF, 0xFF});
  n.message(kPgnDm2, 0, {0x04, 0xFF, 0x00, 0xF0, 0xE3, 0x02, 0xFF, 0xFF});
  j1939_dm_read_call(&a);
  j1939_dm_read_call(&c);
  CHECK(a.DONE && a.COUNT == 1 && c.DONE && c.COUNT == 0);
}

TEST(j1939_dm_plc_stop_cancels) {
  J1939_DM_READ_INST rd;
  {
    Net n;
    rd.SOURCE = 0;
    rd.PREVIOUS = true;
    rd.EXECUTE = true;
    j1939_dm_read_call(&rd);
    n.serve();
  }  // the PLC stops
  j1939_dm_read_call(&rd);
  CHECK(rd.ERROR && rd.ERROR_ID == CANWORKS_J1939_ERR_CANCELLED);
  // A new edge while stopped: 1.
  rd.EXECUTE = false;
  j1939_dm_read_call(&rd);
  rd.EXECUTE = true;
  j1939_dm_read_call(&rd);
  CHECK(rd.ERROR && rd.ERROR_ID == CANWORKS_J1939_ERR_NOT_RUNNING);
}

}  // namespace

int main(int argc, char** argv) { return check::run_all(argc, argv); }
