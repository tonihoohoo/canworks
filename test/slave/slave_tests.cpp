// Virtual-bus tests of the slave role and the gateway (canopen-slave-device
// and canopen-gateway specs). The plugin's own master (Network) is the other
// PLC: it boots the plugin's slave (PlcSlave) on a shared Lely virtual bus,
// all on one event loop, with a fake PLC scan over both images. The gateway
// tests add a field network with a ping-pong device on a second virtual bus.
//
// Networks sit on virtual buses by their adapter interface name up to the
// first '.': "line.m" (the other PLC's master) and "line.s" (the slave) share
// the bus "line", which the config itself would refuse for one real interface.

#include <atomic>
#include <chrono>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <functional>
#include <map>
#include <memory>
#include <mutex>
#include <sstream>
#include <string>
#include <sys/stat.h>
#include <thread>
#include <unistd.h>
#include <vector>

#include <lely/co/dev.h>
#include <lely/co/obj.h>
#include <lely/co/val.h>
#include <lely/ev/loop.hpp>
#include <lely/io2/posix/poll.hpp>
#include <lely/io2/sys/io.hpp>
#include <lely/io2/sys/timer.hpp>
#include <lely/io2/vcan.hpp>

#include "check.hpp"
#include "config.h"
#include "cJSON.h"
#include "dcf_gen.h"
#include "diag.h"
#include "eds_check.h"
#include "eds_lint.h"
#include "fake_runtime.hpp"
#include "gateway.h"
#include "log.h"
#include "network.h"
#include "pingpong_slave.hpp"
#include "plc_api.h"
#include "plc_slave.h"
#include "process_image.h"
#include "slave_state.h"

using namespace canopen_plugin;
using namespace lely;
using namespace std::chrono;

namespace {

std::mutex& log_mutex() {
  static std::mutex m;
  return m;
}
std::vector<std::string>& log_store() {
  static std::vector<std::string> l;
  return l;
}
void capture(LogLevel, const char* msg) {
  {
    std::lock_guard<std::mutex> lock(log_mutex());
    log_store().push_back(msg);
  }
  if (std::getenv("SIM_VERBOSE")) std::printf("    log: %s\n", msg);
}
void clear_logs() {
  std::lock_guard<std::mutex> lock(log_mutex());
  log_store().clear();
}
bool logged(const std::string& needle) {
  std::lock_guard<std::mutex> lock(log_mutex());
  for (const auto& l : log_store())
    if (l.find(needle) != std::string::npos) return true;
  return false;
}

std::string read(const std::string& path) {
  std::ifstream in(path);
  std::stringstream ss;
  ss << in.rdbuf();
  return ss.str();
}

std::string make_dir(const std::string& json, const std::vector<std::pair<std::string, std::string>>& files) {
  char tmpl[] = "/tmp/canopen-slave-XXXXXX";
  std::string dir = mkdtemp(tmpl);
  for (const auto& f : files) std::ofstream(dir + "/" + f.first) << f.second;
  std::ofstream(dir + "/canopen_config.json") << json;
  return dir;
}

std::string slave_eds() { return read(std::string(CONFIG_DIR) + "/slave/openplc-slave.eds"); }
std::string gateway_eds() { return read(std::string(CONFIG_DIR) + "/gateway/openplc-gateway.eds"); }
std::string pingpong_eds() { return read(std::string(PINGPONG_DIR) + "/cpp-slave.eds"); }

// A device on its own thread and loop, as in the plugin's sim tests.
class Box {
 public:
  using Make = std::function<canopen::BasicSlave*(io::TimerBase&, io::CanChannelBase&)>;
  Box(io::VirtualCanController& ctrl, Make make)
      : poll_(ctx_), loop_(poll_.get_poll()), exec_(loop_.get_executor()), timer_(poll_, exec_, CLOCK_MONOTONIC),
        chan_(ctx_, exec_) {
    chan_.open(ctrl);
    slave_.reset(make(timer_, chan_));
    thread_ = std::thread([this] {
      slave_->Reset();
      loop_.run();
    });
  }
  ~Box() {
    ctx_.shutdown();
    thread_.join();
    slave_.reset();
  }
  void Post(std::function<void(canopen::BasicSlave&)> f) {
    exec_.post([this, f] { f(*slave_); });
  }

 private:
  io::Context ctx_;
  io::Poll poll_;
  ev::Loop loop_;
  ev::Executor exec_;
  io::Timer timer_;
  io::VirtualCanChannel chan_;
  std::unique_ptr<canopen::BasicSlave> slave_;
  std::thread thread_;
};

// The whole config on one loop. Store state per slave network survives a
// Rebuild() of that network's slave (a PLC restart).
class SlaveSim {
 public:
  struct Bus {
    explicit Bus(io::TimerBase& t) : ctrl(t.get_clock()) {}
    io::VirtualCanController ctrl;
  };
  // A network's own controller joined to the shared bus by two channels
  // that copy frames both ways; Unplug() stops the copying (a pulled cable).
  // Closing the network's channel instead would leave Lely re-submitting
  // reads on a closed channel in a tight loop.
  struct Cable {
    Cable(io::TimerBase& t, io::Context& ctx, ev::Executor& exec) : own(t.get_clock()), near(ctx, exec), far(ctx, exec) {}
    io::VirtualCanController own;
    io::VirtualCanChannel near, far;
    can_msg in = CAN_MSG_INIT, out = CAN_MSG_INIT;
    bool plugged = true;
    void Join(Bus& bus, ev::Executor& exec) {
      near.open(own);
      far.open(bus.ctrl);
      Copy(near, far, out, exec);
      Copy(far, near, in, exec);
    }
    void Copy(io::VirtualCanChannel& from, io::VirtualCanChannel& to, can_msg& m, ev::Executor& exec) {
      from.submit_read(&m, nullptr, nullptr, exec, [this, &from, &to, &m, &exec](int result, std::error_code ec) {
        if (ec) return;
        if (result == 1 && plugged) to.write(m);
        Copy(from, to, m, exec);
      });
    }
  };
  struct Net {
    Net(io::Poll& poll, ev::Executor& exec, io::Context& ctx, io::TimerBase& clock)
        : timer(poll, exec, CLOCK_MONOTONIC), sup(poll, exec, CLOCK_MONOTONIC), req(poll, exec, CLOCK_MONOTONIC),
          out(poll, exec, CLOCK_MONOTONIC), cable(clock, ctx, exec), chan(new io::VirtualCanChannel(ctx, exec)) {}
    io::Timer timer, sup, req, out;
    // A restarted slave's timers (a new bus session has new ones).
    std::vector<std::unique_ptr<io::Timer>> restart_timers;
    Cable cable;
    std::unique_ptr<io::VirtualCanChannel> chan;
    bool slave = false;
    GeneratedConfig gen;
    ProcessImage image;
    std::unique_ptr<Network> net;
    SlaveImage simage;
    std::shared_ptr<SlaveStore> store;
    std::string state_path;
    std::unique_ptr<PlcSlave> dev;
    std::unique_ptr<FdWake> wake;
    Bus* bus = nullptr;
  };

