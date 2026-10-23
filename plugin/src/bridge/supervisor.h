// supervisor.h - the bridge's stall watchdog and its systemd notifications
// (modbus-bridge "Stall watchdog", "Bridge service limits").
//
// The watched threads beat their counters (can/progress.h). The supervisor
// thread reads them every 500 ms: one that has not moved for the stall time
// is logged by name and the process aborts, so systemd or the container's
// restart policy starts it again. While every counter moved within the last
// 3 s it sends systemd WATCHDOG=1 once a second; systemd's own watchdog is
// then only the backstop for a stuck supervisor. Paused (a config upload
// being applied) it watches nothing and keeps notifying.

#ifndef CANWORKS_BRIDGE_SUPERVISOR_H
#define CANWORKS_BRIDGE_SUPERVISOR_H

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <functional>
#include <mutex>
#include <string>
#include <thread>

namespace canworks_bridge {

// One sd_notify datagram ("READY=1", "WATCHDOG=1", ...) to $NOTIFY_SOCKET;
// false (and nothing sent) when it is not set or cannot be reached.
bool sd_notify_state(const std::string& state);

class Supervisor {
 public:
  using Ms = std::chrono::milliseconds;
  struct Options {
    Ms stall{10000};
    Ms tick{500};
    Ms notify_every{1000};
    Ms fresh{3000};  // every counter moved within this: WATCHDOG=1
    // Called with the stalled thread's name; the default logs and aborts.
    std::function<void(const std::string&)> on_stall;
    // Sends a notification; the default is sd_notify_state.
    std::function<void(const std::string&)> notify;
  };

  explicit Supervisor(Options opt);
  ~Supervisor() { stop(); }
  void start();
  void stop();
  // While paused no thread counts as stalled (the networks are being
  // restarted on an uploaded config).
  void pause(bool paused) { paused_ = paused; }

 private:
  void run();
  Options opt_;
  std::atomic<bool> paused_{false};
  bool stop_ = false;
  std::mutex mu_;
  std::condition_variable cv_;
  std::thread thread_;
};

}  // namespace canworks_bridge

#endif  // CANWORKS_BRIDGE_SUPERVISOR_H
