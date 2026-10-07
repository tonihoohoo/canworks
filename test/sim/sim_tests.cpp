// Virtual-bus tests: the plugin's CANopen master (Network) and the Lely C++
// tutorial ping-pong slave run on one Lely event loop over Lely's in-process
// virtual CAN bus, with a fake PLC scan that runs `%QD100 := %ID100 + 1`
// through the same ProcessImage the plugin's cycle hooks use.
//
// This covers bring-up, the PDO round trip, loss, recovery, a slave absent at
// start, a rejected SDO download and a node re-plugged while OPERATIONAL
// without SocketCAN; test/pingpong/run.sh
// runs the same scenario on vcan0 through the real runtime.

// The library's SDO function blocks with the editor's glue
// (test/plc_sdo/bridge.py); first, before headers that define MIN and MAX.
#include "c_blocks.h"

#include <atomic>
#include <chrono>
#include <functional>
#include <cstdio>
#include <fstream>
#include <memory>
#include <map>
#include <mutex>
#include <thread>
#include <sstream>
#include <string>
#include <sys/stat.h>
#include <vector>

#include <lely/co/dev.h>
#include <lely/co/obj.h>
#include <lely/co/val.h>
#include <lely/ev/loop.hpp>
#include <lely/io2/posix/poll.hpp>
#include <lely/io2/sys/io.hpp>
#include <lely/io2/sys/timer.hpp>
#include <lely/io2/vcan.hpp>

#include "cJSON.h"
#include "check.hpp"
#include "config.h"
#include "dcf_gen.h"
#include "diag.h"
#include "eds_check.h"
#include "eds_lint.h"
#include "fake_runtime.hpp"
#include "log.h"
#include "network.h"
#include "cia402_slave.hpp"
#include "pingpong_slave.hpp"
#include "sensor_slave.hpp"
#include "sim_engine.h"
#include "sim_host.h"
#include "plc_api.h"
#ifdef CIA402_PROGRAM
#include "program_host.h"
// The cyclic demo's host: the same interface in namespace program_host_cyclic
// (test/CMakeLists.txt compiles it with the namespaces renamed).
#undef CIA402_PROGRAM_HOST_H
#define program_host program_host_cyclic
#include "program_host.h"
#undef program_host
#endif
#include "process_image.h"


// From <lely/co/lss.h>, which does not mix with the C++ headers.
extern "C" {
typedef int co_lss_store_ind_t(co_lss_t* lss, co_unsigned8_t id, co_unsigned16_t rate, void* data);
void co_lss_set_store_ind(co_lss_t* lss, co_lss_store_ind_t* ind, void* data);
}
constexpr co_unsigned8_t kCsResetComm = 0x82;

using namespace canopen_plugin;
using namespace lely;
using namespace std::chrono;

namespace {

// A ping-pong slave with an extra object 0x4010 that, like the settings of
// many real devices, only takes an SDO download while the node is not
// OPERATIONAL (or never, with `always`). Its EDS (mode_lock_eds) makes it
// wait for the master's NMT start instead of starting itself.
class ModeLockSlave : public PingPongSlave {
 public:
  ModeLockSlave(io::TimerBase& timer, io::CanChannelBase& chan, const std::string& eds, uint8_t id, bool always)
      : PingPongSlave(timer, chan, eds, "", id), always_(always) {
    BasicSlave::OnWrite<uint8_t>(0x4010, 0, [this](uint16_t, uint8_t, uint8_t&, uint8_t) -> std::error_code {
      if (always_ || operational_) return canopen::SdoErrc::NO_WRITE;
      return {};
    });
  }

 protected:
  void OnCommand(canopen::NmtCommand cs) noexcept override {
    operational_ = cs == canopen::NmtCommand::START;
  }

 private:
  bool always_;
  bool operational_ = false;
};

// A ping-pong slave with CiA 302-3 program download objects (firmware_eds):
// the program data written to 0x1F50:1 starts with the new software version
// (UNSIGNED32, little-endian), which the slave then reports in 0x1F56:1.
class FirmwareSlave : public PingPongSlave {
 public:
  FirmwareSlave(io::TimerBase& timer, io::CanChannelBase& chan, const std::string& eds, uint8_t id)
      : PingPongSlave(timer, chan, eds, "", id) {
    BasicSlave::OnWrite<std::vector<uint8_t>>(
        0x1F50, 1, [this](uint16_t, uint8_t, std::vector<uint8_t>& data) -> std::error_code {
          if (data.size() >= 4) {
            uint32_t version = data[0] | data[1] << 8 | data[2] << 16 | uint32_t(data[3]) << 24;
            co_dev_set_val_u32(reinterpret_cast<co_dev_t*>(dev()), 0x1F56, 1, version);
          }
          return {};
        });
  }
};

// A ping-pong slave (mode_lock_eds, so it waits for the master's NMT start)
// that answers late on object 0x4010, like a device that saves a parameter to
// flash before it answers. It blocks its own thread, which delays the SDO
// answer as a slow device does.
class SlowSlave : public PingPongSlave {
 public:
  SlowSlave(io::TimerBase& timer, io::CanChannelBase& chan, const std::string& eds, uint8_t id,
            milliseconds write_delay, milliseconds read_delay)
      : PingPongSlave(timer, chan, eds, "", id) {
    BasicSlave::OnWrite<uint8_t>(0x4010, 0, [write_delay](uint16_t, uint8_t, uint8_t&, uint8_t) -> std::error_code {
      std::this_thread::sleep_for(write_delay);
      return {};
    });
    BasicSlave::OnRead<uint8_t>(0x4010, 0, [read_delay](uint16_t, uint8_t, uint8_t&) -> std::error_code {
      std::this_thread::sleep_for(read_delay);
      return {};
    });
  }

 protected:
  void OnCommand(canopen::NmtCommand) noexcept override {}
};

// A device with a configuration check (config-check.eds, which starts itself
// like the ping-pong slave): a "save" written to 0x1010:1 keeps everything
// written so far (0x1020 included) across NMT resets, as a device's
// non-volatile memory would. The memory and the counters live in a
// StoredConfig that outlives the slave, so a later slave can come up with it.
// Sim::downloads() counts what the master writes.
struct StoredConfig {
  std::vector<uint8_t> saved;           // DCF of 0x1000-0xFFFF at the last save
  std::atomic<int> saves{0};
  std::atomic<bool> refuse_save{false};  // abort the save with 0x08000020
};

class StoringSlave : public PingPongSlave {
 public:
  StoringSlave(io::TimerBase& timer, io::CanChannelBase& chan, const std::string& eds, uint8_t id,
               std::shared_ptr<StoredConfig> mem)
      : PingPongSlave(timer, chan, eds, "", id), mem_(std::move(mem)) {
    BasicSlave::OnWrite<uint32_t>(0x1010, 1, [this](uint16_t, uint8_t, uint32_t& v, uint32_t) -> std::error_code {
      if (v != 0x65766173u) return canopen::SdoErrc::DATA;
      if (mem_->refuse_save) return canopen::SdoErrc::DATA;
      void* dcf = nullptr;
      if (co_dev_write_dcf(reinterpret_cast<co_dev_t*>(dev()), 0x1000, 0xFFFF, &dcf) == -1)
        return canopen::SdoErrc::HARDWARE;
      const uint8_t* p = static_cast<const uint8_t*>(dcf);
      mem_->saved.assign(p, p + co_val_sizeof(CO_DEFTYPE_DOMAIN, &dcf));
      co_val_fini(CO_DEFTYPE_DOMAIN, &dcf);
      ++mem_->saves;
      v = 1;  // reads back as "saves on command"
      return {};
    });
  }

 protected:
  // Lely has just restored the defaults (reset node and reset communication
  // both end here); the saved values come back before the boot-up message.
  void OnCommand(canopen::NmtCommand cs) noexcept override {
    if (cs != canopen::NmtCommand::RESET_COMM || mem_->saved.empty()) return;
    void* dcf = nullptr;
    co_val_make(CO_DEFTYPE_DOMAIN, &dcf, mem_->saved.data(), mem_->saved.size());
    co_dev_read_dcf(reinterpret_cast<co_dev_t*>(dev()), nullptr, nullptr, &dcf);
    co_val_fini(CO_DEFTYPE_DOMAIN, &dcf);
  }

 private:
  std::shared_ptr<StoredConfig> mem_;
};

// A CiA 402 drive played from its EDS (test/fixtures/eds/drives/),
// with the storage of StoringSlave: the controlword it receives (0x6040)
// comes back as its statusword (0x6041) and, times 1000, as its position
// (0x6064, when the EDS has it). Values that arrive in 0x2301:1/2 are kept
// for the test to read.
class VendorDriveSlave : public StoringSlave {
 public:
  VendorDriveSlave(io::TimerBase& timer, io::CanChannelBase& chan, const std::string& eds, uint8_t id,
                   std::shared_ptr<StoredConfig> mem, bool has_position)
      : StoringSlave(timer, chan, eds, id, std::move(mem)), has_position_(has_position) {}
  std::atomic<int> command{-1};       // last 0x2301:1
  std::atomic<int64_t> argument{-1};  // last 0x2301:2

  // A value in the device's own object dictionary. Call from its thread.
  template <class T>
  T Get(uint16_t idx, uint8_t subidx) {
    return (*this)[idx][subidx].template Get<T>();
  }

 protected:
  void OnWrite(uint16_t idx, uint8_t subidx) noexcept override {
    if (idx == 0x6040 && subidx == 0) {
      uint16_t cw = (*this)[0x6040][0];
      (*this)[0x6041][0] = cw;
      SetEvent(0x6041, 0);
      if (has_position_) {
        (*this)[0x6064][0] = static_cast<int32_t>(cw) * 1000;
        SetEvent(0x6064, 0);
      }
    } else if (idx == 0x2301 && subidx == 1) {
      command = static_cast<uint8_t>((*this)[0x2301][1]);
    } else if (idx == 0x2301 && subidx == 2) {
      argument = static_cast<int32_t>((*this)[0x2301][2]);
    }
  }

 private:
  bool has_position_;
};

// The log is written from every thread that runs a Lely device (the slaves'
// diagnostics go through the same sink), so all access takes this lock.
// A device for PLC-cycle SYNC timing: its TPDO 1 (0x4001, type 1) carries a
// counter it increments after every SYNC, and it keeps the output values
// that arrive in 0x4000 (RPDO 1, type 1) in the order it applies them.
class SyncCounterSlave : public lely::canopen::BasicSlave {
 public:
  using BasicSlave::BasicSlave;
  std::atomic<uint32_t> syncs{0};
  std::mutex mutex;
  std::vector<uint32_t> applied;  // 0x4000 at each SYNC

  // Stops (or resumes) TPDO 1, as a device that misses its SYNC would.
  void Mute(bool mute) {
    co_unsigned32_t cob = mute ? 0x80000182u : 0x182u;
    co_sub_t* sub = co_dev_find_sub(reinterpret_cast<co_dev_t*>(dev()), 0x1800, 1);
    co_sub_dn_ind_val(sub, CO_DEFTYPE_UNSIGNED32, &cob);  // through the PDO service
  }

 protected:
  void OnSync(uint8_t, const time_point&) noexcept override {
    (*this)[0x4001][0] = static_cast<uint32_t>(++syncs);
    std::lock_guard<std::mutex> lock(mutex);
    applied.push_back((*this)[0x4000][0]);
  }
};

std::mutex& log_mutex() {
  static std::mutex m;
  return m;
}

std::vector<std::string>& log_store() {
  static std::vector<std::string> l;
  return l;
}

// A copy of the log so far.
std::vector<std::string> logs() {
  std::lock_guard<std::mutex> lock(log_mutex());
  return log_store();
}

void clear_logs() {
  std::lock_guard<std::mutex> lock(log_mutex());
  log_store().clear();
}

void capture(LogLevel level, const char* msg) {
  {
    std::lock_guard<std::mutex> lock(log_mutex());
    log_store().push_back(msg);
  }
  if (std::getenv("SIM_VERBOSE")) std::printf("    log: %s\n", msg);
}

bool logged(const std::string& needle) {
  for (const auto& l : logs())
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
  char tmpl[] = "/tmp/canopen-sim-XXXXXX";
  std::string dir = mkdtemp(tmpl);
  for (const auto& f : files) std::ofstream(dir + "/" + f.first) << f.second;
  std::ofstream(dir + "/canopen_config.json") << json;
  return dir;
}

std::string pingpong_json(const std::string& extra_nodes = "") {
  return R"({
  "schema_version": 1,
  "adapter": { "type": "socketcan", "interface": "sim", "bitrate": 125000 },
  "master": { "node_id": 1, "sync_period_us": 20000 },
  "nodes": [
    {
      "node_id": 2, "name": "pingpong", "eds": "cpp-slave.eds",
      "heartbeat_ms": 50, "heartbeat_timeout_ms": 200,
      "status_location": "%IX10.0",
      "tx_pdos": [ { "entries": [ { "index": "0x4001", "type": "UNSIGNED32", "iec_location": "%ID100" } ] } ],
      "rx_pdos": [ { "entries": [ { "index": "0x4000", "type": "UNSIGNED32", "iec_location": "%QD100" } ] } ]
    })" + extra_nodes + R"(
  ]
})";
}

// What an LSS device keeps across power cycles: the node ID it stored with
// LSS "store configuration" (0xFF: none), and how often it stored.
struct LssMemory {
  std::atomic<int> stored_id{0xFF};
  std::atomic<int> stores{0};
};

// A ping-pong slave that is also an LSS slave (its EDS says LSS_Supported=1)
// and starts with the node ID it stored, 0xFF when none. Lely's LSS slave
// needs a communication reset to use a node ID it got while it had none;
// CiA 305 devices start with it when switched to the LSS waiting state,
// which ApplyPendingId() plays (SlaveBox::WatchLss calls it).
class LssSlave : public PingPongSlave {
 public:
  LssSlave(io::TimerBase& timer, io::CanChannelBase& chan, const std::string& eds, std::shared_ptr<LssMemory> mem)
      : PingPongSlave(timer, chan, eds, "", static_cast<uint8_t>(mem->stored_id.load())), mem_(std::move(mem)) {}

  void ApplyPendingId() {
    std::lock_guard<util::BasicLockable> lock(*this);
    auto* n = reinterpret_cast<co_nmt_t*>(nmt());
    if (co_dev_get_id(reinterpret_cast<co_dev_t*>(dev())) == 0xFF && co_nmt_get_id(n) != 0xFF)
      co_nmt_cs_ind(n, kCsResetComm);
  }

 protected:
  void OnCommand(canopen::NmtCommand) noexcept override {
    co_lss_t* lss = co_nmt_get_lss(reinterpret_cast<co_nmt_t*>(nmt()));
    if (lss) co_lss_set_store_ind(lss, &Store, this);
  }

 private:
  static int Store(co_lss_t*, co_unsigned8_t id, co_unsigned16_t, void* data) {
    auto* self = static_cast<LssSlave*>(data);
    self->mem_->stored_id = id;
    ++self->mem_->stores;
    return 0;
  }

  std::shared_ptr<LssMemory> mem_;
};

// The EDS of an LSS slave with this serial number (and revision).
std::string lss_eds(uint32_t serial, uint32_t revision = 0) {
  std::string eds = read(std::string(FIXTURES_DIR) + "/eds/lss-slave.eds");
  auto set = [&eds](const std::string& section, uint32_t v) {
    size_t at = eds.find("DefaultValue=", eds.find(section));
    size_t end = eds.find('\n', at);
    char buf[32];
    std::snprintf(buf, sizeof buf, "DefaultValue=0x%08X", v);
    eds.replace(at, end - at, buf);
  };
  set("[1018sub4]", serial);
  set("[1018sub3]", revision);
  return eds;
}

// The fixed-mapping I/O module of test/fixtures/eds/fixed-io.eds: whatever
// arrives in output 0x6200:1 comes back in input 0x6000:1, and plus 100 in
// 0x6000:2. Its PDO mapping and COB-IDs are read-only, so Lely's SDO server
// aborts any write to them, as a real fixed device does.
class FixedIoSlave : public lely::canopen::BasicSlave {
 public:
  using BasicSlave::BasicSlave;
  std::atomic<int> out2{-1};  // last value of 0x6200:2

 protected:
  void OnWrite(uint16_t idx, uint8_t subidx) noexcept override {
    if (idx != 0x6200) return;
    uint8_t v = (*this)[idx][subidx];
    if (subidx == 1) {
      (*this)[0x6000][1] = v;
      (*this)[0x6000][2] = static_cast<uint8_t>(v + 100);
    } else if (subidx == 2) {
      out2 = v;
    }
  }
};

// One virtual CAN bus with the master and any number of slaves, plus a fake
// PLC scanning every 10 ms.
class Sim {
 public:
  // `base_tick_us`: the runtime's base tick, as the plugin gives it to
  // resolve_interpolation_periods (0: not called).
  explicit Sim(const std::string& dir, unsigned long long base_tick_us = 0)
      : poll_(ctx_), loop_(poll_.get_poll()), exec_(loop_.get_executor()),
        timer_(poll_, exec_, CLOCK_MONOTONIC), sup_timer_(poll_, exec_, CLOCK_MONOTONIC),
        req_timer_(poll_, exec_, CLOCK_MONOTONIC), out_timer_(poll_, exec_, CLOCK_MONOTONIC),
        scan_timer_(poll_, exec_, CLOCK_MONOTONIC),
        ctrl_(timer_.get_clock()),
        chan_(ctx_, exec_) {
    std::vector<std::string> errors;
    // As the plugin's start: config, EDS lint (prepared copies), EDS checks, dcfgen.
    ok_ = load_config(dir + "/canopen_config.json", ImageLimits(), cfg_, errors) &&
          run_eds_lint(cfg_, default_edslint_python(), cfg_.config_dir + "/.canopen", errors) &&
          check_eds_files(cfg_, errors);
    if (ok_ && base_tick_us) resolve_interpolation_periods(cfg_, base_tick_us);
    ok_ = ok_ && generate_device_config(cfg_, default_dcfgen(), gen_, errors);
    for (const auto& w : cfg_.warnings) log_warn("%s", w.c_str());
    for (const auto& e : errors) {
      std::printf("  setup: %s\n", e.c_str());
      log_error("%s", e.c_str());
    }
    if (!ok_) return;
    image_.build(cfg_);
    fake_runtime::attach(fake_, rt_);
    chan_.open(ctrl_);
    net_.reset(new Network(exec_, timer_, sup_timer_, chan_, cfg_, gen_, image_, nullptr, &req_timer_, &out_timer_));
    sync_wake_.reset(new SyncWake(poll_, image_.sync_fd(), *net_));
    sniff_.open(ctrl_);
    Sniff();
    scan_timer_.settime(milliseconds(10), milliseconds(10));
    scan_timer_.submit_wait(exec_, [this](int, std::error_code ec) {
      if (!ec) Scan();
    });
  }

  ~Sim() {
    if (hub_) hub_->detach();
    slaves_.clear();
    simulator_.reset();
    if (net_) net_->Stop();
    sync_wake_.reset();
    ctx_.shutdown();
    loop_.restart();
    // As the plugin's session end (bus.cpp): the shutdown normally drains the
    // loop, but a pending operation can keep it waiting forever, so wait in
    // slices and then stop it.
    for (int i = 0; i < 20 && !loop_.stopped(); ++i) loop_.run_for(milliseconds(100));
    if (!loop_.stopped()) {
      std::printf("  teardown: the loop did not drain after shutdown\n");
      loop_.stop();
    }
    net_.reset();
  }

  bool ok() const { return ok_; }
  Network& net() { return *net_; }
  std::string gen_master_dcf() const { return gen_.master_dcf; }
  const Config& cfg() const { return cfg_; }

  // Serves the diagnostics channel through a hub (call before Start()).
  void EnableDiag() {
    hub_.reset(new DiagHub(cfg_, "sim"));
    net_->SetDiag(hub_.get());
    hub_->attach();
  }
  DiagHub& hub() { return *hub_; }

  // Sends a diagnostics request and runs the loop until its answer arrives;
  // returns the parsed answer line (cJSON_Delete it), or null on timeout.
  // The answer line exactly as the server would send it.
  std::string AskLine(DiagRequest r, milliseconds timeout = milliseconds(5000)) {
    uint64_t seq = hub_->submit(std::move(r));
    std::string line;
    RunUntil([&] {
      std::vector<std::pair<uint64_t, std::string>> got;
      hub_->take_answers(got);
      for (auto& a : got)
        if (a.first == seq) line = a.second;
      return !line.empty();
    }, timeout);
    return line;
  }

  cJSON* Ask(DiagRequest r, milliseconds timeout = milliseconds(5000)) {
    uint64_t seq = hub_->submit(std::move(r));
    std::string line;
    RunUntil([&] {
      std::vector<std::pair<uint64_t, std::string>> got;
      hub_->take_answers(got);
      for (auto& a : got)
        if (a.first == seq) line = a.second;
      return !line.empty();
    }, timeout);
    return line.empty() ? nullptr : cJSON_Parse(line.c_str());
  }
  fake_runtime::Image& plc() { return fake_; }
  ev::Executor& exec() { return exec_; }

  // A slave runs on its own thread and event loop, as a separate device would.
  class SlaveBox {
   public:
    using Make = std::function<canopen::BasicSlave*(io::TimerBase&, io::CanChannelBase&)>;
    SlaveBox(io::VirtualCanController& ctrl, Make make, std::function<void(canopen::BasicSlave&)> started = {})
        : poll_(ctx_), loop_(poll_.get_poll()), exec_(loop_.get_executor()),
          timer_(poll_, exec_, CLOCK_MONOTONIC), chan_(ctx_, exec_) {
      chan_.open(ctrl);
      slave_.reset(make(timer_, chan_));
      thread_ = std::thread([this, started] {
        slave_->Reset();
        if (started) started(*slave_);
        loop_.run();  // returns once ctx_.shutdown() has cancelled all work
      });
    }
    // Takes the slave off the bus and puts it back, as a pulled and
    // re-plugged cable would: the slave keeps running and keeps its state.
    void Unplug() {
      exec_.post([this] { chan_.close(); });
    }
    void Replug(io::VirtualCanController& ctrl) {
      exec_.post([this, &ctrl] { chan_.open(ctrl); });
    }
    // Runs f(slave) on the slave's own thread.
    void Post(std::function<void(canopen::BasicSlave&)> f) {
      exec_.post([this, f] { f(*slave_); });
    }
    // For an LssSlave: after each LSS "switch state global waiting" it
    // starts with a node ID it got while it had none (see LssSlave).
    void WatchLss(io::VirtualCanController& ctrl) {
      lss_sniff_.open(ctrl);
      ReadLss();
    }
    ~SlaveBox() {
      ctx_.shutdown();
      thread_.join();
      slave_.reset();
    }

   private:
    void ReadLss() {
      lss_sniff_.submit_read(&lss_msg_, nullptr, nullptr, exec_, [this](int result, std::error_code ec) {
        if (ec) return;
        if (result == 1 && lss_msg_.id == 0x7E5 && lss_msg_.len >= 2 && lss_msg_.data[0] == 0x04 &&
            lss_msg_.data[1] == 0x00)
          exec_.post([this] { static_cast<LssSlave&>(*slave_).ApplyPendingId(); });
        ReadLss();
      });
    }

    io::Context ctx_;
    io::Poll poll_;
    ev::Loop loop_;
    ev::Executor exec_;
    io::Timer timer_;
    io::VirtualCanChannel chan_;
    io::VirtualCanChannel lss_sniff_{ctx_, exec_};
    can_msg lss_msg_ = CAN_MSG_INIT;
    std::unique_ptr<canopen::BasicSlave> slave_;
    std::thread thread_;
  };

  void StartSlave(uint8_t id, const std::string& eds) {
    slaves_[id].reset(new SlaveBox(ctrl_, [=](io::TimerBase& t, io::CanChannelBase& c) {
      return new PingPongSlave(t, c, eds, "", id);
    }));
  }

  // An LSS slave (see LssSlave); `key` only names it in the test.
  void StartLssSlave(uint8_t key, const std::string& eds, std::shared_ptr<LssMemory> mem) {
    slaves_[key].reset(new SlaveBox(ctrl_, [=](io::TimerBase& t, io::CanChannelBase& c) {
      return new LssSlave(t, c, eds, mem);
    }));
    slaves_[key]->WatchLss(ctrl_);
  }

  void StartModeLockSlave(uint8_t id, const std::string& eds, bool always) {
    slaves_[id].reset(new SlaveBox(ctrl_, [=](io::TimerBase& t, io::CanChannelBase& c) {
      return new ModeLockSlave(t, c, eds, id, always);
    }));
  }

  void StartSlowSlave(uint8_t id, const std::string& eds, milliseconds write_delay, milliseconds read_delay) {
    slaves_[id].reset(new SlaveBox(ctrl_, [=](io::TimerBase& t, io::CanChannelBase& c) {
      return new SlowSlave(t, c, eds, id, write_delay, read_delay);
    }));
  }

  void StartStoringSlave(uint8_t id, const std::string& eds, std::shared_ptr<StoredConfig> mem) {
    slaves_[id].reset(new SlaveBox(ctrl_, [=](io::TimerBase& t, io::CanChannelBase& c) {
      return new StoringSlave(t, c, eds, id, mem);
    }));
  }

  VendorDriveSlave* StartVendorDrive(uint8_t id, const std::string& eds, std::shared_ptr<StoredConfig> mem,
                                     bool has_position) {
    VendorDriveSlave* made = nullptr;
    slaves_[id].reset(new SlaveBox(ctrl_, [=, &made](io::TimerBase& t, io::CanChannelBase& c) {
      return made = new VendorDriveSlave(t, c, eds, id, mem, has_position);
    }));
    return made;
  }

  // A CiA 402 drive (test/drive/cia402_slave.hpp), moving on its own thread.
  Cia402Slave* StartCia402Drive(uint8_t id, const std::string& eds) {
    Cia402Slave* made = nullptr;
    slaves_[id].reset(new SlaveBox(
        ctrl_, [=, &made](io::TimerBase& t, io::CanChannelBase& c) { return made = new Cia402Slave(t, c, eds, id); },
        [](canopen::BasicSlave& s) { static_cast<Cia402Slave&>(s).Start(); }));
    return made;
  }

  // Runs f(slave) on the slave's own thread.
  void OnSlave(uint8_t id, std::function<void(canopen::BasicSlave&)> f) { slaves_.at(id)->Post(f); }

  void StartFirmwareSlave(uint8_t id, const std::string& eds) {
    slaves_[id].reset(new SlaveBox(ctrl_, [=](io::TimerBase& t, io::CanChannelBase& c) {
      return new FirmwareSlave(t, c, eds, id);
    }));
  }

  SyncCounterSlave* StartSyncCounterSlave(uint8_t id, const std::string& eds) {
    SyncCounterSlave* made = nullptr;
    slaves_[id].reset(new SlaveBox(ctrl_, [=, &made](io::TimerBase& t, io::CanChannelBase& c) {
      return made = new SyncCounterSlave(t, c, eds, "", id);
    }));
    return made;
  }

  // Extra SYNC requests as if the bus thread had missed frames.
  void RequestSync(int n) {
    for (int i = 0; i < n; ++i) image_.request_sync();
  }
  // SYNC frames seen: arrival time and counter byte (-1 without one).
  struct SyncFrame {
    steady_clock::time_point at;
    int cnt;
  };
  std::vector<SyncFrame> sync_frames() const { return sync_frames_; }

  FixedIoSlave* StartFixedIoSlave(uint8_t id, const std::string& eds) {
    FixedIoSlave* made = nullptr;
    slaves_[id].reset(new SlaveBox(ctrl_, [=, &made](io::TimerBase& t, io::CanChannelBase& c) {
      return made = new FixedIoSlave(t, c, eds, "", id);
    }));
    return made;
  }

  void Unplug(uint8_t id) { slaves_[id]->Unplug(); }
  void Replug(uint8_t id) { slaves_[id]->Replug(ctrl_); }