  explicit SlaveSim(const std::string& dir, const std::string& state_dir = "")
      : poll_(ctx_), loop_(poll_.get_poll()), exec_(loop_.get_executor()), clock_timer_(poll_, exec_, CLOCK_MONOTONIC),
        scan_timer_(poll_, exec_, CLOCK_MONOTONIC), sniff_(ctx_, exec_) {
    state_dir_ = state_dir.empty() ? dir + "/state" : state_dir;
    std::vector<std::string> errors;
    ok_ = load_config_set(dir + "/canopen_config.json", ImageLimits(), set_, errors);
    for (auto& cfg : set_.networks) {
      nets_.emplace_back(new Net(poll_, exec_, ctx_, clock_timer_));
      Net& n = *nets_.back();
      ok_ = ok_ && run_eds_lint(cfg, default_edslint_python(), cfg.work_dir, errors) && check_eds_files(cfg, errors);
      if (ok_ && !cfg.is_slave()) ok_ = generate_device_config(cfg, default_dcfgen(), n.gen, errors);
    }
    ok_ = ok_ && check_gateway_eds(set_, errors);
    errors_ = errors;
    for (const auto& e : errors) std::printf("  setup: %s\n", e.c_str());
    if (!ok_) return;
    fake_runtime::attach(fake_, rt_);
    if (set_.gateway.enabled) gw_.reset(new GatewayLink(set_));
    for (size_t i = 0; i < set_.networks.size(); ++i) {
      const Config& cfg = set_.networks[i];
      Net& n = *nets_[i];
      std::string key = cfg.adapter.interface.substr(0, cfg.adapter.interface.find('.'));
      auto& b = buses_[key];
      if (!b) b.reset(new Bus(clock_timer_));
      n.bus = b.get();
      n.cable.Join(*b, exec_);
      n.chan->open(n.cable.own);
      if (cfg.is_slave()) {
        n.slave = true;
        n.simage.build(cfg);
        n.state_path = slave_state_path(state_dir_, cfg.network);
        n.store = std::make_shared<SlaveStore>();
        std::string note;
        load_slave_state(n.state_path, cfg.slave.eds_sha256, *n.store, note);
        if (!note.empty()) log_warn("%s", note.c_str());
        n.dev.reset(new PlcSlave(exec_, n.timer, n.out, *n.chan, cfg, n.simage, n.store, n.state_path, gw_.get()));
        n.wake.reset(new FdWake(poll_, gw_ ? gw_->fd(cfg.network_index) : -1, [&n] { n.dev->ServiceGateway(); }));
      } else {
        n.image.build(cfg);
        n.net.reset(new Network(exec_, n.timer, n.sup, *n.chan, cfg, n.gen, n.image, nullptr, &n.req, &n.out));
        // The other controller ("*.m", the upper master) is in this config
        // only for the test; in a real gateway it is another device, so it
        // does not feed node states or EMCYs into the gateway (its EMCY
        // from the gateway would otherwise come back up in a loop).
        if (cfg.adapter.interface.size() < 2 || cfg.adapter.interface.compare(cfg.adapter.interface.size() - 2, 2, ".m"))
          n.net->SetGateway(gw_.get());
        n.wake.reset(new FdWake(poll_, gw_ ? gw_->fd(cfg.network_index) : -1, [&n] { n.net->ServiceGateway(); }));
      }
    }
    PlcRequests::instance().open(static_cast<unsigned>(set_.networks.size()));
    scan_timer_.settime(milliseconds(10), milliseconds(10));
    scan_timer_.submit_wait(exec_, [this](int, std::error_code ec) {
      if (!ec) Scan();
    });
  }

  ~SlaveSim() {
    boxes_.clear();
    for (auto& h : hubs_) h->detach();
    for (auto& n : nets_) {
      if (n->net) n->net->Stop();
      if (n->dev) n->dev->Stop();
      n->wake.reset();
    }
    // Cancel the cables' reads and let the loop deliver the cancellations
    // before the channels go away.
    for (auto& n : nets_) {
      n->cable.near.close();
      n->cable.far.close();
    }
    for (auto& c : old_chans_) c->close();
    loop_.restart();
    loop_.run_for(milliseconds(20));
    ctx_.shutdown();
    loop_.restart();
    for (int i = 0; i < 20 && !loop_.stopped(); ++i) loop_.run_for(milliseconds(100));
    if (!loop_.stopped()) loop_.stop();
    for (auto& n : nets_) {
      n->net.reset();
      n->dev.reset();
    }
    PlcRequests::instance().close();
  }

  bool ok() const { return ok_; }
  const std::vector<std::string>& errors() const { return errors_; }
  Net& net(size_t i) { return *nets_[i]; }
  PlcSlave& dev(size_t i) { return *nets_[i]->dev; }
  fake_runtime::Image& plc() { return fake_; }

