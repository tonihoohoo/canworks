// sim_machine.h - the machine model of a simulated network (docs/machine.md).
//
// A machine file describes a made-up machine around the simulated devices:
// joints driven by CiA 402 drive models, a gripper, belt conveyors with
// feeders, presence sensors and fixtures with slots. The model reads the
// drives' actual positions and the master's output bits, and writes the
// drives' inputs (home switch, limit switches, blocked), their load and the
// input bits the sensors and the gripper report. It is kinematic: joints
// follow their drives, parts move through a small state machine (on a belt,
// held, falling, placed, on the table), contacts are axis-aligned boxes, and
// only gravity acts on a falling part. It is deterministic for a given input
// sequence, so tests can step it on a virtual clock (MachineModel::Step).
//
// Coordinates are millimetres: x and y on the table, height above the table
// top. Every public method runs on the simulator's loop thread.

#ifndef CANOPEN_SIM_MACHINE_H
#define CANOPEN_SIM_MACHINE_H

#include <cstdint>
#include <map>
#include <random>
#include <string>
#include <vector>

#include "sim_drive.h"
#include "sim_file.h"

typedef struct cJSON cJSON;

namespace canopen_sim {

constexpr unsigned kMachineSchemaVersion = 1;
constexpr unsigned kDefaultMachineTickMs = 2;
constexpr size_t kMaxMachineParts = 50;

// One bit of an object of a node: an output the master writes, or an input
// the machine sets.
struct IoBit {
  unsigned node = 0;
  ObjKey object;
  unsigned bit = 0;
  std::string str() const;  // "node 10 0x6000:1 bit 3"
};

struct MachineJoint {
  std::string name;  // x, y, z
  unsigned node = 0;
  double travel[2] = {0, 0};
  double counts_per_mm = 1000;
  double offset_mm = 0;  // joint position at drive position 0
  int direction = 1;     // -1: drive counts run against the joint
  bool down = false;     // z: a positive joint position lowers the tool
  bool has_home = false;
  double home_flag = 0;  // home switch on at and below this position
  bool has_limits = false;
  double limits[2] = {0, 0};  // limit switches on at and beyond these
  bool has_stops = false;
  double hard_stops[2] = {0, 0};  // the joint cannot pass these
  double hold_permille = 0, per_kg_permille = 0, per_m_s2_permille = 0;
};

struct MachinePartKind {
  std::string name;
  double size[3] = {80, 60, 50};
  double mass_kg = 0;
};

struct MachineTool {
  bool present = false;
  IoBit close;
  bool has_gripped = false;
  IoBit gripped;
  double stroke_ms = 120;
  double open_mm = 96, closed_mm = 0;
  char axis = 'x';                // the fingers close along x or y
  double offset[3] = {0, 0, 300};  // tool point at joint position 0: x, y, height
  double pick_tolerance_mm = 6;
  double finger[3] = {12, 30, 60};  // pad thickness (along the axis), width, height
};

struct MachineConveyor {
  std::string name;
  double from[2] = {0, 0}, to[2] = {0, 0};
  double width = 120, height = 60;
  double speed_mm_s = 100;
  double gap_mm = 10;
  IoBit run;
  bool has_feed = false;
  std::string feed_part;
  double every_s[2] = {3, 3};
};

struct MachineSensor {
  std::string name;
  double at[3] = {0, 0, 0};  // centre of the detection box
  double size[3] = {10, 10, 10};
  bool detects_tool = false;  // else parts
  IoBit output;
};

struct MachineFixture {
  std::string name;
  double origin[2] = {0, 0};  // first slot's centre
  double pitch[2] = {100, 100};
  unsigned count[2] = {1, 1};
  double height = 40;  // pallet top
  double margin = 30;  // pallet edge beyond the outer slots' parts
  double place_tolerance_mm = 10;
  bool has_change = false;
  IoBit change_request, change_ready;
  double change_time_s = 3;
  double change_move[2] = {0, 400};  // where the pallet goes during a change
};

struct MachineSpec {
  std::string path;
  std::string name;
  std::string kind;  // gantry_xyz
  unsigned tick_ms = kDefaultMachineTickMs;
  uint32_t seed = 1;
  std::vector<MachineJoint> joints;  // x, y, z
  MachineTool tool;
  std::map<std::string, MachinePartKind> parts;
  std::vector<MachineConveyor> conveyors;
  std::vector<MachineSensor> sensors;
  std::vector<MachineFixture> fixtures;

