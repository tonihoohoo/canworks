// sim_engine.h - the simulator engine: simulated devices, their behaviour,
// faults, scenarios and the control requests (docs/simulator.md).
//
// The engine runs on one Lely event loop, which its host owns: the plugin's
// bus thread (simulated network, or simulated nodes on a real interface) or
// the standalone canworks-sim. The host gives it timers and CAN
// channels; everything the engine does happens in callbacks on that loop,
// and every public method must be called from the loop's thread.

#ifndef CANOPEN_SIM_ENGINE_H
#define CANOPEN_SIM_ENGINE_H

#include <chrono>
#include <cstdint>
#include <functional>
#include <map>
#include <memory>
#include <random>
#include <set>
#include <string>
#include <vector>

#include <lely/ev/exec.hpp>
#include <lely/io2/can.hpp>
#include <lely/io2/tqueue.hpp>
#include <lely/io2/timer.hpp>

#include "sim_device.h"
#include "sim_file.h"
#include "sim_machine.h"

typedef struct cJSON cJSON;

namespace canopen_sim {

class Host {
 public:
  enum class Level { Info, Warn, Error };
  virtual ~Host() = default;
  virtual ev_exec_t* exec() = 0;
  // Shared pointers: Lely's timer and channel classes have no virtual
  // destructor, and a channel deleted as its base stays open on the bus.
  virtual std::shared_ptr<lely::io::TimerBase> make_timer() = 0;
  // A new channel on the bus, open.
  virtual std::shared_ptr<lely::io::CanChannelBase> make_channel() = 0;
  virtual void log(Level level, const std::string& message) = 0;
  // Simulated devices next to real ones: the conflict guard runs.
  virtual bool real_network() const = 0;
  virtual std::string interface_name() const = 0;
};

// One device to simulate.
struct DeviceSpec {
  unsigned node = 0;     // 1-127; 0: no node ID (waits for LSS)
  std::string name;      // extra devices: their name; config nodes: the node's name
  bool extra = false;    // from extra_devices
  std::string eds_path;  // EDS or DCF
  // 0x1018 values the device must have (the config's identity and LSS
  // address), before the simulation file's overrides.
  std::map<uint8_t, uint32_t> identity;
  // The node waits for its node ID over LSS (lss_assign in the config).
  bool lss = false;
  // Objects the master writes, and what writes them ("RPDO 1", "startup
  // SDO", ...): no value source may drive them.
  std::map<ObjKey, std::string> master_written;
  bool has_behaviour = false;
  NodeBehaviour behaviour;
  // Found taken on the real network before the start: not started.
  bool conflict = false;
};

// Stored parameters per device, kept by the host across sessions; keyed by
// "node:<id>" or "name:<name>" and the file's hash.
using StoreMap = std::map<std::string, std::shared_ptr<StoredState>>;

struct SimOptions {
  bool defaults = true;  // default behaviour by profile
  std::shared_ptr<StoreMap> store;
  std::string state_dir;  // standalone: keep stored state on disk
  std::string version;    // for hello/status
  bool simulated_network = false;
};

struct ScenarioResult {
  std::string name;
  bool passed = false;
  bool stopped = false;
  std::string message;
  double seconds = 0;
};

class Simulator {
 public:
  using Clock = std::chrono::steady_clock;

  Simulator(Host& host, std::vector<DeviceSpec> devices, SimFile file, SimOptions options);
  ~Simulator();

  // Creates the devices and binds sources and expressions. False with
  // `errors` when the simulation does not fit the devices (unknown object,
  // expression error, source on a master-written object, ...).
  bool Start(std::vector<std::string>& errors);
  // Powers every device off and stops timers; idempotent.
  void Stop();

  // A control request (one parsed JSON line, op sim_*); returns the answer
  // line. `id` is the request's id as JSON text ("" = none).
  std::string Handle(const cJSON* req, const std::string& id, const std::string& peer);
  static bool ReadOnlyOp(const std::string& op);

  // Scenarios.
  bool StartScenario(const std::string& name, std::string& err);
  bool StartScenario(const Scenario& sc, std::string& err);
  void StopScenario(const std::string& name);
  bool ScenarioRunning() const;
  const std::vector<Scenario>& Scenarios() const { return file_.scenarios; }
  std::function<void(const ScenarioResult&)> on_scenario_end;

  // Every started device (no conflict, powered) is OPERATIONAL.
  bool AllOperational() const;
  size_t DeviceCount() const { return devs_.size(); }
  std::vector<unsigned> NodeIds() const;
  // Whether a node ID is simulated here.
  bool Simulates(unsigned node) const;
  // The network's machine model; nullptr without one (or on a real network).
  const MachineModel* Machine() const { return machine_.get(); }

 private:
  struct Dev;
  struct Run;
  struct SourceSlot;
  class Resolver;
  class Ctx;
  class DriveIoImpl;
  class MachineIoImpl;

  void Log(Host::Level l, const std::string& m);
  void PowerOn(Dev& d);
  void PowerOff(Dev& d, const std::string& why);
  void ApplyFaultSettings(Dev& d);
  bool ApplyFault(Dev& d, const Fault& f, std::string& err);
  bool ClearFault(Dev& d, const std::string& name, const cJSON* req, std::string& err);
  bool SetSource(Dev& d, const ObjKey& k, const std::string& json, bool from_file, std::string& err);
  bool CheckCycles(std::string& err);
  bool StartMachine(std::vector<std::string>& errors);
  void StepMachine(Clock::time_point now);
  void Tick();
  void TickDevice(Dev& d, Clock::time_point now, double dt);
  void RunSources(Clock::time_point now, bool rpdo = false);
  void RunScenarios(Clock::time_point now);
  bool StepRun(Run& r, Clock::time_point now);
  void EndRun(Run& r, bool passed, const std::string& msg);
  bool EvalCondition(const Condition& c, const std::string& self, bool& holds, std::string& seen, std::string& err);
  // Writes a value from a writer of `level` (0 default, 1 drive, 2 source,
  // 3 set, 4 override); false when a higher writer owns the object.
  void Write(Dev& d, const ObjKey& k, const Value& v, int level);
  int Owner(const Dev& d, const ObjKey& k) const;
  Dev* Find(const std::string& ref);
  Dev* FindJson(const cJSON* node, std::string& err);
  std::string StoreKey(const Dev& d) const;
  void Persist(Dev& d);
  void LoadPersisted(Dev& d);

  Host& host_;
  SimFile file_;
  SimOptions opt_;
  std::vector<std::unique_ptr<Dev>> devs_;
  std::vector<std::unique_ptr<Run>> runs_;
  std::shared_ptr<lely::io::TimerBase> timer_;
  std::unique_ptr<lely::io::TimerWait> wait_;
  unsigned tick_ms_ = kDefaultTickMs;
  Clock::time_point start_;
  Clock::time_point last_tick_;
  std::mt19937 rng_;
  bool started_ = false;
  bool stopped_ = false;
  std::vector<SourceSlot*> order_;  // sources in evaluation order
  bool order_dirty_ = true;
  bool rpdo_posted_ = false;
  std::shared_ptr<bool> alive_ = std::make_shared<bool>(true);
  // The machine model (docs/simulator.md, Simulated machine).
  std::unique_ptr<MachineIoImpl> machine_io_;
  std::unique_ptr<MachineModel> machine_;
  Clock::time_point machine_next_, machine_last_;
  uint64_t machine_seq_ = 0;
  double machine_step_us_ = 0, machine_step_max_us_ = 0;
};

}  // namespace canopen_sim

#endif  // CANOPEN_SIM_ENGINE_H
