// bridge_host_tests.cpp - canworks-bridge end to end (modbus-bridge spec):
// the example config (examples/modbus-bridge) on its simulated bus, served
// on a free loopback port and read and written by a Modbus TCP client.

#include <sys/stat.h>
#include <unistd.h>

#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <mutex>
#include <sstream>
#include <string>
#include <vector>

#include "bridge_host.h"
#include "cJSON.h"
#include "check.hpp"
#include "iface_lock.h"
#include "canopen_runtime.h"
#include "log.h"
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

std::mutex g_log_mu;
std::vector<std::string> g_log;

void capture(canopen_plugin::LogLevel, const char* msg) {
  std::lock_guard<std::mutex> l(g_log_mu);
  g_log.push_back(msg);
}

int count_logged(const std::string& text) {
  std::lock_guard<std::mutex> l(g_log_mu);
  int n = 0;
  for (const auto& s : g_log)
    if (s.find(text) != std::string::npos) ++n;
  return n;
}

bool logged(const std::string& text) {
  std::lock_guard<std::mutex> l(g_log_mu);
  for (const auto& s : g_log)
    if (s.find(text) != std::string::npos) return true;
  return false;
}

std::string read_file(const std::string& p) {
  std::ifstream f(p);
  std::stringstream s;
  s << f.rdbuf();
  return s.str();
}

void write_file(const std::string& p, const std::string& text) { std::ofstream(p) << text; }

// A copy of the example in a fresh directory, the config edited by `edit`.
std::string example_copy(const std::function<void(cJSON*)>& edit) {
  char tmpl[] = "/tmp/canworks-bridge-XXXXXX";
  std::string dir = mkdtemp(tmpl);
  for (const char* f : {"simulation.json", "rtd8.eds", "dio16.eds"})
    write_file(dir + "/" + f, read_file(std::string(EXAMPLE_DIR) + "/" + f));
  cJSON* root = cJSON_Parse(read_file(std::string(EXAMPLE_DIR) + "/canworks.json").c_str());
  if (edit) edit(root);
  char* text = cJSON_Print(root);
  write_file(dir + "/canworks.json", text);
  cJSON_free(text);
  cJSON_Delete(root);
  return dir + "/canworks.json";
}

cJSON* bridge_of(cJSON* root) { return cJSON_GetObjectItem(root, "bridge"); }

void set_number(cJSON* obj, const char* key, double v) {
  cJSON_DeleteItemFromObject(obj, key);
  cJSON_AddNumberToObject(obj, key, v);
}

void set_string(cJSON* obj, const char* key, const char* v) {
  cJSON_DeleteItemFromObject(obj, key);
  cJSON_AddStringToObject(obj, key, v);
}

// The register layout of the example (byte n is register n / 2).
constexpr uint16_t kStatusReg = 12;    // %IB24
constexpr uint16_t kLiveListReg = 16;  // %IB32: node 5 and 6 are bits 5 and 6 of byte 32
constexpr uint16_t kSdoRespReg = 24;   // %IB48
constexpr uint16_t kControlReg = 3;    // %QB6
constexpr uint16_t kSdoReqReg = 6;     // %QB12

std::vector<uint16_t> regs(Client& c, uint8_t f, uint16_t addr, uint16_t n) {
  Bytes r = c.request(read_req(f, addr, n));
  std::vector<uint16_t> out;
  if (r.size() != 2u + 2u * n || r[0] != f) return out;
  for (uint16_t i = 0; i < n; ++i) out.push_back(get_be16(&r[2 + 2 * i]));
  return out;
}

uint16_t reg(Client& c, uint16_t addr) {
  auto v = regs(c, kReadInputRegisters, addr, 1);
  return v.empty() ? 0xFFFF : v[0];
}

bool write(Client& c, uint16_t addr, const std::vector<uint16_t>& v) {
  Bytes r = c.request(write_regs(addr, v));
  return !r.empty() && r[0] == kWriteMultipleRegisters;
}

uint8_t state(Client& c) { return static_cast<uint8_t>(reg(c, kStatusReg) >> 8); }

bool both_operational(Client& c) { return (reg(c, kLiveListReg) >> 8) == 0x60; }

