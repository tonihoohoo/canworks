// Unit tests of the machine model (plugin/src/canopen/sim/sim_machine.cpp) on a virtual
// clock: three CiA 402 drive models on fake object dictionaries, a fake I/O
// module, and a small pick-and-place sequence standing in for the PLC.

#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <functional>
#include <map>
#include <memory>
#include <string>
#include <vector>

#include "check.hpp"
#include "cJSON.h"
#include "sim_drive.h"
#include "sim_file.h"
#include "sim_machine.h"

using namespace canopen_sim;

namespace {

uint32_t key(uint16_t index, uint8_t sub) { return (uint32_t(index) << 8) | sub; }

class AxisIo : public DriveIo {
 public:
  std::map<uint32_t, double> od;
  std::vector<uint16_t> emcys;
  AxisIo() {
    const std::pair<uint32_t, double> init[] = {
        {key(0x603F, 0), 0},   {key(0x6040, 0), 0},       {key(0x6041, 0), 0},     {key(0x605A, 0), 2},
        {key(0x6060, 0), 0},   {key(0x6061, 0), 0},       {key(0x6062, 0), 0},     {key(0x6064, 0), 0},
        {key(0x6065, 0), 10000}, {key(0x6066, 0), 20},     {key(0x606C, 0), 0},     {key(0x6071, 0), 0},
        {key(0x6077, 0), 0},   {key(0x607A, 0), 0},       {key(0x607C, 0), 0},     {key(0x6081, 0), 100000},
        {key(0x6083, 0), 1e6}, {key(0x6084, 0), 1e6},     {key(0x6085, 0), 1e7},   {key(0x6098, 0), 21},
        {key(0x6099, 1), 50000}, {key(0x6099, 2), 5000},  {key(0x609A, 0), 1e6},   {key(0x60F4, 0), 0},
        {key(0x6502, 0), 0x20 | 0x80 | 0x200},
    };
    for (const auto& p : init) od[p.first] = p.second;
  }
  bool has(uint16_t i, uint8_t s) const override { return od.count(key(i, s)) != 0; }
  double read(uint16_t i, uint8_t s) const override {
    auto it = od.find(key(i, s));
    return it == od.end() ? 0 : it->second;
  }
  void write(uint16_t i, uint8_t s, double v) override { od[key(i, s)] = v; }
  void emcy(uint16_t code, uint8_t) override { emcys.push_back(code); }
  void emcy_reset() override {}
  double get(uint16_t i, uint8_t s = 0) const { return read(i, s); }
  void set(uint16_t i, double v) { od[key(i, 0)] = v; }
};

DriveSettings fast() {
  DriveSettings s;
  s.max_velocity = 1.5e6;      // 1500 mm/s at 1000 counts/mm
  s.max_acceleration = 2e7;    // 20 m/s²
  return s;
}

const char* kMachine = R"({
  "schema_version": 1, "name": "Test cell", "kind": "gantry_xyz", "units": "mm", "tick_ms": 2,
  "joints": {
    "x": { "node": 4, "travel": [0, 900], "counts_per_mm": 1000, "home_flag": 0, "limits": [-5, 905], "hard_stops": [-12, 912] },
    "y": { "node": 5, "travel": [0, 600], "counts_per_mm": 1000, "home_flag": 0, "hard_stops": [-12, 612] },
    "z": { "node": 6, "travel": [0, 300], "counts_per_mm": 1000, "home_flag": 0, "down": true, "hard_stops": [-12, 312],
           "load": { "hold_permille": 165, "per_kg_permille": 140, "per_m_s2_permille": 60 } } },
  "tool": { "type": "gripper", "close": { "node": 10, "object": "0x6200:1", "bit": 1 },
            "gripped": { "node": 10, "object": "0x6000:1", "bit": 4 }, "stroke_ms": 120, "open_mm": 96,
            "offset": [0, 0, 330] },
  "parts": { "box": { "size": [80, 60, 50], "mass_kg": 0.4 } },
  "conveyors": [ { "name": "infeed", "from": [-400, 480], "to": [120, 480], "height": 60, "speed_mm_s": 250, "gap_mm": 40,
                   "run": { "node": 10, "object": "0x6200:1", "bit": 0 }, "feed": { "part": "box", "every_s": [0.8, 1.2] } } ],
  "sensors": [ { "name": "part_at_pick", "at": [80, 480, 85], "size": [20, 140, 40],
                 "output": { "node": 10, "object": "0x6000:1", "bit": 3 } } ],
  "fixtures": [ { "name": "pallet", "slots": { "origin": [500, 120], "pitch": [120, 120], "count": [3, 3] }, "height": 40,
                  "place_tolerance_mm": 12,
                  "change": { "request": { "node": 10, "object": "0x6200:1", "bit": 2 },
                              "ready": { "node": 10, "object": "0x6000:1", "bit": 5 }, "time_s": 2, "move": [0, -400] } } ],
  "visual": { "anything": true }
})";

