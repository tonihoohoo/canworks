// bridge_host.cpp - see bridge_host.h.

#include "bridge_host.h"

#include <algorithm>
#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <dirent.h>
#include <sys/stat.h>
#include <unistd.h>

#include <cerrno>

#include "cJSON.h"
#include "log.h"
#include "outputs_gate.h"
#if CANWORKS_WITH_CANOPEN
#include "canopen_plc_api.h"
#include "host_requests.h"
#include "plc_api.h"
#endif

using canopen_plugin::BridgeConfig;
using canopen_plugin::IecArea;
using canopen_plugin::ImageUse;
using canopen_plugin::log_error;
using canopen_plugin::log_info;
using canopen_plugin::log_warn;

namespace canworks_bridge {

namespace {

// The image tables of the runtime args. The runtime's callbacks carry no
// context, so they live here; one bridge runs per process.
struct RuntimeTables {
  unsigned n = 0;  // table entries (BridgeHost::kImageLimit)
  bool low_first = false;
  std::vector<uint8_t> in;  // the input bytes the journal writes
  std::vector<IEC_BOOL> bool_in, bool_out;
  std::vector<IEC_BYTE> byte_in, byte_out;
  std::vector<IEC_UINT> int_in, int_out;
  std::vector<IEC_UDINT> dint_in, dint_out;
  std::vector<IEC_ULINT> lint_in, lint_out;
  std::vector<IEC_BOOL*> p_bool_in, p_bool_out;
  std::vector<IEC_BYTE*> p_byte_in, p_byte_out;
  std::vector<IEC_UINT*> p_int_in, p_int_out;
  std::vector<IEC_UDINT*> p_dint_in, p_dint_out;
  std::vector<IEC_ULINT*> p_lint_in, p_lint_out;
  std::vector<uint8_t> out;  // the output snapshot being decoded
  plugin_runtime_args_t rt;
};

std::unique_ptr<RuntimeTables> g_tables;

void put_input(int index, uint64_t v, unsigned nbytes) {
  RuntimeTables& t = *g_tables;
  if (index < 0 || static_cast<size_t>(index) + nbytes > t.in.size()) return;
  store_value(&t.in[index], v, nbytes, t.low_first);
}

int j_bool(int type, int index, int bit, int value) {
  RuntimeTables& t = *g_tables;
  if (type != 0 || index < 0 || static_cast<size_t>(index) >= t.in.size() || bit < 0 || bit > 7) return -1;
  uint8_t mask = static_cast<uint8_t>(1u << bit);
  if (value)
    t.in[index] |= mask;
  else
    t.in[index] &= static_cast<uint8_t>(~mask);
  return 0;
}
int j_byte(int type, int index, int value) {
  if (type != 3) return -1;
  put_input(index, static_cast<uint8_t>(value), 1);
  return 0;
}
int j_int(int type, int index, int value) {
  if (type != 5) return -1;
  put_input(index, static_cast<uint16_t>(value), 2);
  return 0;
}
int j_dint(int type, int index, unsigned value) {
  if (type != 8) return -1;
  put_input(index, value, 4);
  return 0;
}
int j_lint(int type, int index, unsigned long long value) {
  if (type != 11) return -1;
  put_input(index, value, 8);
  return 0;
}
void no_lock() {}
void rt_log(const char* fmt, ...) {
  char buf[1024];
  va_list ap;
  va_start(ap, fmt);
  std::vsnprintf(buf, sizeof(buf), fmt, ap);
  va_end(ap);
  log_info("%s", buf);
}

void make_tables(unsigned n, size_t in_bytes, bool low_first) {
  g_tables.reset(new RuntimeTables);
  RuntimeTables& t = *g_tables;
  t.n = n;
  t.low_first = low_first;
  t.in.assign(in_bytes, 0);
  t.bool_in.assign(n * 8, 0);
  t.bool_out.assign(n * 8, 0);
  t.byte_in.assign(n, 0);
  t.byte_out.assign(n, 0);
  t.int_in.assign(n, 0);
  t.int_out.assign(n, 0);
  t.dint_in.assign(n, 0);
  t.dint_out.assign(n, 0);
  t.lint_in.assign(n, 0);
  t.lint_out.assign(n, 0);
  t.p_bool_in.resize(n * 8);
  t.p_bool_out.resize(n * 8);
  for (unsigned i = 0; i < n * 8; ++i) {
    t.p_bool_in[i] = &t.bool_in[i];
    t.p_bool_out[i] = &t.bool_out[i];
  }
  auto point = [n](auto& values, auto& pointers) {
    pointers.resize(n);
    for (unsigned i = 0; i < n; ++i) pointers[i] = &values[i];
  };
  point(t.byte_in, t.p_byte_in);
  point(t.byte_out, t.p_byte_out);
  point(t.int_in, t.p_int_in);
  point(t.int_out, t.p_int_out);
  point(t.dint_in, t.p_dint_in);
  point(t.dint_out, t.p_dint_out);
  point(t.lint_in, t.p_lint_in);
  point(t.lint_out, t.p_lint_out);
  plugin_runtime_args_t& rt = t.rt;
  std::memset(&rt, 0, sizeof(rt));
  rt.bool_input = reinterpret_cast<IEC_BOOL*(*)[8]>(t.p_bool_in.data());
  rt.bool_output = reinterpret_cast<IEC_BOOL*(*)[8]>(t.p_bool_out.data());
  rt.byte_input = t.p_byte_in.data();
  rt.byte_output = t.p_byte_out.data();
  rt.int_input = t.p_int_in.data();
  rt.int_output = t.p_int_out.data();
  rt.dint_input = t.p_dint_in.data();
  rt.dint_output = t.p_dint_out.data();
  rt.lint_input = t.p_lint_in.data();
  rt.lint_output = t.p_lint_out.data();
  rt.image_lock = no_lock;
  rt.image_unlock = no_lock;
  rt.buffer_size = static_cast<int>(n);
  rt.bits_per_buffer = 8;
  rt.log_info = rt_log;
  rt.log_debug = rt_log;
  rt.log_warn = rt_log;
  rt.log_error = rt_log;
  rt.journal_write_bool = j_bool;
  rt.journal_write_byte = j_byte;
  rt.journal_write_int = j_int;
  rt.journal_write_dint = j_dint;
  rt.journal_write_lint = j_lint;
  rt.base_tick_ns = 1000000;  // the loop's period
}

// The output snapshot in g_tables->out into the typed output tables.
void decode_outputs() {
  RuntimeTables& t = *g_tables;
  const size_t size = std::min<size_t>(t.out.size(), t.n);
  const uint8_t* o = t.out.data();
  for (size_t i = 0; i < size; ++i) {
    t.byte_out[i] = o[i];
    for (unsigned b = 0; b < 8; ++b) t.bool_out[i * 8 + b] = (o[i] >> b) & 1;
    if (i + 2 <= size) t.int_out[i] = static_cast<IEC_UINT>(load_value(o + i, 2, false));
    if (i + 4 <= size) t.dint_out[i] = static_cast<IEC_UDINT>(load_value(o + i, 4, t.low_first));
    if (i + 8 <= size) t.lint_out[i] = static_cast<IEC_ULINT>(load_value(o + i, 8, t.low_first));
  }
}

#if CANWORKS_WITH_CANOPEN
// The SDO bridge registers on the queue of the SDO function blocks and the
// gateway's SDO bridge (plc_api.h).
class PlcSdoBackend : public SdoBackend {
 public:
  bool start(const SdoRequest& r, uint32_t& abort) override {
    canopen_plc_request q{};
    q.network = r.network;
    q.node = r.node;
    q.index = r.index;
    q.subindex = r.subindex;
    q.write = r.command == 2 ? 1 : 0;
    q.kind = CANOPEN_PLC_INT;
    q.timeout_ms = 1000;
    uint8_t data[8] = {0};
    if (q.write) {
      for (int i = 0; i < 4; ++i) data[i] = static_cast<uint8_t>(r.value >> (8 * i));
      q.data = data;
      q.length = 8;
      q.size = r.length;
    }
    uint16_t err = 0;
    handle_ = canopen_plugin::PlcRequests::instance().start(q, err);
    if (!handle_) {
      abort = err == CANOPEN_PLC_ERR_BUSY ? 0x08000022u : kAbortGeneral;
      return false;
    }
    log_info("Modbus SDO bridge: %s of node %u 0x%04X:%u on network %u", q.write ? "write" : "read", r.node, r.index,
             r.subindex, r.network);
    return true;
  }
  int poll(uint32_t& value, uint32_t& abort) override {
    canopen_plc_result res{};
    uint8_t data[8] = {0};
    int rc = canopen_plugin::PlcRequests::instance().poll(handle_, &res, data, sizeof(data));
    if (rc == 0) return 0;
    if (rc == 1) {
      value = 0;
      unsigned n = std::min<uint32_t>(res.size, 4);
      for (unsigned i = 0; i < n; ++i) value |= uint32_t(data[i]) << (8 * i);
      return 1;
    }
    abort = res.abort_code;
    if (!abort)
      abort = res.error_id == CANOPEN_PLC_ERR_TIMEOUT       ? 0x05040000u
              : res.error_id == CANOPEN_PLC_ERR_UNAVAILABLE ? 0x08000022u
                                                            : kAbortGeneral;
    return -1;
  }

