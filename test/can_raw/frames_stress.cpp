// Stress test of the PLC frame port across PLC tasks (spec can-plc-frames,
// "Frame blocks from several PLC tasks"): four threads stand in for four PLC
// tasks and call send, receive-open and cyclic-start on one network at the
// same time, while a fifth plays the raw I/O thread. Every CAN_SEND must
// go out exactly once and report DONE, and no two tasks may hold the same
// receiver or cyclic job. Built on its own (plc_frames.cpp only), so the
// weekly workflow can build it with -DCANWORKS_TSAN=ON.

#include <array>
#include <atomic>
#include <chrono>
#include <cstring>
#include <mutex>
#include <set>
#include <string>
#include <thread>
#include <utility>
#include <vector>

#include "can/can_plc_api.h"
#include "can/raw/plc_frames.h"
#include "check.hpp"

using namespace canworks_raw;

namespace {

constexpr int kThreads = 4;
constexpr int kRounds = 3000;

const canworks_can_api_v1* api() {
  return static_cast<const canworks_can_api_v1*>(canworks_can_api_table(CANWORKS_CAN_API_VERSION));
}

unsigned slot_of(uint32_t handle) { return (handle >> 19) & 0xFFu; }

canworks_can_frame frame(uint32_t id, uint8_t task, uint32_t seq) {
  canworks_can_frame f{};
  f.id = id;
  f.dlc = 5;
  f.data[0] = task;
  std::memcpy(f.data + 1, &seq, 4);
  return f;
}

}  // namespace

TEST(frame_blocks_from_four_tasks) {
  PlcPort port(0);
  port.set_rules(PortRules{});
  port.set_running(true);
  set_port(0, &port);

  // Who holds each receiver and cyclic job slot (-1: nobody).
  std::array<std::atomic<int>, CANWORKS_CAN_RECEIVERS> rx_owner;
  std::array<std::atomic<int>, CANWORKS_CAN_CYCLIC_JOBS> job_owner;
  for (auto& o : rx_owner) o.store(-1);
  for (auto& o : job_owner) o.store(-1);

  std::atomic<bool> stop{false};
  std::mutex wire_mutex;
  std::vector<std::pair<uint8_t, uint32_t>> wire;  // (task, seq) of every single frame written
  // The raw I/O thread: writes queued frames (confirmed at once), runs the
  // cyclic jobs, feeds the receivers and publishes bus figures.
  std::thread raw([&] {
    uint32_t n = 0;
    while (!stop.load()) {
      canworks_can_frame f;
      uint32_t tag;
      while (port.next_tx(f, tag)) {
        uint32_t seq;
        std::memcpy(&seq, f.data + 1, 4);
        {
          std::lock_guard<std::mutex> lock(wire_mutex);
          wire.emplace_back(f.data[0], seq);
        }
        port.tx_written(tag, true);
      }
      canworks_can_frame due[CANWORKS_CAN_CYCLIC_JOBS];
      uint8_t jobs[CANWORKS_CAN_CYCLIC_JOBS];
      uint64_t now = monotonic_us();
      int k = port.cyclic_due(now, due, jobs, CANWORKS_CAN_CYCLIC_JOBS);
      for (int i = 0; i < k; ++i) port.cyclic_sent(jobs[i]);
      for (uint8_t t = 0; t < kThreads; ++t) port.on_frame(frame(0x300 + t, t, n));
      canworks_can_bus_info info{};
      info.state = 0;
      info.tx_errors = static_cast<uint16_t>(n);
      info.rx_errors = static_cast<uint16_t>(n);
      port.publish_bus(info);
      ++n;
    }
  });

  std::atomic<int> sends_done{0}, send_errors{0}, wrong_frames{0}, shared_slots{0}, lost_jobs{0}, torn_bus{0};
  std::atomic<int> full{0};
  auto task = [&](uint8_t t) {
    for (int round = 0; round < kRounds; ++round) {
      uint16_t err = 0;
      // CAN_SEND: queue a frame and wait for its result.
      canworks_can_frame f = frame(0x200 + t, t, static_cast<uint32_t>(round));
      uint32_t h = api()->tx_send(0, &f, 1000, &err);
      if (!h) {
        ++send_errors;
      } else {
        int st = 0;
        while ((st = api()->tx_poll(h, &err)) == 0) std::this_thread::yield();
        if (st == 1)
          ++sends_done;
        else
          ++send_errors;
      }
      // CAN_RECEIVE: open on this task's identifier; only its frames arrive.
      uint32_t rh = api()->rx_open(0, 0x300 + t, 0x7FF, 0, 8, &err);
      if (!rh) {
        if (err == CANWORKS_CAN_ERR_FULL) ++full;
      } else {
        if (rx_owner[slot_of(rh)].exchange(t) != -1) ++shared_slots;
        canworks_can_frame got{};
        canworks_can_rx_info info{};
        for (int k = 0; k < 4; ++k)
          if (api()->rx_read(rh, &got, &info) == 1 && (got.id != 0x300u + t || got.data[0] != t)) ++wrong_frames;
        rx_owner[slot_of(rh)].store(-1);
        api()->rx_close(rh);
      }
      // CAN_SEND_CYCLIC: start a job, update it, stop it.
      canworks_can_frame c = frame(0x400 + t, t, static_cast<uint32_t>(round));
      uint32_t jh = api()->cyc_start(0, &c, 1000, &err);
      if (!jh) {
        if (err == CANWORKS_CAN_ERR_FULL) ++full;
      } else {
        if (job_owner[slot_of(jh)].exchange(t) != -1) ++shared_slots;
        uint32_t count = 0;
        if (api()->cyc_update(jh, &c, 2000, &count, &err) != 0) ++lost_jobs;
        job_owner[slot_of(jh)].store(-1);
        api()->cyc_stop(jh);
      }
      // CAN_BUS_INFO returns, with figures from one publication.
      canworks_can_bus_info bi{};
      api()->bus_info(0, &bi, &err);
      if (bi.tx_errors != bi.rx_errors) ++torn_bus;
    }
  };
  std::vector<std::thread> tasks;
  for (uint8_t t = 0; t < kThreads; ++t) tasks.emplace_back(task, t);
  for (auto& th : tasks) th.join();
  stop.store(true);
  raw.join();
  set_port(0, nullptr);

  // Every frame on the wire once, and one per DONE.
  std::set<std::pair<uint8_t, uint32_t>> unique(wire.begin(), wire.end());
  size_t duplicates = wire.size() - unique.size();
  CHECK_MSG(duplicates == 0, std::to_string(duplicates) + " frames written twice");
  CHECK_MSG(send_errors.load() == 0, std::to_string(send_errors.load()) + " sends failed");
  CHECK_MSG(sends_done.load() == kThreads * kRounds,
            std::to_string(sends_done.load()) + " of " + std::to_string(kThreads * kRounds) + " sends DONE");
  CHECK_MSG(unique.size() == static_cast<size_t>(kThreads * kRounds),
            std::to_string(unique.size()) + " different frames written for " + std::to_string(kThreads * kRounds) +
                " sends");
  CHECK_MSG(shared_slots.load() == 0, std::to_string(shared_slots.load()) + " slots held by two tasks");
  CHECK_MSG(wrong_frames.load() == 0, std::to_string(wrong_frames.load()) + " frames for another task's receiver");
  CHECK_MSG(lost_jobs.load() == 0, std::to_string(lost_jobs.load()) + " cyclic jobs taken over by another task");
  CHECK_MSG(torn_bus.load() == 0, std::to_string(torn_bus.load()) + " bus figures mixed from two publications");
  CHECK_MSG(full.load() == 0, std::to_string(full.load()) + " opens refused as full");
}

