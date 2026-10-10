// Unit tests of the J1939 side of the plugin (j1939-ecu spec): NAME bits,
// signals in message bytes, the address claim, and the engine on a fake
// socket (no kernel J1939 module needed). Then the diagnostic messages
// (j1939-diagnostics): the DM codec against the shared byte fixtures, the
// DM1 store, the own trouble codes, clears, DM13, the jobs behind the
// diagnostics operations and the PLC blocks' table.

#include <algorithm>
#include <cerrno>
#include <chrono>
#include <cstring>
#include <fstream>
#include <sstream>
#include <cstdint>
#include <set>
#include <string>
#include <utility>
#include <vector>

#include "address_claim.h"
#include "cJSON.h"
#include "check.hpp"
#include "config.h"
#include "fake_runtime.hpp"
#include "log.h"
#include "dm.h"
#include "j1939_network.h"
#include "j1939_plc_api.h"
#include "j1939_plc_jobs.h"
#include "j1939_signal.h"
#include "j1939_socket.h"

using namespace canopen_plugin;
using clock_type = std::chrono::steady_clock;
using std::chrono::milliseconds;

namespace {

IecLocation loc(const char* text) {
  IecLocation l;
  std::string error;
  if (!parse_iec_location(text, l, error)) {
    std::fprintf(stderr, "bad location %s: %s\n", text, error.c_str());
    std::abort();
  }
  return l;
}

J1939Signal sig(const char* name, unsigned start, unsigned length, bool big = false, bool is_signed = false) {
  J1939Signal s;
  s.name = name;
  s.start_bit = start;
  s.length = length;
  s.big_endian = big;
  s.is_signed = is_signed;
  return s;
}

// ---------------------------------------------------------------------------
// NAME and signals

TEST(j1939_name_bits) {
  J1939Name n;
  n.identity_number = 1234;
  n.function = 0x82;
  n.arbitrary_address_capable = true;
  CHECK(n.value() == 0x80008200000004D2ULL);
  J1939Name f;
  f.identity_number = 0x1FFFFF;
  f.manufacturer_code = 0x123;
  f.ecu_instance = 5;
  f.function_instance = 0x11;
  f.function = 0xA5;
  f.vehicle_system = 0x45;
  f.vehicle_system_instance = 0xA;
  f.industry_group = 3;
  f.arbitrary_address_capable = true;
  CHECK(f.value() == 0xBA8AA58D247FFFFFULL);
}

TEST(j1939_signal_little_endian) {
  J1939Signal s = sig("a", 4, 12);
  uint8_t d[8];
  std::fill(d, d + 8, 0xFF);
  j1939_insert(d, 8, s, 0xABC);
  CHECK(d[0] == 0xCF && d[1] == 0xAB && d[2] == 0xFF);
  uint64_t raw = 0;
  CHECK(j1939_extract(d, 8, s, raw) && raw == 0xABC);
  // Too short a message holds no value.
  CHECK(!j1939_extract(d, 1, s, raw));
}

TEST(j1939_signal_big_endian) {
  // DBC convention: the start bit is the most significant bit, here bit 7 of
  // byte 0, so the 16 bits are bytes 0 and 1 in big byte order.
  J1939Signal s = sig("b", 7, 16, true);
  std::vector<unsigned> bits = j1939_signal_bits(s);
  CHECK(bits.size() == 16 && bits.front() == 8 && bits.back() == 7);
  uint8_t d[8] = {0};
  j1939_insert(d, 8, s, 0x1234);
  CHECK(d[0] == 0x12 && d[1] == 0x34);
  // 12 bits from bit 3 of byte 0: 4 bits there, then all of byte 1.
  J1939Signal t = sig("c", 3, 12, true);
  uint8_t e[8] = {0};
  j1939_insert(e, 8, t, 0xABC);
  CHECK(e[0] == 0x0A && e[1] == 0xBC);
  uint64_t raw = 0;
  CHECK(j1939_extract(e, 8, t, raw) && raw == 0xABC);
}

TEST(j1939_signal_sign_and_validity) {
  J1939Signal s = sig("t", 0, 8, false, true);
  CHECK(j1939_to_plc(s, 0xF6) == 0xFFFFFFFFFFFFFFF6ULL);
  CHECK(j1939_to_plc(s, 0x76) == 0x76);
  J1939Signal u = sig("u", 0, 8);
  CHECK(j1939_to_plc(u, 0xF6) == 0xF6);
  CHECK(j1939_not_valid(u, 0xFF) && j1939_not_valid(u, 0xFE) && !j1939_not_valid(u, 0xFD));
  J1939Signal two = sig("two", 0, 2);
  CHECK(j1939_not_valid(two, 3) && j1939_not_valid(two, 2) && !j1939_not_valid(two, 1));
  J1939Signal one = sig("one", 0, 1);
  CHECK(!j1939_not_valid(one, 1));
  CHECK(j1939_from_plc(u, 0x1FF) == 0xFF);
  J1939Signal l = sig("l", 0, 64);
  CHECK(j1939_from_plc(l, ~uint64_t(0)) == ~uint64_t(0));
}

// ---------------------------------------------------------------------------
// Address claim

struct FakeActions : AddressClaimer::Actions {
  std::vector<int> claims;  // addresses claimed (254: Cannot Claim)
  int requests = 0;
  void send_claim(uint8_t a) override { claims.push_back(a); }
  void send_claim_request() override { ++requests; }
};

J1939Ecu ecu(unsigned address, bool range, bool aac = true) {
  J1939Ecu e;
  e.name.identity_number = 1234;
  e.name.function = 0x82;
  e.name.arbitrary_address_capable = aac;
  e.address = address;
  e.has_range = range;
  e.range_low = 128;
  e.range_high = 130;
  return e;
}

TEST(j1939_claim_uncontested) {
  J1939Ecu e = ecu(128, false);
  FakeActions a;
  AddressClaimer c(e, a);
  CHECK(c.state() == J1939ClaimState::NoBus);
  auto t0 = clock_type::now();
  c.start(t0);
  CHECK(a.requests == 1 && a.claims.empty() && c.state() == J1939ClaimState::Claiming);
  c.tick(t0 + milliseconds(249));
  CHECK(a.claims.empty());
  c.tick(t0 + milliseconds(250));
  CHECK(a.claims == std::vector<int>{128} && c.state() == J1939ClaimState::Claiming && c.address() == 254);
  c.tick(t0 + milliseconds(500));
  CHECK(c.state() == J1939ClaimState::Claimed && c.address() == 128);
  // A request for the claim is answered; a higher NAME is fought off.
  c.on_claim_request(t0 + milliseconds(550));
  c.on_claim(128, c.name() + 1, t0 + milliseconds(600));
  CHECK((a.claims == std::vector<int>{128, 128, 128}) && c.state() == J1939ClaimState::Claimed);
  c.bus_lost();
  CHECK(c.state() == J1939ClaimState::NoBus && c.address() == 254);
}

TEST(j1939_claim_held_by_lower_name) {
  // Without a range: Cannot Claim.
  {
    J1939Ecu e = ecu(128, false);
    FakeActions a;
    AddressClaimer c(e, a);
    auto t0 = clock_type::now();
    c.start(t0);
    c.on_claim(128, 1, t0 + milliseconds(10));
    c.tick(t0 + milliseconds(250));
    CHECK(a.claims == std::vector<int>{254} && c.state() == J1939ClaimState::CannotClaim);
    // A request is answered with Cannot Claim after a pseudo-random delay
    // of 0-153 ms (J1939-81), the same for the same NAME.
    c.on_claim_request(t0 + milliseconds(300));
    int delay = -1;
    for (int ms = 300; ms <= 460 && delay < 0; ++ms) {
      c.tick(t0 + milliseconds(ms));
      if (a.claims.size() == 2) delay = ms - 300;
    }
    CHECK_MSG(delay >= 0 && delay <= 153, "delay " + std::to_string(delay));
    CHECK((a.claims == std::vector<int>{254, 254}));
    c.tick(t0 + milliseconds(1000));
    CHECK(a.claims.size() == 2);
    // A second request while one waits is answered once.
    c.on_claim_request(t0 + milliseconds(2000));
    c.on_claim_request(t0 + milliseconds(2001));
    c.tick(t0 + milliseconds(2160));
    CHECK(a.claims.size() == 3);
  }
  // With a range: the next free address (129 is taken too).
  {
    J1939Ecu e = ecu(128, true);
    FakeActions a;
    AddressClaimer c(e, a);
    auto t0 = clock_type::now();
    c.start(t0);
    c.on_claim(128, 1, t0 + milliseconds(10));
    c.on_claim(129, ~uint64_t(0) >> 1, t0 + milliseconds(20));
    c.tick(t0 + milliseconds(250));
    CHECK(a.claims == std::vector<int>{130});
    c.tick(t0 + milliseconds(500));
    CHECK(c.state() == J1939ClaimState::Claimed && c.address() == 130);
  }
  // A range but not arbitrary-address capable: Cannot Claim.
  {
    J1939Ecu e = ecu(128, true, false);
    FakeActions a;
    AddressClaimer c(e, a);
    auto t0 = clock_type::now();
    c.start(t0);
    c.on_claim(128, 1, t0);
    c.tick(t0 + milliseconds(250));
    CHECK(c.state() == J1939ClaimState::CannotClaim);
  }
}

// The Cannot Claim delay of the first Request after losing the address.
int cannot_claim_delay(uint32_t identity) {
  J1939Ecu e = ecu(128, false);
  e.name.identity_number = identity;
  FakeActions a;
  AddressClaimer c(e, a);
  auto t0 = clock_type::now();
  c.start(t0);
  c.on_claim(128, 1, t0);
  c.tick(t0 + milliseconds(250));
  c.on_claim_request(t0 + milliseconds(300));
  for (int ms = 300; ms <= 460; ++ms) {
    c.tick(t0 + milliseconds(ms));
    if (a.claims.size() == 2) return ms - 300;
  }
  return -1;
}

TEST(j1939_cannot_claim_delay_from_the_name) {
  std::set<int> seen;
  for (uint32_t id = 1; id <= 16; ++id) {
    int d = cannot_claim_delay(id);
    CHECK_MSG(d >= 0 && d <= 153, "identity " + std::to_string(id) + ": delay " + std::to_string(d));
    CHECK(cannot_claim_delay(id) == d);
    seen.insert(d);
  }
  CHECK_MSG(seen.size() >= 8, std::to_string(seen.size()) + " different delays for 16 NAMEs");
}

TEST(j1939_claim_lost_after_claimed) {
  J1939Ecu e = ecu(129, true);
  FakeActions a;
  AddressClaimer c(e, a);
  auto t0 = clock_type::now();
  c.start(t0);
  c.tick(t0 + milliseconds(250));
  c.tick(t0 + milliseconds(500));
  CHECK(c.address() == 129);
  // A lower NAME takes 129: move on, wrapping round the range.
  c.on_claim(129, 1, t0 + milliseconds(600));
  CHECK(a.claims.back() == 130 && c.state() == J1939ClaimState::Claiming);
  c.on_claim(130, 2, t0 + milliseconds(700));
  CHECK(a.claims.back() == 128);
  c.on_claim(128, 3, t0 + milliseconds(800));
  CHECK(a.claims.back() == 254 && c.state() == J1939ClaimState::CannotClaim);
}

// ---------------------------------------------------------------------------
// Engine on a fake socket

struct Sent {
  uint32_t pgn;
  uint8_t destination;
  uint8_t priority;
  std::vector<uint8_t> data;
};

class FakeSocket : public J1939Socket {
 public:
  std::vector<int> binds;
  std::vector<Sent> sent;
  int send_result = 0;
  int open(const std::string&, const std::vector<uint32_t>&) override { return 0; }
  int bind(uint64_t, uint8_t address) override {
    binds.push_back(address);
    return 0;
  }
  void close() override {}
  int fd() const override { return -1; }
  int receive(J1939Message&) override { return -EAGAIN; }
  int send(uint32_t pgn, uint8_t destination, uint8_t priority, const uint8_t* data, size_t len) override {
    sent.push_back(Sent{pgn, destination, priority, std::vector<uint8_t>(data, data + len)});
    return send_result;
  }
  // The sends of `pgn` so far.
  std::vector<Sent> of(uint32_t pgn) const {
    std::vector<Sent> r;
    for (const auto& s : sent)
      if (s.pgn == pgn) r.push_back(s);
    return r;
  }
};

Config engine_config() {
  Config cfg;
  cfg.protocol = Protocol::J1939;
  cfg.adapter.interface = "vcan0";
  cfg.adapter.bitrate = 250000;
  J1939Config& j = cfg.j1939;
  j.ecu = ecu(128, true);
  j.ecu.has_state_location = true;
  j.ecu.state_location = loc("%IB20");
  j.ecu.has_address_location = true;
  j.ecu.address_location = loc("%IB21");
  J1939Rx r;
  r.pgn = 0xFF00;
  r.timeout_ms = 300;
  r.has_status_location = true;
  r.status_location = loc("%IX10.1");
  r.signals.push_back(sig("speed", 0, 16));
  r.signals.back().location = loc("%IW0");
  r.signals.back().has_valid_location = true;
  r.signals.back().valid_location = loc("%IX10.0");
  r.signals.push_back(sig("temp", 16, 8, false, true));
  r.signals.back().location = loc("%IL1");
  j.rx.push_back(r);
  J1939Rx p;  // PDU1, from source 0x30 only
  p.pgn = 0xEF00;
  p.has_source = true;
  p.source = 0x30;
  p.signals.push_back(sig("cmd", 0, 8));
  p.signals.back().location = loc("%IB5");
  j.rx.push_back(p);
  J1939Tx t;
  t.pgn = 0xFF01;
  t.period_ms = 100;
  t.signals.push_back(sig("set", 0, 16));
  t.signals.back().location = loc("%QW0");
  j.tx.push_back(t);
  J1939Tx c;
  c.pgn = 0xFF02;
  c.min_gap_ms = 50;
  c.signals.push_back(sig("mode", 0, 8));
  c.signals.back().location = loc("%QB4");
  j.tx.push_back(c);
  J1939Request q;
  q.pgn = 0xFEDA;
  q.period_ms = 1000;
  j.requests.push_back(q);
  std::vector<std::string> errors;
  check_j1939(j, [&](const std::string& w, const std::string& m) { errors.push_back(w + ": " + m); });
  if (!errors.empty()) {
    std::fprintf(stderr, "engine config: %s\n", errors[0].c_str());
    std::abort();
  }
  return cfg;
}

// An engine on a fake socket, claimed at 128 at `t0 + 500 ms`.
struct Rig {
  Config cfg;
  J1939Image image;
  FakeSocket socket;
  J1939Engine engine{cfg, image, socket};
  fake_runtime::Image img;
  plugin_runtime_args_t rt;
  clock_type::time_point t0 = clock_type::now();

