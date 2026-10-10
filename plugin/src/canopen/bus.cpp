#include "bus.h"

#include <cstdlib>
#include <cstring>
#include <deque>
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
#include "raw_bridge_server.h"
#include "sim_config.h"
#include "sim_host.h"
#include "raw/raw_devices.h"

namespace canopen_plugin {

constexpr std::chrono::milliseconds Bus::kLoopSlice;
constexpr int Bus::kShutdownSlices;
constexpr int Bus::kSyncPriority;
constexpr std::chrono::milliseconds Bus::kStopDrain;

void leave_realtime() {
  int policy = SCHED_OTHER;
  sched_param sp{};
  if (pthread_getschedparam(pthread_self(), &policy, &sp) != 0 || policy == SCHED_OTHER) return;
  sp.sched_priority = 0;
  pthread_setschedparam(pthread_self(), SCHED_OTHER, &sp);
}

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
    // A bit rate sweep ended the session: run it, then a new session at once.
    if (run_requested_sweep(hub_, adapter_.get(), cfg_, stop_)) continue;
    if (!stop_ && !wait_for(std::chrono::milliseconds(1000))) break;
  }
  adapter_->release();
}

bool run_requested_sweep(DiagHub* hub, CanAdapter* adapter, const Config& cfg, const std::atomic<bool>& stop) {
  SweepRequest req;
  if (!hub || !hub->take_sweep(req)) return false;
  SweepResult res;
  LinkOps* ops = adapter ? adapter->link_ops() : nullptr;
  if (!ops || stop) {
    res.verdict = SweepVerdict::Failed;
    res.error = stop ? "stopped (the PLC stopped)" : "the adapter cannot change its bit rate";
  } else {
    std::string rates;
    for (unsigned k : req.rates_kbit) rates += (rates.empty() ? "" : ", ") + std::to_string(k);
    log_info("bit rate detection on %s: listening %u ms per rate (%s), %u round(s)", cfg.adapter.interface.c_str(),
             req.per_rate_ms, rates.empty() ? "all CiA 301 rates" : rates.c_str(), req.rounds);
    const long restart_ms = cfg.adapter.has_restart_ms ? static_cast<long>(cfg.adapter.restart_ms) : -1;
    auto sweep = [&](LinkOps& link, SweepListener& listener) {
      res = run_bitrate_sweep(link, listener, cfg.adapter.interface, cfg.adapter.bitrate, restart_ms, req,
                              [hub](const SweepProgress& p) { hub->sweep_progress(p); },
                              [&stop] { return stop.load(); });
    };
    // slcan sweeps over its serial device (slcan_sweep.h), the rest over the link.
    std::string device_error;
    if (adapter->sweep_on_device(sweep, req.disturb_bus, device_error)) {
      if (!device_error.empty()) {
        res.verdict = SweepVerdict::Failed;
        res.error = device_error;
      }
    } else {
      auto listener = make_can_sweep_listener();
      sweep(*ops, *listener);
    }
  }
  std::string what = sweep_verdict_name(res.verdict);
  if (res.verdict == SweepVerdict::Detected)
    what += " " + std::to_string(res.bitrate_kbit) + " kbit/s" +
            (res.bitrate_kbit * 1000 == cfg.adapter.bitrate ? " (as configured)" : " (the config says " +
                                                                std::to_string(cfg.adapter.bitrate / 1000) + ")");
  else if (res.verdict == SweepVerdict::Failed)
    what += ": " + res.error;
  log_info("bit rate detection on %s ended: %s; CANopen starts again at %u bit/s", cfg.adapter.interface.c_str(),
           what.c_str(), cfg.adapter.bitrate);
  hub->sweep_done(res);
  return true;
}

