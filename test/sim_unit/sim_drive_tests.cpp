// Unit tests of the CiA 402 drive model on a fake object dictionary (no CAN).

#include <cmath>
#include <cstdint>
#include <map>
#include <string>
#include <vector>

#include "check.hpp"
#include "cJSON.h"
#include "sim_drive.h"

using namespace canopen_sim;

namespace {

uint32_t key(uint16_t index, uint8_t sub) { return (uint32_t(index) << 8) | sub; }

// The objects of a typical servo drive EDS.
class FakeIo : public DriveIo {
 public:
  std::map<uint32_t, double> od;
  std::vector<std::pair<uint16_t, uint8_t>> emcys;
  int resets = 0;

  FakeIo() {
    const std::pair<uint32_t, double> init[] = {
        {key(0x603F, 0), 0},      {key(0x6040, 0), 0},       {key(0x6041, 0), 0},      {key(0x605A, 0), 2},
        {key(0x6060, 0), 0},      {key(0x6061, 0), 0},       {key(0x6062, 0), 0},      {key(0x6064, 0), 0},
        {key(0x6065, 0), 4294967295.0}, {key(0x6066, 0), 0}, {key(0x6067, 0), 10},     {key(0x606B, 0), 0},
        {key(0x606C, 0), 0},      {key(0x606D, 0), 20},      {key(0x606F, 0), 10},     {key(0x607A, 0), 0},
        {key(0x607C, 0), 0},      {key(0x607D, 1), 0},       {key(0x607D, 2), 0},      {key(0x6081, 0), 10000},
        {key(0x6083, 0), 100000}, {key(0x6084, 0), 100000},  {key(0x6085, 0), 500000}, {key(0x6098, 0), 0},
        {key(0x6099, 1), 2000},   {key(0x6099, 2), 500},     {key(0x609A, 0), 100000}, {key(0x60F4, 0), 0},
        {key(0x60FF, 0), 0},
        // Profile position, profile velocity, homing, CSP; not CSV.
        {key(0x6502, 0), 0x01 | 0x04 | 0x20 | 0x80},
    };
    for (const auto& p : init) od[p.first] = p.second;
  }

  bool has(uint16_t index, uint8_t sub) const override { return od.count(key(index, sub)) != 0; }
  double read(uint16_t index, uint8_t sub) const override {
    auto it = od.find(key(index, sub));
    return it == od.end() ? 0 : it->second;
  }
  void write(uint16_t index, uint8_t sub, double value) override { od[key(index, sub)] = value; }
  void emcy(uint16_t code, uint8_t reg) override { emcys.emplace_back(code, reg); }
  void emcy_reset() override { ++resets; }

  double get(uint16_t index, uint8_t sub = 0) const { return read(index, sub); }
  void set(uint16_t index, double v) { od[key(index, 0)] = v; }
  void set(uint16_t index, uint8_t sub, double v) { od[key(index, sub)] = v; }
  unsigned sw() const { return static_cast<unsigned>(get(0x6041)); }
};

void run(DriveModel& m, double seconds) {
  int n = static_cast<int>(std::lround(seconds / 0.001));
  for (int i = 0; i < n; ++i) m.step(0.001);
}

void cw(FakeIo& io, DriveModel& m, unsigned value) {
  io.set(0x6040, value);
  m.step(0.001);
}

bool is_enabled(const FakeIo& io) { return (io.sw() & 0x6F) == 0x27; }
bool is_fault(const FakeIo& io) { return (io.sw() & 0x4F) == 0x08; }
bool is_disabled(const FakeIo& io) { return (io.sw() & 0x4F) == 0x40; }

void enable(FakeIo& io, DriveModel& m, int mode) {
  io.set(0x6060, mode);
  cw(io, m, 0x06);
  cw(io, m, 0x07);
  cw(io, m, 0x0F);
}

// A profile position set-point: target, new set-point rising, then falling.
void pp_move(FakeIo& io, DriveModel& m, double target, bool relative = false) {
  io.set(0x607A, target);
  unsigned base = 0x0F | (relative ? 0x40 : 0);
  cw(io, m, base | 0x10);
  cw(io, m, base);
}

}  // namespace

