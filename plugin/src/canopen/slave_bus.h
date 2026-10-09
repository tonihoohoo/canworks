// slave_bus.h - the bus thread of a slave network: prepares the CAN adapter
// as Bus does, runs a PlcSlave on a Lely event loop, and keeps retrying while
// the interface is missing or down (canopen-slave-device spec).

#ifndef CANOPEN_SLAVE_BUS_H
#define CANOPEN_SLAVE_BUS_H

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <memory>
#include <mutex>
#include <string>
#include <thread>

#include "can_adapter.h"
#include "config.h"
#include "diag.h"
#include "gateway.h"
#include "plc_slave.h"
#include "slave_state.h"

namespace canopen_plugin {

class SlaveBus {
 public:
  // `store` is what was loaded from `state_path`; the slave keeps it up to
  // date and writes the file on a save or LSS store. `gw` when the network
  // is a gateway's upper network.
  SlaveBus(const Config& cfg, SlaveImage& image, std::shared_ptr<SlaveStore> store, std::string state_path,
           GatewayLink* gw = nullptr, DiagHub* hub = nullptr);
  ~SlaveBus();

  void start();
  void stop();  // idempotent; joins

 private:
  static constexpr std::chrono::milliseconds kLoopSlice{200};
  static constexpr int kShutdownSlices = 10;

  void thread_main();
  void run_session();
  bool wait_for(std::chrono::milliseconds d);

  const Config& cfg_;
  SlaveImage& image_;
  std::shared_ptr<SlaveStore> store_;
  std::string state_path_;
  GatewayLink* gw_;
  DiagHub* hub_;
  std::unique_ptr<CanAdapter> adapter_;
  std::thread thread_;
  std::atomic<bool> stop_{false};
  std::mutex mutex_;
  std::condition_variable cv_;
};

}  // namespace canopen_plugin

#endif  // CANOPEN_SLAVE_BUS_H
