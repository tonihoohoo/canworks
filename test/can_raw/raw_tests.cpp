// Raw CAN unit tests (specs can-plc-frames and can-raw-messages): the PLC
// frame port's receivers, single frames, cyclic jobs, guards and cancel, and
// the C table the library blocks call. Needs no CAN interface or Lely.

#include <atomic>
#include <chrono>
#include <memory>
#include <cstring>
#include <thread>

#include <fstream>
#include <sstream>
#include <string>
#include <vector>

#include "cJSON.h"
#include "can/can_plc_api.h"
#include "can/raw/config.h"
#include "can/raw/engine.h"
#include "can/raw/plc_frames.h"
#include "can/raw/raw_devices.h"
#include "can/raw/raw_io.h"
#include "can/raw/raw_link.h"
#include "canopen/sim/sim_raw.h"
#include "can/signals.h"
#include "check.hpp"

#ifndef FIXTURES_DIR
#define FIXTURES_DIR "test/fixtures"
#endif

using namespace canworks_raw;

namespace {

canworks_can_frame frame(uint32_t id, std::initializer_list<uint8_t> data, uint8_t flags = 0) {
  canworks_can_frame f{};
  f.id = id;
  f.flags = flags;
  f.dlc = static_cast<uint8_t>(data.size());
  unsigned i = 0;
  for (uint8_t b : data) f.data[i++] = b;
  return f;
}

const canworks_can_api_v1* api() {
  return static_cast<const canworks_can_api_v1*>(canworks_can_api_table(CANWORKS_CAN_API_VERSION));
}

// A running port registered as network 0, unregistered at the end.
struct Net {
  PlcPort port{0};
  explicit Net(PortRules rules = {}) {
    port.set_rules(std::move(rules));
    port.set_running(true);
    set_port(0, &port);
  }
  ~Net() { set_port(0, nullptr); }
};

}  // namespace

TEST(api_versions) {
  CHECK(api() != nullptr);
  CHECK(api()->size == sizeof(canworks_can_api_v1));
  CHECK(canworks_can_api_table(2) == nullptr);
}

TEST(receiver_range_and_order) {
  Net n;
  uint16_t err = 0;
  uint32_t h = api()->rx_open(0, 0x600, 0x780, 0, 0, &err);
  CHECK(h != 0);
  CHECK(err == 0);
  n.port.on_frame(frame(0x605, {1}));
  n.port.on_frame(frame(0x705, {2}));
  n.port.on_frame(frame(0x67F, {3}));
  n.port.on_frame(frame(0x605, {4}, CANWORKS_CAN_EXTENDED));  // other format
  canworks_can_frame f{};
  canworks_can_rx_info info{};
  CHECK(api()->rx_read(h, &f, &info) == 1);
  CHECK(f.id == 0x605 && f.data[0] == 1);
  CHECK(info.queued == 1);
  CHECK(api()->rx_read(h, &f, &info) == 1);
  CHECK(f.id == 0x67F && f.data[0] == 3);
  CHECK(api()->rx_read(h, &f, &info) == 0);
  CHECK(info.queued == 0 && !info.overflow);
  api()->rx_close(h);
  CHECK(api()->rx_read(h, &f, &info) == -CANWORKS_CAN_ERR_CANCELLED);
}

TEST(receiver_overflow) {
  Net n;
  uint16_t err = 0;
  uint32_t h = api()->rx_open(0, 0x123, 0x7FF, 0, 4, &err);
  for (uint8_t i = 0; i < 6; ++i) n.port.on_frame(frame(0x123, {i}));
  canworks_can_frame f{};
  canworks_can_rx_info info{};
  int got = 0;
  while (api()->rx_read(h, &f, &info) == 1) {
    CHECK(f.data[0] == got);
    ++got;
  }
  CHECK(got == 4);
  CHECK(info.overflow);
  CHECK(info.dropped == 2);
}

