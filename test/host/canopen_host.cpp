// canopen_host.cpp - runs the canworks engine (engine.h) in process with a
// stand-in PLC scan over a byte image, as canworks-bridge does without its
// Modbus server, so the engine can be run against a real SocketCAN bus
// without a PLC.
//
//   canopen_host <canworks.json> [seconds] [pingpong|rtd|bus|fixed|two|slave|j1939]
//
// The scan runs every 10 ms. Once a second it prints the inputs and the node
// status bit %IX10.0. Locations are byte-addressed, as in a bridge config.
//
// pingpong (default): computes `%QD100 := %ID100 + 1`. Exits 0 if, at the
// end, the status bit is TRUE and %ID100 rose by at least 5 during the last
// half of the run; 1 otherwise.
//
// rtd: reads the four temperatures of config/rtd-sensor (%IW100, %IW102,
// %IW104, %IW106, INT in 0.1 degC) as test/sensor/run.sh simulates them and
// computes the starter program's alarm `%QX100.0 := AI0 > 25.0 degC`. Exits 0
// if the status bit is TRUE at the end and, during the last half of the run,
// every temperature stayed in its simulated range and AI0 changed; 1
// otherwise.
//
// two: two networks (config/two-networks), one ping-pong node on each;
// computes `%QD100 := %ID100 + 1` and `%QD104 := %ID104 + 1`. Exits 0 if both
// status bits %IX10.0 and %IX10.1 are TRUE at the end and both counters rose
// by at least 5 during the last half of the run.
//
// slave: test/slave/run.sh, a master network and canworks' own slave network
// joined by cangw; the master computes `%QW12 := %IW12 + 1` and the slave
// echoes `%QW300 := %IW300`. Exits 0 if the master's status bit %IX10.0 and
// the slave's comm OK bit %IX303.0 are TRUE at the end and %IW12 rose by at
// least 5 during the last half of the run.
//
// fixed: the fixed-mapping I/O module of test/fixed/run.sh; computes
// `%QB40 := %IB40`. Exits 0 if the status bit is TRUE at the end and, during
// the last half of the run, %IB40 stayed in 10-50 and changed.
//
// j1939: the J1939 example (examples/j1939) of test/j1939/run.sh against
// canworks-j1939-sim as the engine; computes `%QW210 := %IW210 + 1`
// (Setpoint), `%QB204 := 1` (Run) and `%QB205 := 3` (Mode). The script stops
// the simulator, takes the interface down and up, starts it again and stops
// it before the end; then an ECU with a lower NAME claims address 128. Exits
// 0 if the claim state %IB200 went claimed, no bus, claimed again, the
// address %IB201 went 128 then 129 (moved within the range, claimed at the
// end), the Pressures status bit
// %IX202.0 was TRUE while Pressure %IW210 changed and is FALSE at the end
// (timed out), and ComponentInfo brought Starts %IW216 = 42. The J1939
// message table (canworks_j1939_api version 2, the engine side of change 3's
// mailboxes) is used as a program would, from the first claim on: a receiver
// for ComponentInfo from 0, one for Extra (PGN 65310, which no config entry
// receives), a 40-byte send to 0 (PGN 0xD000, RTS/CTS), a 20-byte broadcast
// (PGN 65300, BAM), a request for ComponentInfo to 0, the ECU info and a
// search; each must succeed (run.sh checks what the simulator received).

#include <signal.h>

#include <chrono>
#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <memory>
#include <string>
#include <thread>
#include <vector>

#include "canopen_runtime.h"
#include "engine.h"
#include "fake_host.hpp"
#include "j1939_plc_api.h"
#include "log.h"

namespace {

volatile sig_atomic_t g_stop = 0;
void on_signal(int) { g_stop = 1; }

// The j1939 program's use of the message blocks: one step after another,
// each polled once per scan as a block would.
struct ProgramBlocks {
  const canworks_j1939_api_v2* api = nullptr;
  bool started = false, checked_ecu = false;
  std::chrono::steady_clock::time_point t0, start;
  uint32_t rx = 0, rx_extra = 0, send = 0, request = 0;
  int sends_done = 0;  // 1: the long send, 2: the broadcast
  bool received = false, extra = false, answered = false, ecu_ok = false, found = false;
  std::string notes;  // what happened, in order

  void note(const std::string& what) {
    const long ms = (long)std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now() - t0)
                        .count();
    std::printf("t=%5ldms  program blocks: %s\n", ms, what.c_str());
    std::fflush(stdout);
    notes += (notes.empty() ? "" : "; ") + what;
  }
  void fail(const char* what, uint16_t err) { note(std::string(what) + " error " + std::to_string(err)); }