  // A measuring device driven by its EDS, with moving signals.
  void StartSensor(uint8_t id, const std::string& eds, std::vector<SensorSignal> signals) {
    slaves_[id].reset(new SlaveBox(
        ctrl_,
        [=](io::TimerBase& t, io::CanChannelBase& c) {
          return new SensorSlave(t, c, eds, id, signals, milliseconds(20));
        },
        [](canopen::BasicSlave& s) { static_cast<SensorSlave&>(s).StartSignals(); }));
  }

  // Runs f on the sensor's own thread (see StartSensor).
  void OnSensor(uint8_t id, std::function<void(SensorSlave&)> f) {
    slaves_.at(id)->Post([f](canopen::BasicSlave& s) { f(static_cast<SensorSlave&>(s)); });
  }

  // The slave disappears from the bus (power loss).
  void KillSlave(uint8_t id) { slaves_.erase(id); }

  // Runs the loop until pred() holds or the timeout passes.
  template <class F>
  bool RunUntil(F pred, milliseconds timeout) {
    auto end = steady_clock::now() + timeout;
    while (steady_clock::now() < end) {
      loop_.run_for(milliseconds(5));
      loop_.restart();
      if (pred()) return true;
    }
    return pred();
  }

  void RunFor(milliseconds d) {
    RunUntil([] { return false; }, d);
  }

  // The PLC stops (no scans, so no PLC-cycle SYNC) and starts again.
  void StopPlc(bool stop) { plc_stopped_ = stop; }

  // Replaces the PLC program (default: %QD100 := %ID100 + 1).
  void SetProgram(std::function<void(fake_runtime::Image&)> program) { program_ = std::move(program); }

  // SDO download requests (initiate) seen on the bus for a node so far.
  int downloads(uint8_t id) { return downloads_[id]; }
  // ... of them to a PDO parameter or mapping object (0x1400-0x1BFF).
  int pdo_downloads(uint8_t id) { return pdo_downloads_[id]; }

  // LSS requests the master sent with this command specifier (0x7E5).
  int lss(uint8_t cs) { return lss_cs_[cs]; }
  // Frames seen on a COB-ID.
  int frames(uint32_t id) { return frames_[id]; }
  int lss_total() {
    int n = 0;
    for (const auto& c : lss_cs_) n += c.second;
    return n;
  }
  // Boot-up messages seen from a node ID, and NMT commands sent to it (0 =
  // to all nodes) with command specifier `cs`.
  int bootups(uint8_t id) { return bootups_[id]; }
  // 6-byte frames seen on COB-ID 0x100 or 0x180 (TIME), with when they came.
  struct Stamped {
    std::chrono::steady_clock::time_point at;
    can_msg msg;
  };
  std::vector<Stamped> time_frames(uint32_t id) {
    std::vector<Stamped> out;
    for (const auto& f : time_frames_)
      if (f.msg.id == id) out.push_back(f);
    return out;
  }
  int nmt(uint8_t id, uint8_t cs) { return nmt_[id * 256 + cs]; }

  // Simulated devices (canopen_sim) on this bus. `specs` default to every
  // node of the config.
  bool StartSimulator(const std::string& sim_json, std::vector<canopen_sim::DeviceSpec> specs = {},
                      canopen_sim::SimOptions opt = canopen_sim::SimOptions()) {
    canopen_sim::SimFile file;
    std::vector<std::string> errors;
    if (!sim_json.empty() && !canopen_sim::parse_sim_file(sim_json, cfg_.config_dir + "/simulation.json", file, errors)) {
      for (const auto& e : errors) std::printf("  simulation file: %s\n", e.c_str());
      return false;
    }
    if (specs.empty()) {
      for (const auto& n : cfg_.nodes) {
        canopen_sim::DeviceSpec d;
        d.node = n.node_id;
        d.name = n.name;
        d.eds_path = n.eds_path;
        specs.push_back(d);
      }
    }
    opt.simulated_network = true;
    sim_host_.reset(new canopen_sim::LoopHost(ctx_, poll_, exec_, ctrl_, [](canopen_sim::Host::Level l, const std::string& m) {
      if (l == canopen_sim::Host::Level::Info) log_info("sim: %s", m.c_str());
      else if (l == canopen_sim::Host::Level::Warn) log_warn("sim: %s", m.c_str());
      else log_error("sim: %s", m.c_str());
    }));
    simulator_.reset(new canopen_sim::Simulator(*sim_host_, specs, file, opt));
    simulator_->on_scenario_end = [this](const canopen_sim::ScenarioResult& r) { results_.push_back(r); };
    errors.clear();
    bool ok = simulator_->Start(errors);
    for (const auto& e : errors) std::printf("  simulator: %s\n", e.c_str());
    return ok;
  }
  canopen_sim::Simulator& simulator() { return *simulator_; }
  const std::vector<canopen_sim::ScenarioResult>& scenario_results() const { return results_; }
  // A control request to the simulator; the parsed answer (cJSON_Delete it).
  // Routes sim_ diagnostics requests to the simulator, as bus.cpp does.
  void WireSimHandler() {
    net().SetSimHandler([this](const cJSON* req, const std::string& id, const std::string& peer) {
      return simulator_->Handle(req, id, peer);
    });
  }

  cJSON* SimAsk(const std::string& json) {
    cJSON* req = cJSON_Parse(json.c_str());
    std::string line = simulator_->Handle(req, "", "test");
    cJSON_Delete(req);
    return cJSON_Parse(line.c_str());
  }

  bool status() { return fake_.bool_in[10][0] != 0; }
  uint8_t state() { return static_cast<uint8_t>(fake_.byte_in[20]); }
  uint32_t in() { return fake_.dint_in[100]; }
  int16_t iw(int i) { return static_cast<int16_t>(fake_.int_in[i]); }
  uint16_t uw(int i) { return static_cast<uint16_t>(fake_.int_in[i]); }
  uint8_t ib(int i) { return static_cast<uint8_t>(fake_.byte_in[i]); }
  long scans() const { return scans_; }

 private:
  void Sniff() {
    sniff_.submit_read(&sniff_msg_, nullptr, nullptr, exec_, [this](int result, std::error_code ec) {
      if (ec) return;
      const can_msg& m = sniff_msg_;
      if (result == 1 && m.id > 0x600 && m.id < 0x680 && m.len == 8 && (m.data[0] & 0xE0) == 0x20) {
        ++downloads_[static_cast<uint8_t>(m.id - 0x600)];
        uint16_t idx = m.data[1] | m.data[2] << 8;
        if (idx >= 0x1400 && idx < 0x1C00) ++pdo_downloads_[static_cast<uint8_t>(m.id - 0x600)];
      }
      if (result == 1) ++frames_[m.id];
      if (result == 1 && m.id == 0x080) sync_frames_.push_back({steady_clock::now(), m.len ? m.data[0] : -1});
      if (result == 1 && m.id == 0x7E5 && m.len >= 1) ++lss_cs_[m.data[0]];
      if (result == 1 && m.id > 0x700 && m.id < 0x780 && m.len == 1 && m.data[0] == 0)
        ++bootups_[static_cast<uint8_t>(m.id - 0x700)];
      if (result == 1 && m.id == 0 && m.len == 2) ++nmt_[m.data[1] * 256 + m.data[0]];
      if (result == 1 && (m.id == 0x100 || m.id == 0x180)) time_frames_.push_back({std::chrono::steady_clock::now(), m});
      Sniff();
    });
  }

  void Scan() {
    if (plc_stopped_) {
      scan_timer_.submit_wait(exec_, [this](int, std::error_code ec) {
        if (!ec) Scan();
      });
      return;
    }
    // cycle_start (with its PLC-cycle SYNC request), program, cycle_end
    image_.copy_to_plc(rt_);
    image_.request_sync();
    if (program_)
      program_(fake_);
    else
      fake_.dint_out[100] = fake_.dint_in[100] + 1;
    image_.copy_from_plc(rt_);
    ++scans_;
    scan_timer_.submit_wait(exec_, [this](int, std::error_code ec) {
      if (!ec) Scan();
    });
  }

  io::IoGuard io_guard_;
  io::Context ctx_;
  io::Poll poll_;
  ev::Loop loop_;
  ev::Executor exec_;
  io::Timer timer_;
  io::Timer sup_timer_;
  io::Timer req_timer_;
  io::Timer out_timer_;
  io::Timer scan_timer_;
  io::VirtualCanController ctrl_;
  io::VirtualCanChannel chan_;
  io::VirtualCanChannel sniff_{ctx_, exec_};
  can_msg sniff_msg_ = CAN_MSG_INIT;
  std::map<uint8_t, int> downloads_;
  std::map<uint8_t, int> pdo_downloads_;
  std::map<uint8_t, int> lss_cs_;
  std::map<uint32_t, int> frames_;
  std::map<uint8_t, int> bootups_;
  std::map<int, int> nmt_;
  std::vector<Stamped> time_frames_;
  std::vector<SyncFrame> sync_frames_;
  std::map<uint8_t, std::unique_ptr<SlaveBox>> slaves_;
  std::unique_ptr<canopen_sim::LoopHost> sim_host_;
  std::unique_ptr<canopen_sim::Simulator> simulator_;
  std::vector<canopen_sim::ScenarioResult> results_;
  Config cfg_;
  GeneratedConfig gen_;
  ProcessImage image_;
  fake_runtime::Image fake_;
  plugin_runtime_args_t rt_;
  std::unique_ptr<Network> net_;
  std::unique_ptr<SyncWake> sync_wake_;
  std::unique_ptr<DiagHub> hub_;
  std::function<void(fake_runtime::Image&)> program_;
  bool plc_stopped_ = false;
  bool ok_ = false;
  long scans_ = 0;
};

std::string slave_eds() { return read(std::string(PINGPONG_DIR) + "/cpp-slave.eds"); }

}  // namespace

TEST(sim_pingpong_round_trip) {
  clear_logs();
  std::string dir = make_dir(pingpong_json(), {{"cpp-slave.eds", slave_eds()}});
  static Sim* sim;
  sim = new Sim(dir);
  CHECK(sim->ok());
  if (!sim->ok()) return;
  sim->StartSlave(2, dir + "/cpp-slave.eds");
  sim->net().Start();
  CHECK(sim->RunUntil([] { return sim->status(); }, seconds(5)));
  CHECK(logged("configuring"));
  CHECK(logged("node 2 (pingpong) is operational"));
  uint32_t a = sim->in();
  CHECK(sim->RunUntil([&] { return sim->in() >= a + 10; }, seconds(5)));
  uint32_t b = sim->in();
  sim->RunFor(milliseconds(500));
  CHECK_MSG(sim->in() > b, "counter " + std::to_string(b) + " -> " + std::to_string(sim->in()));
  std::printf("    counter went %u -> %u\n", a, sim->in());
  delete sim;
}

TEST(sim_slave_lost_and_recovered) {
  clear_logs();
  std::string dir = make_dir(pingpong_json(), {{"cpp-slave.eds", slave_eds()}});
  static Sim* sim;
  sim = new Sim(dir);
  if (!sim->ok()) {
    CHECK(sim->ok());
    return;
  }
  sim->StartSlave(2, dir + "/cpp-slave.eds");
  sim->net().Start();
  CHECK(sim->RunUntil([] { return sim->status() && sim->in() > 5; }, seconds(5)));

  // Lost: heartbeat timeout (200 ms) clears the status bit, the input holds,
  // the PLC keeps scanning.
  sim->KillSlave(2);
  auto t0 = steady_clock::now();
  CHECK(sim->RunUntil([] { return !sim->status(); }, seconds(2)));
  auto detect = duration_cast<milliseconds>(steady_clock::now() - t0).count();
  std::printf("    loss detected after %lld ms\n", (long long)detect);
  CHECK(detect <= 400);
  CHECK(logged("node 2 (pingpong) lost: no heartbeat within 200 ms"));
  uint32_t held = sim->in();
  long scans = sim->scans();
  sim->RunFor(milliseconds(500));
  CHECK(sim->in() == held);
  CHECK(sim->scans() > scans + 20);

  // Recovered: the slave comes back, is reconfigured over SDO and runs again.
  size_t cfg_logs = 0;
  for (const auto& l : logs()) cfg_logs += l.find("configuring") != std::string::npos;
  sim->StartSlave(2, dir + "/cpp-slave.eds");
  CHECK(sim->RunUntil([] { return sim->status(); }, seconds(20)));
  size_t cfg_logs2 = 0;
  for (const auto& l : logs()) cfg_logs2 += l.find("configuring") != std::string::npos;
  CHECK(cfg_logs2 > cfg_logs);
  uint32_t c = sim->in();
  CHECK(sim->RunUntil([&] { return sim->in() > c + 5; }, seconds(5)));
  delete sim;
}

TEST(sim_node_state_byte) {
  clear_logs();
  std::string json = pingpong_json();
  size_t at = json.find("\"status_location\": \"%IX10.0\",");
  json.insert(at, "\"state_location\": \"%IB20\", ");
  std::string dir = make_dir(json, {{"cpp-slave.eds", slave_eds()}});
  static Sim* sim;
  sim = new Sim(dir);
  if (!sim->ok()) {
    CHECK(sim->ok());
    return;
  }
  // Nothing heard yet: 0.
  sim->net().Start();
  sim->RunFor(milliseconds(200));
  CHECK(sim->state() == 0);
  // Booted and started: OPERATIONAL (5).
  sim->StartSlave(2, dir + "/cpp-slave.eds");
  CHECK(sim->RunUntil([] { return sim->state() == 5 && sim->status(); }, seconds(20)));
  // The master stops the node: its heartbeat reports STOPPED (4).
  sim->net().Command(canopen::NmtCommand::STOP, 2);
  CHECK_MSG(sim->RunUntil([] { return sim->state() == 4; }, seconds(2)), std::to_string(sim->state()));
  CHECK(!sim->status());
  // Lost: 0. Back: it boots again and reads 5.
  sim->KillSlave(2);
  CHECK_MSG(sim->RunUntil([] { return sim->state() == 0; }, seconds(2)), std::to_string(sim->state()));
  sim->StartSlave(2, dir + "/cpp-slave.eds");
  CHECK(sim->RunUntil([] { return sim->state() == 5; }, seconds(20)));
  delete sim;
}

TEST(sim_slave_absent_at_start) {
  clear_logs();
  std::string dir = make_dir(pingpong_json(), {{"cpp-slave.eds", slave_eds()}});
  static Sim* sim;
  sim = new Sim(dir);
  if (!sim->ok()) {
    CHECK(sim->ok());
    return;
  }
  sim->net().Start();
  sim->RunFor(milliseconds(3500));
  CHECK(!sim->status());
  CHECK(sim->in() == 0);
  CHECK(sim->scans() > 100);
  CHECK(logged("node 2 (pingpong) is not answering"));
  sim->StartSlave(2, dir + "/cpp-slave.eds");
  CHECK(sim->RunUntil([] { return sim->status(); }, seconds(20)));
  CHECK(sim->RunUntil([] { return sim->in() > 5; }, seconds(5)));
  delete sim;
}

TEST(sim_sdo_abort_other_nodes_continue) {
  // Node 3's EDS (as the master sees it) has a mappable 0x4002 that the real
  // slave does not implement, so configuring RPDO 1 with it is aborted by the
  // slave. Node 2 must still come up.
  clear_logs();
  std::string eds = slave_eds();
  std::string bad = eds;
  bad.replace(bad.find("SupportedObjects=2\n1=0x4000\n2=0x4001"), 36,
              "SupportedObjects=3\n1=0x4000\n2=0x4001\n3=0x4002");
  bad += "\n[4002]\nParameterName=Not implemented by the slave\nDataType=0x0007\nAccessType=rww\n"
         "DefaultValue=0\nPDOMapping=1\n";
  std::string node3 = R"(,
    {
      "node_id": 3, "name": "rejects", "eds": "bad-slave.eds",
      "status_location": "%IX10.1",
      "tx_pdos": [ { "entries": [ { "index": "0x4001", "type": "UNSIGNED32", "iec_location": "%ID200" } ] } ],
      "rx_pdos": [ { "entries": [ { "index": "0x4002", "type": "UNSIGNED32", "iec_location": "%QD200" } ] } ]
    })";
  std::string dir = make_dir(pingpong_json(node3), {{"cpp-slave.eds", eds}, {"bad-slave.eds", bad}});
  static Sim* sim;
  sim = new Sim(dir);
  if (!sim->ok()) {
    CHECK(sim->ok());
    return;
  }
  sim->StartSlave(2, dir + "/cpp-slave.eds");
  sim->StartSlave(3, dir + "/cpp-slave.eds");  // the real device lacks 0x4002
  sim->net().Start();
  CHECK(sim->RunUntil([] { return sim->status(); }, seconds(5)));
  CHECK(sim->RunUntil([] { return logged("node 3: SDO download to index 0x1600 subindex 1 aborted"); }, seconds(5)));
  sim->RunFor(milliseconds(500));
  CHECK(!sim->net().IsOperational(3));
  CHECK(sim->plc().bool_in[10][1] == 0);
  CHECK(sim->net().IsOperational(2));
  bool code = false;
  for (const auto& l : logs())
    if (l.find("node 3: SDO download") != std::string::npos && l.find("abort code 0x06") != std::string::npos)
      code = true;
  CHECK(code);
  uint32_t a = sim->in();
  CHECK(sim->RunUntil([&] { return sim->in() > a + 5; }, seconds(5)));
  delete sim;
}

// A node with a startup SDO it only accepts while not OPERATIONAL (as some
// valves do with their settings). Its cable is pulled and plugged back while
// it keeps running, so the master boots it again while it is still OPERATIONAL: the
// download is refused (error status J), and the master must reset the node
// and configure it from PRE-OPERATIONAL instead of retrying the same download
// forever. While the cable is out, the state byte reads 0.
std::string mode_lock_eds() {
  std::string eds = slave_eds();
  eds.replace(eds.find("SupportedObjects=7\n"), 19, "SupportedObjects=8\n8=0x1F80\n");
  eds.replace(eds.find("SupportedObjects=2\n1=0x4000\n2=0x4001"), 36,
              "SupportedObjects=3\n1=0x4000\n2=0x4001\n3=0x4010");
  // 0x1F80 bit 2: no self-start, like most real slaves.
  return eds + "\n[1F80]\nParameterName=NMT startup\nDataType=0x0007\nAccessType=rw\nDefaultValue=0x04\n"
               "PDOMapping=0\n\n[4010]\nParameterName=Mode\nDataType=0x0005\nAccessType=rw\nDefaultValue=0\nPDOMapping=0\n";
}

std::string mode_lock_json() {
  std::string json = pingpong_json();
  size_t at = json.find("\"status_location\": \"%IX10.0\",");
  json.insert(at, "\"state_location\": \"%IB20\", "
                  "\"sdo\": [ { \"index\": \"0x4010\", \"type\": \"UNSIGNED8\", \"value\": 2 } ], ");
  return json;
}

TEST(sim_operational_node_refusing_config_is_reset) {
  clear_logs();
  std::string dir = make_dir(mode_lock_json(), {{"cpp-slave.eds", mode_lock_eds()}});
  static Sim* sim;
  sim = new Sim(dir);
  if (!sim->ok()) {
    CHECK(sim->ok());
    return;
  }
  sim->StartModeLockSlave(2, dir + "/cpp-slave.eds", false);
  sim->net().Start();
  CHECK(sim->RunUntil([] { return sim->status() && sim->state() == 5 && sim->in() > 5; }, seconds(5)));
  sim->Unplug(2);
  CHECK(sim->RunUntil([] { return !sim->status(); }, seconds(2)));
  CHECK_MSG(sim->RunUntil([] { return sim->state() == 0; }, seconds(5)), std::to_string(sim->state()));
  sim->RunFor(seconds(2));
  CHECK(sim->state() == 0);
  sim->Replug(2);
  CHECK(sim->RunUntil([] { return logged("error status J"); }, seconds(20)));
  CHECK(logged("node 2: SDO download to index 0x4010 subindex 0 aborted, abort code 0x06010002"));
  CHECK_MSG(sim->RunUntil([] { return sim->status() && sim->state() == 5; }, seconds(20)),
            std::to_string(sim->state()));
  uint32_t c = sim->in();
  CHECK(sim->RunUntil([&] { return sim->in() > c + 5; }, seconds(5)));
  delete sim;
}

// Boot SDO timeout (master.sdo_timeout_ms). The startup SDO to 0x4010 takes
// 300 ms; a long heartbeat timeout keeps the blocked slave thread from
// counting as a lost node.
std::string slow_json(const std::string& master_extra, const std::string& node_extra = "") {
  std::string json = mode_lock_json();
  json.replace(json.find("\"heartbeat_timeout_ms\": 200"), 27, "\"heartbeat_timeout_ms\": 5000");
  json.replace(json.find("\"sync_period_us\": 20000"), 23, "\"sync_period_us\": 20000" + master_extra);
  json.insert(json.find("\"status_location\": \"%IX10.0\","), node_extra);
  return json;
}

TEST(sim_boot_sdo_timeout_default_waits_for_slow_device) {
  clear_logs();
  std::string dir = make_dir(slow_json(""), {{"cpp-slave.eds", mode_lock_eds()}});
  static Sim* sim;
  sim = new Sim(dir);
  CHECK(sim->ok());
  if (!sim->ok()) return;
  sim->StartSlowSlave(2, dir + "/cpp-slave.eds", milliseconds(300), milliseconds(0));
  sim->net().Start();
  CHECK_MSG(sim->RunUntil([] { return sim->status() && sim->state() == 5; }, seconds(10)),
            std::to_string(sim->state()));
  CHECK(!logged("0x05040000"));
  delete sim;
}

TEST(sim_boot_sdo_timeout_too_short) {
  clear_logs();
  std::string dir = make_dir(slow_json(", \"sdo_timeout_ms\": 200"), {{"cpp-slave.eds", mode_lock_eds()}});
  static Sim* sim;
  sim = new Sim(dir);
  CHECK(sim->ok());
  if (!sim->ok()) return;
  sim->StartSlowSlave(2, dir + "/cpp-slave.eds", milliseconds(300), milliseconds(0));
  sim->net().Start();
  CHECK(sim->RunUntil([] { return logged("abort code 0x05040000"); }, seconds(10)));
  CHECK(logged("node 2: SDO download to index 0x4010 subindex 0 aborted, abort code 0x05040000"));
  CHECK(logged("no answer within 200 ms (master.sdo_timeout_ms)"));
  CHECK(sim->RunUntil([] { return logged("error status J"); }, seconds(10)));
  sim->RunFor(seconds(1));
  CHECK(!sim->status());
  delete sim;
}

// A long boot SDO timeout does not lengthen an SDO variable's own (default
// 1000 ms): the read after boot of a 0x4010 that answers after 1.5 s aborts
// after about 1 s.
TEST(sim_boot_sdo_timeout_leaves_sdo_variables_alone) {
  clear_logs();
  std::string dir = make_dir(slow_json(", \"sdo_timeout_ms\": 5000",
                                       R"("sdo_variables": [ { "name": "mode", "index": "0x4010", "type": "UNSIGNED8",
                                            "direction": "read", "iec_location": "%IB210",
                                            "status_location": "%IB211", "abort_code_location": "%ID211" } ], )"),
                             {{"cpp-slave.eds", mode_lock_eds()}});
  static Sim* sim;
  sim = new Sim(dir);
  CHECK(sim->ok());
  if (!sim->ok()) return;
  sim->StartSlowSlave(2, dir + "/cpp-slave.eds", milliseconds(0), milliseconds(1500));
  sim->net().Start();
  CHECK(sim->RunUntil([] { return sim->ib(211) == 1; }, seconds(10)));
  auto t0 = std::chrono::steady_clock::now();
  CHECK_MSG(sim->RunUntil([] { return sim->ib(211) == 3; }, seconds(5)), std::to_string(sim->ib(211)));
  auto ms = std::chrono::duration_cast<milliseconds>(std::chrono::steady_clock::now() - t0).count();
  std::printf("    SDO variable aborted after %lld ms\n", static_cast<long long>(ms));
  CHECK(ms < 1400);
  CHECK(static_cast<uint32_t>(sim->plc().dint_in[211]) == 0x05040000u);
  delete sim;
}

// Configuration check (config_check, store_configuration).
std::string config_check_json(const std::string& node_extra = "\"config_check\": true, \"store_configuration\": 1, ") {
  std::string json = pingpong_json();
  json.insert(json.find("\"status_location\": \"%IX10.0\","), "\"state_location\": \"%IB20\", " + node_extra);
  return json;
}

std::string config_check_eds() { return read(std::string(FIXTURES_DIR) + "/eds/config-check.eds"); }

// Boots the storing slave with a new master on `json` until the round trip
// runs (the slave starts `lead` before the master); returns the number of SDO
// downloads to the node, or -1 when it did not come up.
int config_check_boot(const std::string& json, std::shared_ptr<StoredConfig> mem, milliseconds lead = milliseconds(0)) {
  std::string dir = make_dir(json, {{"cpp-slave.eds", config_check_eds()}});
  static Sim* sim;
  sim = new Sim(dir);
  CHECK(sim->ok());
  int downloads = -1;
  if (sim->ok()) {
    sim->StartStoringSlave(2, dir + "/cpp-slave.eds", mem);
    sim->RunFor(lead);
    sim->net().Start();
    bool up = sim->RunUntil([] { return sim->status() && sim->in() > 2; }, seconds(10));
    CHECK_MSG(up, std::to_string(sim->state()));
    if (up) downloads = sim->downloads(2);
  }
  delete sim;
  return downloads;
}

TEST(sim_config_check_downloads_once) {
  clear_logs();
  auto mem = std::make_shared<StoredConfig>();
  std::string dir = make_dir(config_check_json(), {{"cpp-slave.eds", config_check_eds()}});
  static Sim* sim;
  sim = new Sim(dir);
  if (!sim->ok()) {
    CHECK(sim->ok());
    return;
  }
  sim->StartStoringSlave(2, dir + "/cpp-slave.eds", mem);
  sim->net().Start();
  CHECK(sim->RunUntil([] { return sim->status() && sim->in() > 2; }, seconds(10)));
  CHECK(logged("node 2 (pingpong): configuring ("));
  CHECK(!logged("configuration unchanged"));
  CHECK_MSG(mem->saves == 1, std::to_string(mem->saves));
  int first = sim->downloads(2);
  CHECK_MSG(first > 3, std::to_string(first));

  // The device restarts (a reset, or a power cycle with the saved values).
  clear_logs();
  sim->OnSlave(2, [](canopen::BasicSlave& s) { s.Reset(); });
  CHECK(sim->RunUntil([] { return logged("configuration unchanged"); }, seconds(10)));
  CHECK(logged("node 2 (pingpong): configuration unchanged (0x1020 matches), nothing downloaded"));
  uint32_t c = sim->in();
  CHECK(sim->RunUntil([&] { return sim->status() && sim->state() == 5 && sim->in() > c + 5; }, seconds(10)));
  CHECK_MSG(sim->downloads(2) == first, std::to_string(sim->downloads(2)) + " vs " + std::to_string(first));
  CHECK(mem->saves == 1);
  CHECK(!logged("boot failed"));
  delete sim;
}

// A new master (PLC runtime restart) finds the node OPERATIONAL with this
// configuration: it is running, not reset, and gets nothing; after a change
// in canopen_config.json the next master downloads and saves again.
TEST(sim_config_check_new_master) {
  clear_logs();
  auto mem = std::make_shared<StoredConfig>();
  CHECK(config_check_boot(config_check_json(), mem) > 3);
  CHECK(mem->saves == 1);

  clear_logs();
  int again = config_check_boot(config_check_json(), mem, milliseconds(300));
  CHECK_MSG(again == 0, std::to_string(again));
  CHECK(logged("node 2 (pingpong): configuration unchanged"));
  CHECK(mem->saves == 1);
  CHECK(!logged("boot failed"));
  CHECK(!logged("configuring ("));

  clear_logs();
  std::string changed = config_check_json();
  changed.replace(changed.find("\"heartbeat_ms\": 50"), 18, "\"heartbeat_ms\": 60");
  int third = config_check_boot(changed, mem, milliseconds(300));
  CHECK_MSG(third > 3, std::to_string(third));
  CHECK(logged("node 2 (pingpong): configuring ("));
  CHECK(!logged("configuration unchanged"));
  CHECK(mem->saves == 2);
}