TEST(reopened_receiver_sees_no_old_frames) {
  Net n;
  uint16_t err = 0;
  uint32_t h = api()->rx_open(0, 0x100, 0x7FF, 0, 0, &err);
  n.port.on_frame(frame(0x100, {9}));
  api()->rx_close(h);
  uint32_t h2 = api()->rx_open(0, 0x100, 0x7FF, 0, 0, &err);
  CHECK(h2 != 0 && h2 != h);
  canworks_can_frame f{};
  canworks_can_rx_info info{};
  CHECK(api()->rx_read(h2, &f, &info) == 0);
  CHECK(api()->rx_read(h, &f, &info) == -CANWORKS_CAN_ERR_CANCELLED);
}

TEST(receiver_limit_and_inputs) {
  Net n;
  uint16_t err = 0;
  CHECK(api()->rx_open(0, 0x800, 0x7FF, 0, 0, &err) == 0 && err == CANWORKS_CAN_ERR_INPUT);
  CHECK(api()->rx_open(0, 0x100, 0x7FF, 0, 300, &err) == 0 && err == CANWORKS_CAN_ERR_INPUT);
  CHECK(api()->rx_open(3, 0x100, 0x7FF, 0, 0, &err) == 0 && err == CANWORKS_CAN_ERR_NETWORK);
  for (unsigned i = 0; i < CANWORKS_CAN_RECEIVERS; ++i) CHECK(api()->rx_open(0, i, 0x7FF, 0, 0, &err) != 0);
  CHECK(api()->rx_open(0, 0x100, 0x7FF, 0, 0, &err) == 0 && err == CANWORKS_CAN_ERR_FULL);
}

TEST(send_confirmed_by_echo) {
  Net n;
  uint16_t err = 0;
  canworks_can_frame f = frame(0x510, {1, 2});
  uint32_t h = api()->tx_send(0, &f, 0, &err);
  CHECK(h != 0);
  CHECK(api()->tx_poll(h, &err) == 0);
  canworks_can_frame out{};
  uint32_t tag = 0;
  CHECK(n.port.next_tx(out, tag));
  CHECK(out.id == 0x510 && out.dlc == 2);
  n.port.tx_written(tag, false);
  CHECK(api()->tx_poll(h, &err) == 0);
  CHECK(!n.port.own_echo(frame(0x510, {1, 3})));  // not ours
  CHECK(n.port.own_echo(frame(0x510, {1, 2})));
  CHECK(api()->tx_poll(h, &err) == 1);
  CHECK(api()->tx_poll(h, &err) == 2 && err == CANWORKS_CAN_ERR_CANCELLED);  // handle used up
}

TEST(send_times_out_without_echo) {
  Net n;
  uint16_t err = 0;
  canworks_can_frame f = frame(0x510, {1});
  uint32_t h = api()->tx_send(0, &f, 5, &err);
  canworks_can_frame out{};
  uint32_t tag = 0;
  CHECK(n.port.next_tx(out, tag));
  n.port.tx_written(tag, false);
  std::this_thread::sleep_for(std::chrono::milliseconds(10));
  CHECK(api()->tx_poll(h, &err) == 2);
  CHECK(err == CANWORKS_CAN_ERR_TIMEOUT);
  // The late echo frees the slot; every slot can be used again.
  n.port.own_echo(frame(0x510, {1}));
  n.port.expire_echoes(monotonic_us() + 10000000u, 1000000u);
  for (unsigned i = 0; i < CANWORKS_CAN_TX_QUEUE; ++i) {
    uint32_t h2 = api()->tx_send(0, &f, 0, &err);
    CHECK(h2 != 0);
  }
  CHECK(api()->tx_send(0, &f, 0, &err) == 0 && err == CANWORKS_CAN_ERR_FULL);
}

TEST(send_written_without_echo_support) {
  Net n;
  uint16_t err = 0;
  canworks_can_frame f = frame(0x1ABCDE, {}, CANWORKS_CAN_EXTENDED | CANWORKS_CAN_RTR);
  f.dlc = 4;
  uint32_t h = api()->tx_send(0, &f, 0, &err);
  canworks_can_frame out{};
  uint32_t tag = 0;
  CHECK(n.port.next_tx(out, tag));
  n.port.tx_written(tag, true);
  CHECK(api()->tx_poll(h, &err) == 1);
}