  static std::vector<uint8_t> payload(int which) {
    std::vector<uint8_t> d(which == 1 ? 40 : 20);
    for (size_t i = 0; i < d.size(); ++i) d[i] = static_cast<uint8_t>(which == 1 ? i * 3 + 1 : 0xA0 + i);
    return d;
  }
  void start_send(int which) {
    uint16_t err = 0;
    const std::vector<uint8_t> d = payload(which);
    send = api->send_start(0, which == 1 ? 0xD000 : 65300, which == 1 ? 0 : 255, 6, d.data(),
                           static_cast<uint16_t>(d.size()), 0, &err);
    if (!send) fail(which == 1 ? "send 0xD000 to 0" : "broadcast 65300", err);
  }

  void scan(bool claimed) {
    using clock = std::chrono::steady_clock;
    uint16_t err = 0;
    if (!started) {
      if (!claimed) return;
      started = true;
      start = clock::now();
      rx = api->rx_open(0, 65282, 0, 0, 0, &err);
      if (!rx) fail("receiver for 65282", err);
      rx_extra = api->rx_open(0, 65310, 255, 0, 0, &err);
      if (!rx_extra) fail("receiver for 65310", err);
      start_send(1);
      return;
    }
    static canworks_j1939_msg msg;  // 1.8 kB: not on the stack of every scan
    if (rx) {
      canworks_j1939_rx_info info;
      const int r = api->rx_read(rx, &msg, &info);
      if (r == 1 && !received && msg.source == 0 && msg.length == 40 && msg.data[4] == 42 && msg.data[5] == 0) {
        received = true;
        note("received ComponentInfo from 0 (40 bytes, Starts=42)");
      } else if (r < 0) {
        fail("receiver read", static_cast<uint16_t>(-r));
        rx = 0;
      }
    }
    if (rx_extra) {
      canworks_j1939_rx_info info;
      const int r = api->rx_read(rx_extra, &msg, &info);
      if (r == 1 && !extra && msg.source == 0 && msg.length == 8) {
        extra = true;
        note("received Extra (PGN 65310) from 0, no config entry for it");
      } else if (r < 0) {
        fail("receiver 65310 read", static_cast<uint16_t>(-r));
        rx_extra = 0;
      }
    }
    if (send) {
      const int r = api->send_poll(send, &err);
      if (r != 0) {
        send = 0;
        if (r == 2) {
          fail(sends_done == 0 ? "send 0xD000 to 0" : "broadcast 65300", err);
        } else {
          note(sends_done == 0 ? "sent 40 bytes of PGN 0xD000 to 0" : "broadcast 20 bytes of PGN 65300");
          if (++sends_done == 1) start_send(2);
        }
        if (sends_done == 2 || r == 2) {
          request = api->request_start(0, 65282, 0, 0, &err);
          if (!request) fail("request 65282 from 0", err);
        }
      }
    }
    if (request) {
      const int r = api->request_poll(request, &msg, &err);
      if (r == 1) {
        answered = msg.source == 0 && msg.length == 40 && msg.data[4] == 42;
        note(std::string("request for 65282 answered by ") + std::to_string(msg.source) + " with " +
             std::to_string(msg.length) + " bytes");
        request = 0;
      } else if (r == 2) {
        fail("request 65282 from 0", err);
        request = 0;
      }
    }
    // The ECU snapshot is published every 100 ms: read it a little later.
    if (!checked_ecu && clock::now() - start >= std::chrono::milliseconds(500)) {
      checked_ecu = true;
      canworks_j1939_ecu_info info;
      if (api->ecu_info(0, &info, &err) == 0) {
        ecu_ok = info.state == 1 && info.address == 128 && info.ecu_count >= 1 && info.name != 0;
        note("ECU info: state " + std::to_string(info.state) + ", address " + std::to_string(info.address) + ", " +
             std::to_string(info.ecu_count) + " other ECU(s)");
      } else {
        fail("ECU info", err);
      }
      canworks_j1939_ecu_found f;
      if (api->find_ecu(0, 0, 0, &f, &err) == 0) {
        found = f.found && f.address == 0 && f.count >= 1;
        note("find ECU (mask 0): found " + std::to_string(f.found) + ", address " + std::to_string(f.address) + ", " +
             std::to_string(f.count) + " match(es)");
      } else {
        fail("find ECU", err);
      }
    }
  }
  bool ok() const { return received && extra && sends_done == 2 && answered && ecu_ok && found; }
};

}  // namespace

