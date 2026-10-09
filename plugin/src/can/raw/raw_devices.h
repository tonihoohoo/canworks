// raw_devices.h - the plain CAN devices of the simulation file
// (`raw_devices`, canopen/sim/sim_raw.h) on one simulated network of the
// plugin. The network's raw I/O thread runs them: it hands them every frame
// on the bus and writes the frames they send. Their value sources have no
// object dictionary to refer to: references to CANopen objects are refused.

#ifndef CANWORKS_RAW_DEVICES_H
#define CANWORKS_RAW_DEVICES_H

#include <cstdint>
#include <memory>
#include <random>
#include <string>
#include <vector>

#include "../can_plc_api.h"

namespace canopen_sim {
class RawDevice;
}

namespace canworks_raw {

class RawSimDevices {
 public:
  RawSimDevices();
  ~RawSimDevices();

  // The devices of the simulation file at `path` for network `network`
  // (devices without a network belong to the only network; `several`: the
  // config has more than one). Errors name the file and the device.
  bool load(const std::string& path, const std::string& network, bool several, std::vector<std::string>& errors);
  // Parses JSON text instead of a file (tests); `dir` resolves CSV paths.
  bool load_text(const std::string& json, const std::string& path, const std::string& dir, const std::string& network,
                 bool several, std::vector<std::string>& errors);

  size_t size() const { return devices_.size(); }
  std::vector<std::string> names() const;

  // Raw I/O thread.
  void start(uint64_t now_ms);
  void on_frame(const canworks_can_frame& f, uint64_t now_ms);
  void due(uint64_t now_ms, std::vector<canworks_can_frame>& out);
  // Milliseconds until a device sends (UINT64_MAX: none).
  uint64_t next_in(uint64_t now_ms) const;

 private:
  std::vector<std::unique_ptr<canopen_sim::RawDevice>> devices_;
  std::mt19937 rng_;
};

// The simulation file next to the config or in the runtime's conf/canworks/
// folder; "" when there is none.
std::string find_simulation_file(const std::string& config_dir, const std::string& fallback_dir);

}  // namespace canworks_raw

#endif  // CANWORKS_RAW_DEVICES_H