  explicit Rig(Config c = engine_config()) : cfg(std::move(c)) {
    image.build(cfg.j1939);
    fake_runtime::attach(img, rt);
  }
  void claim() {
    engine.bus_up(t0);
    engine.tick(t0 + milliseconds(250));
    engine.tick(t0 + milliseconds(500));
  }
  clock_type::time_point at(int ms) const { return t0 + milliseconds(ms); }
  void message(uint32_t pgn, uint8_t source, uint8_t destination, std::vector<uint8_t> data, int ms) {
    J1939Message m;
    m.pgn = pgn;
    m.source = source;
    m.destination = destination;
    m.data = std::move(data);
    engine.on_message(m, at(ms));
  }
  void request(uint32_t pgn, uint8_t source, uint8_t destination, int ms) {
    message(kPgnRequest, source, destination, {uint8_t(pgn), uint8_t(pgn >> 8), uint8_t(pgn >> 16)}, ms);
  }
};

TEST(j1939_engine_claims_and_reports) {
  Rig r;
  r.engine.bus_up(r.t0);
  CHECK(r.socket.binds == std::vector<int>{254});
  CHECK(r.socket.sent.size() == 1 && r.socket.sent[0].pgn == kPgnRequest &&
        (r.socket.sent[0].data == std::vector<uint8_t>{0x00, 0xEE, 0x00}));
  r.engine.tick(r.at(250));
  CHECK((r.socket.binds == std::vector<int>{254, 128}));
  auto ac = r.socket.of(kPgnAddressClaimed);
  CHECK(ac.size() == 1 && ac[0].destination == 255 &&
        (ac[0].data == std::vector<uint8_t>{0xD2, 0x04, 0, 0, 0, 0x82, 0, 0x80}));
  CHECK(r.engine.state() == J1939ClaimState::Claiming);
  r.engine.tick(r.at(500));
  CHECK(r.engine.state() == J1939ClaimState::Claimed && r.engine.address() == 128);
  r.image.copy_to_plc(r.rt);
  CHECK(r.img.byte_in[20] == 1 && r.img.byte_in[21] == 128);
  cJSON* s = r.engine.status(r.at(500));
  char* text = cJSON_PrintUnformatted(s);
  std::string js = text;
  cJSON_free(text);
  cJSON_Delete(s);
  CHECK_MSG(js.find(R"("state_name":"claimed")") != std::string::npos &&
                js.find(R"("address":128)") != std::string::npos &&
                js.find(R"("name":"0x80008200000004D2")") != std::string::npos,
            js);
  r.engine.bus_lost("CAN interface vcan0 is down");
  r.image.copy_to_plc(r.rt);
  CHECK(r.img.byte_in[20] == 3 && r.img.byte_in[21] == 254);
  CHECK(r.engine.problem() == "CAN interface vcan0 is down");
}

TEST(j1939_engine_receives) {
  Rig r;
  r.claim();
  r.message(0xFF00, 0x10, 255, {0x10, 0x27, 0xF6, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF}, 510);
  r.engine.tick(r.at(511));
  r.image.copy_to_plc(r.rt);
  CHECK(r.img.int_in[0] == 0x2710 && r.img.lint_in[1] == 0xFFFFFFFFFFFFFFF6ULL);
  CHECK(r.img.bool_in[10][0] == 1 && r.img.bool_in[10][1] == 1);
  // Not available: valid drops and the value keeps its last one.
  r.message(0xFF00, 0x10, 255, {0xFF, 0xFF, 0x05, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF}, 520);
  r.engine.tick(r.at(521));
  r.image.copy_to_plc(r.rt);
  CHECK(r.img.bool_in[10][0] == 0 && r.img.int_in[0] == 0x2710 && r.img.lint_in[1] == 5);
  // Supervision: nothing for 300 ms.
  r.engine.tick(r.at(819));
  r.image.copy_to_plc(r.rt);
  CHECK(r.img.bool_in[10][1] == 1);
  r.engine.tick(r.at(820));
  r.image.copy_to_plc(r.rt);
  CHECK(r.img.bool_in[10][1] == 0);
  // PDU1: only to us or global, only from the configured source.
  r.message(0xEF00, 0x30, 0x40, {7}, 830);
  r.message(0xEF00, 0x31, 128, {8}, 831);
  r.engine.tick(r.at(832));
  r.image.copy_to_plc(r.rt);
  CHECK(r.img.byte_in[5] == 0);
  r.message(0xEF00, 0x30, 128, {9}, 833);
  r.engine.tick(r.at(834));
  r.image.copy_to_plc(r.rt);
  CHECK(r.img.byte_in[5] == 9);
  // Our own messages coming back are not taken.
  r.message(0xFF00, 128, 255, {1, 0, 0}, 840);
  r.engine.tick(r.at(841));
  r.image.copy_to_plc(r.rt);
  CHECK(r.img.bool_in[10][1] == 0);
}

TEST(j1939_engine_sends) {
  Rig r;
  r.claim();
  // Nothing goes out before the program's first scan.
  r.engine.tick(r.at(600));
  CHECK(r.socket.of(0xFF01).empty() && r.socket.of(0xFF02).empty());
  // The periodic request does not wait for a scan.
  CHECK(r.socket.of(kPgnRequest).size() == 2);  // the claim's, then 0xFEDA
  r.img.int_out[0] = 0x1234;
  r.img.byte_out[4] = 7;
  r.image.copy_from_plc(r.rt);
  r.engine.tick(r.at(610));
  auto a = r.socket.of(0xFF01);
  auto b = r.socket.of(0xFF02);
  CHECK(a.size() == 1 && (a[0].data == std::vector<uint8_t>{0x34, 0x12, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF}));
  CHECK(a[0].destination == 255 && a[0].priority == 6);
  CHECK(b.size() == 1 && b[0].data[0] == 7 && b[0].data[1] == 0xFF && b[0].data.size() == 8);
  // On change, held back until min_gap_ms has passed.
  r.img.byte_out[4] = 8;
  r.image.copy_from_plc(r.rt);
  r.engine.tick(r.at(620));
  CHECK(r.socket.of(0xFF02).size() == 1);
  r.engine.tick(r.at(660));
  b = r.socket.of(0xFF02);
  CHECK(b.size() == 2 && b[1].data[0] == 8);
  // No change, nothing sent; the periodic one keeps its period.
  r.engine.tick(r.at(709));
  CHECK(r.socket.of(0xFF02).size() == 2 && r.socket.of(0xFF01).size() == 1);
  r.engine.tick(r.at(710));
  CHECK(r.socket.of(0xFF01).size() == 2);
}

TEST(j1939_engine_retries_before_the_kernel_takes_the_address) {
  Rig r;
  r.claim();
  r.img.int_out[0] = 0x1234;
  r.img.byte_out[4] = 7;
  r.image.copy_from_plc(r.rt);
  r.socket.send_result = -EADDRNOTAVAIL;
  r.engine.tick(r.at(510));
  CHECK(r.socket.of(0xFF01).size() == 1 && r.socket.of(0xFF02).size() == 1);
  r.socket.send_result = 0;
  r.engine.tick(r.at(511));
  CHECK(r.socket.of(0xFF01).size() == 2 && r.socket.of(0xFF02).size() == 2);
  CHECK(r.engine.send_errors() == 0);
  // Later it is a failure like any other, and is not retried at once.
  r.socket.send_result = -EADDRNOTAVAIL;
  r.engine.tick(r.at(1611));
  CHECK(r.engine.send_errors() >= 1);
  size_t n = r.socket.of(0xFF01).size();
  r.engine.tick(r.at(1612));
  CHECK(r.socket.of(0xFF01).size() == n);
}

TEST(j1939_engine_answers_requests) {
  Rig r;
  r.claim();
  r.img.int_out[0] = 0x0102;
  r.image.copy_from_plc(r.rt);
  size_t before = r.socket.of(0xFF01).size();
  // A request to us for a PGN we send: answered (PDU2, so to global).
  r.request(0xFF01, 0x20, 128, 520);
  auto a = r.socket.of(0xFF01);
  CHECK(a.size() == before + 1 && a.back().data[0] == 0x02 && a.back().data[1] == 0x01);
  // To us for a PGN we do not send: NACK.
  r.request(0xFEEE, 0x20, 128, 530);
  auto n = r.socket.of(kPgnAcknowledgement);
  CHECK(n.size() == 1 && (n[0].data == std::vector<uint8_t>{1, 0xFF, 0xFF, 0xFF, 0x20, 0xEE, 0xFE, 0x00}));
  // Global for a PGN we do not send: nothing.
  r.request(0xFEEE, 0x20, 255, 540);
  CHECK(r.socket.of(kPgnAcknowledgement).size() == 1);
  // To another ECU: nothing.
  r.request(0xFF01, 0x20, 0x21, 545);
  CHECK(r.socket.of(0xFF01).size() == before + 1);
  // For the address claim: our claim again.
  size_t claims = r.socket.of(kPgnAddressClaimed).size();
  r.request(kPgnAddressClaimed, 0x20, 255, 550);
  CHECK(r.socket.of(kPgnAddressClaimed).size() == claims + 1);
  cJSON* s = r.engine.status(r.at(560));
  char* text = cJSON_PrintUnformatted(s);
  std::string js = text;
  cJSON_free(text);
  cJSON_Delete(s);
  CHECK_MSG(js.find(R"("requests_answered":1)") != std::string::npos, js);
}

// Requests for the same PGN from the same requester are answered at most
// every 50 ms; other requesters and other PGNs have their own limit.
TEST(j1939_engine_rate_limits_requests) {
  Rig r;
  r.claim();
  r.img.int_out[0] = 0x0102;
  r.image.copy_from_plc(r.rt);
  size_t before = r.socket.of(0xFF01).size();
  for (int ms = 520; ms < 720; ms += 5) r.request(0xFF01, 0x03, 128, ms);
  size_t answered = r.socket.of(0xFF01).size() - before;
  CHECK_MSG(answered == 4, std::to_string(answered) + " answers in 200 ms");
  r.request(0xFF01, 0x04, 128, 721);
  CHECK(r.socket.of(0xFF01).size() - before == 5);
  // NACKs too.
  for (int ms = 800; ms < 900; ms += 5) r.request(0xFEEE, 0x03, 128, ms);
  CHECK(r.socket.of(kPgnAcknowledgement).size() == 2);
}

// A send the interface refuses does not count as sent: an on-change PGN goes
// out with its new value once the interface takes frames again.
TEST(j1939_engine_failed_send_stays_pending) {
  Rig r;
  r.claim();
  r.img.byte_out[4] = 7;
  r.image.copy_from_plc(r.rt);
  r.engine.tick(r.at(1600));
  CHECK(r.socket.of(0xFF02).size() == 1);
  r.img.byte_out[4] = 8;
  r.image.copy_from_plc(r.rt);
  r.socket.send_result = -ENOBUFS;
  r.engine.tick(r.at(1700));
  CHECK(r.socket.of(0xFF02).size() == 2);
  r.socket.send_result = 0;
  r.engine.tick(r.at(1701));
  auto b = r.socket.of(0xFF02);
  CHECK(b.size() == 3 && b.back().data[0] == 8);
  r.engine.tick(r.at(1800));
  CHECK(r.socket.of(0xFF02).size() == 3);
}

TEST(j1939_engine_moves_on_contention) {
  Rig r;
  r.claim();
  uint8_t lower[8] = {1, 0, 0, 0, 0, 0, 0, 0};
  r.message(kPgnAddressClaimed, 128, 255, std::vector<uint8_t>(lower, lower + 8), 600);
  CHECK(r.socket.binds.back() == 129 && r.engine.state() == J1939ClaimState::Claiming);
  r.engine.tick(r.at(601));
  r.image.copy_to_plc(r.rt);
  CHECK(r.img.byte_in[20] == 0 && r.img.byte_in[21] == 254);  // claiming: no address yet
  // Nothing is sent while the new claim stands open.
  r.img.int_out[0] = 1;
  r.image.copy_from_plc(r.rt);
  r.engine.tick(r.at(700));
  CHECK(r.socket.of(0xFF01).empty());
  r.engine.tick(r.at(850));
  CHECK(r.engine.state() == J1939ClaimState::Claimed && r.engine.address() == 129);
  CHECK(r.socket.of(0xFF01).size() == 1);
  r.image.copy_to_plc(r.rt);
  CHECK(r.img.byte_in[21] == 129);
}

TEST(j1939_engine_cannot_claim_on_contention) {
  Rig r;
  r.cfg.j1939.ecu.has_range = false;
  r.claim();
  uint8_t lower[8] = {1, 0, 0, 0, 0, 0, 0, 0};
  r.message(kPgnAddressClaimed, 128, 255, std::vector<uint8_t>(lower, lower + 8), 600);
  CHECK(r.engine.state() == J1939ClaimState::CannotClaim);
  // Cannot Claim: the claim again, from the null address.
  CHECK(r.socket.binds.back() == 254 && r.socket.of(kPgnAddressClaimed).size() == 2);
  r.engine.tick(r.at(601));
  r.image.copy_to_plc(r.rt);
  CHECK(r.img.byte_in[20] == 2 && r.img.byte_in[21] == 254);
  r.img.int_out[0] = 1;
  r.image.copy_from_plc(r.rt);
  r.engine.tick(r.at(700));
  CHECK(r.socket.of(0xFF01).empty());
}

TEST(j1939_socket_problems) {
  CHECK(j1939_socket_problem(-EPROTONOSUPPORT, "can0") == "J1939 needs the can-j1939 kernel module (modprobe can-j1939)");
  CHECK(j1939_socket_problem(ENODEV, "can0") == "CAN interface can0 not found");
  CHECK(j1939_socket_problem(-ENETDOWN, "can0") == "CAN interface can0 is down");
}

// ---------------------------------------------------------------------------
// Multiplexed messages (can-multiplexed-signals)

J1939Signal muxed(const char* name, unsigned start, unsigned length, std::vector<uint64_t> values,
                  const char* location) {
  J1939Signal s = sig(name, start, length);
  s.mux.has_mux = true;
  for (uint64_t v : values) s.mux.values.push_back(canworks_can::MuxRange{v, v});
  if (location)
    s.location = loc(location);
  else
    s.has_location = false;
  return s;
}

J1939Signal page_switch(const char* location) {
  J1939Signal s = sig("Page", 0, 8);
  s.mux.is_switch = true;
  if (location)
    s.location = loc(location);
  else
    s.has_location = false;
  return s;
}

void index_signals(std::vector<J1939Signal>& signals) {
  for (size_t k = 0; k < signals.size(); ++k) signals[k].index = static_cast<unsigned>(k);
}

Config mux_config() {
  Config cfg;
  cfg.protocol = Protocol::J1939;
  cfg.adapter.interface = "vcan0";
  cfg.adapter.bitrate = 250000;
  J1939Config& j = cfg.j1939;
  j.ecu = ecu(128, true);
  // Received: Page 1 carries Temp, page 2 Press; Count is in every page.
  J1939Rx r;
  r.pgn = 0xFF10;
  r.timeout_ms = 300;
  r.signals.push_back(page_switch("%IB30"));
  r.signals.push_back(muxed("Temp", 8, 8, {1}, "%IB31"));
  r.signals.back().has_valid_location = true;
  r.signals.back().valid_location = loc("%IX12.0");
  r.signals.push_back(muxed("Press", 8, 16, {2}, "%IW16"));
  r.signals.back().has_valid_location = true;
  r.signals.back().valid_location = loc("%IX12.1");
  r.signals.push_back(sig("Count", 56, 8));
  r.signals.back().location = loc("%IB32");
  r.signals.push_back(muxed("Far", 80, 8, {3}, "%IB33"));  // past 8 bytes: transport protocol
  index_signals(r.signals);
  j.rx.push_back(r);
  // Sent: every page each period, one page each period, and the program's page on change.
  for (int m = 0; m < 2; ++m) {
    J1939Tx t;
    t.pgn = 0xFF11 + static_cast<uint32_t>(m);
    t.period_ms = 100;
    t.pages = m == 0 ? canworks_can::MuxPages::All : canworks_can::MuxPages::Rotate;
    t.has_pages = true;
    t.signals.push_back(page_switch(nullptr));
    t.signals.push_back(muxed("A", 8, 8, {1}, m == 0 ? "%QB10" : "%QB12"));
    t.signals.push_back(muxed("B", 8, 8, {2}, m == 0 ? "%QB11" : "%QB13"));
    index_signals(t.signals);
    j.tx.push_back(t);
  }
  J1939Tx p;
  p.pgn = 0xFF13;
  p.signals.push_back(page_switch("%QB14"));
  p.signals.push_back(muxed("A", 8, 8, {1}, "%QB15"));
  p.signals.push_back(muxed("B", 8, 16, {2}, "%QW8"));
  index_signals(p.signals);
  j.tx.push_back(p);
  std::vector<std::string> errors;
  check_j1939(j, [&](const std::string& w, const std::string& m) { errors.push_back(w + ": " + m); });
  if (!errors.empty()) {
    std::fprintf(stderr, "mux config: %s\n", errors[0].c_str());
    std::abort();
  }
  return cfg;
}

std::string status_json(Rig& r, int ms) {
  cJSON* s = r.engine.status(r.at(ms));
  char* text = cJSON_PrintUnformatted(s);
  std::string js = text;
  cJSON_free(text);
  cJSON_Delete(s);
  return js;
}

TEST(j1939_engine_receives_pages) {
  Rig r(mux_config());
  r.claim();
  r.message(0xFF10, 0x10, 255, {1, 25, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 3}, 510);
  r.engine.tick(r.at(511));
  r.image.copy_to_plc(r.rt);
  CHECK(r.img.byte_in[30] == 1 && r.img.byte_in[31] == 25 && r.img.int_in[16] == 0 && r.img.byte_in[32] == 3);
  CHECK(r.img.bool_in[12][0] == 1 && r.img.bool_in[12][1] == 0);
  r.message(0xFF10, 0x10, 255, {2, 0x34, 0x12, 0xFF, 0xFF, 0xFF, 0xFF, 4}, 600);
  r.engine.tick(r.at(601));
  r.image.copy_to_plc(r.rt);
  // Temp keeps its value (bytes 1 are Press's now) and is still valid.
  CHECK(r.img.byte_in[31] == 25 && r.img.int_in[16] == 0x1234 && r.img.byte_in[32] == 4);
  CHECK(r.img.bool_in[12][0] == 1 && r.img.bool_in[12][1] == 1);
  // An unknown page: only the switch and Count.
  r.message(0xFF10, 0x10, 255, {9, 0x77, 0x77, 0xFF, 0xFF, 0xFF, 0xFF, 5}, 700);
  r.engine.tick(r.at(701));
  r.image.copy_to_plc(r.rt);
  CHECK(r.img.byte_in[30] == 9 && r.img.byte_in[31] == 25 && r.img.int_in[16] == 0x1234 && r.img.byte_in[32] == 5);
  std::string js = status_json(r, 701);
  CHECK_MSG(js.find(R"("unknown_pages":1)") != std::string::npos, js);
  // Page 2 goes on, page 1 stopped at 510: Temp's valid bit drops at 810.
  r.message(0xFF10, 0x10, 255, {2, 0x35, 0x12, 0xFF, 0xFF, 0xFF, 0xFF, 6}, 800);
  r.engine.tick(r.at(809));
  r.image.copy_to_plc(r.rt);
  CHECK(r.img.bool_in[12][0] == 1);
  r.engine.tick(r.at(810));
  r.image.copy_to_plc(r.rt);
  CHECK(r.img.bool_in[12][0] == 0 && r.img.bool_in[12][1] == 1);
  // A multi-packet message (BAM or RTS/CTS, reassembled by the kernel) with page 3.
  r.message(0xFF10, 0x10, 255, {3, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 7, 0xFF, 0xFF, 99, 0xFF}, 820);
  r.engine.tick(r.at(821));
  r.image.copy_to_plc(r.rt);
  CHECK(r.img.byte_in[30] == 3 && r.img.byte_in[33] == 99 && r.img.byte_in[32] == 7);
  CHECK(r.img.int_in[16] == 0x1235);
}

TEST(j1939_engine_sends_all_and_rotate) {
  Rig r(mux_config());
  r.claim();
  r.img.byte_out[10] = 0xA1;
  r.img.byte_out[11] = 0xB1;
  r.img.byte_out[12] = 0xA2;
  r.img.byte_out[13] = 0xB2;
  r.image.copy_from_plc(r.rt);
  r.engine.tick(r.at(510));
  auto a = r.socket.of(0xFF11);
  CHECK(a.size() == 2 && a[0].data[0] == 1 && a[0].data[1] == 0xA1 && a[1].data[0] == 2 && a[1].data[1] == 0xB1);
  auto b = r.socket.of(0xFF12);
  CHECK(b.size() == 1 && b[0].data[0] == 1 && b[0].data[1] == 0xA2);
  r.engine.tick(r.at(610));
  b = r.socket.of(0xFF12);
  CHECK(r.socket.of(0xFF11).size() == 4 && b.size() == 2 && b[1].data[0] == 2 && b[1].data[1] == 0xB2);
  r.engine.tick(r.at(710));
  b = r.socket.of(0xFF12);
  CHECK(b.size() == 3 && b[2].data[0] == 1);
  // A request is answered with every page ("all") or the next one ("rotate").
  r.request(0xFF11, 0x20, 128, 720);
  CHECK(r.socket.of(0xFF11).size() == 8);
  r.request(0xFF12, 0x20, 128, 730);
  b = r.socket.of(0xFF12);
  CHECK(b.size() == 4 && b[3].data[0] == 2);
  std::string js = status_json(r, 730);
  CHECK_MSG(js.find(R"("pages":"all")") != std::string::npos && js.find(R"("pages":"rotate")") != std::string::npos,
            js);
}

TEST(j1939_engine_sends_the_program_page) {
  Rig r(mux_config());
  r.claim();
  r.img.byte_out[14] = 1;
  r.img.byte_out[15] = 0x55;
  r.img.int_out[8] = 0x0302;
  r.image.copy_from_plc(r.rt);
  r.engine.tick(r.at(510));
  auto p = r.socket.of(0xFF13);
  CHECK(p.size() == 1 && (p[0].data == std::vector<uint8_t>{1, 0x55, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF}));
  r.img.byte_out[14] = 2;
  r.image.copy_from_plc(r.rt);
  r.engine.tick(r.at(520));
  p = r.socket.of(0xFF13);
  CHECK(p.size() == 2 && (p[1].data == std::vector<uint8_t>{2, 0x02, 0x03, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF}));
  // A page the switch does not know: the switch alone, flagged in the status.
  r.img.byte_out[14] = 7;
  r.image.copy_from_plc(r.rt);
  r.engine.tick(r.at(530));
  p = r.socket.of(0xFF13);
  CHECK(p.size() == 3 && (p[2].data == std::vector<uint8_t>{7, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF}));
  std::string js = status_json(r, 530);
  CHECK_MSG(js.find(R"("pages":"program","unknown_page":true)") != std::string::npos, js);
}

// ---------------------------------------------------------------------------
// Diagnostic messages (j1939-diagnostics): the codec against the byte
// fixtures shared with the PC tools (test/fixtures/j1939-dm/cases.json)

std::vector<uint8_t> hex_bytes(const char* text) {
  std::vector<uint8_t> out;
  std::istringstream in(text);
  unsigned v;
  while (in >> std::hex >> v) out.push_back(static_cast<uint8_t>(v));
  return out;
}

// The fixture cases of one kind; the caller deletes the returned root.
cJSON* dm_fixtures() {
  std::ifstream f(FIXTURES_DIR "/j1939-dm/cases.json");
  std::stringstream ss;
  ss << f.rdbuf();
  cJSON* root = cJSON_Parse(ss.str().c_str());
  if (!root) {
    std::fprintf(stderr, "cannot read %s\n", FIXTURES_DIR "/j1939-dm/cases.json");
    std::abort();
  }
  return root;
}

std::string str_of(const cJSON* o, const char* key) {
  const cJSON* v = cJSON_GetObjectItemCaseSensitive(o, key);
  return cJSON_IsString(v) ? v->valuestring : "";
}

double num_of(const cJSON* o, const char* key) {
  const cJSON* v = cJSON_GetObjectItemCaseSensitive(o, key);
  return cJSON_IsNumber(v) ? v->valuedouble : -1;
}

uint8_t lamp_bits(const cJSON* lamps) {
  uint8_t b = 0;
  const cJSON* l;
  cJSON_ArrayForEach(l, lamps) {
    std::string n = l->valuestring;
    if (n == "mil") b |= kJ1939LampMil;
    if (n == "red") b |= kJ1939LampRed;
    if (n == "amber") b |= kJ1939LampAmber;
    if (n == "protect") b |= kJ1939LampProtect;
  }
  return b;
}

TEST(j1939_dm_codec_fixtures) {
  cJSON* root = dm_fixtures();
  int dm = 0, own = 0, dm13 = 0, dm22 = 0;
  const cJSON* c;
  cJSON_ArrayForEach(c, cJSON_GetObjectItemCaseSensitive(root, "cases")) {
    const std::string kind = str_of(c, "kind"), name = str_of(c, "name");
    std::vector<uint8_t> data = hex_bytes(str_of(c, "data").c_str());
    if (kind == "dm") {
      ++dm;
      DmList l;
      CHECK_MSG(dm_parse(data.data(), data.size(), l), name);
      CHECK_MSG(l.lamps == num_of(c, "lamps") && l.flash == num_of(c, "flash"), name);
      const cJSON* want = cJSON_GetObjectItemCaseSensitive(c, "dtcs");
      CHECK_MSG(l.count == static_cast<size_t>(cJSON_GetArraySize(want)) && l.dtcs.size() == l.count, name);
      size_t k = 0;
      const cJSON* d;
      cJSON_ArrayForEach(d, want) {
        if (k >= l.dtcs.size()) break;
        const J1939Dtc& got = l.dtcs[k++];
        J1939Dtc exp{static_cast<uint32_t>(num_of(d, "spn")), static_cast<uint8_t>(num_of(d, "fmi")),
                     static_cast<uint8_t>(num_of(d, "oc")), cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(d, "cm"))};
        CHECK_MSG(got == exp, name + ": code " + std::to_string(k));
        uint32_t value = static_cast<uint32_t>(num_of(d, "value"));
        CHECK_MSG(dtc_value(got) == value && dtc_from_value(value) == exp, name + ": value");
      }
      // Built back, the same bytes.
      CHECK_MSG(dm_build(l.lamps, l.flash, l.dtcs) == data, name + ": build");
    } else if (kind == "own") {
      ++own;
      J1939Diagnostics diag;
      const cJSON* a;
      std::vector<int> ocs;
      cJSON_ArrayForEach(a, cJSON_GetObjectItemCaseSensitive(c, "active")) {
        J1939OwnDtc o;
        o.spn = static_cast<uint32_t>(num_of(a, "spn"));
        o.fmi = static_cast<uint8_t>(num_of(a, "fmi"));
        o.lamps = lamp_bits(cJSON_GetObjectItemCaseSensitive(a, "lamps"));
        std::string fl = str_of(a, "flash");
        o.flash = fl == "fast" ? 1 : fl == "slow" ? 0 : -1;
        diag.dtcs.push_back(o);
        ocs.push_back(static_cast<int>(num_of(a, "oc")));
      }
      diag.has_lamps_location = true;
      OwnDtcs t(diag);
      const uint8_t lamps = static_cast<uint8_t>(num_of(c, "lamps_output"));
      // Each code goes active OC times and stays active.
      int rounds = 0;
      for (int oc : ocs) rounds = std::max(rounds, oc);
      for (int round = 1; round <= rounds; ++round) {
        std::vector<uint8_t> on, between;
        for (int oc : ocs) {
          on.push_back(oc >= 1 ? 1 : 0);
          between.push_back(oc > round ? 0 : (oc >= 1 ? 1 : 0));
        }
        t.update(on, lamps);
        if (round < rounds) t.update(between, lamps);
      }
      if (!rounds) t.update(std::vector<uint8_t>(ocs.size(), 0), lamps);
      CHECK_MSG(t.dm1() == data, name);
    } else if (kind == "dm13") {
      ++dm13;
      Dm13 m = dm13_decode(data.data(), data.size());
      const cJSON* cmd = cJSON_GetObjectItemCaseSensitive(c, "command");
      Dm13Command want = cJSON_IsNull(cmd) ? Dm13Command::None
                         : std::string(cmd->valuestring) == "stop" ? Dm13Command::Stop
                                                                   : Dm13Command::Start;
      CHECK_MSG(m.command == want, name);
      CHECK_MSG(m.hold == (name.find("hold") != std::string::npos), name);
    } else if (kind == "dm22") {
      ++dm22;
      uint8_t b[4] = {data[5], data[6], data[7], 0};
      J1939Dtc d = dtc_from_bytes(b);
      CHECK_MSG(d.spn == num_of(c, "spn") && d.fmi == num_of(c, "fmi"), name);
      std::vector<uint8_t> nack = dm22_nack(data.data(), data.size());
      if (data[0] == 0x11) {
        CHECK_MSG(nack.size() == 8 && nack[0] == 0x13 && nack[1] == 0 && nack[5] == data[5] && nack[6] == data[6] &&
                      nack[7] == data[7],
                  name);
      } else {
        CHECK_MSG(nack.empty(), name);  // an answer is not answered
      }
    }
  }
  CHECK_MSG(dm >= 5 && own >= 3 && dm13 == 3 && dm22 == 2,
            "fixture kinds dm " + std::to_string(dm) + ", own " + std::to_string(own) + ", dm13 " +
                std::to_string(dm13) + ", dm22 " + std::to_string(dm22));
  cJSON_Delete(root);
}