TEST(send_failed_write) {
  Net n;
  uint16_t err = 0;
  canworks_can_frame f = frame(0x100, {});
  uint32_t h = api()->tx_send(0, &f, 0, &err);
  canworks_can_frame out{};
  uint32_t tag = 0;
  CHECK(n.port.next_tx(out, tag));
  n.port.tx_failed(tag, CANWORKS_CAN_ERR_BUS);
  CHECK(api()->tx_poll(h, &err) == 2 && err == CANWORKS_CAN_ERR_BUS);
}

TEST(send_guards) {
  PortRules rules;
  rules.owned = [](uint32_t id, bool ext) { return !ext && id == 0x205; };
  Net n(rules);
  uint16_t err = 0;
  canworks_can_frame f = frame(0x205, {0});
  CHECK(api()->tx_send(0, &f, 0, &err) == 0 && err == CANWORKS_CAN_ERR_PROTOCOL);
  f.flags = CANWORKS_CAN_EXTENDED;  // 0x205 extended is not the PDO
  CHECK(api()->tx_send(0, &f, 0, &err) != 0);
  f = frame(0x800, {});
  CHECK(api()->tx_send(0, &f, 0, &err) == 0 && err == CANWORKS_CAN_ERR_INPUT);
  f = frame(0x100, {});
  f.dlc = 9;
  CHECK(api()->tx_send(0, &f, 0, &err) == 0 && err == CANWORKS_CAN_ERR_INPUT);

  rules.override_protocol = true;
  n.port.set_rules(rules);
  f = frame(0x205, {0});
  CHECK(api()->tx_send(0, &f, 0, &err) != 0);

  PortRules lo;
  lo.listen_only = true;
  n.port.set_rules(lo);
  CHECK(api()->tx_send(0, &f, 0, &err) == 0 && err == CANWORKS_CAN_ERR_LISTEN_ONLY);
  CHECK(api()->cyc_start(0, &f, 10000, &err) == 0 && err == CANWORKS_CAN_ERR_LISTEN_ONLY);

  n.port.set_rules({});
  canworks_can_bus_info off{};
  off.state = 3;
  n.port.publish_bus(off);
  CHECK(api()->tx_send(0, &f, 0, &err) == 0 && err == CANWORKS_CAN_ERR_BUS);

  n.port.set_running(false);
  CHECK(api()->tx_send(0, &f, 0, &err) == 0 && err == CANWORKS_CAN_ERR_NOT_RUNNING);
}

TEST(cyclic_job_period_and_update) {
  Net n;
  uint16_t err = 0;
  canworks_can_frame f = frame(0x300, {1});
  CHECK(api()->cyc_start(0, &f, 0, &err) == 0 && err == CANWORKS_CAN_ERR_INPUT);
  uint32_t h = api()->cyc_start(0, &f, 10000, &err);
  CHECK(h != 0);
  canworks_can_frame out[4];
  uint8_t jobs[4];
  uint64_t t = 1000000;
  CHECK(n.port.cyclic_due(t, out, jobs, 4) == 1);  // first frame at once
  n.port.cyclic_sent(jobs[0]);
  CHECK(n.port.cyclic_due(t + 5000, out, jobs, 4) == 0);
  CHECK(n.port.next_cyclic_in(t + 5000) == 5000);
  canworks_can_frame g = frame(0x7FF, {7, 8});  // the identifier stays 0x300
  uint32_t count = 0;
  CHECK(api()->cyc_update(h, &g, 20000, &count, &err) == 0);
  CHECK(count == 1);
  CHECK(n.port.cyclic_due(t + 10000, out, jobs, 4) == 1);
  CHECK(out[0].id == 0x300 && out[0].dlc == 2 && out[0].data[1] == 8);
  n.port.cyclic_sent(jobs[0]);
  CHECK(n.port.cyclic_due(t + 20000, out, jobs, 4) == 0);  // now every 20 ms
  CHECK(n.port.cyclic_due(t + 30000, out, jobs, 4) == 1);
  api()->cyc_stop(h);
  CHECK(n.port.cyclic_due(t + 60000, out, jobs, 4) == 0);
  CHECK(api()->cyc_update(h, &g, 20000, &count, &err) == 2 && err == CANWORKS_CAN_ERR_CANCELLED);
}

