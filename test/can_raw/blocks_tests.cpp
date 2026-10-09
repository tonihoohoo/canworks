// The library's CAN_* function blocks (spec can-plc-frames) with the
// editor's glue (test/plc_sdo/bridge.py), against the plugin's frame port in
// the same process (-DCAN_FRAMES_TEST_ENTRY=canworks_can_api_table). The test plays
// the raw I/O thread by hand.

#include <cstring>

#include "c_blocks.h"
#include "can/raw/plc_frames.h"
#include "check.hpp"

using namespace canworks_raw;

namespace {

struct Net {
  PlcPort port{0};
  explicit Net(PortRules rules = {}) {
    port.set_rules(std::move(rules));
    port.set_running(true);
    set_port(0, &port);
  }
  ~Net() { set_port(0, nullptr); }
};

canworks_can_frame frame(uint32_t id, std::initializer_list<uint8_t> data) {
  canworks_can_frame f{};
  f.id = id;
  f.dlc = static_cast<uint8_t>(data.size());
  unsigned i = 0;
  for (uint8_t b : data) f.data[i++] = b;
  return f;
}

}  // namespace

TEST(can_send_handshake) {
  Net n;
  CAN_SEND_INST tx;
  tx.ID = 0x510;
  tx.DLC = 2;
  tx.DATA[0] = 1;
  tx.DATA[1] = 2;
  tx.EXECUTE = true;
  can_send_call(&tx);
  CHECK(tx.BUSY && !tx.DONE && !tx.ERROR);
  canworks_can_frame out{};
  uint32_t tag = 0;
  CHECK(n.port.next_tx(out, tag));
  CHECK(out.id == 0x510 && out.dlc == 2 && out.data[1] == 2);
  n.port.tx_written(tag, false);
  // A second edge while busy is ignored.
  tx.EXECUTE = false;
  can_send_call(&tx);
  tx.EXECUTE = true;
  can_send_call(&tx);
  CHECK(!n.port.next_tx(out, tag));
  n.port.own_echo(out);
  can_send_call(&tx);
  CHECK(tx.DONE && !tx.BUSY);
  tx.EXECUTE = false;
  can_send_call(&tx);
  CHECK(!tx.DONE);  // shown for one call after EXECUTE fell
}

TEST(can_send_errors) {
  PortRules rules;
  rules.owned = [](uint32_t id, bool) { return id == 0x205; };
  Net n(rules);
  CAN_SEND_INST tx;
  tx.ID = 0x205;
  tx.DLC = 1;
  tx.EXECUTE = true;
  can_send_call(&tx);
  CHECK(tx.ERROR && tx.ERROR_ID == CANWORKS_CAN_ERR_PROTOCOL);
  CAN_SEND_INST t2;
  t2.NETWORK = 4;
  t2.EXECUTE = true;
  can_send_call(&t2);
  CHECK(t2.ERROR && t2.ERROR_ID == CANWORKS_CAN_ERR_NETWORK);
  CAN_SEND_INST t3;
  t3.DLC = 9;
  t3.EXECUTE = true;
  can_send_call(&t3);
  CHECK(t3.ERROR && t3.ERROR_ID == CANWORKS_CAN_ERR_INPUT);
}

TEST(can_send_cyclic) {
  Net n;
  CAN_SEND_CYCLIC_INST cy;
  cy.ID = 0x300;
  cy.DLC = 1;
  cy.DATA[0] = 5;
  cy.PERIOD = 10LL * 1000000;  // T#10ms
  cy.ENABLE = true;
  can_send_cyclic_call(&cy);
  CHECK(cy.ACTIVE && !cy.ERROR);
  canworks_can_frame out[2];
  uint8_t jobs[2];
  CHECK(n.port.cyclic_due(1000, out, jobs, 2) == 1);
  n.port.cyclic_sent(jobs[0]);
  cy.DATA[0] = 6;
  can_send_cyclic_call(&cy);
  CHECK(cy.COUNT == 1);
  CHECK(n.port.cyclic_due(11000, out, jobs, 2) == 1);
  CHECK(out[0].data[0] == 6);
  cy.ENABLE = false;
  can_send_cyclic_call(&cy);
  CHECK(!cy.ACTIVE);
  CHECK(n.port.cyclic_due(50000, out, jobs, 2) == 0);
  CAN_SEND_CYCLIC_INST bad;
  bad.ENABLE = true;  // PERIOD T#0s
  can_send_cyclic_call(&bad);
  CHECK(bad.ERROR && bad.ERROR_ID == CANWORKS_CAN_ERR_INPUT);
}

TEST(can_receive_drain_in_one_scan) {
  Net n;
  CAN_RECEIVE_INST rx;
  rx.ID = 0x600;
  rx.MASK = 0x780;
  rx.ENABLE = true;
  can_receive_call(&rx);
  CHECK(rx.ACTIVE && !rx.NEW);
  for (uint8_t i = 0; i < 5; ++i) n.port.on_frame(frame(0x601 + i, {i}));
  n.port.on_frame(frame(0x705, {9}));
  int seen = 0;
  can_receive_call(&rx);
  while (rx.NEW) {
    CHECK(rx.RX_ID == 0x601u + seen);
    CHECK(rx.RX_DATA[0] == seen);
    ++seen;
    can_receive_call(&rx);
  }
  CHECK(seen == 5);
  CHECK(rx.QUEUED == 0);
}

TEST(can_receive_exact_and_any) {
  Net n;
  CAN_RECEIVE_INST exact;  // MASK 0: every identifier bit
  exact.ID = 0x123;
  exact.ENABLE = true;
  can_receive_call(&exact);
  CAN_RECEIVE_INST any;
  any.ANY = true;
  any.ENABLE = true;
  can_receive_call(&any);
  n.port.on_frame(frame(0x123, {1}));
  n.port.on_frame(frame(0x124, {2}));
  can_receive_call(&exact);
  CHECK(exact.NEW && exact.RX_ID == 0x123);
  can_receive_call(&exact);
  CHECK(!exact.NEW);
  can_receive_call(&any);
  can_receive_call(&any);
  CHECK(any.NEW && any.RX_ID == 0x124);
}

TEST(can_receive_overflow_and_plc_stop) {
  Net n;
  CAN_RECEIVE_INST rx;
  rx.ID = 0x10;
  rx.DEPTH = 4;
  rx.ENABLE = true;
  can_receive_call(&rx);
  for (uint8_t i = 0; i < 6; ++i) n.port.on_frame(frame(0x10, {i}));
  can_receive_call(&rx);
  CHECK(rx.NEW && rx.OVERFLOW && rx.DROPPED == 2 && rx.QUEUED == 3);
  n.port.cancel_all();
  can_receive_call(&rx);
  CHECK(rx.ERROR && rx.ERROR_ID == CANWORKS_CAN_ERR_CANCELLED && !rx.ACTIVE);
}

TEST(can_bus_info) {
  Net n;
  canworks_can_bus_info b{};
  b.state = 1;
  b.rx_errors = 96;
  n.port.publish_bus(b);
  CAN_BUS_INFO_INST info;
  can_bus_info_call(&info);
  CHECK(info.STATE == 1 && info.RX_ERRORS == 96 && !info.ERROR);
  info.NETWORK = 7;
  can_bus_info_call(&info);
  CHECK(info.ERROR && info.ERROR_ID == CANWORKS_CAN_ERR_NETWORK && info.STATE == 4);
}

int main(int argc, char** argv) { return check::run_all(argc, argv); }