TEST(j1939_dm_value_layout) {
  // The spec's example: SPN 520192, FMI 3, OC 2.
  CHECK(dtc_value(J1939Dtc{520192, 3, 2, false}) == 0x021FF000u);
  CHECK(dtc_value(J1939Dtc{91, 3, 1, true}) == 0x8118005Bu);
  CHECK((dtc_from_value(0xFFFFFFFFu) == J1939Dtc{0x7FFFF, 31, 127, true}));
  // Too short, and the 0xFF filler of a one-code message.
  DmList l;
  const uint8_t shorty[5] = {0, 0xFF, 0, 0, 0};
  CHECK(!dm_parse(shorty, 5, l));
  const uint8_t odd[9] = {0x04, 0xFF, 0x00, 0xF0, 0xE3, 0x01, 0xFF, 0xFF, 0xFF};
  CHECK(dm_parse(odd, 9, l) && l.count == 1);
}

std::vector<std::string> g_logged;
void capture_log(LogLevel, const char* msg) { g_logged.push_back(msg); }

TEST(j1939_dm_store) {
  DmStore store;
  auto t = clock_type::now();
  // 70 codes: 64 kept, all counted.
  std::vector<J1939Dtc> many;
  for (uint32_t k = 0; k < 70; ++k) many.push_back(J1939Dtc{520192 + k, 3, 1, false});
  std::vector<uint8_t> big = dm_build(0x04, 0xFF, many);
  const DmStore::Source* s = store.on_dm1(0, big.data(), big.size(), t);
  CHECK(s && s->count == 70 && s->dtcs.size() == kDmStoredCodes && s->dtcs[63].spn == 520192 + 63);
  // The older SPN format: passed on, counted and logged once per source.
  g_logged.clear();
  set_log_sink(capture_log);
  std::vector<uint8_t> cm = hex_bytes("04 FF 5B 00 03 81 FF FF");
  for (int k = 0; k < 3; ++k) store.on_dm1(3, cm.data(), cm.size(), t + milliseconds(k));
  std::vector<uint8_t> cm2 = hex_bytes("04 FF 5B 00 03 81 FF FF");
  store.on_dm1(4, cm2.data(), cm2.size(), t);
  set_log_sink(nullptr);
  CHECK_MSG(g_logged.size() == 2 && g_logged[0].find("address 3 ") != std::string::npos &&
                g_logged[1].find("address 4 ") != std::string::npos,
            std::to_string(g_logged.size()) + " log lines");
  const DmStore::Source* three = store.find(3);
  CHECK(three && three->dm1_count == 3 && three->old_format == 3 && three->dtcs[0].cm);
  CHECK(dtc_value(three->dtcs[0]) & 0x80000000u);
  CHECK(!store.find(7));
}

