#include "slave_bus.h"

#include <pthread.h>

#include <lely/ev/loop.hpp>
#include <lely/io2/linux/can.hpp>
#include <lely/io2/posix/poll.hpp>
#include <lely/io2/sys/io.hpp>
#include <lely/io2/sys/timer.hpp>

#include "bus.h"
#include "log.h"
#include "network.h"

namespace canopen_plugin {

constexpr std::chrono::milliseconds SlaveBus::kLoopSlice;
constexpr int SlaveBus::kShutdownSlices;

SlaveBus::SlaveBus(const Config& cfg, SlaveImage& image, std::shared_ptr<SlaveStore> store, std::string state_path,
                   GatewayLink* gw, DiagHub* hub)
    : cfg_(cfg), image_(image), store_(std::move(store)), state_path_(std::move(state_path)), gw_(gw), hub_(hub),
      adapter_(make_adapter(cfg.adapter)) {}

SlaveBus::~SlaveBus() { stop(); }

void SlaveBus::start() {
  if (thread_.joinable()) return;
  stop_ = false;
  thread_ = std::thread([this] { thread_main(); });
}

void SlaveBus::stop() {
  {
    std::lock_guard<std::mutex> lock(mutex_);
    stop_ = true;
  }
  cv_.notify_all();
  if (thread_.joinable()) thread_.join();
}

bool SlaveBus::wait_for(std::chrono::milliseconds d) {
  std::unique_lock<std::mutex> lock(mutex_);
  cv_.wait_for(lock, d, [this] { return stop_.load(); });
  return !stop_;
}

void SlaveBus::thread_main() {
  pthread_setname_np(pthread_self(), "canopen_slave");
  set_thread_log_prefix(cfg_.log_prefix.empty() ? "" : cfg_.log_prefix + ": ");
  AdapterState last = AdapterState::Ready;
  std::string last_problem;
  while (!stop_) {
    AdapterState st = adapter_->prepare();
    if (st != AdapterState::Ready) {
      if (st != last || adapter_->problem() != last_problem)
        log_error("%s; the slave is off the bus, retrying", adapter_->problem().c_str());
      last = st;
      last_problem = adapter_->problem();
      if (!wait_for(std::chrono::milliseconds(1000))) break;
      continue;
    }
    if (last != AdapterState::Ready) log_info("CAN interface %s is up", cfg_.adapter.interface.c_str());
    last = AdapterState::Ready;
    last_problem.clear();
    run_session();
    if (!stop_ && !wait_for(std::chrono::milliseconds(1000))) break;
  }
  adapter_->release();
}

void SlaveBus::run_session() {
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
    lely::io::Timer loop_timer(poll, exec, CLOCK_MONOTONIC);
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
    PlcSlave slave(exec, timer, loop_timer, chan, cfg_, image_, store_, state_path_, gw_, [&]() {
      if (!stop_ && ++ticks % 5 == 0 && iface_state(cfg_.adapter.interface) != IfaceState::Up) iface_lost = true;
      if (stop_ || iface_lost) {
        end_session();
        return false;
      }
      return true;
    });
    if (cfg_.slave.lss && slave.node_id() == 0xFF)
      log_info("opened %s, starting the CANopen slave without a node ID (LSS)", cfg_.adapter.interface.c_str());
    else
      log_info("opened %s, starting the CANopen slave (node ID %u)", cfg_.adapter.interface.c_str(), slave.node_id());
    slave.SetDiag(hub_);
    FdWake gw_wake(poll, gw_ ? gw_->fd(cfg_.network_index) : -1, [&slave] { slave.ServiceGateway(); });
    slave.Start();
    if (hub_) hub_->attach();
    int slices_after_shutdown = 0;
    while (true) {
      loop.run_for(kLoopSlice);
      if (loop.stopped()) break;
      if (!shut_down && (stop_ || iface_state(cfg_.adapter.interface) != IfaceState::Up)) {
        if (!stop_) iface_lost = true;
        slave.Stop();
        end_session();
      } else if (shut_down && ++slices_after_shutdown >= kShutdownSlices) {
        log_warn("CANopen session on %s did not end cleanly after shutdown", cfg_.adapter.interface.c_str());
        loop.stop();
        break;
      }
    }
    slave.Stop();
    slave.MarkDown();
    if (iface_lost)
      log_error("CAN interface %s went down; the slave is off the bus, retrying", cfg_.adapter.interface.c_str());
  } catch (const std::exception& e) {
    image_.set_state(0);
    image_.set_comm_ok(false);
    image_.commit_inputs();
    if (gw_) gw_->set_upper_ok(false);
    log_error("CANopen slave session on %s failed: %s; retrying", cfg_.adapter.interface.c_str(), e.what());
  }
}

}  // namespace canopen_plugin