  // Starts every network: slaves first, so the masters find them.
  void Start() {
    for (auto& n : nets_)
      if (n->dev) n->dev->Start();
    for (auto& n : nets_)
      if (n->net) n->net->Start();
  }
  // The slave network `i` as after a PLC restart: a new device from the EDS
  // and the state file.
  void Restart(size_t i) {
    Net& n = *nets_[i];
    const Config& cfg = set_.networks[i];
    n.wake.reset();
    n.dev->Stop();
    n.dev.reset();
    loop_.restart();
    loop_.run_for(milliseconds(20));
    // A new channel for the new device, as a new bus session opens one. The
    // old one is closed (an open channel nobody reads fills up and stalls
    // the controller) and destroyed at the end.
    n.chan->close();
    old_chans_.push_back(std::move(n.chan));
    n.chan.reset(new io::VirtualCanChannel(ctx_, exec_));
    n.chan->open(n.cable.own);
    n.simage.build(cfg);
    n.store = std::make_shared<SlaveStore>();
    std::string note;
    load_slave_state(n.state_path, cfg.slave.eds_sha256, *n.store, note);
    if (!note.empty()) log_warn("%s", note.c_str());
    n.restart_timers.emplace_back(new io::Timer(poll_, exec_, CLOCK_MONOTONIC));
    n.restart_timers.emplace_back(new io::Timer(poll_, exec_, CLOCK_MONOTONIC));
    auto& t = n.restart_timers;
    n.dev.reset(new PlcSlave(exec_, *t[t.size() - 2], *t.back(), *n.chan, cfg, n.simage, n.store, n.state_path,
                             gw_.get()));
    n.dev->Start();
  }
  // Serves the diagnostics channel of slave network `i` through a hub.
  void EnableDiag(size_t i) {
    hubs_.emplace_back(new DiagHub(set_.networks[i], "sim"));
    nets_[i]->dev->SetDiag(hubs_.back().get());
    hubs_.back()->attach();
  }
  DiagHub& hub() { return *hubs_.back(); }
  // Sends a request to the last enabled hub and runs the loop until its
  // answer arrives; the parsed answer (cJSON_Delete it) or null.
  cJSON* Ask(DiagRequest r, milliseconds timeout = milliseconds(3000)) {
    uint64_t seq = hub().submit(std::move(r));
    std::string line;
    RunUntil([&] {
      std::vector<std::pair<uint64_t, std::string>> got;
      hub().take_answers(got);
      for (auto& a : got)
        if (a.first == seq) line = a.second;
      return !line.empty();
    }, timeout);
    return line.empty() ? nullptr : cJSON_Parse(line.c_str());
  }

  // Takes network `i` off its bus (cable pulled) and back.
  void Unplug(size_t i) { nets_[i]->cable.plugged = false; }
  void Replug(size_t i) { nets_[i]->cable.plugged = true; }

  // A ping-pong device with node ID `id` on the bus `key`.
  PingPongSlave* AddPingPong(const std::string& key, uint8_t id) {
    PingPongSlave* made = nullptr;
    boxes_.emplace_back(new Box(buses_.at(key)->ctrl, [&](io::TimerBase& t, io::CanChannelBase& c) {
      return made = new PingPongSlave(t, c, std::string(PINGPONG_DIR) + "/cpp-slave.eds", "", id);
    }));
    return made;
  }

  // Sniffs the bus `key` (frames counted per COB-ID, EMCY bodies kept).
  void Sniff(const std::string& key) {
    sniff_.open(buses_.at(key)->ctrl);
    ReadSniff();
  }
  int frames(uint32_t id) { return frames_[id]; }
  std::vector<can_msg> frames_of(uint32_t id) {
    std::vector<can_msg> out;
    for (const auto& m : log_)
      if (m.id == id) out.push_back(m);
    return out;
  }
  // Sends a raw frame on the bus `key` from a separate channel.
  void Send(const std::string& key, uint32_t id, std::vector<uint8_t> data) {
    if (!raw_) {
      raw_.reset(new io::VirtualCanChannel(ctx_, exec_));
      raw_->open(buses_.at(key)->ctrl);
    }
    can_msg m = CAN_MSG_INIT;
    m.id = id;
    m.len = static_cast<uint8_t>(data.size());
    std::memcpy(m.data, data.data(), data.size());
    raw_->write(m);
  }

  template <class F>
  bool RunUntil(F pred, milliseconds timeout) {
    auto end = steady_clock::now() + timeout;
    while (steady_clock::now() < end) {
      loop_.run_for(milliseconds(2));
      loop_.restart();
      if (pred()) return true;
    }
    return pred();
  }
  void RunFor(milliseconds d) {
    RunUntil([] { return false; }, d);
  }

  void SetProgram(std::function<void(fake_runtime::Image&)> p) { program_ = std::move(p); }
  void PauseScan(milliseconds d) { pause_until_ = steady_clock::now() + d; }

  // An SDO transfer through the program's request path on network `net`.
  // Returns the error id (0 = done) and fills `value` for reads.
  uint16_t Sdo(unsigned net, uint8_t node, uint16_t idx, uint8_t sub, bool write, uint64_t value, uint8_t size,
               uint64_t* out = nullptr, uint32_t* abort = nullptr) {
    canopen_plc_request req{};
    req.network = static_cast<uint8_t>(net);
    req.node = node;
    req.index = idx;
    req.subindex = sub;
    req.write = write ? 1 : 0;
    req.kind = CANOPEN_PLC_INT;
    req.size = size;
    req.timeout_ms = 1000;
    uint8_t data[8];
    for (int i = 0; i < 8; ++i) data[i] = static_cast<uint8_t>(value >> (8 * i));
    if (write) {
      req.data = data;
      req.length = 8;
    }
    uint16_t err = 0;
    uint32_t h = PlcRequests::instance().start(req, err);
    if (!h) return err;
    canopen_plc_result res{};
    uint8_t buf[8] = {0};
    int rc = 0;
    RunUntil([&] { return (rc = PlcRequests::instance().poll(h, &res, buf, sizeof buf)) != 0; }, milliseconds(3000));
    if (abort) *abort = res.abort_code;
    if (out) {
      *out = 0;
      for (unsigned i = 0; i < std::min<uint32_t>(res.size, 8); ++i) *out |= uint64_t(buf[i]) << (8 * i);
    }
    return rc == 1 ? 0 : (res.error_id ? res.error_id : 0xFFFF);
  }

 private:
  void Scan() {
    if (steady_clock::now() >= pause_until_) {
      for (auto& n : nets_) {
        if (n->slave)
          n->simage.copy_to_plc(rt_);
        else
          n->image.copy_to_plc(rt_);
      }
      if (program_) program_(fake_);
      for (auto& n : nets_) {
        if (n->slave)
          n->simage.copy_from_plc(rt_);
        else
          n->image.copy_from_plc(rt_);
      }
    }
    scan_timer_.submit_wait(exec_, [this](int, std::error_code ec) {
      if (!ec) Scan();
    });
  }
  void ReadSniff() {
    sniff_.submit_read(&msg_, nullptr, nullptr, exec_, [this](int result, std::error_code ec) {
      if (ec) return;
      if (result == 1) {
        ++frames_[msg_.id];
        log_.push_back(msg_);
      }
      ReadSniff();
    });
  }