TEST(cyclic_limit) {
  Net n;
  uint16_t err = 0;
  canworks_can_frame f = frame(0x300, {1});
  for (unsigned i = 0; i < CANWORKS_CAN_CYCLIC_JOBS; ++i) CHECK(api()->cyc_start(0, &f, 1000, &err) != 0);
  CHECK(api()->cyc_start(0, &f, 1000, &err) == 0 && err == CANWORKS_CAN_ERR_FULL);
}

TEST(cancel_all_on_plc_stop) {
  Net n;
  uint16_t err = 0;
  canworks_can_frame f = frame(0x300, {1});
  uint32_t rx = api()->rx_open(0, 0x1, 0x7FF, 0, 0, &err);
  uint32_t job = api()->cyc_start(0, &f, 1000, &err);
  uint32_t tx = api()->tx_send(0, &f, 0, &err);
  CHECK(n.port.active());
  n.port.cancel_all();
  canworks_can_frame g{};
  canworks_can_rx_info info{};
  uint32_t count;
  CHECK(api()->rx_read(rx, &g, &info) == -CANWORKS_CAN_ERR_CANCELLED);
  CHECK(api()->cyc_update(job, &f, 1000, &count, &err) == 2 && err == CANWORKS_CAN_ERR_CANCELLED);
  CHECK(api()->tx_poll(tx, &err) == 2 && err == CANWORKS_CAN_ERR_CANCELLED);
  // The queued frame is dropped, not sent.
  uint32_t tag;
  CHECK(!n.port.next_tx(g, tag));
  CHECK(!n.port.active());
}

TEST(bus_info) {
  Net n;
  canworks_can_bus_info info{};
  uint16_t err = 0;
  canworks_can_bus_info pub{};
  pub.state = 2;
  pub.tx_errors = 130;
  pub.bus_load = 37;
  n.port.publish_bus(pub);
  n.port.count_rx();
  CHECK(api()->bus_info(0, &info, &err) == 0);
  CHECK(info.state == 2 && info.tx_errors == 130 && info.bus_load == 37 && info.rx_count == 1);
  n.port.set_running(false);
  CHECK(api()->bus_info(0, &info, &err) == 0 && info.state == 4);
  CHECK(api()->bus_info(5, &info, &err) == 2 && err == CANWORKS_CAN_ERR_NETWORK);
}

TEST(receivers_from_another_thread) {
  Net n;
  uint16_t err = 0;
  uint32_t h = api()->rx_open(0, 0x10, 0x7F0, 0, 256, &err);
  std::atomic<bool> done{false};
  std::thread producer([&] {
    for (uint32_t i = 0; i < 20000; ++i) {
      canworks_can_frame f = frame(0x10 + (i & 0xF), {});
      f.dlc = 4;
      std::memcpy(f.data, &i, 4);
      n.port.on_frame(f);
    }
    done.store(true);
  });
  uint32_t last = 0, seen = 0;
  bool first = true, ordered = true;
  canworks_can_frame f{};
  canworks_can_rx_info info{};
  auto drain = [&] {
    while (api()->rx_read(h, &f, &info) == 1) {
      uint32_t v;
      std::memcpy(&v, f.data, 4);
      if (!first && v <= last) ordered = false;
      first = false;
      last = v;
      ++seen;
    }
  };
  while (!done.load()) drain();
  producer.join();
  drain();
  CHECK(ordered);
  CHECK(seen + info.dropped == 20000);
}

// --- Signal packing (shared fixture, also used by the Python and ST packers) ---