struct Host {
  BridgeHost host;
  bool ok = false;
  explicit Host(const std::function<void(cJSON*)>& edit = nullptr) {
    canopen_plugin::set_log_sink(capture);
    canopen_plugin::canopen_init_logging();
    host.listen_override = "127.0.0.1:0";
    ok = host.start(example_copy([&](cJSON* r) {
                      // The test client writes from loopback.
                      cJSON* w = cJSON_CreateArray();
                      cJSON_AddItemToArray(w, cJSON_CreateString("127.0.0.1"));
                      cJSON_AddItemToArray(w, cJSON_CreateString("::1"));
                      cJSON_DeleteItemFromObject(bridge_of(r), "writers");
                      cJSON_AddItemToObject(bridge_of(r), "writers", w);
                      if (edit) edit(r);
                    }),
                    "test");
    if (!ok) {
      std::lock_guard<std::mutex> l(g_log_mu);
      for (const auto& m : g_log) std::printf("  log: %s\n", m.c_str());
    }
  }
  ~Host() { host.stop(); }
  uint16_t port() { return host.modbus_port(); }
};

}  // namespace

TEST(boots_and_serves_the_map) {
  Host h;
  EXPECT(h.ok);
  if (!h.ok) return;
  Client c(h.port());
  EXPECT(wait_for([&] { return both_operational(c); }, 10000));
  // Node 5's simulated temperatures in %IW0 and %IW2.
  EXPECT(wait_for([&] { return reg(c, 0) >= 200 && reg(c, 0) <= 260; }, 2000));
  // The node status bits %IX16.0 and .1 as discrete inputs 128 and 129.
  Bytes di = c.request(read_req(kReadDiscreteInputs, 128, 2));
  EXPECT(di.size() == 3 && (di[2] & 3) == 3);
  // Outputs of node 6 come back on its inputs (the simulated device loops
  // them): %QB0/%QB1 -> %IB8/%IB9, %QW2 -> %IW10, %QW4 -> %IW12.
  EXPECT(write(c, 0, {0x1234, 0x5678, 1000}));
  EXPECT(wait_for([&] {
    auto v = regs(c, kReadInputRegisters, 4, 3);
    return v.size() == 3 && v[0] == 0x1234 && v[1] == 0x5678 && v[2] == 1000;
  }));
  EXPECT(state(c) == 1);
  // Past the image: illegal data address.
  EXPECT(c.request(read_req(kReadInputRegisters, 0, 32)) == exc(kReadInputRegisters, 2));
}

TEST(watchdog_stop_keeps_inputs) {
  Host h([](cJSON* r) { set_number(bridge_of(r), "watchdog_ms", 300); });
  EXPECT(h.ok);
  if (!h.ok) return;
  Client c(h.port());
  EXPECT(wait_for([&] { return both_operational(c); }, 10000));
  EXPECT(write(c, 0, {0x0101}));
  EXPECT(wait_for([&] { return state(c) == 2; }, 2000));
  EXPECT(logged("outputs off by the watchdog"));
  // SYNC goes on: node 5's synchronous inputs keep changing.
  uint16_t a = reg(c, 2);
  EXPECT(wait_for([&] { return reg(c, 2) != a; }, 3000));
  EXPECT(write(c, 0, {0x0202}));
  EXPECT(wait_for([&] { return state(c) == 1; }));
  EXPECT(logged("outputs on again: a client wrote"));
}

TEST(watchdog_zero) {
  Host h([](cJSON* r) {
    set_number(bridge_of(r), "watchdog_ms", 300);
    set_string(bridge_of(r), "on_client_loss", "zero");
  });
  EXPECT(h.ok);
  if (!h.ok) return;
  Client c(h.port());
  EXPECT(wait_for([&] { return both_operational(c); }, 10000));
  EXPECT(write(c, 1, {1234}));  // %QW2 -> %IW10
  EXPECT(wait_for([&] { return reg(c, 5) == 1234; }));
  // The zeros reach the device before the outputs stop.
  EXPECT(wait_for([&] { return state(c) == 2 && reg(c, 5) == 0; }, 3000));
  // The output image itself reads back 0 too.
  auto q = regs(c, kReadHoldingRegisters, 1, 1);
  EXPECT(q.size() == 1 && q[0] == 0);
}

// Spec: outputs off after a loss with "stop", then a writer writes one coil
// -> that coil is sent with its new value and every other output as 0.
TEST(watchdog_stop_clears_outputs) {
  Host h([](cJSON* r) { set_number(bridge_of(r), "watchdog_ms", 300); });
  EXPECT(h.ok);
  if (!h.ok) return;
  Client c(h.port());
  EXPECT(wait_for([&] { return both_operational(c); }, 10000));
  // %QB0, %QB1, %QW2 -> %IB8, %IB9, %IW10 on the simulated device.
  EXPECT(write(c, 0, {0x0102, 1234}));
  EXPECT(wait_for([&] { return reg(c, 4) == 0x0102 && reg(c, 5) == 1234; }));
  EXPECT(wait_for([&] { return state(c) == 2; }, 3000));
  EXPECT(reg(c, 5) == 1234);  // nothing sent while off
  // Coil 0 is %QX0.0.
  EXPECT(c.request({kWriteSingleCoil, 0, 0, 0xFF, 0x00}) == Bytes({kWriteSingleCoil, 0, 0, 0xFF, 0x00}));
  EXPECT(wait_for([&] { return state(c) == 1; }));
  EXPECT(wait_for([&] { return reg(c, 4) == 0x0100 && reg(c, 5) == 0; }));
  auto q = regs(c, kReadHoldingRegisters, 0, 2);
  EXPECT(q.size() == 2 && q[0] == 0x0100 && q[1] == 0);
}