void Bus::enter_realtime() {
  if (!cfg_.master.sync_plc_cycle || std::getenv("CANWORKS_BUS_NO_FIFO")) return;
  // PLC-cycle SYNC: the SYNC should follow the frame closely, so the bus
  // thread runs at the level of the runtime's highest task priority (below
  // its dispatcher) while a session runs; a session's shutdown leaves it
  // (leave_realtime). Without the right to do so it runs as before.
  // CANWORKS_BUS_NO_FIFO skips this, to measure what it gains.
  sched_param sp{};
  sp.sched_priority = kSyncPriority;
  int rc = pthread_setschedparam(pthread_self(), SCHED_FIFO, &sp);
  if (rc && !fifo_warned_) {
    fifo_warned_ = true;
    log_warn("cannot run the CANopen bus thread at SCHED_FIFO %d (%s); PLC-cycle SYNC may jitter more", kSyncPriority,
             strerror(rc));
  }
}

void Bus::run_session() {
  enter_realtime();
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
    // A shared pointer deletes the channel as what it is (Lely's channel
    // classes have no virtual destructor): it leaves the bus at the end.
    std::shared_ptr<lely::io::CanChannelBase> chan;
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
      if (!shut_down) {
        // What follows can wait (the loop draining, the adapter): not at
        // SCHED_FIFO, where it would hold the CPU from the runtime.
        leave_realtime();
        ctx.shutdown();
      }
      shut_down = true;
    };
    // Frames the master and the diagnostics channel (below) put on the
    // simulated bus that the trace tap has yet to see: it marks them Tx.
    // Before the Network, which can send until it is destroyed.
    std::deque<can_msg> sent;
    // The supervision tick ends the session by shutting the I/O context down:
    // that cancels every pending Lely operation, after which the loop stops
    // and everything can be destroyed cleanly.
    Network* netp = nullptr;
    Network net(exec, timer, sup_timer, *chan, cfg_, gen_, image_, [&]() {
      if (!stop_ && ++ticks % 5 == 0 && iface_down()) iface_lost = true;
      if (stop_) {
        // No output PDO after the stop request; the loop below sends the
        // NMT command of master.on_plc_stop and ends the session.
        if (netp) netp->StopNodes();
        return true;
      }
      if (iface_lost) {
        end_session();
        return false;
      }
      if (virt ? monitor_.simulated() : monitor_.poll(BusMonitor::clock::now())) image_.commit_inputs();
      return true;
    }, &req_timer, &out_timer);
    netp = &net;
    log_info("opened %s, starting the CANopen master (node ID %u)", where.c_str(), cfg_.master.node_id);
    net.SetDiag(hub_);
    // The upper master's stand-in on a simulated bus is not a field network:
    // its node states and EMCYs (the gateway's own) must not go back up.
    if (gw_ && gw_->field_position(cfg_.network_index) >= 0) net.SetGateway(gw_);

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
      std::set<unsigned> taken_ids;  // config nodes and extra devices alike
      if (virt) {
        sim_host.reset(new canopen_sim::LoopHost(ctx, poll, exec, *vbus, sim_log));
      } else {
        sim_host.reset(new canopen_sim::LoopHost(ctx, poll, exec, cfg_.adapter.interface, true, sim_log));
        // A node ID that a device on the wire already uses stays real.
        if (!specs.empty() || !sim_->file.extra.empty()) {
          std::set<unsigned> seen;
          std::string err;
          if (!listen_node_ids(cfg_.adapter.interface, 1000, seen, err)) log_warn("%s", err.c_str());
          taken_ids = seen;
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
      opt.taken = taken_ids;
      simulator.reset(new canopen_sim::Simulator(*sim_host, specs, sim_->file, opt));
      // Plain CAN devices run in the network's raw path (raw_devices.h).
      unsigned index = cfg_.network_index;
      simulator->raw_device_action = [index](const std::string& device, const std::string& action,
                                             const std::string& what, int dlc, std::string& err) {
        return canworks_raw::sim_device_action(index, device, action, what, dlc, err);
      };
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
      net.SetSendTap([&sent](const can_msg& m) {
        if (sent.size() >= 256) sent.pop_front();  // never seen: do not grow
        sent.push_back(m);
      });
      tap_chan.reset(new lely::io::VirtualCanChannel(ctx, exec));
      tap_chan->open(*vbus);
      SimTraceTap* tap = sim_->tap.get();
      tap_read = [&, tap]() {
        tap_chan->submit_read(&tap_msg, nullptr, nullptr, exec, [&, tap](int result, std::error_code ec) {
          if (ec) return;
          if (result == 1) {
            bool tx = false;
            for (auto it = sent.begin(); it != sent.end(); ++it)
              if (it->id == tap_msg.id && it->flags == tap_msg.flags && it->len == tap_msg.len &&
                  std::memcmp(it->data, tap_msg.data, tap_msg.len) == 0) {
                sent.erase(it);
                tx = true;
                break;
              }
            tap->push(tap_msg, tx);
          }
          tap_read();
        });
      };
      tap_read();
    }
    // Frames sent by hand through the diagnostics channel, onto the virtual
    // bus (frame_tx.h); the tap sees them there and marks them Tx.
    // The channel also receives every frame on the virtual bus: it is read
    // and the frames dropped, or its receive queue fills and each write on
    // the bus then blocks.
    can_msg inject_msg = CAN_MSG_INIT;
    std::function<void()> inject_read;
    std::unique_ptr<lely::io::VirtualCanChannel> inject_chan;
    std::unique_ptr<FdWake> inject_wake;
    if (virt && sim_ && sim_->injector) {
      inject_chan.reset(new lely::io::VirtualCanChannel(ctx, exec));
      inject_chan->open(*vbus);
      inject_read = [&]() {
        inject_chan->submit_read(&inject_msg, nullptr, nullptr, exec, [&](int, std::error_code ec) {
          if (!ec) inject_read();
        });
      };
      inject_read();
      SimFrameInjector* inj = sim_->injector.get();
      const bool tapped = static_cast<bool>(tap_chan);
      inject_wake.reset(new FdWake(poll, inj->read_fd(), [&, inj, tapped] {
        std::vector<RawFrame> frames;
        inj->drain(frames);
        for (const auto& f : frames) {
          can_msg msg;
          raw_frame_to_msg(f, msg);
          std::error_code ec;
          inject_chan->write(msg, 0, ec);
          if (!ec && tapped) {
            if (sent.size() >= 256) sent.pop_front();  // never seen: do not grow
            sent.push_back(msg);
          }
        }
      }));
    }
    // The raw path (raw messages, program frames, plain CAN devices) on the
    // virtual bus; its own frames show as Tx in a trace.
    std::unique_ptr<RawBridgeServer> raw_bridge;
    if (virt) {
      if (auto bridge = canworks_raw::sim_bridge(cfg_.network_index)) {
        const bool tapped = static_cast<bool>(tap_chan);
        raw_bridge.reset(new RawBridgeServer(ctx, poll, exec, *vbus, bridge, [&, tapped](const can_msg& m, bool own) {
          if (!own || !tapped) return;
          if (sent.size() >= 256) sent.pop_front();
          sent.push_back(m);
        }));
      }
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
        if (stop_) {
          // The PLC or the plugin stops: master.on_plc_stop's NMT command
          // to the nodes, given time to go out before the I/O shuts down.
          net.StopNodes();
          loop.run_for(kStopDrain);
        }
        // As the supervision tick does when it ends the session: what is in
        // flight is cancelled, so the loop can drain.
        net.Stop();
        end_session();
      } else if (!shut_down && hub_ && hub_->sweep_pending()) {
        // Bit rate detection: the session ends as on an adapter loss and the
        // sweep runs before the next one (run_requested_sweep).
        log_info("bit rate detection requested: ending the CANopen session on %s", where.c_str());
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