// ---------------------------------------------------------------------------
// The engine's diagnostic messages

// engine_config() plus diagnostics: ECU 0 watched (status %IX40.0, lamps
// %IB41, flash %IB42, count %IB43, four codes from %ID56), and with `own`
// two own codes (%QX40.0 amber, %QX40.1 red fast), lamps %QB41 and clears
// at %IB44.
Config dm_config(bool own = true) {
  Config cfg = engine_config();
  J1939Diagnostics& d = cfg.j1939.diagnostics;
  J1939DmRx w;
  w.has_source = true;
  w.source = 0;
  w.timeout_ms = 3000;
  w.has_status_location = true;
  w.status_location = loc("%IX40.0");
  w.has_lamps_location = true;
  w.lamps_location = loc("%IB41");
  w.has_flash_location = true;
  w.flash_location = loc("%IB42");
  w.has_count_location = true;
  w.count_location = loc("%IB43");
  w.has_dtcs_location = true;
  w.dtcs_location = loc("%ID56");
  w.dtcs = 4;
  d.rx.push_back(w);
  if (own) {
    J1939OwnDtc a;
    a.spn = 520192;
    a.fmi = 3;
    a.active_location = loc("%QX40.0");
    a.lamps = kJ1939LampAmber;
    d.dtcs.push_back(a);
    J1939OwnDtc b;
    b.spn = 520193;
    b.fmi = 1;
    b.active_location = loc("%QX40.1");
    b.lamps = kJ1939LampRed;
    b.flash = 1;
    d.dtcs.push_back(b);
    d.has_lamps_location = true;
    d.lamps_location = loc("%QB41");
    d.has_clear_location = true;
    d.clear_location = loc("%IB44");
  }
  return cfg;
}

