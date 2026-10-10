// sim_raw.h - plain CAN devices of the simulation file (`raw_devices`,
// docs/simulator.md "Plain CAN devices"): frames sent at a period with
// signals driven by value sources, and replies to received frames.
//
// The engine owns the timing: it asks due() for the frames to send now,
// hands every received frame to on_frame() and sends the replies when
// they fall due. Nothing here touches a socket, so the same code runs on the
// simulated bus and in the standalone simulator.

#ifndef CANOPEN_SIM_RAW_H
#define CANOPEN_SIM_RAW_H

#include <cstdint>
#include <functional>
#include <memory>
#include <random>
#include <string>
#include <vector>

#include "can/mux.h"
#include "sim_expr.h"
#include "sim_source.h"

typedef struct cJSON cJSON;

namespace canopen_sim {

struct RawFrame {
  uint32_t id = 0;
  bool extended = false;
  bool rtr = false;
  uint8_t dlc = 0;
  uint8_t data[8] = {};
};

struct RawSimSignal {
  std::string name;
  unsigned start_bit = 0, length = 1;
  bool big_endian = false, is_signed = false;
  double scale = 1, offset = 0;  // the source gives scale * raw + offset
  std::string source_json;        // empty: a switch (its value comes from the page)
  canworks_can::MuxSpec mux;      // multiplexer / mux as in the config
};

struct RawSimSend {
  std::string name;
  RawFrame frame;  // identifier, flags, DLC and the bytes no signal covers
  unsigned period_ms = 0;
  std::vector<RawSimSignal> signals;
  // A send with switches (`multiplexer`): every page each period (`pages`
  // "all", the default) or the next page each period ("rotate").
  bool rotate = false;
  std::vector<canworks_can::MuxLayout::Page> pages;  // empty: not multiplexed
};

struct RawSimReply {
  uint32_t on_id = 0;
  bool on_extended = false;
  // Data the received frame must have under `mask` (empty: any data).
  std::vector<uint8_t> on_data, on_mask;
  RawFrame send;
  unsigned delay_ms = 0;
};

struct RawDeviceSpec {
  std::string name;
  std::string network;  // "" with one network
  std::vector<RawSimSend> sends;
  std::vector<RawSimReply> replies;
};

// Parses the file's `raw_devices` list; errors name the entry
// ("raw_devices[0].send[1].signals[0]: ...").
bool parse_raw_devices(const cJSON* list, std::vector<RawDeviceSpec>& out, std::vector<std::string>& errors);

// One running device.
class RawDevice {
 public:
  explicit RawDevice(RawDeviceSpec spec);
  ~RawDevice();
  RawDevice(const RawDevice&) = delete;
  RawDevice& operator=(const RawDevice&) = delete;

  const RawDeviceSpec& spec() const { return spec_; }
  const std::string& name() const { return spec_.name; }

  // Parses and binds the value sources; `base_dir` resolves CSV paths.
  bool bind(const std::string& base_dir, const ExprResolver& resolver, std::vector<std::string>& errors);

  // Starts sending at `now_ms` (the first frames go out at once) and
  // restarts every source; also how a stopped device comes back.
  void power_on(uint64_t now_ms);
  // Stops sending and replying (scenario stop, fault "stop").
  void power_off();
  bool powered() const { return powered_; }

  // Fault "wrong_dlc": every sent frame carries `dlc` (0-8) instead of its
  // own; -1 clears it.
  void set_dlc_fault(int dlc) { dlc_fault_ = dlc; }
  int dlc_fault() const { return dlc_fault_; }

  // Appends the frames due at `now_ms` (periodic sends and replies whose
  // delay has passed).
  void due(uint64_t now_ms, std::vector<RawFrame>& out, ExprContext& ctx);
  // A frame from the bus; matching replies are queued.
  void on_frame(const RawFrame& frame, uint64_t now_ms);
  // Milliseconds until something falls due (UINT64_MAX: nothing).
  uint64_t next_in(uint64_t now_ms) const;

  uint64_t sent() const { return sent_; }

 private:
  struct Bound;
  // The frame of a send; `page` indexes its pages (-1: not multiplexed).
  RawFrame build(size_t send, int page, double t, ExprContext& ctx);

  RawDeviceSpec spec_;
  std::vector<std::unique_ptr<Bound>> bound_;
  std::vector<uint64_t> next_due_;
  std::vector<size_t> cursor_;  // per send: the next page ("rotate")
  struct Pending {
    uint64_t at;
    RawFrame frame;
  };
  std::vector<Pending> pending_;
  bool powered_ = false;
  int dlc_fault_ = -1;
  uint64_t start_ms_ = 0;
  uint64_t sent_ = 0;
};

// A scenario step on a device: fault "stop" (power_off) or "wrong_dlc"
// (`dlc`), clear "stop" (power_on), "wrong_dlc" or "all". False with `err`
// for an unknown action.
bool raw_device_action(RawDevice& d, const std::string& action, const std::string& what, int dlc, uint64_t now_ms,
                       std::string& err);

// Scenarios on a plain CAN network, where no CANopen simulator runs: steps
// with "device" and "fault" or "clear", "log" and "repeat", timed with
// "at_ms" or "after_ms" (docs/simulator.md, "Plain CAN devices").
struct RawScenarioStep {
  bool has_at = false, has_after = false;
  unsigned at_ms = 0, after_ms = 0;
  std::string action;  // fault, clear, log, repeat
  std::string device, what;  // fault: stop | wrong_dlc; clear: stop | wrong_dlc | all
  int dlc = -1;
  std::string log;
  unsigned count = 1;  // repeat: 0 = forever
  std::vector<RawScenarioStep> steps;
};

struct RawScenario {
  std::string name;
  bool autostart = false;
  std::vector<RawScenarioStep> steps;
};

// Parses a network's "scenarios" object; errors name the scenario and step.
bool parse_raw_scenarios(const cJSON* scenarios, std::vector<RawScenario>& out, std::vector<std::string>& errors);

class RawScenarioRunner {
 public:
  using Log = std::function<void(const std::string&)>;
  RawScenarioRunner(std::vector<RawDevice*> devices, Log log) : devices_(std::move(devices)), log_(std::move(log)) {}
  void start(const RawScenario& sc, uint64_t now_ms);
  // Runs the steps that are due.
  void step(uint64_t now_ms);
  // Milliseconds until a step falls due (UINT64_MAX: none).
  uint64_t next_in(uint64_t now_ms) const;
  bool running() const { return !runs_.empty(); }

 private:
  struct Frame {
    const std::vector<RawScenarioStep>* steps;
    size_t i = 0;
    unsigned remaining = 0;
    bool forever = false;
  };
  struct Run {
    std::string name;
    uint64_t start = 0, prev_end = 0;
    std::vector<Frame> stack;
  };
  bool due_at(const Run& r, uint64_t& at) const;
  std::vector<RawDevice*> devices_;
  Log log_;
  std::vector<Run> runs_;
};

// The bytes of `f` as "0x123 [2] 01 02" (for logs and status answers).
std::string raw_frame_text(const RawFrame& f);

}  // namespace canopen_sim

#endif  // CANOPEN_SIM_RAW_H