// Without store_configuration the master never writes 0x1010.
TEST(sim_config_check_without_store) {
  clear_logs();
  auto mem = std::make_shared<StoredConfig>();
  CHECK(config_check_boot(config_check_json("\"config_check\": true, "), mem) > 3);
  CHECK(mem->saves == 0);
  CHECK(mem->saved.empty());
}

TEST(sim_config_check_save_refused) {
  clear_logs();
  auto mem = std::make_shared<StoredConfig>();
  mem->refuse_save = true;
  std::string dir = make_dir(config_check_json(), {{"cpp-slave.eds", config_check_eds()}});
  static Sim* sim;
  sim = new Sim(dir);
  if (!sim->ok()) {
    CHECK(sim->ok());
    return;
  }
  sim->StartStoringSlave(2, dir + "/cpp-slave.eds", mem);
  sim->net().Start();
  CHECK(sim->RunUntil([] { return logged("error status J"); }, seconds(10)));
  CHECK(logged("node 2: SDO download to index 0x1010 subindex 1 aborted, abort code 0x08000020"));
  CHECK(!sim->status());
  CHECK(mem->saves == 0);
  delete sim;
}

// A node that answers but cannot be configured, then goes silent: while the
// master keeps retrying its boot, the state byte must drop to 0.
TEST(sim_state_byte_clears_when_failing_node_goes_silent) {
  clear_logs();
  std::string dir = make_dir(mode_lock_json(), {{"cpp-slave.eds", mode_lock_eds()}});
  static Sim* sim;
  sim = new Sim(dir);
  if (!sim->ok()) {
    CHECK(sim->ok());
    return;
  }
  sim->StartModeLockSlave(2, dir + "/cpp-slave.eds", true);
  sim->net().Start();
  CHECK(sim->RunUntil([] { return logged("error status J"); }, seconds(5)));
  CHECK(!sim->status());
  sim->KillSlave(2);
  CHECK_MSG(sim->RunUntil([] { return sim->state() == 0; }, seconds(20)), std::to_string(sim->state()));
  sim->RunFor(seconds(3));
  CHECK(sim->state() == 0);
  delete sim;
}

// The node's event-driven TPDO with an inhibit time: the round trip
// %QD100 := %ID100 + 1 advances at most once per received PDO, so with a
// 250 ms inhibit time (and a 10 ms event timer) the counter moves at most 4
// times a second; without it the round trip itself (SYNC, scan) sets the pace.
TEST(sim_tpdo_inhibit_time) {
  clear_logs();
  auto rate = [](const std::string& tx_fields) {
    std::string json = pingpong_json();
    size_t at = json.find("\"tx_pdos\": [ { \"entries\"");
    json.insert(at + std::string("\"tx_pdos\": [ { ").size(), tx_fields);
    std::string dir = make_dir(json, {{"cpp-slave.eds", slave_eds()}});
    static Sim* sim;
    sim = new Sim(dir);
    if (!sim->ok()) {
      CHECK(sim->ok());
      delete sim;
      return -1.0;
    }
    sim->StartSlave(2, dir + "/cpp-slave.eds");
    sim->net().Start();
    CHECK(sim->RunUntil([] { return sim->status() && sim->in() > 2; }, seconds(5)));
    uint32_t a = sim->in();
    sim->RunFor(seconds(2));
    double per_s = (sim->in() - a) / 2.0;
    delete sim;
    return per_s;
  };
  double fast = rate("\"transmission\": 255, \"event_timer_ms\": 10, ");
  double slow = rate("\"transmission\": 255, \"event_timer_ms\": 10, \"inhibit_time_us\": 250000, ");
  std::printf("    %.1f updates/s without inhibit time, %.1f with 250 ms\n", fast, slow);
  CHECK(fast > 10);
  CHECK(slow > 2 && slow <= 4.5);
}

// No SYNC period: no SYNC on the bus, outputs go out as event-driven PDOs
// when they change, and not when they do not.
TEST(sim_no_sync_event_driven) {
  clear_logs();
  std::string json = pingpong_json();
  json.replace(json.find("\"sync_period_us\": 20000"), 23, "\"heartbeat_ms\": 0");
  json.replace(json.find("\"tx_pdos\": [ { "), 15, "\"tx_pdos\": [ { \"transmission\": 255, \"event_timer_ms\": 10, ");
  json.replace(json.find("\"rx_pdos\": [ { "), 15, "\"rx_pdos\": [ { \"transmission\": 255, ");
  std::string dir = make_dir(json, {{"cpp-slave.eds", slave_eds()}});
  static Sim* sim;
  sim = new Sim(dir);
  CHECK(sim->ok());
  if (!sim->ok()) return;
  CHECK(sim->cfg().master.sync_period_us == 0);
  sim->StartSlave(2, dir + "/cpp-slave.eds");
  sim->net().Start();
  CHECK(sim->RunUntil([] { return sim->status(); }, seconds(5)));
  uint32_t a = sim->in();
  CHECK(sim->RunUntil([&] { return sim->in() >= a + 10; }, seconds(5)));
  std::printf("    counter went %u -> %u without SYNC\n", a, sim->in());
  CHECK_MSG(sim->frames(0x080) == 0, std::to_string(sim->frames(0x080)) + " SYNC frames");
  // A program whose outputs stay the same puts no RPDO on the bus.
  sim->SetProgram([](fake_runtime::Image& plc) { plc.dint_out[100] = 7; });
  sim->RunFor(milliseconds(200));
  int before = sim->frames(0x202);
  sim->RunFor(milliseconds(1000));
  CHECK_MSG(sim->frames(0x202) == before, std::to_string(sim->frames(0x202) - before) + " RPDOs for unchanged outputs");
  CHECK(sim->frames(0x080) == 0);
  delete sim;
}

// PLC-cycle SYNC (canopen-master-bringup "SYNC from the PLC cycle", canopen-pdo-io
// "PDO timing with PLC-cycle SYNC"): Sim's scan requests a SYNC in its
// cycle_start step, every 10 ms.
std::string plc_cycle_json(const std::string& extra = "") {
  std::string json = pingpong_json();
  json.replace(json.find("\"sync_period_us\": 20000"), 23, "\"sync_source\": \"plc_cycle\"" + extra);
  return json;
}

// Every step of a run of values is +1.
int steps_off(const std::vector<uint32_t>& v, size_t from) {
  int bad = 0;
  for (size_t i = from + 1; i < v.size(); ++i)
    if (v[i] != v[i - 1] + 1) ++bad;
  return bad;
}

TEST(sim_plc_cycle_sync) {
  clear_logs();
  std::string dir = make_dir(plc_cycle_json(), {{"cpp-slave.eds", slave_eds()}});
  static Sim* sim;
  sim = new Sim(dir);
  CHECK(sim->ok());
  if (!sim->ok()) return;
  CHECK(sim->cfg().master.sync_plc_cycle && sim->cfg().master.sync_period_us == 0);
  // dcfgen gets no period, so Lely runs no SYNC timer; 0x1005 keeps the producer bit.
  std::string dcf = read(sim->gen_master_dcf());
  size_t at = dcf.find("[1006]");
  CHECK(at != std::string::npos && dcf.find("DefaultValue=0\n", at) < dcf.find("[1007]"));
  at = dcf.find("[1005]");
  CHECK(at != std::string::npos && dcf.find("DefaultValue=0x40000080", at) < dcf.find("[1006]"));
  SyncCounterSlave* slave = sim->StartSyncCounterSlave(2, dir + "/cpp-slave.eds");
  static std::vector<uint32_t> seen;
  static uint32_t scan_no;
  seen.clear();
  scan_no = 0;
  sim->SetProgram([](fake_runtime::Image& plc) {
    seen.push_back(plc.dint_in[100]);
    plc.dint_out[100] = ++scan_no;
  });
  sim->EnableDiag();
  sim->net().Start();
  CHECK(sim->RunUntil([] { return sim->status(); }, seconds(5)));
  sim->RunFor(milliseconds(300));
  long scans0 = sim->scans();
  int syncs0 = sim->frames(0x080);
  size_t seen0 = seen.size();
  size_t applied0;
  {
    std::lock_guard<std::mutex> lock(slave->mutex);
    applied0 = slave->applied.size();
  }
  sim->RunFor(milliseconds(2000));
  long scans = sim->scans() - scans0;
  int syncs = sim->frames(0x080) - syncs0;
  std::printf("    %ld scans, %d SYNCs\n", scans, syncs);
  CHECK_MSG(std::abs(syncs - static_cast<int>(scans)) <= 1, std::to_string(syncs) + " SYNCs for " +
                                                                 std::to_string(scans) + " scans");
  // Inputs: the device counts SYNCs, and every scan sees the next count.
  CHECK_MSG(steps_off(seen, seen0) == 0, std::to_string(steps_off(seen, seen0)) + " scans saw no new input");
  // Outputs: each SYNC carries the newest scan's value, applied at the next.
  std::vector<uint32_t> applied;
  {
    std::lock_guard<std::mutex> lock(slave->mutex);
    applied = slave->applied;
  }
  CHECK(applied.size() > applied0 + 100);
  CHECK_MSG(steps_off(applied, applied0) == 0,
            std::to_string(steps_off(applied, applied0)) + " outputs repeated or lost");
  const Network::SyncStats& st = sim->net().sync_stats();
  std::printf("    SYNC interval last %llu, min %llu, max %llu us\n", (unsigned long long)st.last_us,
              (unsigned long long)st.min_us, (unsigned long long)st.max_us);
  CHECK(st.count >= static_cast<uint64_t>(syncs));
  CHECK(st.skipped == 0);
  CHECK(st.late == 0);
  CHECK(st.min_us > 2000 && st.max_us < 40000);
  // The status answer names the source and carries the statistics.
  DiagRequest r;
  r.op = "status";
  r.peer = "127.0.0.1";
  cJSON* res = sim->Ask(r);
  CHECK(res != nullptr);
  if (res) {
    const cJSON* sync = cJSON_GetObjectItem(cJSON_GetObjectItem(res, "result"), "sync");
    CHECK(sync && std::string(cJSON_GetStringValue(cJSON_GetObjectItem(sync, "source"))) == "plc_cycle");
    CHECK(sync && cJSON_GetObjectItem(sync, "cycles")->valuedouble == 1);
    CHECK(sync && cJSON_GetObjectItem(sync, "count")->valuedouble > 100);
    cJSON_Delete(res);
  }
  delete sim;
}

TEST(sim_plc_cycle_sync_cycles_counter_skips) {
  clear_logs();
  std::string dir = make_dir(plc_cycle_json(", \"sync_cycles\": 2, \"sync_counter_overflow\": 10"),
                             {{"cpp-slave.eds", slave_eds()}});
  static Sim* sim;
  sim = new Sim(dir);
  CHECK(sim->ok());
  if (!sim->ok()) return;
  sim->StartSyncCounterSlave(2, dir + "/cpp-slave.eds");
  sim->net().Start();
  CHECK(sim->RunUntil([] { return sim->status(); }, seconds(5)));
  long scans0 = sim->scans();
  int syncs0 = sim->frames(0x080);
  sim->RunFor(milliseconds(2000));
  long scans = sim->scans() - scans0;
  int syncs = sim->frames(0x080) - syncs0;
  CHECK_MSG(std::abs(2 * syncs - static_cast<int>(scans)) <= 2,
            std::to_string(syncs) + " SYNCs for " + std::to_string(scans) + " scans");
  auto frames = sim->sync_frames();
  int bad = 0;
  for (size_t i = 1; i < frames.size(); ++i)
    if (frames[i].cnt != frames[i - 1].cnt % 10 + 1) ++bad;
  CHECK_MSG(frames.size() > 50 && bad == 0, std::to_string(bad) + " SYNC counter steps off");
  CHECK(frames.empty() || (frames[0].cnt >= 1 && frames[0].cnt <= 10));
  // Two requests before the bus thread gets to them: one SYNC, one skip.
  CHECK(sim->net().sync_stats().skipped == 0);
  sim->RequestSync(4);
  sim->RunFor(milliseconds(100));
  CHECK_MSG(sim->net().sync_stats().skipped >= 1, std::to_string(sim->net().sync_stats().skipped) + " skipped");
  CHECK(logged("fell behind the PLC cycle"));
  delete sim;
}

TEST(sim_plc_cycle_late_pdo) {
  clear_logs();
  std::string dir = make_dir(plc_cycle_json(), {{"cpp-slave.eds", slave_eds()}});
  static Sim* sim;
  sim = new Sim(dir);
  CHECK(sim->ok());
  if (!sim->ok()) return;
  sim->StartSyncCounterSlave(2, dir + "/cpp-slave.eds");
  sim->net().Start();
  CHECK(sim->RunUntil([] { return sim->status(); }, seconds(5)));
  sim->RunFor(milliseconds(200));
  CHECK(sim->net().sync_stats().late == 0);
  sim->OnSlave(2, [](canopen::BasicSlave& s) { static_cast<SyncCounterSlave&>(s).Mute(true); });
  sim->RunFor(milliseconds(150));
  sim->OnSlave(2, [](canopen::BasicSlave& s) { static_cast<SyncCounterSlave&>(s).Mute(false); });
  sim->RunFor(milliseconds(200));
  uint64_t late = sim->net().sync_stats().late;
  std::printf("    %llu late PDOs\n", (unsigned long long)late);
  CHECK(late >= 5 && late <= 20);
  int lines = 0;
  for (const auto& l : logs())
    if (l.find("node 2 (pingpong) TPDO 1 (transmission type 1) did not arrive before the next SYNC") !=
        std::string::npos)
      ++lines;
  CHECK_MSG(lines == 1, std::to_string(lines) + " late PDO warnings");
  // Back in time: no more late PDOs.
  sim->RunFor(milliseconds(300));
  CHECK(sim->net().sync_stats().late == late);
  delete sim;
}

TEST(sim_timer_sync_stats) {
  clear_logs();
  std::string dir = make_dir(pingpong_json(), {{"cpp-slave.eds", slave_eds()}});
  static Sim* sim;
  sim = new Sim(dir);
  CHECK(sim->ok());
  if (!sim->ok()) return;
  sim->StartSlave(2, dir + "/cpp-slave.eds");
  sim->net().Start();
  CHECK(sim->RunUntil([] { return sim->status(); }, seconds(5)));
  sim->RunFor(milliseconds(1000));
  const Network::SyncStats& st = sim->net().sync_stats();
  std::printf("    timer SYNC: %llu sent, interval min %llu max %llu us\n", (unsigned long long)st.count,
              (unsigned long long)st.min_us, (unsigned long long)st.max_us);
  CHECK(st.count >= 40);
  CHECK(st.min_us > 10000 && st.max_us < 40000);
  CHECK(st.skipped == 0 && st.late == 0);
  delete sim;
}

TEST(time_of_day_encoding) {
  uint8_t d[6];
  encode_time_of_day(441763200000LL, d);  // 1984-01-01 00:00:00 UTC
  CHECK(d[0] == 0 && d[1] == 0 && d[2] == 0 && d[3] == 0 && d[4] == 0 && d[5] == 0);
  // 2026-10-05 14:30:00.250 UTC: day 15618 since 1984-01-01, 52200250 ms.
  encode_time_of_day(1791210600250LL, d);
  uint32_t ms = d[0] | d[1] << 8 | d[2] << 16 | static_cast<uint32_t>(d[3]) << 24;
  uint16_t days = static_cast<uint16_t>(d[4] | d[5] << 8);
  CHECK_MSG(ms == 52200250 && days == 15618, std::to_string(ms) + " ms, day " + std::to_string(days));
}

// TIME producer (master.time_period_ms): a TIME_OF_DAY from the host clock at
// once when the bus comes up, then every period; none without the setting.
TEST(sim_time_producer) {
  clear_logs();
  auto run = [](const std::string& master_fields, uint32_t id, int run_ms) {
    std::string json = pingpong_json();
    std::string from = "\"sync_period_us\": 20000";
    json.replace(json.find(from), from.size(), from + master_fields);
    std::string dir = make_dir(json, {{"cpp-slave.eds", slave_eds()}});
    static Sim* sim;
    sim = new Sim(dir);
    std::vector<Sim::Stamped> frames;
    if (!sim->ok()) {
      CHECK(sim->ok());
      delete sim;
      return std::make_pair(frames, std::chrono::steady_clock::time_point());
    }
    sim->StartSlave(2, dir + "/cpp-slave.eds");
    auto start = std::chrono::steady_clock::now();
    sim->net().Start();
    sim->RunFor(milliseconds(run_ms));
    frames = sim->time_frames(id);
    delete sim;
    return std::make_pair(frames, start);
  };

  auto res = run(", \"time_period_ms\": 500", 0x100, 1750);
  const auto& f = res.first;
  CHECK_MSG(f.size() >= 4 && f.size() <= 5, std::to_string(f.size()) + " TIME frames in 1.75 s");
  if (!f.empty()) {
    CHECK(f[0].at - res.second < milliseconds(150));
    CHECK(f[0].msg.len == 6);
    timespec ts{};
    clock_gettime(CLOCK_REALTIME, &ts);
    int64_t now_ms = static_cast<int64_t>(ts.tv_sec) * 1000 + ts.tv_nsec / 1000000;
    uint32_t ms = f.back().msg.data[0] | f.back().msg.data[1] << 8 | f.back().msg.data[2] << 16 |
                  (f.back().msg.data[3] & 0x0F) << 24;
    uint16_t days = static_cast<uint16_t>(f.back().msg.data[4] | f.back().msg.data[5] << 8);
    int64_t sent_ms = (static_cast<int64_t>(days) + 5113) * 86400000 + ms;
    CHECK_MSG(now_ms - sent_ms >= 0 && now_ms - sent_ms < 2000,
              "TIME carries " + std::to_string(sent_ms) + ", host clock " + std::to_string(now_ms));
  }
  for (size_t i = 1; i < f.size(); ++i) {
    auto gap = std::chrono::duration_cast<milliseconds>(f[i].at - f[i - 1].at).count();
    CHECK_MSG(gap >= 350 && gap <= 650, "TIME gap " + std::to_string(gap) + " ms");
  }
  CHECK(logged("producing TIME on COB-ID 0x100 every 500 ms"));
  CHECK(logged("no configured node is set to consume it"));

  clear_logs();
  res = run(", \"time_period_ms\": 500, \"time_cob_id\": \"0x180\"", 0x180, 600);
  CHECK(!res.first.empty());

  clear_logs();
  res = run("", 0x100, 800);
  CHECK(res.first.empty());
  CHECK(!logged("producing TIME"));
}

// The simulated RTD-8 module (8x RTD, CiA 404, config/rtd-sensor/rtd8.eds)
// unchanged on the master side. The simulated device starts with every PDO mapping
// blank, so the four temperatures can only reach %IW100-%IW103 if the master
// builds TPDO 1 from canopen_config.json.
TEST(sim_rtd_sensor_blank_mapping) {
  clear_logs();
  std::string eds = read(std::string(RTD_DIR) + "/rtd8.eds");
  std::string cfg = read(std::string(RTD_DIR) + "/canopen_config.json");
  cfg.replace(cfg.find("\"vcan0\""), 7, "\"sim\"");
  cfg.replace(cfg.find("\"sync_period_us\": 100000"), 24, "\"sync_period_us\": 20000");
  std::string dir = make_dir(cfg, {{"rtd8.eds", eds}, {"device.eds", blank_pdo_mapping(eds)}});
  CHECK(blank_pdo_mapping(eds).find("[1A00sub0]") != std::string::npos);
  static Sim* sim;
  sim = new Sim(dir);
  CHECK(sim->ok());
  if (!sim->ok()) return;
  // 0.1 degC: 20.0-26.0, 30.0-36.0, 40.0-46.0, -10.0..-4.0
  sim->StartSensor(5, dir + "/device.eds",
                   {{0x7130, 1, 200, 260, 1}, {0x7130, 2, 300, 360, 1}, {0x7130, 3, 400, 460, 1},
                    {0x7130, 4, -100, -40, 1}});
  sim->net().Start();
  CHECK(sim->RunUntil([] { return sim->status(); }, seconds(5)));
  CHECK(logged("node 5 (rtd) is operational"));
  CHECK(sim->RunUntil([] { return sim->iw(100) != 0 && sim->iw(103) != 0; }, seconds(2)));
  int16_t first = sim->iw(100);
  bool moved = false, in_range = true;
  sim->RunUntil([&] {
    in_range = in_range && sim->iw(100) >= 200 && sim->iw(100) <= 260 && sim->iw(101) >= 300 &&
               sim->iw(101) <= 360 && sim->iw(102) >= 400 && sim->iw(102) <= 460 && sim->iw(103) >= -100 &&
               sim->iw(103) <= -40;
    moved = moved || sim->iw(100) != first;
    return false;
  }, milliseconds(800));
  CHECK_MSG(in_range, "values " + std::to_string(sim->iw(100)) + " " + std::to_string(sim->iw(101)) + " " +
                          std::to_string(sim->iw(102)) + " " + std::to_string(sim->iw(103)));
  CHECK(moved);
  CHECK(sim->plc().byte_in[100] == 0 && sim->plc().byte_in[103] == 0);  // AI status: no error
  std::printf("    AI0..AI3 = %d %d %d %d (0.1 degC)\n", sim->iw(100), sim->iw(101), sim->iw(102), sim->iw(103));
  delete sim;
}

// A device with a fixed PDO mapping and read-only COB-IDs (any write to them
// aborts) comes up with the device mapping, and a subset of each PDO
// reaches the PLC: %QB40 -> 0x6200:1, 0x6000:2 (= that + 100) -> %IB40. The
// output the config leaves out (0x6200:2) goes out as 0.
TEST(sim_fixed_pdo_mapping) {
  clear_logs();
  std::string json = R"({
  "schema_version": 1,
  "adapter": { "type": "socketcan", "interface": "sim", "bitrate": 125000 },
  "master": { "node_id": 1, "sync_period_us": 20000 },
  "nodes": [
    {
      "node_id": 4, "name": "io", "eds": "fixed-io.eds",
      "heartbeat_ms": 50, "heartbeat_timeout_ms": 200,
      "status_location": "%IX10.0",
      "tx_pdos": [ { "entries": [ { "index": "0x6000", "subindex": 2, "type": "UNSIGNED8", "iec_location": "%IB40" } ] } ],
      "rx_pdos": [ { "entries": [ { "index": "0x6200", "subindex": 1, "type": "UNSIGNED8", "iec_location": "%QB40" } ] } ]
    }
  ]
})";
  std::string dir = make_dir(json, {{"fixed-io.eds", read(std::string(FIXTURES_DIR) + "/eds/fixed-io.eds")}});
  static Sim* sim;
  sim = new Sim(dir);
  CHECK(sim->ok());
  if (!sim->ok()) return;
  sim->SetProgram([](fake_runtime::Image& plc) { plc.byte_out[40] = 7; });
  FixedIoSlave* io = sim->StartFixedIoSlave(4, dir + "/fixed-io.eds");
  sim->net().Start();
  CHECK(sim->RunUntil([] { return sim->status(); }, seconds(5)));
  CHECK(logged("node 4 (io) is operational"));
  CHECK_MSG(sim->RunUntil([] { return sim->ib(40) == 107; }, seconds(2)), "%IB40 = " + std::to_string(sim->ib(40)));
  CHECK(sim->RunUntil([io] { return io->out2 == 0; }, seconds(1)));
  CHECK(!logged("aborted"));
  delete sim;
}

// ---------------------------------------------------------------------------
// Made-up drive EDS files (test/fixtures/eds/drives/make_drives.py). Both
// have lint findings only about limits written as unsigned hex outside the
// communication objects, as many vendor files do, so they load under the
// default eds_lint ("communication") with one warning each.

std::string drive_eds(const std::string& name) {
  return read(std::string(FIXTURES_DIR) + "/eds/drives/" + name);
}

const char* kServoEds = "servo-drive.eds";

// The servo drive's EDS gives no values for its identity (0x1018), which a
// real drive reports from its firmware. The simulated drive gets those of the
// EDS's [DeviceInfo] in its own copy; the master keeps the file as it is.
std::string servo_device_eds() {
  std::string eds = drive_eds(kServoEds);
  const std::pair<const char*, const char*> ids[] = {
      {"[1018sub1]", "0x00F0F0F1"}, {"[1018sub2]", "0x00000402"}, {"[1018sub3]", "0x00010000"}};
  for (const auto& id : ids) {
    size_t at = eds.find('\n', eds.find(id.first)) + 1;
    eds.insert(at, std::string("DefaultValue=") + id.second + "\n");
  }
  return eds;
}

// The servo drive as node 3: writable 0x1020 and 0x1010:1. The config maps
// statusword and position (not the device's default TPDO 1 mapping) and asks
// for the configuration check with a save.
std::string servo_json() {
  return R"({
  "schema_version": 1,
  "adapter": { "type": "socketcan", "interface": "sim", "bitrate": 500000 },
  "master": { "node_id": 1, "sync_period_us": 20000 },
  "nodes": [
    {
      "node_id": 3, "name": "servo", "eds": "servo-drive.eds",
      "heartbeat_ms": 50, "heartbeat_timeout_ms": 200,
      "status_location": "%IX10.0", "state_location": "%IB20",
      "config_check": true, "store_configuration": 1,
      "tx_pdos": [ { "transmission": 1, "entries": [
        { "index": "0x6041", "type": "UNSIGNED16", "iec_location": "%IW40" },
        { "index": "0x6064", "type": "INTEGER32", "iec_location": "%ID40" } ] } ],
      "rx_pdos": [ { "entries": [ { "index": "0x6040", "type": "UNSIGNED16", "iec_location": "%QW40" } ] } ]
    }
  ]
})";
}

// The device's own view of its configuration: 0x1020:1/2, the TPDO 1
// mapping and transmission type, read on its thread.
struct DeviceView {
  uint32_t date = 0, time = 0, map0 = 0, map1 = 0, map2 = 0, trans = 0;
};

DeviceView read_device(Sim& sim, uint8_t id) {
  auto v = std::make_shared<DeviceView>();
  auto done = std::make_shared<std::atomic<bool>>(false);
  sim.OnSlave(id, [v, done](canopen::BasicSlave& b) {
    auto& s = static_cast<VendorDriveSlave&>(b);
    v->date = s.Get<uint32_t>(0x1020, 1);
    v->time = s.Get<uint32_t>(0x1020, 2);
    v->map0 = s.Get<uint8_t>(0x1A00, 0);
    v->map1 = s.Get<uint32_t>(0x1A00, 1);
    v->map2 = s.Get<uint32_t>(0x1A00, 2);
    v->trans = s.Get<uint8_t>(0x1800, 2);
    *done = true;
  });
  sim.RunUntil([done] { return done->load(); }, seconds(2));
  return *v;
}

