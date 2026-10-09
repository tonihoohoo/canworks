// Raw CAN unit tests (specs can-plc-frames and can-raw-messages): the PLC
// frame port's receivers, single frames, cyclic jobs, guards and cancel, and
// the C table the library blocks call. Needs no CAN interface or Lely.

#include <atomic>
#include <cstring>
#include <thread>

#include "can/can_plc_api.h"
#include "can/raw/plc_frames.h"
#include "check.hpp"

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
  return static_cast<const canworks_can_api_v1*>(canworks_can_api(CANWORKS_CAN_API_VERSION));
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
  CHECK(canworks_can_api(2) == nullptr);
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

int main(int argc, char** argv) { return check::run_all(argc, argv); }