const IoBit kRun{10, ObjKey{0x6200, 1}, 0}, kClose{10, ObjKey{0x6200, 1}, 1}, kChange{10, ObjKey{0x6200, 1}, 2};
const IoBit kSensor{10, ObjKey{0x6000, 1}, 3}, kGripped{10, ObjKey{0x6000, 1}, 4}, kReady{10, ObjKey{0x6000, 1}, 5};

MachineSpec spec_from(const std::string& json) {
  MachineSpec s;
  std::vector<std::string> errors;
  bool ok = parse_machine_file(json, "machine.json", s, errors);
  for (const auto& e : errors) std::printf("  %s\n", e.c_str());
  CHECK(ok);
  return s;
}

// The drives, the I/O module and the machine on a 1 ms virtual clock.
struct Rig : MachineIo {
  AxisIo io[3];
  std::unique_ptr<DriveModel> ax[3];
  std::map<std::string, uint64_t> objects;  // "node:0xIIII:S" -> value
  std::unique_ptr<MachineModel> machine;
  double t = 0, since_machine = 0;
  unsigned tick_ms = 2;

  explicit Rig(const MachineSpec& spec, double start_mm[3] = nullptr) {
    for (int i = 0; i < 3; ++i) {
      DriveSettings s = fast();
      s.start_position = start_mm ? start_mm[i] * 1000 : 0;
      ax[i].reset(new DriveModel(io[i], s));
      ax[i]->power_on();
    }
    tick_ms = spec.tick_ms;
    machine.reset(new MachineModel(spec, *this));
  }
  int axis(unsigned node) const { return node >= 4 && node <= 6 ? static_cast<int>(node) - 4 : -1; }
  Drive drive(unsigned node) override {
    Drive d;
    int a = axis(node);
    if (a < 0) return d;
    d.present = true;
    d.actual = ax[a]->actual_position();
    d.demand = ax[a]->demand_position();
    d.velocity = ax[a]->actual_velocity();
    d.demand_velocity = ax[a]->demand_velocity();
    d.mode = ax[a]->mode();
    d.statusword = ax[a]->statusword();
    d.fault = ax[a]->state() == DriveModel::State::Fault;
    d.state = d.fault ? "fault" : "other";
    return d;
  }
  void set_drive(unsigned node, const DriveInputs& in, double load) override {
    int a = axis(node);
    if (a < 0) return;
    ax[a]->inputs = in;
    ax[a]->load_permille = load;
  }
  static std::string name(const IoBit& b) { return std::to_string(b.node) + ":" + b.object.str(); }
  bool output(const IoBit& b) override { return (objects[name(b)] >> b.bit) & 1; }
  void set_input(const IoBit& b, bool on) override {
    uint64_t& v = objects[name(b)];
    v = on ? v | (uint64_t(1) << b.bit) : v & ~(uint64_t(1) << b.bit);
  }
  void out(const IoBit& b, bool on) { set_input(b, on); }
  bool in(const IoBit& b) { return output(b); }

  void step() {
    for (auto& d : ax) d->step(0.001);
    t += 0.001;
    since_machine += 0.001;
    if (since_machine >= tick_ms / 1000.0 - 1e-9) {
      machine->Step(since_machine);
      since_machine = 0;
    }
  }
  void run(double seconds) {
    for (int i = static_cast<int>(std::lround(seconds * 1000)); i > 0; --i) step();
  }
  bool wait(const std::function<bool()>& cond, double timeout) {
    for (double end = t + timeout; t < end; step())
      if (cond()) return true;
    return cond();
  }
  void enable(int a, int mode) {
    io[a].set(0x6060, mode);
    for (unsigned c : {0x06u, 0x07u, 0x0Fu}) {
      io[a].set(0x6040, c);
      step();
    }
  }
  void enable_all() {
    for (int a = 0; a < 3; ++a) {
      io[a].set(0x607A, ax[a]->actual_position());
      enable(a, 8);
    }
  }
  bool fault(int a) const { return ax[a]->state() == DriveModel::State::Fault; }
  double pos(int a) const { return ax[a]->actual_position() / 1000.0; }
  // CSP: the target moves to `mm` on a trapezoid (`speed` mm/s, 8 m/s²), then the axis settles.
  void move(int a, double mm, double speed = 800) {
    const double acc = 8000;
    double from = io[a].get(0x607A) / 1000.0, d = std::fabs(mm - from), dir = mm > from ? 1 : -1;
    double v = 0, s = 0;
    while (s < d - 1e-9) {
      double brake = std::sqrt(2 * acc * (d - s));
      v = std::min(std::min(v + acc * 0.001, speed), brake);
      v = std::max(v, 20.0);
      s = std::min(d, s + v * 0.001);
      io[a].set(0x607A, std::round((from + dir * s) * 1000));
      step();
    }
    run(0.03);
  }
};