 private:
  uint32_t handle_ = 0;
};
#else
class PlcSdoBackend : public SdoBackend {
 public:
  bool start(const SdoRequest&, uint32_t& abort) override {
    abort = kAbortGeneral;  // no CANopen in this build
    return false;
  }
  int poll(uint32_t&, uint32_t&) override { return -1; }
};
#endif

PlcSdoBackend g_sdo_backend;

const char* loss_name(BridgeConfig::Loss l) {
  switch (l) {
    case BridgeConfig::Loss::Zero: return "zero";
    case BridgeConfig::Loss::Hold: return "hold";
    default: return "stop";
  }
}

const char* nmt_command(uint8_t cmd) {
  switch (cmd) {
    case kCmdNmtStart: return "start";
    case kCmdNmtStop: return "stop";
    case kCmdNmtPreOperational: return "preop";
    case kCmdResetNode: return "reset";
    default: return "reset-comm";
  }
}

}  // namespace

bool server_config(const BridgeConfig& b, ServerConfig& out, std::string& err) {
  out = ServerConfig();
  out.listen = b.listen;
  out.unit_id = static_cast<uint8_t>(b.unit_id);
  out.max_clients = static_cast<int>(b.max_clients);
  out.max_clients_per_address = static_cast<int>(b.max_clients_per_address);
  for (const auto& a : b.readers) {
    if (!out.readers.add(a, err)) {
      err = "bridge readers: " + err;
      return false;
    }
  }
  for (const auto& a : b.writers) {
    if (!out.writers.add(a, err)) {
      err = "bridge writers: " + err;
      return false;
    }
  }
  return true;
}

bool image_sizes(const std::vector<ImageUse>& uses, uint64_t limit, size_t& in, size_t& out, std::string& err) {
  uint64_t in_end = 0, out_end = 0;
  for (const ImageUse& u : uses) {
    uint64_t end = static_cast<uint64_t>(u.loc.index) + u.nbytes;
    if (end > limit) {
      err = u.loc.str() + " (" + u.who + ") ends past the bridge image of " + std::to_string(limit) + " bytes";
      return false;
    }
    uint64_t& e = u.loc.area == IecArea::Input ? in_end : out_end;
    e = std::max(e, end);
  }
  in = static_cast<size_t>(in_end);
  out = static_cast<size_t>(out_end);
  return true;
}

BridgeHost::BridgeHost() = default;

BridgeHost::~BridgeHost() {
  stop();
  engine_.reset();
}

bool BridgeHost::check(const std::string& config_path, std::vector<std::string>* problems) {
  canopen_plugin::ImageLimits limits;
  limits.buffer_size = kImageLimit;
  limits.bridge_host = true;
  limits.force_simulate = canopen_plugin::force_simulate_from_env(std::getenv("CANWORKS_FORCE_SIMULATE"));
  return canopen_plugin::Engine::check(config_path, limits, problems);
}

bool BridgeHost::start(const std::string& config_path, const char* version) {
  stop();
  engine_.reset(new canopen_plugin::Engine);
  canopen_plugin::ImageLimits limits;
  limits.buffer_size = kImageLimit;
  limits.bridge_host = true;
  limits.force_simulate = canopen_plugin::force_simulate_from_env(std::getenv("CANWORKS_FORCE_SIMULATE"));
  config_path_ = config_path;
  version_ = version;
  canopen_plugin::DiagHost dh;
  dh.name = "bridge";
  dh.status_part = [this] { return status_json(); };
  dh.put_config = [this](const std::vector<std::pair<std::string, std::string>>& files, std::string& why) {
    return put_config(files, why);
  };
  engine_->set_diag_host(dh);
  if (!engine_->prepare(config_path, limits, 1000000, version)) return false;
  const canopen_plugin::ConfigSet& s = engine_->set();
  cfg_ = s.bridge;

  size_t in_bytes = 0, out_bytes = 0;
  std::vector<ImageUse> uses = canopen_plugin::image_uses(s);
  std::string err;
  ServerConfig sc;
  if (!image_sizes(uses, kImageLimit, in_bytes, out_bytes, err) || !server_config(cfg_, sc, err)) {
    log_error("%s; canworks-bridge not started", err.c_str());
    return false;
  }
  if (!listen_override.empty()) sc.listen = listen_override;
  data_outputs_.clear();
  for (const ImageUse& u : uses)
    if (u.loc.area != IecArea::Input && !u.bridge_block) data_outputs_.push_back(u);
  image_.resize(in_bytes, out_bytes);
  make_tables(kImageLimit, image_.input_size(), cfg_.low_first);
  g_tables->out.assign(image_.output_size(), 0);
  out_copy_.assign(image_.output_size(), 0);
  is_master_.clear();
  unsigned max_sync_us = 0;
  for (const auto& n : s.networks) {
    bool master = n.is_canopen() && !n.is_slave();
    is_master_.push_back(master);
    if (master) max_sync_us = std::max(max_sync_us, n.master.sync_period_us);
  }
  zero_settle_ = std::max(std::chrono::milliseconds(100), std::chrono::milliseconds(2 * max_sync_us / 1000));

  server_.on_write = [this] { on_write(); };
  server_.log = [](const std::string& line) { log_info("%s", line.c_str()); };

  Clock::time_point now = Clock::now();
  supervisor_.reset(new OutputSupervisor(cfg_.watchdog_ms, now));
  control_ = ControlBlock();
  sdo_.reset(cfg_.has_sdo_bridge ? new SdoBridgeRegisters(cfg_.sdo_bridge_write) : nullptr);
  zero_pending_ = false;
  outputs_seen_ = ~0ull;
  canopen_plugin::set_outputs_enabled(true);

  engine_->start();
  if (!server_.start(sc, err)) {
    log_error("%s; canworks-bridge not started", err.c_str());
    engine_->stop();
    return false;
  }
  log_info("canworks-bridge: config %s, protocols %s; Modbus TCP on %s (unit %u, word order %s), %zu input bytes, "
           "%zu output bytes; watchdog %u ms, on client loss %s",
           config_path.c_str(), canopen_plugin::built_in_protocols().c_str(), cfg_.listen.c_str(), cfg_.unit_id,
           cfg_.low_first ? "low_first" : "high_first", image_.input_size(), image_.output_size(), cfg_.watchdog_ms,
           loss_name(cfg_.on_client_loss));
  started_ = now;
  stop_ = false;
  thread_ = std::thread(&BridgeHost::loop, this);
  running_ = true;
  return true;
}

void BridgeHost::stop() {
  if (!running_) return;
  stop_ = true;
  if (thread_.joinable()) thread_.join();
  server_.stop();
  engine_->stop();
  canopen_plugin::set_outputs_enabled(true);
  running_ = false;
}

void BridgeHost::push_outputs() {
  uint64_t v = image_.take_outputs(g_tables->out.data(), outputs_seen_);
  if (v == outputs_seen_) return;
  outputs_seen_ = v;
  decode_outputs();
  engine_->cycle_end(g_tables->rt);
}

void BridgeHost::on_write() {
  std::lock_guard<std::mutex> lock(exchange_mu_);
  if (supervisor_->write(Clock::now())) leave_off("a client wrote");
  push_outputs();
}

void BridgeHost::enter_off(OutputState why, Clock::time_point now) {
  const char* reason = why == OutputState::kIdle ? "the control block's idle command"
                                                 : "the watchdog (no write from a writer client)";
  switch (cfg_.on_client_loss) {
    case BridgeConfig::Loss::Hold:
      log_warn("outputs held at their last values by %s (on_client_loss hold)", reason);
      return;
    case BridgeConfig::Loss::Zero: {
      log_warn("outputs off by %s: outputs set to 0 and sent once, then stopped (on_client_loss zero)", reason);
      clear_outputs();
      push_outputs();
      zero_pending_ = true;
      zero_until_ = now + zero_settle_;
      return;
    }
    case BridgeConfig::Loss::Stop: {
      log_warn("outputs off by %s: RPDOs and transmit messages stopped, output image cleared (on_client_loss stop)",
               reason);
      canopen_plugin::set_outputs_enabled(false);
      // Nothing is sent now; the write that ends outputs off starts from
      // zeros, not from the values written before the loss.
      clear_outputs();
      return;
    }
  }
}

void BridgeHost::clear_outputs() {
  std::vector<uint8_t> zeros(8, 0);
  for (const ImageUse& u : data_outputs_) {
    if (zeros.size() < u.nbytes) zeros.resize(u.nbytes, 0);
    image_.write_outputs(u.loc.index, zeros.data(), u.nbytes);
  }
}

void BridgeHost::leave_off(const char* why) {
  zero_pending_ = false;
  if (cfg_.on_client_loss != BridgeConfig::Loss::Hold) canopen_plugin::set_outputs_enabled(true);
  log_info("outputs on again: %s", why);
}

void BridgeHost::service_control(const uint8_t* out, Clock::time_point now) {
  if (!cfg_.has_control) return;
  ControlRequest req;
  if (!control_.poll(out + cfg_.control_location.index, req)) return;
  uint8_t result = ControlBlock::check(req, is_master_);
  if (result == kCtrlOk) {
    switch (req.command) {
      case kCmdNone: break;
      case kCmdRun:
        if (supervisor_->run(now)) leave_off("the control block's run command");
        break;
      case kCmdIdle:
        if (supervisor_->idle()) enter_off(OutputState::kIdle, now);
        break;
      default:
#if CANWORKS_WITH_CANOPEN
        canopen_plugin::HostRequests::instance().nmt(req.network, req.node, nmt_command(req.command));
#endif
        break;
    }
  }
  if (req.command != kCmdNone || result != kCtrlOk)
    log_info("Modbus control block: command %u, network %u, node %u (counter %u): result %u", req.command,
             req.network, req.node, req.counter, result);
  control_.handled(req.counter, result);
}

void BridgeHost::write_blocks(Clock::time_point now) {
  std::vector<uint8_t>& in = g_tables->in;
  if (cfg_.has_status) {
    auto ticks = std::chrono::duration_cast<std::chrono::milliseconds>(now - started_).count() / 100;
    encode_status(&in[cfg_.status_location.index], supervisor_->state(), server_.clients(),
                  static_cast<uint16_t>(ticks), control_);
  }
#if CANWORKS_WITH_CANOPEN
  for (const auto& l : cfg_.live_lists)
    encode_live_list(&in[l.location.index], canopen_plugin::HostRequests::instance().operational(l.network));
#endif
  if (sdo_) sdo_->encode(&in[cfg_.sdo_response.index]);
}

void BridgeHost::loop() {
  canopen_plugin::set_thread_log_prefix("");
  uint64_t ctl_seen = ~0ull;
  auto next = Clock::now();
  while (!stop_) {
    {
      std::lock_guard<std::mutex> lock(exchange_mu_);
      Clock::time_point now = Clock::now();
      engine_->cycle_start(g_tables->rt);
      if (supervisor_->tick(now)) enter_off(OutputState::kWatchdog, now);
      if (zero_pending_ && now >= zero_until_) {
        zero_pending_ = false;
        canopen_plugin::set_outputs_enabled(false);
      }
      ctl_seen = image_.take_outputs(out_copy_.data(), ctl_seen);
      service_control(out_copy_.data(), now);
      if (sdo_) sdo_->service(out_copy_.data() + cfg_.sdo_request.index, g_sdo_backend);
      write_blocks(now);
      image_.publish_inputs(g_tables->in.data(), g_tables->in.size());
      push_outputs();  // the first snapshot, and the zero action's
    }
    next += std::chrono::milliseconds(1);
    Clock::time_point now = Clock::now();
    if (next < now) next = now;
    std::this_thread::sleep_until(next);
  }
}

cJSON* BridgeHost::status_json() const {
  std::lock_guard<std::mutex> lock(exchange_mu_);
  cJSON* b = cJSON_CreateObject();
  OutputState st = supervisor_ ? supervisor_->state() : OutputState::kRunning;
  cJSON_AddStringToObject(b, "state", st == OutputState::kRunning ? "running" : "outputs_off");
  if (st == OutputState::kWatchdog)
    cJSON_AddStringToObject(b, "reason", "watchdog");
  else if (st == OutputState::kIdle)
    cJSON_AddStringToObject(b, "reason", "idle");
  else
    cJSON_AddNullToObject(b, "reason");
  cJSON_AddStringToObject(b, "on_client_loss", loss_name(cfg_.on_client_loss));
  cJSON_AddStringToObject(b, "listen", cfg_.listen.c_str());
  cJSON_AddNumberToObject(b, "unit_id", cfg_.unit_id);
  cJSON_AddNumberToObject(b, "input_bytes", static_cast<double>(image_.input_size()));
  cJSON_AddNumberToObject(b, "output_bytes", static_cast<double>(image_.output_size()));
  cJSON_AddNumberToObject(b, "watchdog_ms", cfg_.watchdog_ms);
  cJSON* clients = cJSON_AddArrayToObject(b, "clients");
  for (const ClientInfo& c : server_.client_list()) {
    cJSON* o = cJSON_CreateObject();
    cJSON_AddStringToObject(o, "address", c.address.c_str());
    cJSON_AddNumberToObject(o, "requests", static_cast<double>(c.requests));
    cJSON_AddBoolToObject(o, "writer", c.writer);
    cJSON_AddItemToArray(clients, o);
  }
  if (supervisor_ && cfg_.watchdog_ms && st == OutputState::kRunning)
    cJSON_AddNumberToObject(b, "watchdog_left_ms", static_cast<double>(supervisor_->left_ms(Clock::now())));
  std::lock_guard<std::mutex> ul(upload_mu_);
  if (!upload_result_.empty()) {
    cJSON* u = cJSON_AddObjectToObject(b, "last_upload");
    cJSON_AddNumberToObject(u, "number", upload_number_);
    cJSON_AddStringToObject(u, "result", upload_result_.c_str());
    cJSON_AddStringToObject(u, "detail", upload_detail_.c_str());
  }
  return b;
}

// ---- config upload (put_config) ----

namespace {

std::string dir_of(const std::string& path) {
  size_t slash = path.rfind('/');
  return slash == std::string::npos ? "." : slash == 0 ? "/" : path.substr(0, slash);
}

std::string base_of(const std::string& path) {
  size_t slash = path.rfind('/');
  return slash == std::string::npos ? path : path.substr(slash + 1);
}

bool make_dirs(const std::string& dir) {
  std::string cur;
  size_t i = 0;
  while (i <= dir.size()) {
    size_t j = dir.find('/', i);
    if (j == std::string::npos) j = dir.size();
    cur = dir.substr(0, j);
    if (!cur.empty() && ::mkdir(cur.c_str(), 0755) != 0 && errno != EEXIST) return false;
    i = j + 1;
  }
  return true;
}

void remove_tree(const std::string& path) {
  struct stat st;
  if (::lstat(path.c_str(), &st) != 0) return;
  if (S_ISDIR(st.st_mode)) {
    if (DIR* d = ::opendir(path.c_str())) {
      while (dirent* e = ::readdir(d)) {
        std::string n = e->d_name;
        if (n != "." && n != "..") remove_tree(path + "/" + n);
      }
      ::closedir(d);
    }
    ::rmdir(path.c_str());
  } else {
    ::unlink(path.c_str());
  }
}

bool write_file(const std::string& path, const std::string& data) {
  if (!make_dirs(dir_of(path))) return false;
  FILE* f = std::fopen(path.c_str(), "wb");
  if (!f) return false;
  bool ok = std::fwrite(data.data(), 1, data.size(), f) == data.size();
  return std::fclose(f) == 0 && ok;
}

bool read_file(const std::string& path, std::string& out) {
  FILE* f = std::fopen(path.c_str(), "rb");
  if (!f) return false;
  out.clear();
  char buf[65536];
  size_t n;
  while ((n = std::fread(buf, 1, sizeof(buf), f)) > 0) out.append(buf, n);
  std::fclose(f);
  return true;
}

bool copy_file(const std::string& from, const std::string& to) {
  std::string data;
  return read_file(from, data) && write_file(to, data);
}

}  // namespace

// The uploaded "canworks.json" is the running config file, whatever its name.
std::string BridgeHost::staged_path(const std::string& name) const {
  return name == "canworks.json" ? base_of(config_path_) : name;
}

unsigned BridgeHost::put_config(const std::vector<std::pair<std::string, std::string>>& files, std::string& why) {
  std::lock_guard<std::mutex> lock(upload_mu_);
  if (upload_pending_) {
    why = "a config upload is being applied; try again in a moment";
    return 0;
  }
  const std::string stage = dir_of(config_path_) + "/.canworks-upload";
  remove_tree(stage);
  staged_.clear();
  for (const auto& f : files) {
    std::string rel = staged_path(f.first);
    if (!write_file(stage + "/" + rel, f.second)) {
      why = "cannot stage " + f.first + " in " + stage + ": " + std::strerror(errno);
      remove_tree(stage);
      return 0;
    }
    staged_.push_back(rel);
  }
  std::vector<std::string> problems;
  if (!check(stage + "/" + base_of(config_path_), &problems)) {
    remove_tree(stage);
    why = "the uploaded config was rejected; the running config stays:";
    for (const auto& p : problems) why += "\n" + p;
    return 0;
  }
  upload_pending_ = true;
  ++upload_number_;
  log_info("canworks-bridge: uploaded config accepted; restarting on it");
  return upload_number_;
}

bool BridgeHost::upload_pending() const {
  std::lock_guard<std::mutex> lock(upload_mu_);
  return upload_pending_;
}

void BridgeHost::apply_upload() {
  std::vector<std::string> staged;
  {
    std::lock_guard<std::mutex> lock(upload_mu_);
    if (!upload_pending_) return;
    staged = staged_;
  }
  const std::string dir = dir_of(config_path_);
  const std::string stage = dir + "/.canworks-upload";
  const std::string backup = dir + "/.canworks-previous";
  std::string path = config_path_, version = version_;
  stop();
  remove_tree(backup);
  std::vector<std::string> created;
  for (const auto& rel : staged) {
    struct stat st;
    if (::stat((dir + "/" + rel).c_str(), &st) == 0)
      copy_file(dir + "/" + rel, backup + "/" + rel);
    else
      created.push_back(rel);
  }
  for (const auto& rel : staged) copy_file(stage + "/" + rel, dir + "/" + rel);
  remove_tree(stage);
  std::string result = "started", detail;
  if (!start(path, version.c_str())) {
    log_error("canworks-bridge: the uploaded config did not start; going back to the previous one");
    for (const auto& rel : staged) {
      if (std::find(created.begin(), created.end(), rel) != created.end())
        ::unlink((dir + "/" + rel).c_str());
      else
        copy_file(backup + "/" + rel, dir + "/" + rel);
    }
    result = "restored";
    detail = "the uploaded config did not start (see the log); the previous config runs again";
    if (!start(path, version.c_str())) detail = "the uploaded config did not start, nor did the previous one";
  } else {
    detail = "the uploaded config runs";
  }
  std::lock_guard<std::mutex> lock(upload_mu_);
  upload_pending_ = false;
  upload_result_ = result;
  upload_detail_ = detail;
}

}  // namespace canworks_bridge