TEST(signal_vectors) {
  std::ifstream in(FIXTURES_DIR "/can_signals.json");
  std::stringstream ss;
  ss << in.rdbuf();
  cJSON* root = cJSON_Parse(ss.str().c_str());
  CHECK(root != nullptr);
  if (!root) return;
  int n = 0;
  const cJSON* cases = cJSON_GetObjectItem(root, "cases");
  for (const cJSON* c = cases ? cases->child : nullptr; c; c = c->next, ++n) {
    unsigned start = static_cast<unsigned>(cJSON_GetObjectItem(c, "start_bit")->valuedouble);
    unsigned length = static_cast<unsigned>(cJSON_GetObjectItem(c, "length")->valuedouble);
    bool big = cJSON_IsTrue(cJSON_GetObjectItem(c, "big_endian"));
    bool sign = cJSON_IsTrue(cJSON_GetObjectItem(c, "signed"));
    auto bytes = [](const char* hex, uint8_t* out) {
      for (int i = 0; i < 8; ++i) out[i] = static_cast<uint8_t>(std::stoul(std::string(hex + 2 * i, 2), nullptr, 16));
    };
    uint8_t data[8], packed[8];
    bytes(cJSON_GetObjectItem(c, "data")->valuestring, data);
    bytes(cJSON_GetObjectItem(c, "packed")->valuestring, packed);
    // The value may not be exact as a double above 2^53; compare via packing.
    uint64_t raw = canworks_can::unpack_signal(data, 8, start, length, big);
    uint8_t mine[8] = {};
    canworks_can::pack_signal(mine, start, length, big, raw);
    CHECK_MSG(std::memcmp(mine, packed, 8) == 0, "case " + std::to_string(n));
    double want = cJSON_GetObjectItem(c, "value")->valuedouble;
    double got = sign ? static_cast<double>(canworks_can::sign_extend(raw, length)) : static_cast<double>(raw);
    CHECK_MSG(got == want, "case " + std::to_string(n));
  }
  CHECK(n >= 100);
  cJSON_Delete(root);
}

// --- Raw config ---

namespace {

struct Parsed {
  canworks_raw::RawConfig cfg;
  std::vector<std::string> errors, warnings;
  bool ok = false;
};

Parsed parse(const char* json, bool listen_only = false) {
  Parsed p;
  cJSON* j = cJSON_Parse(json);
  p.ok = canworks_raw::parse_raw(j, "networks[0].raw", listen_only, p.cfg, p.errors, p.warnings);
  cJSON_Delete(j);
  return p;
}

const char* kExample = R"({
  "rx": [ { "name": "Joystick", "id": 291, "dlc": 8, "timeout_ms": 300,
            "status_location": "%IX300.0", "counter_location": "%IW302",
            "signals": [ { "name": "X", "start_bit": 0, "length": 12, "signed": true,
                           "scale": 0.1, "unit": "%", "iec_location": "%IW304" } ] },
          { "name": "AnyBattery", "id": 1536, "mask": 2032,
            "id_location": "%ID308", "data_location": "%IL312" } ],
  "tx": [ { "name": "Lamps", "id": 1281, "dlc": 2, "period_ms": 100,
            "on_change": true, "min_gap_ms": 10, "enable_location": "%QX300.0",
            "signals": [ { "name": "Red", "start_bit": 0, "length": 1, "iec_location": "%QX300.1" } ] },
          { "name": "Wake", "id": 1282, "rtr": true, "dlc": 0, "trigger_location": "%QX300.2" } ] })";

}  // namespace

TEST(raw_config_example) {
  Parsed p = parse(kExample);
  CHECK(p.ok);
  CHECK(p.errors.empty());
  CHECK(p.warnings.empty());
  CHECK(p.cfg.rx.size() == 2 && p.cfg.tx.size() == 2);
  CHECK(p.cfg.rx[0].mask == 0x7FF && p.cfg.rx[1].mask == 0x7F0);
  CHECK(p.cfg.rx[0].need == 8);
  CHECK(p.cfg.tx[0].dlc == 2);
  std::vector<std::pair<canopen_plugin::IecLocation, std::string>> locs;
  canworks_raw::raw_locations(p.cfg, locs);
  CHECK(locs.size() == 8);
}