// The machine file's tool heights: pick on the belt, place on the pallet.
const double kPickZ = 330 - 62;   // finger tips 2 mm above the belt
const double kPlaceZ = 330 - 43;  // the held part's bottom 1 mm above the pallet

// One pick and place, as the demo program does it.
bool pick_and_place(Rig& r, double sx, double sy) {
  if (!r.wait([&] { return r.in(kSensor); }, 10)) return false;
  r.move(0, 80);
  r.move(1, 480);
  r.move(2, kPickZ);
  r.out(kClose, true);
  if (!r.wait([&] { return r.in(kGripped); }, 1)) return false;
  r.move(2, 0);
  r.move(0, sx);
  r.move(1, sy);
  r.move(2, kPlaceZ);
  r.out(kClose, false);
  r.run(0.15);
  r.move(2, 0);
  return true;
}

double slot_x(int i) { return 500 + 120 * (i % 3); }
double slot_y(int i) { return 120 + 120 * (i / 3); }

}  // namespace

TEST(machine_file_valid) {
  MachineSpec s = spec_from(kMachine);
  CHECK(s.joints.size() == 3 && s.joints[0].name == "x" && s.joints[2].name == "z" && s.joints[2].down);
  CHECK(s.tool.present && s.tool.has_gripped && s.conveyors.size() == 1 && s.fixtures[0].has_change);
  CHECK(s.inputs().size() == 3 && s.outputs().size() == 3);
}

TEST(machine_file_errors) {
  struct Case {
    std::string from, to, expect;
  } cases[] = {
      {"\"units\": \"mm\"", "\"units\": \"mm\", \"colour\": 1", "unknown key \"colour\""},
      {"\"y\": { \"node\": 5,", "\"w\": { \"node\": 5,", "joint \"y\" is missing"},
      {"\"travel\": [0, 600]", "\"travel\": [600, 0]", "joints.y.travel: must be [low, high]"},
      {"\"hard_stops\": [-12, 912]", "\"hard_stops\": [-2, 912]", "must lie outside the limit switches"},
      {"\"part\": \"box\"", "\"part\": \"crate\"", "part kind \"crate\" is not defined"},
      {"\"object\": \"0x6000:1\", \"bit\": 4", "\"object\": \"0x6000:1\", \"bit\": 3", "is bound twice"},
      {"\"from\": [-400, 480]", "\"from\": [-400, 400]", "a conveyor runs along x or y"},
      {"\"kind\": \"gantry_xyz\"", "\"kind\": \"scara\"", "must be \"gantry_xyz\""},
  };
  for (const auto& c : cases) {
    std::string json = kMachine;
    size_t at = json.find(c.from);
    CHECK(at != std::string::npos);
    json.replace(at, c.from.size(), c.to);
    MachineSpec s;
    std::vector<std::string> errors;
    CHECK(!parse_machine_file(json, "machine.json", s, errors));
    bool found = false;
    for (const auto& e : errors) found = found || e.find(c.expect) != std::string::npos;
    if (!found) {
      std::printf("  expected \"%s\", got:\n", c.expect.c_str());
      for (const auto& e : errors) std::printf("    %s\n", e.c_str());
    }
    CHECK(found);
  }
}