// The program's own codes as the scan writes them.
void own_bits(Rig& r, bool a, bool b, uint8_t lamps = 0) {
  r.img.bool_out[40][0] = a;
  r.img.bool_out[40][1] = b;
  r.img.byte_out[41] = lamps;
  r.image.copy_from_plc(r.rt);
}

TEST(j1939_dm_receive_into_the_plc) {
  Rig r(dm_config(false));
  r.claim();
  // Five codes (22 bytes, BAM): count 5, the first four codes.
  r.message(kPgnDm1, 0, 255, hex_bytes("40 FF 64 00 01 01 6E 00 00 05 BE 00 02 7E 00 F0 E3 02 FF FF FF 7F"), 510);
  r.engine.tick(r.at(511));
  r.image.copy_to_plc(r.rt);
  CHECK(r.img.bool_in[40][0] == 1 && r.img.byte_in[41] == 0x40 && r.img.byte_in[42] == 0xFF &&
        r.img.byte_in[43] == 5);
  CHECK(r.img.dint_in[56] == 17301604u && r.img.dint_in[57] == 83886190u && r.img.dint_in[58] == 2114977982u &&
        r.img.dint_in[59] == 35647488u && r.img.dint_in[60] == 0);
  // Another ECU's DM1 is stored, not mapped.
  r.message(kPgnDm1, 3, 255, hex_bytes("04 FF 00 F0 E3 02 FF FF"), 520);
  r.engine.tick(r.at(521));
  r.image.copy_to_plc(r.rt);
  CHECK(r.img.byte_in[43] == 5);
  // The fault cleared on the ECU.
  r.message(kPgnDm1, 0, 255, hex_bytes("00 FF 00 00 00 00 FF FF"), 1500);
  r.engine.tick(r.at(1501));
  r.image.copy_to_plc(r.rt);
  CHECK(r.img.byte_in[43] == 0 && r.img.byte_in[41] == 0 && r.img.dint_in[56] == 0 && r.img.dint_in[59] == 0);
  // ECU silent: the status bit drops 3 s later, the values hold.
  r.message(kPgnDm1, 0, 255, hex_bytes("04 FF 00 F0 E3 02 FF FF"), 2000);
  r.engine.tick(r.at(4999));
  r.image.copy_to_plc(r.rt);
  CHECK(r.img.bool_in[40][0] == 1);
  r.engine.tick(r.at(5000));
  r.image.copy_to_plc(r.rt);
  CHECK(r.img.bool_in[40][0] == 0 && r.img.byte_in[43] == 1 && r.img.dint_in[56] == 35647488u &&
        r.img.byte_in[41] == 4);
  std::string js = status_json(r, 5000);
  CHECK_MSG(js.find(R"("dm":{"sources":[{"address":0,"lamps":4,"flash":255,"count":1,"truncated":0,)"
                    R"("dtcs":[{"spn":520192,"fmi":3,"oc":2,"cm":false}],"age_ms":3000,"dm1_count":3,)"
                    R"("old_spn_format":false},{"address":3,)") != std::string::npos &&
                js.find(R"("watched":[{"index":0,"source":0,"source_name":null,"timed_out":true,"timeouts":1}],)"
                        R"("own":null})") != std::string::npos,
            js);
  // Without own DM1 a Request for DM1 to us is NACKed like any PGN we do not send.
  r.request(kPgnDm1, 0x20, 128, 5100);
  auto n = r.socket.of(kPgnAcknowledgement);
  CHECK(n.size() == 1 && n[0].data[0] == 1 && n[0].data[5] == 0xCA && n[0].data[6] == 0xFE);
  CHECK(r.socket.of(kPgnDm1).empty());
  // The receive socket takes the diagnostic messages.
  std::vector<uint32_t> pgns = r.engine.receive_pgns();
  for (uint32_t p : {kPgnDm1, kPgnDm2, kPgnAcknowledgement, kPgnDm13, kPgnDm22})
    CHECK(std::find(pgns.begin(), pgns.end(), p) != pgns.end());
}