  io::IoGuard io_guard_;
  io::Context ctx_;
  io::Poll poll_;
  ev::Loop loop_;
  ev::Executor exec_;
  io::Timer clock_timer_;
  io::Timer scan_timer_;
  io::VirtualCanChannel sniff_;
  std::unique_ptr<io::VirtualCanChannel> raw_;
  can_msg msg_ = CAN_MSG_INIT;
  std::map<uint32_t, int> frames_;
  std::vector<can_msg> log_;
  std::map<std::string, std::unique_ptr<Bus>> buses_;
  ConfigSet set_;
  std::vector<std::unique_ptr<Net>> nets_;
  std::unique_ptr<GatewayLink> gw_;
  std::vector<std::unique_ptr<Box>> boxes_;
  std::vector<std::unique_ptr<io::VirtualCanChannel>> old_chans_;
  std::vector<std::unique_ptr<DiagHub>> hubs_;
  fake_runtime::Image fake_;
  plugin_runtime_args_t rt_;
  std::function<void(fake_runtime::Image&)> program_;
  steady_clock::time_point pause_until_{};
  std::string state_dir_;
  std::vector<std::string> errors_;
  bool ok_ = false;
};

// The other PLC (master "plc" on line.m) and the plugin's slave (node 10 on
// line.s). The master maps the slave's 0x2000:1 (speed, from the master) and
// 0x2001:1 into its RPDO 1... seen from the slave; the slave's 0x2100:1/2 come back.
std::string slave_json(const std::string& master_node_extra = "", const std::string& slave_extra = "",
                       const std::string& master_extra = "", const std::string& tx_extra = "") {
  return R"({ "schema_version": 2, "networks": [
    { "name": "plc", "adapter": { "type": "socketcan", "interface": "line.m", "bitrate": 250000 },
      "master": { "node_id": 1, "heartbeat_ms": 50 )" + master_extra + R"( },
      "nodes": [ { "node_id": 10, "name": "openplc", "eds": "openplc-slave.eds" )" + master_node_extra + R"(,
        "tx_pdos": [ { "number": 1, )" + tx_extra + R"( "entries": [
            { "index": "0x2100", "subindex": 1, "type": "UNSIGNED16", "iec_location": "%IW10" },
            { "index": "0x2100", "subindex": 2, "type": "UNSIGNED16", "iec_location": "%IW11" } ] } ],
        "rx_pdos": [ { "number": 1, "entries": [
            { "index": "0x2000", "subindex": 1, "type": "UNSIGNED16", "iec_location": "%QW10" } ] } ] } ] },
    { "name": "line", "role": "slave", "adapter": { "type": "socketcan", "interface": "line.s", "bitrate": 250000 },
      "slave": { "node_id": 10, "eds": "openplc-slave.eds",
        "objects": [
          { "index": "0x2000", "subindex": 1, "iec_location": "%IW300", "name": "speed" },
          { "index": "0x2001", "subindex": 1, "iec_location": "%IB300", "name": "mode" },
          { "index": "0x2100", "subindex": 1, "iec_location": "%QW300" },
          { "index": "0x2100", "subindex": 2, "iec_location": "%QW301" } ],
        "state_location": "%IB301", "comm_ok_location": "%IX300.0", "sync_count_location": "%IW301",
        "emcy_code_location": "%QW302", "error_register_location": "%QB300" )" + slave_extra + R"( } } ] })";
}

std::unique_ptr<SlaveSim> start_slave_sim(const std::string& json, const std::string& state_dir = "") {
  std::string dir = make_dir(json, {{"openplc-slave.eds", slave_eds()}});
  std::unique_ptr<SlaveSim> sim(new SlaveSim(dir, state_dir));
  CHECK(sim->ok());
  return sim;
}

bool slave_up(SlaveSim& s) { return s.plc().byte_in[301] == 5 && s.plc().bool_in[300][0]; }

}  // namespace

TEST(slave_boot_and_pdos) {
  clear_logs();
  auto sim = start_slave_sim(slave_json());
  if (!sim->ok()) return;
  sim->Sniff("line");
  sim->SetProgram([](fake_runtime::Image& p) {
    p.int_out[300] = static_cast<IEC_UINT>(p.int_in[300] + 1);  // slave: speed + 1 back
    p.int_out[301] = 77;
  });
  sim->Start();
  CHECK(sim->RunUntil([&] { return sim->frames(0x70A) > 0; }, seconds(2)));  // boot-up of node 10
  CHECK(sim->RunUntil([&] { return slave_up(*sim); }, seconds(5)));
  // Master %QW10 -> RPDO -> slave %IW300; program +1 -> %QW300 -> TPDO -> master %IW10.
  sim->plc().int_out[10] = 1234;
  CHECK(sim->RunUntil([&] { return sim->plc().int_in[300] == 1234; }, seconds(2)));
  CHECK(sim->RunUntil([&] { return sim->plc().int_in[10] == 1235 && sim->plc().int_in[11] == 77; }, seconds(2)));
  // The heartbeat comes from the EDS (0x1017 = 500 ms).
  int hb = sim->frames(0x70A);
  sim->RunFor(milliseconds(1100));
  CHECK_MSG(sim->frames(0x70A) - hb >= 2 && sim->frames(0x70A) - hb <= 3, std::to_string(sim->frames(0x70A) - hb));
  CHECK(logged("NMT state OPERATIONAL"));
}

TEST(slave_sdo_to_bound_object_and_remap) {
  auto sim = start_slave_sim(slave_json());
  if (!sim->ok()) return;
  sim->Start();
  CHECK(sim->RunUntil([&] { return slave_up(*sim); }, seconds(5)));
  // 0x2001:1 is in no RPDO the master set: an SDO download still reaches %IB300.
  CHECK(sim->Sdo(0, 10, 0x2001, 1, true, 3, 1) == 0);
  CHECK(sim->RunUntil([&] { return sim->plc().byte_in[300] == 3; }, seconds(1)));
  // The master remapped RPDO 1 to 0x2000:1 alone (its config) and TPDO 1 to 0x2100:1/2.
  uint64_t v = 0;
  CHECK(sim->Sdo(0, 10, 0x1600, 0, false, 0, 0, &v) == 0 && v == 1);
  CHECK(sim->Sdo(0, 10, 0x1A00, 2, false, 0, 0, &v) == 0 && v == 0x21000210u);
  // A write to a read-only object aborts with 0x06010002.
  uint32_t abort = 0;
  CHECK(sim->Sdo(0, 10, 0x1018, 1, true, 5, 4, nullptr, &abort) == CANOPEN_PLC_ERR_ABORT && abort == 0x06010002u);
  // The master never writes a PLC output: %QW300 stays the program's.
  sim->plc().int_out[300] = 42;
  sim->RunFor(milliseconds(50));
  CHECK(sim->Sdo(0, 10, 0x2100, 1, true, 999, 2, nullptr, &abort) != 0);
  CHECK(sim->plc().int_out[300] == 42);
}