TEST(machine_sim_file_section) {
  const char* sim = R"({ "schema_version": 2, "networks": { "motion": { "machine": "machine.json",
    "scenarios": { "t": { "test": true, "steps": [
      { "machine": "z", "fault": { "jam": true } },
      { "machine": "z", "clear": "jam" },
      { "expect": { "machine": "placed", "ge": 9 }, "within_ms": 60000 } ] } } } } })";
  SimFile f, sec;
  std::vector<std::string> errors;
  CHECK(parse_sim_file(sim, "/p/canworks/simulation.json", f, errors));
  for (const auto& e : errors) std::printf("  %s\n", e.c_str());
  CHECK(sim_file_section(f, "motion", sec));
  CHECK(sec.machine == "machine.json" && sec.machine_path == "/p/canworks/machine.json");
  CHECK(sec.scenarios.size() == 1 && sec.scenarios[0].steps.size() == 3);
  CHECK(sec.scenarios[0].steps[0].machine == "z" && sec.scenarios[0].steps[0].machine_fault == "{\"jam\":true}");
  CHECK(sec.scenarios[0].steps[2].cond.machine == "placed" && sec.scenarios[0].steps[2].cond.op == "ge");
  const char* bad[] = {
      R"({ "schema_version": 2, "networks": { "m": { "scenarios": { "t": { "steps": [ { "machine": "z", "fault": { "jam": 1 } } ] } } } } })",
      R"({ "schema_version": 2, "networks": { "m": { "scenarios": { "t": { "steps": [ { "machine": "z", "set": { "0x6000:1": 1 } } ] } } } } })",
      R"({ "schema_version": 2, "networks": { "m": { "scenarios": { "t": { "steps": [ { "expect": { "machine": "placed", "node": 4, "eq": 1 } } ] } } } } })",
      R"({ "schema_version": 2, "networks": { "m": { "machine": 3 } } })",
  };
  for (const char* b : bad) {
    SimFile g;
    std::vector<std::string> e2;
    CHECK(!parse_sim_file(b, "s.json", g, e2));
  }
}

TEST(machine_home_flag) {
  double start[3] = {60, 0, 0};
  Rig r(spec_from(kMachine), start);
  r.run(0.01);
  CHECK(!r.ax[0]->inputs.home_switch);
  r.enable(0, 6);  // homing, method 21: the home switch in the negative direction
  r.io[0].set(0x6040, 0x1F);
  CHECK(r.wait([&] { return (r.ax[0]->statusword() & 0x1000) != 0; }, 5));
  // Homed where the switch went off again, with the offset 0x607C (0) as the position.
  CHECK(std::fabs(r.pos(0)) < 0.01);
  r.run(0.01);
  CHECK(std::fabs(r.machine->joint_position(0)) < 1);
}

TEST(machine_hard_stop) {
  Rig r(spec_from(kMachine));
  r.enable_all();
  r.move(1, 600);
  CHECK(!r.fault(1));
  r.move(1, 650, 200);
  r.run(0.2);
  CHECK(r.pos(1) > 611 && r.pos(1) < 613.5);
  CHECK(r.fault(1));
  CHECK(!r.io[1].emcys.empty() && r.io[1].emcys.back() == 0x8611);
}

TEST(machine_limit_switch) {
  Rig r(spec_from(kMachine));
  r.enable_all();
  r.move(0, 904);
  CHECK(!r.ax[0]->inputs.positive_limit);
  r.move(0, 906);
  r.run(0.01);
  CHECK(r.ax[0]->inputs.positive_limit && !r.ax[0]->inputs.negative_limit);
}

TEST(machine_gripper) {
  Rig r(spec_from(kMachine));
  r.enable_all();
  // Close on nothing: fully closed, not gripped.
  r.out(kClose, true);
  r.run(0.2);
  CHECK(r.machine->opening() < 0.01 && !r.in(kGripped));
  r.out(kClose, false);
  r.run(0.2);
  CHECK(std::fabs(r.machine->opening() - 96) < 0.01);
  // A part at the pick position.
  r.out(kRun, true);
  CHECK(r.wait([&] { return r.in(kSensor); }, 10));
  r.run(0.5);  // on to the end stop
  r.out(kRun, false);
  r.move(0, 80);
  r.move(1, 480);
  r.move(2, kPickZ);
  CHECK(!r.fault(2));
  r.out(kClose, true);
  r.run(0.1);  // less than the stroke time
  CHECK(!r.in(kGripped));
  r.run(0.03);
  CHECK(r.in(kGripped) && r.machine->counters().picked == 1);
  r.move(2, 100);
  const auto& parts = r.machine->parts();
  bool held = false;
  for (const auto& p : parts) held = held || (p.state == MachineModel::PartState::Held && p.pos[2] > 150);
  CHECK(held);
  CHECK(!r.in(kSensor));
  // Opening drops it on the belt below, back on the conveyor.
  r.out(kClose, false);
  r.run(0.5);
  CHECK(!r.in(kGripped) && r.machine->counters().dropped == 0);
}

