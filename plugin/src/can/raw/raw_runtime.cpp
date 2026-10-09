// raw_runtime.cpp - see raw_runtime.h.

#include "raw_runtime.h"

#include "../can_adapter.h"
#include "../diag.h"
#include "../frame_tx.h"
#include "../log.h"
#include <cstring>

#include "cJSON.h"

namespace canworks_raw {

using namespace canopen_plugin;

namespace {

const char* plural(size_t n) { return n == 1 ? "" : "s"; }

std::string frame_hex(const canworks_can_frame& f) {
  static const char* hex = "0123456789ABCDEF";
  std::string s;
  for (unsigned i = 0; i < f.dlc && i < 8; ++i) {
    if (i) s += ' ';
    s += hex[f.data[i] >> 4];
    s += hex[f.data[i] & 0xF];
  }
  return s;
}

}  // namespace

RawRuntime::RawRuntime(const Config& cfg)
    : cfg_(cfg),
      index_(static_cast<uint8_t>(cfg.network_index)),
      prefix_(cfg.log_prefix.empty() ? "" : cfg.log_prefix + ": ") {}

RawRuntime::~RawRuntime() {
  stop();
  set_port(index_, nullptr);
  if (bridge_ && !bridge_->loopback()) set_sim_bridge(index_, nullptr);
  if (devices_) set_sim_devices(index_, nullptr);
  if (adapter_) adapter_->release();
}

bool RawRuntime::make(const ConfigSet& set, std::vector<std::string>& errors) {
  if (!cfg_.raw.empty()) {
    engine_.reset(new RawEngine(cfg_.raw));
    in_.resize(engine_->input_values().size());
    out_.resize(engine_->output_locations().size());
  }
  // Which 11-bit identifiers the protocol owns, for the program's sends
  // (checked on the scan thread, so looked up, never computed there).
  owned_std_.assign(0x800, 0);
  for (uint32_t id = 0; id < 0x800; ++id) owned_std_[id] = protocol_id_use(cfg_, id, false).empty() ? 0 : 1;
  port_.reset(new PlcPort(index_));
  PortRules rules;
  rules.listen_only = cfg_.adapter.listen_only;
  rules.override_protocol = cfg_.raw.program_override_protocol;
  const std::vector<uint8_t>* owned = &owned_std_;
  bool j1939 = cfg_.is_j1939();
  unsigned sa = cfg_.j1939.ecu.address, lo = 0, hi = 0;
  if (j1939 && cfg_.j1939.ecu.has_range) {
    lo = cfg_.j1939.ecu.range_low;
    hi = cfg_.j1939.ecu.range_high;
  }
  bool has_range = j1939 && cfg_.j1939.ecu.has_range;
  rules.owned = [owned, j1939, sa, has_range, lo, hi](uint32_t id, bool ext) {
    if (!ext) return id < owned->size() && (*owned)[id] != 0;
    if (!j1939) return false;
    unsigned s = id & 0xFF;
    return s == sa || (has_range && s >= lo && s <= hi);
  };
  port_->set_rules(std::move(rules));

  if (cfg_.adapter.simulate) {
    std::string path = find_simulation_file(cfg_.config_dir, default_eds_fallback_dir());
    devices_.reset(new RawSimDevices);
    if (!path.empty()) {
      std::string name = cfg_.network.empty() ? cfg_.adapter.interface : cfg_.network;
      if (!devices_->load(path, name, set.several(), cfg_.is_plain(), errors)) return false;
    }
    bridge_ = std::make_shared<SimBridge>(cfg_.is_plain());
    if (cfg_.is_plain())
      injector_ = std::make_shared<SimFrameInjector>();
    else
      set_sim_bridge(index_, bridge_);
    set_sim_devices(index_, devices_.get());
  } else {
    if (cfg_.is_plain()) adapter_ = make_adapter(cfg_.adapter);
    link_ops_ = make_netlink_ops();
  }
  set_port(index_, port_.get());
  return true;
}

bool RawRuntime::prepare_adapter() {
  AdapterState st = adapter_->prepare();
  if (st == AdapterState::Ready) {
    adapter_problem_.clear();
    return true;
  }
  std::string p = adapter_->problem();
  if (p != adapter_problem_) {
    ScopedLogPrefix prefix(prefix_);
    log_warn("%s; retrying", p.c_str());
  }
  adapter_problem_ = p;
  return false;
}

void RawRuntime::bus_info(canworks_can_bus_info& info) {
  if (cfg_.adapter.simulate) {
    info.state = 0;
    return;
  }
  LinkInfo li;
  if (!link_ops_ || link_ops_->get(cfg_.adapter.interface, li) < 0 || !li.up) {
    info.state = 4;
    return;
  }
  info.state = li.has_can_state ? static_cast<uint8_t>(li.can_state > 3 ? 4 : li.can_state) : 0;
  if (li.has_berr) {
    info.tx_errors = static_cast<uint8_t>(li.tx_errors > 255 ? 255 : li.tx_errors);
    info.rx_errors = static_cast<uint8_t>(li.rx_errors > 255 ? 255 : li.rx_errors);
  }
}

void RawRuntime::start() {
  if (io_) return;
  RawIoHooks hooks;
  if (engine_) {
    hooks.publish_inputs = [this](const std::vector<uint64_t>& v) {
      uint64_t* b = in_.back();
      for (size_t i = 0; i < v.size() && i < in_.size(); ++i) b[i] = v[i];
      in_.publish();
    };
    hooks.latest_outputs = [this](std::vector<uint64_t>& v) {
      bool fresh = false;
      const uint64_t* p = out_.latest(&fresh);
      if (!fresh) return false;
      for (size_t i = 0; i < v.size() && i < out_.size(); ++i) v[i] = p[i];
      return true;
    };
  }
  hooks.bus_info = [this](canworks_can_bus_info& info) { bus_info(info); };
  if (adapter_) hooks.prepare = [this] { return prepare_adapter(); };
  hooks.host_frames_received = cfg_.is_plain();
  // Waiting for the interface is worth a line only when the network has
  // raw messages or is the plain network's own: otherwise nothing waits.
  if (engine_ || cfg_.is_plain()) {
    std::string prefix = prefix_;
    hooks.log = [prefix](const std::string& line) {
      ScopedLogPrefix p(prefix);
      log_info("%s", line.c_str());
    };
  }
  std::unique_ptr<RawLink> link = bridge_ ? make_bridge_link(bridge_) : make_socket_link(cfg_.adapter.interface);
  io_.reset(new RawIo(std::move(link), cfg_.adapter.bitrate, cfg_.adapter.listen_only, engine_.get(), port_.get(),
                      std::move(hooks), devices_.get(), injector_));
  io_->start();
}

void RawRuntime::stop() {
  if (!io_) return;
  io_->stop();
  io_.reset();
  if (port_) port_->cancel_all();
}

void RawRuntime::cycle_start(const plugin_runtime_args_t& rt) {
  if (!engine_ || !in_.size()) return;
  bool fresh = false;
  const uint64_t* v = in_.latest(&fresh);
  if (!fresh) return;
  const std::vector<IecLocation>& locs = engine_->input_locations();
  for (size_t i = 0; i < locs.size(); ++i) image_write_input(rt, locs[i], v[i]);
}

void RawRuntime::cycle_end(const plugin_runtime_args_t& rt) {
  if (!engine_ || !out_.size()) return;
  uint64_t* b = out_.back();
  const std::vector<IecLocation>& locs = engine_->output_locations();
  for (size_t i = 0; i < locs.size(); ++i) b[i] = image_read_output(rt, locs[i]);
  out_.publish();
}

std::unique_ptr<TraceSource> RawRuntime::trace_source() {
  return bridge_ && bridge_->loopback() ? bridge_->trace_source() : nullptr;
}

cJSON* RawRuntime::status() {
  cJSON* r = cJSON_CreateObject();
  RawIo* io = io_.get();
  const char* confirm = "unknown";
  if (io && io->confirm_mode() == Confirm::Echo) confirm = "echo";
  if (io && io->confirm_mode() == Confirm::Write) confirm = "write";
  cJSON_AddBoolToObject(r, "running", port_ && port_->running());
  cJSON_AddBoolToObject(r, "listen_only", cfg_.adapter.listen_only);
  cJSON_AddStringToObject(r, "confirm", confirm);
  cJSON_AddNumberToObject(r, "frames_sent", io ? static_cast<double>(io->frames_sent()) : 0);
  cJSON_AddNumberToObject(r, "frames_received", io ? static_cast<double>(io->frames_received()) : 0);
  cJSON_AddNumberToObject(r, "bus_load", io ? io->bus_load() : 0);
  cJSON* prog = cJSON_AddObjectToObject(r, "program");
  if (port_) {
    PlcPort::Stats s = port_->stats();
    cJSON_AddNumberToObject(prog, "receivers", s.receivers);
    cJSON_AddNumberToObject(prog, "cyclic_jobs", s.cyclic_jobs);
    cJSON_AddNumberToObject(prog, "frames_sent", s.sent);
    cJSON_AddNumberToObject(prog, "dropped", s.dropped);
  }
  cJSON* rx = cJSON_AddArrayToObject(r, "rx");
  cJSON* tx = cJSON_AddArrayToObject(r, "tx");
  auto fill = [&](const RawEngine& e) {
    uint64_t now = monotonic_us();
    for (size_t i = 0; i < e.config().rx.size(); ++i) {
      const RawRx& m = e.config().rx[i];
      const RawEngine::RxStatus& s = e.rx_status()[i];
      cJSON* o = cJSON_CreateObject();
      cJSON_AddStringToObject(o, "message", m.label().c_str());
      cJSON_AddNumberToObject(o, "count", s.count);
      cJSON_AddNumberToObject(o, "short_frames", s.short_frames);
      cJSON_AddBoolToObject(o, "seen", s.seen);
      cJSON_AddBoolToObject(o, "timed_out", s.timed_out);
      if (s.seen) {
        cJSON_AddNumberToObject(o, "age_ms", static_cast<double>((now - s.last_us) / 1000));
        cJSON_AddNumberToObject(o, "last_id", s.last.id);
        cJSON_AddNumberToObject(o, "last_dlc", s.last.dlc);
        cJSON_AddStringToObject(o, "last_data", frame_hex(s.last).c_str());
      }
      cJSON_AddItemToArray(rx, o);
    }
    for (size_t i = 0; i < e.config().tx.size(); ++i) {
      const RawTx& m = e.config().tx[i];
      const RawEngine::TxStatus& s = e.tx_status()[i];
      cJSON* o = cJSON_CreateObject();
      cJSON_AddStringToObject(o, "message", m.label().c_str());
      cJSON_AddNumberToObject(o, "count", s.count);
      if (s.last_error) cJSON_AddStringToObject(o, "error", std::strerror(s.last_error));
      cJSON_AddItemToArray(tx, o);
    }
  };
  if (io)
    io->with_engine(fill);
  else if (engine_)
    fill(*engine_);
  if (devices_ && devices_->size()) {
    cJSON* d = cJSON_AddArrayToObject(r, "simulated_devices");
    for (const auto& n : devices_->names()) cJSON_AddItemToArray(d, cJSON_CreateString(n.c_str()));
  }
  return r;
}

// --- Plain CAN networks ---

namespace {

class PlainRuntime : public NetworkRuntime {
 public:
  PlainRuntime(RawRuntime* raw, const char* version) : raw_(raw) {
    if (raw->config().master.has_diagnostics) {
      hub_.reset(new DiagHub(raw->config(), version));
      hub_->set_raw_status([raw] { return raw->status(); });
      hub_->set_raw_running([raw] { return raw->running(); });
    }
  }
  // The plugin starts, stops and scans `raw` with the other networks' raw paths.
  void start() override {}
  void stop() override {}
  void cycle_start(const plugin_runtime_args_t&) override {}
  void cycle_end(const plugin_runtime_args_t&) override {}
  DiagHub* hub() override { return hub_.get(); }
  std::unique_ptr<TraceSource> trace_source() override { return raw_->trace_source(); }
  std::shared_ptr<SimFrameInjector> frame_injector() override { return raw_->frame_injector(); }