TEST(j1939_dm_send_own) {
  Rig r(dm_config());
  // Nothing before the claim.
  r.engine.bus_up(r.t0);
  r.engine.tick(r.at(250));
  CHECK(r.socket.of(kPgnDm1).empty());
  r.engine.tick(r.at(500));
  // No faults: lamps off and the all-zero code, priority 6, global.
  auto d = r.socket.of(kPgnDm1);
  CHECK(d.size() == 1 && d[0].data == hex_bytes("00 FF 00 00 00 00 FF FF") && d[0].priority == 6 &&
        d[0].destination == 255);
  // Fault raised: sent at once, OC 1.
  own_bits(r, true, false);
  r.engine.tick(r.at(510));
  d = r.socket.of(kPgnDm1);
  CHECK(d.size() == 2 && d[1].data == hex_bytes("04 FF 00 F0 E3 01 FF FF"));
  // A second change within the second waits: at most one change-driven send per 1000 ms.
  own_bits(r, true, true);
  r.engine.tick(r.at(600));
  CHECK(r.socket.of(kPgnDm1).size() == 2);
  r.engine.tick(r.at(1509));
  CHECK(r.socket.of(kPgnDm1).size() == 2);
  r.engine.tick(r.at(1510));
  d = r.socket.of(kPgnDm1);
  CHECK(d.size() == 3 && d[2].data == hex_bytes("14 DF 00 F0 E3 01 01 F0 E1 01"));
  // Every second.
  r.engine.tick(r.at(2509));
  CHECK(r.socket.of(kPgnDm1).size() == 3);
  r.engine.tick(r.at(2510));
  CHECK(r.socket.of(kPgnDm1).size() == 4);
  // Lamps from the program are ORed in; a change a second after the last
  // change-driven send goes out at once.
  own_bits(r, true, true, kJ1939LampProtect);
  r.engine.tick(r.at(2600));
  d = r.socket.of(kPgnDm1);
  CHECK(d.size() == 5 && d[4].data[0] == 0x15);
  // The fault goes away: no longer in DM1 (with the next periodic send,
  // within a second of the last change), in DM2 with its count.
  own_bits(r, false, true);
  r.engine.tick(r.at(2700));
  CHECK(r.socket.of(kPgnDm1).size() == 5);
  r.engine.tick(r.at(3600));
  d = r.socket.of(kPgnDm1);
  CHECK(d.size() == 6 && d[5].data == hex_bytes("10 DF 01 F0 E1 01 FF FF"));
  own_bits(r, true, true);
  r.engine.tick(r.at(4600));
  own_bits(r, false, true);
  r.engine.tick(r.at(5600));
  r.request(kPgnDm2, 0x20, 128, 5700);
  auto p = r.socket.of(kPgnDm2);
  CHECK(p.size() == 1 && p[0].destination == 255 && p[0].data == hex_bytes("10 DF 00 F0 E3 02 FF FF"));
  std::string js = status_json(r, 5700);
  CHECK_MSG(js.find(R"("own":{"active":[{"spn":520193,"fmi":1,"oc":1,"lamps":["red"],"flash":"fast"}],)"
                    R"("previous":[{"spn":520192,"fmi":3,"oc":2}],"lamps":16,"flash":223,"clears":0,)"
                    R"("suspended":false,"dm1_sent":)") != std::string::npos,
            js);
  // Requests for DM1, global too, answered with the current list through the reply gate.
  size_t before = r.socket.of(kPgnDm1).size();
  r.request(kPgnDm1, 0x20, 255, 5710);
  r.request(kPgnDm1, 0x20, 128, 5720);
  CHECK(r.socket.of(kPgnDm1).size() == before + 1);
  r.request(kPgnDm1, 0x20, 128, 5770);
  CHECK(r.socket.of(kPgnDm1).size() == before + 2);
  CHECK(r.socket.of(kPgnAcknowledgement).empty());
}