// Every case of test/fixtures/config/cases-raw.json (the PC tools run the
// same file).
TEST(raw_config_shared_cases) {
  std::ifstream in(FIXTURES_DIR "/config/cases-raw.json");
  std::stringstream ss;
  ss << in.rdbuf();
  cJSON* root = cJSON_Parse(ss.str().c_str());
  CHECK(root != nullptr);
  if (!root) return;
  int n = 0;
  for (const cJSON* c = cJSON_GetObjectItem(root, "cases")->child; c; c = c->next, ++n) {
    std::string name = cJSON_GetObjectItem(c, "name")->valuestring;
    bool listen_only = cJSON_IsTrue(cJSON_GetObjectItem(c, "listen_only"));
    canworks_raw::RawConfig cfg;
    std::vector<std::string> errors, warnings, overrides;
    canworks_raw::parse_raw(cJSON_GetObjectItem(c, "raw"), "networks[0].raw", listen_only, cfg, errors, warnings);
    const cJSON* ids = cJSON_GetObjectItem(c, "protocol_ids");
    if (ids) {
      auto use = [ids](uint32_t id, bool ext) -> std::string {
        char key[16];
        std::snprintf(key, sizeof key, "0x%X", id);
        const cJSON* v = ext ? nullptr : cJSON_GetObjectItem(ids, key);
        return v ? v->valuestring : "";
      };
      canworks_raw::check_protocol_ids(cfg, use, errors, overrides);
    }
    auto expect = [&](const char* key, const std::vector<std::string>& got) {
      const cJSON* want = cJSON_GetObjectItem(c, key);
      if (!want) return;
      size_t k = 0;
      for (const cJSON* w = want->child; w; w = w->next, ++k) {
        bool ok = k < got.size() && got[k].find(w->valuestring) != std::string::npos;
        CHECK_MSG(ok, name + ": " + key + "[" + std::to_string(k) + "] should contain \"" + w->valuestring + "\", got \"" +
                          (k < got.size() ? got[k] : std::string("nothing")) + "\"");
      }
      CHECK_MSG(got.size() == k, name + ": " + std::to_string(got.size()) + " " + key + ", want " + std::to_string(k) +
                                     (got.empty() ? "" : " (first: " + got[0] + ")"));
    };
    expect("errors", errors);
    expect("warnings", warnings);
  }
  CHECK(n >= 20);
  cJSON_Delete(root);
}

// --- Engine ---

TEST(engine_receive) {
  Parsed p = parse(kExample);
  canworks_raw::RawEngine e(p.cfg);
  CHECK(e.input_locations().size() == 5);
  CHECK(e.on_frame(frame(0x123, {0xFF, 0x0F, 0, 0, 0, 0, 0, 0}), 1000));
  // status, counter, X
  CHECK(e.input_values()[0] == 1 && e.input_values()[1] == 1);
  CHECK(static_cast<int16_t>(e.input_values()[2]) == -1);
  // Range entry: last identifier and data.
  e.on_frame(frame(0x603, {1}), 2000);
  e.on_frame(frame(0x60A, {2, 3}), 3000);
  CHECK(e.input_values()[3] == 0x60A);
  CHECK(e.input_values()[4] == 0x0302);
  CHECK(e.rx_status()[1].count == 2);
  // Short frame.
  CHECK(!e.on_frame(frame(0x123, {1, 2}), 4000));
  CHECK(e.rx_status()[0].short_frames == 1);
  // Timeout 300 ms after the last good frame.
  CHECK(e.next_event_in(1000) == 300000);
  CHECK(!e.check_timeouts(300000));
  CHECK(e.check_timeouts(301000));
  CHECK(e.input_values()[0] == 0);
  CHECK(static_cast<int16_t>(e.input_values()[2]) == -1);  // value held
}