int main(int argc, char** argv) {
  if (argc < 2) {
    std::fprintf(stderr, "usage: %s <canworks.json> [seconds] [pingpong|rtd|bus|fixed|two|slave|j1939]\n", argv[0]);
    return 2;
  }
  const int seconds = argc > 2 ? std::atoi(argv[2]) : 10;
  const bool rtd = argc > 3 && std::strcmp(argv[3], "rtd") == 0;
  // bus: the ping-pong program, but passes when the bus state byte %IB110
  // went 1 -> 0 -> 1 (test/bus/run.sh takes the interface down and up).
  const bool bus = argc > 3 && std::strcmp(argv[3], "bus") == 0;
  const bool fixed = argc > 3 && std::strcmp(argv[3], "fixed") == 0;
  const bool two = argc > 3 && std::strcmp(argv[3], "two") == 0;
  const bool slave = argc > 3 && std::strcmp(argv[3], "slave") == 0;
  const bool j1939 = argc > 3 && std::strcmp(argv[3], "j1939") == 0;
  std::string claim_states;  // distinct successive values of %IB200
  int last_claim = -1;
  int last_address = -1;
  std::string addresses;  // distinct successive values of %IB201
  bool pressures_seen = false, pressure_moved = false, starts_seen = false;
  int first_pressure = -1;
  bool fixed_in_range = true, fixed_moved = false;
  uint8_t fixed_first = 0;
  if (argc > 3 && !rtd && !bus && !fixed && !two && !slave && !j1939 && std::strcmp(argv[3], "pingpong") != 0) {
    std::fprintf(stderr, "canopen_host: unknown program '%s'\n", argv[3]);
    return 2;
  }
  // The ranges test/sensor/run.sh gives the simulated channels, in 0.1 degC.
  const int lo[4] = {200, 300, 400, -100}, hi[4] = {260, 360, 460, -40};
  bool rtd_in_range = true, rtd_moved = false, rtd_alarm_seen = false;
  int16_t rtd_first = 0;
  signal(SIGINT, on_signal);
  signal(SIGTERM, on_signal);
  // As canworks-bridge: one no-op SIGUSR1 handler before any network starts,
  // so a Lely poll that ends never puts the default action back while the
  // other networks still wake each other with it.
  struct sigaction wake;
  std::memset(&wake, 0, sizeof(wake));
  wake.sa_handler = [](int) {};
  sigaction(SIGUSR1, &wake, nullptr);

  canopen_plugin::canopen_init_logging();
  ProgramBlocks blocks;
  if (j1939) {
    blocks.api = static_cast<const canworks_j1939_api_v2*>(canworks_j1939_api_table(2));
    if (!blocks.api) {
      std::fprintf(stderr, "canopen_host: no J1939 message table version 2\n");
      return 2;
    }
  }

  std::unique_ptr<fake_host::Image> img(new fake_host::Image);
  canopen_plugin::ImageLimits limits;
  limits.buffer_size = fake_host::kSize;
  limits.force_simulate = canopen_plugin::force_simulate_from_env(std::getenv("CANWORKS_FORCE_SIMULATE"));
  canopen_plugin::Engine engine;
  if (!engine.prepare(argv[1], limits, "test")) {
    std::fprintf(stderr, "canopen_host: config rejected\n");
    return 1;
  }
  engine.start();

  using clock = std::chrono::steady_clock;
  const auto t0 = clock::now();
  blocks.t0 = t0;
  auto next = t0;
  auto next_print = t0 + std::chrono::seconds(1);
  const auto half = t0 + std::chrono::milliseconds(seconds * 500);
  bool have_mid = false;
  uint32_t mid = 0, mid2 = 0;
  std::string bus_states;  // distinct successive values of %IB110
  int last_bus = -1;

  while (!g_stop && clock::now() - t0 < std::chrono::seconds(seconds)) {
    engine.cycle_start(*img);
    auto ai = [&](int ch) { return static_cast<int16_t>(img->int_in[100 + 2 * ch]); };
    if (j1939) {
      img->int_out[210] = static_cast<uint16_t>(img->int_in[210] + 1);  // Setpoint
      img->byte_out[204] = 1;                                            // Run
      img->byte_out[205] = 3;                                            // Mode
    } else if (rtd)
      img->bool_out[100][0] = ai(0) > 250;  // %QX100.0 := AI0 > 25.0 degC
    else if (fixed)
      img->byte_out[40] = img->byte_in[40];  // %QB40 := %IB40
    else if (slave) {
      img->int_out[12] = static_cast<uint16_t>(img->int_in[12] + 1);  // master: %QW12 := %IW12 + 1
      img->int_out[300] = img->int_in[300];                            // slave: %QW300 := %IW300
    } else
      img->dint_out[100] = img->dint_in[100] + 1;  // %QD100 := %ID100 + 1
    if (two) img->dint_out[104] = img->dint_in[104] + 1;  // %QD104 := %ID104 + 1
    engine.cycle_end(*img);

    if (bus && img->byte_in[110] != last_bus) {
      last_bus = img->byte_in[110];
      bus_states += (bus_states.empty() ? "" : " ") + std::to_string(last_bus);
      const long ms = (long)std::chrono::duration_cast<std::chrono::milliseconds>(clock::now() - t0).count();
      std::printf("t=%5ldms  bus state %%IB110=%d\n", ms, last_bus);
      std::fflush(stdout);
    }
    if (j1939) {
      if (img->byte_in[200] != last_claim) {
        last_claim = img->byte_in[200];
        claim_states += (claim_states.empty() ? "" : " ") + std::to_string(last_claim);
        const long ms = (long)std::chrono::duration_cast<std::chrono::milliseconds>(clock::now() - t0).count();
        std::printf("t=%5ldms  claim state %%IB200=%d  address %%IB201=%u\n", ms, last_claim,
                    (unsigned)img->byte_in[201]);
        std::fflush(stdout);
      }
      if (img->byte_in[201] != last_address) {
        last_address = img->byte_in[201];
        addresses += (addresses.empty() ? "" : " ") + std::to_string(last_address);
      }
      if (img->bool_in[202][0]) {
        pressures_seen = true;
        if (first_pressure < 0) first_pressure = img->int_in[210];
        pressure_moved = pressure_moved || img->int_in[210] != first_pressure;
      }
      starts_seen = starts_seen || (img->bool_in[202][3] && img->int_in[216] == 42);
      blocks.scan(last_claim == 1);
    }
    if (!have_mid && clock::now() >= half) {
      mid = img->dint_in[100];
      mid2 = slave ? img->int_in[12] : img->dint_in[104];
      rtd_first = ai(0);
      fixed_first = img->byte_in[40];
      have_mid = true;
    }
    if (fixed && have_mid) {
      fixed_in_range = fixed_in_range && img->byte_in[40] >= 10 && img->byte_in[40] <= 50;
      fixed_moved = fixed_moved || img->byte_in[40] != fixed_first;
    }
    if (rtd && have_mid) {
      for (int ch = 0; ch < 4; ++ch) rtd_in_range = rtd_in_range && ai(ch) >= lo[ch] && ai(ch) <= hi[ch];
      rtd_moved = rtd_moved || ai(0) != rtd_first;
      rtd_alarm_seen = rtd_alarm_seen || (int)img->bool_out[100][0];
    }
    if (clock::now() >= next_print) {
      const long t = (long)std::chrono::duration_cast<std::chrono::seconds>(clock::now() - t0).count();
      if (j1939)
        std::printf("t=%2lds  %%IW210=%u  %%IX202.0=%d  %%IW216=%u  %%IX202.3=%d\n", t, (unsigned)img->int_in[210],
                    (int)img->bool_in[202][0], (unsigned)img->int_in[216], (int)img->bool_in[202][3]);
      else if (fixed)
        std::printf("t=%2lds  %%IB40=%u  %%IX10.0=%d\n", t, (unsigned)img->byte_in[40], (int)img->bool_in[10][0]);
      else if (rtd)
        std::printf("t=%2lds  AI0..AI3=%.1f %.1f %.1f %.1f degC  alarm=%d  %%IX10.0=%d\n", t, ai(0) / 10.0,
                    ai(1) / 10.0, ai(2) / 10.0, ai(3) / 10.0, (int)img->bool_out[100][0], (int)img->bool_in[10][0]);
      else if (slave)
        std::printf("t=%2lds  %%IW12=%u  %%IX10.0=%d  %%IW300=%u  %%IX303.0=%d\n", t, (unsigned)img->int_in[12],
                    (int)img->bool_in[10][0], (unsigned)img->int_in[300], (int)img->bool_in[303][0]);
      else if (two)
        std::printf("t=%2lds  %%ID100=%u  %%IX10.0=%d  %%ID104=%u  %%IX10.1=%d\n", t, (unsigned)img->dint_in[100],
                    (int)img->bool_in[10][0], (unsigned)img->dint_in[104], (int)img->bool_in[10][1]);
      else
        std::printf("t=%2lds  %%ID100=%u  %%IX10.0=%d\n", t, (unsigned)img->dint_in[100], (int)img->bool_in[10][0]);
      std::fflush(stdout);
      next_print += std::chrono::seconds(1);
    }
    next += std::chrono::milliseconds(10);
    std::this_thread::sleep_until(next);
  }

  const uint32_t last = img->dint_in[100], last2 = slave ? img->int_in[12] : img->dint_in[104];
  const bool slave_ok = img->bool_in[303][0] != 0;
  const bool up = img->bool_in[10][0] != 0, up2 = img->bool_in[10][1] != 0;
  const bool pressures_at_end = img->bool_in[202][0] != 0;
  const unsigned address_at_end = img->byte_in[201];
  engine.stop();

  if (j1939) {
    // Claimed, then no bus, then claimed again.
    size_t a = (" " + claim_states + " ").find(" 1 ");
    size_t b = a == std::string::npos ? a : (" " + claim_states + " ").find(" 3 ", a);
    size_t c = b == std::string::npos ? b : (" " + claim_states + " ").find(" 1 ", b);
    const bool reclaimed = c != std::string::npos && last_claim == 1;
    // Lost 128 to the lower NAME, then claimed 129.
    const bool moved = (" " + addresses + " ").find(" 128 ") != std::string::npos && address_at_end == 129;
    const bool ok =
        reclaimed && moved && pressures_seen && pressure_moved && !pressures_at_end && starts_seen && blocks.ok();
    std::printf("%s: claim states %s, addresses %s (%u at the end), Pressures %s and %s, %s at the end, Starts=42 %s, "
                "program blocks %s (%s)\n",
                ok ? "PASS" : "FAIL", claim_states.c_str(), addresses.c_str(), address_at_end, pressures_seen ? "seen" : "not seen",
                pressure_moved ? "changed" : "did not change", pressures_at_end ? "still TRUE" : "timed out",
                starts_seen ? "seen" : "not seen", blocks.ok() ? "ok" : "FAILED", blocks.notes.c_str());
    return ok ? 0 : 1;
  }
  if (bus) {
    const bool ok = (" " + bus_states + " ").find(" 1 0 1 ") != std::string::npos;
    std::printf("%s: bus state byte went %s\n", ok ? "PASS" : "FAIL", bus_states.c_str());
    return ok ? 0 : 1;
  }
  if (fixed) {
    const bool ok = up && have_mid && fixed_in_range && fixed_moved;
    std::printf("%s: status bit %s, %%IB40 %s 10-50 and %s\n", ok ? "PASS" : "FAIL", up ? "TRUE" : "FALSE",
                fixed_in_range ? "stayed in" : "left", fixed_moved ? "changed" : "did not change");
    return ok ? 0 : 1;
  }
  if (rtd) {
    const bool ok = up && have_mid && rtd_in_range && rtd_moved;
    std::printf("%s: status bit %s, temperatures %s their simulated ranges, AI0 %s, alarm %s\n",
                ok ? "PASS" : "FAIL", up ? "TRUE" : "FALSE", rtd_in_range ? "stayed in" : "left",
                rtd_moved ? "changed" : "did not change", rtd_alarm_seen ? "seen" : "not seen");
    return ok ? 0 : 1;
  }
  if (slave) {
    const bool ok = up && slave_ok && have_mid && last2 >= mid2 + 5;
    std::printf("%s: master status bit %s, slave comm OK %s, %%IW12 went from %u to %u in the last half\n",
                ok ? "PASS" : "FAIL", up ? "TRUE" : "FALSE", slave_ok ? "TRUE" : "FALSE", (unsigned)mid2,
                (unsigned)last2);
    return ok ? 0 : 1;
  }
  if (two) {
    const bool ok = up && up2 && have_mid && last >= mid + 5 && last2 >= mid2 + 5;
    std::printf("%s: status bits %s/%s, %%ID100 went from %u to %u and %%ID104 from %u to %u in the last half\n",
                ok ? "PASS" : "FAIL", up ? "TRUE" : "FALSE", up2 ? "TRUE" : "FALSE", (unsigned)mid, (unsigned)last,
                (unsigned)mid2, (unsigned)last2);
    return ok ? 0 : 1;
  }
  const bool ok = up && have_mid && last >= mid + 5;
  std::printf("%s: status bit %s, %%ID100 went from %u to %u in the last half of the run\n",
              ok ? "PASS" : "FAIL", up ? "TRUE" : "FALSE", (unsigned)mid, (unsigned)last);
  return ok ? 0 : 1;
}