// A receiver changed from 0x100 to 0x200 (closed and opened again, as
// CAN_RECEIVE does) while the raw thread keeps matching frames of 0x100:
// none of them may reach the receiver after the change.
TEST(receiver_reopen_drops_frames_of_the_old_filter) {
  PlcPort port(0);
  port.set_rules(PortRules{});
  port.set_running(true);
  set_port(0, &port);
  std::atomic<bool> stop{false};
  std::thread raw([&] {
    uint32_t n = 0;
    while (!stop.load()) port.on_frame(frame(0x100, 0, n++));
  });
  int stale = 0;
  for (int round = 0; round < 20000; ++round) {
    uint16_t err = 0;
    uint32_t h = api()->rx_open(0, 0x100, 0x7FF, 0, 4, &err);
    api()->rx_close(h);
    h = api()->rx_open(0, 0x200, 0x7FF, 0, 4, &err);
    canworks_can_frame got{};
    canworks_can_rx_info info{};
    while (api()->rx_read(h, &got, &info) == 1)
      if (got.id != 0x200) ++stale;
    api()->rx_close(h);
  }
  stop.store(true);
  raw.join();
  set_port(0, nullptr);
  CHECK_MSG(stale == 0, std::to_string(stale) + " frames of the old filter delivered");
}

// CAN_BUS_INFO while the raw thread publishes all the time: every call
// returns figures from one publication.
TEST(bus_info_while_published) {
  PlcPort port(0);
  port.set_running(true);
  set_port(0, &port);
  std::atomic<bool> stop{false};
  std::thread raw([&] {
    for (uint16_t n = 0; !stop.load(); ++n) {
      canworks_can_bus_info info{};
      info.tx_errors = n;
      info.rx_errors = n;
      info.bus_off_count = n;
      port.publish_bus(info);
    }
  });
  int torn = 0;
  for (int k = 0; k < 200000; ++k) {
    canworks_can_bus_info bi{};
    uint16_t err = 0;
    api()->bus_info(0, &bi, &err);
    if (bi.tx_errors != bi.rx_errors || bi.rx_errors != static_cast<uint16_t>(bi.bus_off_count)) ++torn;
  }
  stop.store(true);
  raw.join();
  set_port(0, nullptr);
  CHECK_MSG(torn == 0, std::to_string(torn) + " mixed readings");
}

int main(int argc, char** argv) { return check::run_all(argc, argv); }