TEST(engine_send_periodic_and_on_change) {
  Parsed p = parse(kExample);
  canworks_raw::RawEngine e(p.cfg);
  CHECK(e.output_locations().size() == 3);  // enable, Red, trigger
  // order: Lamps.enable, Lamps.Red, Wake.trigger
  uint64_t out[3] = {1, 0, 0};
  std::vector<canworks_can_frame> frames;
  std::vector<size_t> idx;
  e.set_outputs(out, 0);
  e.due(0, frames, idx);
  CHECK(frames.empty());  // PLC not running
  e.set_plc_running(true, 0);
  e.due(0, frames, idx);
  CHECK(frames.size() == 1 && frames[0].id == 0x501 && frames[0].dlc == 2 && frames[0].data[0] == 0);
  frames.clear();
  e.due(40000, frames, idx);
  CHECK(frames.empty());
  out[1] = 1;  // Red changes 40 ms after the last send
  e.set_outputs(out, 40000);
  e.due(40000, frames, idx);
  CHECK(frames.size() == 1 && frames[0].data[0] == 1);
  frames.clear();
  e.due(100000, frames, idx);
  CHECK(frames.empty());  // next periodic is 100 ms after the change
  e.due(140000, frames, idx);
  CHECK(frames.size() == 1);
  frames.clear();
  // Change within min_gap waits for it.
  out[1] = 0;
  e.set_outputs(out, 145000);
  e.due(145000, frames, idx);
  CHECK(frames.empty());
  CHECK(e.next_event_in(145000) == 5000);
  e.due(150000, frames, idx);
  CHECK(frames.size() == 1 && frames[0].data[0] == 0);
  frames.clear();
  // Enable FALSE stops periodic sends.
  out[0] = 0;
  e.set_outputs(out, 151000);
  e.due(400000, frames, idx);
  CHECK(frames.empty());
}

TEST(engine_trigger_once) {
  Parsed p = parse(kExample);
  canworks_raw::RawEngine e(p.cfg);
  uint64_t out[3] = {0, 0, 0};
  e.set_outputs(out, 0);
  e.set_plc_running(true, 0);
  std::vector<canworks_can_frame> frames;
  std::vector<size_t> idx;
  e.due(0, frames, idx);
  CHECK(frames.empty());
  for (int scan = 0; scan < 3; ++scan) {
    out[2] = 1;
    e.set_outputs(out, 1000 * scan);
    e.due(1000 * scan, frames, idx);
  }
  CHECK(frames.size() == 1);
  CHECK(frames.size() == 1 && frames[0].id == 0x502 && (frames[0].flags & CANWORKS_CAN_RTR) && frames[0].dlc == 0);
  e.set_plc_running(false, 5000);
  out[2] = 0;
  e.set_outputs(out, 6000);
  out[2] = 1;
  e.set_outputs(out, 7000);
  frames.clear();
  e.due(7000, frames, idx);
  CHECK(frames.empty());  // PLC stopped
}

TEST(engine_big_endian_and_fill) {
  Parsed p = parse(R"({"tx":[{"id":16,"dlc":4,"fill":255,"period_ms":10,
     "signals":[{"start_bit":7,"length":16,"byte_order":"big","iec_location":"%QW1"}]}],
     "rx":[{"id":17,"signals":[{"start_bit":7,"length":16,"byte_order":"big","iec_location":"%IW1"}]}]})");
  CHECK(p.ok);
  canworks_raw::RawEngine e(p.cfg);
  uint64_t out[1] = {0x1234};
  canworks_can_frame f = e.build(0, out);
  CHECK(f.dlc == 4 && f.data[0] == 0x12 && f.data[1] == 0x34 && f.data[2] == 0xFF && f.data[3] == 0xFF && f.data[4] == 0);
  e.on_frame(frame(17, {0x12, 0x34}), 0);
  CHECK(e.input_values()[0] == 0x1234);
}