TEST(slave_sync_tpdo_and_sync_count) {
  auto sim = start_slave_sim(slave_json("", "", R"(, "sync_period_us": 20000)", R"("transmission": 1,)"));
  if (!sim->ok()) return;
  sim->SetProgram([](fake_runtime::Image& p) { p.int_out[300] = 500; });
  sim->Start();
  CHECK(sim->RunUntil([&] { return slave_up(*sim) && sim->plc().int_in[10] == 500; }, seconds(5)));
  uint16_t c0 = sim->plc().int_in[301];
  sim->RunFor(milliseconds(200));
  CHECK_MSG(sim->plc().int_in[301] - c0 >= 5, std::to_string(sim->plc().int_in[301] - c0));
  sim->SetProgram([](fake_runtime::Image& p) { p.int_out[300] = 600; });
  CHECK(sim->RunUntil([&] { return sim->plc().int_in[10] == 600; }, milliseconds(200)));
}

TEST(slave_nmt_stop_holds_or_zeroes_inputs) {
  for (bool zero : {false, true}) {
    auto sim = start_slave_sim(slave_json("", zero ? R"(, "inputs_on_loss": "zero")" : ""));
    if (!sim->ok()) return;
    sim->Start();
    CHECK(sim->RunUntil([&] { return slave_up(*sim); }, seconds(5)));
    sim->plc().int_out[10] = 321;
    CHECK(sim->RunUntil([&] { return sim->plc().int_in[300] == 321; }, seconds(2)));
    // The other PLC stops the node: NMT stop (0x02) to node 10.
    sim->Send("line", 0x000, {0x02, 10});
    CHECK(sim->RunUntil([&] { return sim->plc().byte_in[301] == 4; }, seconds(1)));
    CHECK(!sim->plc().bool_in[300][0]);
    sim->RunFor(milliseconds(50));
    CHECK_MSG(sim->plc().int_in[300] == (zero ? 0 : 321), std::to_string(sim->plc().int_in[300]));
  }
}

TEST(slave_master_heartbeat_lost) {
  clear_logs();
  // The master makes node 10 watch its heartbeat (0x1016), then disappears.
  auto sim = start_slave_sim(slave_json(R"(, "heartbeat_consumer": true, "heartbeat_ms": 50, "heartbeat_timeout_ms": 150)"));
  if (!sim->ok()) return;
  sim->Start();
  CHECK(sim->RunUntil([&] { return slave_up(*sim); }, seconds(5)));
  sim->Unplug(0);
  CHECK(sim->RunUntil([&] { return !sim->plc().bool_in[300][0]; }, seconds(2)));
  CHECK(logged("lost the heartbeat of node 1"));
}

TEST(slave_emcy_from_program) {
  auto sim = start_slave_sim(slave_json());
  if (!sim->ok()) return;
  sim->Sniff("line");
  sim->Start();
  CHECK(sim->RunUntil([&] { return slave_up(*sim); }, seconds(5)));
  sim->plc().int_out[302] = 0x5000;
  sim->plc().byte_out[300] = 1;
  CHECK(sim->RunUntil([&] { return !sim->frames_of(0x08A).empty(); }, seconds(1)));
  sim->RunFor(milliseconds(100));
  auto e = sim->frames_of(0x08A);
  CHECK_MSG(e.size() == 1, std::to_string(e.size()));
  CHECK(e[0].data[0] == 0x00 && e[0].data[1] == 0x50 && e[0].data[2] == 0x01);
  uint64_t v = 0;
  CHECK(sim->Sdo(0, 10, 0x1001, 0, false, 0, 0, &v) == 0 && v == 1);
  sim->plc().int_out[302] = 0;
  CHECK(sim->RunUntil([&] { return sim->frames_of(0x08A).size() == 2; }, seconds(1)));
  e = sim->frames_of(0x08A);
  CHECK(e[1].data[0] == 0 && e[1].data[1] == 0);
  CHECK(sim->Sdo(0, 10, 0x1001, 0, false, 0, 0, &v) == 0 && v == 0);
}

TEST(slave_store_survives_restart) {
  char tmpl[] = "/tmp/canopen-slave-state-XXXXXX";
  std::string state = mkdtemp(tmpl);
  {
    auto sim = start_slave_sim(slave_json(), state);
    if (!sim->ok()) return;
    sim->Start();
    CHECK(sim->RunUntil([&] { return slave_up(*sim); }, seconds(5)));
    // The master changes TPDO 1's event timer and the configuration date, and saves.
    CHECK(sim->Sdo(0, 10, 0x1800, 5, true, 250, 2) == 0);
    CHECK(sim->Sdo(0, 10, 0x1020, 1, true, 0x1234, 4) == 0);
    CHECK(sim->Sdo(0, 10, 0x1010, 1, true, 0x65766173u, 4) == 0);
    struct stat st;
    CHECK(stat((state + "/line.json").c_str(), &st) == 0);
    // Changed without a save: back to the EDS value at the next start.
    CHECK(sim->Sdo(0, 10, 0x1017, 0, true, 700, 2) == 0);
    // A new PLC start: the saved values come back, the unsaved one does not.
    sim->Restart(1);
    sim->RunFor(milliseconds(300));
    uint64_t v = 0;
    CHECK(sim->Sdo(0, 10, 0x1800, 5, false, 0, 0, &v) == 0 && v == 250);
    CHECK(sim->Sdo(0, 10, 0x1020, 1, false, 0, 0, &v) == 0 && v == 0x1234);
    CHECK(sim->Sdo(0, 10, 0x1017, 0, false, 0, 0, &v) == 0 && v != 700);
    // 0x1011 load drops them.
    CHECK(sim->Sdo(0, 10, 0x1011, 1, true, 0x64616F6Cu, 4) == 0);
    sim->Restart(1);
    sim->RunFor(milliseconds(300));
    CHECK(sim->Sdo(0, 10, 0x1800, 5, false, 0, 0, &v) == 0 && v == 0);
  }
  {
    // Saved again, then the EDS changes: the stored values are not applied.
    auto sim = start_slave_sim(slave_json(), state);
    if (!sim->ok()) return;
    sim->Start();
    CHECK(sim->RunUntil([&] { return slave_up(*sim); }, seconds(5)));
    CHECK(sim->Sdo(0, 10, 0x1800, 5, true, 250, 2) == 0);
    CHECK(sim->Sdo(0, 10, 0x1010, 1, true, 0x65766173u, 4) == 0);
  }
  clear_logs();
  std::string eds = slave_eds();
  eds += "\n";  // another file, another hash
  std::string dir = make_dir(slave_json(), {{"openplc-slave.eds", eds}});
  SlaveSim sim(dir, state);
  CHECK(sim.ok());
  CHECK(logged("were saved with another EDS"));
}