TEST(drive_enable_sequence) {
  FakeIo io;
  DriveModel m(io, DriveSettings());
  m.power_on();
  CHECK(is_disabled(io));
  CHECK(m.state() == DriveModel::State::SwitchOnDisabled);
  cw(io, m, 0x06);
  CHECK((io.sw() & 0x6F) == 0x21);
  cw(io, m, 0x07);
  CHECK((io.sw() & 0x6F) == 0x23);
  cw(io, m, 0x0F);
  CHECK(is_enabled(io));
  CHECK(m.state() == DriveModel::State::OperationEnabled);
  // Quick stop, then back to switch on disabled once stopped (option 2).
  cw(io, m, 0x0B);
  run(m, 0.01);
  CHECK(is_disabled(io));
  // Disable voltage from operation enabled.
  enable(io, m, 1);
  CHECK(is_enabled(io));
  cw(io, m, 0x00);
  CHECK(is_disabled(io));
  CHECK(m.missing().empty());
  CHECK(!m.outputs().empty());
}

TEST(drive_pp_absolute_move) {
  FakeIo io;
  DriveModel m(io, DriveSettings());
  m.power_on();
  enable(io, m, 1);
  CHECK(io.get(0x6061) == 1);
  io.set(0x607A, 10000);
  cw(io, m, 0x1F);
  CHECK(io.sw() & 0x1000);    // set-point acknowledged
  CHECK(!(io.sw() & 0x0400)); // not reached
  cw(io, m, 0x0F);
  CHECK(!(io.sw() & 0x1000)); // handshake done
  double vmax = 0;
  for (int i = 0; i < 2500; ++i) {
    m.step(0.001);
    vmax = std::max(vmax, std::fabs(io.get(0x606C)));
  }
  CHECK(io.get(0x6064) == 10000);
  CHECK(io.sw() & 0x0400);
  CHECK_MSG(vmax <= 10001, std::to_string(vmax));
  CHECK(vmax > 9000);
  CHECK(io.get(0x6062) == 10000);
}

TEST(drive_pp_relative_move) {
  FakeIo io;
  DriveModel m(io, DriveSettings());
  m.power_on();
  enable(io, m, 1);
  pp_move(io, m, 1000);
  run(m, 1.0);
  CHECK(io.get(0x6064) == 1000);
  pp_move(io, m, 500, true);
  CHECK(!(io.sw() & 0x0400));
  run(m, 1.0);
  CHECK(io.get(0x6064) == 1500);
  CHECK(io.sw() & 0x0400);
}

TEST(drive_pp_change_set_immediately) {
  FakeIo io;
  DriveModel m(io, DriveSettings());
  m.power_on();
  enable(io, m, 1);
  pp_move(io, m, 10000);
  run(m, 0.1);
  // A new set-point with "change set immediately" replaces the running move.
  io.set(0x607A, 2000);
  cw(io, m, 0x3F);  // change immediately
  cw(io, m, 0x2F);
  run(m, 2.0);
  CHECK(io.get(0x6064) == 2000);
  CHECK(io.sw() & 0x0400);
}

TEST(drive_pv_ramp) {
  FakeIo io;
  DriveModel m(io, DriveSettings());
  m.power_on();
  enable(io, m, 3);
  CHECK(io.get(0x6061) == 3);
  io.set(0x60FF, 20000);
  run(m, 0.1);
  double v = io.get(0x606C);
  CHECK_MSG(v > 8000 && v < 10500, std::to_string(v));  // 100000 counts/s² for 0.1 s
  CHECK(!(io.sw() & 0x0400));
  run(m, 0.3);
  CHECK(std::fabs(io.get(0x606C) - 20000) <= 1);
  CHECK(io.sw() & 0x0400);
  CHECK(io.get(0x6064) > 3000);
  io.set(0x60FF, 0);
  run(m, 0.4);
  CHECK(io.get(0x606C) == 0);
  CHECK(io.sw() & 0x1000);  // speed = 0
}

