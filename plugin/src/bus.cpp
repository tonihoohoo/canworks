#include "bus.h"

#include <cstdlib>
#include <cstring>
#include <fstream>
#include <map>
#include <net/if.h>
#include <pthread.h>

#include <lely/ev/loop.hpp>
#include <lely/io2/linux/can.hpp>
#include <lely/io2/posix/poll.hpp>
#include <lely/io2/sys/clock.hpp>
#include <lely/io2/sys/io.hpp>
#include <lely/io2/sys/timer.hpp>
#include <lely/io2/vcan.hpp>

#include "can_adapter.h"
#include "log.h"
#include "network.h"
#include "sim_config.h"
#include "sim_host.h"

namespace canopen_plugin {

constexpr std::chrono::milliseconds Bus::kLoopSlice;
constexpr int Bus::kShutdownSlices;
constexpr int Bus::kSyncPriority;

std::shared_ptr<lely::io::VirtualCanController> shared_virtual_bus(const std::string& interface) {
  if (interface.empty()) return std::make_shared<lely::io::VirtualCanController>(lely::io::clock_monotonic);
  static std::mutex mutex;
  static std::map<std::string, std::weak_ptr<lely::io::VirtualCanController>> buses;
  std::lock_guard<std::mutex> lock(mutex);
  auto& slot = buses[interface];
  std::shared_ptr<lely::io::VirtualCanController> bus = slot.lock();
  if (!bus) {
    // Lely's virtual controller is thread-safe: each channel reads on its own
    // event loop, so the master's and the slave's bus threads can share it.
    bus = std::make_shared<lely::io::VirtualCanController>(lely::io::clock_monotonic);
    slot = bus;
  }
  return bus;
}

IfaceState iface_state(const std::string& name) {
  std::ifstream in("/sys/class/net/" + name + "/flags");
  if (!in) return IfaceState::Missing;
  unsigned long flags = 0;
  in >> std::hex >> flags;
  return (flags & IFF_UP) ? IfaceState::Up : IfaceState::Down;
}

Bus::Bus(const Config& cfg, const GeneratedConfig& gen, ProcessImage& image, DiagHub* hub,
         std::shared_ptr<const SimSetup> sim, GatewayLink* gw)
    : cfg_(cfg), gen_(gen), image_(image), hub_(hub), sim_(std::move(sim)), gw_(gw),
      adapter_(cfg.adapter.simulate ? nullptr : make_adapter(cfg.adapter)), monitor_(cfg, image) {}

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
  set_thread_log_prefix(cfg_.log_prefix.empty() ? "" : cfg_.log_prefix + ": ");
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
  if (cfg_.adapter.simulate) {
    // A simulated network has no adapter: no link, no interface to wait for.
    while (!stop_) {
      run_session();
      if (monitor_.no_bus()) image_.commit_inputs();
      if (!stop_ && !wait_for(std::chrono::milliseconds(1000))) break;
    }
    return;
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
    const bool virt = cfg_.adapter.simulate;
    const std::string where = virt ? std::string("the simulated network") : cfg_.adapter.interface;
    // The master's channel: on the in-process virtual bus, or on the interface.
    std::shared_ptr<lely::io::VirtualCanController> vbus;
    std::unique_ptr<lely::io::CanController> ctrl;
    std::unique_ptr<lely::io::CanChannelBase> chan;
    if (virt) {
      vbus = shared_virtual_bus(cfg_.adapter.interface);
      auto* c = new lely::io::VirtualCanChannel(ctx, exec);
      chan.reset(c);
      c->open(*vbus);
    } else {
      ctrl.reset(new lely::io::CanController(cfg_.adapter.interface.c_str()));
      auto* c = new lely::io::CanChannel(poll, exec);
      chan.reset(c);
      c->open(*ctrl);
    }
    auto iface_down = [&]() { return !virt && iface_state(cfg_.adapter.interface) != IfaceState::Up; };

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
    Network net(exec, timer, sup_timer, *chan, cfg_, gen_, image_, [&]() {
      if (!stop_ && ++ticks % 5 == 0 && iface_down()) iface_lost = true;
      if (stop_ || iface_lost) {
        end_session();
        return false;
      }
      if (virt ? monitor_.simulated() : monitor_.poll(BusMonitor::clock::now())) image_.commit_inputs();
      return true;
    }, &req_timer, &out_timer);
    log_info("opened %s, starting the CANopen master (node ID %u)", where.c_str(), cfg_.master.node_id);
    net.SetDiag(hub_);
    net.SetGateway(gw_);

    // Simulated devices, on the virtual bus or on their own sockets on the
    // interface; they boot before the master starts.
    std::unique_ptr<canopen_sim::LoopHost> sim_host;
    std::unique_ptr<canopen_sim::Simulator> simulator;
    std::unique_ptr<lely::io::VirtualCanChannel> tap_chan;
    can_msg tap_msg = CAN_MSG_INIT;
    std::function<void()> tap_read;
    if (sim_ && simulates_anything(cfg_)) {
      auto sim_log = [](canopen_sim::Host::Level l, const std::string& m) {
        if (l == canopen_sim::Host::Level::Info)
          log_info("simulated %s", m.c_str());
        else if (l == canopen_sim::Host::Level::Warn)
          log_warn("simulated %s", m.c_str());
        else
          log_error("simulated %s", m.c_str());
      };
      std::vector<canopen_sim::DeviceSpec> specs = sim_device_specs(cfg_, true);
      if (virt) {
        sim_host.reset(new canopen_sim::LoopHost(ctx, poll, exec, *vbus, sim_log));
      } else {
        sim_host.reset(new canopen_sim::LoopHost(ctx, poll, exec, cfg_.adapter.interface, true, sim_log));
        // A node ID that a device on the wire already uses stays real.
        if (!specs.empty() || !sim_->file.extra.empty()) {
          std::set<unsigned> seen;
          std::string err;
          if (!listen_node_ids(cfg_.adapter.interface, 1000, seen, err)) log_warn("%s", err.c_str());
          std::set<unsigned> conflicts;
          for (auto& d : specs) {
            d.conflict = seen.count(d.node) > 0;
            if (d.conflict && !d.extra) conflicts.insert(d.node);
          }
          net.SetSimConflicts(std::move(conflicts));
        }
      }
      canopen_sim::SimOptions opt;
      opt.store = sim_->store;
      opt.simulated_network = virt;
      simulator.reset(new canopen_sim::Simulator(*sim_host, specs, sim_->file, opt));
      std::vector<std::string> errors;
      if (!simulator->Start(errors)) {
        for (const auto& e : errors) log_error("simulation: %s", e.c_str());
        log_error("the simulated devices could not start; the master runs without them");
        simulator.reset();
      } else {
        canopen_sim::Simulator* s = simulator.get();
        net.SetSimHandler([s](const cJSON* req, const std::string& id, const std::string& peer) {
          return s->Handle(req, id, peer);
        });
      }
    }
    // The bus trace on a simulated network: a channel that sees every frame.
    if (virt && sim_ && sim_->tap) {
      tap_chan.reset(new lely::io::VirtualCanChannel(ctx, exec));
      tap_chan->open(*vbus);
      SimTraceTap* tap = sim_->tap.get();
      tap_read = [&, tap]() {
        tap_chan->submit_read(&tap_msg, nullptr, nullptr, exec, [&, tap](int result, std::error_code ec) {
          if (ec) return;
          if (result == 1) tap->push(tap_msg);
          tap_read();
        });
      };
      tap_read();
    }
    net.Start();
    SyncWake sync_wake(poll, image_.sync_fd(), net);
    FdWake gw_wake(poll, gw_ ? gw_->fd(cfg_.network_index) : -1, [&net] { net.ServiceGateway(); });
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
      if (!shut_down && (stop_ || iface_down())) {
        if (!stop_) iface_lost = true;
        // As the supervision tick does when it ends the session: what is in
        // flight is cancelled, so the loop can drain.
        net.Stop();
        end_session();
      } else if (shut_down && ++slices_after_shutdown >= kShutdownSlices) {
        // The shutdown did not drain the loop (with the adapter gone, its
        // socket can keep the poll busy): stop it and let the objects below
        // cancel what is left as they are destroyed.
        log_warn("CANopen session on %s did not end cleanly after shutdown", where.c_str());
        loop.stop();
        break;
      }
    }
    if (simulator) simulator->Stop();
    net.MarkAllDown();
    if (iface_lost)
      log_error("CAN interface %s went down; nodes are not operational, retrying", cfg_.adapter.interface.c_str());
  } catch (const std::exception& e) {
    for (unsigned id : image_.nodes()) image_.set_node_status(id, false);
    monitor_.no_bus();
    image_.commit_inputs();
    log_error("CANopen session on %s failed: %s; retrying",
              cfg_.adapter.simulate ? "the simulated network" : cfg_.adapter.interface.c_str(), e.what());
  }
}

}  // namespace canopen_plugin