// Hardware task 5.1 of add-config-check, on a virtual bus: boot, boot again
// (device reset: nothing downloaded), then a power cycle (a new device with
// only its saved memory): nothing downloaded again, the device kept the
// configuration, and the PLC data moves throughout.
TEST(sim_config_check_servo_drive) {
  clear_logs();
  auto mem = std::make_shared<StoredConfig>();
  std::string dir = make_dir(servo_json(), {{kServoEds, drive_eds(kServoEds)}, {"device.eds", servo_device_eds()}});
  static Sim* sim;
  sim = new Sim(dir);
  if (!sim->ok()) {
    CHECK(sim->ok());
    return;
  }
  // Round trip: %QW40 := %IW40 + 1, through controlword, statusword and
  // position (statusword x 1000), so the counter only moves while both PDOs do.
  sim->SetProgram([](fake_runtime::Image& plc) { plc.int_out[40] = static_cast<IEC_UINT>(plc.int_in[40] + 1); });
  sim->StartVendorDrive(3, dir + "/device.eds", mem, true);
  sim->net().Start();
  auto running = [] {
    uint16_t mark = sim->uw(40);
    return sim->RunUntil([mark] {
      int32_t pos = static_cast<int32_t>(sim->plc().dint_in[40]);
      return sim->status() && sim->state() == 5 && static_cast<uint16_t>(sim->uw(40) - mark) > 5 && pos > 0 &&
             pos % 1000 == 0;
    }, seconds(5));
  };
  CHECK_MSG(running(), "state " + std::to_string(sim->state()) + ", %IW40 " + std::to_string(sim->uw(40)));
  CHECK(logged("node 3 (servo): configuring ("));
  CHECK(logged("node 3 (servo): EDS servo-drive.eds: 2 lint findings accepted (not in the communication "
               "objects, or only about limits): 0x60C0: LowLimit overflow in [60C0]; 0x60C2 sub 2"));
  // dcfgen's own copy of the lint findings is not logged again.
  CHECK(!logged("dcfgen: LowLimit overflow"));
  CHECK_MSG(mem->saves == 1, std::to_string(mem->saves));
  int first = sim->downloads(3);
  std::printf("    first boot: %d SDO downloads, saved\n", first);
  CHECK(first > 3);
  DeviceView before = read_device(*sim, 3);
  CHECK(before.date != 0 || before.time != 0);
  CHECK_MSG(before.map0 == 2 && before.map1 == 0x60410010u && before.map2 == 0x60640020u,
            "0x1A00 " + std::to_string(before.map0));
  CHECK(before.trans == 1);

  // Second boot: the device is reset.
  clear_logs();
  sim->OnSlave(3, [](canopen::BasicSlave& s) { s.Reset(); });
  CHECK(sim->RunUntil([] { return logged("configuration unchanged"); }, seconds(10)));
  CHECK(logged("node 3 (servo): configuration unchanged (0x1020 matches), nothing downloaded"));
  CHECK(running());
  CHECK_MSG(sim->downloads(3) == first, std::to_string(sim->downloads(3)) + " vs " + std::to_string(first));

  // Power cycle: the device goes away and comes back with what it saved.
  clear_logs();
  sim->KillSlave(3);
  CHECK(sim->RunUntil([] { return !sim->status(); }, seconds(5)));
  sim->StartVendorDrive(3, dir + "/device.eds", mem, true);
  CHECK(sim->RunUntil([] { return logged("configuration unchanged"); }, seconds(10)));
  CHECK(running());
  CHECK_MSG(sim->downloads(3) == first, std::to_string(sim->downloads(3)) + " vs " + std::to_string(first));
  DeviceView after = read_device(*sim, 3);
  CHECK(after.date == before.date && after.time == before.time);
  CHECK(after.map0 == 2 && after.map1 == 0x60410010u && after.map2 == 0x60640020u && after.trans == 1);
  CHECK(mem->saves == 1);
  CHECK(!logged("boot failed"));
  std::printf("    reset and power cycle: nothing downloaded, 0x1020 = %08x %08x kept\n", after.date, after.time);
  delete sim;
}

// Hardware task 4.1 of add-device-pdo-mapping, on a virtual bus: the
// fixed drive (fixed mapping and read-only COB-IDs on every PDO, node
// guarding instead of heartbeat). The config uses TPDO 1 (statusword), RPDO 1
// (controlword) and only the second object of RPDO 2 (0x2301:2 of
// 0x2301:1 + 0x2301:2). The master must write no PDO object, and 0x2301:1
// goes out as 0.
// The EDS lint stops the load on a broken communication object, and on any
// finding with the pre-contract strict_eds: true; the CAN side never starts.
TEST(sim_eds_lint_stops_load) {
  std::string fixtures = std::string(FIXTURES_DIR) + "/eds/lint/";
  struct Case {
    const char* eds;
    const char* master;
    const char* error;
  } cases[] = {
      {"comm-broken.eds", "", "node 2 (pingpong): EDS cpp-slave.eds fails dcfgen's lint (eds_lint \"communication\"): "
                              "0x1A00 sub 0: DataType should be UNSIGNED8 in [1A00sub0]; eds_lint: \"off\" would accept it"},
      {"signed-hex.eds", ", \"strict_eds\": true",
       "EDS cpp-slave.eds fails dcfgen's lint (eds_lint \"all\"): 0x6061: HighLimit overflow in [6061]"},
  };
  for (const auto& c : cases) {
    clear_logs();
    std::string json = pingpong_json();
    std::string from = "\"sync_period_us\": 20000";
    json.replace(json.find(from), from.size(), from + c.master);
    std::string dir = make_dir(json, {{"cpp-slave.eds", read(fixtures + c.eds)}});
    Sim sim(dir);
    CHECK_MSG(!sim.ok(), c.eds);
    CHECK_MSG(logged(c.error), c.eds);
  }
  // The same broken file with eds_lint "off" loads, with the finding as a warning.
  clear_logs();
  std::string json = pingpong_json();
  std::string from = "\"sync_period_us\": 20000";
  json.replace(json.find(from), from.size(), from + ", \"eds_lint\": \"off\"");
  Sim sim(make_dir(json, {{"cpp-slave.eds", read(fixtures + "comm-broken.eds")}}));
  CHECK(sim.ok());
  CHECK(logged("EDS cpp-slave.eds: 1 lint finding accepted (eds_lint \"off\"): 0x1A00 sub 0"));
}

TEST(sim_fixed_pdo_mapping_fixed_drive) {
  clear_logs();
  const char* eds = "fixed-drive.eds";
  std::string json = R"({
  "schema_version": 1,
  "adapter": { "type": "socketcan", "interface": "sim", "bitrate": 500000 },
  "master": { "node_id": 1, "sync_period_us": 20000 },
  "nodes": [
    {
      "node_id": 4, "name": "fixed", "eds": "fixed-drive.eds",
      "guard_time_ms": 100, "life_time_factor": 3,
      "status_location": "%IX10.0", "state_location": "%IB20",
      "tx_pdos": [ { "entries": [ { "index": "0x6041", "type": "UNSIGNED16", "iec_location": "%IW40" } ] } ],
      "rx_pdos": [
        { "entries": [ { "index": "0x6040", "type": "UNSIGNED16", "iec_location": "%QW40" } ] },
        { "entries": [ { "index": "0x2301", "subindex": 2, "type": "INTEGER32", "iec_location": "%QD40" } ] } ]
    }
  ]
})";
  std::string dir = make_dir(json, {{eds, drive_eds(eds)}});
  static Sim* sim;
  sim = new Sim(dir);
  if (!sim->ok()) {
    CHECK(sim->ok());
    return;
  }
  CHECK(sim->cfg().nodes[0].tx_pdos[0].device_mapping && sim->cfg().nodes[0].rx_pdos[1].device_mapping);
  sim->SetProgram([](fake_runtime::Image& plc) {
    plc.int_out[40] = 0x0006;
    plc.dint_out[40] = static_cast<IEC_UDINT>(-1234);
  });
  VendorDriveSlave* drive = sim->StartVendorDrive(4, dir + "/" + eds, std::make_shared<StoredConfig>(), false);
  sim->net().Start();
  CHECK(sim->RunUntil([] { return sim->status() && sim->state() == 5; }, seconds(5)));
  CHECK(logged("node 4 (fixed) is operational"));
  CHECK(logged("node 4 (fixed): EDS fixed-drive.eds: 1 lint finding accepted"));
  CHECK_MSG(sim->RunUntil([] { return sim->uw(40) == 0x0006; }, seconds(2)), "%IW40 = " + std::to_string(sim->uw(40)));
  CHECK(sim->RunUntil([drive] { return drive->argument == -1234; }, seconds(2)));
  CHECK_MSG(drive->command == 0, std::to_string(drive->command));
  CHECK_MSG(sim->pdo_downloads(4) == 0, std::to_string(sim->pdo_downloads(4)));
  CHECK(!logged("aborted"));
  std::printf("    %d SDO downloads at boot, none to a PDO object; 0x2301:2 = %lld, 0x2301:1 = %d\n",
              sim->downloads(4), static_cast<long long>(drive->argument.load()), drive->command.load());
  delete sim;
}

// ---------------------------------------------------------------------------
// dcfgen options: mandatory nodes, start options, identity check

// Inserts `fields` at the start of the master object.
std::string with_master(std::string json, const std::string& fields) {
  size_t at = json.find("\"master\": { ") + std::string("\"master\": { ").size();
  return json.insert(at, fields);
}

// Inserts `fields` at the start of the node object with this name.
std::string with_node(std::string json, const std::string& name, const std::string& fields) {
  size_t at = json.find("\"name\": \"" + name + "\",");
  return json.insert(at, fields);
}

const char* kSecondNode = R"(,
    {
      "node_id": 3, "name": "second", "eds": "cpp-slave.eds",
      "heartbeat_ms": 50, "heartbeat_timeout_ms": 200,
      "status_location": "%IX10.1", "state_location": "%IB22",
      "tx_pdos": [ { "entries": [ { "index": "0x4001", "type": "UNSIGNED32", "iec_location": "%ID200" } ] } ],
      "rx_pdos": [ { "entries": [ { "index": "0x4000", "type": "UNSIGNED32", "iec_location": "%QD200" } ] } ]
    })";

// A missing mandatory node holds the whole network: the other node is
// started but no PDO data moves and its status bit stays FALSE; the master
// reads PRE-OPERATIONAL. Once the mandatory node boots, everything runs.
TEST(sim_mandatory_node_absent_then_present) {
  clear_logs();
  std::string json = with_master(pingpong_json(kSecondNode), "\"state_location\": \"%IB21\", ");
  json = with_node(json, "pingpong", "\"state_location\": \"%IB20\", ");
  json = with_node(json, "second", "\"mandatory\": true, ");
  std::string dir = make_dir(json, {{"cpp-slave.eds", slave_eds()}});
  static Sim* sim;
  sim = new Sim(dir);
  if (!sim->ok()) {
    CHECK(sim->ok());
    return;
  }
  auto master = [] { return static_cast<uint8_t>(sim->plc().byte_in[21]); };
  sim->StartSlave(2, dir + "/cpp-slave.eds");
  sim->net().Start();
  CHECK(sim->RunUntil([] { return sim->state() == 5; }, seconds(5)));
  sim->RunFor(milliseconds(3500));
  CHECK_MSG(master() == 127, std::to_string(master()));
  CHECK(!sim->status());
  CHECK(sim->in() == 0);
  CHECK(logged("node 3 (second) is mandatory and not answering: the master holds the whole network"));
  sim->StartSlave(3, dir + "/cpp-slave.eds");
  CHECK_MSG(sim->RunUntil([&] { return master() == 5 && sim->status(); }, seconds(20)), std::to_string(master()));
  CHECK(sim->RunUntil([] { return sim->in() > 5; }, seconds(5)));  // (the fake program only drives node 2)
  CHECK(sim->plc().bool_in[10][1] != 0);
  delete sim;
}

// A mandatory node that fails its boot (here: it is the wrong device) halts
// Lely's network boot-up for good; once it boots on a retry, the plugin
// starts the master.
TEST(sim_mandatory_node_failed_then_booted) {
  clear_logs();
  std::string json = with_master(pingpong_json(kSecondNode), "\"state_location\": \"%IB21\", ");
  json = with_node(json, "second", "\"mandatory\": true, \"serial_number\": 7, ");
  std::string dir = make_dir(json, {{"cpp-slave.eds", slave_eds()}});
  static Sim* sim;
  sim = new Sim(dir);
  if (!sim->ok()) {
    CHECK(sim->ok());
    return;
  }
  auto master = [] { return static_cast<uint8_t>(sim->plc().byte_in[21]); };
  sim->StartSlave(2, dir + "/cpp-slave.eds");
  sim->StartSlave(3, dir + "/cpp-slave.eds");  // serial number 0, not 7
  sim->net().Start();
  CHECK(sim->RunUntil([] { return logged("node 3 (second): wrong device: serial number 0"); }, seconds(5)));
  sim->RunFor(milliseconds(1500));
  CHECK_MSG(master() == 127, std::to_string(master()));
  CHECK(!sim->status());
  // The right device: same EDS with serial number 7.
  std::string eds = slave_eds();
  size_t sub4 = eds.find("[1018sub4]");
  eds.replace(eds.find("DefaultValue=0x00000000", sub4), 23, "DefaultValue=0x00000007");
  std::ofstream(dir + "/right.eds") << eds;
  sim->KillSlave(3);
  sim->StartSlave(3, dir + "/right.eds");
  CHECK_MSG(sim->RunUntil([&] { return master() == 5 && sim->status(); }, seconds(20)), std::to_string(master()));
  CHECK(logged("all mandatory nodes have booted: starting the master"));
  CHECK(sim->RunUntil([] { return sim->in() > 5; }, seconds(5)));
  delete sim;
}

// start_nodes: false: the master configures the node but leaves it
// PRE-OPERATIONAL; the master itself is OPERATIONAL.
TEST(sim_start_nodes_false) {
  clear_logs();
  std::string json = with_master(pingpong_json(), "\"state_location\": \"%IB21\", \"start_nodes\": false, ");
  json = with_node(json, "pingpong", "\"state_location\": \"%IB20\", ");
  std::string dir = make_dir(json, {{"cpp-slave.eds", mode_lock_eds()}});  // waits for NMT start
  static Sim* sim;
  sim = new Sim(dir);
  if (!sim->ok()) {
    CHECK(sim->ok());
    return;
  }
  sim->StartModeLockSlave(2, dir + "/cpp-slave.eds", false);
  sim->net().Start();
  CHECK(sim->RunUntil([] { return logged("it stays PRE-OPERATIONAL (master start_nodes is false)"); }, seconds(5)));
  sim->RunFor(milliseconds(1000));
  CHECK_MSG(sim->state() == 127, std::to_string(sim->state()));
  CHECK(sim->plc().byte_in[21] == 5);
  CHECK(!sim->status());
  CHECK(sim->in() == 0);
  delete sim;
}

// stop_all_nodes: losing a mandatory node stops the master and every other
// node; nothing is booted again.
TEST(sim_stop_all_nodes_on_mandatory_loss) {
  clear_logs();
  std::string json = with_master(pingpong_json(kSecondNode), "\"state_location\": \"%IB21\", \"stop_all_nodes\": true, ");
  json = with_node(json, "pingpong", "\"state_location\": \"%IB20\", \"mandatory\": true, ");
  std::string dir = make_dir(json, {{"cpp-slave.eds", slave_eds()}});
  static Sim* sim;
  sim = new Sim(dir);
  if (!sim->ok()) {
    CHECK(sim->ok());
    return;
  }
  auto master = [] { return static_cast<uint8_t>(sim->plc().byte_in[21]); };
  sim->StartSlave(2, dir + "/cpp-slave.eds");
  sim->StartSlave(3, dir + "/cpp-slave.eds");
  sim->net().Start();
  CHECK(sim->RunUntil([&] { return master() == 5 && sim->status() && sim->plc().bool_in[10][1]; }, seconds(5)));
  sim->KillSlave(2);
  CHECK_MSG(sim->RunUntil([&] { return master() == 4; }, seconds(2)), std::to_string(master()));
  CHECK_MSG(sim->RunUntil([] { return sim->plc().byte_in[22] == 4; }, seconds(2)),
            std::to_string(sim->plc().byte_in[22]));
  CHECK(!sim->plc().bool_in[10][1]);
  CHECK(logged("master is STOPPED"));
  sim->StartSlave(2, dir + "/cpp-slave.eds");
  sim->RunFor(seconds(3));
  CHECK(master() == 4);
  CHECK(!sim->status());
  delete sim;
}

// The RTD sensor with its EDS on the master side and a simulated
// device whose identity differs as given.
struct RtdIdentity {
  Sim* sim = nullptr;
  std::string dir;
  uint8_t boot_err() { return static_cast<uint8_t>(sim->plc().byte_in[31]); }
};

std::string rtd_device_eds(const std::string& from, const std::string& to) {
  std::string eds = blank_pdo_mapping(read(std::string(RTD_DIR) + "/rtd8.eds"));
  if (!from.empty())
    for (size_t at; (at = eds.find(from)) != std::string::npos;) eds.replace(at, from.size(), to);
  return eds;
}

void start_rtd(RtdIdentity& r, const std::string& node_fields, const std::string& device_eds) {
  std::string eds = read(std::string(RTD_DIR) + "/rtd8.eds");
  std::string cfg = read(std::string(RTD_DIR) + "/canopen_config.json");
  cfg.replace(cfg.find("\"vcan0\""), 7, "\"sim\"");
  cfg.replace(cfg.find("\"sync_period_us\": 100000"), 24, "\"sync_period_us\": 20000");
  cfg = with_master(cfg, "\"state_location\": \"%IB30\", ");
  cfg = with_node(cfg, "rtd", "\"boot_error_location\": \"%IB31\", " + node_fields);
  r.dir = make_dir(cfg, {{"rtd8.eds", eds}, {"device.eds", device_eds}});
  r.sim = new Sim(r.dir);
  CHECK(r.sim->ok());
  if (!r.sim->ok()) return;
  r.sim->StartSensor(5, r.dir + "/device.eds", {{0x7130, 1, 200, 260, 1}});
  r.sim->net().Start();
}

size_t count_logs(const std::string& needle) {
  size_t n = 0;
  for (const auto& l : logs()) n += l.find(needle) != std::string::npos;
  return n;
}

// A device with another product code: one "wrong device" line naming both
// values, no "not answering", boot error byte 'M' (77); after the right
// device is plugged in, it runs and the byte reads 0.
TEST(sim_wrong_product_code_reported_once) {
  clear_logs();
  static RtdIdentity r;
  start_rtd(r, "", rtd_device_eds("0x00000404", "0x00000405"));
  if (!r.sim->ok()) return;
  CHECK(r.sim->RunUntil([] { return r.boot_err() == 'M'; }, seconds(5)));
  r.sim->RunFor(seconds(5));  // several boot retries
  CHECK_MSG(count_logs("node 5 (rtd): wrong device: product code 1029 (0x00000405), expected 1028 "
                       "(0x00000404) from rtd8.eds") == 1,
            std::to_string(count_logs("wrong device")));
  CHECK(!logged("not answering"));
  CHECK(!logged("error status M"));
  CHECK(r.sim->plc().byte_in[30] == 5);  // nothing mandatory: the master runs
  CHECK(!r.sim->status());
  r.sim->KillSlave(5);
  std::ofstream(r.dir + "/device.eds") << rtd_device_eds("", "");
  r.sim->StartSensor(5, r.dir + "/device.eds", {{0x7130, 1, 200, 260, 1}});
  CHECK(r.sim->RunUntil([] { return r.sim->status(); }, seconds(20)));
  CHECK(r.boot_err() == 0);
  delete r.sim;
}

// A newer revision: refused by default (the EDS revision is expected, 'N'),
// accepted with "revision_number": 0.
TEST(sim_revision_check) {
  clear_logs();
  static RtdIdentity r;
  start_rtd(r, "", rtd_device_eds("0x00010003", "0x00010004"));
  if (!r.sim->ok()) return;
  CHECK(r.sim->RunUntil([] { return r.boot_err() == 'N'; }, seconds(5)));
  CHECK(r.sim->RunUntil([] { return logged("node 5 (rtd): wrong device: revision number 65540 (0x00010004), "
                                           "expected 65539 (0x00010003) from rtd8.eds"); },
                        seconds(2)));
  delete r.sim;

  clear_logs();
  start_rtd(r, "\"revision_number\": 0, ", rtd_device_eds("0x00010003", "0x00010004"));
  if (!r.sim->ok()) return;
  CHECK(r.sim->RunUntil([] { return r.sim->status(); }, seconds(5)));
  CHECK(r.boot_err() == 0);
  delete r.sim;
}

// A pinned serial number the device does not have: 'O' (79).
TEST(sim_serial_number_pinned) {
  clear_logs();
  static RtdIdentity r;
  start_rtd(r, "\"serial_number\": \"0x00001234\", ", rtd_device_eds("", ""));
  if (!r.sim->ok()) return;
  CHECK(r.sim->RunUntil([] { return r.boot_err() == 'O'; }, seconds(5)));
  CHECK(r.sim->RunUntil([] { return logged("node 5 (rtd): wrong device: serial number 0 (0x00000000), "
                                           "expected 4660 (0x00001234) from the configuration"); },
                        seconds(2)));
  r.sim->RunFor(seconds(1));
  CHECK(!r.sim->status());
  delete r.sim;
}

// A silent node reads 'B' (66) once it is reported as not answering.
TEST(sim_boot_error_byte_silent) {
  clear_logs();
  std::string json = with_node(pingpong_json(), "pingpong", "\"boot_error_location\": \"%IB31\", ");
  std::string dir = make_dir(json, {{"cpp-slave.eds", slave_eds()}});
  static Sim* sim;
  sim = new Sim(dir);
  if (!sim->ok()) {
    CHECK(sim->ok());
    return;
  }
  sim->net().Start();
  CHECK(sim->RunUntil([] { return logged("not answering"); }, seconds(5)));
  CHECK(sim->RunUntil([] { return sim->plc().byte_in[31] == 'B'; }, seconds(1)));
  sim->StartSlave(2, dir + "/cpp-slave.eds");
  CHECK(sim->RunUntil([] { return sim->status(); }, seconds(20)));
  CHECK(sim->plc().byte_in[31] == 0);
  delete sim;
}

// The ping-pong EDS with the program download objects of CiA 302-3 and a
// software version (0x1F56:1) of 1.
std::string firmware_eds() {
  std::string eds = slave_eds();
  eds.replace(eds.find("SupportedObjects=7\n"), 19, "SupportedObjects=11\n8=0x1F50\n9=0x1F51\n10=0x1F56\n11=0x1F57\n");
  auto arr = [](const char* idx, const char* name, const char* type, const char* access, const char* value) {
    std::string s = std::string("\n[") + idx + "]\nSubNumber=2\nParameterName=" + name + "\nObjectType=0x08\n\n[" + idx +
                    "sub0]\nParameterName=Highest sub-index supported\nDataType=0x0005\nAccessType=const\n"
                    "DefaultValue=1\nPDOMapping=0\n\n[" + idx + "sub1]\nParameterName=" + name + " 1\nDataType=" +
                    type + "\nAccessType=" + access + "\nPDOMapping=0\n";
    if (*value) s += std::string("DefaultValue=") + value + "\n";
    return s;
  };
  return eds + arr("1F50", "Program data", "0x000F", "rw", "") + arr("1F51", "Program control", "0x0005", "rw", "1") +
         arr("1F56", "Program software identification", "0x0007", "ro", "1") +
         arr("1F57", "Flash status identification", "0x0007", "ro", "0");
}

// software_version 2 and a node reporting 1: Lely's master downloads the
// file (0x1F58 -> the node's 0x1F50) before configuring the node, which then
// runs.
TEST(sim_firmware_download) {
  clear_logs();
  std::string json = with_node(pingpong_json(), "pingpong",
                               "\"software_file\": \"fw/node2.bin\", \"software_version\": 2, ");
  std::string fw("\x02\x00\x00\x00new firmware", 16);
  std::string dir = make_dir(json, {{"cpp-slave.eds", firmware_eds()}});
  mkdir((dir + "/fw").c_str(), 0755);
  std::ofstream(dir + "/fw/node2.bin") << fw;
  static Sim* sim;
  sim = new Sim(dir);
  if (!sim->ok()) {
    CHECK(sim->ok());
    return;
  }
  sim->StartFirmwareSlave(2, dir + "/cpp-slave.eds");
  sim->net().Start();
  CHECK(sim->RunUntil([] { return sim->status() && sim->in() > 5; }, seconds(20)));
  CHECK(logged("node 2 (pingpong): configuring"));
  // Read the slave's version back over SDO: the download happened.
  uint32_t version = 0;
  bool done = false;
  sim->net().SubmitRead<uint32_t>(sim->exec(), 2, 0x1F56, 1,
                                  [&](uint8_t, uint16_t, uint8_t, std::error_code ec, uint32_t v) {
                                    if (!ec) version = v;
                                    done = true;
                                  });
  CHECK(sim->RunUntil([&] { return done; }, seconds(2)));
  CHECK_MSG(version == 2, std::to_string(version));
  delete sim;
}

// canopen-node-supervision: emergency messages, logged and in %IW30 / %IB31.
TEST(sim_emcy) {
  clear_logs();
  std::string eds = read(std::string(RTD_DIR) + "/rtd8.eds");
  std::string cfg = read(std::string(RTD_DIR) + "/canopen_config.json");
  cfg.replace(cfg.find("\"vcan0\""), 7, "\"sim\"");
  cfg.replace(cfg.find("\"sync_period_us\": 100000"), 24, "\"sync_period_us\": 20000");
  cfg.insert(cfg.find("\"status_location\""), "\"emcy_code_location\": \"%IW30\", \"error_register_location\": \"%IB31\", ");
  std::string dir = make_dir(cfg, {{"rtd8.eds", eds}});
  static Sim* sim;
  sim = new Sim(dir);
  CHECK(sim->ok());
  if (!sim->ok()) return;
  sim->StartSensor(5, dir + "/rtd8.eds", {});
  sim->net().Start();
  CHECK(sim->RunUntil([] { return sim->status(); }, seconds(5)));
  CHECK(sim->uw(30) == 0 && sim->ib(31) == 0);

  // A fault: logged with its class, in the inputs, the node stays up.
  sim->OnSensor(5, [](SensorSlave& s) {
    const uint8_t msef[5] = {1, 2, 3, 4, 5};
    s.SendEmcy(0x4210, 0x08, msef);
  });
  CHECK_MSG(sim->RunUntil([] { return sim->uw(30) == 0x4210; }, seconds(2)), std::to_string(sim->uw(30)));
  CHECK(sim->ib(31) == 0x09);  // the device always adds bit 0 (generic error)
  CHECK(sim->RunUntil([] {
    return logged("node 5 (rtd): EMCY 0x4210 (temperature), error register 0x09, manufacturer bytes 01 02 03 04 05");
  }, seconds(1)));
  CHECK(sim->net().IsOperational(5) && sim->status());

  // A flood: the first EMCY of the second are logged one by one, the rest
  // go into one summary line with the latest code; the inputs follow all.
  sim->RunFor(milliseconds(1100));  // a fresh one-second window
  clear_logs();
  sim->OnSensor(5, [](SensorSlave& s) {
    for (int i = 0; i < 50; ++i) s.SendEmcy(0x4210, 0x08);
    s.SendEmcy(0x5000, 0x80);
  });
  CHECK(sim->RunUntil([] { return logged("more EMCY in the last second"); }, seconds(3)));
  CHECK_MSG(count_logs("EMCY 0x4210") == Network::kLoggedEmcyPerSecond, std::to_string(count_logs("EMCY 0x4210")));
  CHECK(logged("node 5 (rtd): 46 more EMCY in the last second, latest 0x5000 (device hardware), "
               "error register 0x89"));  // 0x08 still active, plus bit 0
  CHECK(count_logs("more EMCY in the last second") == 1);
  CHECK(sim->RunUntil([] { return sim->uw(30) == 0x5000 && sim->ib(31) == 0x89; }, seconds(1)));

  // Error reset: both read 0.
  sim->OnSensor(5, [](SensorSlave& s) { s.ResetEmcy(); });
  CHECK(sim->RunUntil([] { return sim->uw(30) == 0 && sim->ib(31) == 0; }, seconds(2)));
  CHECK(sim->RunUntil([] { return logged("node 5 (rtd): EMCY error reset"); }, seconds(1)));

  // A fault, then the node is lost: the code is held. It comes back: its
  // boot-up message clears it.
  sim->OnSensor(5, [](SensorSlave& s) { s.SendEmcy(0x3120, 0x04); });
  CHECK(sim->RunUntil([] { return sim->uw(30) == 0x3120; }, seconds(2)));
  sim->KillSlave(5);
  CHECK(sim->RunUntil([] { return !sim->status(); }, seconds(2)));
  sim->RunFor(milliseconds(300));
  CHECK(sim->uw(30) == 0x3120 && sim->ib(31) == 0x05);
  sim->StartSensor(5, dir + "/rtd8.eds", {});
  CHECK(sim->RunUntil([] { return sim->uw(30) == 0 && sim->ib(31) == 0; }, seconds(5)));
  CHECK(sim->RunUntil([] { return sim->status(); }, seconds(20)));

  // An EMCY from a node that is not configured: one warning, then silence.
  sim->StartSensor(9, dir + "/rtd8.eds", {});
  sim->RunFor(milliseconds(200));
  sim->OnSensor(9, [](SensorSlave& s) { s.SendEmcy(0x5000, 0x01); });
  CHECK(sim->RunUntil([] { return logged("EMCY from node 9, which is not in the configuration"); }, seconds(2)));
  sim->OnSensor(9, [](SensorSlave& s) { s.SendEmcy(0x6000, 0x01); });
  sim->RunFor(milliseconds(300));
  CHECK(count_logs("node 9") == 1);
  CHECK(sim->uw(30) == 0);
  delete sim;
}