TEST(watchdog_hold) {
  Host h([](cJSON* r) {
    set_number(bridge_of(r), "watchdog_ms", 300);
    set_string(bridge_of(r), "on_client_loss", "hold");
  });
  EXPECT(h.ok);
  if (!h.ok) return;
  Client c(h.port());
  EXPECT(wait_for([&] { return both_operational(c); }, 10000));
  EXPECT(write(c, 1, {777}));
  EXPECT(wait_for([&] { return state(c) == 2; }, 3000));
  EXPECT(reg(c, 5) == 777);
}

TEST(control_block_nmt_and_idle) {
  Host h([](cJSON* r) { set_number(bridge_of(r), "watchdog_ms", 0); });
  EXPECT(h.ok);
  if (!h.ok) return;
  Client c(h.port());
  EXPECT(wait_for([&] { return both_operational(c); }, 10000));
  // counter 1: NMT stop node 5 of network 0.
  EXPECT(write(c, kControlReg, {1, (4 << 8) | 0, 5 << 8}));
  EXPECT(wait_for([&] { return (reg(c, kLiveListReg) >> 8) == 0x40; }, 3000));
  auto st = regs(c, kReadInputRegisters, kStatusReg, 4);
  EXPECT(st.size() == 4 && st[2] == 1 && (st[3] >> 8) == 0);  // counter echoed, result OK
  // counter 2: NMT start it again.
  EXPECT(write(c, kControlReg, {2, (3 << 8) | 0, 5 << 8}));
  EXPECT(wait_for([&] { return both_operational(c); }, 3000));
  // counter 3: an unknown network.
  EXPECT(write(c, kControlReg, {3, (3 << 8) | 7, 5 << 8}));
  EXPECT(wait_for([&] {
    auto s = regs(c, kReadInputRegisters, kStatusReg, 4);
    return s.size() == 4 && s[2] == 3 && (s[3] >> 8) == 2;
  }));
  // counter 4: idle; writes do not end it, run does.
  EXPECT(write(c, kControlReg, {4, 2 << 8, 0}));
  EXPECT(wait_for([&] { return state(c) == 3; }));
  EXPECT(write(c, 0, {0x0303}));
  EXPECT(state(c) == 3);
  EXPECT(write(c, kControlReg, {5, 1 << 8, 0}));
  EXPECT(wait_for([&] { return state(c) == 1; }));
}

TEST(sdo_bridge_read_and_refused_write) {
  Host h([](cJSON* r) { set_number(bridge_of(r), "watchdog_ms", 0); });
  EXPECT(h.ok);
  if (!h.ok) return;
  Client c(h.port());
  EXPECT(wait_for([&] { return both_operational(c); }, 10000));
  // counter 1: read 0x1018:1 (vendor ID) of node 6 on network 0.
  // Request: counter, command|network, node|subindex, index, length|0, value.
  EXPECT(write(c, kSdoReqReg, {1, (1 << 8) | 0, (6 << 8) | 1, 0x1018, 0, 0, 0}));
  std::vector<uint16_t> r;
  EXPECT(wait_for([&] {
    r = regs(c, kReadInputRegisters, kSdoRespReg, 6);
    return r.size() == 6 && r[0] == 1 && (r[1] >> 8) >= 2;
  }, 3000));
  EXPECT(r.size() == 6 && (r[1] >> 8) == 2);  // done
  // counter 2: a write is refused (sdo_bridge_write false).
  EXPECT(write(c, kSdoReqReg, {2, (2 << 8) | 0, (6 << 8) | 0, 0x1017, 2 << 8, 0, 100}));
  EXPECT(wait_for([&] {
    r = regs(c, kReadInputRegisters, kSdoRespReg, 6);
    return r.size() == 6 && r[0] == 2;
  }, 3000));
  EXPECT(r.size() == 6 && (r[1] >> 8) == 3 && r[2] == 0x0800 && r[3] == 0x0020);
}

