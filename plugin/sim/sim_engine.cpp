#include "sim_engine.h"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <sstream>
#include <sys/stat.h>

#include "cJSON.h"
#include "sim_drive.h"
#include "sim_expr.h"
#include "sim_od.h"
#include "sim_source.h"

namespace canopen_sim {

namespace {

using Clock = std::chrono::steady_clock;

double seconds(Clock::duration d) { return std::chrono::duration<double>(d).count(); }

std::string fmt_value(const Value& v) {
  if (v.is_string) return "\"" + v.str + "\"";
  char b[32];
  std::snprintf(b, sizeof b, "%.10g", v.num);
  return b;
}

cJSON* json_value(const Value& v) { return v.is_string ? cJSON_CreateString(v.str.c_str()) : cJSON_CreateNumber(v.num); }

std::string answer(const std::string& id, cJSON* result, const std::string& error) {
  cJSON* o = cJSON_CreateObject();
  if (!id.empty()) {
    cJSON* idv = cJSON_Parse(id.c_str());
    cJSON_AddItemToObject(o, "id", idv ? idv : cJSON_CreateNull());
  }
  cJSON_AddBoolToObject(o, "ok", error.empty());
  if (error.empty()) {
    cJSON_AddItemToObject(o, "result", result ? result : cJSON_CreateObject());
  } else {
    if (result) cJSON_Delete(result);
    cJSON_AddStringToObject(o, "error", error.c_str());
  }
  char* p = cJSON_PrintUnformatted(o);
  std::string s = p;
  cJSON_free(p);
  cJSON_Delete(o);
  return s;
}

std::string nmt_name(uint8_t st) {
  switch (st) {
    case 0: return "bootup";
    case 4: return "stopped";
    case 5: return "operational";
    case 127: return "preop";
    default: return "unknown";
  }
}

std::string nmt_log_name(uint8_t st) {
  switch (st) {
    case 0: return "BOOT-UP";
    case 4: return "STOPPED";
    case 5: return "OPERATIONAL";
    case 127: return "PRE-OPERATIONAL";
    default: return "state " + std::to_string(st);
  }
}

uint64_t file_hash(const std::string& path) {
  std::ifstream in(path, std::ios::binary);
  uint64_t h = 1469598103934665603ull;
  char c;
  while (in.get(c)) {
    h ^= static_cast<unsigned char>(c);
    h *= 1099511628211ull;
  }
  return h;
}

std::string basename_of(const std::string& p) {
  size_t s = p.rfind('/');
  return s == std::string::npos ? p : p.substr(s + 1);
}

std::string to_hex(const std::vector<uint8_t>& v) {
  std::string s;
  char b[3];
  for (uint8_t x : v) {
    std::snprintf(b, sizeof b, "%02x", x);
    s += b;
  }
  return s;
}

bool from_hex(const std::string& s, std::vector<uint8_t>& out) {
  if (s.size() % 2) return false;
  out.clear();
  for (size_t i = 0; i < s.size(); i += 2) {
    char b[3] = {s[i], s[i + 1], 0};
    char* e = nullptr;
    long v = std::strtol(b, &e, 16);
    if (*e) return false;
    out.push_back(static_cast<uint8_t>(v));
  }
  return true;
}

}  // namespace

struct Simulator::SourceSlot {
  Dev* dev = nullptr;
  ObjKey key;
  std::unique_ptr<Source> src;
  bool from_file = false;
  bool is_default = false;
  Clock::time_point started;
  Clock::time_point next_due;
  Clock::time_point last;
  bool reported = false;
};

struct Simulator::Dev {
  int index = 0;
  DeviceSpec spec;
  std::string label;
  unsigned tick_ms = kDefaultTickMs;
  std::string store_key;
  std::shared_ptr<StoredState> store;

  std::unique_ptr<lely::io::TimerBase> timer;
  std::unique_ptr<lely::io::CanChannelBase> chan;
  std::unique_ptr<SimDevice> dev;
  bool powered = false;
  bool conflict = false;
  bool cycle_pending = false;
  Clock::time_point power_on_due;
  Clock::time_point power_on_at;
  Clock::time_point next_tick, last_tick;
  uint8_t last_nmt = 0xFF;

  std::set<ObjKey> objects;
  uint16_t profile = 0;
  std::map<uint8_t, uint32_t> eds_identity;  // 0x1018 as the file has it
  uint32_t eds_device_type = 0;

  std::map<ObjKey, std::unique_ptr<SourceSlot>> sources;
  std::map<ObjKey, std::unique_ptr<SourceSlot>> defaults;
  std::vector<std::pair<ObjKey, ObjKey>> loopback;  // from output, to input
  std::map<ObjKey, Value> overrides;
  struct Hold {
    bool has_ref = false;
    Value ref;
  };
  std::map<ObjKey, Hold> sets;

  bool has_drive = false;
  DriveSettings drive_settings;
  std::unique_ptr<DriveIoImpl> drive_io;
  std::unique_ptr<DriveModel> drive;
  std::set<ObjKey> drive_outputs;
  DriveInputs inputs;

  // Fault settings; they last across power cycles until cleared.
  std::vector<SdoRule> rules;
  std::set<unsigned> stopped_tpdos;
  bool heartbeat_stopped = false;
  unsigned sdo_delay_ms = 0;
  bool sdo_delay_all = true;
  ObjKey sdo_delay_obj;
  bool refuse_op = false;
  std::map<uint8_t, uint32_t> fault_identity;
  bool has_fault_device_type = false;
  uint32_t fault_device_type = 0;
  bool emcy_periodic = false;
  Fault emcy;
  Clock::time_point emcy_next;
  // Active faults for status: key -> fault JSON.
  std::map<std::string, std::string> active;
};

class Simulator::DriveIoImpl : public DriveIo {
 public:
  DriveIoImpl(Simulator& s, Dev& d) : s_(s), d_(d) {}
  bool has(uint16_t index, uint8_t subindex) const override {
    return d_.objects.count(ObjKey{index, subindex}) > 0;
  }
  double read(uint16_t index, uint8_t subindex) const override {
    return d_.dev ? od_number(d_.dev->od(), index, subindex) : 0;
  }
  void write(uint16_t index, uint8_t subindex, double value) override {
    s_.Write(d_, ObjKey{index, subindex}, Value::number(value), 1);
  }
  void emcy(uint16_t code, uint8_t error_register) override {
    if (!d_.dev) return;
    uint8_t msef[5] = {};
    d_.dev->SendEmcy(code, error_register, msef);
  }
  void emcy_reset() override {
    if (d_.dev) d_.dev->ClearEmcy();
  }

 private:
  Simulator& s_;
  Dev& d_;
};

class Simulator::Resolver : public ExprResolver {
 public:
  Resolver(const Simulator& s, int self) : s_(s), self_(self) {}
  int self() const override { return self_; }
  int device(const std::string& name) const override {
    for (const auto& d : s_.devs_) {
      if (d->spec.node && std::to_string(d->spec.node) == name) return d->index;
      if (!d->spec.name.empty() && d->spec.extra && d->spec.name == name) return d->index;
    }
    return -1;
  }
  bool has_object(int device, uint16_t index, uint8_t subindex) const override {
    if (device < 0 || device >= static_cast<int>(s_.devs_.size())) return false;
    const Dev& d = *s_.devs_[device];
    if (d.objects.empty()) return true;  // never started (taken node ID): reads give 0
    return d.objects.count(ObjKey{index, subindex}) > 0;
  }

 private:
  const Simulator& s_;
  int self_;
};

class Simulator::Ctx : public ExprContext {
 public:
  explicit Ctx(Simulator& s) : s_(s) { rng = &s.rng_; }
  double value(const ObjectRef& ref) override {
    if (ref.device < 0 || ref.device >= static_cast<int>(s_.devs_.size())) return 0;
    Dev& d = *s_.devs_[ref.device];
    return d.dev ? od_number(d.dev->od(), ref.index, ref.subindex) : 0;
  }