TEST(slave_lss_assigned_node_id) {
  char tmpl[] = "/tmp/canopen-slave-state-XXXXXX";
  std::string state = mkdtemp(tmpl);
  // The other PLC assigns node 12 over LSS and stores it.
  std::string json = slave_json(R"(, "serial_number": 0, "lss": { "assign": true, "store": true })");
  auto replace = [](std::string s, const std::string& a, const std::string& b) {
    for (size_t p; (p = s.find(a)) != std::string::npos;) s.replace(p, a.size(), b);
    return s;
  };
  json = replace(json, R"("node_id": 10, "name")", R"("node_id": 12, "name")");
  json = replace(json, R"("node_id": 10, "eds")", R"("node_id": null, "eds")");
  {
    auto sim = start_slave_sim(json, state);
    if (!sim->ok()) return;
    sim->Sniff("line");
    sim->Start();
    CHECK(sim->RunUntil([&] { return slave_up(*sim); }, seconds(8)));
    CHECK(sim->dev(1).node_id() == 12);
    CHECK(read(state + "/line.json").find("\"lss_node_id\":\t12") != std::string::npos ||
          read(state + "/line.json").find("\"lss_node_id\": 12") != std::string::npos);
  }
  // Without the master's LSS: boots as 12 from the state file.
  json = replace(json, R"(, "serial_number": 0, "lss": { "assign": true, "store": true })", "");
  auto sim = start_slave_sim(json, state);
  if (!sim->ok()) return;
  sim->Start();
  CHECK(sim->RunUntil([&] { return slave_up(*sim); }, seconds(5)));
  CHECK(sim->dev(1).node_id() == 12);
}

TEST(slave_node_id_conflict) {
  clear_logs();
  auto sim = start_slave_sim(slave_json());
  if (!sim->ok()) return;
  sim->Start();
  CHECK(sim->RunUntil([&] { return slave_up(*sim); }, seconds(5)));
  sim->Send("line", 0x70A, {0x05});  // someone else's heartbeat as node 10
  CHECK(sim->RunUntil([&] { return logged("uses node ID 10"); }, seconds(1)));
}

DiagRequest diag_req(const std::string& op, unsigned node = 0, uint16_t index = 0, uint8_t sub = 0) {
  DiagRequest r;
  r.op = op;
  r.node = node;
  r.index = index;
  r.subindex = sub;
  r.peer = "127.0.0.1";
  return r;
}
const cJSON* field(const cJSON* obj, const char* key) { return obj ? cJSON_GetObjectItemCaseSensitive(obj, key) : nullptr; }
double num(const cJSON* obj, const char* key) {
  const cJSON* v = field(obj, key);
  return cJSON_IsNumber(v) ? v->valuedouble : -1;
}
std::string text(const cJSON* obj) {
  if (!obj) return "no answer";
  char* t = cJSON_PrintUnformatted(obj);
  std::string out = t ? t : "";
  cJSON_free(t);
  return out;
}
std::string str(const cJSON* obj, const char* key) {
  const cJSON* v = field(obj, key);
  return cJSON_IsString(v) ? v->valuestring : "";
}

TEST(slave_diag_status_and_local_od) {
  auto sim = start_slave_sim(slave_json());
  if (!sim->ok()) return;
  sim->EnableDiag(1);
  // Before the session: the offline answer has the slave's shape.
  {
    cJSON* off = cJSON_Parse(sim->hub().offline_answer(diag_req("status")).c_str());
    const cJSON* res = field(off, "result");
    CHECK(str(res, "role") == "slave");
    CHECK(num(field(res, "slave"), "node_id") == 10);
    cJSON_Delete(off);
  }
  sim->Start();
  CHECK(sim->RunUntil([&] { return slave_up(*sim); }, seconds(5)));
  sim->plc().int_out[10] = 321;  // the master writes 0x2000:1 over RPDO 1
  CHECK(sim->RunUntil([&] { return sim->plc().int_in[300] == 321; }, seconds(1)));

  cJSON* a = sim->Ask(diag_req("status"));
  const cJSON* res = field(a, "result");
  CHECK(str(res, "role") == "slave");
  const cJSON* sl = field(res, "slave");
  CHECK(num(sl, "node_id") == 10 && num(sl, "state") == 5);
  CHECK(cJSON_IsTrue(field(sl, "comm_ok")));
  const cJSON* tp = field(sl, "tpdos");
  CHECK(cJSON_IsArray(tp) && cJSON_GetArraySize(tp) >= 1);
  const cJSON* first = cJSON_GetArrayItem(tp, 0);
  const cJSON* entries = field(first, "entries");
  CHECK(num(cJSON_GetArrayItem(entries, 0), "index") == 0x2100);
  cJSON_Delete(a);

  // The slave's own dictionary.
  a = sim->Ask(diag_req("sdo_read", 10, 0x2000, 1));
  CHECK_MSG(str(field(a, "result"), "data") == "41 01", text(a));
  cJSON_Delete(a);
  a = sim->Ask(diag_req("sdo_read", 5, 0x1000, 0));  // another node: refused
  CHECK_MSG(text(a).find("is not this slave") != std::string::npos, text(a));
  cJSON_Delete(a);
  DiagRequest w = diag_req("sdo_write", 10, 0x1018, 1);  // read-only identity
  w.data = {1, 0, 0, 0};
  a = sim->Ask(w);
  CHECK_MSG(str(field(a, "result"), "abort_code_hex") == "0x06010002", text(a));
  cJSON_Delete(a);
  // Master-only operations are refused by name.
  a = sim->Ask(diag_req("nmt", 10));
  CHECK_MSG(text(a).find("is a slave network") != std::string::npos, text(a));
  cJSON_Delete(a);
}