 private:
  RawRuntime* raw_;
  std::unique_ptr<DiagHub> hub_;
};

}  // namespace

std::unique_ptr<NetworkRuntime> make_plain_runtime(RawRuntime* raw, const char* version) {
  return std::unique_ptr<NetworkRuntime>(new PlainRuntime(raw, version));
}

void log_plain_loaded(const ConfigSet& set, const Config& cfg) {
  ScopedLogPrefix prefix(cfg.log_prefix.empty() ? "" : cfg.log_prefix + ": ");
  if (cfg.adapter.simulate)
    log_info("loaded %s: plain CAN network, SIMULATED (%s), %zu received and %zu sent raw message%s",
             set.path.c_str(), cfg.adapter.simulation_forced ? "forced by the runtime" : "adapter.simulate",
             cfg.raw.rx.size(), cfg.raw.tx.size(), plural(cfg.raw.tx.size()));
  else
    log_info("loaded %s: plain CAN network on %s adapter %s, %u bit/s%s, %zu received and %zu sent raw message%s",
             set.path.c_str(), cfg.adapter.type.c_str(), cfg.adapter.interface.c_str(), cfg.adapter.bitrate,
             cfg.adapter.listen_only ? ", listen-only" : "", cfg.raw.rx.size(), cfg.raw.tx.size(),
             plural(cfg.raw.tx.size()));
}

}  // namespace canworks_raw
