// The library's J1939 blocks: J1939_DM_READ and J1939_DM_CLEAR (spec
// j1939-plc-diagnostics) and the message blocks J1939_SEND, J1939_RECEIVE,
// J1939_REQUEST, J1939_ECU_INFO and J1939_FIND_ECU (spec j1939-plc-blocks),
// with the editor's glue (test/plc_sdo/bridge.py),
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
#include "j1939_plc_msgs.h"

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
  int send(uint32_t pgn, uint8_t destination, uint8_t priority, const uint8_t* data, size_t len) override {
    if (send_result) return send_result;
    sent.push_back(Sent{pgn, destination, std::vector<uint8_t>(data, data + len)});
    last_priority = priority;
    return 0;
  }
  // The program's blocks: filter changes, long sends and their end.
  std::vector<uint32_t> filter;
  bool filter_any = false;
  int filter_sets = 0;
  std::vector<Sent> long_sent;
  int events = 1;  // 1: the kernel reports sessions; -1: it does not
  std::vector<int> pending;  // 0 done, positive errno: aborted
  int send_result = 0;
  uint8_t last_priority = 0;
  int set_filter(const std::vector<uint32_t>& pgns, bool any) override {
    filter = pgns;
    filter_any = any;
    ++filter_sets;
    return 0;
  }
  int send_long(uint32_t pgn, uint8_t destination, uint8_t, const uint8_t* data, size_t len) override {
    long_sent.push_back(Sent{pgn, destination, std::vector<uint8_t>(data, data + len)});
    return 0;
  }
  int send_event(bool& aborted, int& error) override {
    if (events < 0) return -1;
    if (pending.empty()) return 0;
    error = pending.front();
    aborted = error != 0;
    pending.erase(pending.begin());
    return 1;
  }
  bool filtered(uint32_t pgn) const {
    for (uint32_t p : filter)
      if (p == pgn) return true;
    return false;
  }
  const Sent* last(uint32_t pgn) const {
    for (size_t i = sent.size(); i-- > 0;)
      if (sent[i].pgn == pgn) return &sent[i];
    return nullptr;
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
  Config cfg;
  J1939Image image;
  FakeSocket socket;
  J1939Engine engine;
  std::chrono::steady_clock::time_point t0 = std::chrono::steady_clock::now();
  int ms = 500;
  explicit Net(Config c = net_config(), bool claim = true) : cfg(std::move(c)), engine(cfg, image, socket) {
    image.build(cfg.j1939);
    J1939PlcJobs::instance().open({true, false});
    J1939PlcJobs::instance().set_attached(0, true);
    J1939PlcMsgs::instance().open({true, false});
    J1939PlcMsgs::instance().set_attached(0, true);
    engine.bus_up(t0);
    if (!claim) {
      ms = 0;
      return;
    }
    engine.tick(t0 + milliseconds(250));
    engine.tick(t0 + milliseconds(500));
  }
  ~Net() {
    J1939PlcJobs::instance().close();
    J1939PlcJobs::instance().set_attached(0, false);
    J1939PlcMsgs::instance().close();
    J1939PlcMsgs::instance().set_attached(0, false);
  }
  // One pass of the bus thread.
  void serve() {
    ms += 1;
    engine.tick(t0 + milliseconds(ms));
    engine.serve_plc(0, t0 + milliseconds(ms));
    engine.serve_plc_msgs(t0 + milliseconds(ms));
  }
  void message(uint32_t pgn, uint8_t source, std::vector<uint8_t> data, uint8_t destination = 255) {
    J1939Message m;
    m.pgn = pgn;
    m.source = source;
    m.destination = destination;
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

// ---- The message blocks (j1939-plc-blocks) ----

std::vector<uint8_t> bytes(size_t n, uint8_t first = 1) {
  std::vector<uint8_t> v(n);
  for (size_t i = 0; i < n; ++i) v[i] = static_cast<uint8_t>(first + i);
  return v;
}

TEST(j1939_send_short_and_long) {
  Net n;
  J1939_SEND_INST s;
  s.PGN = 65300;
  s.DESTINATION = 255;
  s.LENGTH = 8;
  for (unsigned i = 0; i < 8; ++i) s.DATA[i] = static_cast<uint8_t>(0x10 + i);
  s.EXECUTE = true;
  j1939_send_call(&s);
  CHECK(s.BUSY && !s.ERROR);
  n.serve();
  j1939_send_call(&s);
  const FakeSocket::Sent* m = n.socket.last(65300);
  CHECK(s.DONE && !s.BUSY && m && m->destination == 255 && m->data.size() == 8 && m->data[7] == 0x17);
  CHECK(n.socket.last_priority == 6);  // PRIORITY 0: the default 6
  s.EXECUTE = false;
  j1939_send_call(&s);
  CHECK(!s.DONE);
  // 40 bytes to address 0 (a PDU1 PGN): the long socket, done when the
  // session completes.
  J1939_SEND_INST l;
  l.PGN = 0xEF00;
  l.DESTINATION = 0;
  l.PRIORITY = 3;
  l.LENGTH = 40;
  for (unsigned i = 0; i < 40; ++i) l.DATA[i] = static_cast<uint8_t>(i);
  l.EXECUTE = true;
  j1939_send_call(&l);
  n.serve();
  j1939_send_call(&l);
  CHECK(l.BUSY && n.socket.long_sent.size() == 1 && n.socket.long_sent[0].destination == 0 &&
        n.socket.long_sent[0].data.size() == 40 && n.socket.long_sent[0].data[39] == 39);
  n.socket.pending.push_back(0);
  n.serve();
  j1939_send_call(&l);
  CHECK(l.DONE && !l.ERROR);
  // Aborted by the receiver: 14.
  l.EXECUTE = false;
  j1939_send_call(&l);
  l.EXECUTE = true;
  j1939_send_call(&l);
  n.serve();
  n.socket.pending.push_back(ECONNABORTED);
  n.serve();
  j1939_send_call(&l);
  CHECK(l.ERROR && l.ERROR_ID == CANWORKS_J1939_ERR_ABORTED);
}

TEST(j1939_send_long_without_session_reports) {
  Net n;
  n.socket.events = -1;
  J1939_SEND_INST l;
  l.PGN = 65300;
  l.DESTINATION = 255;
  l.LENGTH = 20;
  l.EXECUTE = true;
  j1939_send_call(&l);
  n.serve();
  j1939_send_call(&l);
  CHECK(l.DONE && n.socket.long_sent.size() == 1);
}

Config with_tx() {
  Config c = net_config();
  J1939Tx t;
  t.pgn = 65281;
  c.j1939.tx.push_back(t);
  return c;
}

TEST(j1939_send_refuses_owned_pgns) {
  Net n(with_tx());
  J1939_SEND_INST s;
  s.LENGTH = 8;
  s.DESTINATION = 255;
  const unsigned owned[] = {65281, 59904, 60928, 59392, 60416, 60160, 65226, 57088};
  for (unsigned pgn : owned) {
    s.PGN = pgn;
    s.EXECUTE = true;
    j1939_send_call(&s);
    n.serve();
    j1939_send_call(&s);
    CHECK(s.ERROR && s.ERROR_ID == CANWORKS_J1939_ERR_PROTOCOL);
    s.EXECUTE = false;
    j1939_send_call(&s);
  }
  // raw.program_override_protocol lets the tx and DM PGNs through, never the
  // transport protocol or the address claim.
  Config c = with_tx();
  c.raw.program_override_protocol = true;
  Net o(c);
  J1939_SEND_INST p;
  p.LENGTH = 8;
  p.DESTINATION = 255;
  p.PGN = 65281;
  p.EXECUTE = true;
  j1939_send_call(&p);
  o.serve();
  j1939_send_call(&p);
  CHECK(p.DONE);
  p.EXECUTE = false;
  j1939_send_call(&p);
  p.PGN = 60928;
  p.EXECUTE = true;
  j1939_send_call(&p);
  o.serve();
  j1939_send_call(&p);
  CHECK(p.ERROR && p.ERROR_ID == CANWORKS_J1939_ERR_PROTOCOL);
}

TEST(j1939_send_errors) {
  {
    // Still claiming: 11, nothing sent.
    Net n(net_config(), false);
    J1939_SEND_INST s;
    s.PGN = 65300;
    s.LENGTH = 8;
    s.EXECUTE = true;
    j1939_send_call(&s);
    n.serve();
    j1939_send_call(&s);
    CHECK(s.ERROR && s.ERROR_ID == CANWORKS_J1939_ERR_NO_ADDRESS && !n.socket.last(65300));
  }
  Net n;
  J1939_SEND_INST s;
  s.LENGTH = 1786;
  s.EXECUTE = true;
  j1939_send_call(&s);
  CHECK(s.ERROR && s.ERROR_ID == CANWORKS_J1939_ERR_INPUT);
  J1939_SEND_INST co;
  co.NETWORK = 1;
  co.EXECUTE = true;
  j1939_send_call(&co);
  CHECK(co.ERROR && co.ERROR_ID == CANWORKS_J1939_ERR_NOT_J1939);
  J1939_SEND_INST pgn;
  pgn.PGN = 0x40000;
  pgn.EXECUTE = true;
  j1939_send_call(&pgn);
  CHECK(pgn.ERROR && pgn.ERROR_ID == CANWORKS_J1939_ERR_INPUT);
  // A full transmit queue until the timeout: 6.
  n.socket.send_result = -ENOBUFS;
  J1939_SEND_INST q;
  q.PGN = 65300;
  q.LENGTH = 8;
  q.TIMEOUT = 50LL * 1000000;
  q.EXECUTE = true;
  j1939_send_call(&q);
  n.serve();
  n.ms += 60;
  n.serve();
  j1939_send_call(&q);
  CHECK(q.ERROR && q.ERROR_ID == CANWORKS_J1939_ERR_TIMEOUT);
}

TEST(j1939_receive_any_pgn) {
  Net n;
  J1939_RECEIVE_INST rx;
  rx.PGN = 65300;
  rx.ENABLE = true;
  j1939_receive_call(&rx);
  CHECK(rx.ACTIVE && !rx.ERROR && !rx.NEW);
  n.serve();  // the receiver is taken into use and the filter widened
  CHECK(n.socket.filtered(65300) && n.socket.filtered(kPgnDm1));
  n.message(65300, 0, bytes(40));
  n.message(65301, 0, bytes(8));  // another PGN
  j1939_receive_call(&rx);
  CHECK(rx.NEW && rx.RX_PGN == 65300 && rx.RX_SOURCE == 0 && rx.RX_DESTINATION == 255 && rx.RX_LENGTH == 40);
  CHECK(rx.RX_DATA[0] == 1 && rx.RX_DATA[39] == 40 && rx.QUEUED == 0 && rx.TIMESTAMP > 0);
  j1939_receive_call(&rx);
  CHECK(!rx.NEW && rx.RX_LENGTH == 40);
  // Our own messages and messages to another ECU are left out.
  n.message(65300, 128, bytes(8));
  n.message(0xEF00, 0, bytes(8), 7);
  j1939_receive_call(&rx);
  CHECK(!rx.NEW);
  // Overflow at DEPTH 4 (the default).
  for (int i = 0; i < 6; ++i) n.message(65300, 3, bytes(8, static_cast<uint8_t>(i)));
  int got = 0;
  j1939_receive_call(&rx);
  while (rx.NEW) {
    ++got;
    j1939_receive_call(&rx);
  }
  CHECK(got == 4 && rx.OVERFLOW && rx.DROPPED == 2 && rx.QUEUED == 0);
  // Disabled: closed, and the filter shrinks again.
  rx.ENABLE = false;
  j1939_receive_call(&rx);
  CHECK(!rx.ACTIVE);
  n.serve();
  CHECK(!n.socket.filtered(65300));
}

TEST(j1939_receive_filters) {
  Net n;
  J1939_RECEIVE_INST src;
  src.PGN = 0xEF00;
  src.SOURCE = 5;
  src.FILTER_SOURCE = true;
  src.ENABLE = true;
  J1939_RECEIVE_INST all;
  all.ANY = true;
  all.ALL_DESTINATIONS = true;
  all.DEPTH = 32;
  all.ENABLE = true;
  j1939_receive_call(&src);
  j1939_receive_call(&all);
  n.serve();
  CHECK(n.socket.filter_any);
  n.message(0xEF00, 4, bytes(8));
  n.message(0xEF00, 5, bytes(8), 128);
  n.message(0xEF00, 5, bytes(8), 9);  // to another ECU
  j1939_receive_call(&src);
  CHECK(src.NEW && src.RX_SOURCE == 5 && src.RX_DESTINATION == 128);
  j1939_receive_call(&src);
  CHECK(!src.NEW);
  int got = 0;
  for (j1939_receive_call(&all); all.NEW; j1939_receive_call(&all)) ++got;
  CHECK(got == 3);
  // New inputs while enabled: opened again with them.
  src.SOURCE = 4;
  j1939_receive_call(&src);
  n.serve();
  n.message(0xEF00, 4, bytes(8));
  j1939_receive_call(&src);
  CHECK(src.NEW && src.RX_SOURCE == 4);
  // Bus lost: ERROR_ID 7 while the receiver stays open.
  n.engine.bus_lost("test");
  j1939_receive_call(&src);
  CHECK(src.ACTIVE && src.ERROR && src.ERROR_ID == 7);
}

TEST(j1939_receivers_limit) {
  Net n;
  std::vector<J1939_RECEIVE_INST> rx(17);
  for (auto& r : rx) {
    r.PGN = 65300;
    r.ENABLE = true;
    j1939_receive_call(&r);
  }
  for (size_t i = 0; i < 16; ++i) CHECK(rx[i].ACTIVE);
  CHECK(!rx[16].ACTIVE && rx[16].ERROR && rx[16].ERROR_ID == CANWORKS_J1939_ERR_FULL);
  rx[0].ENABLE = false;
  j1939_receive_call(&rx[0]);
  j1939_receive_call(&rx[16]);  // tries again
  CHECK(rx[16].ACTIVE && !rx[16].ERROR);
}

TEST(j1939_request_answer_nack_timeout) {
  Net n;
  J1939_REQUEST_INST rq;
  rq.PGN = 65259;
  rq.DESTINATION = 0;
  rq.EXECUTE = true;
  j1939_request_call(&rq);
  n.serve();
  CHECK(n.socket.requests_to(0, 65259) == 1 && n.socket.filtered(65259));
  j1939_request_call(&rq);
  CHECK(rq.BUSY);
  n.message(65259, 3, bytes(8));  // another ECU's
  j1939_request_call(&rq);
  CHECK(rq.BUSY);
  n.message(65259, 0, bytes(30, 9));
  j1939_request_call(&rq);
  CHECK(rq.DONE && rq.SOURCE == 0 && rq.LENGTH == 30 && rq.DATA[0] == 9 && rq.DATA[29] == 38 && rq.ACK_CODE == 0);
  rq.EXECUTE = false;
  j1939_request_call(&rq);
  // NACK.
  rq.PGN = 65300;
  rq.EXECUTE = true;
  j1939_request_call(&rq);
  n.serve();
  n.message(kPgnAcknowledgement, 0, {1, 0xFF, 0xFF, 0xFF, 128, 0x14, 0xFF, 0x00});
  j1939_request_call(&rq);
  CHECK(rq.ERROR && rq.ERROR_ID == CANWORKS_J1939_ERR_NACK && rq.ACK_CODE == 1);
  rq.EXECUTE = false;
  j1939_request_call(&rq);
  // No answer.
  rq.DESTINATION = 7;
  rq.TIMEOUT = 100LL * 1000000;
  rq.EXECUTE = true;
  j1939_request_call(&rq);
  n.serve();
  n.ms += 110;
  n.serve();
  j1939_request_call(&rq);
  CHECK(rq.ERROR && rq.ERROR_ID == CANWORKS_J1939_ERR_TIMEOUT);
  rq.EXECUTE = false;
  j1939_request_call(&rq);
  // Global: done once sent.
  rq.DESTINATION = 255;
  rq.EXECUTE = true;
  j1939_request_call(&rq);
  n.serve();
  j1939_request_call(&rq);
  CHECK(rq.DONE && rq.LENGTH == 0 && n.socket.requests_to(255, 65300) == 1);
}

std::vector<uint8_t> name_bytes(uint64_t name) {
  std::vector<uint8_t> d(8);
  for (int k = 0; k < 8; ++k) d[k] = static_cast<uint8_t>(name >> (8 * k));
  return d;
}

TEST(j1939_ecu_info_and_find) {
  Net n;
  J1939_ECU_INFO_INST info;
  info.ENABLE = true;
  n.serve();
  j1939_ecu_info_call(&info);
  CHECK(info.VALID && info.STATE == 1 && info.ADDRESS == 128 && info.NAME == 77 && info.ECU_COUNT == 0);
  // An engine (function 0) at 3 and a transmission (function 3) at 5.
  const uint64_t engine = 0x8000000000000000ull | 1234;
  const uint64_t gearbox = (uint64_t(3) << 40) | 99;
  n.message(kPgnAddressClaimed, 5, name_bytes(gearbox));
  n.message(kPgnAddressClaimed, 3, name_bytes(engine));
  n.serve();
  j1939_ecu_info_call(&info);
  CHECK(info.ECU_COUNT == 2);
  J1939_FIND_ECU_INST f;
  f.NAME = uint64_t(3) << 40;
  f.MASK = uint64_t(0xFF) << 40;
  f.ENABLE = true;
  j1939_find_ecu_call(&f);
  CHECK(f.VALID && f.FOUND && f.ADDRESS == 5 && f.FOUND_NAME == gearbox && f.COUNT == 1);
  f.NAME = 0;
  j1939_find_ecu_call(&f);
  CHECK(f.FOUND && f.ADDRESS == 3 && f.COUNT == 1);
  f.MASK = 0;  // every ECU matches: the lowest address
  j1939_find_ecu_call(&f);
  CHECK(f.FOUND && f.ADDRESS == 3 && f.COUNT == 2);
  f.NAME = uint64_t(7) << 40;
  f.MASK = uint64_t(0xFF) << 40;
  j1939_find_ecu_call(&f);
  CHECK(f.VALID && !f.FOUND && f.ADDRESS == 254);
  J1939_ECU_INFO_INST co;
  co.NETWORK = 1;
  co.ENABLE = true;
  j1939_ecu_info_call(&co);
  CHECK(!co.VALID && co.ERROR && co.ERROR_ID == CANWORKS_J1939_ERR_NOT_J1939);
}

TEST(j1939_tables_v1_and_v2) {
  const auto* v1 = static_cast<const canworks_j1939_api_v1*>(canworks_j1939_api_table(1));
  const auto* v2 = static_cast<const canworks_j1939_api_v2*>(canworks_j1939_api_table(2));
  CHECK(v1 && v1->size == sizeof(canworks_j1939_api_v1));
  CHECK(v2 && v2->size == sizeof(canworks_j1939_api_v2) && v2->dm_read_start == v1->dm_read_start);
  CHECK(canworks_j1939_api_table(3) == nullptr);
  CHECK(J1939PlcMsgs::instance().take_unknown_version() == 3);
}

TEST(j1939_message_blocks_plc_stop) {
  J1939_RECEIVE_INST rx;
  J1939_REQUEST_INST rq;
  {
    Net n;
    rx.PGN = 65300;
    rx.ENABLE = true;
    j1939_receive_call(&rx);
    rq.PGN = 65300;
    rq.EXECUTE = true;
    j1939_request_call(&rq);
    n.serve();
  }  // the PLC stops
  j1939_receive_call(&rx);
  j1939_request_call(&rq);
  CHECK(rx.ERROR && rx.ERROR_ID == CANWORKS_J1939_ERR_CANCELLED && !rx.ACTIVE);
  CHECK(rq.ERROR && rq.ERROR_ID == CANWORKS_J1939_ERR_CANCELLED);
}

}  // namespace

int main(int argc, char** argv) { return check::run_all(argc, argv); }