// ---------------------------------------------------------------------------
// Gateway: the other PLC ("plc" on top.m) is the upper master; the gateway
// is a slave on top.s and the master of "field" (bus "field") with a
// ping-pong node 2 there. "field" comes first so it is field network 0 for
// the status record, the SDO bridge and forwarded EMCYs; "plc" stands in for
// the other controller and only gets a warning that its status is not published.

namespace {

std::string gateway_json(const std::string& gw_extra = "", const std::string& upper_node_extra = "") {
  return R"({ "schema_version": 2, "networks": [
    { "name": "field", "adapter": { "type": "socketcan", "interface": "field", "bitrate": 125000 },
      "master": { "node_id": 1, "sync_period_us": 10000 },
      "nodes": [ { "node_id": 2, "name": "pingpong", "eds": "cpp-slave.eds", "heartbeat_ms": 50,
        "heartbeat_timeout_ms": 150, "state_location": "%IB40",
        "tx_pdos": [ { "entries": [ { "index": "0x4001", "type": "UNSIGNED32", "iec_location": "%ID40" } ] } ],
        "rx_pdos": [ { "entries": [ { "index": "0x4000", "type": "UNSIGNED32" } ] } ] } ] },
    { "name": "plc", "adapter": { "type": "socketcan", "interface": "top.m", "bitrate": 250000 },
      "master": { "node_id": 1, "heartbeat_ms": 50 },
      "nodes": [ { "node_id": 20, "name": "gateway", "eds": "openplc-gateway.eds" )" + upper_node_extra + R"(,
        "tx_pdos": [ { "number": 1, "entries": [
            { "index": "0x2100", "subindex": 1, "type": "BOOLEAN", "iec_location": "%IX20.0" },
            { "index": "0x2101", "subindex": 1, "type": "UNSIGNED32", "iec_location": "%ID20" } ] },
          { "number": 2, "entries": [
            { "index": "0x5E10", "subindex": 1, "type": "UNSIGNED32", "iec_location": "%ID21" } ] } ],
        "rx_pdos": [ { "number": 1, "entries": [
            { "index": "0x2000", "subindex": 1, "type": "UNSIGNED32", "iec_location": "%QD20" } ] } ] } ] },
    { "name": "top", "role": "slave", "adapter": { "type": "socketcan", "interface": "top.s", "bitrate": 250000 },
      "slave": { "node_id": 20, "eds": "openplc-gateway.eds",
        "objects": [ { "index": "0x2100", "subindex": 1, "iec_location": "%QX300.0" } ],
        "comm_ok_location": "%IX300.1", "emcy_code_location": "%QW300", "error_register_location": "%QB300" } } ],
  "gateway": { "upper": "top",
    "routes": [
      { "slave": { "index": "0x2101", "subindex": 1 },
        "field": { "network": "field", "node": 2, "index": "0x4001", "subindex": 0 }, "name": "pong" },
      { "slave": { "index": "0x2000", "subindex": 1 },
        "field": { "network": "field", "node": 2, "index": "0x4000", "subindex": 0 }, "name": "ping" } ],
    "status": { "index": "0x5E00" }, "emcy_forward": true, "sdo_bridge": true )" + gw_extra + R"( } })";
}

std::unique_ptr<SlaveSim> start_gateway_sim(const std::string& json) {
  std::string dir = make_dir(json, {{"openplc-gateway.eds", gateway_eds()}, {"cpp-slave.eds", pingpong_eds()}});
  std::unique_ptr<SlaveSim> sim(new SlaveSim(dir));
  CHECK(sim->ok());
  return sim;
}

bool gateway_up(SlaveSim& s) { return s.plc().bool_in[300][1] && s.plc().byte_in[40] == 5; }

}  // namespace

TEST(gateway_routes_up_and_down) {
  auto sim = start_gateway_sim(gateway_json());
  if (!sim->ok()) return;
  sim->AddPingPong("field", 2);
  sim->Start();
  CHECK(sim->RunUntil([&] { return gateway_up(*sim); }, seconds(8)));
  // Upper master %QD20 -> gateway 0x2000:1 -> field RPDO 0x4000 -> ping-pong
  // copies it to 0x4001 -> field TPDO -> gateway 0x2101:1 -> upper %ID20.
  sim->plc().dint_out[20] = 4242;
  CHECK(sim->RunUntil([&] { return sim->plc().dint_in[20] == 4242; }, seconds(2)));
  CHECK(sim->plc().dint_in[40] == 4242);  // the field PLC input sees it too
  // Routes keep running while the scan stalls.
  sim->PauseScan(milliseconds(400));
  sim->RunFor(milliseconds(20));
  sim->plc().dint_out[20] = 777;  // the scan is paused: this goes nowhere until it resumes
  uint32_t before = sim->plc().dint_in[20];
  CHECK(before == 4242);
  CHECK(sim->Sdo(1, 20, 0x2000, 1, true, 99, 4) == 0);  // the upper master writes over SDO meanwhile
  CHECK(sim->RunUntil([&] { uint64_t v = 0; return sim->Sdo(1, 20, 0x2101, 1, false, 0, 0, &v) == 0 && v == 99; },
                      milliseconds(300)));
  // The PLC output on the slave side still works.
  sim->RunFor(milliseconds(400));
  sim->plc().bool_out[300][0] = 1;
  CHECK(sim->RunUntil([&] { return sim->plc().bool_in[20][0]; }, seconds(1)));
}