// Rising edges are seen between written snapshots: rewriting the same value
// is no new edge (modbus-bridge "Outputs").
TEST(cyclic_rewrite_is_no_edge) {
  Host h([](cJSON* r) {
    set_number(bridge_of(r), "watchdog_ms", 0);
    cJSON* node = cJSON_GetArrayItem(
        cJSON_GetObjectItem(cJSON_GetArrayItem(cJSON_GetObjectItem(r, "networks"), 0), "nodes"), 0);
    cJSON_AddStringToObject(node, "nmt_command_location", "%QB26");
  });
  EXPECT(h.ok);
  if (!h.ok) return;
  Client c(h.port());
  EXPECT(wait_for([&] { return both_operational(c); }, 10000));
  const std::string reset = "NMT RESET NODE (from the program)";
  int before = count_logged(reset);
  EXPECT(write(c, 13, {129 << 8}));
  EXPECT(wait_for([&] { return count_logged(reset) == before + 1; }));
  for (int i = 0; i < 5; ++i) {
    EXPECT(write(c, 13, {129 << 8}));
    std::this_thread::sleep_for(std::chrono::milliseconds(30));
  }
  EXPECT(count_logged(reset) == before + 1);
  EXPECT(write(c, 13, {0}));
  std::this_thread::sleep_for(std::chrono::milliseconds(50));
  EXPECT(write(c, 13, {129 << 8}));
  EXPECT(wait_for([&] { return count_logged(reset) == before + 2; }));
}

// Without SYNC, event-driven RPDOs carry a write at once: the simulated
// device echoes %QW2 on %IW10 within a few milliseconds (its TPDO has a
// 10 ms inhibit time, hence the pause between writes).
TEST(event_driven_output_without_sync) {
  Host h([](cJSON* r) {
    set_number(bridge_of(r), "watchdog_ms", 0);
    cJSON* net = cJSON_GetArrayItem(cJSON_GetObjectItem(r, "networks"), 0);
    cJSON_DeleteItemFromObject(cJSON_GetObjectItem(net, "master"), "sync_period_us");
    cJSON* node;
    cJSON_ArrayForEach(node, cJSON_GetObjectItem(net, "nodes")) {
      for (const char* key : {"tx_pdos", "rx_pdos"}) {
        cJSON* pdo;
        cJSON_ArrayForEach(pdo, cJSON_GetObjectItem(node, key)) set_number(pdo, "transmission", 255);
      }
    }
  });
  EXPECT(h.ok);
  if (!h.ok) return;
  Client c(h.port());
  EXPECT(wait_for([&] { return both_operational(c); }, 10000));
  int worst = 0;
  for (uint16_t v = 1; v <= 20; ++v) {
    std::this_thread::sleep_for(std::chrono::milliseconds(30));
    auto t0 = std::chrono::steady_clock::now();
    EXPECT(write(c, 1, {static_cast<uint16_t>(v * 100)}));
    EXPECT(wait_for([&] { return reg(c, 5) == v * 100; }, 1000));
    int ms = static_cast<int>(
        std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now() - t0).count());
    worst = std::max(worst, ms);
  }
  std::printf("  write to echo, worst of 20: %d ms\n", worst);
  EXPECT(worst < 50);
}

// The register map the PC tools compute (modbusmap.py, fixture made from the
// example by test_modbusmap) is the one the bridge serves.
TEST(map_matches_the_pc_tools) {
  Host h;
  EXPECT(h.ok);
  if (!h.ok) return;
  cJSON* map = cJSON_Parse(read_file(std::string(FIXTURES_DIR) + "/modbus/example-map.json").c_str());
  EXPECT(map != nullptr);
  if (!map) return;
  EXPECT(cJSON_GetObjectItem(map, "input_bytes")->valueint == static_cast<int>(h.host.image().input_size()));
  EXPECT(cJSON_GetObjectItem(map, "output_bytes")->valueint == static_cast<int>(h.host.image().output_size()));
  std::vector<canopen_plugin::ImageUse> uses = canopen_plugin::image_uses(h.host.set());
  int rows = 0;
  const cJSON* r;
  cJSON_ArrayForEach(r, cJSON_GetObjectItem(map, "registers")) {
    ++rows;
    std::string loc = cJSON_GetObjectItem(r, "location")->valuestring;
    std::string table = cJSON_GetObjectItem(r, "table")->valuestring;
    int address = cJSON_GetObjectItem(r, "address")->valueint;
    int count = cJSON_GetObjectItem(r, "count")->valueint;
    bool found = false;
    for (const auto& u : uses) {
      if (u.loc.str() != loc) continue;
      found = true;
      bool in = u.loc.area == canopen_plugin::IecArea::Input;
      if (u.loc.size == canopen_plugin::IecSize::X) {
        EXPECT(table == (in ? "discrete input" : "coil"));
        EXPECT(address == static_cast<int>(u.loc.index * 8 + u.loc.bit));
        EXPECT(count == 1);
      } else {
        EXPECT(table == (in ? "input register" : "holding register"));
        EXPECT(address == static_cast<int>(u.loc.index / 2));
        EXPECT(count == static_cast<int>((u.loc.index % 2 + u.nbytes + 1) / 2));
      }
    }
    if (!found) std::printf("  %s is not a location of the bridge\n", loc.c_str());
    EXPECT(found);
  }
  EXPECT(rows == static_cast<int>(uses.size()));
  cJSON_Delete(map);
}

