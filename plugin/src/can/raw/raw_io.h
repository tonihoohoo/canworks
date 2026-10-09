// raw_io.h - the raw I/O thread of a network (spec can-raw-messages, design
// Decision 2): its own link next to the protocol's (a CAN_RAW socket, or a
// bridge to the simulated bus), feeding the config messages (RawEngine) and
// the program's frame blocks (PlcPort), sending their frames, and
// confirming program frames by their echo. On a simulated network it also
// runs the simulation file's plain CAN devices and, on a plain CAN network,
// the frames sent by hand through the diagnostics channel.

#ifndef CANWORKS_RAW_IO_H
#define CANWORKS_RAW_IO_H

#include <atomic>
#include <cstdint>
#include <functional>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#include "engine.h"
#include "plc_frames.h"
#include "raw_devices.h"
#include "raw_link.h"

namespace canopen_plugin {
class SimFrameInjector;
}

namespace canworks_raw {

struct RawIoHooks {
  // New input values for the PLC (engine->input_values() order).
  std::function<void(const std::vector<uint64_t>&)> publish_inputs;
  // The latest PLC output values (engine->output_locations() order); false
  // when the PLC has not published any yet.
  std::function<bool(std::vector<uint64_t>&)> latest_outputs;
  // The PLC program runs.
  std::function<bool()> plc_running;
  // Bus state and error counters (state 4 when down).
  std::function<void(canworks_can_bus_info&)> bus_info;
  // Before each (re)open of the link: bring the interface up (plain CAN
  // networks own their adapter). False: not now, retry later.
  std::function<bool()> prepare;
  // A line for the runtime log.
  std::function<void(const std::string&)> log;
};

class RawIo {
 public:
  // `engine` may be null (no config messages); `port` is the network's
  // program frame port. `bitrate` gives the bus load. `devices` and
  // `injector` are optional (simulated networks).
  RawIo(std::unique_ptr<RawLink> link, uint32_t bitrate, bool listen_only, RawEngine* engine, PlcPort* port,
        RawIoHooks hooks, RawSimDevices* devices = nullptr,
        std::shared_ptr<canopen_plugin::SimFrameInjector> injector = nullptr);
  ~RawIo();
  void start();
  void stop();
  Confirm confirm_mode() const { return confirm_.load(); }
  // Engine status under the thread's lock (diagnostics).
  void with_engine(const std::function<void(const RawEngine&)>& f);
  // Frames this path wrote and received (diagnostics).
  uint64_t frames_sent() const { return sent_.load(); }
  uint64_t frames_received() const { return received_.load(); }
  uint8_t bus_load() const { return bus_load_.load(); }

 private:
  void run();
  void set_filters();
  void receive(uint64_t now);
  void handle(const LinkFrame& lf, uint64_t now);
  void send_due(uint64_t now);
  bool write_frame(const canworks_can_frame& f, int& error, Origin origin = Origin::Own);
  void update_bus(uint64_t now);
  int next_timeout(uint64_t now);

  std::unique_ptr<RawLink> link_;
  uint32_t bitrate_;
  bool listen_only_;
  RawEngine* engine_;
  PlcPort* port_;
  RawIoHooks hooks_;
  RawSimDevices* devices_;
  std::shared_ptr<canopen_plugin::SimFrameInjector> injector_;
  std::thread thread_;
  std::atomic<bool> stop_{false};
  int wake_fd_ = -1;
  std::mutex engine_mutex_;
  std::atomic<Confirm> confirm_{Confirm::Unknown};
  uint32_t filters_version_ = ~0u;
  bool filters_all_ = false;
  std::vector<uint64_t> outputs_;
  std::vector<LinkFrame> rx_buf_;
  std::vector<canworks_can_frame> dev_buf_;
  std::atomic<uint64_t> sent_{0}, received_{0};
  // Bus load: frame bits in the current second.
  uint64_t load_window_start_ = 0;
  uint64_t load_bits_ = 0;
  std::atomic<uint8_t> bus_load_{0};
  uint64_t next_bus_update_ = 0;
};

}  // namespace canworks_raw

#endif  // CANWORKS_RAW_IO_H
