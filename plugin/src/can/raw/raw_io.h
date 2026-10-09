// raw_io.h - the raw I/O thread of a network on a SocketCAN interface (spec
// can-raw-messages, design Decision 2): its own CAN_RAW socket next to the
// protocol's, feeding the config messages (RawEngine) and the program's
// frame blocks (PlcPort), sending their frames, and confirming program
// frames by the adapter's echo. Simulated networks drive the same engine and
// port from their bus thread instead.

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

namespace canworks_raw {

struct RawIoHooks {
  // New input values for the PLC (engine->input_values() order).
  std::function<void(const std::vector<uint64_t>&)> publish_inputs;
  // The latest PLC output values (engine->output_locations() order); false
  // when the PLC has not published any yet.
  std::function<bool(std::vector<uint64_t>&)> latest_outputs;
  // The PLC program runs.
  std::function<bool()> plc_running;
  // Bus state and error counters from the bus monitor (state 4 when down).
  std::function<void(canworks_can_bus_info&)> bus_info;
  // A line for the runtime log.
  std::function<void(const std::string&)> log;
};

// How program frames are confirmed (diagnostics status).
enum class Confirm { Unknown, Echo, Write };

class RawIo {
 public:
  // `engine` may be null (no config messages); `port` is the network's
  // program frame port. `bitrate` gives the bus load.
  RawIo(std::string interface, uint32_t bitrate, bool listen_only, RawEngine* engine, PlcPort* port,
        RawIoHooks hooks);
  ~RawIo();
  void start();
  void stop();
  Confirm confirm_mode() const { return confirm_.load(); }
  // Engine status under the thread's lock (diagnostics).
  void with_engine(const std::function<void(const RawEngine&)>& f);

 private:
  void run();
  int open_socket();
  void set_filters(int fd);
  void receive(int fd, uint64_t now);
  void send_due(int fd, uint64_t now);
  bool write_frame(int fd, const canworks_can_frame& f, int& error);
  void update_bus(uint64_t now);

  std::string interface_;
  uint32_t bitrate_;
  bool listen_only_;
  RawEngine* engine_;
  PlcPort* port_;
  RawIoHooks hooks_;
  std::thread thread_;
  std::atomic<bool> stop_{false};
  int wake_fd_ = -1;
  std::mutex engine_mutex_;
  std::atomic<Confirm> confirm_{Confirm::Unknown};
  uint32_t filters_version_ = ~0u;
  bool filters_all_ = false;
  std::vector<uint64_t> outputs_;
  // Bus load: frame bits in the current second.
  uint64_t load_window_start_ = 0;
  uint64_t load_bits_ = 0;
  uint8_t bus_load_ = 0;
  uint64_t next_bus_update_ = 0;
};

}  // namespace canworks_raw

#endif  // CANWORKS_RAW_IO_H