TEST(drive_homing_current_position) {
  FakeIo io;
  DriveSettings s;
  s.start_position = 777;
  DriveModel m(io, s);
  m.power_on();
  CHECK(io.get(0x6064) == 777);
  io.set(0x607C, 1234);
  io.set(0x6098, 35);
  enable(io, m, 6);
  CHECK(io.get(0x6061) == 6);
  cw(io, m, 0x1F);
  run(m, 0.01);
  CHECK(io.sw() & 0x1000);    // homing attained
  CHECK(io.sw() & 0x0400);    // target reached
  CHECK(!(io.sw() & 0x2000)); // no error
  CHECK(io.get(0x6064) == 1234);
}

TEST(drive_homing_unsupported_method) {
  FakeIo io;
  DriveModel m(io, DriveSettings());
  m.power_on();
  io.set(0x6098, 1);
  enable(io, m, 6);
  cw(io, m, 0x1F);
  run(m, 0.01);
  CHECK(io.sw() & 0x2000);
  CHECK(!(io.sw() & 0x1000));
}

TEST(drive_homing_negative_limit_switch) {
  FakeIo io;
  DriveModel m(io, DriveSettings());
  m.power_on();
  io.set(0x607C, 100);
  io.set(0x6098, 17);
  enable(io, m, 6);
  cw(io, m, 0x1F);
  run(m, 0.2);
  CHECK(io.get(0x606C) < -1000);
  CHECK(!(io.sw() & 0x0400));
  m.inputs.negative_limit = true;
  run(m, 0.1);
  CHECK(io.sw() & 0x0800);
  CHECK(io.get(0x606C) > 0);  // backs off the switch
  m.inputs.negative_limit = false;
  run(m, 0.01);
  CHECK(io.sw() & 0x1000);
  CHECK(io.sw() & 0x0400);
  CHECK(io.get(0x6064) == 100);
}

TEST(drive_following_error_faults) {
  FakeIo io;
  DriveModel m(io, DriveSettings());
  m.power_on();
  io.set(0x6065, 1000);
  io.set(0x6066, 10);
  enable(io, m, 1);
  m.inputs.blocked = true;
  pp_move(io, m, 10000);
  run(m, 1.0);
  CHECK(is_fault(io));
  CHECK(m.state() == DriveModel::State::Fault);
  CHECK(io.emcys.size() == 1);
  if (!io.emcys.empty()) CHECK(io.emcys[0].first == 0x8611);
  CHECK(io.get(0x603F) == 0x8611);
  CHECK(io.get(0x6064) == 0);
  run(m, 0.5);
  CHECK(io.emcys.size() == 1);

  // Fault reset on the rising edge of bit 7.
  m.inputs.blocked = false;
  cw(io, m, 0x80);
  CHECK(is_disabled(io));
  CHECK(io.get(0x603F) == 0);
  CHECK(io.resets == 1);
  cw(io, m, 0x00);
  enable(io, m, 1);
  CHECK(is_enabled(io));
  pp_move(io, m, 3000);
  run(m, 1.0);
  CHECK(io.get(0x6064) == 3000);
  CHECK(io.emcys.size() == 1);
}

TEST(drive_software_limit) {
  FakeIo io;
  DriveModel m(io, DriveSettings());
  m.power_on();
  io.set(0x607D, 1, -5000);
  io.set(0x607D, 2, 5000);
  enable(io, m, 1);
  pp_move(io, m, 10000);
  run(m, 2.0);
  CHECK(io.get(0x6064) == 5000);
  CHECK(io.sw() & 0x0080);  // warning
  CHECK(io.sw() & 0x0800);  // internal limit active
  pp_move(io, m, 0);
  run(m, 1.0);
  CHECK(io.get(0x6064) == 0);
  CHECK(!(io.sw() & 0x0080));

  // Profile velocity stops at the limit too.
  io.set(0x6060, 3);
  io.set(0x60FF, -10000);
  run(m, 2.0);
  CHECK_MSG(io.get(0x6064) >= -5000 && io.get(0x6064) < -4900, std::to_string(io.get(0x6064)));
  CHECK(std::fabs(io.get(0x606C)) <= 1);
  CHECK(io.sw() & 0x0080);
}