// SDO variables against the simulated RTD sensor (canopen-sdo-variables):
// a read after boot, a periodic read, an owned write (and again after a
// reset from the NMT byte), a triggered write, a refused value, a timeout
// and a lost node.
namespace {

std::string rtd_sim_config(const std::string& node_fields) {
  std::string cfg = read(std::string(RTD_DIR) + "/canopen_config.json");
  cfg.replace(cfg.find("\"vcan0\""), 7, "\"sim\"");
  cfg.replace(cfg.find("\"sync_period_us\": 100000"), 24, "\"sync_period_us\": 20000");
  cfg.insert(cfg.find("\"status_location\""), "\"state_location\": \"%IB20\", " + node_fields);
  return cfg;
}

// The sensor's own value of 0x6110 sub `sub` (-1 until read).
int sensor_6110(Sim* sim, uint8_t sub) {
  auto value = std::make_shared<std::atomic<int>>(-1);
  sim->OnSensor(5, [value, sub](SensorSlave& s) { *value = s.Get<uint16_t>(0x6110, sub); });
  sim->RunUntil([value] { return *value >= 0; }, seconds(1));
  return *value;
}

}  // namespace

TEST(sim_sdo_variables) {
  clear_logs();
  std::string eds = read(std::string(RTD_DIR) + "/rtd8.eds");
  std::string cfg = rtd_sim_config(R"("nmt_command_location": "%QB30", "sdo_variables": [
      { "name": "vendor", "index": "0x1018", "subindex": 1, "type": "UNSIGNED32", "direction": "read",
        "iec_location": "%ID200", "status_location": "%IB200" },
      { "name": "t0", "index": "0x7130", "subindex": 1, "type": "INTEGER16", "direction": "read",
        "iec_location": "%IW200", "period_ms": 50, "timeout_ms": 50 },
      { "name": "type0", "index": "0x6110", "subindex": 1, "type": "UNSIGNED16", "direction": "write",
        "iec_location": "%QW200", "status_location": "%IB201", "abort_code_location": "%ID201" },
      { "name": "type1", "index": "0x6110", "subindex": 2, "type": "UNSIGNED16", "direction": "write",
        "iec_location": "%QW201", "trigger_location": "%QX20.0", "status_location": "%IB202" },
      { "name": "type2", "index": "0x6110", "subindex": 3, "type": "UNSIGNED16", "direction": "read",
        "iec_location": "%IW202", "trigger_location": "%QX20.1", "status_location": "%IB203",
        "abort_code_location": "%ID203", "timeout_ms": 50 }
    ], )");
  std::string dir = make_dir(cfg, {{"rtd8.eds", eds}});
  static Sim* sim;
  sim = new Sim(dir);
  CHECK(sim->ok());
  if (!sim->ok()) return;
  static std::atomic<int> type0{31}, type1{32}, nmt{0};
  static std::atomic<bool> trig0{false}, trig1{false};
  sim->SetProgram([](fake_runtime::Image& p) {
    p.int_out[200] = static_cast<IEC_UINT>(type0.load());
    p.int_out[201] = static_cast<IEC_UINT>(type1.load());
    p.bool_out[20][0] = trig0.load();
    p.bool_out[20][1] = trig1.load();
    p.byte_out[30] = static_cast<IEC_BYTE>(nmt.load());
  });
  sim->StartSensor(5, dir + "/rtd8.eds", {{0x7130, 1, 200, 260, 1}});
  sim->net().Start();
  CHECK(sim->RunUntil([] { return sim->status(); }, seconds(5)));

  // Read once after boot: the vendor ID (0x00F0F0F0 in the EDS), status done.
  CHECK_MSG(sim->RunUntil([] { return sim->plc().dint_in[200] == 0xF0F0F0 && sim->ib(200) == 2; }, seconds(2)),
            std::to_string(sim->plc().dint_in[200]) + " " + std::to_string(sim->ib(200)));
  // Periodic read follows the moving temperature.
  CHECK(sim->RunUntil([] { return sim->iw(200) >= 200; }, seconds(2)));
  int16_t first = sim->iw(200);
  CHECK(sim->RunUntil([first] { return sim->iw(200) != first; }, seconds(2)));

  // Owned write: the startup SDO wrote 30 at boot, the program's 31 follows.
  CHECK(sim->RunUntil([] { return sim->ib(201) == 2; }, seconds(2)));
  CHECK_MSG(sensor_6110(sim, 1) == 31, std::to_string(sensor_6110(sim, 1)));
  type0 = 33;
  CHECK(sim->RunUntil([] { return sensor_6110(sim, 1) == 33; }, seconds(2)));
  // A value the device refuses (limits 0x1E-0x21): aborted, logged once.
  type0 = 0x40;
  CHECK(sim->RunUntil([] { return sim->ib(201) == 3; }, seconds(2)));
  uint32_t abort = sim->plc().dint_in[201];
  CHECK_MSG(abort == 0x06090031 || abort == 0x06090030, std::to_string(abort));
  sim->RunFor(milliseconds(300));
  CHECK(count_logs("node 5 (rtd): SDO variable 0x6110:1 (type0): write aborted") == 1);
  CHECK(sensor_6110(sim, 1) == 33);
  CHECK(sim->net().IsOperational(5));
  type0 = 31;
  CHECK(sim->RunUntil([] { return sim->ib(201) == 2 && sim->plc().dint_in[201] == 0; }, seconds(2)));

  // Triggered write: nothing until the rising edge, then once.
  CHECK(sensor_6110(sim, 2) == 30);
  CHECK(sim->ib(202) == 0);
  trig0 = true;
  CHECK(sim->RunUntil([] { return sim->ib(202) == 2; }, seconds(2)));
  CHECK(sensor_6110(sim, 2) == 32);
  type1 = 33;
  sim->RunFor(milliseconds(200));
  CHECK(sensor_6110(sim, 2) == 32);
  trig0 = false;

  // Reset from the NMT byte: the node boots again (startup SDOs write 30)
  // and the owned value is written again.
  nmt = 129;
  CHECK(sim->RunUntil([] { return sim->state() != 5; }, seconds(2)));
  CHECK(sim->RunUntil([] { return sim->state() == 5 && sim->status(); }, seconds(10)));
  nmt = 0;
  CHECK(sim->RunUntil([] { return sensor_6110(sim, 1) == 31; }, seconds(2)));
  CHECK(sensor_6110(sim, 2) == 30);  // triggered: not written again
  CHECK(count_logs("NMT RESET NODE (from the program)") == 1);

  // Timeout: the sensor is unplugged; a triggered read before loss detection
  // gets no answer within 50 ms. The periodic read also times out after 50 ms,
  // so one still in flight at the unplug cannot hold the triggered read back
  // until the loss (300 ms) is detected.
  sim->Unplug(5);
  trig1 = true;
  CHECK_MSG(sim->RunUntil([] { return sim->ib(203) == 3; }, seconds(1)), std::to_string(sim->ib(203)));
  CHECK_MSG(sim->plc().dint_in[203] == 0x05040000, std::to_string(sim->plc().dint_in[203]));
  // Lost: automatic entries wait (4), values are held.
  CHECK(sim->RunUntil([] { return !sim->status(); }, seconds(2)));
  CHECK(sim->RunUntil([] { return sim->ib(200) == 4 && sim->ib(201) == 4; }, seconds(1)));
  CHECK(sim->plc().dint_in[200] == 0xF0F0F0);
  // A trigger while lost is dropped (4) and not sent when the node returns.
  trig0 = true;
  sim->RunFor(milliseconds(50));
  CHECK(sim->ib(202) == 4);
  sim->Replug(5);
  CHECK(sim->RunUntil([] { return sim->status(); }, seconds(20)));
  CHECK(sim->RunUntil([] { return sim->ib(200) == 2 && sim->ib(201) == 2; }, seconds(2)));
  CHECK(sim->ib(202) == 4);
  CHECK(sensor_6110(sim, 2) == 30);  // the dropped trigger wrote nothing
  trig0 = false;
  trig1 = false;
  delete sim;
}

// The NMT command byte (canopen-node-supervision): hold STOPPED and
// PRE-OPERATIONAL, release, a held node that power-cycles, an unknown code.
TEST(sim_nmt_command_byte) {
  clear_logs();
  std::string eds = read(std::string(RTD_DIR) + "/rtd8.eds");
  std::string dir = make_dir(rtd_sim_config(R"("nmt_command_location": "%QB30", )"), {{"rtd8.eds", eds}});
  static Sim* sim;
  sim = new Sim(dir);
  CHECK(sim->ok());
  if (!sim->ok()) return;
  static std::atomic<int> nmt{0};
  sim->SetProgram([](fake_runtime::Image& p) { p.byte_out[30] = static_cast<IEC_BYTE>(nmt.load()); });
  sim->StartSensor(5, dir + "/rtd8.eds", {{0x7130, 1, 200, 260, 1}});
  sim->net().Start();
  CHECK(sim->RunUntil([] { return sim->state() == 5 && sim->status(); }, seconds(5)));

  // Stop: STOPPED, status off, inputs held, no reboot.
  CHECK(sim->RunUntil([] { return sim->iw(100) != 0; }, seconds(2)));
  nmt = 2;
  CHECK(sim->RunUntil([] { return sim->state() == 4; }, seconds(2)));
  CHECK(!sim->status());
  int16_t held = sim->iw(100);
  sim->RunFor(milliseconds(1500));
  CHECK(sim->state() == 4 && sim->iw(100) == held);
  CHECK(!logged("node 5 (rtd): retrying boot"));
  CHECK(logged("node 5 (rtd): NMT STOP (held by the program)"));
  // Release: OPERATIONAL again, PDOs flow.
  nmt = 0;
  CHECK(sim->RunUntil([] { return sim->state() == 5 && sim->status(); }, seconds(2)));
  CHECK(sim->RunUntil([held] { return sim->iw(100) != held; }, seconds(2)));

  // Hold PRE-OPERATIONAL, then the node power-cycles: configured, then held
  // again.
  nmt = 128;
  CHECK(sim->RunUntil([] { return sim->state() == 127; }, seconds(2)));
  CHECK(!sim->status());
  sim->KillSlave(5);
  CHECK(sim->RunUntil([] { return sim->state() == 0; }, seconds(2)));
  clear_logs();
  sim->StartSensor(5, dir + "/rtd8.eds", {{0x7130, 1, 200, 260, 1}});
  CHECK(sim->RunUntil([] { return logged("node 5 (rtd): configuring"); }, seconds(20)));
  CHECK(sim->RunUntil([] { return logged("NMT ENTER PRE-OPERATIONAL (held by the program)"); }, seconds(5)));
  sim->RunFor(milliseconds(500));
  CHECK_MSG(sim->state() == 127, std::to_string(sim->state()));
  CHECK(!sim->status());
  nmt = 1;
  CHECK(sim->RunUntil([] { return sim->state() == 5 && sim->status(); }, seconds(2)));

  // An unknown code: one warning, the node keeps running.
  nmt = 7;
  sim->RunFor(milliseconds(300));
  CHECK(count_logs("NMT command byte 7 is not a command") == 1);
  CHECK(sim->state() == 5 && sim->status());
  nmt = 0;
  delete sim;
}


// ---------------------------------------------------------------------------
// Diagnostics channel (canopen-online-diagnostics)

namespace {

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
std::string str(const cJSON* obj, const char* key) {
  const cJSON* v = field(obj, key);
  return cJSON_IsString(v) ? v->valuestring : "";
}
bool ok(const cJSON* a) { return cJSON_IsTrue(field(a, "ok")); }
const cJSON* result(const cJSON* a) { return field(a, "result"); }
const cJSON* node_of(const cJSON* status, unsigned id) {
  const cJSON* n;
  cJSON_ArrayForEach(n, field(result(status), "nodes")) if (num(n, "node_id") == id) return n;
  return nullptr;
}

}  // namespace

TEST(sim_diag_status_emcy_sdo_nmt) {
  clear_logs();
  std::string eds = read(std::string(RTD_DIR) + "/rtd8.eds");
  std::string dir = make_dir(rtd_sim_config(R"("nmt_command_location": "%QB30", "sdo_variables": [
      { "name": "type0", "index": "0x6110", "subindex": 1, "type": "UNSIGNED16", "direction": "write",
        "iec_location": "%QW200" } ], )"),
                             {{"rtd8.eds", eds}});
  static Sim* sim;
  sim = new Sim(dir);
  CHECK(sim->ok());
  if (!sim->ok()) return;
  static std::atomic<int> nmt{0};
  sim->SetProgram([](fake_runtime::Image& p) {
    p.int_out[200] = 31;
    p.byte_out[30] = static_cast<IEC_BYTE>(nmt.load());
  });
  sim->EnableDiag();
  sim->StartSensor(5, dir + "/rtd8.eds", {{0x7130, 1, 200, 260, 1}});
  sim->net().Start();
  CHECK(sim->RunUntil([] { return sim->state() == 5 && sim->status(); }, seconds(5)));

  // Status without any diagnostic locations beyond the state byte.
  cJSON* a = sim->Ask(diag_req("status"));
  CHECK(ok(a));
  const cJSON* n5 = node_of(a, 5);
  CHECK(n5 && num(n5, "state") == 5 && cJSON_IsTrue(field(n5, "status")) && cJSON_IsTrue(field(n5, "booted")));
  CHECK(str(n5, "hold") == "none" && cJSON_IsNull(field(n5, "boot_error")));
  CHECK(cJSON_GetArraySize(field(n5, "sdo_variables")) == 1);
  CHECK(num(field(result(a), "master"), "state") == 5);
  CHECK(str(result(a), "config_sha256").size() == 64);
  cJSON_Delete(a);

  // EMCY history: three faults then the reset, newest first.
  sim->OnSensor(5, [](SensorSlave& s) {
    for (int i = 0; i < 3; ++i) s.SendEmcy(0x5030, 0x01);
    s.ResetEmcy();
  });
  CHECK(sim->RunUntil([] { return logged("EMCY error reset"); }, seconds(2)));
  a = sim->Ask(diag_req("emcy", 5));
  const cJSON* list = field(result(a), "emcy");
  CHECK_MSG(cJSON_GetArraySize(list) == 4, std::to_string(cJSON_GetArraySize(list)));
  CHECK(num(cJSON_GetArrayItem(list, 0), "code") == 0);
  CHECK(num(cJSON_GetArrayItem(list, 1), "code") == 0x5030 && num(cJSON_GetArrayItem(list, 3), "code") == 0x5030);
  CHECK(str(cJSON_GetArrayItem(list, 1), "time").size() == 24);
  cJSON_Delete(a);
  // A burst beyond the history keeps the newest 16.
  sim->OnSensor(5, [](SensorSlave& s) {
    for (int i = 0; i < 40; ++i) s.SendEmcy(static_cast<uint16_t>(0x6000 + i), 0x01);
  });
  sim->RunFor(milliseconds(500));
  a = sim->Ask(diag_req("emcy", 5));
  list = field(result(a), "emcy");
  CHECK(cJSON_GetArraySize(list) == 16);
  CHECK_MSG(num(cJSON_GetArrayItem(list, 0), "code") == 0x6000 + 39, std::to_string(num(cJSON_GetArrayItem(list, 0), "code")));
  CHECK(num(cJSON_GetArrayItem(list, 15), "code") == 0x6000 + 24);
  cJSON_Delete(a);

  // Manual SDO read: the device name, a missing object, an absent node.
  a = sim->Ask(diag_req("sdo_read", 5, 0x1008, 0));
  CHECK(ok(a) && cJSON_IsTrue(field(result(a), "success")));
  CHECK_MSG(str(result(a), "data") == hex_bytes(std::vector<uint8_t>{'R', 'T', 'D', '-', '8'}),
            str(result(a), "data"));
  cJSON_Delete(a);
  a = sim->Ask(diag_req("sdo_read", 5, 0x2100, 0));
  CHECK(ok(a) && num(result(a), "abort_code") == 0x06020000);
  cJSON_Delete(a);
  DiagRequest absent = diag_req("sdo_read", 40, 0x1000, 0);
  absent.timeout_ms = 200;
  auto t0 = steady_clock::now();
  a = sim->Ask(absent);
  CHECK(ok(a) && str(result(a), "error") == "timeout");
  CHECK(steady_clock::now() - t0 < milliseconds(1500));
  cJSON_Delete(a);

  // Manual SDO write, read back; the owned SDO variable writes the
  // program's value again after the node's next boot.
  DiagRequest w = diag_req("sdo_write", 5, 0x6110, 1);
  w.data = {0x1E, 0x00};
  a = sim->Ask(w);
  CHECK(ok(a) && cJSON_IsTrue(field(result(a), "success")));
  cJSON_Delete(a);
  CHECK(logged("node 5: SDO write to 0x6110 sub 1 (2 bytes: 1E 00) from diagnostics client 127.0.0.1"));
  a = sim->Ask(diag_req("sdo_read", 5, 0x6110, 1));
  CHECK(str(result(a), "data") == "1E 00");
  cJSON_Delete(a);

  // Manual NMT: stop holds the node, no reboot.
  DiagRequest stop = diag_req("nmt", 5);
  stop.command = "stop";
  a = sim->Ask(stop);
  CHECK(ok(a));
  cJSON_Delete(a);
  CHECK(sim->RunUntil([] { return sim->state() == 4; }, seconds(2)));
  CHECK(!sim->status());
  sim->RunFor(milliseconds(1200));
  CHECK(sim->state() == 4);
  CHECK(!logged("node 5 (rtd): retrying boot"));
  CHECK(logged("NMT STOP (held by a diagnostics client)"));
  a = sim->Ask(diag_req("status"));
  CHECK(str(node_of(a, 5), "hold") == "stopped" && str(node_of(a, 5), "hold_by") == "operator");
  cJSON_Delete(a);
  // The program's byte changes afterwards: newest wins, the node runs.
  nmt = 1;
  CHECK(sim->RunUntil([] { return sim->state() == 5 && sim->status(); }, seconds(2)));
  // Operator PRE-OPERATIONAL, released by start.
  DiagRequest pre = diag_req("nmt", 5);
  pre.command = "preop";
  cJSON_Delete(sim->Ask(pre));
  CHECK(sim->RunUntil([] { return sim->state() == 127; }, seconds(2)));
  DiagRequest start = diag_req("nmt", 5);
  start.command = "start";
  cJSON_Delete(sim->Ask(start));
  CHECK(sim->RunUntil([] { return sim->state() == 5 && sim->status(); }, seconds(2)));
  // Reset: the node boots again and the owned variable is written again.
  DiagRequest reset = diag_req("nmt", 5);
  reset.command = "reset";
  clear_logs();
  cJSON_Delete(sim->Ask(reset));
  CHECK(logged("node 5 (rtd): NMT RESET NODE (from diagnostics client 127.0.0.1)"));
  CHECK(sim->RunUntil([] { return logged("node 5 (rtd): configuring"); }, seconds(5)));
  CHECK(sim->RunUntil([] { return sim->state() == 5 && sim->status(); }, seconds(20)));
  sim->RunFor(milliseconds(300));
  a = sim->Ask(diag_req("sdo_read", 5, 0x6110, 1));
  CHECK_MSG(str(result(a), "data") == "1F 00", str(result(a), "data"));
  cJSON_Delete(a);
  // Unconfigured node: refused.
  DiagRequest other = diag_req("nmt", 40);
  other.command = "reset";
  a = sim->Ask(other);
  CHECK(!ok(a));
  cJSON_Delete(a);
  nmt = 0;
  delete sim;
}

TEST(sim_diag_scan) {
  clear_logs();
  // Node 2: configured ping-pong slave. Node 3: configured as the RTD
  // module, but the device there reports another product code (boot: false,
  // so the master leaves it alone). Node 40: a ping-pong slave nobody
  // configured.
  std::string rtd = read(std::string(RTD_DIR) + "/rtd8.eds");
  std::string json = pingpong_json(R"(,
    { "node_id": 3, "name": "rtd", "eds": "rtd8.eds", "boot": false })");
  std::string dir = make_dir(json, {{"cpp-slave.eds", slave_eds()}, {"rtd8.eds", rtd},
                                    {"device.eds", rtd_device_eds("0x00000404", "0x00000405")}});
  static Sim* sim;
  sim = new Sim(dir);
  CHECK(sim->ok());
  if (!sim->ok()) return;
  sim->EnableDiag();
  sim->StartSlave(2, dir + "/cpp-slave.eds");
  sim->StartSensor(3, dir + "/device.eds", {});
  sim->StartSlave(40, dir + "/cpp-slave.eds");
  sim->net().Start();
  CHECK(sim->RunUntil([] { return sim->status() && sim->in() > 5; }, seconds(5)));
  sim->RunFor(milliseconds(500));
  clear_logs();

  cJSON* a = sim->Ask(diag_req("scan"));
  CHECK(ok(a) && cJSON_IsTrue(field(result(a), "running")));
  cJSON_Delete(a);
  // A second request joins the running scan.
  a = sim->Ask(diag_req("scan"));
  CHECK(ok(a) && cJSON_IsTrue(field(result(a), "running")) && num(result(a), "total") == 126);
  cJSON_Delete(a);
  // PDOs keep flowing while it runs.
  uint32_t before = sim->in();
  cJSON* done = nullptr;
  auto t0 = steady_clock::now();
  CHECK(sim->RunUntil([&] {
    cJSON* s = sim->Ask(diag_req("scan_status"));
    if (s && !cJSON_IsTrue(field(result(s), "running"))) {
      done = s;
      return true;
    }
    cJSON_Delete(s);
    return false;
  }, seconds(15)));
  double secs = duration<double>(steady_clock::now() - t0).count();
  std::printf("    scan took %.1f s\n", secs);
  CHECK(secs < 10);
  CHECK(sim->status() && sim->in() > before + 10);
  CHECK(!logged("is not operational"));
  const cJSON* nodes = field(result(done), "nodes");
  std::map<int, std::string> match;
  const cJSON* n;
  cJSON_ArrayForEach(n, nodes) match[static_cast<int>(num(n, "node_id"))] = str(n, "match");
  CHECK_MSG(match.size() == 3, std::to_string(match.size()));
  CHECK(match[2] == "configured");
  CHECK_MSG(match[3] == "configured, different device", match[3]);
  CHECK(match[40] == "not configured");
  cJSON_ArrayForEach(n, nodes) {
    if (num(n, "node_id") == 3) {
      CHECK_MSG(str(n, "differs") == "product code 0x00000405, expected 0x00000404", str(n, "differs"));
      CHECK(str(n, "device_name") == "RTD-8");
      CHECK(num(n, "vendor_id") == 0xF0F0F0);
    }
    if (num(n, "node_id") == 40) CHECK(num(n, "vendor_id") == 0x360);
  }
  CHECK(logged("network scan done"));
  cJSON_Delete(done);
  delete sim;
}

// Status of a node that refuses its configuration (error status J) and has
// no diagnostic locations at all.
TEST(sim_diag_boot_error) {
  clear_logs();
  std::string eds = slave_eds();
  std::string bad = eds;
  bad.replace(bad.find("SupportedObjects=2\n1=0x4000\n2=0x4001"), 36,
              "SupportedObjects=3\n1=0x4000\n2=0x4001\n3=0x4002");
  bad += "\n[4002]\nParameterName=Not implemented by the slave\nDataType=0x0007\nAccessType=rww\n"
         "DefaultValue=0\nPDOMapping=1\n";
  std::string node3 = R"(,
    {
      "node_id": 3, "name": "rejects", "eds": "bad-slave.eds",
      "rx_pdos": [ { "entries": [ { "index": "0x4002", "type": "UNSIGNED32", "iec_location": "%QD200" } ] } ]
    })";
  std::string dir = make_dir(pingpong_json(node3), {{"cpp-slave.eds", eds}, {"bad-slave.eds", bad}});
  static Sim* sim;
  sim = new Sim(dir);
  CHECK(sim->ok());
  if (!sim->ok()) return;
  sim->EnableDiag();
  sim->StartSlave(2, dir + "/cpp-slave.eds");
  sim->StartSlave(3, dir + "/cpp-slave.eds");  // the real device lacks 0x4002
  sim->net().Start();
  cJSON* a = nullptr;
  CHECK(sim->RunUntil([&] {
    cJSON_Delete(a);
    a = sim->Ask(diag_req("status"));
    const cJSON* n3 = node_of(a, 3);
    return n3 && cJSON_IsString(field(n3, "boot_error"));
  }, seconds(10)));
  const cJSON* n3 = node_of(a, 3);
  CHECK(n3 && str(n3, "boot_error") == "J");
  CHECK_MSG(n3 && !str(n3, "boot_error_text").empty(), n3 ? str(n3, "boot_error_text") : "");
  CHECK(n3 && cJSON_IsFalse(field(n3, "status")) && cJSON_IsFalse(field(n3, "booted")));
  CHECK(n3 && str(n3, "name") == "rejects");
  if (n3) std::printf("    node 3: %s\n", str(n3, "boot_error_text").c_str());
  cJSON_Delete(a);
  // A retry is pending between boot attempts; node 2 runs regardless.
  a = nullptr;
  CHECK(sim->RunUntil([&] {
    cJSON_Delete(a);
    a = sim->Ask(diag_req("status"));
    const cJSON* n = node_of(a, 3);
    return n && cJSON_IsTrue(field(n, "retry_pending"));
  }, seconds(10)));
  CHECK(sim->RunUntil([] { return sim->status(); }, seconds(5)));
  cJSON_Delete(a);
  delete sim;
}

TEST(sim_diag_scan_only) {
  clear_logs();
  // No slave configured: the master runs alone on the bus, and a scan finds
  // the ping-pong slave at node 2.
  std::string json = R"({
  "schema_version": 1,
  "adapter": { "type": "socketcan", "interface": "sim", "bitrate": 125000 },
  "master": { "node_id": 1, "sync_period_us": 20000,
              "diagnostics": { "token_verifier": "SCRAM-SHA-256$4096:b3BlbnBsYy1jYW5vcGVuLQ==$SCwajLpaZodu1wAN8vyPszAhAZJB4cXO6Rk+MpacSlQ=:7p7OTxtK+R6omxv8Fdz+xdCpEf4bc82kbkxCL8w33kg=" } },
  "nodes": []
})";
  std::string dir = make_dir(json, {{"cpp-slave.eds", slave_eds()}});
  static Sim* sim;
  sim = new Sim(dir);
  CHECK(sim->ok());
  if (!sim->ok()) return;
  sim->EnableDiag();
  sim->StartSlave(2, dir + "/cpp-slave.eds");
  sim->net().Start();
  cJSON* st = nullptr;
  CHECK(sim->RunUntil([&] {
    cJSON_Delete(st);
    st = sim->Ask(diag_req("status"));
    const cJSON* m = field(result(st), "master");
    return m && (num(m, "state") == 5 || num(m, "state") == 127);
  }, seconds(5)));
  CHECK(cJSON_GetArraySize(field(result(st), "nodes")) == 0);
  cJSON_Delete(st);
  cJSON* a = sim->Ask(diag_req("scan"));
  CHECK(ok(a));
  cJSON_Delete(a);
  cJSON* done = nullptr;
  CHECK(sim->RunUntil([&] {
    cJSON* s = sim->Ask(diag_req("scan_status"));
    if (s && !cJSON_IsTrue(field(result(s), "running"))) {
      done = s;
      return true;
    }
    cJSON_Delete(s);
    return false;
  }, seconds(15)));
  const cJSON* nodes = field(result(done), "nodes");
  CHECK(cJSON_GetArraySize(nodes) == 1);
  const cJSON* n = cJSON_GetArrayItem(nodes, 0);
  CHECK(n && num(n, "node_id") == 2 && str(n, "match") == "not configured" && num(n, "vendor_id") == 0x360);
  cJSON_Delete(done);
  delete sim;
}