TEST(gateway_status_and_emcy_forwarding) {
  auto sim = start_gateway_sim(gateway_json());
  if (!sim->ok()) return;
  sim->AddPingPong("field", 2);
  sim->Sniff("top");
  sim->Start();
  CHECK(sim->RunUntil([&] { return gateway_up(*sim) && (sim->plc().dint_in[21] & 0x4); }, seconds(8)));
  uint64_t v = 0;
  CHECK(sim->Sdo(1, 20, 0x5E00, 2, false, 0, 0, &v) == 0 && v == 5);
  // A field EMCY goes up with the field network's place and the node ID.
  // (The ping-pong EDS has no EMCY producer, so the test sends node 2's EMCY frame.)
  sim->Send("field", 0x082, {0x00, 0x50, 0x01, 0, 0, 0, 0, 0});
  CHECK(sim->RunUntil([&] { return !sim->frames_of(0x094).empty(); }, seconds(1)));
  auto e = sim->frames_of(0x094);
  if (e.empty()) return;
  CHECK(e[0].data[0] == 0x00 && e[0].data[1] == 0x50 && e[0].data[2] == 0x01);
  CHECK_MSG(e[0].data[3] == 0 && e[0].data[4] == 2, std::to_string(e[0].data[3]) + " " + std::to_string(e[0].data[4]));
  // The program's own EMCY too; 0x1001 is the OR of both.
  sim->plc().int_out[300] = 0x6000;
  sim->plc().byte_out[300] = 0x04;
  CHECK(sim->RunUntil([&] { return sim->frames_of(0x094).size() >= 2; }, seconds(1)));
  CHECK(sim->Sdo(1, 20, 0x1001, 0, false, 0, 0, &v) == 0 && v == 0x05);
  // The field node's error reset clears its entry; the program's stays.
  sim->Send("field", 0x082, {0, 0, 0, 0, 0, 0, 0, 0});
  CHECK(sim->RunUntil([&] { return sim->frames_of(0x094).size() >= 3; }, seconds(1)));
  sim->RunFor(milliseconds(50));
  CHECK(sim->Sdo(1, 20, 0x1001, 0, false, 0, 0, &v) == 0 && (v & 0x04));
  // Node lost: its status goes to 0 and its bit clears.
  sim->Unplug(0);  // the field master loses node 2
  CHECK(sim->RunUntil([&] { return !(sim->plc().dint_in[21] & 0x4); }, seconds(2)));
  CHECK(sim->Sdo(1, 20, 0x5E00, 2, false, 0, 0, &v) == 0 && v == 0);
}

TEST(gateway_sdo_bridge) {
  for (bool allow : {false, true}) {
    auto sim = start_gateway_sim(gateway_json(allow ? R"(, "sdo_bridge_write": true)" : ""));
    if (!sim->ok()) return;
    sim->AddPingPong("field", 2);
    sim->Start();
    CHECK(sim->RunUntil([&] { return gateway_up(*sim); }, seconds(8)));
    // Read node 2's 0x1017 (heartbeat 50 ms set by the field master) on field network 0.
    CHECK(sim->Sdo(1, 20, 0x5F00, 1, true, 0, 1) == 0);
    CHECK(sim->Sdo(1, 20, 0x5F00, 2, true, 2, 1) == 0);
    CHECK(sim->Sdo(1, 20, 0x5F00, 3, true, 0x1017, 2) == 0);
    CHECK(sim->Sdo(1, 20, 0x5F00, 4, true, 0, 1) == 0);
    CHECK(sim->Sdo(1, 20, 0x5F00, 7, true, 1, 1) == 0);
    uint64_t v = 0;
    CHECK(sim->RunUntil([&] { return sim->Sdo(1, 20, 0x5F00, 8, false, 0, 0, &v) == 0 && v == 2; }, seconds(2)));
    CHECK(sim->Sdo(1, 20, 0x5F00, 5, false, 0, 0, &v) == 0 && v == 50);
    CHECK(sim->Sdo(1, 20, 0x5F00, 6, false, 0, 0, &v) == 0 && v == 2);
    // A write: refused without sdo_bridge_write.
    CHECK(sim->Sdo(1, 20, 0x5F00, 3, true, 0x1017, 2) == 0);
    CHECK(sim->Sdo(1, 20, 0x5F00, 5, true, 70, 4) == 0);
    CHECK(sim->Sdo(1, 20, 0x5F00, 6, true, 2, 1) == 0);
    CHECK(sim->Sdo(1, 20, 0x5F00, 7, true, 2, 1) == 0);
    CHECK(sim->RunUntil([&] { return sim->Sdo(1, 20, 0x5F00, 8, false, 0, 0, &v) == 0 && v >= 2; }, seconds(2)));
    if (allow) {
      CHECK(v == 2);
      CHECK(sim->Sdo(2, 2, 0x1017, 0, false, 0, 0, &v) == CANOPEN_PLC_ERR_INPUT);  // a slave network refuses
      CHECK(sim->Sdo(0, 2, 0x1017, 0, false, 0, 0, &v) == 0 && v == 70);
    } else {
      CHECK(v == 3);
      CHECK(sim->Sdo(1, 20, 0x5F00, 9, false, 0, 0, &v) == 0 && v == 0x08000020u);
    }
  }
}

TEST(gateway_upper_loss) {
  for (const char* mode : {"zero", "stop_nodes"}) {
    clear_logs();
    auto sim = start_gateway_sim(
        gateway_json(std::string(R"(, "on_upper_loss": ")") + mode + "\"", R"(, "heartbeat_consumer": true, "heartbeat_ms": 50, "heartbeat_timeout_ms": 150)"));
    if (!sim->ok()) return;
    sim->AddPingPong("field", 2);
    sim->Start();
    CHECK(sim->RunUntil([&] { return gateway_up(*sim); }, seconds(8)));
    sim->plc().dint_out[20] = 55;
    CHECK(sim->RunUntil([&] { return sim->plc().dint_in[40] == 55; }, seconds(2)));
    sim->Unplug(1);  // the upper master is gone
    if (std::string(mode) == "zero") {
      CHECK(sim->RunUntil([&] { return sim->plc().dint_in[40] == 0; }, seconds(2)));
      CHECK(logged("routed outputs set to 0"));
    } else {
      CHECK(sim->RunUntil([&] { return sim->plc().byte_in[40] == 4; }, seconds(2)));
      CHECK(logged("held by the gateway"));
    }
    // Back: the gateway went to PRE-OPERATIONAL (0x1029); the upper master
    // sees that in its heartbeat and starts it again.
    sim->Replug(1);
    CHECK(sim->RunUntil([&] { return sim->plc().byte_in[40] == 5 && sim->plc().dint_in[40] == 55; }, seconds(8)));
  }
}

int main(int argc, char** argv) {
  std::setvbuf(stdout, nullptr, _IOLBF, 0);
  set_log_sink(capture);
  route_lely_diagnostics();
  return check::run_all(argc, argv);
}