TEST(drive_limit_switch_stops_motion) {
  FakeIo io;
  DriveModel m(io, DriveSettings());
  m.power_on();
  enable(io, m, 3);
  io.set(0x60FF, 5000);
  run(m, 0.2);
  CHECK(io.get(0x606C) > 4000);
  m.inputs.positive_limit = true;
  run(m, 0.05);
  CHECK(io.get(0x606C) == 0);
  CHECK(io.sw() & 0x0800);
  double p = io.get(0x6064);
  run(m, 0.1);
  CHECK(io.get(0x6064) == p);
  io.set(0x60FF, -5000);
  run(m, 0.2);
  CHECK(io.get(0x606C) < -4000);
}

TEST(drive_mode_not_listed) {
  FakeIo io;
  DriveModel m(io, DriveSettings());
  m.power_on();
  io.set(0x6060, 1);
  m.step(0.001);
  CHECK(io.get(0x6061) == 1);
  io.set(0x6060, 9);  // the model knows CSV, but 0x6502 does not list it
  m.step(0.001);
  CHECK(io.get(0x6061) == 1);
  io.set(0x6060, 2);  // velocity mode: not in the model
  m.step(0.001);
  CHECK(io.get(0x6061) == 1);
  io.set(0x6060, 3);
  m.step(0.001);
  CHECK(io.get(0x6061) == 3);
  // Without 0x6502 every mode of the model is accepted.
  io.od.erase(key(0x6502, 0));
  io.set(0x6060, 9);
  m.step(0.001);
  CHECK(io.get(0x6061) == 9);
}

TEST(drive_csp_sync) {
  FakeIo io;
  DriveSettings ds;
  ds.sync_watchdog = false;  // the gaps between SYNCs below are longer than 30 ms
  DriveModel m(io, ds);
  m.power_on();
  enable(io, m, 8);
  CHECK(io.get(0x6061) == 8);
  CHECK(!m.has_sync_seen());
  io.set(0x607A, 500);
  run(m, 0.1);
  CHECK(io.get(0x6064) == 500);  // no SYNC yet: follows every tick
  m.sync();
  CHECK(m.has_sync_seen());
  io.set(0x607A, 800);
  run(m, 0.1);
  CHECK(io.get(0x6064) == 500);  // waits for the next SYNC
  m.sync();
  run(m, 0.1);
  CHECK(io.get(0x6064) == 800);
  CHECK(io.sw() & 0x1000);
}

TEST(drive_parse_settings) {
  DriveSettings s;
  std::string err;
  cJSON* j = cJSON_Parse("{\"max_velocity\": 50000, \"max_acceleration\": 200000, \"lag_ms\": 2, \"start_position\": -10}");
  CHECK(parse_drive_settings(j, s, err));
  CHECK(s.max_velocity == 50000 && s.max_acceleration == 200000 && s.lag_ms == 2 && s.start_position == -10);
  cJSON_Delete(j);
  j = cJSON_Parse("{\"max_velocity\": 1, \"x\": 1}");
  CHECK(!parse_drive_settings(j, s, err));
  CHECK_MSG(err == "drive: unknown key \"x\"", err);
  cJSON_Delete(j);
  j = cJSON_Parse("{\"lag_ms\": \"fast\"}");
  CHECK(!parse_drive_settings(j, s, err));
  cJSON_Delete(j);
  j = cJSON_Parse("{\"max_velocity\": 0}");
  CHECK(!parse_drive_settings(j, s, err));
  cJSON_Delete(j);
  CHECK(parse_drive_settings(nullptr, s, err));
  CHECK(s.max_velocity == 100000 && s.lag_ms == 5);
  CHECK(s.torque_accel == 10000 && s.sync_watchdog);
  j = cJSON_Parse("{\"torque_accel\": 500, \"sync_watchdog\": false}");
  CHECK(parse_drive_settings(j, s, err));
  CHECK(s.torque_accel == 500 && !s.sync_watchdog);
  cJSON_Delete(j);
  j = cJSON_Parse("{\"sync_watchdog\": 0}");
  CHECK(!parse_drive_settings(j, s, err));
  CHECK_MSG(err == "drive: \"sync_watchdog\" must be true or false", err);
  cJSON_Delete(j);
}