// ---------------------------------------------------------------------------
// LSS (add-lss-master)

// Node 12, the ping-pong slave as an LSS device with serial 0x1234, plus
// `node_fields` (its "lss" object and anything else) and other nodes.
std::string lss_json(const std::string& node_fields, const std::string& extra_nodes = "",
                     const std::string& master_extra = "") {
  return R"({
  "schema_version": 1,
  "adapter": { "type": "socketcan", "interface": "sim", "bitrate": 125000 },
  "master": { "node_id": 1, "sync_period_us": 20000 )" + master_extra + R"( },
  "nodes": [
    {
      "node_id": 12, "name": "valve", "eds": "lss-slave.eds", "serial_number": "0x1234",
      "heartbeat_ms": 50, "heartbeat_timeout_ms": 200, )" + node_fields + R"(
      "status_location": "%IX10.0",
      "tx_pdos": [ { "entries": [ { "index": "0x4001", "type": "UNSIGNED32", "iec_location": "%ID100" } ] } ],
      "rx_pdos": [ { "entries": [ { "index": "0x4000", "type": "UNSIGNED32", "iec_location": "%QD100" } ] } ]
    })" + extra_nodes + R"(
  ]
})";
}

std::string lss_dir(const std::string& json) {
  return make_dir(json, {{"lss-slave.eds", read(std::string(FIXTURES_DIR) + "/eds/lss-slave.eds")},
                         {"cpp-slave.eds", slave_eds()},
                         {"device.eds", lss_eds(0x1234)},
                         {"device-rev.eds", lss_eds(0x1234, 0x00020003)},
                         {"other.eds", lss_eds(0x5678)},
                         {"new.eds", lss_eds(0x42)}});
}

const char* const kAssignedFromNone = "node 12 (valve): LSS assigned node ID 12 (previous: none)";

TEST(sim_lss_assign_at_start) {
  clear_logs();
  std::string dir = lss_dir(lss_json(R"("lss": { "assign": true },)"));
  static Sim* sim;
  sim = new Sim(dir);
  CHECK(sim->ok());
  if (!sim->ok()) return;
  auto mem = std::make_shared<LssMemory>();
  sim->StartLssSlave(200, dir + "/device.eds", mem);
  sim->RunFor(milliseconds(100));
  sim->net().Start();
  CHECK(sim->RunUntil([] { return sim->status() && sim->in() > 5; }, seconds(5)));
  CHECK(logged(kAssignedFromNone));
  CHECK(sim->lss(0x11) == 1);  // configure node-ID
  CHECK(sim->lss(0x17) == 0);  // no store without lss.store
  CHECK(mem->stores == 0);
  delete sim;
}

TEST(sim_lss_already_right) {
  clear_logs();
  std::string dir = lss_dir(lss_json(R"("lss": { "assign": true, "store": true },)"));
  static Sim* sim;
  sim = new Sim(dir);
  CHECK(sim->ok());
  if (!sim->ok()) return;
  auto mem = std::make_shared<LssMemory>();
  mem->stored_id = 12;
  sim->StartLssSlave(200, dir + "/device.eds", mem);
  sim->RunFor(milliseconds(100));
  sim->net().Start();
  CHECK(sim->RunUntil([] { return sim->status() && sim->in() > 5; }, seconds(5)));
  CHECK(logged("node 12 (valve): LSS: the device already has node ID 12"));
  CHECK(sim->lss(0x11) == 0);
  CHECK(sim->lss(0x17) == 0);
  delete sim;
}

TEST(sim_lss_revision_searched) {
  clear_logs();
  std::string dir = lss_dir(lss_json(R"("lss": { "assign": true },)"));
  static Sim* sim;
  sim = new Sim(dir);
  CHECK(sim->ok());
  if (!sim->ok()) return;
  auto mem = std::make_shared<LssMemory>();
  sim->StartLssSlave(200, dir + "/device-rev.eds", mem);
  sim->RunFor(milliseconds(100));
  sim->net().Start();
  CHECK(sim->RunUntil([] { return sim->status() && sim->in() > 5; }, seconds(5)));
  CHECK(logged(kAssignedFromNone));
  CHECK(sim->lss(0x46) > 0);  // identify remote slave (slowscan)
  delete sim;
}

TEST(sim_lss_store_then_power_cycle) {
  clear_logs();
  std::string dir = lss_dir(lss_json(R"("lss": { "assign": true, "store": true },)"));
  static Sim* sim;
  sim = new Sim(dir);
  CHECK(sim->ok());
  if (!sim->ok()) return;
  auto mem = std::make_shared<LssMemory>();
  sim->StartLssSlave(200, dir + "/device.eds", mem);
  sim->RunFor(milliseconds(100));
  sim->net().Start();
  CHECK(sim->RunUntil([] { return sim->status() && sim->in() > 5; }, seconds(5)));
  CHECK(logged("node 12 (valve): LSS stored node ID 12 in the device"));
  CHECK(sim->lss(0x17) == 1);
  CHECK(mem->stores == 1 && mem->stored_id == 12);
  // Power cycle: it comes back as node 12 by itself, nothing more is set.
  sim->KillSlave(200);
  CHECK(sim->RunUntil([] { return !sim->status(); }, seconds(2)));
  sim->StartLssSlave(200, dir + "/device.eds", mem);
  CHECK(sim->RunUntil([] { return sim->status(); }, seconds(20)));
  CHECK(sim->lss(0x11) == 1);
  CHECK(sim->lss(0x17) == 1);
  delete sim;
}

TEST(sim_lss_device_missing) {
  clear_logs();
  std::string dir = lss_dir(lss_json(R"("lss": { "assign": true },)", R"(,
    { "node_id": 2, "name": "pingpong", "eds": "cpp-slave.eds", "heartbeat_ms": 50, "status_location": "%IX10.1" })"));
  static Sim* sim;
  sim = new Sim(dir);
  CHECK(sim->ok());
  if (!sim->ok()) return;
  sim->StartSlave(2, dir + "/cpp-slave.eds");
  sim->net().Start();
  CHECK(sim->RunUntil([] { return sim->plc().bool_in[10][1] != 0; }, seconds(5)));
  CHECK(logged("node 12 (valve): no device with vendor ID 0x00000360, product code 0x00000000, serial number "
               "0x00001234 answered LSS"));
  CHECK(!sim->status());
  CHECK(sim->RunUntil([] { return logged("node 12 (valve) is not answering"); }, seconds(5)));
  delete sim;
}

TEST(sim_lss_no_frames_without_lss) {
  clear_logs();
  std::string dir = make_dir(pingpong_json(), {{"cpp-slave.eds", slave_eds()}});
  static Sim* sim;
  sim = new Sim(dir);
  CHECK(sim->ok());
  if (!sim->ok()) return;
  sim->StartSlave(2, dir + "/cpp-slave.eds");
  sim->net().Start();
  CHECK(sim->RunUntil([] { return sim->status() && sim->in() > 5; }, seconds(5)));
  sim->KillSlave(2);
  sim->RunFor(milliseconds(2500));  // lost, retried
  CHECK(sim->lss_total() == 0);
  delete sim;
}

TEST(sim_lss_reassign_after_power_loss) {
  clear_logs();
  std::string dir = lss_dir(lss_json(R"("lss": { "assign": true },)", R"(,
    { "node_id": 2, "name": "pingpong", "eds": "cpp-slave.eds", "heartbeat_ms": 50, "status_location": "%IX10.1" })"));
  static Sim* sim;
  sim = new Sim(dir);
  CHECK(sim->ok());
  if (!sim->ok()) return;
  auto mem = std::make_shared<LssMemory>();
  sim->StartSlave(2, dir + "/cpp-slave.eds");
  sim->StartLssSlave(200, dir + "/device.eds", mem);
  sim->RunFor(milliseconds(100));
  sim->net().Start();
  CHECK(sim->RunUntil([] { return sim->status() && sim->in() > 5; }, seconds(5)));
  int resets = sim->nmt(0, 0x81) + sim->nmt(0, 0x82) + sim->nmt(2, 0x81) + sim->nmt(2, 0x82);
  // Power loss without store: it comes back without a node ID.
  sim->KillSlave(200);
  CHECK(sim->RunUntil([] { return !sim->status(); }, seconds(2)));
  sim->StartLssSlave(200, dir + "/device.eds", mem);
  CHECK(sim->RunUntil([] { return sim->status(); }, seconds(20)));
  CHECK(count_logs(kAssignedFromNone) == 2);
  uint32_t c = sim->in();
  CHECK(sim->RunUntil([&] { return sim->in() > c + 5; }, seconds(5)));
  CHECK(sim->nmt(0, 0x81) + sim->nmt(0, 0x82) + sim->nmt(2, 0x81) + sim->nmt(2, 0x82) == resets);
  CHECK(sim->plc().bool_in[10][1] != 0);
  delete sim;
}

TEST(sim_lss_device_with_old_id_at_retry) {
  clear_logs();
  std::string dir = lss_dir(lss_json(R"("lss": { "assign": true },)"));
  static Sim* sim;
  sim = new Sim(dir);
  CHECK(sim->ok());
  if (!sim->ok()) return;
  auto mem = std::make_shared<LssMemory>();
  sim->StartLssSlave(200, dir + "/device.eds", mem);
  sim->RunFor(milliseconds(100));
  sim->net().Start();
  CHECK(sim->RunUntil([] { return sim->status(); }, seconds(5)));
  sim->KillSlave(200);
  CHECK(sim->RunUntil([] { return !sim->status(); }, seconds(2)));
  // Comes back as node 5 (stored elsewhere).
  mem->stored_id = 5;
  sim->StartLssSlave(200, dir + "/device.eds", mem);
  CHECK(sim->RunUntil([] {
    return logged("node 12 (valve): LSS assigned node ID 12; the device keeps node ID 5 until it is reset or "
                  "power-cycled");
  }, seconds(20)));
  sim->RunFor(milliseconds(500));
  CHECK(sim->nmt(5, 0x81) == 0 && sim->nmt(5, 0x82) == 0 && sim->nmt(5, 0x01) == 0);
  CHECK(!sim->status());
  delete sim;
}

std::string lss_diag_json(bool allow_changes) {
  return lss_json(R"("boot": true,)", "",
                  std::string(R"(, "diagnostics": { "token_verifier": )"
                              R"("SCRAM-SHA-256$4096:b3BlbnBsYy1jYW5vcGVuLQ==$SCwajLpaZodu1wAN8vyPszAhAZJB4cXO6Rk+MpacSlQ=:7p7OTxtK+R6omxv8Fdz+xdCpEf4bc82kbkxCL8w33kg=", "allow_changes": )") +
                      (allow_changes ? "true" : "false") + " }");
}

DiagRequest lss_req(const std::string& op, const uint32_t a[4]) {
  DiagRequest r = diag_req(op);
  for (int f = 0; f < 4; ++f) r.lss[f] = a[f];
  return r;
}

// Commissioning over the diagnostics channel: node 12 is a configured LSS
// device with its node ID; a new device without one is found, given node
// ID 40, then 41 (stored) and a bit rate (stored), while node 12 runs.
TEST(sim_lss_diag_commissioning) {
  clear_logs();
  std::string dir = lss_dir(lss_diag_json(true));
  static Sim* sim;
  sim = new Sim(dir);
  CHECK(sim->ok());
  if (!sim->ok()) return;
  sim->EnableDiag();
  auto mem12 = std::make_shared<LssMemory>();
  mem12->stored_id = 12;
  auto mem = std::make_shared<LssMemory>();
  sim->StartLssSlave(200, dir + "/device.eds", mem12);
  // Lely's LSS slave answers fastscan even with a node ID, so the new device
  // has the lower serial number, which the search finds first.
  sim->StartLssSlave(201, dir + "/new.eds", mem);
  sim->net().Start();
  CHECK(sim->RunUntil([] { return sim->status() && sim->in() > 5; }, seconds(5)));
  CHECK(sim->lss_total() == 0);  // no lss.assign: no LSS at start

  // Find: runs in the background, the result names the new device.
  cJSON* a = sim->Ask(diag_req("lss_find"));
  CHECK(ok(a) && cJSON_IsTrue(field(result(a), "running")));
  cJSON_Delete(a);
  static cJSON* done;
  done = nullptr;
  CHECK(sim->RunUntil([] {
    cJSON* s = sim->Ask(diag_req("lss_find_status"));
    if (s && !cJSON_IsTrue(field(result(s), "running"))) {
      done = s;
      return true;
    }
    cJSON_Delete(s);
    sim->RunFor(milliseconds(200));
    return false;
  }, seconds(25)));
  const cJSON* dev = field(result(done), "device");
  CHECK(cJSON_IsTrue(field(result(done), "found")));
  CHECK(dev && num(dev, "serial_number") == 0x42 && num(dev, "vendor_id") == 0x360 && num(dev, "node_id") == 255);
  std::printf("    found in %.1f s\n", num(result(done), "seconds"));
  CHECK(num(result(done), "seconds") < 20);
  cJSON_Delete(done);
  CHECK(sim->status());  // node 12 kept running
  CHECK(!logged("node 12 (valve) lost"));

  const uint32_t addr[4] = {0x360, 0, 0, 0x42};
  // Node ID in use by a booted node: refused, nothing sent.
  int before = sim->lss_total();
  DiagRequest r = lss_req("lss_set_id", addr);
  r.node = 12;
  a = sim->Ask(r);
  CHECK(!ok(a) && str(a, "error").find("node ID 12 is in use by node 12 (valve)") != std::string::npos);
  cJSON_Delete(a);
  CHECK(sim->lss_total() == before);

  // Set node ID 40 without store: it had none and starts as node 40.
  r = lss_req("lss_set_id", addr);
  r.node = 40;
  a = sim->Ask(r);
  CHECK(ok(a) && cJSON_IsFalse(field(result(a), "had_node_id")) && cJSON_IsFalse(field(result(a), "stored")));
  cJSON_Delete(a);
  CHECK(sim->lss(0x17) == 0);
  CHECK(sim->RunUntil([] { return sim->bootups(40) > 0; }, seconds(2)));

  // Node ID 41, stored: it had one, so 41 waits for its next reset.
  r = lss_req("lss_set_id", addr);
  r.node = 41;
  r.store = true;
  a = sim->Ask(r);
  CHECK(ok(a) && cJSON_IsTrue(field(result(a), "had_node_id")) && cJSON_IsTrue(field(result(a), "stored")) &&
        num(result(a), "previous_node_id") == 40);
  cJSON_Delete(a);
  CHECK(sim->lss(0x17) == 1);
  CHECK(mem->stores == 1 && mem->stored_id == 41);

  // Inquire sees the node ID.
  a = sim->Ask(lss_req("lss_inquire", addr));
  CHECK(ok(a));
  cJSON_Delete(a);

  // Bit rate 250 kbit/s, stored, never activated.
  r = lss_req("lss_set_bitrate", addr);
  r.bitrate_kbit = 250;
  r.store = true;
  a = sim->Ask(r);
  CHECK(ok(a) && str(result(a), "note").find("next power cycle") != std::string::npos);
  cJSON_Delete(a);
  CHECK(sim->lss(0x13) == 1);
  CHECK(sim->lss(0x15) == 0);
  CHECK(sim->lss(0x17) == 2);

  // An address nobody has.
  const uint32_t nobody[4] = {0x360, 0, 0, 0x9999};
  a = sim->Ask(lss_req("lss_inquire", nobody));
  CHECK(!ok(a) && str(a, "error").find("not found") != std::string::npos);
  cJSON_Delete(a);

  CHECK(sim->status());
  uint32_t c = sim->in();
  CHECK(sim->RunUntil([&] { return sim->in() > c + 5; }, seconds(5)));
  CHECK(!logged("node 12 (valve) lost"));
  delete sim;
}

TEST(sim_lss_diag_none_found) {
  clear_logs();
  std::string dir = lss_dir(lss_diag_json(true));
  static Sim* sim;
  sim = new Sim(dir);
  CHECK(sim->ok());
  if (!sim->ok()) return;
  sim->EnableDiag();
  sim->net().Start();
  sim->RunFor(milliseconds(200));
  cJSON* a = sim->Ask(diag_req("lss_find"));
  CHECK(ok(a));
  cJSON_Delete(a);
  static cJSON* done;
  done = nullptr;
  CHECK(sim->RunUntil([] {
    cJSON* s = sim->Ask(diag_req("lss_find_status"));
    if (s && !cJSON_IsTrue(field(result(s), "running"))) {
      done = s;
      return true;
    }
    cJSON_Delete(s);
    sim->RunFor(milliseconds(200));
    return false;
  }, seconds(25)));
  CHECK(cJSON_IsFalse(field(result(done), "found")));
  cJSON_Delete(done);
  delete sim;
}

TEST(sim_lss_diag_read_only) {
  clear_logs();
  std::string dir = lss_dir(lss_diag_json(false));
  static Sim* sim;
  sim = new Sim(dir);
  CHECK(sim->ok());
  if (!sim->ok()) return;
  sim->EnableDiag();
  sim->net().Start();
  sim->RunFor(milliseconds(200));
  const uint32_t addr[4] = {0x360, 0, 0, 0x5678};
  cJSON* a = sim->Ask(diag_req("lss_find"));
  CHECK(!ok(a));
  cJSON_Delete(a);
  a = sim->Ask(lss_req("lss_inquire", addr));
  CHECK(!ok(a));
  cJSON_Delete(a);
  sim->RunFor(milliseconds(200));
  CHECK(sim->lss_total() == 0);
  delete sim;
}

// ---- simulated devices (canopen_sim) ----

// The ping-pong node as a simulated device: its TPDO object follows the
// RPDO object the program writes, so the counter runs as with the real slave.
TEST(sim_simulated_pingpong) {
  clear_logs();
  std::string dir = make_dir(pingpong_json(), {{"cpp-slave.eds", slave_eds()}});
  static Sim* sim;
  sim = new Sim(dir);
  CHECK(sim->ok());
  if (!sim->ok()) return;
  CHECK(sim->StartSimulator(R"({"nodes": {"2": {"sources": {"0x4001": {"expr": "[0x4000]"}}}}})"));
  sim->net().Start();
  CHECK(sim->RunUntil([] { return sim->status() && sim->in() > 5; }, seconds(5)));
  uint32_t a = sim->in();
  sim->RunFor(milliseconds(500));
  CHECK_MSG(sim->in() >= a + 4, std::to_string(a) + " -> " + std::to_string(sim->in()));
  CHECK(sim->simulator().AllOperational());
  CHECK(logged("sim: node 2: OPERATIONAL"));

  // A source on the object the master writes is refused.
  cJSON* r = sim->SimAsk(R"({"op":"sim_source","node":2,"object":"0x4000","source":{"constant":5}})");
  CHECK(!ok(r));
  CHECK_MSG(str(r, "error").find("the master writes 0x4000:0") != std::string::npos, str(r, "error"));
  cJSON_Delete(r);
  // An override wins over the source; release gives it back.
  r = sim->SimAsk(R"({"op":"sim_override","node":2,"values":{"0x4001":7}})");
  CHECK(ok(r));
  cJSON_Delete(r);
  sim->RunFor(milliseconds(300));
  CHECK_MSG(sim->in() == 7, std::to_string(sim->in()));
  r = sim->SimAsk(R"({"op":"sim_get","items":[{"node":2,"object":"0x4001"}]})");
  const cJSON* v = cJSON_GetArrayItem(field(result(r), "values"), 0);
  CHECK(num(v, "value") == 7 && str(v, "writer") == "override" && str(v, "type") == "UNSIGNED32");
  cJSON_Delete(r);
  r = sim->SimAsk(R"({"op":"sim_release","node":2,"objects":"all"})");
  cJSON_Delete(r);
  CHECK(sim->RunUntil([] { return sim->in() > 20; }, seconds(5)));
  // Status lists the device.
  r = sim->SimAsk(R"({"op":"sim_status"})");
  const cJSON* d = cJSON_GetArrayItem(field(result(r), "devices"), 0);
  CHECK(num(d, "node") == 2 && str(d, "power") == "on" && str(d, "nmt") == "operational");
  CHECK(cJSON_IsTrue(field(result(r), "simulated_network")));
  cJSON_Delete(r);
  delete sim;
}

// Faults the master notices: heartbeat stop, power off/on, SDO abort rules.
TEST(sim_simulated_faults) {
  clear_logs();
  std::string dir = make_dir(pingpong_json(), {{"cpp-slave.eds", slave_eds()}});
  static Sim* sim;
  sim = new Sim(dir);
  CHECK(sim->ok());
  if (!sim->ok()) return;
  sim->EnableDiag();
  CHECK(sim->StartSimulator(R"({"nodes": {"2": {"sources": {"0x4001": {"expr": "[0x4000]"}}}}})"));
  sim->net().Start();
  CHECK(sim->RunUntil([] { return sim->status(); }, seconds(5)));

  // Through the diagnostics channel, as a client sends it: one whole line back.
  sim->WireSimHandler();
  DiagRequest dr = diag_req("sim_status");
  dr.raw = R"({"op":"sim_status","id":7})";
  dr.id = "7";
  std::string line = sim->AskLine(std::move(dr));
  CHECK_MSG(!line.empty() && line.back() == '\n' && line.find('\n') == line.size() - 1, line);
  cJSON* sa = cJSON_Parse(line.c_str());
  CHECK(ok(sa) && num(sa, "id") == 7);
  cJSON_Delete(sa);

  cJSON* r = sim->SimAsk(R"({"op":"sim_fault","node":2,"fault":{"heartbeat":"stop"}})");
  CHECK(ok(r));
  cJSON_Delete(r);
  CHECK(sim->RunUntil([] { return !sim->status(); }, seconds(3)));
  r = sim->SimAsk(R"({"op":"sim_clear","node":2,"fault":"heartbeat"})");
  cJSON_Delete(r);
  CHECK(sim->RunUntil([] { return sim->status(); }, seconds(5)));

  // The ping-pong EDS has no 0x1014, so the device has no EMCY producer.
  r = sim->SimAsk(R"({"op":"sim_fault","node":2,"fault":{"emcy":{"code":"0x5000"}}})");
  CHECK(!ok(r));
  CHECK_MSG(str(r, "error").find("cannot send EMCY") != std::string::npos, str(r, "error"));
  cJSON_Delete(r);

  r = sim->SimAsk(R"({"op":"sim_fault","node":2,"fault":{"power":"cycle","off_ms":500}})");
  CHECK(ok(r));
  cJSON_Delete(r);
  CHECK(sim->RunUntil([] { return !sim->status(); }, seconds(3)));
  CHECK(sim->RunUntil([] { return sim->status() && sim->in() > 3; }, seconds(10)));
  CHECK(logged("sim: node 2: powered off"));

  r = sim->SimAsk(R"({"op":"sim_fault","node":2,"fault":{"sdo_abort":{"object":"0x1008","code":"0x08000020","count":1}}})");
  CHECK(!ok(r) && str(r, "error") == "node 2 has no object 0x1008:0");
  cJSON_Delete(r);
  cJSON* a = sim->Ask(diag_req("sdo_read", 2, 0x1018, 1));
  CHECK(ok(a) && cJSON_IsTrue(field(result(a), "success")));
  cJSON_Delete(a);
  r = sim->SimAsk(R"({"op":"sim_fault","node":2,"fault":{"sdo_abort":{"object":"0x1018:1","code":"0x08000020","count":1}}})");
  cJSON_Delete(r);
  a = sim->Ask(diag_req("sdo_read", 2, 0x1018, 1));
  CHECK_MSG(ok(a) && num(result(a), "abort_code") == 0x08000020, a ? cJSON_PrintUnformatted(a) : "null");
  cJSON_Delete(a);
  a = sim->Ask(diag_req("sdo_read", 2, 0x1018, 1));  // count 1: the next one passes
  CHECK(ok(a) && cJSON_IsTrue(field(result(a), "success")));
  cJSON_Delete(a);

  // Wrong identity: 0x1018 reads the override.
  r = sim->SimAsk(R"({"op":"sim_fault","node":2,"fault":{"identity":{"serial_number":4660}}})");
  cJSON_Delete(r);
  a = sim->Ask(diag_req("sdo_read", 2, 0x1018, 4));
  CHECK_MSG(str(result(a), "data") == "34 12 00 00", str(result(a), "data"));
  cJSON_Delete(a);
  r = sim->SimAsk(R"({"op":"sim_clear","node":2,"fault":"all"})");
  cJSON_Delete(r);
  a = sim->Ask(diag_req("sdo_read", 2, 0x1018, 4));
  CHECK_MSG(str(result(a), "data") == "00 00 00 00", str(result(a), "data"));
  cJSON_Delete(a);
  delete sim;
}

// Receive timeout of an input PDO (canopen-pdo-io "Input PDO timeout
// detection", "Timeout reported to the PLC and the log", "Inputs while a PDO
// is timed out"): the simulated device keeps its heartbeat and stops TPDO 1.
std::string input_timeout_json(const std::string& extra) {
  std::string json = pingpong_json();
  json.replace(json.find("\"tx_pdos\": [ { "), 15,
               "\"tx_pdos\": [ { \"transmission\": 255, \"event_timer_ms\": 20, \"timeout_ms\": 100, "
               "\"timeout_location\": \"%IX10.1\", " + extra);
  return json;
}

const cJSON* pdo_timeout_of(const cJSON* status, unsigned node, unsigned tpdo) {
  const cJSON* n;
  cJSON_ArrayForEach(n, field(result(status), "nodes")) {
    if (num(n, "node_id") != node) continue;
    const cJSON* t;
    cJSON_ArrayForEach(t, field(n, "pdo_timeouts"))
      if (num(t, "tpdo") == tpdo) return t;
  }
  return nullptr;
}

TEST(sim_input_pdo_timeout) {
  clear_logs();
  std::string dir = make_dir(input_timeout_json(""), {{"cpp-slave.eds", slave_eds()}});
  CHECK(read(dir + "/canopen_config.json").find("timeout_ms") != std::string::npos);
  static Sim* sim;
  sim = new Sim(dir);
  CHECK(sim->ok());
  if (!sim->ok()) return;
  sim->EnableDiag();
  CHECK(sim->StartSimulator(R"({"nodes": {"2": {"sources": {"0x4001": {"expr": "[0x4000]"}}}}})"));
  sim->net().Start();
  CHECK(sim->RunUntil([] { return sim->status() && sim->in() > 3; }, seconds(5)));
  CHECK(logged("node 2 (pingpong) TPDO 1: receive timeout 100 ms"));
  sim->RunFor(milliseconds(300));
  CHECK(sim->plc().bool_in[10][1] == 0);
  CHECK(!logged("no PDO for"));

  cJSON* r = sim->SimAsk(R"({"op":"sim_fault","node":2,"fault":{"tpdo_stop":1}})");
  CHECK(ok(r));
  cJSON_Delete(r);
  auto stopped = steady_clock::now();
  CHECK(sim->RunUntil([] { return sim->plc().bool_in[10][1] != 0; }, seconds(2)));
  auto took = duration_cast<milliseconds>(steady_clock::now() - stopped).count();
  std::printf("    timeout bit after %lld ms\n", (long long)took);
  CHECK(took >= 80 && took < 400);
  uint32_t held = sim->in();
  sim->RunFor(milliseconds(500));
  CHECK(sim->status());               // the node is still up
  CHECK(sim->in() == held);           // hold: the last value
  CHECK(sim->plc().bool_in[10][1] != 0);
  CHECK_MSG(count_logs("node 2 (pingpong) TPDO 1: no PDO for 100 ms (timeout_ms); its inputs keep their last values") == 1,
            std::to_string(count_logs("no PDO for")) + " timeout warnings");
  cJSON* a = sim->Ask(diag_req("status"));
  const cJSON* t = pdo_timeout_of(a, 2, 1);
  CHECK_MSG(t && cJSON_IsTrue(field(t, "timed_out")) && num(t, "count") == 1 && num(t, "timeout_ms") == 100 &&
                num(t, "since_ms") >= 500,
            a ? cJSON_PrintUnformatted(a) : "null");
  cJSON_Delete(a);

  r = sim->SimAsk(R"({"op":"sim_clear","node":2,"fault":"tpdo_stop"})");
  cJSON_Delete(r);
  CHECK(sim->RunUntil([] { return sim->plc().bool_in[10][1] == 0; }, seconds(2)));
  CHECK(sim->RunUntil([held] { return sim->in() > held; }, seconds(2)));
  CHECK(logged("node 2 (pingpong) TPDO 1 is back after "));
  a = sim->Ask(diag_req("status"));
  t = pdo_timeout_of(a, 2, 1);
  CHECK(t && cJSON_IsFalse(field(t, "timed_out")) && num(t, "count") == 1 && num(t, "since_ms") < 100);
  cJSON_Delete(a);
  // The master sent no EMCY of its own for it (Lely's default would).
  CHECK(sim->frames(0x081) == 0);
  delete sim;
}

TEST(sim_input_pdo_timeout_zero) {
  clear_logs();
  std::string dir = make_dir(input_timeout_json("\"on_timeout\": \"zero\", "), {{"cpp-slave.eds", slave_eds()}});
  static Sim* sim;
  sim = new Sim(dir);
  CHECK(sim->ok());
  if (!sim->ok()) return;
  CHECK(sim->StartSimulator(R"({"nodes": {"2": {"sources": {"0x4001": {"expr": "[0x4000]"}}}}})"));
  sim->net().Start();
  CHECK(sim->RunUntil([] { return sim->status() && sim->in() > 3; }, seconds(5)));
  cJSON* r = sim->SimAsk(R"({"op":"sim_fault","node":2,"fault":{"tpdo_stop":1}})");
  cJSON_Delete(r);
  CHECK(sim->RunUntil([] { return sim->plc().bool_in[10][1] != 0; }, seconds(2)));
  CHECK(sim->in() == 0);
  CHECK(logged("node 2 (pingpong) TPDO 1: no PDO for 100 ms (timeout_ms); its inputs read 0 until it is back"));
  sim->RunFor(milliseconds(300));
  CHECK(sim->in() == 0);
  r = sim->SimAsk(R"({"op":"sim_clear","node":2,"fault":"all"})");
  cJSON_Delete(r);
  CHECK(sim->RunUntil([] { return sim->plc().bool_in[10][1] == 0 && sim->in() > 0; }, seconds(2)));
  delete sim;
}

// A TPDO that never arrives after the node came up times out too (Lely's
// deadline only runs from a received PDO), and a lost node ends the timeout
// without more warnings.
TEST(sim_input_pdo_never_arrives) {
  clear_logs();
  std::string dir = make_dir(input_timeout_json(""), {{"cpp-slave.eds", slave_eds()}});
  static Sim* sim;
  sim = new Sim(dir);
  CHECK(sim->ok());
  if (!sim->ok()) return;
  CHECK(sim->StartSimulator(R"({"nodes": {"2": {"sources": {"0x4001": {"expr": "[0x4000]"}}}}})"));
  cJSON* r = sim->SimAsk(R"({"op":"sim_fault","node":2,"fault":{"tpdo_stop":1}})");
  CHECK(ok(r));
  cJSON_Delete(r);
  sim->net().Start();
  CHECK(sim->RunUntil([] { return sim->status(); }, seconds(5)));
  auto up = steady_clock::now();
  CHECK(sim->RunUntil([] { return sim->plc().bool_in[10][1] != 0; }, seconds(2)));
  auto took = duration_cast<milliseconds>(steady_clock::now() - up).count();
  std::printf("    timeout bit %lld ms after the node came up\n", (long long)took);
  CHECK(took < 400);
  CHECK(sim->in() == 0);
  r = sim->SimAsk(R"({"op":"sim_fault","node":2,"fault":{"heartbeat":"stop"}})");
  cJSON_Delete(r);
  CHECK(sim->RunUntil([] { return !sim->status(); }, seconds(3)));
  CHECK(sim->plc().bool_in[10][1] == 0);
  sim->RunFor(milliseconds(500));
  CHECK(sim->plc().bool_in[10][1] == 0);
  CHECK_MSG(count_logs("no PDO for") == 1, std::to_string(count_logs("no PDO for")) + " timeout warnings");
  delete sim;
}

// Stored parameters: the master's configuration is saved (0x1010) and kept
// across a power cycle, so the configuration check skips the download.
TEST(sim_simulated_store_power_cycle) {
  clear_logs();
  std::string dir = make_dir(config_check_json(), {{"cpp-slave.eds", config_check_eds()}});
  static Sim* sim;
  sim = new Sim(dir);
  CHECK(sim->ok());
  if (!sim->ok()) return;
  CHECK(sim->StartSimulator(R"({"nodes": {"2": {"sources": {"0x4001": {"expr": "[0x4000]"}}}}})"));
  sim->net().Start();
  CHECK(sim->RunUntil([] { return sim->status() && sim->in() > 2; }, seconds(10)));
  CHECK(logged("node 2 (pingpong): configuring ("));
  CHECK(logged("sim: node 2: parameters saved by the master (0x1010 sub 1)"));
  clear_logs();
  cJSON* r = sim->SimAsk(R"({"op":"sim_fault","node":2,"fault":{"power":"cycle","off_ms":300}})");
  cJSON_Delete(r);
  CHECK(sim->RunUntil([] { return logged("configuration unchanged"); }, seconds(10)));
  uint32_t c = sim->in();
  CHECK(sim->RunUntil([&] { return sim->status() && sim->in() > c + 5; }, seconds(10)));
  delete sim;
}

// A scenario drives a value and checks what the program answers.
TEST(sim_simulated_scenario) {
  clear_logs();
  std::string dir = make_dir(pingpong_json(), {{"cpp-slave.eds", slave_eds()}});
  static Sim* sim;
  sim = new Sim(dir);
  CHECK(sim->ok());
  if (!sim->ok()) return;
  // The program answers 2x its input.
  sim->SetProgram([](fake_runtime::Image& io) { io.dint_out[100] = io.dint_in[100] * 2; });
  CHECK(sim->StartSimulator(R"({"scenarios": {
    "double": {"test": true, "steps": [
      {"wait": {"node": 2, "object": "0x1001", "eq": 0}, "timeout_ms": 1000},
      {"node": 2, "override": {"0x4001": 21}},
      {"expect": {"node": 2, "object": "0x4000", "eq": 42}, "within_ms": 2000},
      {"expect": {"expr": "[2/0x4000] == 2 * [2/0x4001]"}, "for_ms": 300},
      {"log": "doubled"}]},
    "wrong": {"steps": [
      {"node": 2, "override": {"0x4001": 5}},
      {"expect": {"node": 2, "object": "0x4000", "eq": 11}, "within_ms": 500}]}}})"));
  sim->net().Start();
  CHECK(sim->RunUntil([] { return sim->status(); }, seconds(5)));
  std::string err;
  CHECK(sim->simulator().StartScenario("double", err));
  CHECK(sim->RunUntil([] { return !sim->scenario_results().empty(); }, seconds(5)));
  CHECK(!sim->scenario_results().empty() && sim->scenario_results()[0].passed);
  CHECK(logged("scenario double: doubled"));
  CHECK(sim->simulator().StartScenario("wrong", err));
  CHECK(sim->RunUntil([] { return sim->scenario_results().size() == 2; }, seconds(5)));
  if (sim->scenario_results().size() == 2) {
    const auto& res = sim->scenario_results()[1];
    CHECK(!res.passed);
    CHECK_MSG(res.message.find("step 2: expected [2/0x4000:0] == 11 within 500 ms (value seen: 10)") != std::string::npos,
              res.message);
  }
  delete sim;
}

// A node with simulate: false next to simulated ones stays absent.
TEST(sim_simulated_subset) {
  clear_logs();
  std::string extra = R"(,
    { "node_id": 3, "name": "other", "eds": "cpp-slave.eds", "heartbeat_ms": 50,
      "status_location": "%IX10.1",
      "tx_pdos": [ { "entries": [ { "index": "0x4001", "type": "UNSIGNED32", "iec_location": "%ID104" } ] } ],
      "rx_pdos": [ { "entries": [ { "index": "0x4000", "type": "UNSIGNED32", "iec_location": "%QD104" } ] } ] })";
  std::string dir = make_dir(pingpong_json(extra), {{"cpp-slave.eds", slave_eds()}});
  static Sim* sim;
  sim = new Sim(dir);
  CHECK(sim->ok());
  if (!sim->ok()) return;
  canopen_sim::DeviceSpec d;
  d.node = 2;
  d.eds_path = dir + "/cpp-slave.eds";
  CHECK(sim->StartSimulator(R"({"nodes": {"3": {"default_behaviour": false}}})", {d}));
  sim->net().Start();
  CHECK(sim->RunUntil([] { return sim->status(); }, seconds(5)));
  sim->RunFor(milliseconds(500));
  CHECK(sim->plc().bool_in[10][1] == 0);
  CHECK(!sim->simulator().Simulates(3));
  cJSON* r = sim->SimAsk(R"({"op":"sim_get","items":[{"node":3,"object":"0x1000"}]})");
  CHECK(str(cJSON_GetArrayItem(field(result(r), "values"), 0), "error") == "node 3 is not simulated");
  cJSON_Delete(r);
  delete sim;
}