TEST(machine_load_torque) {
  Rig r(spec_from(kMachine));
  r.enable_all();
  r.run(0.1);
  CHECK(std::lround(r.io[2].get(0x6077)) == 165);
  CHECK(std::lround(r.io[0].get(0x6077)) == 0);
  r.out(kRun, true);
  CHECK(r.wait([&] { return r.in(kSensor); }, 10));
  r.move(0, 80);
  r.move(1, 480);
  r.move(2, kPickZ);
  r.out(kClose, true);
  CHECK(r.wait([&] { return r.in(kGripped); }, 1));
  r.move(2, 0);
  r.run(0.3);
  CHECK(std::lround(r.io[2].get(0x6077)) == 221);
  // Disabled: no torque.
  r.io[2].set(0x6040, 0x06);
  r.run(0.01);
  CHECK(std::lround(r.io[2].get(0x6077)) == 0);
}

TEST(machine_conveyor_queue) {
  Rig r(spec_from(kMachine));
  r.out(kRun, true);
  r.run(1.5);
  CHECK(r.machine->counters().fed == 1);
  // Stop with a part halfway: it stays, and moves on when the belt runs again.
  r.out(kRun, false);
  double x = r.machine->parts()[0].pos[0];
  r.run(1);
  CHECK(r.machine->parts()[0].pos[0] == x);
  r.out(kRun, true);
  r.run(10);
  // Parts queue against the end stop and each other with the gap.
  const auto& p = r.machine->parts();
  CHECK(p.size() >= 4);
  CHECK(std::fabs(p[0].pos[0] - 80) < 0.01);
  CHECK(std::fabs(p[1].pos[0] - (80 - 80 - 40)) < 0.01);
  CHECK(r.in(kSensor));
}

TEST(machine_sensor_stuck) {
  Rig r(spec_from(kMachine));
  r.out(kRun, true);
  cJSON* f = cJSON_Parse(R"({"stuck": "off"})");
  std::string err;
  CHECK(r.machine->Fault("part_at_pick", f, err));
  cJSON_Delete(f);
  r.run(4);
  CHECK(!r.in(kSensor));
  double v = -1;
  CHECK(r.machine->Value("part_at_pick", v) && v == 0);
  cJSON* fs = r.machine->FaultsJson();
  CHECK(cJSON_GetArraySize(fs) == 1);
  cJSON_Delete(fs);
  CHECK(r.machine->Clear("part_at_pick", "stuck", err));
  r.run(0.01);
  CHECK(r.in(kSensor));
  // Wrong element for a fault.
  f = cJSON_Parse(R"({"jam": true})");
  CHECK(!r.machine->Fault("part_at_pick", f, err) && err.find("a joint") != std::string::npos);
  CHECK(!r.machine->Fault("nothing", f, err) && err.find("no element") != std::string::npos);
  cJSON_Delete(f);
}

TEST(machine_feeder_faults) {
  Rig r(spec_from(kMachine));
  r.out(kRun, true);
  std::string err;
  cJSON* f = cJSON_Parse(R"({"feeder": "empty"})");
  CHECK(r.machine->Fault("infeed", f, err));
  cJSON_Delete(f);
  r.run(3);
  CHECK(r.machine->counters().fed == 0);
  CHECK(r.machine->Clear("infeed", "all", err));
  f = cJSON_Parse(R"({"misaligned_mm": 15})");
  CHECK(r.machine->Fault("infeed", f, err));
  cJSON_Delete(f);
  r.run(5);
  CHECK(std::fabs(r.machine->parts()[0].pos[1] - 495) < 0.01);
  CHECK(std::fabs(r.machine->parts()[1].pos[1] - 480) < 0.01);
}

TEST(machine_contact_blocks) {
  Rig r(spec_from(kMachine));
  r.enable_all();
  r.out(kRun, true);
  CHECK(pick_and_place(r, slot_x(0), slot_y(0)));
  CHECK(r.machine->counters().placed == 1);
  // Now lower the open gripper straight onto the placed part, offset so a finger lands on it.
  r.move(0, slot_x(0) + 40);
  r.move(1, slot_y(0));
  r.move(2, kPlaceZ, 200);
  r.run(0.2);
  CHECK(r.fault(2));
  CHECK(!r.io[2].emcys.empty() && r.io[2].emcys.back() == 0x8611);
  // Stopped at the part's top: finger tips at 40 + 50.
  CHECK(std::fabs((330 - r.pos(2)) - 90) < 1.5);
}