namespace {

// A drive with the cyclic modes and a 10 ms interpolation time period.
void cyclic_io(FakeIo& io) {
  io.set(0x6502, 0x01 | 0x04 | 0x20 | 0x80 | 0x100 | 0x200);
  io.set(0x6071, 0);
  io.set(0x6077, 0);
  io.set(0x60C2, 1, 10);
  io.set(0x60C2, 2, -3);
}

// `seconds` of 1 ms ticks with a SYNC every `period` seconds.
void run_synced(DriveModel& m, double seconds, double period = 0.01) {
  int n = static_cast<int>(std::lround(seconds / 0.001));
  int every = static_cast<int>(std::lround(period / 0.001));
  for (int i = 0; i < n; ++i) {
    if (i % every == 0) m.sync();
    m.step(0.001);
  }
}

}  // namespace

TEST(drive_cst_torque_accelerates) {
  FakeIo io;
  cyclic_io(io);
  DriveSettings ds;
  ds.lag_ms = 0;
  DriveModel m(io, ds);
  m.power_on();
  enable(io, m, 10);
  CHECK(io.get(0x6061) == 10);
  CHECK(is_enabled(io) && (io.sw() & 0x1000));
  io.set(0x6071, 100);  // 100 per mille x 10000 = 1e6 counts/s²
  run_synced(m, 0.05);
  double v = io.get(0x606C);
  CHECK_MSG(std::fabs(v - 50000) < 2000, std::to_string(v));
  CHECK(io.get(0x6077) == 100);
  run_synced(m, 0.2);
  CHECK(io.get(0x606C) == 100000);  // held at the maximum velocity
  io.set(0x6071, -100);
  run_synced(m, 0.1);
  CHECK(io.get(0x606C) == 0);
  CHECK(is_enabled(io) && io.emcys.empty());
}

TEST(drive_cst_not_listed) {
  FakeIo io;  // 0x6502 without mode 10
  DriveModel m(io, DriveSettings());
  m.power_on();
  enable(io, m, 10);
  CHECK(io.get(0x6061) == 0);
}

TEST(drive_sync_watchdog) {
  FakeIo io;
  cyclic_io(io);
  DriveModel m(io, DriveSettings());
  m.power_on();
  enable(io, m, 8);
  // Without any SYNC in the mode the watchdog is not armed.
  run(m, 0.1);
  CHECK(is_enabled(io));
  run_synced(m, 0.1);
  CHECK(is_enabled(io));
  // SYNC stops (the last one came 9 ms ago, counted from the tick after
  // it): fault three periods (30 ms) after it.
  run(m, 0.018);
  CHECK(is_enabled(io));
  run(m, 0.003);
  CHECK(!is_enabled(io));
  run(m, 0.1);
  CHECK(is_fault(io));
  CHECK(io.emcys.size() == 1 && io.emcys[0].first == 0x8700);
  CHECK(io.get(0x603F) == 0x8700);
  // Fault reset and enable again; SYNC back, no new fault.
  cw(io, m, 0x80);
  enable(io, m, 8);
  run_synced(m, 0.2);
  CHECK(is_enabled(io) && io.emcys.size() == 1);
  // A 2.5 ms period: 7.5 ms.
  io.set(0x60C2, 1, 25);
  io.set(0x60C2, 2, -4);
  run_synced(m, 0.05, 0.0025);  // SYNC every 3rd 1 ms tick, the last 1 ms ago
  run(m, 0.006);
  CHECK(is_enabled(io));
  run(m, 0.001);
  CHECK(is_fault(io) || !is_enabled(io));
}

TEST(drive_sync_watchdog_off) {
  FakeIo io;
  cyclic_io(io);
  DriveSettings ds;
  ds.sync_watchdog = false;
  DriveModel m(io, ds);
  m.power_on();
  enable(io, m, 9);
  run_synced(m, 0.1);
  run(m, 0.5);
  CHECK(is_enabled(io) && io.emcys.empty());
}

TEST(drive_csp_oversized_steps) {
  FakeIo io;
  cyclic_io(io);
  DriveModel m(io, DriveSettings());  // 100000 counts/s: 1000 counts per 10 ms
  m.power_on();
  enable(io, m, 8);
  for (int i = 1; i <= 20; ++i) {
    io.set(0x607A, i * 900);
    run_synced(m, 0.01);
  }
  CHECK(m.oversized_steps() == 0);
  io.set(0x607A, 18000 + 5000);
  run_synced(m, 0.01);
  CHECK(m.oversized_steps() == 1);
}