// A simulated plain CAN network end to end: the I/O thread on a loopback
// bridge, a simulated device sending periodically and answering a request,
// config messages in and out, and a program receiver.
TEST(raw_io_on_a_simulated_plain_network) {
  Parsed p = parse(R"({"rx": [{"name": "Joy", "id": 384, "timeout_ms": 500, "status_location": "%IX0.0",
                               "signals": [{"start_bit": 16, "length": 8, "iec_location": "%IB1"}]}],
                       "tx": [{"name": "Ask", "id": 2016, "dlc": 3, "period_ms": 20, "data_location": "%QL0"}]})");
  CHECK(p.ok);
  RawEngine engine(p.cfg);
  RawSimDevices devices;
  std::vector<std::string> errors;
  CHECK(devices.load_text(R"({"raw_devices": [{"name": "joystick",
      "send": [{"id": 384, "dlc": 4, "period_ms": 10, "data": [0, 0, 42, 0]}],
      "replies": [{"on": {"id": 2016, "data": [2, 1, 12]}, "send": {"id": 2024, "data": [4, 65, 12]}}]}],
      "scenarios": {"stop": {"autostart": true, "steps": [{"at_ms": 300, "device": "joystick", "fault": {"stop": true}},
                                                          {"log": "joystick stopped"}]}}})",
                          "simulation.json", ".", "plain", false, true, errors));
  CHECK(errors.empty() && devices.size() == 1);
  PlcPort port(1);
  port.set_rules(PortRules{});
  set_port(1, &port);
  auto bridge = std::make_shared<SimBridge>(true);
  std::atomic<uint64_t> joy{0}, status{0};
  std::atomic<bool> have_out{false};
  RawIoHooks hooks;
  hooks.publish_inputs = [&](const std::vector<uint64_t>& v) {
    status = v[0];
    joy = v[1];
  };
  hooks.latest_outputs = [&](std::vector<uint64_t>& v) {
    v[0] = 0x0C0102;  // bytes 02 01 0C: the device's request
    return !have_out.exchange(true);
  };
  RawIo io(make_bridge_link(bridge), 500000, false, &engine, &port, hooks, &devices);
  io.start();
  uint16_t err = 0;
  uint32_t h = 0;
  for (int i = 0; i < 100 && !port.running(); ++i) std::this_thread::sleep_for(std::chrono::milliseconds(5));
  CHECK(port.running());
  h = port.rx_open(2024, 0x7FF, 0, 8, &err);
  CHECK(h != 0);
  canworks_can_frame f{};
  canworks_can_rx_info info{};
  bool replied = false;
  for (int i = 0; i < 200 && !replied; ++i) {
    std::this_thread::sleep_for(std::chrono::milliseconds(5));
    replied = port.rx_read(h, &f, &info) == 1;
  }
  CHECK(replied && f.dlc == 3 && f.data[1] == 65);
  CHECK(joy == 42 && status == 1);
  CHECK(io.frames_sent() > 0 && io.frames_received() > 0);
  // The scenario stops the device: the message times out.
  for (int i = 0; i < 300 && status != 0; ++i) std::this_thread::sleep_for(std::chrono::milliseconds(5));
  CHECK(status == 0);
  // A step from the CANopen simulator (here: by hand) brings it back.
  set_sim_devices(1, &devices);
  std::string why;
  CHECK(!sim_device_action(1, "pedal", "clear", "stop", -1, why) && why.find("no plain CAN device \"pedal\"") == 0);
  CHECK(!sim_device_action(2, "joystick", "clear", "stop", -1, why));
  CHECK(sim_device_action(1, "joystick", "clear", "stop", -1, why));
  for (int i = 0; i < 200 && status != 1; ++i) std::this_thread::sleep_for(std::chrono::milliseconds(5));
  CHECK(status == 1);
  set_sim_devices(1, nullptr);
  io.stop();
  CHECK(!port.running());
  set_port(1, nullptr);
}

TEST(raw_scenarios_parse) {
  std::vector<canopen_sim::RawScenario> sc;
  std::vector<std::string> errors;
  cJSON* j = cJSON_Parse(R"({"a": {"steps": [{"node": 5, "fault": {"heartbeat": "stop"}}]},
                            "b": {"steps": [{"device": "x", "fault": {"wrong_dlc": 9}}]},
                            "c": {"steps": [{"device": "x", "clear": "all", "after_ms": 10},
                                            {"repeat": {"count": 2, "steps": [{"log": "hi"}]}}]}})");
  CHECK(!canopen_sim::parse_raw_scenarios(j, sc, errors));
  cJSON_Delete(j);
  auto has = [&](const std::string& m) {
    for (const auto& e : errors)
      if (e.find(m) == 0) return true;
    return false;
  };
  CHECK(has("scenarios.a.steps[0]: unknown key \"node\""));
  CHECK(has("scenarios.b.steps[0].fault: \"wrong_dlc\" must be an integer 0-8"));
  CHECK(sc.size() == 1 && sc[0].name == "c" && sc[0].steps[1].steps.size() == 1 && sc[0].steps[1].count == 2);
}

int main(int argc, char** argv) { return check::run_all(argc, argv); }
