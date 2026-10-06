#include "bus.h"

#include <cstdlib>
#include <cstring>
#include <fstream>
#include <net/if.h>
#include <pthread.h>

#include <lely/ev/loop.hpp>
#include <lely/io2/linux/can.hpp>
#include <lely/io2/posix/poll.hpp>
#include <lely/io2/sys/io.hpp>
#include <lely/io2/sys/timer.hpp>

#include "can_adapter.h"
#include "log.h"
#include "network.h"

namespace canopen_plugin {

constexpr std::chrono::milliseconds Bus::kLoopSlice;
constexpr int Bus::kShutdownSlices;
constexpr int Bus::kSyncPriority;

IfaceState iface_state(const std::string& name) {
  std::ifstream in("/sys/class/net/" + name + "/flags");
  if (!in) return IfaceState::Missing;
  unsigned long flags = 0;
  in >> std::hex >> flags;
  return (flags & IFF_UP) ? IfaceState::Up : IfaceState::Down;
}

Bus::Bus(const Config& cfg, const GeneratedConfig& gen, ProcessImage& image, DiagHub* hub)
    : cfg_(cfg), gen_(gen), image_(image), hub_(hub), adapter_(make_adapter(cfg.adapter)), monitor_(cfg, image) {}

Bus::~Bus() { stop(); }

void Bus::start() {
  if (thread_.joinable()) return;
  stop_ = false;
  monitor_.reset();  // before the thread exists, so no race on the image
  thread_ = std::thread([this] { thread_main(); });
}

void Bus::stop() {
  {
    std::lock_guard<std::mutex> lock(mutex_);
    stop_ = true;
  }
  cv_.notify_all();
  if (thread_.joinable()) thread_.join();
}

bool Bus::wait_for(std::chrono::milliseconds d) {
  std::unique_lock<std::mutex> lock(mutex_);
  cv_.wait_for(lock, d, [this] { return stop_.load(); });
  return !stop_;
}

void Bus::thread_main() {
  pthread_setname_np(pthread_self(), "canopen_bus");
  if (cfg_.master.sync_plc_cycle && !std::getenv("CANOPEN_BUS_NO_FIFO")) {
    // PLC-cycle SYNC: the SYNC should follow the frame closely, so the bus
    // thread runs at the level of the runtime's highest task priority (below
    // its dispatcher). Without the right to do so it runs as before.
    // CANOPEN_BUS_NO_FIFO skips this, to measure what it gains.
    sched_param sp{};
    sp.sched_priority = kSyncPriority;
    int rc = pthread_setschedparam(pthread_self(), SCHED_FIFO, &sp);
    if (rc)
      log_warn("cannot run the CANopen bus thread at SCHED_FIFO %d (%s); PLC-cycle SYNC may jitter more",
               kSyncPriority, strerror(rc));
  }
  const char* name = cfg_.adapter.interface.c_str();
  AdapterState last = AdapterState::Ready;
  std::string last_problem;
  while (!stop_) {
    // Link setup runs on every attempt, so a link that was reset or lost its
    // bit rate is configured again.
    AdapterState st = adapter_->prepare();
    if (st != AdapterState::Ready) {
      if (monitor_.no_bus()) image_.commit_inputs();
      if (st != last || adapter_->problem() != last_problem)
        log_error("%s; nodes are not operational, retrying", adapter_->problem().c_str());
      last = st;
      last_problem = adapter_->problem();
      if (!wait_for(std::chrono::milliseconds(1000))) break;
      continue;
    }
    if (last != AdapterState::Ready) log_info("CAN interface %s is up", name);
    last = AdapterState::Ready;
    last_problem.clear();
    run_session();
    if (monitor_.no_bus()) image_.commit_inputs();
    if (!stop_ && !wait_for(std::chrono::milliseconds(1000))) break;
  }
  adapter_->release();
}

void Bus::run_session() {
  // Requests the session's Network took and did not answer get "no bus"
  // when it ends, however it ends.
  struct Detach {
    DiagHub* hub;
    ~Detach() {
      if (hub) hub->detach();
    }
  } detach{hub_};
  try {
    lely::io::IoGuard io_guard;
    lely::io::Context ctx;
    lely::io::Poll poll(ctx);
    lely::ev::Loop loop(poll.get_poll());
    auto exec = loop.get_executor();
    lely::io::Timer timer(poll, exec, CLOCK_MONOTONIC);
    lely::io::Timer sup_timer(poll, exec, CLOCK_MONOTONIC);
    lely::io::Timer req_timer(poll, exec, CLOCK_MONOTONIC);
    lely::io::Timer out_timer(poll, exec, CLOCK_MONOTONIC);
    lely::io::CanController ctrl(cfg_.adapter.interface.c_str());
    lely::io::CanChannel chan(poll, exec);
    chan.open(ctrl);

    bool iface_lost = false;
    bool shut_down = false;
    int ticks = 0;
    auto end_session = [&]() {
      if (!shut_down) ctx.shutdown();
      shut_down = true;
    };
    // The supervision tick ends the session by shutting the I/O context down:
    // that cancels every pending Lely operation, after which the loop stops
    // and everything can be destroyed cleanly.
    Network net(exec, timer, sup_timer, chan, cfg_, gen_, image_, [&]() {
      if (!stop_ && ++ticks % 5 == 0 && iface_state(cfg_.adapter.interface) != IfaceState::Up) iface_lost = true;
      if (stop_ || iface_lost) {
        end_session();
        return false;
      }
      if (monitor_.poll(BusMonitor::clock::now())) image_.commit_inputs();
      return true;
    }, &req_timer, &out_timer);
    log_info("opened %s, starting the CANopen master (node ID %u)", cfg_.adapter.interface.c_str(),
             cfg_.master.node_id);
    net.SetDiag(hub_);
    net.Start();
    SyncWake sync_wake(poll, image_.sync_fd(), net);
    if (hub_) hub_->attach();
    // The loop runs in slices so that a stop or a lost interface ends the
    // session even when no supervision tick comes: when an slcan adapter is
    // unplugged, Lely can drop every registration from its poll set, and the
    // loop would then wait forever (and a PLC stop would hang joining this
    // thread).
    int slices_after_shutdown = 0;
    while (true) {
      loop.run_for(kLoopSlice);
      if (loop.stopped()) break;
      if (!shut_down && (stop_ || iface_state(cfg_.adapter.interface) != IfaceState::Up)) {
        if (!stop_) iface_lost = true;
        end_session();
      } else if (shut_down && ++slices_after_shutdown >= kShutdownSlices) {
        // The shutdown did not drain the loop (with the adapter gone, its
        // socket can keep the poll busy): stop it and let the objects below
        // cancel what is left as they are destroyed.
        log_warn("CANopen session on %s did not end cleanly after shutdown", cfg_.adapter.interface.c_str());
        loop.stop();
        break;
      }
    }
    net.MarkAllDown();
    if (iface_lost)
      log_error("CAN interface %s went down; nodes are not operational, retrying", cfg_.adapter.interface.c_str());
  } catch (const std::exception& e) {
    for (unsigned id : image_.nodes()) image_.set_node_status(id, false);
    monitor_.no_bus();
    image_.commit_inputs();
    log_error("CANopen session on %s failed: %s; retrying", cfg_.adapter.interface.c_str(), e.what());
  }
}

}  // namespace canopen_plugin