TEST(j1939_dm_occurrence_count_stops_at_126) {
  J1939Diagnostics diag;
  J1939OwnDtc a;
  a.spn = 520192;
  diag.dtcs.push_back(a);
  OwnDtcs t(diag);
  for (int k = 0; k < 200; ++k) {
    t.update({1}, 0);
    t.update({0}, 0);
  }
  CHECK(t.oc(0) == 126 && t.previous().size() == 1);
}

TEST(j1939_dm_clears) {
  Rig r(dm_config());
  r.claim();
  own_bits(r, true, true);
  r.engine.tick(r.at(510));
  own_bits(r, false, true);
  r.engine.tick(r.at(520));
  own_bits(r, true, true);
  r.engine.tick(r.at(530));  // 520192 at OC 2, still active
  own_bits(r, true, false);
  r.engine.tick(r.at(540));  // 520193 previously active
  // A tool clears with DM11: ACK, clear_location + 1, DM2 empty, the next DM1 with OC 1.
  r.request(kPgnDm11, 249, 128, 600);
  auto ack = r.socket.of(kPgnAcknowledgement);
  CHECK(ack.size() == 1 && ack[0].data == hex_bytes("00 FF FF FF F9 D3 FE 00"));
  r.engine.tick(r.at(601));
  r.image.copy_to_plc(r.rt);
  CHECK(r.img.byte_in[44] == 1);
  r.request(kPgnDm2, 249, 128, 610);
  CHECK(r.socket.of(kPgnDm2).back().data == hex_bytes("04 FF 00 00 00 00 FF FF"));
  r.engine.tick(r.at(1600));
  CHECK(r.socket.of(kPgnDm1).back().data == hex_bytes("04 FF 00 F0 E3 01 FF FF"));
  // DM3 globally: carried out without ACK.
  own_bits(r, false, false);
  r.engine.tick(r.at(1700));
  r.request(kPgnDm3, 249, 255, 1800);
  CHECK(r.socket.of(kPgnAcknowledgement).size() == 1);
  r.engine.tick(r.at(1801));
  r.image.copy_to_plc(r.rt);
  CHECK(r.img.byte_in[44] == 2);
  r.request(kPgnDm2, 249, 128, 1810);
  CHECK(r.socket.of(kPgnDm2).back().data == hex_bytes("00 FF 00 00 00 00 FF FF"));
  // DM22 to us: its negative acknowledgement, to the sender.
  r.message(kPgnDm22, 249, 128, hex_bytes("11 FF FF FF FF 00 F0 E3"), 1900);
  auto n22 = r.socket.of(kPgnDm22);
  CHECK(n22.size() == 1 && n22[0].destination == 249 && n22[0].data == hex_bytes("13 00 FF FF FF 00 F0 E3"));
  // DM22 to another ECU: nothing.
  r.message(kPgnDm22, 249, 3, hex_bytes("11 FF FF FF FF 00 F0 E3"), 2000);
  CHECK(r.socket.of(kPgnDm22).size() == 1);
  std::string js = status_json(r, 2000);
  CHECK_MSG(js.find(R"("clears":2)") != std::string::npos, js);
}

TEST(j1939_dm_clears_refused) {
  Config cfg = dm_config();
  cfg.j1939.diagnostics.accept_clear = false;
  Rig r(cfg);
  r.claim();
  own_bits(r, true, false);
  r.engine.tick(r.at(510));
  own_bits(r, false, false);
  r.engine.tick(r.at(520));
  r.request(kPgnDm3, 249, 128, 600);
  auto n = r.socket.of(kPgnAcknowledgement);
  CHECK(n.size() == 1 && n[0].data == hex_bytes("01 FF FF FF F9 CC FE 00"));
  r.request(kPgnDm11, 249, 255, 610);
  CHECK(r.socket.of(kPgnAcknowledgement).size() == 1);
  r.engine.tick(r.at(611));
  r.image.copy_to_plc(r.rt);
  CHECK(r.img.byte_in[44] == 0);
  r.request(kPgnDm2, 249, 128, 620);
  CHECK(r.socket.of(kPgnDm2).back().data == hex_bytes("00 FF 00 F0 E3 01 FF FF"));
}

TEST(j1939_dm13_suspends_broadcasts) {
  Rig r(dm_config());
  r.claim();
  r.img.int_out[0] = 1;
  r.img.byte_out[4] = 1;
  r.image.copy_from_plc(r.rt);
  r.engine.tick(r.at(510));
  // A tool stops broadcasts globally and repeats it every 5 s.
  r.message(kPgnDm13, 249, 255, hex_bytes("3F FF FF FF FF FF FF FF"), 600);
  size_t periodic = r.socket.of(0xFF01).size(), dm1 = r.socket.of(kPgnDm1).size();
  for (int ms = 600; ms < 11600; ms += 10) {
    if (ms == 5600) r.message(kPgnDm13, 249, 255, hex_bytes("3F FF FF FF FF FF FF FF"), ms);
    if (ms == 3000) {
      // On-change sends and request answers go on.
      r.img.byte_out[4] = 2;
      r.image.copy_from_plc(r.rt);
      r.request(0xFF01, 0x20, 128, ms);
    }
    r.engine.tick(r.at(ms));
  }
  CHECK(r.socket.of(0xFF01).size() == periodic + 1);  // the request's answer
  CHECK(r.socket.of(kPgnDm1).size() == dm1);
  CHECK(r.socket.of(0xFF02).size() == 2);
  CHECK(r.engine.suspended());
  std::string js = status_json(r, 11000);
  CHECK_MSG(js.find(R"("suspended":true)") != std::string::npos, js);
  // 6 s after the last stop they resume.
  r.engine.tick(r.at(11600));
  CHECK(!r.engine.suspended() && r.socket.of(0xFF01).size() == periodic + 2 &&
        r.socket.of(kPgnDm1).size() == dm1 + 1);
  // Hold keeps a suspension going; start ends it.
  r.message(kPgnDm13, 249, 128, hex_bytes("3F FF FF FF FF FF FF FF"), 12000);
  r.message(kPgnDm13, 249, 255, hex_bytes("FF FF FF 0F FF FF FF FF"), 17000);
  r.engine.tick(r.at(18500));
  CHECK(r.engine.suspended());
  r.message(kPgnDm13, 249, 255, hex_bytes("7F FF FF FF FF FF FF FF"), 18600);
  r.engine.tick(r.at(18601));
  CHECK(!r.engine.suspended());
  // To another ECU: ignored.
  r.message(kPgnDm13, 249, 3, hex_bytes("3F FF FF FF FF FF FF FF"), 18700);
  r.engine.tick(r.at(18701));
  CHECK(!r.engine.suspended());
}

TEST(j1939_dm13_ignored_when_off) {
  Config cfg = dm_config();
  cfg.j1939.diagnostics.dm13 = false;
  Rig r(cfg);
  r.claim();
  r.message(kPgnDm13, 249, 255, hex_bytes("3F FF FF FF FF FF FF FF"), 600);
  r.engine.tick(r.at(601));
  CHECK(!r.engine.suspended());
  r.engine.tick(r.at(1600));
  CHECK(r.socket.of(kPgnDm1).size() == 2);
}

// ---------------------------------------------------------------------------
// DM jobs: the diagnostics operations and the PLC blocks

struct JobLog {
  std::vector<J1939Engine::DmResult> results;
  J1939Engine::DmDone done() {
    return [this](const J1939Engine::DmResult& r) { results.push_back(r); };
  }
};