// CiA 401 default: outputs loop back to inputs; switched off per node.
TEST(sim_simulated_io_loopback) {
  for (int defaults = 1; defaults >= 0; --defaults) {
    clear_logs();
    std::string json = R"({
  "schema_version": 1,
  "adapter": { "type": "socketcan", "interface": "sim", "bitrate": 125000, "simulate": true },
  "master": { "node_id": 1, "sync_period_us": 20000 },
  "nodes": [ { "node_id": 4, "name": "io", "eds": "fixed-io.eds", "heartbeat_ms": 50, "status_location": "%IX10.0",
      "tx_pdos": [ { "entries": [ { "index": "0x6000", "subindex": 2, "type": "UNSIGNED8", "iec_location": "%IB40" } ] } ],
      "rx_pdos": [ { "entries": [ { "index": "0x6200", "subindex": 1, "type": "UNSIGNED8", "iec_location": "%QB40" } ] } ] } ] })";
    std::string dir = make_dir(json, {{"fixed-io.eds", read(std::string(FIXTURES_DIR) + "/eds/fixed-io.eds")}});
    static Sim* sim;
    sim = new Sim(dir);
    CHECK(sim->ok());
    if (!sim->ok()) return;
    sim->SetProgram([](fake_runtime::Image& plc) { plc.byte_out[40] = 7; });
    // The fixture says device type 0; the simulation file makes it a CiA 401 module.
    CHECK(sim->StartSimulator(std::string(R"({"nodes": {"4": {"device_type": "0x00000191")") +
                              (defaults ? "" : R"(, "default_behaviour": false)") + "}}}"));
    sim->net().Start();
    CHECK(sim->RunUntil([] { return sim->status(); }, seconds(5)));
    bool looped = sim->RunUntil([] {
      cJSON* r = sim->SimAsk(R"({"op":"sim_get","items":[{"node":4,"object":"0x6000:1"}]})");
      bool v = num(cJSON_GetArrayItem(field(result(r), "values"), 0), "value") == 7;
      cJSON_Delete(r);
      return v;
    }, milliseconds(defaults ? 2000 : 500));
    CHECK_MSG(looped == (defaults == 1), defaults ? "no loopback" : "loopback without defaults");
    delete sim;
  }
}

// CiA 404 default: the RTD module's mapped values move slowly by themselves.
TEST(sim_simulated_rtd_defaults) {
  clear_logs();
  std::string eds = read(std::string(RTD_DIR) + "/rtd8.eds");
  std::string cfg = read(std::string(RTD_DIR) + "/canopen_config.json");
  cfg.replace(cfg.find("\"sync_period_us\": 100000"), 24, "\"sync_period_us\": 20000");
  std::string dir = make_dir(cfg, {{"rtd8.eds", eds}});
  static Sim* sim;
  sim = new Sim(dir);
  CHECK(sim->ok());
  if (!sim->ok()) return;
  CHECK(sim->StartSimulator(""));
  sim->net().Start();
  CHECK(sim->RunUntil([] { return sim->status(); }, seconds(5)));
  sim->RunFor(milliseconds(300));
  int16_t first = sim->iw(100);
  CHECK_MSG(sim->RunUntil([&] { return sim->iw(100) != first; }, seconds(3)), std::to_string(first));
  cJSON* r = sim->SimAsk(R"({"op":"sim_status"})");
  CHECK(num(cJSON_GetArrayItem(field(result(r), "devices"), 0), "profile") == 404);
  cJSON_Delete(r);
  delete sim;
}

// CiA 402: the drive model enables on the program's controlword and moves in
// profile velocity mode.
TEST(sim_simulated_drive) {
  clear_logs();
  std::string dir = make_dir(servo_json(), {{"servo-drive.eds", drive_eds(kServoEds)}, {"device.eds", servo_device_eds()}});
  static Sim* sim;
  sim = new Sim(dir);
  CHECK(sim->ok());
  if (!sim->ok()) return;
  sim->SetProgram([](fake_runtime::Image& plc) {
    uint16_t sw = plc.int_in[40];
    uint16_t cw = 0;
    if ((sw & 0x4F) == 0x40) cw = 0x06;        // switch on disabled -> shutdown
    else if ((sw & 0x6F) == 0x21) cw = 0x07;   // ready to switch on -> switch on
    else if ((sw & 0x6F) == 0x23) cw = 0x0F;   // switched on -> enable operation
    else if ((sw & 0x6F) == 0x27) cw = 0x0F;   // operation enabled
    else if (sw & 0x08) cw = 0x80;             // fault -> fault reset
    plc.int_out[40] = cw;
  });
  canopen_sim::DeviceSpec d;
  d.node = 3;
  d.eds_path = dir + "/device.eds";
  CHECK(sim->StartSimulator("", {d}));
  sim->net().Start();
  CHECK(sim->RunUntil([] { return sim->status(); }, seconds(10)));
  CHECK_MSG(sim->RunUntil([] { return (sim->uw(40) & 0x6F) == 0x27; }, seconds(3)), std::to_string(sim->uw(40)));
  cJSON* r = sim->SimAsk(R"({"op":"sim_set","node":3,"values":{"0x6060":3,"0x60FF":20000}})");
  CHECK(ok(r));
  cJSON_Delete(r);
  int32_t p0 = static_cast<int32_t>(sim->plc().dint_in[40]);
  CHECK(sim->RunUntil([&] { return static_cast<int32_t>(sim->plc().dint_in[40]) > p0 + 5000; }, seconds(3)));
  r = sim->SimAsk(R"({"op":"sim_status"})");
  CHECK(cJSON_IsTrue(field(cJSON_GetArrayItem(field(result(r), "devices"), 0), "drive")));
  cJSON_Delete(r);
  // A blocked axis in profile position: following error, fault, EMCY 0x8611.
  r = sim->SimAsk(R"({"op":"sim_fault","node":3,"fault":{"drive_input":{"blocked":true}}})");
  cJSON_Delete(r);
  delete sim;
}

// Extra devices: one more node, and one without a node ID waiting for LSS.
TEST(sim_simulated_extra_devices) {
  clear_logs();
  std::string dir = make_dir(pingpong_json(), {{"cpp-slave.eds", slave_eds()},
                                               {"lss.eds", read(std::string(FIXTURES_DIR) + "/eds/lss-slave.eds")}});
  static Sim* sim;
  sim = new Sim(dir);
  CHECK(sim->ok());
  if (!sim->ok()) return;
  CHECK(sim->StartSimulator(R"({"extra_devices": [
      {"node": 40, "name": "spare", "eds": "cpp-slave.eds"},
      {"node": 0, "name": "fresh", "eds": "lss.eds", "identity": {"serial_number": 1234}}],
    "nodes": {"2": {"sources": {"0x4001": {"expr": "[spare/0x4001] + 1"}}}}})"));
  sim->net().Start();
  CHECK(sim->RunUntil([] { return sim->status(); }, seconds(5)));
  CHECK(sim->RunUntil([] { return sim->in() == 1; }, seconds(2)));
  CHECK(sim->bootups(40) >= 1);
  cJSON* r = sim->SimAsk(R"({"op":"sim_status"})");
  const cJSON* devs = field(result(r), "devices");
  CHECK(cJSON_GetArraySize(devs) == 3);
  CHECK(str(cJSON_GetArrayItem(devs, 2), "name") == "fresh" && cJSON_IsString(field(cJSON_GetArrayItem(devs, 2), "node")));
  cJSON_Delete(r);
  r = sim->SimAsk(R"({"op":"sim_get","items":[{"node":"fresh","object":"0x1018:4"}]})");
  CHECK(num(cJSON_GetArrayItem(field(result(r), "values"), 0), "value") == 1234);
  cJSON_Delete(r);
  r = sim->SimAsk(R"({"op":"sim_check_expr","node":2,"expr":"[nobody/0x1000] + 1"})");
  CHECK(!cJSON_IsTrue(field(result(r), "ok")) && num(result(r), "position") == 0);
  cJSON_Delete(r);
  delete sim;
}

// 32 simulated devices with a value source each stay within a small CPU budget.
TEST(sim_simulated_cpu_budget) {
  clear_logs();
  std::string dir = make_dir(pingpong_json(), {{"cpp-slave.eds", slave_eds()}});
  static Sim* sim;
  sim = new Sim(dir);
  CHECK(sim->ok());
  if (!sim->ok()) return;
  std::string extra;
  for (int n = 10; n < 41; ++n)
    extra += std::string(extra.empty() ? "" : ",") + R"({"node": )" + std::to_string(n) +
             R"(, "eds": "cpp-slave.eds", "sources": {"0x4001": {"sine": {"min": 0, "max": 1000, "period_s": 2}}}})";
  CHECK(sim->StartSimulator(R"({"nodes": {"2": {"sources": {"0x4001": {"expr": "[0x4000]"}}}}, "extra_devices": [)" +
                            extra + "]}"));
  CHECK(sim->simulator().DeviceCount() == 32);
  sim->net().Start();
  CHECK(sim->RunUntil([] { return sim->status(); }, seconds(5)));
  auto cpu = [] {
    timespec ts;
    clock_gettime(CLOCK_PROCESS_CPUTIME_ID, &ts);
    return ts.tv_sec + ts.tv_nsec / 1e9;
  };
  double c0 = cpu();
  auto t0 = steady_clock::now();
  sim->RunFor(seconds(3));
  double load = (cpu() - c0) / std::chrono::duration<double>(steady_clock::now() - t0).count();
  std::printf("    CPU load with 32 simulated devices (and the master and fake PLC): %.1f %%\n", load * 100);
  CHECK_MSG(load < 0.10, std::to_string(load));
  delete sim;
}

// The SDO function blocks of library/openplc_canopen, built with the editor's
// glue, find the master's API table through this (CO_SDO_TEST_ENTRY) instead
// of dlopen; test/plc_sdo/lookup_check covers the dlopen route.
extern "C" const void* canopen_plc_api_test(uint32_t version) { return plc_api_table(version); }

namespace {

// Block instances the fake PLC program calls every scan.
struct SdoBlocks {
  CO_SDO_READ_INST rd, rd2, rd_node;
  CO_SDO_WRITE_INST wr;
  CO_SDO_READ_REAL_INST rdr;
  CO_SDO_WRITE_REAL_INST wrr;
  CO_SDO_READ_STRING_INST rds;
  CO_SDO_WRITE_STRING_INST wrs;
  CO_SDO_READ_BYTES_INST rdb;
  CO_SDO_WRITE_BYTES_INST wrb;
  CO_SDO_READ_INST many[65];
  bool call_many = false;
  void Scan() {
    co_sdo_read_call(&rd);
    co_sdo_read_call(&rd2);
    co_sdo_read_call(&rd_node);
    co_sdo_write_call(&wr);
    co_sdo_read_real_call(&rdr);
    co_sdo_write_real_call(&wrr);
    co_sdo_read_string_call(&rds);
    co_sdo_write_string_call(&wrs);
    co_sdo_read_bytes_call(&rdb);
    co_sdo_write_bytes_call(&wrb);
    if (call_many)
      for (auto& b : many) co_sdo_read_call(&b);
  }
};

template <class I>
void target(I& b, unsigned node, unsigned index, unsigned sub, int64_t timeout_ms = 0) {
  b.NODE = static_cast<uint8_t>(node);
  b.INDEX = static_cast<uint16_t>(index);
  b.SUBINDEX = static_cast<uint8_t>(sub);
  b.TIMEOUT = timeout_ms * 1000000;
}

// Raises EXECUTE, runs until DONE or ERROR, then drops EXECUTE.
template <class I>
bool run_block(Sim* sim, I& b, milliseconds timeout = milliseconds(3000)) {
  b.EXECUTE = true;
  bool ended = sim->RunUntil([&b] { return static_cast<bool>(b.DONE) || static_cast<bool>(b.ERROR); }, timeout);
  b.EXECUTE = false;
  sim->RunFor(milliseconds(30));
  return ended;
}

}  // namespace

// SDO transfers from the PLC program through the library's function blocks
// (spec canopen-plc-sdo).
TEST(sim_plc_sdo_blocks) {
  clear_logs();
  std::string eds = read(std::string(RTD_DIR) + "/rtd8.eds");
  std::string dir = make_dir(rtd_sim_config(""), {{"rtd8.eds", eds}, {"cpp-slave.eds", slave_eds()}});
  static Sim* sim;
  static SdoBlocks* blk;
  sim = new Sim(dir);
  blk = new SdoBlocks();
  CHECK(sim->ok());
  if (!sim->ok()) return;
  PlcRequests::instance().open();
  sim->SetProgram([](fake_runtime::Image&) { blk->Scan(); });
  sim->StartSlave(9, dir + "/cpp-slave.eds");  // a device the configuration does not list
  SdoBlocks& b = *blk;
  // A read the program starts in its first scans, before the master has heard
  // from the node, waits for the node's boot instead of failing, and its
  // TIMEOUT (here the default 1 s) starts only once the node can be asked.
  target(b.rd2, 5, 0x1018, 1);
  b.rd2.EXECUTE = true;
  sim->net().Start();
  sim->RunFor(milliseconds(1200));
  CHECK_MSG(b.rd2.BUSY, std::to_string(b.rd2.ERROR_ID.get()));
  sim->StartSensor(5, dir + "/rtd8.eds", {{0x7130, 1, 200, 260, 1}});
  CHECK(sim->RunUntil([&] { return static_cast<bool>(b.rd2.DONE) || static_cast<bool>(b.rd2.ERROR); }, seconds(5)));
  CHECK_MSG(b.rd2.DONE && b.rd2.DATA.get() == 0xF0F0F0u, std::to_string(b.rd2.ERROR_ID.get()));
  b.rd2.EXECUTE = false;
  CHECK(sim->RunUntil([] { return sim->status(); }, seconds(5)));

  // Integer read: DONE while EXECUTE is held, cleared once it drops.
  target(b.rd, 5, 0x1018, 1);
  b.rd.EXECUTE = true;
  CHECK(sim->RunUntil([&] { return static_cast<bool>(b.rd.DONE); }, seconds(2)));
  CHECK(!b.rd.BUSY && !b.rd.ERROR);
  CHECK_MSG(b.rd.DATA.get() == 0xF0F0F0u && b.rd.SIZE.get() == 4, std::to_string(b.rd.DATA.get()));
  sim->RunFor(milliseconds(50));
  CHECK(b.rd.DONE);
  b.rd.EXECUTE = false;
  sim->RunFor(milliseconds(30));
  CHECK(!b.rd.DONE);
  // Signed value: LWORD_TO_INT gives -200.
  target(b.rd, 5, 0x7134, 1);
  CHECK(run_block(sim, b.rd));
  CHECK_MSG(b.rd.DATA.get() == 0xFF38u && b.rd.SIZE.get() == 2, std::to_string(b.rd.DATA.get()));
  CHECK(static_cast<int16_t>(b.rd.DATA.get()) == -200);

  // Integer write with the size from the EDS (INTEGER16), read back.
  target(b.wr, 5, 0x7134, 1);
  b.wr.DATA = static_cast<uint64_t>(int64_t(-150));
  b.wr.SIZE = 0;
  CHECK(run_block(sim, b.wr));
  CHECK(!b.wr.ERROR);
  CHECK(run_block(sim, b.rd));
  CHECK_MSG(static_cast<int16_t>(b.rd.DATA.get()) == -150, std::to_string(b.rd.DATA.get()));

  // A value the device refuses: ERROR_ID 1 with the abort code, logged once.
  target(b.wr, 5, 0x6110, 1);
  b.wr.DATA = 0x40;
  for (int i = 0; i < 2; ++i) {
    CHECK(run_block(sim, b.wr));
    b.wr.EXECUTE = true;  // ERROR stays while EXECUTE is held
    sim->RunFor(milliseconds(30));
    CHECK(b.wr.ERROR && b.wr.ERROR_ID.get() == 1);
    b.wr.EXECUTE = false;
    sim->RunFor(milliseconds(30));
  }
  uint32_t abort = b.wr.ABORT_CODE.get();
  CHECK_MSG(abort == 0x06090031 || abort == 0x06090030, std::to_string(abort));
  CHECK(count_logs("PLC program SDO write of 0x6110 sub 1 aborted") == 1);
  CHECK(sim->net().IsOperational(5));

  // REAL32 write (size from the EDS) and read.
  target(b.wrr, 5, 0x6126, 1);
  b.wrr.VALUE = 12.5;
  b.wrr.SIZE = 0;
  CHECK(run_block(sim, b.wrr));
  CHECK(!b.wrr.ERROR);
  target(b.rdr, 5, 0x6126, 1);
  CHECK(run_block(sim, b.rdr));
  CHECK_MSG(b.rdr.VALUE.get() == 12.5, std::to_string(b.rdr.VALUE.get()));
  // A 5-byte object does not fit a REAL: ERROR_ID 7, VALUE kept.
  target(b.rdr, 5, 0x1008, 0);
  CHECK(run_block(sim, b.rdr));
  CHECK(b.rdr.ERROR_ID.get() == 7 && b.rdr.VALUE.get() == 12.5);

  // Strings: the device name; a 2-character string into a 16-bit object.
  target(b.rds, 5, 0x1008, 0);
  CHECK(run_block(sim, b.rds));
  CHECK_MSG(std::string(b.rds.VALUE.c_str()) == "RTD-8", b.rds.VALUE.c_str());
  target(b.wrs, 5, 0x7133, 1);
  b.wrs.VALUE = "AB";
  CHECK(run_block(sim, b.wrs));
  CHECK(!b.wrs.ERROR);
  target(b.rd, 5, 0x7133, 1);
  CHECK(run_block(sim, b.rd));
  CHECK_MSG(b.rd.DATA.get() == 0x4241u, std::to_string(b.rd.DATA.get()));

  // Bytes.
  target(b.rdb, 5, 0x1008, 0);
  CHECK(run_block(sim, b.rdb));
  CHECK(b.rdb.SIZE.get() == 5 && b.rdb.BUFFER[0].get() == 'R' && b.rdb.BUFFER[4].get() == '8');
  target(b.wrb, 5, 0x7133, 1);
  b.wrb.BUFFER[0] = 0x10;
  b.wrb.BUFFER[1] = 0x00;
  b.wrb.SIZE = 2;
  CHECK(run_block(sim, b.wrb));
  CHECK(!b.wrb.ERROR);
  CHECK(run_block(sim, b.rd));
  CHECK(b.rd.DATA.get() == 0x10u);

  // A device the configuration does not list; SIZE 0 needs its EDS.
  target(b.rd_node, 9, 0x1018, 1);
  CHECK(run_block(sim, b.rd_node));
  CHECK_MSG(!b.rd_node.ERROR && b.rd_node.SIZE.get() == 4,
            std::to_string(b.rd_node.ERROR_ID.get()));
  target(b.wr, 9, 0x2000, 0);
  b.wr.SIZE = 0;
  CHECK(run_block(sim, b.wr));
  CHECK(b.wr.ERROR_ID.get() == 6);

  // Bad node ID: ERROR_ID 6 in the same call.
  target(b.rd, 0, 0x1000, 0);
  b.rd.EXECUTE = true;
  sim->RunFor(milliseconds(15));
  CHECK(b.rd.ERROR && b.rd.ERROR_ID.get() == 6);
  b.rd.EXECUTE = false;
  sim->RunFor(milliseconds(30));

  // No answer: ERROR_ID 2 after TIMEOUT, logged.
  target(b.rd, 40, 0x1000, 0, 200);
  auto t0 = steady_clock::now();
  CHECK(run_block(sim, b.rd));
  auto took = duration_cast<milliseconds>(steady_clock::now() - t0).count();
  CHECK(b.rd.ERROR_ID.get() == 2 && b.rd.ABORT_CODE.get() == 0x05040000u);
  CHECK_MSG(took >= 150 && took < 1000, std::to_string(took));

  // Two blocks on one node in the same scan: both done, one after the other.
  target(b.rd, 5, 0x1018, 1);
  target(b.rd2, 5, 0x1008, 0);
  b.rd.EXECUTE = true;
  b.rd2.EXECUTE = true;
  CHECK(sim->RunUntil([&] { return b.rd.DONE && b.rd2.DONE; }, seconds(2)));
  b.rd.EXECUTE = false;
  b.rd2.EXECUTE = false;
  sim->RunFor(milliseconds(30));

  // 65 at once: 64 run or wait, one ends with ERROR_ID 5 in the same call.
  for (auto& m : b.many) {
    target(m, 40, 0x1000, 0, 300);
    m.EXECUTE = true;
  }
  b.call_many = true;
  sim->RunFor(milliseconds(15));
  int busy = 0, full = 0;
  for (auto& m : b.many) {
    busy += m.BUSY ? 1 : 0;
    full += m.ERROR && m.ERROR_ID.get() == 5 ? 1 : 0;
  }
  CHECK_MSG(busy == 64 && full == 1, std::to_string(busy) + " " + std::to_string(full));
  CHECK(sim->RunUntil([&] {
    for (auto& m : b.many)
      if (m.BUSY) return false;
    return true;
  }, seconds(3)));
  for (auto& m : b.many) m.EXECUTE = false;
  sim->RunFor(milliseconds(30));
  b.call_many = false;

  // Writing an object the plugin configures: sent, warned once.
  target(b.wr, 5, 0x100C, 0);
  b.wr.DATA = 0;
  b.wr.SIZE = 0;
  CHECK(run_block(sim, b.wr));
  CHECK(run_block(sim, b.wr));
  CHECK(count_logs("the PLC program writes 0x100C sub 0, which the plugin configures") == 1);

  // PLC stop during a transfer: ERROR_ID 8, then a new edge works.
  target(b.rd, 40, 0x1000, 0, 500);
  b.rd.EXECUTE = true;
  sim->RunFor(milliseconds(30));
  CHECK(b.rd.BUSY);
  PlcRequests::instance().close();
  PlcRequests::instance().open();
  sim->RunFor(milliseconds(30));
  CHECK(b.rd.ERROR && b.rd.ERROR_ID.get() == 8);
  b.rd.EXECUTE = false;
  sim->RunFor(milliseconds(600));  // the abandoned transfer ends unseen
  target(b.rd, 5, 0x1018, 1);
  CHECK(run_block(sim, b.rd));
  CHECK(!b.rd.ERROR && b.rd.DATA.get() == 0xF0F0F0u);

  // CANopen not running: ERROR_ID 4 in the same call.
  PlcRequests::instance().close();
  b.rd.EXECUTE = true;
  sim->RunFor(milliseconds(15));
  CHECK(b.rd.ERROR && b.rd.ERROR_ID.get() == 4);
  b.rd.EXECUTE = false;
  sim->RunFor(milliseconds(30));
  PlcRequests::instance().open();

  // A library asking for an unknown API version: logged once.
  CHECK(plc_api_table(99) == nullptr);
  CHECK(plc_api_table(1) != nullptr);
  sim->RunFor(milliseconds(50));
  CHECK(count_logs("asks for SDO block API version 99") == 1);

  // Node lost: ERROR_ID 3 at once.
  sim->Unplug(5);
  CHECK(sim->RunUntil([] { return !sim->status(); }, seconds(3)));
  CHECK(run_block(sim, b.rd, milliseconds(500)));
  CHECK_MSG(b.rd.ERROR_ID.get() == 3, std::to_string(b.rd.ERROR_ID.get()));

  PlcRequests::instance().close();
  delete sim;
  delete blk;
}

