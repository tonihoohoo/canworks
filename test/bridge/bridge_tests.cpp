// bridge_tests.cpp - the Modbus bridge's server, register rule and own
// registers, without a bus: a small Modbus TCP client talks to the server
// over loopback.

#include <arpa/inet.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <poll.h>
#include <sys/socket.h>
#include <unistd.h>

#include <atomic>
#include <functional>
#include <mutex>
#include <chrono>
#include <cstring>
#include <string>
#include <thread>
#include <vector>

#include "address_list.h"
#include "bridge_blocks.h"
#include "byte_image.h"
#include "check.hpp"
#include "modbus.h"
#include "modbus_server.h"
#include "modbus_client.hpp"

using namespace canworks_bridge;

#define EXPECT(cond)                                                    \
  do {                                                                  \
    if (!(cond)) {                                                      \
      std::printf("  %s:%d: expected %s\n", __FILE__, __LINE__, #cond); \
      ++check::failures();                                              \
    }                                                                   \
  } while (0)

namespace {

// Every address may write (writers ["0.0.0.0/0", "::/0"]).
ServerConfig open_config() {
  ServerConfig cfg;
  std::string err;
  cfg.writers.add("0.0.0.0/0", err);
  cfg.writers.add("::/0", err);
  return cfg;
}

// A server on a free loopback port with a 40-byte input and 16-byte output image.
struct Fixture {
  ByteImage image;
  ModbusServer server{image};
  std::atomic<int> writes{0};
  std::vector<std::string> logs;
  std::mutex log_mu;

  explicit Fixture(ServerConfig cfg = open_config(), size_t in = 40, size_t out = 16) {
    image.resize(in, out);
    cfg.listen = "127.0.0.1:0";
    server.on_write = [this] { ++writes; };
    server.log = [this](const std::string& s) {
      std::lock_guard<std::mutex> l(log_mu);
      logs.push_back(s);
    };
    std::string err;
    if (!server.start(cfg, err)) std::printf("  start: %s\n", err.c_str());
  }
  ~Fixture() { server.stop(); }  // before the log the server thread writes
  bool logged(const std::string& text) {
    std::lock_guard<std::mutex> l(log_mu);
    for (const auto& s : logs)
      if (s.find(text) != std::string::npos) return true;
    return false;
  }
  size_t queued() {
    size_t n = 0;
    for (const ClientInfo& c : server.client_list()) n = std::max(n, c.queued);
    return n;
  }
  Bytes outputs() {
    Bytes b(image.output_size());
    image.take_outputs(b.data(), ~0ull);
    return b;
  }
};

}  // namespace

TEST(value_store_word_order) {
  uint8_t b[8];
  store_value(b, 0x12345678, 4, false);
  EXPECT(get_be16(b) == 0x1234 && get_be16(b + 2) == 0x5678);
  EXPECT(load_value(b, 4, false) == 0x12345678);
  store_value(b, 0x12345678, 4, true);
  EXPECT(get_be16(b) == 0x5678 && get_be16(b + 2) == 0x1234);
  EXPECT(load_value(b, 4, true) == 0x12345678);
  store_value(b, 0x1122334455667788ull, 8, true);
  EXPECT(get_be16(b) == 0x7788 && get_be16(b + 6) == 0x1122);
  EXPECT(load_value(b, 8, true) == 0x1122334455667788ull);
  store_value(b, 0xABCD, 2, true);  // words keep their byte order
  EXPECT(get_be16(b) == 0xABCD);
}

TEST(register_rule_inputs) {
  // Spec: UNSIGNED32 0x12345678 at %ID4 -> input registers 2 and 3.
  Fixture fx;
  Bytes in(40, 0);
  store_value(&in[4], 0x12345678, 4, false);
  in[11] = 0x08;  // %IX11.3
  fx.image.publish_inputs(in.data(), in.size());
  Client c(fx.server.port());
  Bytes r = c.request(read_req(kReadInputRegisters, 2, 2));
  EXPECT((r == Bytes{4, 4, 0x12, 0x34, 0x56, 0x78}));
  r = c.request(read_req(kReadDiscreteInputs, 11 * 8 + 3, 1));
  EXPECT((r == Bytes{2, 1, 1}));
  r = c.request(read_req(kReadInputRegisters, 5, 1));  // bytes 10, 11: low byte bit 3
  EXPECT((r == Bytes{4, 2, 0x00, 0x08}));
  r = c.request(read_req(kReadDiscreteInputs, 86, 4));  // bits 86..89: only 91 set? none
  EXPECT((r == Bytes{2, 1, 0}));
}

TEST(output_bit_as_coil) {
  // Spec: coil 801 -> %QX100.1; holding register 50 high byte bit 1.
  Fixture fx(open_config(), 40, 120);
  Client c(fx.server.port());
  Bytes r = c.request({kWriteSingleCoil, 0x03, 0x21, 0xFF, 0x00});
  EXPECT((r == Bytes{kWriteSingleCoil, 0x03, 0x21, 0xFF, 0x00}));
  EXPECT(fx.outputs()[100] == 0x02);
  r = c.request(read_req(kReadHoldingRegisters, 50, 1));
  EXPECT((r == Bytes{3, 2, 0x02, 0x00}));
  r = c.request(read_req(kReadCoils, 801, 1));
  EXPECT((r == Bytes{1, 1, 1}));
  r = c.request({kWriteSingleCoil, 0x03, 0x21, 0x00, 0x00});
  EXPECT(fx.outputs()[100] == 0);
  r = c.request({kWriteSingleCoil, 0x03, 0x21, 0x12, 0x34});
  EXPECT(r == exc(kWriteSingleCoil, kIllegalDataValue));
  EXPECT(fx.writes == 2);
}

TEST(write_functions) {
  Fixture fx;
  Client c(fx.server.port());
  Bytes r = c.request({kWriteSingleRegister, 0, 3, 0xBE, 0xEF});
  EXPECT((r == Bytes{kWriteSingleRegister, 0, 3, 0xBE, 0xEF}));
  EXPECT(fx.outputs()[6] == 0xBE && fx.outputs()[7] == 0xEF);
  r = c.request(write_regs(0, {0x1111, 0x2222}));
  EXPECT((r == Bytes{kWriteMultipleRegisters, 0, 0, 0, 2}));
  r = c.request({kWriteMultipleCoils, 0, 16, 0, 10, 2, 0xFF, 0x02});  // coils 16..25
  EXPECT((r == Bytes{kWriteMultipleCoils, 0, 16, 0, 10}));
  Bytes o = fx.outputs();
  EXPECT(o[0] == 0x11 && o[1] == 0x11 && o[2] == 0xFF && o[3] == 0x22);  // coil 24 cleared, 25 set
  // Function 23: write registers 4..5, then read 3..5 after the write.
  r = c.request({kReadWriteMultipleRegisters, 0, 3, 0, 3, 0, 4, 0, 2, 4, 0xAA, 0xBB, 0xCC, 0xDD});
  EXPECT((r == Bytes{kReadWriteMultipleRegisters, 6, 0xBE, 0xEF, 0xAA, 0xBB, 0xCC, 0xDD}));
  EXPECT(fx.writes == 4);
  // Reading does not feed the watchdog.
  c.request(read_req(kReadHoldingRegisters, 0, 8));
  EXPECT(fx.writes == 4);
}

TEST(loopback_and_unknown_functions) {
  Fixture fx;
  Client c(fx.server.port());
  Bytes r = c.request({kDiagnostics, 0, 0, 0x12, 0x34});
  EXPECT((r == Bytes{kDiagnostics, 0, 0, 0x12, 0x34}));
  r = c.request({kDiagnostics, 0, 1, 0, 0});  // restart communications: not offered
  EXPECT(r == exc(kDiagnostics, kIllegalFunction));
  r = c.request({43, 13, 0, 0});  // CiA 309-2 is not in this change
  EXPECT(r == exc(43, kIllegalFunction));
  r = c.request({7});
  EXPECT(r == exc(7, kIllegalFunction));
}

TEST(addresses_and_limits) {
  // Spec: 40-byte input image, input registers 18..21 -> exception 0x02.
  Fixture fx;
  Client c(fx.server.port());
  EXPECT(c.request(read_req(kReadInputRegisters, 18, 4)) == exc(kReadInputRegisters, kIllegalDataAddress));
  EXPECT(c.request(read_req(kReadInputRegisters, 18, 2)).size() == 6);
  EXPECT(c.request(read_req(kReadInputRegisters, 0, 0)) == exc(kReadInputRegisters, kIllegalDataValue));
  EXPECT(c.request(read_req(kReadInputRegisters, 0, 126)) == exc(kReadInputRegisters, kIllegalDataValue));
  EXPECT(c.request(read_req(kReadDiscreteInputs, 0, 2001)) == exc(kReadDiscreteInputs, kIllegalDataValue));
  EXPECT(c.request(read_req(kReadDiscreteInputs, 319, 2)) == exc(kReadDiscreteInputs, kIllegalDataAddress));
  EXPECT(c.request(read_req(kReadHoldingRegisters, 8, 1)) == exc(kReadHoldingRegisters, kIllegalDataAddress));
  EXPECT(c.request({kWriteSingleRegister, 0, 8, 0, 0}) == exc(kWriteSingleRegister, kIllegalDataAddress));
  // 124 registers do not fit a frame; a count over 123 is refused as a value.
  EXPECT(c.request({kWriteMultipleRegisters, 0, 0, 0, 124, 0}) == exc(kWriteMultipleRegisters, kIllegalDataValue));
  // Byte count that does not match the quantity.
  EXPECT(c.request({kWriteMultipleRegisters, 0, 0, 0, 2, 2, 0, 0}) == exc(kWriteMultipleRegisters, kIllegalDataValue));
  EXPECT(fx.writes == 0);
}

TEST(unit_ids) {
  ServerConfig cfg;
  cfg.unit_id = 7;
  Fixture fx(cfg);
  Client c(fx.server.port());
  EXPECT(c.request(read_req(kReadInputRegisters, 0, 1), 7).size() == 4);
  EXPECT(c.request(read_req(kReadInputRegisters, 0, 1), 0).size() == 4);
  EXPECT(c.request(read_req(kReadInputRegisters, 0, 1), 255).size() == 4);
  EXPECT(c.request(read_req(kReadInputRegisters, 0, 1), 1) == exc(kReadInputRegisters, kGatewayTargetFailed));
}

TEST(pipelined_and_split_frames) {
  Fixture fx;
  Client c(fx.server.port());
  // Two requests in one segment, answered in order with their transaction IDs.
  Bytes two = c.frame(read_req(kReadInputRegisters, 0, 1));
  Bytes second = c.frame(read_req(kReadHoldingRegisters, 0, 1));
  two.insert(two.end(), second.begin(), second.end());
  c.send_raw(two);
  uint16_t t1 = 0, t2 = 0;
  Bytes r1 = c.read_frame(&t1), r2 = c.read_frame(&t2);
  EXPECT(r1.size() == 4 && r1[0] == kReadInputRegisters && t1 == 1);
  EXPECT(r2.size() == 4 && r2[0] == kReadHoldingRegisters && t2 == 2);
  // One request split over two segments.
  Bytes f = c.frame(read_req(kReadInputRegisters, 1, 2));
  c.send_raw(Bytes(f.begin(), f.begin() + 5));
  std::this_thread::sleep_for(std::chrono::milliseconds(30));
  c.send_raw(Bytes(f.begin() + 5, f.end()));
  EXPECT(c.read_frame().size() == 6);
  // Not Modbus TCP: protocol ID 1 closes the connection.
  c.send_raw({0, 9, 0, 1, 0, 2, 1, 4});
  EXPECT(c.closed());
}

TEST(writers_allowlist) {
  // Spec: writers ["10.0.0.20"], a client elsewhere writes -> 0x01, no change.
  ServerConfig cfg;
  std::string err;
  EXPECT(cfg.writers.add("10.0.0.20", err));
  Fixture fx(cfg);
  Client c(fx.server.port());
  EXPECT(c.request({kWriteSingleRegister, 0, 0, 0x12, 0x34}) == exc(kWriteSingleRegister, kIllegalFunction));
  EXPECT(c.request(write_regs(0, {1})) == exc(kWriteMultipleRegisters, kIllegalFunction));
  EXPECT(c.request(read_req(kReadHoldingRegisters, 0, 1)).size() == 4);
  EXPECT(fx.outputs()[0] == 0 && fx.writes == 0);
}

TEST(readers_allowlist_and_max_clients) {
  ServerConfig cfg;
  std::string err;
  EXPECT(cfg.readers.add("10.0.0.0/8", err));
  {
    Fixture fx(cfg);
    Client c(fx.server.port());
    EXPECT(c.closed());
    EXPECT(wait_for([&] { return fx.logged("not in readers"); }));
  }
  ServerConfig two;
  two.max_clients = 2;
  Fixture fx(two);
  Client a(fx.server.port()), b(fx.server.port());
  EXPECT(a.request(read_req(kReadInputRegisters, 0, 1)).size() == 4);
  EXPECT(b.request(read_req(kReadInputRegisters, 0, 1)).size() == 4);
  EXPECT(wait_for([&] { return fx.server.clients() == 2; }));
  Client third(fx.server.port());
  EXPECT(third.closed());
  EXPECT(wait_for([&] { return fx.logged("max_clients"); }));
  EXPECT(a.request(read_req(kReadInputRegisters, 0, 1)).size() == 4);
}

TEST(idle_connection_closed) {
  ServerConfig cfg;
  cfg.idle_timeout_ms = 200;  // 60 s in the bridge
  Fixture fx(cfg);
  Client c(fx.server.port());
  EXPECT(c.request(read_req(kReadInputRegisters, 0, 1)).size() == 4);
  EXPECT(c.closed(3000));
  EXPECT(wait_for([&] { return fx.server.clients() == 0; }));
}

TEST(empty_writers_is_nobody) {
  Fixture fx{ServerConfig()};
  Client c(fx.server.port());
  EXPECT(c.request({kWriteSingleRegister, 0, 0, 0x12, 0x34}) == exc(kWriteSingleRegister, kIllegalFunction));
  EXPECT(fx.outputs()[0] == 0 && fx.writes == 0);
}

// Spec: a client sends read requests without pause and never reads its
// socket -> bounded memory, others served, disconnected after 10 s (here
// 500 ms) over the cap.
TEST(client_that_never_reads) {
  ServerConfig cfg = open_config();
  cfg.over_queued_ms = 500;
  Fixture fx(cfg, 250, 16);
  Client slow(fx.server.port(), "127.0.0.1", 4096);
  slow.set_nonblocking();
  Bytes burst;
  for (int i = 0; i < 64; ++i) {
    Bytes f = slow.frame(read_req(kReadInputRegisters, 0, 125));  // 12 bytes in, 257 out
    burst.insert(burst.end(), f.begin(), f.end());
  }
  Client other(fx.server.port());
  size_t worst = 0;
  bool other_ok = true;
  auto end = std::chrono::steady_clock::now() + std::chrono::milliseconds(300);
  while (std::chrono::steady_clock::now() < end) {
    slow.send_raw(burst);
    worst = std::max(worst, fx.queued());
    std::this_thread::sleep_for(std::chrono::milliseconds(1));
  }
  other_ok = other.request(read_req(kReadInputRegisters, 0, 1)).size() == 4;
  std::printf("  most unsent reply bytes: %zu\n", worst);
  EXPECT(worst <= 8192 + 260);
  EXPECT(other_ok);
  EXPECT(wait_for([&] { return fx.logged("replies not read"); }, 3000));
  EXPECT(wait_for([&] { return fx.server.clients() == 1; }));
  EXPECT(other.request(read_req(kReadInputRegisters, 0, 1)).size() == 4);
}

// The idle timer counts complete requests only; a partial request is closed
// after 5 s (here 300 ms).
TEST(idle_needs_complete_requests) {
  ServerConfig cfg = open_config();
  cfg.idle_timeout_ms = 400;
  cfg.partial_timeout_ms = 100000;
  Fixture fx(cfg);
  Client c(fx.server.port());
  EXPECT(c.request(read_req(kReadInputRegisters, 0, 1)).size() == 4);
  // A long write sent one byte every 100 ms: bytes keep coming, but no
  // request completes within the idle time.
  Bytes f = c.frame(write_regs(0, std::vector<uint16_t>(100, 1)));
  bool closed = false;
  for (size_t i = 0; i + 1 < f.size() && i < 20 && !closed; ++i) {
    c.send_raw(Bytes(f.begin() + i, f.begin() + i + 1));
    closed = c.closed(100);
  }
  EXPECT(closed);  // well before the 2 s the bytes kept coming
  EXPECT(wait_for([&] { return fx.logged("idle"); }));
}

TEST(partial_request_closed) {
  ServerConfig cfg = open_config();
  cfg.partial_timeout_ms = 300;
  Fixture fx(cfg);
  Client c(fx.server.port());
  Bytes f = c.frame(read_req(kReadInputRegisters, 0, 1));
  c.send_raw(Bytes(f.begin(), f.begin() + 5));
  EXPECT(c.closed(3000));
  EXPECT(wait_for([&] { return fx.logged("incomplete request"); }));
}

TEST(max_clients_per_address) {
  ServerConfig cfg = open_config();
  cfg.max_clients_per_address = 2;
  Fixture fx(cfg);
  Client a(fx.server.port()), b(fx.server.port());
  EXPECT(a.request(read_req(kReadInputRegisters, 0, 1)).size() == 4);
  EXPECT(b.request(read_req(kReadInputRegisters, 0, 1)).size() == 4);
  Client third(fx.server.port());
  EXPECT(third.closed());
  EXPECT(wait_for([&] { return fx.logged("max_clients_per_address"); }));
  Client elsewhere(fx.server.port(), "127.0.0.1", 0, "127.0.0.2");
  EXPECT(elsewhere.request(read_req(kReadInputRegisters, 0, 1)).size() == 4);
}

// Spec: every slot taken by readers, the writer connects -> the oldest
// reader connection is closed and the writer is served.
TEST(writer_takes_a_slot) {
  ServerConfig cfg;
  std::string err;
  EXPECT(cfg.writers.add("127.0.0.3", err));
  cfg.max_clients = 2;
  Fixture fx(cfg);
  Client a(fx.server.port()), b(fx.server.port(), "127.0.0.1", 0, "127.0.0.2");
  EXPECT(a.request(read_req(kReadInputRegisters, 0, 1)).size() == 4);
  EXPECT(b.request(read_req(kReadInputRegisters, 0, 1)).size() == 4);
  Client w(fx.server.port(), "127.0.0.1", 0, "127.0.0.3");
  EXPECT(w.request({kWriteSingleRegister, 0, 0, 0x12, 0x34}) == Bytes({kWriteSingleRegister, 0, 0, 0x12, 0x34}));
  EXPECT(a.closed());
  EXPECT(wait_for([&] { return fx.logged("to make room"); }));
  EXPECT(b.request(read_req(kReadInputRegisters, 0, 1)).size() == 4);
  // A reader does not push anyone out.
  Client r(fx.server.port(), "127.0.0.1", 0, "127.0.0.4");
  EXPECT(r.closed());
  EXPECT(w.request(read_req(kReadHoldingRegisters, 0, 1)).size() == 4);
}

TEST(read_is_one_snapshot) {
  // Spec: a 32-bit counter changing every millisecond never tears within a
  // request (here it changes every 20 us, with both
  // words always changing: high word = counter, low word = ~counter).
  Fixture fx;
  std::atomic<bool> done{false};
  Bytes first(40, 0);
  put_be16(&first[6], 0xFFFF);  // counter 0: a pair from the start
  fx.image.publish_inputs(first.data(), first.size());
  std::thread bus([&] {
    Bytes in(40, 0);
    for (uint16_t n = 1; !done; ++n) {
      put_be16(&in[4], n);
      put_be16(&in[6], static_cast<uint16_t>(~n));
      fx.image.publish_inputs(in.data(), in.size());
      // Faster than any bus (a snapshot every 20 us), without starving the
      // server of the image lock.
      std::this_thread::sleep_for(std::chrono::microseconds(20));
    }
  });
  Client c(fx.server.port());
  int torn = 0, lost = 0;
  for (int i = 0; i < 10000; ++i) {
    Bytes r = c.request(read_req(kReadInputRegisters, 2, 2));
    if (r.size() != 6)
      ++lost;
    else if (get_be16(&r[2]) != static_cast<uint16_t>(~get_be16(&r[4])))
      ++torn;
  }
  done = true;
  bus.join();
  EXPECT(torn == 0);
  EXPECT(lost == 0);
}

TEST(write_publishes_one_snapshot) {
  Fixture fx;
  uint64_t seen = fx.image.output_version();
  Client c(fx.server.port());
  c.request(write_regs(2, {0x1234, 0x5678}));
  Bytes o(fx.image.output_size());
  uint64_t v = fx.image.take_outputs(o.data(), seen);
  EXPECT(v == seen + 1);
  EXPECT(load_value(&o[4], 4, false) == 0x12345678);
  // Nothing new: the copy is skipped.
  EXPECT(fx.image.take_outputs(o.data(), v) == v);
}

TEST(address_lists) {
  AddressList l;
  std::string err;
  EXPECT(l.add("192.168.10.0/24", err));
  EXPECT(l.add("fd00::/8", err));
  EXPECT(!l.add("192.168.10.0/33", err));
  EXPECT(!l.add("plc.local", err));
  sockaddr_in v4{};
  v4.sin_family = AF_INET;
  inet_pton(AF_INET, "192.168.10.77", &v4.sin_addr);
  EXPECT(l.matches(reinterpret_cast<sockaddr*>(&v4)));
  inet_pton(AF_INET, "192.168.11.1", &v4.sin_addr);
  EXPECT(!l.matches(reinterpret_cast<sockaddr*>(&v4)));
  sockaddr_in6 v6{};
  v6.sin6_family = AF_INET6;
  inet_pton(AF_INET6, "::ffff:192.168.10.5", &v6.sin6_addr);
  EXPECT(l.matches(reinterpret_cast<sockaddr*>(&v6)));
  inet_pton(AF_INET6, "fd12::1", &v6.sin6_addr);
  EXPECT(l.matches(reinterpret_cast<sockaddr*>(&v6)));
  inet_pton(AF_INET6, "fe80::1", &v6.sin6_addr);
  EXPECT(!l.matches(reinterpret_cast<sockaddr*>(&v6)));

  sockaddr_storage ss;
  socklen_t len;
  EXPECT(parse_listen("0.0.0.0:502", ss, len, err) && ss.ss_family == AF_INET);
  EXPECT(parse_listen("[::]:1502", ss, len, err) && ss.ss_family == AF_INET6);
  EXPECT(!parse_listen("0.0.0.0", ss, len, err));
  EXPECT(!parse_listen("0.0.0.0:70000", ss, len, err));
  EXPECT(!parse_listen("::1:502", ss, len, err));
}

TEST(watchdog_states) {
  auto t0 = Clock::now();
  auto ms = [&](int n) { return t0 + std::chrono::milliseconds(n); };
  OutputSupervisor w(1000, t0);
  EXPECT(w.running());
  EXPECT(!w.tick(ms(999)));
  EXPECT(w.tick(ms(1000)) && w.state() == OutputState::kWatchdog);
  EXPECT(!w.tick(ms(5000)));
  EXPECT(w.write(ms(5001)) && w.running());  // the next accepted write ends it
  EXPECT(!w.write(ms(5050)));
  // Idle: writes do not end it, only run.
  EXPECT(w.idle() && w.state() == OutputState::kIdle);
  EXPECT(!w.write(ms(5100)) && w.state() == OutputState::kIdle);
  EXPECT(!w.tick(ms(9000)) && w.state() == OutputState::kIdle);
  EXPECT(w.run(ms(9001)) && w.running());
  EXPECT(!w.tick(ms(9500)));
  // 0 turns the watchdog off.
  OutputSupervisor off(0, t0);
  EXPECT(!off.tick(ms(100000)) && off.running());
}

TEST(control_block_handshake) {
  // Spec: command 4, network 0, node 7, counter 41 -> 42: runs once.
  ControlBlock cb;
  std::vector<bool> masters = {true, false};
  uint8_t blk[kControlBytes] = {0, 41, kCmdNmtStop, 0, 7, 0};
  ControlRequest req;
  EXPECT(cb.poll(blk, req) && req.counter == 41);
  cb.handled(req.counter, ControlBlock::check(req, masters));
  EXPECT(!cb.poll(blk, req));  // cyclic rewrite: nothing
  blk[1] = 42;
  EXPECT(cb.poll(blk, req) && req.command == kCmdNmtStop && req.network == 0 && req.node == 7);
  cb.handled(req.counter, ControlBlock::check(req, masters));
  uint8_t st[kStatusBytes];
  encode_status(st, OutputState::kRunning, 3, 0x0102, cb);
  EXPECT((Bytes(st, st + 8) == Bytes{1, 3, 1, 2, 0, 42, kCtrlOk, 0}));

  auto result = [&](uint8_t cmd, uint8_t net, uint8_t node) {
    ControlRequest r;
    r.command = cmd;
    r.network = net;
    r.node = node;
    return ControlBlock::check(r, masters);
  };
  EXPECT(result(9, 0, 1) == kCtrlUnknownCommand);
  EXPECT(result(kCmdNmtStart, 2, 1) == kCtrlBadNetwork);
  EXPECT(result(kCmdNmtStart, 1, 1) == kCtrlNotMaster);
  EXPECT(result(kCmdResetNode, 0, 128) == kCtrlBadNode);
  EXPECT(result(kCmdResetCommunication, 0, 0) == kCtrlOk);  // node 0: all nodes
  EXPECT(result(kCmdIdle, 9, 200) == kCtrlOk);              // run/idle ignore network and node
  EXPECT(result(kCmdNone, 0, 0) == kCtrlOk);                // zeroed block: nothing to do
}

TEST(live_list_bits) {
  std::bitset<128> ops;
  ops[5] = ops[7] = ops[127] = true;
  ops[0] = true;  // never a node
  uint8_t b[kLiveListBytes];
  encode_live_list(b, ops);
  EXPECT(b[0] == 0xA0 && b[15] == 0x80);
  for (int i = 1; i < 15; ++i) EXPECT(b[i] == 0);
}

namespace {

struct FakeSdo : SdoBackend {
  int starts = 0;
  SdoRequest last;
  bool refuse = false;
  int result = 0;
  uint32_t value = 0, abort = 0;
  bool start(const SdoRequest& r, uint32_t& a) override {
    if (refuse) {
      a = 0x08000022u;
      return false;
    }
    ++starts;
    last = r;
    result = 0;
    return true;
  }
  int poll(uint32_t& v, uint32_t& a) override {
    v = value;
    a = abort;
    return result;
  }
};

Bytes sdo_req(uint16_t counter, uint8_t cmd, uint8_t net, uint8_t node, uint16_t index, uint8_t sub, uint8_t len,
              uint32_t value = 0) {
  Bytes b(kSdoRequestBytes, 0);
  put_be16(&b[0], counter);
  b[2] = cmd;
  b[3] = net;
  b[4] = node;
  b[5] = sub;
  put_be16(&b[6], index);
  b[8] = len;
  put_be32(&b[10], value);
  return b;
}

Bytes sdo_resp(const SdoBridgeRegisters& r) {
  Bytes b(kSdoResponseBytes);
  r.encode(b.data());
  return b;
}

}  // namespace

TEST(sdo_bridge_read) {
  // Spec: read 0x1018:1 of node 5 on network 0.
  SdoBridgeRegisters regs(false);
  FakeSdo be;
  Bytes req = sdo_req(1, 1, 0, 5, 0x1018, 1, 4);
  regs.service(req.data(), be);
  EXPECT(be.starts == 1 && be.last.index == 0x1018 && be.last.subindex == 1 && be.last.node == 5);
  Bytes r = sdo_resp(regs);
  EXPECT(get_be16(&r[0]) == 1 && r[2] == kSdoBusy);
  regs.service(req.data(), be);  // still running
  EXPECT(regs.status() == kSdoBusy && be.starts == 1);
  be.result = 1;
  be.value = 0x000004D2;
  regs.service(req.data(), be);
  r = sdo_resp(regs);
  EXPECT(r[2] == kSdoDone && get_be32(&r[4]) == 0 && get_be32(&r[8]) == 0x4D2);
  regs.service(req.data(), be);  // cyclic rewrite: not started again
  EXPECT(be.starts == 1);
}

TEST(sdo_bridge_write_refused_and_aborts) {
  SdoBridgeRegisters regs(false);
  FakeSdo be;
  Bytes req = sdo_req(1, 2, 0, 5, 0x2000, 0, 2, 7);
  regs.service(req.data(), be);
  Bytes r = sdo_resp(regs);
  EXPECT(be.starts == 0 && r[2] == kSdoAborted && get_be32(&r[4]) == kAbortNoTransfer);

  SdoBridgeRegisters rw(true);
  rw.service(req.data(), be);
  EXPECT(be.starts == 1 && be.last.command == 2 && be.last.value == 7 && be.last.length == 2);
  be.result = -1;
  be.abort = 0x06020000u;  // object does not exist: passed through
  rw.service(req.data(), be);
  r = sdo_resp(rw);
  EXPECT(r[2] == kSdoAborted && get_be32(&r[4]) == 0x06020000u);

  req = sdo_req(2, 9, 0, 5, 0x1000, 0, 4);
  rw.service(req.data(), be);
  EXPECT(get_be32(&sdo_resp(rw)[4]) == kAbortValueRange && get_be16(&sdo_resp(rw)[0]) == 2);
  req = sdo_req(3, 1, 0, 0, 0x1000, 0, 4);
  rw.service(req.data(), be);
  EXPECT(get_be32(&sdo_resp(rw)[4]) == kAbortGeneral);
  be.refuse = true;
  req = sdo_req(4, 1, 0, 5, 0x1000, 0, 4);
  rw.service(req.data(), be);
  EXPECT(get_be32(&sdo_resp(rw)[4]) == 0x08000022u);
}

TEST(sdo_bridge_new_counter_while_busy) {
  SdoBridgeRegisters regs(true);
  FakeSdo be;
  Bytes a = sdo_req(1, 1, 0, 5, 0x1000, 0, 4);
  Bytes b = sdo_req(2, 1, 0, 5, 0x1018, 1, 4);
  regs.service(a.data(), be);
  regs.service(b.data(), be);  // busy: waits
  EXPECT(be.starts == 1 && get_be16(&sdo_resp(regs)[0]) == 1);
  be.result = 1;
  regs.service(b.data(), be);  // first ends, second starts
  EXPECT(be.starts == 2 && be.last.index == 0x1018);
  Bytes r = sdo_resp(regs);
  EXPECT(get_be16(&r[0]) == 2 && r[2] == kSdoBusy);
}

int main(int argc, char** argv) { return check::run_all(argc, argv); }