TEST(j1939_dm_jobs) {
  Rig r(dm_config(false));
  JobLog log;
  // Before the claim: no address.
  r.engine.bus_up(r.t0);
  CHECK(r.engine.dm_start(J1939Engine::DmOp::ReadDm2, 0, 1000, r.at(10), log.done()) ==
        CANWORKS_J1939_ERR_NO_ADDRESS);
  CHECK(j1939_dm_error_text(CANWORKS_J1939_ERR_NO_ADDRESS, true, 0, 1000, r.engine.state()) ==
        "network has no address (state: claiming)");
  r.engine.tick(r.at(250));
  r.engine.tick(r.at(500));
  // A DM2 read: a Request for DM2 to the address, answered by its DM2.
  CHECK(r.engine.dm_start(J1939Engine::DmOp::ReadDm2, 0, 1000, r.at(510), log.done()) == 0);
  auto q = r.socket.of(kPgnRequest);
  CHECK(q.back().destination == 0 && q.back().data == hex_bytes("CB FE 00"));
  // A second job for the same address: busy, also a clear.
  CHECK(r.engine.dm_start(J1939Engine::DmOp::ClearDm3, 0, 1000, r.at(511), log.done()) ==
        CANWORKS_J1939_ERR_PENDING);
  CHECK(j1939_dm_error_text(CANWORKS_J1939_ERR_PENDING, true, 0, 1000, r.engine.state()) ==
        "busy: a DM2 read or clear for address 0 is pending");
  r.message(kPgnDm2, 0, 255, hex_bytes("04 FF 00 F0 E3 02 FF FF"), 520);
  CHECK(log.results.size() == 1 && !log.results[0].error && log.results[0].list.count == 1);
  cJSON* j = j1939_dm_result_json(log.results[0], true);
  char* t = cJSON_PrintUnformatted(j);
  CHECK_MSG(std::string(t) ==
                R"({"address":0,"lamps":4,"flash":255,"count":1,"dtcs":[{"spn":520192,"fmi":3,"oc":2,"cm":false}]})",
            t);
  cJSON_free(t);
  cJSON_Delete(j);
  // A clear: done on the ECU's ACK, an error on its NACK.
  CHECK(r.engine.dm_start(J1939Engine::DmOp::ClearDm11, 0, 1000, r.at(600), log.done()) == 0);
  CHECK(r.socket.of(kPgnRequest).back().data == hex_bytes("D3 FE 00"));
  r.message(kPgnAcknowledgement, 0, 255, hex_bytes("00 FF FF FF 80 D3 FE 00"), 610);
  CHECK(log.results.size() == 2 && !log.results[1].error);
  j = j1939_dm_result_json(log.results[1], false);
  t = cJSON_PrintUnformatted(j);
  CHECK_MSG(std::string(t) == R"({"address":0,"result":"ack"})", t);
  cJSON_free(t);
  cJSON_Delete(j);
  CHECK(r.engine.dm_start(J1939Engine::DmOp::ClearDm3, 0, 1000, r.at(700), log.done()) == 0);
  // Another requester's ACK, or one for another PGN, is not ours.
  r.message(kPgnAcknowledgement, 0, 255, hex_bytes("00 FF FF FF 81 CC FE 00"), 705);
  r.message(kPgnAcknowledgement, 0, 255, hex_bytes("00 FF FF FF 80 D3 FE 00"), 706);
  CHECK(log.results.size() == 2);
  r.message(kPgnAcknowledgement, 0, 128, hex_bytes("01 FF FF FF 80 CC FE 00"), 710);
  CHECK(log.results.size() == 3 && log.results[2].error == CANWORKS_J1939_ERR_NACK);
  CHECK(j1939_dm_error_text(CANWORKS_J1939_ERR_NACK, false, 0, 1000, r.engine.state()) == "NACK from 0");
  // No answer: a timeout.
  CHECK(r.engine.dm_start(J1939Engine::DmOp::ReadDm2, 7, 300, r.at(800), log.done()) == 0);
  r.engine.tick(r.at(1099));
  CHECK(log.results.size() == 3);
  r.engine.tick(r.at(1100));
  CHECK(log.results.size() == 4 && log.results[3].error == CANWORKS_J1939_ERR_TIMEOUT && log.results[3].address == 7);
  CHECK(j1939_dm_error_text(CANWORKS_J1939_ERR_TIMEOUT, true, 7, 1000, r.engine.state()) ==
        "no answer from 7 within 1000 ms");
  // Global clears are done once sent.
  CHECK(r.engine.dm_start(J1939Engine::DmOp::ClearDm11, 255, 1000, r.at(1200), log.done()) == 0);
  CHECK(log.results.size() == 5 && log.results[4].address == 255 && r.socket.of(kPgnRequest).back().destination == 255);
  j = j1939_dm_result_json(log.results[4], false);
  t = cJSON_PrintUnformatted(j);
  CHECK_MSG(std::string(t) == R"({"address":255,"result":"sent"})", t);
  cJSON_free(t);
  cJSON_Delete(j);
  // The bus goes: pending jobs end.
  CHECK(r.engine.dm_start(J1939Engine::DmOp::ReadDm2, 9, 1000, r.at(1300), log.done()) == 0);
  r.engine.bus_lost("CAN interface vcan0 is down");
  CHECK(log.results.size() == 6 && log.results[5].error == CANWORKS_J1939_ERR_BUS);
  CHECK(j1939_dm_error_text(CANWORKS_J1939_ERR_BUS, true, 9, 1000, r.engine.state()) ==
        "network has no address (state: no bus)");
}

TEST(j1939_dm_plc_jobs) {
  Rig r(dm_config(false));
  J1939PlcJobs& jobs = J1939PlcJobs::instance();
  const auto* api = static_cast<const canworks_j1939_api_v1*>(canworks_j1939_api_table(CANWORKS_J1939_API_VERSION));
  CHECK(api && api->size == sizeof(canworks_j1939_api_v1) && !canworks_j1939_api_table(2));
  uint16_t err = 0;
  // Not running yet.
  CHECK(!api->dm_read_start(0, 0, 0, 0, &err) && err == CANWORKS_J1939_ERR_NOT_RUNNING);
  jobs.open({true, false});
  CHECK(!api->dm_read_start(0, 0, 0, 0, &err) && err == CANWORKS_J1939_ERR_NOT_RUNNING);  // bus thread not there
  jobs.set_attached(0, true);
  CHECK(!api->dm_read_start(1, 0, 0, 0, &err) && err == CANWORKS_J1939_ERR_NOT_J1939);
  CHECK(!api->dm_read_start(2, 0, 0, 0, &err) && err == CANWORKS_J1939_ERR_NETWORK);
  CHECK(!api->dm_read_start(0, 254, 0, 0, &err) && err == CANWORKS_J1939_ERR_INPUT);
  CHECK(!api->dm_clear_start(0, 254, 0, 0, &err) && err == CANWORKS_J1939_ERR_INPUT);
  r.claim();
  // A DM1 never seen.
  uint32_t h = api->dm_read_start(0, 7, 0, 0, &err);
  CHECK(h && !err);
  canworks_j1939_dm out;
  CHECK(api->dm_read_poll(h, &out, &err) == 0);
  r.engine.serve_plc(0, r.at(510));
  CHECK(api->dm_read_poll(h, &out, &err) == 2 && err == CANWORKS_J1939_ERR_NO_DM1);
  // The latest DM1, without bus traffic.
  r.message(kPgnDm1, 0, 255, hex_bytes("14 DF 00 F0 E3 02 01 F0 E1 01"), 520);
  size_t sent = r.socket.sent.size();
  h = api->dm_read_start(0, 0, 0, 0, &err);
  r.engine.serve_plc(0, r.at(770));
  CHECK(api->dm_read_poll(h, &out, &err) == 1 && !err);
  CHECK(out.lamps == 0x14 && out.flash == 0xDF && out.count == 2 && out.age_ms == 250 &&
        out.dtcs[0] == 35647488u && out.dtcs[1] == 17821697u && out.dtcs[2] == 0);
  CHECK(r.socket.sent.size() == sent);
  CHECK(api->dm_read_poll(h, &out, &err) == 2 && err == CANWORKS_J1939_ERR_CANCELLED);  // used up
  // DM2 by Request; a second job for the address meanwhile is refused (5),
  // whoever starts it.
  h = api->dm_read_start(0, 0, 1, 0, &err);
  uint32_t h2 = api->dm_clear_start(0, 0, 1, 0, &err);
  r.engine.serve_plc(0, r.at(800));
  CHECK(r.socket.of(kPgnRequest).back().destination == 0);
  CHECK(api->dm_clear_poll(h2, &err) == 2 && err == CANWORKS_J1939_ERR_PENDING);
  JobLog log;
  CHECK(r.engine.dm_start(J1939Engine::DmOp::ReadDm2, 0, 1000, r.at(801), log.done()) ==
        CANWORKS_J1939_ERR_PENDING);
  CHECK(api->dm_read_poll(h, &out, &err) == 0);
  r.message(kPgnDm2, 0, 255, hex_bytes("04 FF 00 F0 E3 02 FF FF"), 810);
  CHECK(api->dm_read_poll(h, &out, &err) == 1 && out.count == 1 && out.dtcs[0] == 35647488u && out.age_ms == 0);
  // A clear NACKed: 12; acknowledged: done.
  h = api->dm_clear_start(0, 0, 0, 0, &err);
  r.engine.serve_plc(0, r.at(900));
  r.message(kPgnAcknowledgement, 0, 255, hex_bytes("01 FF FF FF 80 D3 FE 00"), 910);
  CHECK(api->dm_clear_poll(h, &err) == 2 && err == CANWORKS_J1939_ERR_NACK);
  h = api->dm_clear_start(0, 0, 1, 0, &err);
  r.engine.serve_plc(0, r.at(1000));
  r.message(kPgnAcknowledgement, 0, 255, hex_bytes("00 FF FF FF 80 CC FE 00"), 1010);
  CHECK(api->dm_clear_poll(h, &err) == 1 && !err);
  // A read and a clear handle are not interchangeable.
  h = api->dm_clear_start(0, 255, 0, 0, &err);
  r.engine.serve_plc(0, r.at(1100));
  CHECK(api->dm_read_poll(h, &out, &err) == 2 && err == CANWORKS_J1939_ERR_CANCELLED);
  // The PLC stops: pending jobs end with 8.
  h = api->dm_read_start(0, 5, 1, 0, &err);
  r.engine.serve_plc(0, r.at(1200));
  jobs.close();
  CHECK(api->dm_read_poll(h, &out, &err) == 2 && err == CANWORKS_J1939_ERR_CANCELLED);
  jobs.set_attached(0, false);
}

}  // namespace

int main(int argc, char** argv) { return check::run_all(argc, argv); }