TEST(machine_slip_drops) {
  Rig r(spec_from(kMachine));
  r.enable_all();
  r.out(kRun, true);
  CHECK(r.wait([&] { return r.in(kSensor); }, 10));
  r.move(0, 80);
  r.move(1, 480);
  r.move(2, kPickZ);
  r.out(kClose, true);
  CHECK(r.wait([&] { return r.in(kGripped); }, 1));
  r.move(2, 0);
  r.move(1, 300);
  cJSON* f = cJSON_Parse(R"({"slip": true})");
  std::string err;
  CHECK(r.machine->Fault("tool", f, err));
  cJSON_Delete(f);
  r.run(0.5);
  CHECK(!r.in(kGripped) && r.machine->counters().dropped == 1);
}

namespace {

struct Outcome {
  MachineModel::Counters c;
  std::vector<double> xs;
  bool ok = true;
};

// A full 3 x 3 pallet, then a pallet change.
Outcome full_pallet() {
  Outcome o;
  Rig r(spec_from(kMachine));
  r.enable_all();
  r.out(kRun, true);
  for (int i = 0; i < 9 && o.ok; ++i) {
    o.ok = pick_and_place(r, slot_x(i), slot_y(i));
    const auto& c = r.machine->counters();
    if (!o.ok || c.placed != static_cast<unsigned>(i + 1))
      std::printf("  part %d: t %.1f s, fed %u picked %u placed %u misplaced %u dropped %u, faults %d%d%d\n", i, r.t, c.fed,
                  c.picked, c.placed, c.misplaced, c.dropped, r.fault(0), r.fault(1), r.fault(2));
  }
  double filled = 0;
  r.machine->Value("pallet", filled);
  o.ok = o.ok && filled == 9 && r.in(kReady);
  for (int a = 0; a < 3; ++a) o.ok = o.ok && !r.fault(a);
  r.out(kChange, true);
  r.run(0.1);
  o.ok = o.ok && !r.in(kReady);
  o.ok = o.ok && r.wait([&] { return r.in(kReady); }, 3);
  r.out(kChange, false);
  r.machine->Value("pallet", filled);
  o.ok = o.ok && filled == 0;
  o.ok = o.ok && r.t < 60;
  std::printf("  9 parts and a pallet change in %.1f s of simulated time\n", r.t);
  o.c = r.machine->counters();
  for (const auto& p : r.machine->parts()) o.xs.push_back(p.pos[0] + p.pos[1] * 1e4);
  return o;
}

}  // namespace

TEST(machine_full_pallet) {
  Outcome o = full_pallet();
  CHECK(o.ok);
  CHECK(o.c.placed == 9 && o.c.picked == 9 && o.c.dropped == 0 && o.c.misplaced == 0 && o.c.pallets == 1);
}

TEST(machine_deterministic) {
  Outcome a = full_pallet(), b = full_pallet();
  CHECK(a.ok && b.ok);
  CHECK(a.c.fed == b.c.fed && a.c.placed == b.c.placed && a.xs == b.xs);
}

TEST(machine_snapshot_size_and_step_time) {
  // 50 parts on a long belt fed every 10 ms.
  std::string json = kMachine;
  auto rep = [&](const std::string& a, const std::string& b) { json.replace(json.find(a), a.size(), b); };
  rep("\"from\": [-400, 480]", "\"from\": [-6000, 480]");
  rep("\"every_s\": [0.8, 1.2]", "\"every_s\": [0.01, 0.01]");
  rep("\"speed_mm_s\": 250", "\"speed_mm_s\": 9000");
  Rig r(spec_from(json));
  r.out(kRun, true);
  r.run(3);
  CHECK(r.machine->parts().size() == kMaxMachineParts);
  auto t0 = std::chrono::steady_clock::now();
  const int n = 2000;
  for (int i = 0; i < n; ++i) r.machine->Step(0.002);
  double us = std::chrono::duration<double, std::micro>(std::chrono::steady_clock::now() - t0).count() / n;
  std::printf("  machine step with %zu parts: %.1f us\n", r.machine->parts().size(), us);
  CHECK(us < 100);  // 5 % of a 2 ms step
  cJSON* s = r.machine->Snapshot();
  char* text = cJSON_PrintUnformatted(s);
  size_t size = std::strlen(text);
  std::printf("  sim_machine answer with 50 parts: %zu bytes\n", size);
  CHECK(size < 16 * 1024);
  cJSON_free(text);
  cJSON_Delete(s);
}

