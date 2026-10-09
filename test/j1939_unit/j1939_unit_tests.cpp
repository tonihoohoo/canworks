// Unit tests of the J1939 side of the plugin (j1939-ecu spec): NAME bits,
// signals in message bytes, the address claim, and the engine on a fake
// socket (no kernel J1939 module needed).

#include <cerrno>
#include <chrono>
#include <cstdint>
#include <string>
#include <vector>

#include "address_claim.h"
#include "cJSON.h"
#include "check.hpp"
#include "config.h"
#include "fake_runtime.hpp"
#include "j1939_network.h"
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
  c.on_claim_request();
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
    c.on_claim_request();
    CHECK((a.claims == std::vector<int>{254, 254}));
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
  Config cfg = engine_config();
  J1939Image image;
  FakeSocket socket;
  J1939Engine engine{cfg, image, socket};
  fake_runtime::Image img;
  plugin_runtime_args_t rt;
  clock_type::time_point t0 = clock_type::now();

  Rig() {
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

TEST(j1939_engine_moves_on_contention) {
  Rig r;
  r.claim();
  uint8_t lower[8] = {1, 0, 0, 0, 0, 0, 0, 0};
  r.message(kPgnAddressClaimed, 128, 255, std::vector<uint8_t>(lower, lower + 8), 600);
  CHECK(r.socket.binds.back() == 129 && r.engine.state() == J1939ClaimState::Claiming);
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

TEST(j1939_socket_problems) {
  CHECK(j1939_socket_problem(-EPROTONOSUPPORT, "can0") == "J1939 needs the can-j1939 kernel module (modprobe can-j1939)");
  CHECK(j1939_socket_problem(ENODEV, "can0") == "CAN interface can0 not found");
  CHECK(j1939_socket_problem(-ENETDOWN, "can0") == "CAN interface can0 is down");
}

}  // namespace

int main(int argc, char** argv) { return check::run_all(argc, argv); }