  // Every I/O bit the model reads (outputs) and writes (inputs), with the element that names it.
  std::vector<std::pair<IoBit, std::string>> outputs() const;
  std::vector<std::pair<IoBit, std::string>> inputs() const;
};

// Loads a machine file; errors name the file and the JSON path. The `visual`
// part is the configurator's and is not read.
bool parse_machine_file(const std::string& json, const std::string& path, MachineSpec& out,
                        std::vector<std::string>& errors);
bool load_machine_file(const std::string& path, MachineSpec& out, std::vector<std::string>& errors);

// A fault on a machine element, as a scenario step or sim_fault gives it:
// jam (joint), stuck on/off (sensor), slip (tool), feeder stop/empty and
// misaligned_mm (conveyor). The shape is checked here, the element when
// it is applied.
bool parse_machine_fault(const cJSON* json, std::string& err);
// The names a machine `clear` takes.
bool is_machine_clear_name(const std::string& name);

// What the model reads and writes, as the engine gives it.
class MachineIo {
 public:
  struct Drive {
    bool present = false;  // a powered drive model
    double actual = 0, demand = 0, velocity = 0, demand_velocity = 0;  // counts, counts/s
    std::string state;  // operation_enabled, fault, ...
    int mode = 0;
    uint16_t statusword = 0;
    bool fault = false;
    uint16_t error_code = 0;  // 0x603F
    double torque = 0;        // 0x6077, per mille
  };
  virtual ~MachineIo() = default;
  virtual Drive drive(unsigned node) = 0;
  // The machine's inputs of a drive and its load (per mille of rated torque).
  virtual void set_drive(unsigned node, const DriveInputs& inputs, double load_permille) = 0;
  virtual bool output(const IoBit& b) = 0;
  virtual void set_input(const IoBit& b, bool on) = 0;
};

class MachineModel {
 public:
  enum class PartState { Belt, Held, Falling, Placed, Misplaced, Table };
  struct Part {
    unsigned id = 0;
    const MachinePartKind* kind = nullptr;
    double pos[3] = {0, 0, 0};  // centre x, y and bottom height
    PartState state = PartState::Belt;
    int conveyor = -1;  // Belt
    double s = 0;       // Belt: distance of the centre from the conveyor's start
    double lateral = 0; // Belt: offset across the belt
    int fixture = -1, slot = -1;  // Placed, Misplaced
    double vz = 0;                // Falling
    double hold[3] = {0, 0, 0};   // Held: centre minus tool point
  };
  struct Counters {
    unsigned fed = 0, picked = 0, placed = 0, misplaced = 0, dropped = 0, pallets = 0;
  };

  MachineModel(const MachineSpec& spec, MachineIo& io);

  // Back to the start: no parts, gripper open, pallets in place and ready,
  // counters zero, faults cleared, the feeder's random sequence restarted.
  void Reset();
  // One step of `dt` seconds.
  void Step(double dt);

  // Faults on an element (joint, "tool", conveyor, sensor). False with `err`
  // for an unknown element or a fault that does not fit it.
  bool Fault(const std::string& element, const cJSON* fault, std::string& err);
  bool Clear(const std::string& element, const std::string& name, std::string& err);
  // [{"machine": element, "fault": {...}}, ...]
  cJSON* FaultsJson() const;

  // A scenario condition's value: a counter (fed, picked, placed, misplaced,
  // dropped, pallets), a sensor (0/1), a fixture (parts in its slots) or a
  // joint (position, mm).
  bool Value(const std::string& name, double& out) const;
  // The element names, for messages.
  std::vector<std::string> Names() const;

  // The sim_machine answer's state (time stamp and sequence number added by the caller).
  cJSON* Snapshot() const;

  const MachineSpec& spec() const { return spec_; }
  const Counters& counters() const { return counters_; }
  const std::vector<Part>& parts() const { return parts_; }
  double tool_position(int axis) const { return tool_[axis]; }
  double opening() const { return opening_; }
  double joint_position(size_t i) const { return jp_[i]; }

 private:
  struct Box {
    double lo[3], hi[3];
  };
  enum class Obstacle { Table, Conveyor, Fixture, Part };

  int JointIndex(const std::string& name) const;
  int ConveyorIndex(const std::string& name) const;
  int SensorIndex(const std::string& name) const;
  int FixtureIndex(const std::string& name) const;
  Box PartBox(const Part& p) const;
  Box ConveyorBox(size_t c) const;
  Box FixtureBox(size_t f) const;
  std::vector<Box> ToolBoxes(bool with_part) const;
  // The highest surface under the footprint `b` and what it is.
  double Support(const Box& b, unsigned skip_id, Obstacle& what, int& index) const;
  bool Blocks(size_t joint, int dir) const;
  void UpdateTool();
  void StepGripper(double dt);
  void StepConveyors(double dt);
  void StepFalling(double dt);
  void Land(Part& p, Obstacle what, int index);
  void StepFixtures(double dt);
  void WriteInputs();
  double SlotX(const MachineFixture& f, unsigned i) const;
  double SlotY(const MachineFixture& f, unsigned j) const;
  double Random(double a, double b);
  void Release();

  MachineSpec spec_;
  MachineIo& io_;
  std::mt19937 rng_;
  unsigned next_id_ = 1;
  std::vector<Part> parts_;
  Counters counters_;
  // Joints: position (mm), filtered velocity and acceleration, inputs sent.
  std::vector<double> jp_, jv_, ja_;
  std::vector<int> jpush_;
  std::vector<MachineIo::Drive> jd_;
  std::vector<bool> jam_;
  double tool_[3] = {0, 0, 0};
  // Gripper.
  double opening_ = 0;
  bool close_cmd_ = false;
  double stroke_ = 0;  // 0 open .. 1 closed
  int held_ = -1;      // index into parts_
  // Conveyors.
  std::vector<double> feed_wait_;
  std::vector<double> belt_travel_;
  std::vector<int> feeder_fault_;  // 0 none, 1 stop, 2 empty
  std::vector<double> misalign_;   // > 0: the next part fed is offset by this
  std::vector<bool> misalign_pending_;
  // Sensors: 0 normal, 1 stuck on, 2 stuck off.
  std::vector<int> stuck_;
  std::vector<bool> sensor_on_;
  // Fixtures: change phase 0..1 (< 0: not changing), offset, ready, request seen.
  std::vector<double> change_;
  std::vector<double> offset_x_, offset_y_;
  std::vector<bool> ready_, request_prev_, emptied_;
};

}  // namespace canopen_sim

#endif  // CANOPEN_SIM_MACHINE_H