 private:
  Simulator& s_;
};

struct Simulator::Run {
  Scenario sc;
  struct Frame {
    const std::vector<Step>* steps = nullptr;
    size_t i = 0;
    unsigned remaining = 0;  // repeat frames: runs left after this one
    bool forever = false;
    std::string prefix;
  };
  std::vector<Frame> stack;
  Clock::time_point start, prev_end, step_begin;
  bool active = false;  // the current step's action has begun
  std::string state = "running";
  std::string message;
  std::string step_label;
  std::map<const Step*, std::unique_ptr<Expr>> exprs;
  bool done = false;
};

Simulator::Simulator(Host& host, std::vector<DeviceSpec> devices, SimFile file, SimOptions options)
    : host_(host), file_(std::move(file)), opt_(std::move(options)), rng_(std::random_device{}()) {
  if (!opt_.store) opt_.store = std::make_shared<StoreMap>();
  for (auto& spec : devices) {
    std::unique_ptr<Dev> d(new Dev);
    d->spec = std::move(spec);
    devs_.push_back(std::move(d));
  }
}

Simulator::~Simulator() { Stop(); }

bool Simulator::ReadOnlyOp(const std::string& op) {
  return op == "sim_status" || op == "sim_get" || op == "sim_scenario_list" || op == "sim_check_expr";
}

void Simulator::Log(Host::Level l, const std::string& m) { host_.log(l, m); }

std::vector<unsigned> Simulator::NodeIds() const {
  std::vector<unsigned> v;
  for (const auto& d : devs_)
    if (d->spec.node) v.push_back(d->spec.node);
  return v;
}

bool Simulator::Simulates(unsigned node) const {
  for (const auto& d : devs_)
    if (d->spec.node == node) return true;
  return false;
}

std::string Simulator::StoreKey(const Dev& d) const {
  std::string k = d.spec.extra && !d.spec.name.empty() ? "name-" + d.spec.name : "node-" + std::to_string(d.spec.node);
  char h[24];
  std::snprintf(h, sizeof h, "-%016llx", static_cast<unsigned long long>(file_hash(d.spec.eds_path)));
  return k + h;
}

void Simulator::Persist(Dev& d) {
  if (opt_.state_dir.empty()) return;
  std::string path = opt_.state_dir + "/" + d.store_key + ".state";
  std::ofstream out(path + ".tmp");
  out << "lss_id " << unsigned(d.store->lss_id) << "\n";
  for (const auto& kv : d.store->saved) out << "saved " << kv.first << " " << to_hex(kv.second) << "\n";
  out.close();
  if (!out || std::rename((path + ".tmp").c_str(), path.c_str()) != 0)
    Log(Host::Level::Warn, d.label + ": cannot write the stored state to " + path);
}

void Simulator::LoadPersisted(Dev& d) {
  if (opt_.state_dir.empty()) return;
  std::ifstream in(opt_.state_dir + "/" + d.store_key + ".state");
  std::string word;
  while (in >> word) {
    if (word == "lss_id") {
      unsigned id = 0;
      in >> id;
      d.store->lss_id = static_cast<uint8_t>(id);
    } else if (word == "saved") {
      std::string k, h;
      in >> k >> h;
      std::vector<uint8_t> bytes;
      if (k.size() == 1 && from_hex(h, bytes)) d.store->saved[k[0]] = bytes;
    }
  }
}

bool Simulator::Start(std::vector<std::string>& errors) {
  if (started_) return true;
  start_ = last_tick_ = Clock::now();
  tick_ms_ = file_.tick_ms ? file_.tick_ms : kDefaultTickMs;

  // Extra devices of the simulation file.
  for (const auto& x : file_.extra) {
    bool clash = false;
    for (const auto& d : devs_) {
      if (x.node && d->spec.node == x.node) {
        errors.push_back(file_.path + ": extra device " + (x.name.empty() ? "" : x.name + " ") + "has node ID " +
                         std::to_string(x.node) + ", which a simulated node of the config has");
        clash = true;
      }
    }
    if (clash) continue;
    std::unique_ptr<Dev> d(new Dev);
    d->spec.node = x.node;
    d->spec.name = x.name;
    d->spec.extra = true;
    d->spec.eds_path = x.eds_path;
    d->spec.has_behaviour = true;
    d->spec.behaviour = x.behaviour;
    devs_.push_back(std::move(d));
  }
  for (size_t i = 0; i < devs_.size(); ++i) {
    Dev& d = *devs_[i];
    d.index = static_cast<int>(i);
    if (!d.spec.has_behaviour) {
      auto it = file_.nodes.find(d.spec.node);
      if (d.spec.node && it != file_.nodes.end()) {
        d.spec.has_behaviour = true;
        d.spec.behaviour = it->second;
      }
    }
    if (d.spec.extra)
      d.label = d.spec.node ? d.spec.name.empty() ? "node " + std::to_string(d.spec.node)
                                                   : d.spec.name + " (node " + std::to_string(d.spec.node) + ")"
                            : d.spec.name;
    else
      d.label = "node " + std::to_string(d.spec.node);
    d.tick_ms = d.spec.behaviour.tick_ms ? d.spec.behaviour.tick_ms : tick_ms_;
    tick_ms_ = std::min(tick_ms_, d.tick_ms);
    d.store_key = StoreKey(d);
    auto& slot = (*opt_.store)[d.store_key];
    if (!slot) slot = std::make_shared<StoredState>();
    d.store = slot;
    LoadPersisted(d);
    if (d.spec.behaviour.has_drive) {
      cJSON* j = cJSON_Parse(d.spec.behaviour.drive_json.c_str());
      std::string err;
      if (!parse_drive_settings(j, d.drive_settings, err)) errors.push_back(d.label + ": drive: " + err);
      cJSON_Delete(j);
    }
    d.inputs = DriveInputs();
    d.conflict = d.spec.conflict;
  }
  if (!errors.empty()) return false;

  for (auto& dp : devs_) {
    Dev& d = *dp;
    if (d.conflict) {
      Log(Host::Level::Error, d.label + ": node ID " + std::to_string(d.spec.node) +
                                  " is taken by a device on " + host_.interface_name() + "; not simulated");
      continue;
    }
    PowerOn(d);
    if (!d.powered) errors.push_back(d.label + ": cannot start the device from " + d.spec.eds_path);
  }
  if (!errors.empty()) {
    Stop();
    return false;
  }
  // Sources and faults from the file.
  for (auto& dp : devs_) {
    Dev& d = *dp;
    for (const auto& s : d.spec.behaviour.sources) {
      std::string err;
      if (!SetSource(d, s.first, s.second, true, err)) errors.push_back(d.label + ": source of " + s.first.str() + ": " + err);
    }
  }
  std::string cyc;
  if (errors.empty() && !CheckCycles(cyc)) errors.push_back(cyc);
  if (!errors.empty()) {
    Stop();
    return false;
  }
  for (auto& dp : devs_) {
    Dev& d = *dp;
    if (!d.powered) continue;
    for (const auto& f : d.spec.behaviour.faults) {
      std::string err;
      if (!ApplyFault(d, f, err)) errors.push_back(d.label + ": fault " + f.json + ": " + err);
    }
  }
  if (!errors.empty()) {
    Stop();
    return false;
  }

  timer_ = host_.make_timer();
  wait_.reset(new lely::io::TimerWait(host_.exec(), [this](int, std::error_code ec) {
    if (ec || stopped_) return;
    Tick();
    if (!stopped_) timer_->submit_wait(*wait_);
  }));
  timer_->settime(std::chrono::milliseconds(tick_ms_), std::chrono::milliseconds(tick_ms_));
  timer_->submit_wait(*wait_);
  started_ = true;

  for (const auto& sc : file_.scenarios) {
    if (!sc.autostart) continue;
    std::string err;
    if (!StartScenario(sc, err)) Log(Host::Level::Error, "scenario " + sc.name + ": " + err);
  }
  return true;
}

void Simulator::Stop() {
  if (stopped_) return;
  stopped_ = true;
  if (timer_) {
    // Abort, not cancel: a canceled wait would still run after the engine is gone.
    timer_->abort_wait(*wait_);
    timer_->settime(std::chrono::milliseconds(0), std::chrono::milliseconds(0));
  }
  for (auto& d : devs_) {
    if (d->dev) d->dev->powered = false;
    d->drive.reset();
    d->dev.reset();
    d->chan.reset();
    d->timer.reset();
    d->powered = false;
  }
}

void Simulator::PowerOn(Dev& d) {
  if (d.powered || d.conflict) return;
  d.cycle_pending = false;
  uint8_t id = static_cast<uint8_t>(d.spec.node ? d.spec.node : 0xFF);
  if (d.spec.lss || !d.spec.node) id = 0xFF;
  if (d.store->lss_id) id = d.store->lss_id;
  try {
    d.timer = host_.make_timer();
    d.chan = host_.make_channel();
    d.dev.reset(new SimDevice(host_.exec(), *d.timer, *d.chan, d.spec.eds_path, id, d.store));
  } catch (const std::exception& e) {
    Log(Host::Level::Error, d.label + ": " + d.spec.eds_path + ": " + e.what());
    d.dev.reset();
    d.chan.reset();
    d.timer.reset();
    return;
  }
  SimDevice& dev = *d.dev;
  if (d.objects.empty()) {
    for (const auto& o : od_objects(dev.od())) d.objects.insert(ObjKey{o.first, o.second});
    for (uint8_t s = 1; s <= 4; ++s)
      if (od_has(dev.od(), 0x1018, s)) d.eds_identity[s] = static_cast<uint32_t>(od_number(dev.od(), 0x1018, s));
    d.eds_device_type = static_cast<uint32_t>(od_number(dev.od(), 0x1000, 0));
  }
  dev.on_log = [this, &d](const std::string& m) { Log(Host::Level::Info, d.label + ": " + m); };
  dev.on_stored = [this, &d]() { Persist(d); };
  // Sources that read what the master just wrote run at once, so a device
  // answers in the same SYNC cycle as firmware would.
  dev.on_rpdo = [this]() {
    if (rpdo_posted_) return;
    rpdo_posted_ = true;
    std::weak_ptr<bool> alive = alive_;
    lely::ev::Executor(host_.exec()).post([this, alive]() {
      if (alive.expired() || stopped_) return;
      rpdo_posted_ = false;
      RunSources(Clock::now(), true);
    });
  };
  ApplyFaultSettings(d);
  uint32_t device_type = d.has_fault_device_type ? d.fault_device_type
                         : d.spec.behaviour.has_device_type ? d.spec.behaviour.device_type
                                                            : d.eds_device_type;
  d.profile = static_cast<uint16_t>(device_type & 0xFFFF);
  bool defaults = opt_.defaults && d.spec.behaviour.default_behaviour;

  // Default behaviour by profile.
  d.loopback.clear();
  d.defaults.clear();
  if (defaults && d.profile == 401) {
    const std::pair<uint16_t, uint16_t> pairs[] = {{0x6200, 0x6000}, {0x6220, 0x6020}, {0x6250, 0x6050}, {0x6411, 0x6401}};
    for (const auto& p : pairs)
      for (unsigned s = 1; s <= 0xFE; ++s)
        if (d.objects.count(ObjKey{p.first, static_cast<uint8_t>(s)}) &&
            d.objects.count(ObjKey{p.second, static_cast<uint8_t>(s)}))
          d.loopback.emplace_back(ObjKey{p.first, static_cast<uint8_t>(s)}, ObjKey{p.second, static_cast<uint8_t>(s)});
  }
  if (defaults && d.profile == 404) {
    for (const auto& o : dev.PdoObjects()) {
      ObjKey k{o.first, o.second};
      if (dev.InRpdo(o.first, o.second) || od_kind(dev.od(), k.index, k.subindex) != OdKind::Number) continue;
      double lo = 0, hi = 0;
      if (!od_limits(dev.od(), k.index, k.subindex, lo, hi)) continue;
      double span = hi - lo;
      char js[160];
      std::snprintf(js, sizeof js, "{\"sine\":{\"min\":%.17g,\"max\":%.17g,\"period_s\":60}}", lo + span * 0.25,
                    lo + span * 0.75);
      cJSON* j = cJSON_Parse(js);
      std::string err;
      std::unique_ptr<Source> src = Source::parse(j, "", err);
      cJSON_Delete(j);
      if (!src) continue;
      std::unique_ptr<SourceSlot> slot(new SourceSlot);
      slot->dev = &d;
      slot->key = k;
      slot->src = std::move(src);
      slot->is_default = true;
      d.defaults[k] = std::move(slot);
    }
  }
  d.drive.reset();
  d.drive_outputs.clear();
  d.has_drive = (defaults && d.profile == 402) || d.spec.behaviour.has_drive;
  if (d.has_drive) {
    d.drive_io.reset(new DriveIoImpl(*this, d));
    d.drive.reset(new DriveModel(*d.drive_io, d.drive_settings));
    d.drive->inputs = d.inputs;
    for (const auto& o : d.drive->outputs()) d.drive_outputs.insert(ObjKey{o.first, o.second});
    DriveModel* dm = d.drive.get();
    dev.on_sync = [dm]() { dm->sync(); };
  }

  Clock::time_point now = Clock::now();
  d.power_on_at = now;
  d.last_tick = now;
  d.next_tick = now + std::chrono::milliseconds(d.tick_ms);
  d.last_nmt = 0xFF;
  d.powered = true;
  for (auto& kv : d.sources) {
    if (!kv.second->from_file) continue;
    kv.second->src->restart();
    kv.second->started = kv.second->last = kv.second->next_due = now;
  }
  for (auto& kv : d.defaults) kv.second->started = kv.second->last = kv.second->next_due = now;
  if (host_.real_network()) {
    dev.GuardNodeId([this, &d]() {
      if (!d.powered) return;
      Log(Host::Level::Error, d.label + ": another device sends with node ID " + std::to_string(d.dev->node_id()) +
                                  " on " + host_.interface_name() + "; the simulated device powers off");
      d.conflict = true;
      PowerOff(d, "");
    });
  }
  dev.Reset();
  if (d.drive) d.drive->power_on();
  Log(Host::Level::Info, d.label + ": powered on (" + basename_of(d.spec.eds_path) +
                             (id == 0xFF ? ", no node ID, waiting for LSS" : "") + ")");
}

void Simulator::PowerOff(Dev& d, const std::string& why) {
  if (!d.powered) return;
  d.powered = false;
  if (d.dev) d.dev->powered = false;
  d.drive.reset();
  d.dev.reset();
  d.chan.reset();
  d.timer.reset();
  d.emcy_periodic = false;
  d.active.erase("emcy");
  if (!why.empty()) Log(Host::Level::Info, d.label + ": powered off" + (why == "fault" ? "" : " (" + why + ")"));
}

void Simulator::ApplyFaultSettings(Dev& d) {
  SimDevice& dev = *d.dev;
  dev.sdo_rules = d.rules;
  dev.stopped_tpdos = d.stopped_tpdos;
  dev.heartbeat_stopped = d.heartbeat_stopped;
  dev.sdo_delay_ms = d.sdo_delay_ms;
  dev.sdo_delay_all = d.sdo_delay_all;
  dev.sdo_delay_index = d.sdo_delay_obj.index;
  dev.sdo_delay_subindex = d.sdo_delay_obj.subindex;
  dev.refuse_write_operational = d.refuse_op;
  dev.identity = d.spec.identity;
  for (const auto& kv : d.spec.behaviour.identity) dev.identity[kv.first] = kv.second;
  for (const auto& kv : d.fault_identity) dev.identity[kv.first] = kv.second;
  dev.has_device_type = d.has_fault_device_type || d.spec.behaviour.has_device_type;
  dev.device_type = d.has_fault_device_type ? d.fault_device_type : d.spec.behaviour.device_type;
  dev.ApplyOverrides();
}

int Simulator::Owner(const Dev& d, const ObjKey& k) const {
  if (d.overrides.count(k)) return 4;
  if (d.sources.count(k)) return 2;
  if (d.drive && d.drive_outputs.count(k)) return 1;
  return 0;
}

void Simulator::Write(Dev& d, const ObjKey& k, const Value& v, int level) {
  if (!d.dev) return;
  if (level < 3) {
    if (level < Owner(d, k)) return;
    auto h = d.sets.find(k);
    if (h != d.sets.end()) {
      // A value set once holds until its writer's value changes.
      if (!h->second.has_ref) {
        h->second.has_ref = true;
        h->second.ref = v;
        return;
      }
      if (h->second.ref == v) return;
      d.sets.erase(h);
    }
  }
  bool changed = false;
  if (od_write(d.dev->od(), k.index, k.subindex, v, &changed) && changed) d.dev->Changed(k.index, k.subindex);
}

bool Simulator::SetSource(Dev& d, const ObjKey& k, const std::string& json, bool from_file, std::string& err) {
  if (json.empty()) {
    d.sources.erase(k);
    order_dirty_ = true;
    return true;
  }
  if (!d.objects.empty() && !d.objects.count(k)) {
    err = "the device has no object " + k.str();
    return false;
  }
  auto mw = d.spec.master_written.find(k);
  if (mw != d.spec.master_written.end()) {
    err = "the master writes " + k.str() + " (" + mw->second + "); use an override to make the device ignore it";
    return false;
  }
  if (d.dev && d.dev->InRpdo(k.index, k.subindex)) {
    err = "the master writes " + k.str() + " (an RPDO maps it); use an override to make the device ignore it";
    return false;
  }
  cJSON* j = cJSON_Parse(json.c_str());
  std::unique_ptr<Source> src = Source::parse(j, file_.dir, err);
  cJSON_Delete(j);
  if (!src) return false;
  if (d.dev && src->type() == Source::Type::Constant) {
    // A string constant only fits a VISIBLE_STRING object, a number only a number.
  }
  Resolver res(*this, d.index);
  ExprError ee;
  if (!src->bind(res, ee)) {
    err = "expression error at " + std::to_string(ee.position) + ": " + ee.message;
    return false;
  }
  std::unique_ptr<SourceSlot> slot(new SourceSlot);
  slot->dev = &d;
  slot->key = k;
  slot->src = std::move(src);
  slot->from_file = from_file;
  Clock::time_point now = Clock::now();
  slot->started = slot->last = slot->next_due = now;
  if (slot->src->tick_ms() && slot->src->tick_ms() < tick_ms_ && timer_) {
    tick_ms_ = slot->src->tick_ms();
    timer_->settime(std::chrono::milliseconds(tick_ms_), std::chrono::milliseconds(tick_ms_));
  } else if (slot->src->tick_ms() && slot->src->tick_ms() < tick_ms_) {
    tick_ms_ = slot->src->tick_ms();
  }
  auto old = std::move(d.sources[k]);
  d.sources[k] = std::move(slot);
  d.sets.erase(k);
  order_dirty_ = true;
  if (started_) {
    std::string cyc;
    if (!CheckCycles(cyc)) {
      if (old)
        d.sources[k] = std::move(old);
      else
        d.sources.erase(k);
      order_dirty_ = true;
      CheckCycles(cyc);
      err = cyc;
      return false;
    }
  }
  return true;
}

bool Simulator::CheckCycles(std::string& err) {
  // Depth-first search over expression sources; an edge is a read that does
  // not go through lag, delay or integrate. Also produces the evaluation
  // order: a source after the sources it reads.
  std::vector<SourceSlot*> all;
  for (auto& d : devs_)
    for (auto& kv : d->sources) all.push_back(kv.second.get());
  auto find = [&](const ObjectRef& r) -> SourceSlot* {
    if (r.device < 0 || r.device >= static_cast<int>(devs_.size())) return nullptr;
    auto& m = devs_[r.device]->sources;
    auto it = m.find(ObjKey{r.index, r.subindex});
    return it == m.end() ? nullptr : it->second.get();
  };
  std::map<SourceSlot*, int> mark;  // 1 on the stack, 2 done
  std::vector<SourceSlot*> order, path;
  std::function<bool(SourceSlot*)> visit = [&](SourceSlot* s) -> bool {
    int m = mark[s];
    if (m == 2) return true;
    if (m == 1) {
      std::string chain;
      bool on = false;
      for (SourceSlot* p : path) {
        on = on || p == s;
        if (on) chain += p->dev->label + " " + p->key.str() + " -> ";
      }
      err = "reference cycle without lag, delay or integrate: " + chain + s->dev->label + " " + s->key.str();
      return false;
    }
    mark[s] = 1;
    path.push_back(s);
    if (const Expr* e = s->src->expr()) {
      for (const auto& r : e->reads()) {
        if (r.delayed) continue;
        SourceSlot* t = find(r.ref);
        if (t && !visit(t)) return false;
      }
    }
    path.pop_back();
    mark[s] = 2;
    order.push_back(s);
    return true;
  };
  for (SourceSlot* s : all)
    if (!visit(s)) return false;
  order_ = order;
  order_dirty_ = false;
  return true;
}

Simulator::Dev* Simulator::Find(const std::string& ref) {
  for (auto& d : devs_) {
    if (d->spec.node && std::to_string(d->spec.node) == ref) return d.get();
    if (d->spec.extra && !d->spec.name.empty() && d->spec.name == ref) return d.get();
  }
  return nullptr;
}

Simulator::Dev* Simulator::FindJson(const cJSON* node, std::string& err) {
  std::string ref;
  if (!node || !parse_device_ref(node, ref)) {
    err = "\"node\" must be a node ID 1-127 or a device name";
    return nullptr;
  }
  Dev* d = Find(ref);
  if (!d) {
    bool num = std::isdigit(static_cast<unsigned char>(ref[0]));
    err = num ? "node " + ref + " is not simulated" : "device " + ref + " is not simulated";
  }
  return d;
}

bool Simulator::AllOperational() const {
  for (const auto& d : devs_) {
    if (d->conflict || !d->powered) continue;
    if (!d->dev || d->dev->nmt_state() != 5) return false;
  }
  return true;
}

void Simulator::Tick() {
  Clock::time_point now = Clock::now();
  last_tick_ = now;
  for (auto& dp : devs_) {
    Dev& d = *dp;
    if (!d.powered && d.cycle_pending && now >= d.power_on_due) PowerOn(d);
    if (!d.powered) continue;
    d.dev->FlushDelayed(now);
    if (d.emcy_periodic && now >= d.emcy_next) {
      d.dev->SendEmcy(d.emcy.code, d.emcy.error_register, d.emcy.msef);
      d.emcy_next += std::chrono::milliseconds(d.emcy.period_ms);
      if (d.emcy_next < now) d.emcy_next = now + std::chrono::milliseconds(d.emcy.period_ms);
    }
    uint8_t st = d.dev->nmt_state();
    if (st != d.last_nmt) {
      if (d.last_nmt != 0xFF || st != 0) Log(Host::Level::Info, d.label + ": " + nmt_log_name(st));
      d.last_nmt = st;
    }
    if (now >= d.next_tick) {
      double dt = seconds(now - d.last_tick);
      d.last_tick = now;
      d.next_tick += std::chrono::milliseconds(d.tick_ms);
      if (d.next_tick < now) d.next_tick = now + std::chrono::milliseconds(d.tick_ms);
      TickDevice(d, now, dt);
    }
  }
  RunSources(now);
  for (auto& dp : devs_) {
    Dev& d = *dp;
    if (!d.powered) continue;
    for (const auto& kv : d.overrides) Write(d, kv.first, kv.second, 4);
  }
  RunScenarios(now);
}

void Simulator::TickDevice(Dev& d, Clock::time_point now, double dt) {
  for (const auto& p : d.loopback) {
    Value v;
    if (od_read(d.dev->od(), p.first.index, p.first.subindex, v)) Write(d, p.second, v, 0);
  }
  Ctx ctx(*this);
  for (auto& kv : d.defaults) {
    SourceSlot& s = *kv.second;
    ctx.t = seconds(now - d.power_on_at);
    ctx.dt = dt;
    ctx.prev = od_number(d.dev->od(), s.key.index, s.key.subindex);
    Value v = s.src->eval(seconds(now - s.started), ctx);
    if (!v.is_string && !std::isfinite(v.num)) continue;
    Write(d, s.key, v, 0);
  }
  if (d.drive) d.drive->step(dt);
}

void Simulator::RunSources(Clock::time_point now, bool rpdo) {
  if (order_dirty_) {
    std::string err;
    if (!CheckCycles(err)) Log(Host::Level::Error, err);
  }
  Ctx ctx(*this);
  for (SourceSlot* s : order_) {
    Dev& d = *s->dev;
    if (!d.powered) continue;
    unsigned tick = s->src->tick_ms() ? s->src->tick_ms() : d.tick_ms;
    if (rpdo) {
      // Only plain expressions: stateful functions keep their tick.
      if (s->src->type() != Source::Type::Expr || !s->src->expr()->stateless()) continue;
    } else {
      if (now < s->next_due) continue;
      s->next_due += std::chrono::milliseconds(tick);
      if (s->next_due < now) s->next_due = now + std::chrono::milliseconds(tick);
    }
    ctx.t = seconds(now - d.power_on_at);
    ctx.dt = seconds(now - s->last);
    s->last = now;
    Value cur;
    od_read(d.dev->od(), s->key.index, s->key.subindex, cur);
    ctx.prev = cur.is_string ? 0 : cur.num;
    Value v = s->src->eval(seconds(now - s->started), ctx);
    if (!v.is_string && !std::isfinite(v.num)) {
      if (!s->reported) {
        s->reported = true;
        Log(Host::Level::Warn, d.label + ": the source of " + s->key.str() +
                                   " gave no finite number (division by zero?); the object keeps its value");
      }
      continue;
    }
    Write(d, s->key, v, 2);
  }
}

// ---- faults ----

bool Simulator::ApplyFault(Dev& d, const Fault& f, std::string& err) {
  const std::string& k = f.kind;
  if (k == "power") {
    if (f.mode == "on") {
      d.conflict = false;
      d.active.erase("power");
      PowerOn(d);
      return true;
    }
    PowerOff(d, "fault");
    d.active["power"] = f.json;
    if (f.mode == "cycle") {
      d.cycle_pending = true;
      d.power_on_due = Clock::now() + std::chrono::milliseconds(f.off_ms);
      d.active.erase("power");
    }
    return true;
  }
  if ((k == "sdo_abort" || k == "sdo_delay") && f.has_object && !d.objects.empty() && !d.objects.count(f.object)) {
    err = d.label + " has no object " + f.object.str();
    return false;
  }
  // Settings that last across power cycles.
  if (k == "heartbeat") {
    d.heartbeat_stopped = true;
  } else if (k == "sdo_abort") {
    SdoRule r;
    r.index = f.object.index;
    r.subindex = f.object.subindex;
    r.on_read = f.on_read;
    r.on_write = f.on_write;
    r.code = f.abort_code;
    r.count = f.count;
    d.rules.push_back(r);
    d.active["sdo_abort " + f.object.str()] = f.json;
  } else if (k == "sdo_delay") {
    d.sdo_delay_ms = f.ms;
    d.sdo_delay_all = !f.has_object;
    d.sdo_delay_obj = f.object;
  } else if (k == "refuse_write_operational") {
    d.refuse_op = true;
  } else if (k == "tpdo_stop") {
    d.stopped_tpdos.insert(f.tpdo);
    d.active["tpdo_stop " + std::to_string(f.tpdo)] = f.json;
  } else if (k == "identity") {
    for (const auto& kv : f.identity) d.fault_identity[kv.first] = kv.second;
  } else if (k == "device_type") {
    d.has_fault_device_type = true;
    d.fault_device_type = f.value;
  } else if (k == "drive_input") {
    for (const auto& kv : f.inputs) {
      if (kv.first == "blocked") d.inputs.blocked = kv.second;
      if (kv.first == "positive_limit") d.inputs.positive_limit = kv.second;
      if (kv.first == "negative_limit") d.inputs.negative_limit = kv.second;
      if (kv.first == "home_switch") d.inputs.home_switch = kv.second;
    }
    if (d.drive) d.drive->inputs = d.inputs;
  }
  bool setting = k == "heartbeat" || k == "sdo_abort" || k == "sdo_delay" || k == "refuse_write_operational" ||
                 k == "tpdo_stop" || k == "identity" || k == "device_type" || k == "drive_input";
  if (setting) {
    if (k != "sdo_abort" && k != "tpdo_stop") d.active[k] = f.json;
    if (d.dev) ApplyFaultSettings(d);
    Log(Host::Level::Info, d.label + ": fault " + f.json);
    return true;
  }
  // Actions on a running device.
  if (!d.powered || !d.dev) {
    err = d.label + " is powered off";
    return false;
  }
  SimDevice& dev = *d.dev;
  if (k == "emcy") {
    dev.SendEmcy(f.code, f.error_register, f.msef);
    if (f.period_ms) {
      d.emcy_periodic = true;
      d.emcy = f;
      d.emcy_next = Clock::now() + std::chrono::milliseconds(f.period_ms);
    }
    d.active["emcy"] = f.json;
  } else if (k == "reset") {
    dev.SelfCommand(f.mode == "node" ? 0x81 : 0x82);
  } else if (k == "nmt_state") {
    dev.SelfCommand(f.mode == "stopped" ? 0x02 : f.mode == "preop" ? 0x80 : 0x01);
  } else if (k == "forget_node_id") {
    dev.ForgetNodeId();
  } else {
    err = "unknown fault " + k;
    return false;
  }
  Log(Host::Level::Info, d.label + ": fault " + f.json);
  return true;
}

bool Simulator::ClearFault(Dev& d, const std::string& name, const cJSON* req, std::string& err) {
  const cJSON* obj = req ? cJSON_GetObjectItemCaseSensitive(req, "object") : nullptr;
  const cJSON* tpdo = req ? cJSON_GetObjectItemCaseSensitive(req, "tpdo") : nullptr;
  bool all = name == "all";
  if (!all && !is_clear_name(name)) {
    err = "unknown fault \"" + name + "\"";
    return false;
  }
  if (all || name == "emcy") {
    bool had = d.active.count("emcy") > 0 || d.emcy_periodic;
    d.emcy_periodic = false;
    d.active.erase("emcy");
    if (had && d.dev) d.dev->ClearEmcy();
  }
  if (all || name == "heartbeat") {
    d.heartbeat_stopped = false;
    d.active.erase("heartbeat");
  }
  if (all || name == "sdo_abort") {
    ObjKey k;
    if (!all && obj) {
      if (!cJSON_IsString(obj) || !parse_obj_key(obj->valuestring, k)) {
        err = "\"object\" must be \"0xIIII:S\"";
        return false;
      }
      d.rules.erase(std::remove_if(d.rules.begin(), d.rules.end(),
                                   [&](const SdoRule& r) { return r.index == k.index && r.subindex == k.subindex; }),
                    d.rules.end());
      d.active.erase("sdo_abort " + k.str());
    } else {
      d.rules.clear();
      for (auto it = d.active.begin(); it != d.active.end();)
        it = it->first.compare(0, 10, "sdo_abort ") == 0 ? d.active.erase(it) : std::next(it);
    }
  }
  if (all || name == "sdo_delay") {
    d.sdo_delay_ms = 0;
    d.active.erase("sdo_delay");
  }
  if (all || name == "refuse_write_operational") {
    d.refuse_op = false;
    d.active.erase("refuse_write_operational");
  }
  if (all || name == "tpdo_stop") {
    if (!all && tpdo) {
      if (!cJSON_IsNumber(tpdo)) {
        err = "\"tpdo\" must be a TPDO number";
        return false;
      }
      unsigned n = static_cast<unsigned>(tpdo->valuedouble);
      d.stopped_tpdos.erase(n);
      d.active.erase("tpdo_stop " + std::to_string(n));
    } else {
      d.stopped_tpdos.clear();
      for (auto it = d.active.begin(); it != d.active.end();)
        it = it->first.compare(0, 10, "tpdo_stop ") == 0 ? d.active.erase(it) : std::next(it);
    }
  }
  bool restore_identity = false;
  if (all || name == "identity") {
    restore_identity = !d.fault_identity.empty();
    d.fault_identity.clear();
    d.active.erase("identity");
  }
  bool restore_type = false;
  if (all || name == "device_type") {
    restore_type = d.has_fault_device_type;
    d.has_fault_device_type = false;
    d.active.erase("device_type");
  }
  if (all || name == "drive_input") {
    d.inputs = DriveInputs();
    if (d.drive) d.drive->inputs = d.inputs;
    d.active.erase("drive_input");
  }
  if (d.dev) {
    if (restore_identity)
      for (const auto& kv : d.eds_identity) od_write(d.dev->od(), 0x1018, kv.first, Value::number(kv.second));
    if (restore_type) od_write(d.dev->od(), 0x1000, 0, Value::number(d.eds_device_type));
    ApplyFaultSettings(d);
  }
  if (all || name == "power") {
    d.active.erase("power");
    d.conflict = false;
    if (!d.powered) PowerOn(d);
  }
  Log(Host::Level::Info, d.label + ": cleared " + name);
  return true;
}

// ---- scenarios ----

bool Simulator::StartScenario(const std::string& name, std::string& err) {
  for (const auto& sc : file_.scenarios)
    if (sc.name == name) return StartScenario(sc, err);
  err = "no scenario \"" + name + "\"";
  return false;
}

bool Simulator::StartScenario(const Scenario& sc, std::string& err) {
  for (auto& r : runs_) {
    if (r->sc.name == sc.name && !r->done) {
      err = "scenario " + sc.name + " is already running";
      return false;
    }
  }
  runs_.erase(std::remove_if(runs_.begin(), runs_.end(), [&](const std::unique_ptr<Run>& r) { return r->sc.name == sc.name; }),
              runs_.end());
  std::unique_ptr<Run> r(new Run);
  r->sc = sc;
  r->start = r->prev_end = Clock::now();
  Run::Frame f;
  f.steps = &r->sc.steps;
  r->stack.push_back(f);
  Log(Host::Level::Info, "scenario " + sc.name + ": started");
  runs_.push_back(std::move(r));
  return true;
}

void Simulator::StopScenario(const std::string& name) {
  for (auto& r : runs_) {
    if (r->sc.name == name && !r->done) {
      r->state = "stopped";
      r->done = true;
      r->message = "stopped";
      Log(Host::Level::Info, "scenario " + name + ": stopped");
      if (on_scenario_end) {
        ScenarioResult res;
        res.name = name;
        res.stopped = true;
        res.message = "stopped";
        res.seconds = seconds(Clock::now() - r->start);
        on_scenario_end(res);
      }
    }
  }
}

bool Simulator::ScenarioRunning() const {
  for (const auto& r : runs_)
    if (!r->done) return true;
  return false;
}

void Simulator::EndRun(Run& r, bool passed, const std::string& msg) {
  r.done = true;
  r.state = passed ? "passed" : "failed";
  r.message = msg;
  Log(passed ? Host::Level::Info : Host::Level::Error,
      "scenario " + r.sc.name + ": " + (passed ? "passed" : "FAILED: " + msg));
  if (on_scenario_end) {
    ScenarioResult res;
    res.name = r.sc.name;
    res.passed = passed;
    res.message = msg;
    res.seconds = seconds(Clock::now() - r.start);
    on_scenario_end(res);
  }
}

bool Simulator::EvalCondition(const Condition& c, const std::string& self, bool& holds, std::string& seen,
                              std::string& err) {
  holds = false;
  if (c.is_expr) return false;  // handled by the caller (compiled per step)
  Dev* d = Find(c.node);
  if (!d) {
    err = "node " + c.node + " is not simulated";
    return false;
  }
  (void)self;
  if (!d->dev) {
    seen = "powered off";
    return true;
  }
  Value v;
  if (!od_read(d->dev->od(), c.object.index, c.object.subindex, v)) {
    err = d->label + " has no object " + c.object.str();
    return false;
  }
  if (c.bit >= 0 && !v.is_string) {
    double x = std::floor(std::fabs(v.num));
    v = Value::number(std::fmod(std::floor(x / std::ldexp(1.0, c.bit)), 2.0));
  }
  seen = fmt_value(v);
  if (v.is_string || c.value.is_string) {
    bool eq = v.is_string && c.value.is_string && v.str == c.value.str;
    holds = c.op == "eq" ? eq : c.op == "ne" ? !eq : false;
    return true;
  }
  double a = v.num, b = c.value.num;
  if (c.op == "eq") holds = a == b;
  else if (c.op == "ne") holds = a != b;
  else if (c.op == "lt") holds = a < b;
  else if (c.op == "le") holds = a <= b;
  else if (c.op == "gt") holds = a > b;
  else if (c.op == "ge") holds = a >= b;
  return true;
}

void Simulator::RunScenarios(Clock::time_point now) {
  for (size_t i = 0; i < runs_.size(); ++i) {
    Run& r = *runs_[i];
    if (r.done) continue;
    for (int guard = 0; guard < 1000 && !r.done; ++guard)
      if (!StepRun(r, now)) break;
  }
}

// Advances a run by one step; false when it has to wait.
bool Simulator::StepRun(Run& r, Clock::time_point now) {
  if (r.stack.empty()) {
    EndRun(r, true, "");
    return false;
  }
  Run::Frame& f = r.stack.back();
  if (f.i >= f.steps->size()) {
    if (r.stack.size() > 1 && (f.forever || f.remaining > 0)) {
      if (!f.forever) --f.remaining;
      f.i = 0;
      return true;
    }
    r.stack.pop_back();
    if (r.stack.empty()) {
      EndRun(r, true, "");
      return false;
    }
    r.stack.back().i++;
    return true;
  }
  const Step& s = (*f.steps)[f.i];
  r.step_label = "step " + f.prefix + std::to_string(f.i + 1);
  auto fail = [&](const std::string& m) {
    EndRun(r, false, r.step_label + ": " + m);
    return false;
  };
  if (!r.active) {
    Clock::time_point due = now;
    if (s.has_at) due = r.start + std::chrono::milliseconds(s.at_ms);
    if (s.has_after) due = r.prev_end + std::chrono::milliseconds(s.after_ms);
    if (now < due) return false;
    r.active = true;
    r.step_begin = now;
  }
  auto advance = [&]() {
    r.prev_end = now;
    r.active = false;
    r.stack.back().i++;
    return true;
  };
  Dev* d = nullptr;
  if (!s.node.empty()) {
    d = Find(s.node);
    if (!d) return fail("node " + s.node + " is not simulated");
  }
  const std::string& a = s.action;
  if (a == "log") {
    Log(Host::Level::Info, "scenario " + r.sc.name + ": " + s.log);
    return advance();
  }
  if (a == "repeat") {
    Run::Frame nf;
    nf.steps = &s.steps;
    nf.forever = s.count == 0;
    nf.remaining = s.count ? s.count - 1 : 0;
    nf.prefix = f.prefix + std::to_string(f.i + 1) + ".";
    r.active = false;
    r.stack.push_back(nf);
    return true;
  }
  if (a == "set" || a == "override") {
    for (const auto& kv : s.values) {
      if (!d->objects.count(kv.first)) return fail(d->label + " has no object " + kv.first.str());
      if (a == "set") {
        Write(*d, kv.first, kv.second, 3);
        d->sets[kv.first] = Dev::Hold();
      } else {
        d->overrides[kv.first] = kv.second;
        Write(*d, kv.first, kv.second, 4);
      }
    }
    return advance();
  }
  if (a == "release") {
    if (s.release_all)
      d->overrides.clear();
    else
      for (const auto& k : s.release) d->overrides.erase(k);
    return advance();
  }
  if (a == "source") {
    for (const auto& kv : s.sources) {
      std::string err;
      if (!SetSource(*d, kv.first, kv.second, false, err)) return fail("source of " + kv.first.str() + ": " + err);
    }
    return advance();
  }
  if (a == "fault") {
    std::string err;
    if (!ApplyFault(*d, s.fault, err)) return fail(err);
    return advance();
  }
  if (a == "clear") {
    std::string err;
    if (!ClearFault(*d, s.clear, nullptr, err)) return fail(err);
    return advance();
  }
  // wait / expect
  bool holds = false;
  std::string seen, err;
  if (s.cond.is_expr) {
    auto& e = r.exprs[&s];
    if (!e) {
      Resolver res(*this, d ? d->index : -1);
      ExprError ee;
      e = Expr::compile(s.cond.expr, res, ee);
      if (!e) return fail("expression error at " + std::to_string(ee.position) + ": " + ee.message);
    }
    Ctx ctx(*this);
    ctx.t = seconds(now - r.start);
    double v = e->eval(ctx);
    holds = std::isfinite(v) && v != 0;
    char b[32];
    std::snprintf(b, sizeof b, "%.10g", v);
    seen = b;
  } else if (!EvalCondition(s.cond, s.node, holds, seen, err)) {
    return fail(err);
  }
  unsigned elapsed = static_cast<unsigned>(std::chrono::duration_cast<std::chrono::milliseconds>(now - r.step_begin).count());
  std::string cond = s.cond.text();
  std::string saw = " (value seen: " + seen + ")";
  if (a == "wait") {
    if (holds) return advance();
    if (s.timeout_ms && elapsed >= s.timeout_ms)
      return fail("wait timed out after " + std::to_string(s.timeout_ms) + " ms: " + cond + saw);
    return false;
  }
  if (s.for_ms) {
    if (!holds)
      return fail("expected " + cond + " for " + std::to_string(s.for_ms) + " ms, broken after " +
                  std::to_string(elapsed) + " ms" + saw);
    if (elapsed >= s.for_ms) return advance();
    return false;
  }
  if (holds) return advance();
  if (s.within_ms && elapsed < s.within_ms) return false;
  return fail("expected " + cond + (s.within_ms ? " within " + std::to_string(s.within_ms) + " ms" : "") + saw);
}

// ---- control requests ----

std::string Simulator::Handle(const cJSON* req, const std::string& id, const std::string& peer) {
  const cJSON* opj = cJSON_GetObjectItemCaseSensitive(req, "op");
  std::string op = cJSON_IsString(opj) ? opj->valuestring : "";
  std::string err;
  auto logchange = [&](const std::string& what) {
    Log(Host::Level::Info, what + (peer.empty() ? "" : " (from " + peer + ")"));
  };
  auto scenario_json = [&](cJSON* arr) {
    for (const auto& sc : file_.scenarios) {
      bool listed = false;
      for (const auto& r : runs_) listed = listed || r->sc.name == sc.name;
      if (listed) continue;
      cJSON* o = cJSON_CreateObject();
      cJSON_AddStringToObject(o, "name", sc.name.c_str());
      cJSON_AddStringToObject(o, "state", "idle");
      cJSON_AddBoolToObject(o, "test", sc.test);
      cJSON_AddBoolToObject(o, "autostart", sc.autostart);
      if (!sc.description.empty()) cJSON_AddStringToObject(o, "description", sc.description.c_str());
      cJSON_AddItemToArray(arr, o);
    }
    for (const auto& r : runs_) {
      cJSON* o = cJSON_CreateObject();
      cJSON_AddStringToObject(o, "name", r->sc.name.c_str());
      cJSON_AddStringToObject(o, "state", r->state.c_str());
      cJSON_AddBoolToObject(o, "test", r->sc.test);
      cJSON_AddBoolToObject(o, "autostart", r->sc.autostart);
      if (!r->sc.description.empty()) cJSON_AddStringToObject(o, "description", r->sc.description.c_str());
      cJSON_AddStringToObject(o, "step", r->step_label.c_str());
      cJSON_AddStringToObject(o, "message", r->message.c_str());
      cJSON_AddItemToArray(arr, o);
    }
  };
  auto node_json = [](const Dev& d) -> cJSON* {
    if (d.spec.extra && !d.spec.node) return cJSON_CreateString(d.spec.name.c_str());
    return cJSON_CreateNumber(d.spec.node);
  };

  if (op == "sim_status") {
    cJSON* res = cJSON_CreateObject();
    cJSON_AddBoolToObject(res, "simulated_network", opt_.simulated_network);
    cJSON_AddStringToObject(res, "interface", opt_.simulated_network ? "simulated" : host_.interface_name().c_str());
    cJSON_AddNumberToObject(res, "tick_ms", tick_ms_);
    cJSON* devs = cJSON_AddArrayToObject(res, "devices");
    for (const auto& dp : devs_) {
      const Dev& d = *dp;
      cJSON* o = cJSON_CreateObject();
      cJSON_AddItemToObject(o, "node", node_json(d));
      if (d.dev && d.dev->node_id() != 0xFF && d.dev->node_id() != d.spec.node)
        cJSON_AddNumberToObject(o, "node_id", d.dev->node_id());
      cJSON_AddStringToObject(o, "name", d.spec.name.c_str());
      cJSON_AddBoolToObject(o, "extra", d.spec.extra);
      cJSON_AddStringToObject(o, "eds", basename_of(d.spec.eds_path).c_str());
      cJSON_AddNumberToObject(o, "profile", d.profile);
      cJSON_AddStringToObject(o, "power", d.powered ? "on" : "off");
      cJSON_AddStringToObject(o, "nmt", d.dev ? nmt_name(d.dev->nmt_state()).c_str() : "off");
      cJSON_AddBoolToObject(o, "conflict", d.conflict);
      cJSON_AddBoolToObject(o, "drive", d.drive != nullptr);
      cJSON* fa = cJSON_AddArrayToObject(o, "faults");
      for (const auto& kv : d.active) {
        cJSON* j = cJSON_Parse(kv.second.c_str());
        if (j) cJSON_AddItemToArray(fa, j);
      }
      cJSON* so = cJSON_AddObjectToObject(o, "sources");
      for (const auto& kv : d.sources) {
        cJSON* j = cJSON_Parse(kv.second->src->json().c_str());
        if (j) cJSON_AddItemToObject(so, kv.first.str().c_str(), j);
      }
      cJSON* ov = cJSON_AddObjectToObject(o, "overrides");
      for (const auto& kv : d.overrides) cJSON_AddItemToObject(ov, kv.first.str().c_str(), json_value(kv.second));
      cJSON_AddItemToArray(devs, o);
    }
    scenario_json(cJSON_AddArrayToObject(res, "scenarios"));
    return answer(id, res, "");
  }
  if (op == "sim_scenario_list") {
    cJSON* res = cJSON_CreateObject();
    scenario_json(cJSON_AddArrayToObject(res, "scenarios"));
    return answer(id, res, "");
  }
  if (op == "sim_get") {
    cJSON* res = cJSON_CreateObject();
    cJSON* vals = cJSON_AddArrayToObject(res, "values");
    auto add = [&](Dev* d, const cJSON* nodej, const ObjKey& k, const std::string& e) {
      cJSON* o = cJSON_CreateObject();
      cJSON_AddItemToObject(o, "node", d ? node_json(*d) : cJSON_Duplicate(nodej, 1));
      cJSON_AddStringToObject(o, "object", k.str().c_str());
      Value v;
      if (!e.empty()) {
        cJSON_AddStringToObject(o, "error", e.c_str());
      } else if (!d->dev) {
        cJSON_AddStringToObject(o, "error", "powered off");
      } else if (!od_read(d->dev->od(), k.index, k.subindex, v)) {
        cJSON_AddStringToObject(o, "error", ("no object " + k.str()).c_str());
      } else {
        cJSON_AddItemToObject(o, "value", json_value(v));
        cJSON_AddStringToObject(o, "type", od_type_name(d->dev->od(), k.index, k.subindex).c_str());
        cJSON_AddStringToObject(o, "access", od_access(d->dev->od(), k.index, k.subindex).c_str());
        int owner = Owner(*d, k);
        const char* w = owner == 4 ? "override" : owner == 2 ? "source" : owner == 1 ? "drive" : nullptr;
        if (d->sets.count(k) && owner < 4) w = "set";
        if (w) cJSON_AddStringToObject(o, "writer", w);
      }
      cJSON_AddItemToArray(vals, o);
    };
    const cJSON* items = cJSON_GetObjectItemCaseSensitive(req, "items");
    if (cJSON_IsArray(items)) {
      for (const cJSON* it = items->child; it; it = it->next) {
        const cJSON* nj = cJSON_GetObjectItemCaseSensitive(it, "node");
        const cJSON* oj = cJSON_GetObjectItemCaseSensitive(it, "object");
        ObjKey k;
        std::string e;
        Dev* d = FindJson(nj, e);
        if (!cJSON_IsString(oj) || !parse_obj_key(oj->valuestring, k)) e = "\"object\" must be \"0xIIII:S\"";
        add(e.empty() ? d : nullptr, nj ? nj : cJSON_CreateNull(), k, e);
      }
      return answer(id, res, "");
    }
    Dev* d = FindJson(cJSON_GetObjectItemCaseSensitive(req, "node"), err);
    if (!d) return answer(id, res, err);
    if (!d->dev) return answer(id, res, d->label + " is powered off");
    for (const auto& o : d->dev->PdoObjects()) add(d, nullptr, ObjKey{o.first, o.second}, "");
    return answer(id, res, "");
  }
  if (op == "sim_check_expr") {
    Dev* d = FindJson(cJSON_GetObjectItemCaseSensitive(req, "node"), err);
    if (!d) return answer(id, nullptr, err);
    const cJSON* ej = cJSON_GetObjectItemCaseSensitive(req, "expr");
    if (!cJSON_IsString(ej)) return answer(id, nullptr, "\"expr\" must be text");
    Resolver res(*this, d->index);
    ExprError ee;
    auto e = Expr::compile(ej->valuestring, res, ee);
    cJSON* out = cJSON_CreateObject();
    cJSON_AddBoolToObject(out, "ok", e != nullptr);
    if (!e) {
      cJSON_AddStringToObject(out, "error", ee.message.c_str());
      cJSON_AddNumberToObject(out, "position", static_cast<double>(ee.position));
    }
    return answer(id, out, "");
  }
  if (op == "sim_scenario_start") {
    const cJSON* sj = cJSON_GetObjectItemCaseSensitive(req, "scenario");
    const cJSON* nj = cJSON_GetObjectItemCaseSensitive(req, "name");
    std::string name = cJSON_IsString(nj) ? nj->valuestring : "";
    if (sj) {
      Scenario sc;
      if (name.empty()) name = "adhoc";
      if (!parse_scenario(sj, name, sc, err)) return answer(id, nullptr, "scenario: " + err);
      if (!StartScenario(sc, err)) return answer(id, nullptr, err);
    } else {
      if (name.empty()) return answer(id, nullptr, "\"name\" is required");
      if (!StartScenario(name, err)) return answer(id, nullptr, err);
    }
    logchange("scenario " + name + " started");
    return answer(id, nullptr, "");
  }
  if (op == "sim_scenario_stop") {
    const cJSON* nj = cJSON_GetObjectItemCaseSensitive(req, "name");
    if (!cJSON_IsString(nj)) return answer(id, nullptr, "\"name\" is required");
    bool running = false;
    for (const auto& r : runs_) running = running || (r->sc.name == nj->valuestring && !r->done);
    if (!running) return answer(id, nullptr, std::string("scenario ") + nj->valuestring + " is not running");
    StopScenario(nj->valuestring);
    return answer(id, nullptr, "");
  }

  // Requests on one device.
  bool known = op == "sim_set" || op == "sim_override" || op == "sim_release" || op == "sim_source" ||
               op == "sim_fault" || op == "sim_clear";
  if (!known) return answer(id, nullptr, "unknown op \"" + op + "\"");
  Dev* d = FindJson(cJSON_GetObjectItemCaseSensitive(req, "node"), err);
  if (!d) return answer(id, nullptr, err);
  if (op == "sim_set" || op == "sim_override") {
    std::vector<std::pair<ObjKey, Value>> values;
    const cJSON* vj = cJSON_GetObjectItemCaseSensitive(req, "values");
    if (!cJSON_IsObject(vj) || !vj->child) return answer(id, nullptr, "\"values\" must be an object of object -> value");
    for (const cJSON* c = vj->child; c; c = c->next) {
      ObjKey k;
      Value v;
      if (!parse_obj_key(c->string, k)) return answer(id, nullptr, std::string("\"") + c->string + "\" is not an object");
      if (!parse_value(c, v)) return answer(id, nullptr, std::string("the value of ") + c->string + " must be a number or text");
      if (!d->objects.count(k)) return answer(id, nullptr, d->label + " has no object " + k.str());
      if (d->dev) {
        OdKind kind = od_kind(d->dev->od(), k.index, k.subindex);
        if ((kind == OdKind::String) != v.is_string)
          return answer(id, nullptr, k.str() + " is " + od_type_name(d->dev->od(), k.index, k.subindex) +
                                         (v.is_string ? "; give a number" : "; give text"));
      }
      values.emplace_back(k, v);
    }
    std::string desc;
    for (const auto& kv : values) {
      if (op == "sim_set") {
        Write(*d, kv.first, kv.second, 3);
        d->sets[kv.first] = Dev::Hold();
      } else {
        d->overrides[kv.first] = kv.second;
        Write(*d, kv.first, kv.second, 4);
      }
      desc += (desc.empty() ? "" : ", ") + kv.first.str() + " = " + fmt_value(kv.second);
    }
    logchange(d->label + ": " + (op == "sim_set" ? "set " : "override ") + desc);
    return answer(id, nullptr, "");
  }
  if (op == "sim_release") {
    const cJSON* oj = cJSON_GetObjectItemCaseSensitive(req, "objects");
    if (!oj || (cJSON_IsString(oj) && std::strcmp(oj->valuestring, "all") == 0)) {
      d->overrides.clear();
      logchange(d->label + ": released all overrides");
      return answer(id, nullptr, "");
    }
    if (!cJSON_IsArray(oj)) return answer(id, nullptr, "\"objects\" must be \"all\" or a list of objects");
    for (const cJSON* c = oj->child; c; c = c->next) {
      ObjKey k;
      if (!cJSON_IsString(c) || !parse_obj_key(c->valuestring, k)) return answer(id, nullptr, "\"objects\" must list objects");
      d->overrides.erase(k);
    }
    logchange(d->label + ": released overrides");
    return answer(id, nullptr, "");
  }
  if (op == "sim_source") {
    const cJSON* oj = cJSON_GetObjectItemCaseSensitive(req, "object");
    ObjKey k;
    if (!cJSON_IsString(oj) || !parse_obj_key(oj->valuestring, k)) return answer(id, nullptr, "\"object\" must be \"0xIIII:S\"");
    const cJSON* sj = cJSON_GetObjectItemCaseSensitive(req, "source");
    std::string json = !sj || cJSON_IsNull(sj) ? "" : sim_json_text(sj);
    if (!SetSource(*d, k, json, false, err)) return answer(id, nullptr, "source of " + k.str() + ": " + err);
    logchange(d->label + ": source of " + k.str() + (json.empty() ? " removed" : " = " + json));
    return answer(id, nullptr, "");
  }
  if (op == "sim_fault") {
    Fault f;
    if (!parse_fault(cJSON_GetObjectItemCaseSensitive(req, "fault"), f, err)) return answer(id, nullptr, "fault: " + err);
    if (!ApplyFault(*d, f, err)) return answer(id, nullptr, err);
    if (!peer.empty()) logchange(d->label + ": fault " + f.json);
    return answer(id, nullptr, "");
  }
  // sim_clear
  const cJSON* fj = cJSON_GetObjectItemCaseSensitive(req, "fault");
  if (!cJSON_IsString(fj)) return answer(id, nullptr, "\"fault\" must be a fault name or \"all\"");
  if (!ClearFault(*d, fj->valuestring, req, err)) return answer(id, nullptr, err);
  if (!peer.empty()) logchange(d->label + ": cleared " + std::string(fj->valuestring));
  return answer(id, nullptr, "");
}

}  // namespace canopen_sim