// A configured node that never answers: a read started at once waits for its
// first boot and ends with ERROR_ID 3 when the master reports it absent, not
// with a timeout of the default 1 s.
TEST(sim_plc_sdo_node_absent_at_start) {
  clear_logs();
  std::string eds = read(std::string(RTD_DIR) + "/rtd8.eds");
  std::string dir = make_dir(rtd_sim_config(""), {{"rtd8.eds", eds}});
  static Sim* sim;
  static CO_SDO_READ_INST* rd;
  sim = new Sim(dir);
  rd = new CO_SDO_READ_INST();
  CHECK(sim->ok());
  if (!sim->ok()) return;
  PlcRequests::instance().open();
  sim->SetProgram([](fake_runtime::Image&) { co_sdo_read_call(rd); });
  target(*rd, 5, 0x1018, 1);
  rd->EXECUTE = true;
  sim->net().Start();
  sim->RunFor(milliseconds(1500));
  CHECK_MSG(rd->BUSY, std::to_string(rd->ERROR_ID.get()));
  CHECK(sim->RunUntil([] { return static_cast<bool>(rd->ERROR) || static_cast<bool>(rd->DONE); }, seconds(4)));
  CHECK_MSG(rd->ERROR && rd->ERROR_ID.get() == 3, std::to_string(rd->ERROR_ID.get()));
  CHECK(logged("not answering"));
  PlcRequests::instance().close();
  delete sim;
  delete rd;
}

// ---------------------------------------------------------------------------
// CiA 402 axis: the example's demo program (config/cia402-drive/drive_demo.st),
// compiled by STruC++ with the editor's PLCopen motion blocks, runs as the PLC
// program against a simulated CiA 402 drive through the real master: power
// on, homing, a move to 1000, 2 s at 200 units/s, halt; then a drive fault
// and a lost drive, each followed by the fault reset and a new run.

TEST(sim_cia402_demo) {
#ifndef CIA402_PROGRAM
  const char* need = std::getenv("CANOPEN_REQUIRE_STRUCPP");
  std::printf("    not built: configure with -DSTRUCPP=$(scripts/fetch-strucpp.sh) to run the CiA 402 demo program\n");
  CHECK_MSG(!(need && std::string(need) == "1"), "CANOPEN_REQUIRE_STRUCPP=1 but the CiA 402 program was not built");
#else
  clear_logs();
  std::string dir = make_dir(read(std::string(CIA402_DIR) + "/canopen_config.json"),
                             {{"servo402.eds", read(std::string(CIA402_DIR) + "/servo402.eds")}});
  static Sim* sim;
  sim = new Sim(dir);
  if (!sim->ok()) {
    CHECK(sim->ok());
    return;
  }
  program_host::Reset();
  CHECK(program_host::LocatedCount() == 10);
  auto t0 = steady_clock::now();
  sim->SetProgram([t0](fake_runtime::Image& plc) {
    program_host::Image img{plc.bool_in, plc.bool_out, plc.byte_in, plc.byte_out, plc.int_in,
                            plc.int_out, plc.dint_in, plc.dint_out, fake_runtime::kSize};
    program_host::Scan(img, std::chrono::duration_cast<std::chrono::nanoseconds>(steady_clock::now() - t0).count());
  });
  Cia402Slave* drive = sim->StartCia402Drive(4, dir + "/servo402.eds");
  sim->net().Start();
  auto step = [] { return program_host::Step(); };
  auto where = [&] {
    return "step " + std::to_string(step()) + ", drive state " + std::to_string(drive->state.load()) + ", position " +
           std::to_string(drive->position.load()) + ", velocity " + std::to_string(drive->velocity.load()) +
           ", %IW100 " + std::to_string(sim->uw(100));
  };

  // Power on, home, move to 1000.
  CHECK_MSG(sim->RunUntil([&] { return step() == 30; }, seconds(20)), where());
  CHECK_MSG(drive->position == 1000, where());
  CHECK(sim->status());
  // 200 units/s in profile velocity, then halt after 2 s.
  CHECK_MSG(sim->RunUntil([&] { return drive->velocity == 200; }, seconds(3)), where());
  CHECK_MSG(sim->RunUntil([&] { return step() == 50; }, seconds(5)), where());
  CHECK_MSG(drive->velocity == 0 && drive->state == 4, where());
  CHECK(drive->position > 1300);
  std::printf("    demo done: %s\n", where().c_str());

  // A drive fault: the program resets it and runs the sequence again.
  drive->fault = true;
  CHECK_MSG(sim->RunUntil([&] { return step() == 90; }, seconds(2)), where());
  sim->RunFor(milliseconds(300));
  drive->fault = false;
  CHECK_MSG(sim->RunUntil([&] { return step() == 30; }, seconds(20)), where());
  CHECK(drive->fault_resets >= 1);

  // The drive goes away: the status bit drops and the axis is in error stop.
  sim->KillSlave(4);
  CHECK_MSG(sim->RunUntil([&] { return !sim->status() && step() == 90; }, seconds(3)), where());
  CHECK(!logged("boot failed"));
  delete sim;
#endif
}

// ---------------------------------------------------------------------------
// Cyclic synchronous CiA 402 (add-cia402-cyclic-modes): the cyclic demo
// (config/cia402-drive/drive_cyclic_demo.st with the CO402_Cyclic* blocks of
// the openplc_canopen library) as the PLC program, SYNC from the PLC cycle,
// against the in-plugin simulated drive: 0x60C2 written from the base tick,
// the sequence ends without a fault and without an oversized CSP step; the
// PLC stops, the drive's SYNC watchdog faults it, and after the restart the
// program's fault reset brings it back.

TEST(sim_cia402_cyclic) {
#ifndef CIA402_PROGRAM
  const char* need = std::getenv("CANOPEN_REQUIRE_STRUCPP");
  std::printf("    not built: configure with -DSTRUCPP=$(scripts/fetch-strucpp.sh) to run the cyclic demo program\n");
  CHECK_MSG(!(need && std::string(need) == "1"), "CANOPEN_REQUIRE_STRUCPP=1 but the cyclic program was not built");
#else
  clear_logs();
  std::string dir = make_dir(read(std::string(CIA402_DIR) + "/canopen_config_cyclic.json"),
                             {{"servo402.eds", read(std::string(CIA402_DIR) + "/servo402.eds")}});
  static Sim* sim;
  sim = new Sim(dir, 10000);  // 10 ms task: the Sim scans every 10 ms
  if (!sim->ok()) {
    CHECK(sim->ok());
    return;
  }
  CHECK(sim->cfg().nodes[0].interpolation_write_us == 10000);
  program_host_cyclic::Reset();
  CHECK(program_host_cyclic::LocatedCount() == 11);
  auto t0 = steady_clock::now();
  sim->SetProgram([t0](fake_runtime::Image& plc) {
    program_host_cyclic::Image img{plc.bool_in, plc.bool_out, plc.byte_in, plc.byte_out, plc.int_in,
                                   plc.int_out, plc.dint_in, plc.dint_out, fake_runtime::kSize};
    program_host_cyclic::Scan(img,
                              std::chrono::duration_cast<std::chrono::nanoseconds>(steady_clock::now() - t0).count());
  });
  // max_velocity 600 counts/s: a CSP set-point step above 6 counts per SYNC
  // is counted; the torque gain of the ST drive model (test/cia402).
  if (!sim->StartSimulator(R"({"nodes": {"4": {"drive": {"max_velocity": 600, "torque_accel": 10}}}})")) {
    CHECK(!"simulator started");
    delete sim;
    return;
  }
  sim->net().Start();
  auto step = [] { return program_host_cyclic::Step(); };
  auto get = [](const char* object) {
    cJSON* r = sim->SimAsk(std::string(R"({"op":"sim_get","items":[{"node":4,"object":")") + object + "\"}]}");
    double v = num(cJSON_GetArrayItem(field(result(r), "values"), 0), "value");
    cJSON_Delete(r);
    return v;
  };
  auto oversized = [] {
    cJSON* r = sim->SimAsk(R"({"op":"sim_status"})");
    double v = num(cJSON_GetArrayItem(field(result(r), "devices"), 0), "oversized_steps");
    cJSON_Delete(r);
    return v;
  };
  auto where = [&] {
    return "step " + std::to_string(step()) + ", statusword " + std::to_string(sim->uw(100)) + ", mode " +
           std::to_string(static_cast<int8_t>(sim->ib(100))) + ", position " +
           std::to_string(static_cast<int32_t>(sim->plc().dint_in[100]));
  };

  // Power on, home, CSP move, CSV run, CST step, standstill in CSV.
  CHECK_MSG(sim->RunUntil([&] { return step() == 20; }, seconds(20)), where());
  CHECK(get("0x60C2:1") == 10 && get("0x60C2:2") == -3);
  CHECK_MSG(sim->RunUntil([&] { return step() == 30; }, seconds(20)), where());
  CHECK_MSG(std::abs(static_cast<int32_t>(sim->plc().dint_in[100]) - 1000) <= 1, where());
  CHECK_MSG(sim->RunUntil([&] { return step() == 50; }, seconds(30)), where());
  sim->RunFor(milliseconds(300));
  CHECK_MSG(step() == 50 && (sim->uw(100) & 0x6F) == 0x27 && static_cast<int8_t>(sim->ib(100)) == 9, where());
  CHECK_MSG(oversized() == 0, std::to_string(oversized()));
  // No EMCY from the drive (the master's own boot-time PDO length EMCY, from
  // the simulated device's PDOs before its configuration, does not count).
  // On a loaded machine a scan can come 30 ms late; then the drive's SYNC
  // watchdog is right to fault it, and the program has reset it.
  uint64_t max_us = sim->net().sync_stats().max_us;
  if (logged("(drive): EMCY 0x8700") && max_us >= 30000)
    std::printf("    a %llu us SYNC gap faulted the drive during the demo (machine under load)\n",
                static_cast<unsigned long long>(max_us));
  else
    CHECK_MSG(!logged("(drive): EMCY 0x"), "max SYNC interval " + std::to_string(max_us) + " us");
  CHECK(!logged("the drive interpolates with the wrong period"));
  std::printf("    demo done: %s\n", where().c_str());

  // The PLC stops: no SYNC, the drive faults by its watchdog (EMCY 0x8700).
  clear_logs();
  sim->StopPlc(true);
  CHECK_MSG(sim->RunUntil([&] { return get("0x603F") == 0x8700; }, seconds(2)), where());
  CHECK_MSG(sim->RunUntil([] { return logged("(drive): EMCY 0x8700"); }, seconds(2)), "no EMCY 0x8700 logged");
  // The PLC starts again: the program sees the fault, resets it and runs the sequence again.
  sim->StopPlc(false);
  CHECK_MSG(sim->RunUntil([&] { return step() == 90; }, seconds(2)), where());
  CHECK_MSG(sim->RunUntil([&] { return step() == 30; }, seconds(30)), where());
  CHECK(oversized() == 0);
  delete sim;
#endif
}

// A cyclic axis whose 0x60C2 period (here from a 5 ms base tick) is not the
// measured SYNC interval (a 10 ms scan): one warning after 100 SYNCs.
TEST(sim_cia402_cyclic_period_warning) {
  clear_logs();
  std::string dir = make_dir(read(std::string(CIA402_DIR) + "/canopen_config_cyclic.json"),
                             {{"servo402.eds", read(std::string(CIA402_DIR) + "/servo402.eds")}});
  static Sim* sim;
  sim = new Sim(dir, 5000);
  if (!sim->ok()) {
    CHECK(sim->ok());
    return;
  }
  CHECK(sim->cfg().nodes[0].interpolation_write_us == 5000);
  sim->SetProgram([](fake_runtime::Image&) {});
  if (!sim->StartSimulator("")) {
    CHECK(!"simulator started");
    delete sim;
    return;
  }
  sim->net().Start();
  CHECK(sim->RunUntil([] { return sim->status(); }, seconds(10)));
  CHECK_MSG(sim->RunUntil([] { return logged("the drive interpolates with the wrong period"); }, seconds(5)),
            std::to_string(sim->net().sync_stats().count) + " SYNCs");
  CHECK(logged("node 4 (drive): cyclic axis: interpolation time period 5000 us, but the measured SYNC interval is"));
  sim->RunFor(milliseconds(1500));
  size_t n = 0;
  for (const auto& l : logs()) n += l.find("the drive interpolates with the wrong period") != std::string::npos;
  CHECK(n == 1);
  delete sim;
}

int main(int argc, char** argv) {
  set_log_sink(capture);
  route_lely_diagnostics();
  return check::run_all(argc, argv);
}

// ---------------------------------------------------------------------------
// Several networks (canopen-networks spec): two masters, each on its own
// virtual bus, with the same node ID on both and one PLC scan for both.

namespace {

std::string two_networks_json() {
  auto net = [](const char* name, const char* iface, int n) {
    std::string s = std::to_string(n);
    return std::string(R"({ "name": ")") + name + R"(", "adapter": { "type": "socketcan", "interface": ")" + iface +
           R"(", "bitrate": 125000 }, "master": { "node_id": 1, "sync_period_us": 20000 },
      "nodes": [ { "node_id": 2, "name": "pingpong", "eds": "cpp-slave.eds", "heartbeat_ms": 50, "heartbeat_timeout_ms": 200,
        "status_location": "%IX10.)" + s + R"(",
        "tx_pdos": [ { "entries": [ { "index": "0x4001", "type": "UNSIGNED32", "iec_location": "%ID10)" + s + R"(" } ] } ],
        "rx_pdos": [ { "entries": [ { "index": "0x4000", "type": "UNSIGNED32", "iec_location": "%QD10)" + s + R"(" } ] } ] } ] })";
  };
  return R"({ "schema_version": 2, "networks": [ )" + net("io", "sim0", 0) + ", " + net("drives", "sim1", 1) + " ] }";
}

class TwoNetSim {
 public:
  struct Net {
    Net(io::Poll& poll, ev::Executor& exec, io::Context& ctx)
        : timer(poll, exec, CLOCK_MONOTONIC), sup(poll, exec, CLOCK_MONOTONIC), req(poll, exec, CLOCK_MONOTONIC),
          out(poll, exec, CLOCK_MONOTONIC), ctrl(timer.get_clock()), chan(ctx, exec) {}
    io::Timer timer, sup, req, out;
    io::VirtualCanController ctrl;
    io::VirtualCanChannel chan;
    GeneratedConfig gen;
    ProcessImage image;
    std::unique_ptr<Network> net;
    std::unique_ptr<Sim::SlaveBox> slave;
  };

  explicit TwoNetSim(const std::string& dir)
      : poll_(ctx_), loop_(poll_.get_poll()), exec_(loop_.get_executor()), scan_timer_(poll_, exec_, CLOCK_MONOTONIC) {
    std::vector<std::string> errors;
    ok_ = load_config_set(dir + "/canopen_config.json", ImageLimits(), set_, errors);
    for (auto& cfg : set_.networks) {
      nets_.emplace_back(new Net(poll_, exec_, ctx_));
      Net& n = *nets_.back();
      ok_ = ok_ && run_eds_lint(cfg, default_edslint_python(), cfg.work_dir, errors) && check_eds_files(cfg, errors) &&
            generate_device_config(cfg, default_dcfgen(), n.gen, errors);
    }
    for (const auto& e : errors) std::printf("  setup: %s\n", e.c_str());
    if (!ok_ || set_.networks.size() != 2) {
      ok_ = false;
      return;
    }
    fake_runtime::attach(fake_, rt_);
    for (size_t i = 0; i < 2; ++i) {
      Net& n = *nets_[i];
      n.image.build(set_.networks[i]);
      n.chan.open(n.ctrl);
      n.net.reset(new Network(exec_, n.timer, n.sup, n.chan, set_.networks[i], n.gen, n.image, nullptr, &n.req, &n.out));
    }
    scan_timer_.settime(milliseconds(10), milliseconds(10));
    scan_timer_.submit_wait(exec_, [this](int, std::error_code ec) {
      if (!ec) Scan();
    });
  }

  ~TwoNetSim() {
    for (auto& n : nets_) n->slave.reset();
    for (auto& n : nets_)
      if (n->net) n->net->Stop();
    ctx_.shutdown();
    loop_.restart();
    for (int i = 0; i < 20 && !loop_.stopped(); ++i) loop_.run_for(milliseconds(100));
    if (!loop_.stopped()) loop_.stop();
    for (auto& n : nets_) n->net.reset();
  }

  bool ok() const { return ok_; }
  const ConfigSet& set() const { return set_; }
  Net& net(size_t i) { return *nets_[i]; }

  void StartSlave(size_t i, const std::string& eds) {
    nets_[i]->slave.reset(new Sim::SlaveBox(nets_[i]->ctrl, [=](io::TimerBase& t, io::CanChannelBase& c) {
      return new PingPongSlave(t, c, eds, "", 2);
    }));
  }
  void Unplug(size_t i) { nets_[i]->slave->Unplug(); }
  void Replug(size_t i) { nets_[i]->slave->Replug(nets_[i]->ctrl); }

  template <class F>
  bool RunUntil(F pred, milliseconds timeout) {
    auto end = steady_clock::now() + timeout;
    while (steady_clock::now() < end) {
      loop_.run_for(milliseconds(5));
      loop_.restart();
      if (pred()) return true;
    }
    return pred();
  }
  void RunFor(milliseconds d) {
    RunUntil([] { return false; }, d);
  }

  bool status(int i) { return fake_.bool_in[10][i] != 0; }
  uint32_t in(int i) { return fake_.dint_in[100 + i]; }
  void SetProgram(std::function<void()> program) { program_ = std::move(program); }
  // Scans in which both inputs had changed since the scan before.
  long both_new() const { return both_new_; }

 private:
  void Scan() {
    // cycle_start for every network, the program, cycle_end for every network
    for (auto& n : nets_) n->image.copy_to_plc(rt_);
    uint32_t a = fake_.dint_in[100], b = fake_.dint_in[101];
    if (a != last_[0] && b != last_[1]) ++both_new_;
    last_[0] = a;
    last_[1] = b;
    fake_.dint_out[100] = a + 1;
    fake_.dint_out[101] = b + 1000;
    if (program_) program_();
    for (auto& n : nets_) n->image.copy_from_plc(rt_);
    scan_timer_.submit_wait(exec_, [this](int, std::error_code ec) {
      if (!ec) Scan();
    });
  }

  io::IoGuard io_guard_;
  io::Context ctx_;
  io::Poll poll_;
  ev::Loop loop_;
  ev::Executor exec_;
  io::Timer scan_timer_;
  ConfigSet set_;
  std::vector<std::unique_ptr<Net>> nets_;
  fake_runtime::Image fake_;
  plugin_runtime_args_t rt_;
  std::function<void()> program_;
  uint32_t last_[2] = {0, 0};
  long both_new_ = 0;
  bool ok_ = false;
};

}  // namespace

TEST(sim_two_networks) {
  clear_logs();
  std::string dir = make_dir(two_networks_json(), {{"cpp-slave.eds", slave_eds()}});
  static TwoNetSim* sim;
  sim = new TwoNetSim(dir);
  CHECK(sim->ok());
  if (!sim->ok()) {
    delete sim;
    return;
  }
  // Each network generates into its own folder.
  struct stat st;
  CHECK(stat((dir + "/.canopen/io/master.dcf").c_str(), &st) == 0);
  CHECK(stat((dir + "/.canopen/drives/master.dcf").c_str(), &st) == 0);
  // Node 2 on both buses, each with its own master.
  sim->StartSlave(0, dir + "/cpp-slave.eds");
  sim->StartSlave(1, dir + "/cpp-slave.eds");
  sim->net(0).net->Start();
  sim->net(1).net->Start();
  CHECK(sim->RunUntil([] { return sim->status(0) && sim->status(1); }, seconds(5)));
  // Both counters run: io adds 1, drives adds 1000 per round trip.
  uint32_t a0 = sim->in(0), a1 = sim->in(1);
  CHECK(sim->RunUntil([&] { return sim->in(0) >= a0 + 10 && sim->in(1) >= a1 + 10000; }, seconds(5)));
  CHECK_MSG(sim->in(1) % 1000 == 0, std::to_string(sim->in(1)));
  // Values from both networks arrive in the same scans.
  CHECK(sim->both_new() > 0);

  // The SDO blocks reach each network by its NETWORK number.
  static CO_SDO_READ_INST rd[3];
  PlcRequests::instance().open(2);
  sim->SetProgram([] {
    for (auto& b : rd) co_sdo_read_call(&b);
  });
  auto read = [](unsigned i, unsigned network) {
    rd[i].NETWORK = static_cast<uint8_t>(network);
    target(rd[i], 2, 0x1017, 0);
    rd[i].EXECUTE = true;
  };
  auto ended = [](unsigned i) { return static_cast<bool>(rd[i].DONE) || static_cast<bool>(rd[i].ERROR); };
  read(0, 0);
  read(1, 1);
  read(2, 2);
  CHECK(sim->RunUntil([&] { return ended(0) && ended(1) && ended(2); }, seconds(3)));
  CHECK_MSG(rd[0].DONE && rd[0].DATA.get() == 50, std::to_string(rd[0].ERROR_ID.get()));
  CHECK_MSG(rd[1].DONE && rd[1].DATA.get() == 50, std::to_string(rd[1].ERROR_ID.get()));
  CHECK(rd[2].ERROR && rd[2].ERROR_ID.get() == CANOPEN_PLC_ERR_INPUT);
  for (auto& b : rd) b.EXECUTE = false;
  sim->RunFor(milliseconds(30));

  // The drives bus loses its node; io keeps exchanging.
  sim->Unplug(1);
  CHECK(sim->RunUntil([] { return !sim->status(1); }, seconds(3)));
  CHECK(sim->status(0));
  // A read on drives ends as unavailable; the same read on io still works.
  read(0, 0);
  read(1, 1);
  CHECK(sim->RunUntil([&] { return ended(0) && ended(1); }, seconds(3)));
  CHECK_MSG(rd[0].DONE, std::to_string(rd[0].ERROR_ID.get()));
  CHECK_MSG(rd[1].ERROR && rd[1].ERROR_ID.get() == CANOPEN_PLC_ERR_UNAVAILABLE, std::to_string(rd[1].ERROR_ID.get()));
  for (auto& b : rd) b.EXECUTE = false;
  sim->RunFor(milliseconds(30));
  sim->SetProgram(nullptr);
  uint32_t held = sim->in(1), b0 = sim->in(0);
  sim->RunFor(milliseconds(500));
  CHECK_MSG(sim->in(0) > b0 + 1, "io counter " + std::to_string(b0) + " -> " + std::to_string(sim->in(0)));
  CHECK(sim->in(1) == held);  // inputs hold
  // Back on the bus: drives comes back without disturbing io.
  sim->Replug(1);
  CHECK(sim->RunUntil([] { return sim->status(1); }, seconds(10)));
  CHECK(sim->status(0));
  delete sim;
  PlcRequests::instance().close();
}