TEST(interface_lock) {
  std::string prefix = "canworks-test-" + std::to_string(getpid()) + ":";
  setenv("CANWORKS_LOCK_PREFIX", prefix.c_str(), 1);
  canopen_plugin::InterfaceLock a, b, c;
  std::string problem;
  EXPECT(a.acquire("vcan9", problem));
  EXPECT(!b.acquire("vcan9", problem));
  EXPECT(problem.find("owned by another canworks process (process ID " + std::to_string(getpid()) + ")") !=
         std::string::npos);
  EXPECT(c.acquire("vcan8", problem));  // another interface is free
  a.release();
  EXPECT(b.acquire("vcan9", problem));
  b.release();
  c.release();
  unsetenv("CANWORKS_LOCK_PREFIX");
}

// A byte address near 2^32 does not wrap the image size.
TEST(rejects_huge_byte_address) {
  Host h([](cJSON* r) {
    cJSON* node = cJSON_GetArrayItem(
        cJSON_GetObjectItem(cJSON_GetArrayItem(cJSON_GetObjectItem(r, "networks"), 0), "nodes"), 0);
    set_string(node, "state_location", "%IB4294967295");
  });
  EXPECT(!h.ok);
}

// An allowlist entry the server cannot use stops the start.
TEST(server_config_from_bridge) {
  canopen_plugin::BridgeConfig b;
  b.listen = "0.0.0.0:502";
  b.max_clients_per_address = 3;
  b.writers = {"10.0.0.20"};
  b.readers = {"10.0.0.0/8"};
  ServerConfig sc;
  std::string err;
  EXPECT(server_config(b, sc, err));
  EXPECT(sc.max_clients_per_address == 3 && !sc.writers.empty() && !sc.readers.empty());
  b.writers = {"10.0.0.0/33"};
  EXPECT(!server_config(b, sc, err));
  EXPECT(err.find("writers") != std::string::npos && err.find("10.0.0.0/33") != std::string::npos);
  b.writers = {};
  b.readers = {"not an address"};
  EXPECT(!server_config(b, sc, err));
  EXPECT(err.find("readers") != std::string::npos);
}

// Image sizes are counted in 64 bits and refused over the limit.
TEST(image_sizes_refuse_over_the_limit) {
  canopen_plugin::ImageUse u;
  u.loc.area = canopen_plugin::IecArea::Input;
  u.loc.size = canopen_plugin::IecSize::B;
  u.loc.index = 0xFFFFFFFFu;
  u.nbytes = 1;
  size_t in = 0, out = 0;
  std::string err;
  EXPECT(!image_sizes({u}, BridgeHost::kImageLimit, in, out, err));
  EXPECT(err.find("%IB4294967295") != std::string::npos);
  u.loc.index = 8191;
  EXPECT(image_sizes({u}, BridgeHost::kImageLimit, in, out, err) && in == 8192 && out == 0);
  u.nbytes = 2;
  EXPECT(!image_sizes({u}, BridgeHost::kImageLimit, in, out, err));
}

TEST(rejects_plain_configs) {
  canopen_plugin::set_log_sink(capture);
  std::string path = example_copy([](cJSON* r) { cJSON_DeleteItemFromObject(r, "bridge"); });
  EXPECT(!BridgeHost::check(path));
  EXPECT(logged("not a bridge config"));
  path = example_copy([](cJSON* r) {
    cJSON* m = cJSON_GetObjectItem(cJSON_GetArrayItem(cJSON_GetObjectItem(r, "networks"), 0), "master");
    cJSON_AddStringToObject(m, "sync_source", "plc_cycle");
  });
  EXPECT(!BridgeHost::check(path));
  EXPECT(logged("needs a PLC cycle"));
}

int main(int argc, char** argv) { return check::run_all(argc, argv); }
