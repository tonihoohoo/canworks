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
#include <memory>
#include <random>
#include <string>
#include <vector>

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
  std::string source_json;
};

struct RawSimSend {
  std::string name;
  RawFrame frame;  // identifier, flags, DLC and the bytes no signal covers
  unsigned period_ms = 0;
  std::vector<RawSimSignal> signals;
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
  RawFrame build(size_t send, double t, ExprContext& ctx);

  RawDeviceSpec spec_;
  std::vector<std::unique_ptr<Bound>> bound_;
  std::vector<uint64_t> next_due_;
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

// The bytes of `f` as "0x123 [2] 01 02" (for logs and status answers).
std::string raw_frame_text(const RawFrame& f);

}  // namespace canopen_sim

#endif  // CANOPEN_SIM_RAW_H
