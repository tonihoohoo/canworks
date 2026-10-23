// mailbox_tests.cpp - the bridge's mailboxes (modbus-bridge-mailboxes) on a
// scripted backend: the request handshake, chunks, the receive mailbox with
// its batches, acknowledgement and stall rule, cyclic jobs and their
// keepalive, and ending everything when the link stops.

#include <chrono>
#include <cstring>
#include <deque>
#include <map>
#include <string>
#include <vector>

#include "byte_image.h"
#include "check.hpp"
#include "mailboxes.h"

using namespace canworks_bridge;
using Clock = std::chrono::steady_clock;

#define EXPECT(cond)                                                    \
  do {                                                                  \
    if (!(cond)) {                                                      \
      std::printf("  %s:%d: expected %s\n", __FILE__, __LINE__, #cond); \
      ++check::failures();                                              \
    }                                                                   \
  } while (0)

namespace {

// A backend whose operations end after `polls` polls with what the test set.
struct FakeBackend : MailboxBackend {
  struct Job : MbJob {
    FakeBackend* b;
    MbAnswer answer;
    int polls;
    bool* cancelled;
    bool poll(MbAnswer& out) override {
      if (polls-- > 0) return false;
      out = answer;
      return true;
    }
    void cancel() override { *cancelled = true; }
  };
  int polls = 1;
  std::vector<MbCall> calls;
  MbAnswer next;  // what the next operation ends with
  bool cancelled = false;
  std::unique_ptr<MbJob> start(const MbCall& c, MbAnswer& now) override {
    calls.push_back(c);
    if (c.op == kOpFindEcu) {
      now = next;
      return nullptr;
    }
    std::unique_ptr<Job> j(new Job);
    j->b = this;
    j->answer = next;
    j->polls = polls;
    j->cancelled = &cancelled;
    return std::move(j);
  }
  // Receivers: queues by handle.
  std::map<uint32_t, std::deque<RxRecord>> rx;
  std::map<uint32_t, RxSpec> specs;
  uint32_t next_rx = 1;
  std::vector<uint32_t> closed;
  uint32_t rx_open(const RxSpec& s, uint8_t&) override {
    specs[next_rx] = s;
    rx[next_rx];
    return next_rx++;
  }
  int rx_read(uint32_t h, RxRecord& rec, uint8_t& error) override {
    auto it = rx.find(h);
    if (it == rx.end()) {
      error = 8;
      return -1;
    }
    if (it->second.empty()) return 0;
    rec = it->second.front();
    it->second.pop_front();
    return 1;
  }
  void rx_close(uint32_t h) override {
    rx.erase(h);
    closed.push_back(h);
  }
  // Cyclic jobs.
  std::map<uint32_t, CyclicFrame> cyc;
  uint32_t next_cyc = 1;
  std::vector<uint32_t> stopped;
  uint32_t cyc_start(uint8_t, const CyclicFrame& f, uint8_t&) override {
    cyc[next_cyc] = f;
    return next_cyc++;
  }
  bool cyc_update(uint32_t h, const CyclicFrame* f, uint32_t& count, uint8_t&) override {
    if (!cyc.count(h)) return false;
    if (f) cyc[h] = *f;
    count = 7;
    return true;
  }
  void cyc_stop(uint32_t h) override {
    cyc.erase(h);
    stopped.push_back(h);
  }
  bool net_info(unsigned n, NetInfo& out) override {
    out.can_state = 0;
    out.bus_load = static_cast<uint8_t>(10 + n);
    out.rx_count = 0x12345;
    out.j1939 = n == 1;
    out.j1939_state = 1;
    out.address = 128;
    out.name = 0x0102030405060708ull;
    out.ecu_count = 3;
    return true;
  }
  bool has_network(unsigned n) const override { return n < 2; }
};

struct Rig {
  MailboxLayout layout;
  FakeBackend backend;
  std::unique_ptr<Mailboxes> mb;
  std::vector<uint8_t> out, in;
  Clock::time_point now = Clock::now();
  uint16_t counter[kMaxRequestMailboxes] = {};
  explicit Rig(unsigned requests = 1, unsigned jobs = 2, unsigned rx_blocks = 1) {
    layout.requests = requests;
    layout.receive = true;
    layout.receive_blocks = rx_blocks;
    layout.info_networks = 2;
    layout.cyclic_jobs = jobs;
    layout.in_base = 100;
    layout.out_base = 40;
    out.assign(layout.out_base + layout.output_bytes(), 0);
    in.assign(layout.in_base + layout.input_bytes(), 0);
    mb.reset(new Mailboxes(layout, backend));
    step();
  }
  void step(int ms = 1) {
    now += std::chrono::milliseconds(ms);
    mb->service(out.data(), in.data(), now);
  }
  uint16_t req_word(unsigned m, unsigned w) { return get_be16(&out[layout.request(m) + 2 * w]); }
  void set_req(unsigned m, unsigned w, uint16_t v) { put_be16(&out[layout.request(m) + 2 * w], v); }
  uint16_t rsp(unsigned m, unsigned w) { return get_be16(&in[layout.response(m) + 2 * w]); }
  uint8_t state(unsigned m) { return in[layout.response(m) + 2]; }
  uint8_t error(unsigned m) { return in[layout.response(m) + 3]; }
  // Writes one request (new counter), with `data` inline.
  void call(unsigned m, uint8_t op, uint8_t network, std::vector<uint16_t> args,
            const std::vector<uint8_t>& data = {}) {
    std::memset(&out[layout.request(m)], 0, kMbBytes);
    set_req(m, 0, ++counter[m]);
    out[layout.request(m) + 2] = op;
    out[layout.request(m) + 3] = network;
    for (size_t i = 0; i < args.size(); ++i) set_req(m, 2 + static_cast<unsigned>(i), args[i]);
    for (size_t i = 0; i < data.size() && i < kMbChunk; ++i) out[layout.request(m) + 16 + i] = data[i];
  }
  // Steps until the response echoes the counter and is not busy.
  bool wait(unsigned m, int max = 20) {
    for (int i = 0; i < max; ++i) {
      step();
      if (rsp(m, 0) == counter[m] && state(m) != kMbBusy) return true;
    }
    return false;
  }
  std::vector<uint8_t> data(unsigned m, size_t n) {
    return std::vector<uint8_t>(in.begin() + layout.response(m) + 16, in.begin() + layout.response(m) + 16 + n);
  }
  uint16_t rx_word(unsigned w) { return get_be16(&in[layout.receive_block() + 2 * w]); }
  void ack(uint16_t seq, uint32_t pending) {
    put_be16(&out[layout.ack()], seq);
    put_be16(&out[layout.ack() + 2], static_cast<uint16_t>(pending >> 16));
    put_be16(&out[layout.ack() + 4], static_cast<uint16_t>(pending));
  }
};

RxRecord can_rec(uint32_t id, uint64_t t, uint8_t b0 = 0) {
  RxRecord r;
  r.id = id;
  r.dlc = 2;
  r.time_us = t;
  r.data = {b0, 2, 0, 0, 0, 0, 0, 0};
  return r;
}

}  // namespace

TEST(layout_sizes) {
  MailboxLayout l;
  l.requests = 1;
  l.receive = true;
  l.info_networks = 2;
  l.cyclic_jobs = 4;
  EXPECT(l.input_bytes() == 144 + 240 + 72 + 2 + 32);
  EXPECT(l.output_bytes() == 144 + 6 + 8);
  l.receive_blocks = 2;
  EXPECT(l.input_bytes() == 144 + 480 + 72 + 2 + 32);
  EXPECT(l.info(0) == 144 + 480 && l.output_bytes() == 144 + 6 + 8);
}

TEST(record_sizes) {
  std::vector<uint16_t> w;
  RxRecord rec = can_rec(0x123, 77);
  encode_record(3, kRxCan, rec, false, w);
  EXPECT(w.size() == 10 && record_words(kRxCan) == 10);
  EXPECT(w[3] == 0 && w[4] == 0x123 && w[5] == 2 && w[6] == 0x0002);
  w.clear();
  encode_record(3, kRxJ1939, rec, false, w);
  EXPECT(w.size() == 12 && record_words(kRxJ1939) == 12);
  w.clear();
  rec.node = 5;
  encode_record(3, kRxEmcy, rec, false, w);
  EXPECT(w.size() == 12 && record_words(kRxEmcy) == 12);
  EXPECT(w[6] == 77 && w[7] >> 8 == 5);  // EMCY keeps its own time
}

TEST(request_runs_once_per_counter) {
  Rig r;
  r.call(0, kOpCanSend, 0, {0, 0x510, 2, 100}, {1, 2});
  EXPECT(r.wait(0));
  EXPECT(r.state(0) == kMbDone);
  EXPECT(r.backend.calls.size() == 1);
  EXPECT(r.backend.calls[0].a[1] == 0x510 && r.backend.calls[0].data.size() == 8);
  EXPECT(r.backend.calls[0].data[0] == 1 && r.backend.calls[0].data[1] == 2);
  // The same request written again starts nothing.
  for (int i = 0; i < 10; ++i) r.step();
  EXPECT(r.backend.calls.size() == 1);
}

TEST(restart_does_not_replay_the_last_request) {
  Rig r;
  r.call(0, kOpCanSend, 0, {0, 0x510, 2, 100}, {1, 2});
  EXPECT(r.wait(0));
  EXPECT(r.backend.calls.size() == 1);
  // A new bridge sees the PLC's last request still in the registers.
  r.mb.reset(new Mailboxes(r.layout, r.backend));
  for (int i = 0; i < 5; ++i) r.step();
  EXPECT(r.backend.calls.size() == 1);
  EXPECT(r.rsp(0, 0) == r.counter[0] && r.state(0) == kMbError && r.error(0) == 8);
  // The next request runs.
  r.call(0, kOpCanSend, 0, {0, 0x511, 2, 100}, {3, 4});
  EXPECT(r.wait(0));
  EXPECT(r.state(0) == kMbDone && r.backend.calls.size() == 2);
}

TEST(operation_none_does_nothing) {
  Rig r;
  r.call(0, kOpNone, 0, {});
  r.step();
  r.step();
  EXPECT(r.backend.calls.empty());
  EXPECT(r.rsp(0, 0) == r.counter[0] && r.state(0) == kMbIdle);
}

TEST(error_and_results_pass_through) {
  Rig r;
  r.backend.next.error = 1;
  r.backend.next.r[2] = 0x0609;
  r.backend.next.r[3] = 0x0030;
  r.call(0, kOpSdoRead, 0, {5 << 8 | 0, 0x2000, 3 << 8, 500});
  EXPECT(r.wait(0));
  EXPECT(r.state(0) == kMbError && r.error(0) == 1);
  EXPECT(r.rsp(0, 4) == 0x0609 && r.rsp(0, 5) == 0x0030);
}

TEST(unknown_network) {
  Rig r;
  r.call(0, kOpSdoRead, 7, {5 << 8, 0x1008, 3 << 8, 500});
  EXPECT(r.wait(0));
  EXPECT(r.state(0) == kMbError && r.error(0) == 6);
  r.call(0, kOpCanSend, 7, {0, 0x100, 1, 0});
  EXPECT(r.wait(0));
  EXPECT(r.error(0) == 2);
}

TEST(long_read_in_chunks) {
  Rig r;
  for (int i = 0; i < 300; ++i) r.backend.next.data.push_back(static_cast<uint8_t>(i));
  r.backend.next.r[1] = 300;
  r.call(0, kOpSdoRead, 0, {5 << 8, 0x1008, 3 << 8, 500});
  EXPECT(r.wait(0));
  EXPECT(r.rsp(0, 3) == 300);
  EXPECT(r.data(0, 128)[127] == 127);
  r.call(0, kOpFetch, 0, {128});
  EXPECT(r.wait(0));
  EXPECT(r.state(0) == kMbDone && r.rsp(0, 2) == 300 && r.data(0, 1)[0] == 128);
  r.call(0, kOpFetch, 0, {256});
  EXPECT(r.wait(0));
  EXPECT(r.data(0, 1)[0] == static_cast<uint8_t>(256) && r.data(0, 44)[43] == static_cast<uint8_t>(299));
  // Past the end.
  r.call(0, kOpFetch, 0, {400});
  EXPECT(r.wait(0));
  EXPECT(r.state(0) == kMbError);
}

TEST(long_write_from_staging) {
  Rig r;
  std::vector<uint8_t> chunk(128);
  for (unsigned c = 0; c < 5; ++c) {
    for (unsigned i = 0; i < 128; ++i) chunk[i] = static_cast<uint8_t>(c * 128 + i);
    r.call(0, kOpStage, 0, {static_cast<uint16_t>(c * 128), static_cast<uint16_t>(c == 4 ? 88 : 128)}, chunk);
    EXPECT(r.wait(0));
    EXPECT(r.state(0) == kMbDone);
  }
  r.call(0, kOpSdoWrite, 0, {5 << 8, 0x2000, 3 << 8, 500, 600});
  EXPECT(r.wait(0));
  EXPECT(r.backend.calls.size() == 1 && r.backend.calls[0].data.size() == 600);
  EXPECT(r.backend.calls[0].data[599] == static_cast<uint8_t>(599));
  // The staging buffer is gone after the write.
  r.call(0, kOpSdoWrite, 0, {5 << 8, 0x2000, 3 << 8, 500, 600});
  EXPECT(r.wait(0));
  EXPECT(r.state(0) == kMbError && r.error(0) == 6);
}

TEST(two_mailboxes_run_in_parallel) {
  Rig r(2);
  r.backend.polls = 5;
  r.call(0, kOpCanSend, 0, {0, 0x100, 1, 0});
  r.call(1, kOpCanSend, 0, {0, 0x101, 1, 0});
  r.step();
  EXPECT(r.state(0) == kMbBusy && r.state(1) == kMbBusy);
  EXPECT(r.backend.calls.size() == 2);
}

TEST(find_ecu_at_once) {
  Rig r;
  r.backend.next.r[0] = 1;
  r.backend.next.r[1] = 3;
  r.backend.next.data = {1, 2, 3, 4, 5, 6, 7, 8};
  std::vector<uint8_t> nm(16, 0);
  nm[7] = 0x55;
  nm[15] = 0xFF;
  r.call(0, kOpFindEcu, 1, {}, nm);
  EXPECT(r.wait(0));
  EXPECT(r.state(0) == kMbDone && r.rsp(0, 2) == 1 && r.rsp(0, 3) == 3 && r.data(0, 8)[7] == 8);
  EXPECT(r.backend.calls[0].data.size() == 16 && r.backend.calls[0].data[15] == 0xFF);
}

TEST(receiver_batches_and_acknowledgement) {
  Rig r;
  r.call(0, kOpRxOpen, 0, {kRxCan << 8, 32, 0, 0x600, 0, 0x780});
  EXPECT(r.wait(0));
  EXPECT(r.state(0) == kMbDone);
  uint16_t slot = r.rsp(0, 2), gen = r.rsp(0, 3);
  EXPECT(gen != 0);
  EXPECT(r.backend.specs[1].id == 0x600 && r.backend.specs[1].mask == 0x780);
  // The generation shows in the receive mailbox.
  EXPECT(r.in[r.layout.receive_block() + 10 + slot] == gen);
  for (unsigned i = 0; i < 12; ++i) r.backend.rx[1].push_back(can_rec(0x605, 1000 + i, static_cast<uint8_t>(i)));
  r.step();
  uint16_t seq = r.rx_word(0);
  EXPECT(seq != 0);
  EXPECT(r.rx_word(2) == (1u << slot));
  unsigned used = r.rx_word(3);
  EXPECT(used == 9 * 10);  // 9 CAN records fit in 95 words
  // The batch time is the first record's.
  EXPECT(r.rx_word(21) == 0 && r.rx_word(22) == 0 && r.rx_word(23) == 0 && r.rx_word(24) == 1000);
  // First record: receiver, kind and the frame.
  uint16_t w0 = r.rx_word(kRxHeaderWords);
  EXPECT((w0 >> 8) == slot && ((w0 >> 4) & 0xF) == kRxCan);
  EXPECT(r.rx_word(kRxHeaderWords + 4) == 0x605 && r.rx_word(kRxHeaderWords + 5) == 2);
  // Not acknowledged: the batch stays.
  for (int i = 0; i < 5; ++i) r.step();
  EXPECT(r.rx_word(0) == seq);
  // Acknowledged with nothing pending: the next batch with the other 3.
  r.ack(seq, 0);
  r.step();
  EXPECT(r.rx_word(0) == static_cast<uint16_t>(seq + 1));
  EXPECT(r.rx_word(3) == 3 * 10);
  EXPECT(r.rx_word(24) == 1009);
  EXPECT(r.rx_word(kRxHeaderWords + 6) >> 8 == 9);  // the tenth frame's first byte
}

// 30 records queued: how many one batch takes, per kind and receive blocks.
TEST(full_batches) {
  struct Case {
    uint8_t kind, network;
    uint16_t a0, a3, a5;
    unsigned one, two;
  };
  for (const Case& c : {Case{kRxCan, 0, kRxCan << 8, 0x100, 0x700, 9, 21},
                        Case{kRxJ1939, 1, kRxJ1939 << 8, 65282, 255, 7, 17},
                        Case{kRxEmcy, 0, kRxEmcy << 8, 0, 0, 7, 17}}) {
    for (unsigned blocks = 1; blocks <= 2; ++blocks) {
      Rig r(1, 2, blocks);
      r.call(0, kOpRxOpen, c.network, {c.a0, 32, 0, c.a3, 0, c.a5});
      EXPECT(r.wait(0));
      EXPECT(r.state(0) == kMbDone);
      for (unsigned i = 0; i < 30; ++i) {
        RxRecord rec = can_rec(0x100, 500 + i, static_cast<uint8_t>(i));
        rec.pgn = 65282;
        r.backend.rx[1].push_back(rec);
      }
      r.step();
      unsigned want = blocks == 1 ? c.one : c.two;
      EXPECT(r.rx_word(3) == want * record_words(c.kind));
      EXPECT(r.rx_word(24) == 500);
      // The last record ends inside the receive area; the info follows it.
      EXPECT(kRxHeaderWords + r.rx_word(3) <= blocks * kRxWords);
      EXPECT(r.layout.info(0) == r.layout.receive_block() + blocks * kRxBytes);
    }
  }
}

TEST(acknowledgement_with_pending_waits) {
  Rig r;
  r.call(0, kOpRxOpen, 0, {kRxCan << 8, 32, 0, 0x100, 0, 0x7FF});
  EXPECT(r.wait(0));
  r.backend.rx[1].push_back(can_rec(0x100, 1));
  r.step();
  uint16_t seq = r.rx_word(0);
  r.ack(seq, 1u);  // seen, still pending
  r.backend.rx[1].push_back(can_rec(0x100, 2));
  for (int i = 0; i < 5; ++i) r.step();
  EXPECT(r.rx_word(0) == seq);
  r.ack(seq, 0);
  r.step();
  EXPECT(r.rx_word(0) == static_cast<uint16_t>(seq + 1));
}

TEST(stalled_receiver_closes_after_a_second) {
  Rig r;
  r.call(0, kOpRxOpen, 0, {kRxCan << 8, 32, 0, 0x100, 0, 0x7FF});
  EXPECT(r.wait(0));
  r.call(0, kOpRxOpen, 0, {kRxCan << 8, 32, 0, 0x200, 0, 0x7FF});
  EXPECT(r.wait(0));
  r.backend.rx[1].push_back(can_rec(0x100, 1));
  r.backend.rx[2].push_back(can_rec(0x200, 2));
  r.step();
  uint16_t seq = r.rx_word(0);
  EXPECT(r.rx_word(2) == 3u);
  r.ack(seq, 1u);  // receiver 1 took its record, receiver 0 never does
  r.step(500);
  EXPECT(r.backend.closed.empty());
  r.step(600);
  EXPECT(r.backend.closed.size() == 1 && r.backend.closed[0] == 1);
  EXPECT(r.mb->take_stalled() == 1u);
  EXPECT(r.in[r.layout.receive_block() + 10] == 0);   // receiver 0 closed
  EXPECT(r.in[r.layout.receive_block() + 11] != 0);   // receiver 1 open
}

TEST(long_j1939_message_held_for_fetch) {
  Rig r;
  r.call(0, kOpRxOpen, 1, {kRxJ1939 << 8, 4, 0, 65282, 0, 255});
  EXPECT(r.wait(0));
  RxRecord m;
  m.pgn = 65282;
  m.source = 0;
  m.destination = 255;
  m.priority = 6;
  m.time_us = 5;
  for (int i = 0; i < 40; ++i) m.data.push_back(static_cast<uint8_t>(i));
  r.backend.rx[1].push_back(m);
  r.backend.rx[1].push_back(m);
  r.step();
  // One long record per receiver and batch.
  EXPECT(r.rx_word(3) == 12);
  EXPECT((r.rx_word(kRxHeaderWords) & kRecLong) != 0);
  EXPECT(r.rx_word(kRxHeaderWords + 7) == 40);
  r.call(0, kOpRxFetch, 1, {0, 0});
  EXPECT(r.wait(0));
  EXPECT(r.state(0) == kMbDone && r.rsp(0, 2) == 40 && r.data(0, 40)[39] == 39);
}

TEST(long_j1939_message_fetched_in_parts) {
  Rig r;
  r.call(0, kOpRxOpen, 1, {kRxJ1939 << 8, 4, 0, 65282, 0, 255});
  EXPECT(r.wait(0));
  RxRecord m;
  m.pgn = 65282;
  m.time_us = 5;
  for (int i = 0; i < 300; ++i) m.data.push_back(static_cast<uint8_t>(i));
  r.backend.rx[1].push_back(m);
  r.step();
  // RX_FETCH answers the size and the first 128 bytes; FETCH the rest.
  r.call(0, kOpRxFetch, 1, {0, 0});
  EXPECT(r.wait(0));
  EXPECT(r.state(0) == kMbDone && r.rsp(0, 2) == 300 && r.data(0, 128)[127] == 127);
  r.call(0, kOpFetch, 0, {256});
  EXPECT(r.wait(0));
  EXPECT(r.state(0) == kMbDone && r.rsp(0, 2) == 300 && r.data(0, 44)[0] == 0 && r.data(0, 44)[43] == 43);
}

TEST(cyclic_job_set_update_keepalive) {
  Rig r;
  r.call(0, kOpCyclicSet, 0, {0xFFFF, 0, 0x300, 2, 20}, {9, 8});
  EXPECT(r.wait(0));
  EXPECT(r.state(0) == kMbDone);
  uint16_t job = r.rsp(0, 2), gen = r.rsp(0, 3);
  EXPECT(r.backend.cyc[1].period_ms == 20 && r.backend.cyc[1].data[0] == 9);
  r.call(0, kOpCyclicSet, 0, {job, 0, 0x300, 2, 10}, {1, 2});
  EXPECT(r.wait(0));
  EXPECT(r.backend.cyc[1].period_ms == 10 && r.backend.cyc[1].data[0] == 1);
  // The table: active, generation, count.
  const uint8_t* t = &r.in[r.layout.cyclic_table() + 2 + job * kJobWords * 2];
  EXPECT(t[0] == 1 && get_be16(t + 2) == gen && get_be16(t + 6) == 7);
  // Keepalive changing: the job stays; then it stops after 1 s.
  for (int i = 0; i < 15; ++i) {
    put_be16(&r.out[r.layout.keepalive(job)], static_cast<uint16_t>(i + 1));
    r.step(100);
  }
  EXPECT(r.backend.stopped.empty());
  r.step(600);
  r.step(600);
  EXPECT(r.backend.stopped.size() == 1);
  EXPECT(r.mb->take_forgotten() == 1);
}

TEST(cyclic_period_out_of_range) {
  Rig r;
  r.call(0, kOpCyclicSet, 0, {0xFFFF, 0, 0x300, 2, 0});
  EXPECT(r.wait(0));
  EXPECT(r.state(0) == kMbError && r.error(0) == 3);
}

TEST(network_info) {
  Rig r;
  const uint8_t* p = &r.in[r.layout.info(1)];
  EXPECT(p[1] == 11);
  EXPECT(get_be32(p + 10) == 0x12345);
  EXPECT(p[22] == 1 && p[23] == 128);
  EXPECT(get_be16(p + 24) == 0x0102 && get_be16(p + 30) == 0x0708);
  EXPECT(get_be16(p + 32) == 3);
}

TEST(end_all_cancels_everything) {
  Rig r;
  r.backend.polls = 100;
  r.call(0, kOpRxOpen, 0, {kRxCan << 8, 32, 0, 0x100, 0, 0x7FF});
  r.backend.polls = 0;
  EXPECT(r.wait(0));
  r.call(0, kOpCyclicSet, 0, {0xFFFF, 0, 0x300, 2, 20});
  EXPECT(r.wait(0));
  r.backend.polls = 100;
  r.call(0, kOpCanSend, 0, {0, 0x100, 1, 0});
  r.step();
  EXPECT(r.state(0) == kMbBusy);
  EXPECT(r.mb->end_all("test") == 3);
  r.step();
  EXPECT(r.state(0) == kMbError && r.error(0) == 8);
  EXPECT(r.backend.cancelled);
  EXPECT(r.backend.closed.size() == 1 && r.backend.stopped.size() == 1);
}

TEST(receiver_limit) {
  Rig r;
  for (unsigned i = 0; i < kMaxReceivers; ++i) {
    r.call(0, kOpRxOpen, 0, {kRxCan << 8, 1, 0, static_cast<uint16_t>(i), 0, 0x7FF});
    EXPECT(r.wait(0));
    EXPECT(r.state(0) == kMbDone);
  }
  r.call(0, kOpRxOpen, 0, {kRxCan << 8, 1, 0, 0x7FF, 0, 0x7FF});
  EXPECT(r.wait(0));
  EXPECT(r.state(0) == kMbError && r.error(0) == 5);
  r.call(0, kOpRxOpen, 1, {kRxJ1939 << 8, 1, 0, 1, 0, 255});
  EXPECT(r.wait(0));
  EXPECT(r.error(0) == 9);
}

TEST(use_counts_for_the_status) {
  Rig r;
  EXPECT(r.mb->operations() == 0 && r.mb->receivers_opened() == 0);
  r.call(0, kOpRxOpen, 0, {kRxCan << 8, 32, 0, 0x600, 0, 0x780});
  EXPECT(r.wait(0));
  for (int i = 0; i < 3; ++i) {
    r.call(0, kOpCanSend, 0, {0, 0x510, 2, 100}, {1, 2});
    EXPECT(r.wait(0));
  }
  // The same request rewritten and operation none count nothing.
  for (int i = 0; i < 5; ++i) r.step();
  r.call(0, kOpNone, 0, {});
  r.step();
  EXPECT(r.mb->operations() == 4 && r.mb->receivers_opened() == 1);
  // After a restart the last request, ended with ERROR_ID 8, counts.
  r.call(0, kOpCanSend, 0, {0, 0x511, 2, 100}, {3, 4});
  r.mb.reset(new Mailboxes(r.layout, r.backend));
  r.step();
  EXPECT(r.mb->operations() == 1 && r.mb->receivers_opened() == 0);
}

int main(int argc, char** argv) { return check::run_all(argc, argv); }
