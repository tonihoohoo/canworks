// bridge_host.cpp - see bridge_host.h.

#include "bridge_host.h"

#include <algorithm>
#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <dirent.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <sys/statvfs.h>
#include <unistd.h>

#include <cerrno>

#include "cJSON.h"
#include "can_plc_api.h"
#include "image_io.h"
#include "log.h"
#include "outputs_gate.h"
#include "progress.h"
#if CANWORKS_WITH_CANOPEN
#include "canopen_plc_api.h"
#include "host_requests.h"
#include "plc_api.h"
#endif

using canopen_plugin::BridgeConfig;
using canopen_plugin::IecArea;
using canopen_plugin::ImageUse;
using canopen_plugin::log_debug;
using canopen_plugin::log_error;
using canopen_plugin::log_info;
using canopen_plugin::log_warn;

namespace canworks_bridge {

namespace {

std::unique_ptr<canopen_plugin::ByteImageHost> g_image;

#if CANWORKS_WITH_CANOPEN
// The SDO bridge registers on the queue of the SDO function blocks and the
// gateway's SDO bridge (plc_api.h).
class PlcSdoBackend : public SdoBackend {
 public:
  bool start(const SdoRequest& r, uint32_t& abort) override {
    req_ = r;
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
    // One line per request would fill the journal for a program that reads every scan.
    log_debug("Modbus SDO bridge: %s of node %u 0x%04X:%u on network %u", q.write ? "write" : "read", r.node, r.index,
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
    log_info("Modbus SDO bridge: %s of node %u 0x%04X:%u on network %u ended with abort 0x%08X",
             req_.command == 2 ? "write" : "read", req_.node, req_.index, req_.subindex, req_.network, abort);
    return -1;
  }

 private:
  uint32_t handle_ = 0;
  SdoRequest req_;
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
    case BridgeConfig::Loss::Preop: return "preop";
    case BridgeConfig::Loss::Safe: return "safe";
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

namespace {

uint64_t utc_now_us() {
  return static_cast<uint64_t>(std::chrono::duration_cast<std::chrono::microseconds>(
                                   std::chrono::system_clock::now().time_since_epoch())
                                   .count());
}

const char* write_table(uint8_t fn) {
  return fn == 5 || fn == 15 ? "coil" : "holding register";
}

// A client's counters in the status (modbus-bridge "Client counters").
cJSON* client_json(const ClientInfo& c) {
  cJSON* o = cJSON_CreateObject();
  cJSON_AddStringToObject(o, "address", c.address.c_str());
  cJSON_AddNumberToObject(o, "port", c.port);
  cJSON_AddNumberToObject(o, "connection", c.connection);
  cJSON_AddNumberToObject(o, "requests", static_cast<double>(c.requests));
  cJSON_AddBoolToObject(o, "writer", c.writer);
  cJSON_AddNumberToObject(o, "connected_us", static_cast<double>(c.connected_us));
  cJSON_AddNumberToObject(o, "rate", static_cast<double>(c.recent) / 5.0);
  cJSON* fns = cJSON_AddObjectToObject(o, "functions");
  for (size_t i = 0; i < kFunctionSlots; ++i) {
    if (!c.functions[i]) continue;
    std::string k = i < sizeof(kCountedFunctions) ? std::to_string(kCountedFunctions[i]) : "other";
    cJSON_AddNumberToObject(fns, k.c_str(), static_cast<double>(c.functions[i]));
  }
  cJSON* ex = cJSON_AddObjectToObject(o, "exceptions");
  for (size_t i = 0; i < kExceptionSlots; ++i) {
    if (!c.exceptions[i]) continue;
    char k[8];
    if (i < sizeof(kCountedExceptions))
      std::snprintf(k, sizeof(k), "0x%02X", kCountedExceptions[i]);
    else
      std::snprintf(k, sizeof(k), "other");
    cJSON_AddNumberToObject(ex, k, static_cast<double>(c.exceptions[i]));
  }
  cJSON_AddNumberToObject(o, "refused_writes", static_cast<double>(c.refused_writes));
  if (c.last_write_us) {
    cJSON* w = cJSON_AddObjectToObject(o, "last_write");
    cJSON_AddNumberToObject(w, "time_us", static_cast<double>(c.last_write_us));
    cJSON_AddNumberToObject(w, "function", c.last_write_function);
    cJSON_AddStringToObject(w, "table", write_table(c.last_write_function));
    cJSON_AddNumberToObject(w, "start", c.last_write_start);
    cJSON_AddNumberToObject(w, "count", c.last_write_count);
  } else {
    cJSON_AddNullToObject(o, "last_write");
  }
  return o;
}

std::string dir_of(const std::string& path) {
  size_t slash = path.rfind('/');
  return slash == std::string::npos ? "." : slash == 0 ? "/" : path.substr(0, slash);
}

std::string base_of(const std::string& path) {
  size_t slash = path.rfind('/');
  return slash == std::string::npos ? path : path.substr(slash + 1);
}

bool exists(const std::string& path) {
  struct stat st;
  return ::stat(path.c_str(), &st) == 0;
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

// Writes a folder's entries (a rename, a new or removed file) to disk.
void sync_dir(const std::string& dir) {
  int fd = ::open(dir.c_str(), O_RDONLY | O_DIRECTORY | O_CLOEXEC);
  if (fd < 0) return;
  ::fsync(fd);
  ::close(fd);
}

// Replaces `path` atomically: a temporary file next to it, written to disk,
// renamed over it, and the folder written to disk. After a power loss the
// file is either the old or the new one, never a part. `why` gets the
// reason of a failure (the temporary file is removed then).
bool write_file(const std::string& path, const std::string& data, std::string* why = nullptr) {
  auto fail = [&](const char* step, const std::string& tmp) {
    if (why) *why = std::string(step) + " " + path + ": " + std::strerror(errno);
    if (!tmp.empty()) ::unlink(tmp.c_str());
    return false;
  };
  const std::string dir = dir_of(path);
  if (!make_dirs(dir)) return fail("cannot create the folder of", "");
  const std::string tmp = dir + "/." + base_of(path) + ".canworks-new";
  int fd = ::open(tmp.c_str(), O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC, 0644);
  if (fd < 0) return fail("cannot write", "");
  size_t done = 0;
  while (done < data.size()) {
    ssize_t n = ::write(fd, data.data() + done, data.size() - done);
    if (n < 0 && errno == EINTR) continue;
    if (n <= 0) {
      if (n == 0) errno = ENOSPC;
      int e = errno;
      ::close(fd);
      errno = e;
      return fail("cannot write", tmp);
    }
    done += static_cast<size_t>(n);
  }
  if (::fsync(fd) != 0) {
    int e = errno;
    ::close(fd);
    errno = e;
    return fail("cannot write", tmp);
  }
  if (::close(fd) != 0) return fail("cannot write", tmp);
  if (::rename(tmp.c_str(), path.c_str()) != 0) return fail("cannot replace", tmp);
  sync_dir(dir);
  return true;
}

bool read_file(const std::string& path, std::string& out) {
  FILE* f = std::fopen(path.c_str(), "rb");
  if (!f) return false;
  out.clear();
  char buf[65536];
  size_t n;
  while ((n = std::fread(buf, 1, sizeof(buf), f)) > 0) out.append(buf, n);
  bool ok = !std::ferror(f);
  std::fclose(f);
  return ok;
}

bool copy_file(const std::string& from, const std::string& to, std::string* why = nullptr) {
  std::string data;
  if (!read_file(from, data)) {
    if (why) *why = "cannot read " + from + ": " + std::strerror(errno);
    return false;
  }
  return write_file(to, data, why);
}

// Free bytes for an unprivileged writer in `dir`'s file system; -1 unknown.
long long free_bytes(const std::string& dir) {
  struct statvfs vfs;
  if (::statvfs(dir.c_str(), &vfs) != 0) return -1;
  return static_cast<long long>(vfs.f_bavail) * static_cast<long long>(vfs.f_frsize);
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

bool BridgeHost::check(const std::string& config_path, std::vector<std::string>* problems, uint32_t* map_hash) {
  canopen_plugin::ImageLimits limits;
  limits.buffer_size = kImageLimit;
  limits.force_simulate = canopen_plugin::force_simulate_from_env(std::getenv("CANWORKS_FORCE_SIMULATE"));
  if (!canopen_plugin::Engine::check(config_path, limits, problems)) return false;
  if (map_hash) {
    canopen_plugin::ConfigSet set;
    std::vector<std::string> errors;
    if (canopen_plugin::load_config_set(config_path, limits, set, errors)) *map_hash = canopen_plugin::map_hash(set);
  }
  return true;
}

bool BridgeHost::start(const std::string& config_path, const char* version) {
  stop();
  engine_.reset(new canopen_plugin::Engine);
  canopen_plugin::ImageLimits limits;
  limits.buffer_size = kImageLimit;
  limits.force_simulate = canopen_plugin::force_simulate_from_env(std::getenv("CANWORKS_FORCE_SIMULATE"));
  config_path_ = config_path;
  version_ = version;
  if (last_stop_.empty()) {
    // Before prepare() makes .canworks/: without it this config never ran here.
    last_stop_ = exists(marker_path()) ? "unclean" : exists(dir_of(marker_path())) ? "clean" : "unknown";
    unclean_start_ = last_stop_ == "unclean";
    if (unclean_start_)
      log_warn("canworks-bridge: the previous run of this config did not stop cleanly (a crash, a kill, a hang or a "
               "power loss); status byte 7 bit 0 is set for this run");
  }
  canopen_plugin::DiagHost dh;
  dh.name = "bridge";
  dh.status_part = [this] { return status_json(); };
  dh.put_config = [this](const std::vector<std::pair<std::string, std::string>>& files, std::string& why) {
    return put_config(files, why);
  };
  dh.host_op = [this](uint64_t client, const std::string& id, const std::string& op, const cJSON* req,
                      std::string& out) { return modbus_trace_op(client, id, op, req, out); };
  dh.client_gone = [this](uint64_t client) {
    if (modbus_trace_.stop(client)) log_info("diagnostics: Modbus trace ended: client disconnected");
  };
  engine_->set_diag_host(dh);
  if (!engine_->prepare(config_path, limits, version)) return false;
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
  map_hash_ = canopen_plugin::map_hash(s);
  image_.set_link(cfg_.plc_link ? canopen_plugin::kOpenplcHeaderBytes : 0, map_hash_);
  mismatch_logged_ = false;
  g_image.reset(new canopen_plugin::ByteImageHost);
  g_image->low_first = cfg_.low_first;
  g_image->in.assign(image_.input_size(), 0);
  g_image->out.assign(image_.output_size(), 0);
  out_copy_.assign(image_.output_size(), 0);
  is_master_.clear();
  unsigned max_sync_us = 0;
  for (const auto& n : s.networks) {
    bool master = n.is_canopen() && !n.is_slave();
    is_master_.push_back(master);
    if (master) max_sync_us = std::max(max_sync_us, n.master.sync_period_us);
  }
  zero_settle_ = std::max(std::chrono::milliseconds(100), std::chrono::milliseconds(2 * max_sync_us / 1000));
  safe_stop_wait_ = std::min(std::chrono::milliseconds(200),
                             std::max(std::chrono::milliseconds(20), std::chrono::milliseconds(max_sync_us / 1000)));
  safe_out_.assign(image_.output_size(), 0);
  for (const auto& v : cfg_.safe_values) {
    if (v.loc.index >= safe_out_.size()) continue;
    if (v.nbytes) {
      if (v.loc.index + v.nbytes <= safe_out_.size()) store_value(&safe_out_[v.loc.index], v.raw, v.nbytes, cfg_.low_first);
    } else if (v.raw) {
      safe_out_[v.loc.index] = static_cast<uint8_t>(safe_out_[v.loc.index] | (1u << v.loc.bit));
    } else {
      safe_out_[v.loc.index] = static_cast<uint8_t>(safe_out_[v.loc.index] & ~(1u << v.loc.bit));
    }
  }

  server_.on_write = [this] { on_write(); };
  server_.trace = &modbus_trace_;
  {
    // Read Device Identification (modbus-bridge "Device identification
    // with the map hash"): a client checks the map without the PLC link.
    char hash[16];
    std::snprintf(hash, sizeof(hash), "%08X", map_hash_);
    server_.identity = DeviceIdentity{"canworks", "canworks-bridge", version ? version : "", hash};
  }
  server_.log = [](const std::string& line) { log_info("%s", line.c_str()); };

  Clock::time_point now = Clock::now();
  supervisor_.reset(new OutputSupervisor(cfg_.watchdog_ms, now));
  // PLC link: outputs stay off until the header says the PLC runs.
  if (cfg_.plc_link) supervisor_->link_off(OutputState::kPlcStopped);
  control_ = ControlBlock();
  // A PLC behind the link header rewrites its whole output image every poll,
  // so after a restart its last request would run again: PLC link configs
  // take a baseline first. Other clients write a block when they mean it.
  control_known_ = sdo_known_ = !cfg_.plc_link;
  sdo_.reset(cfg_.has_sdo_bridge ? new SdoBridgeRegisters(cfg_.sdo_bridge_write) : nullptr);
  mailboxes_.reset();
  mailbox_backend_.reset();
  mb_written_ = 0;
  modbus_trace_.set_ignored({}, {});
  image_.watch_reads(0, 0);
  if (cfg_.has_mailboxes) {
    MailboxLayout ml;
    ml.requests = cfg_.mb_requests;
    ml.receive = cfg_.mb_receive;
    ml.receive_blocks = cfg_.mb_receive_blocks;
    ml.info_networks = cfg_.mb_info_networks;
    ml.cyclic_jobs = cfg_.mb_cyclic_jobs;
    ml.in_base = cfg_.mb_input.index;
    ml.out_base = cfg_.mb_output.index;
    mailbox_backend_.reset(new EngineMailboxBackend(static_cast<unsigned>(s.networks.size())));
    mailboxes_.reset(new Mailboxes(ml, *mailbox_backend_));
    // The words the mailboxes change on their own stay out of the Modbus
    // trace's change filter: the keepalives and the two clock words.
    std::vector<uint16_t> keepalives, clocks;
    for (unsigned j = 0; j < ml.cyclic_jobs; ++j) keepalives.push_back(static_cast<uint16_t>(ml.keepalive(j) / 2));
    if (ml.receive) clocks.push_back(static_cast<uint16_t>((ml.receive_block() + 8) / 2));
    if (ml.cyclic_jobs) clocks.push_back(static_cast<uint16_t>(ml.cyclic_table() / 2));
    modbus_trace_.set_ignored(std::move(keepalives), std::move(clocks));
    // The network info blocks and the cyclic job table, one after the other
    // at the end of the input area: a program that only reads them (the
    // info blocks) uses the mailboxes too.
    image_.watch_reads(ml.info(0), ml.in_base + ml.input_bytes() - ml.info(0));
    log_info("bridge mailboxes: %u request mailbox(es) at input byte %u and output byte %u, receive mailbox %s "
             "(%u block(s)), network info for %u network(s), %u cyclic job(s); %u input and %u output bytes",
             ml.requests, ml.in_base, ml.out_base, ml.receive ? "on" : "off", ml.receive ? ml.receive_blocks : 0,
             ml.info_networks, ml.cyclic_jobs,
             ml.input_bytes(), ml.output_bytes());
  }
  sessions_ended_.assign(s.networks.size(), 0);
#if CANWORKS_WITH_CANOPEN
  for (unsigned n = 0; n < s.networks.size(); ++n)
    sessions_ended_[n] = canopen_plugin::HostRequests::instance().sessions_ended(n);
#endif
  // Outputs are off until the first write: with "safe" they are the safe
  // values from the start (modbus-bridge "Safe values at start and clean
  // stop"); the loop's first push sends them.
  if (cfg_.on_client_loss == BridgeConfig::Loss::Safe) write_safe_outputs();
  first_out_version_ = image_.take_outputs(out_copy_.data(), ~0ull);
  zero_pending_ = false;
  outputs_seen_ = ~0ull;
  canopen_plugin::set_outputs_enabled(!cfg_.plc_link || cfg_.on_client_loss == BridgeConfig::Loss::Safe);

  engine_->start();
  if (!server_.start(sc, err)) {
    log_error("%s; canworks-bridge not started", err.c_str());
    engine_->stop();
    return false;
  }
  log_info("canworks-bridge: config %s, protocols %s; Modbus TCP on %s (unit %u, word order %s), %zu input bytes, "
           "%zu output bytes; watchdog %u ms, on client loss %s; map hash 0x%08x%s",
           config_path.c_str(), canopen_plugin::built_in_protocols().c_str(), cfg_.listen.c_str(), cfg_.unit_id,
           cfg_.low_first ? "low_first" : "high_first", image_.input_size(), image_.output_size(), cfg_.watchdog_ms,
           loss_name(cfg_.on_client_loss), map_hash_,
           cfg_.plc_link ? " (PLC link)" : "");
  started_ = now;
  stop_ = false;
  thread_ = std::thread(&BridgeHost::loop, this);
  running_ = true;
  write_marker();
  return true;
}

std::string BridgeHost::marker_path() const { return dir_of(config_path_) + "/.canworks/running"; }

void BridgeHost::write_marker() {
  std::string why;
  if (!write_file(marker_path(), version_ + "\n", &why))
    log_warn("canworks-bridge: %s; an unclean stop of this run will not be reported", why.c_str());
}

void BridgeHost::stop() {
  if (!running_) return;
  if (cfg_.on_client_loss == BridgeConfig::Loss::Safe) {
    // The Modbus server stops first: a PLC that keeps writing while the
    // bridge stops would put its own values over the safe ones before the
    // networks send them (hardware check of add-safe-output-values 5.2).
    server_.stop();
    {
      std::lock_guard<std::mutex> lock(exchange_mu_);
      write_safe_outputs();
      canopen_plugin::set_outputs_enabled(true);
      push_outputs();
    }
    log_info("canworks-bridge: stopping; outputs at their safe values for %lld ms first (on_client_loss safe)",
             static_cast<long long>(safe_stop_wait_.count()));
    std::this_thread::sleep_for(safe_stop_wait_);
  }
  stop_ = true;
  if (thread_.joinable()) thread_.join();
  mailboxes_.reset();
  mailbox_backend_.reset();
  server_.stop();
  engine_->stop();
  canopen_plugin::set_outputs_enabled(true);
  running_ = false;
  if (::unlink(marker_path().c_str()) == 0) sync_dir(dir_of(marker_path()));
}

std::vector<uint8_t> BridgeHost::sent_outputs() const {
  std::lock_guard<std::mutex> lock(exchange_mu_);
  return g_image ? g_image->out : std::vector<uint8_t>();
}

void BridgeHost::push_outputs() {
  uint64_t v = image_.take_outputs(g_image->out.data(), outputs_seen_);
  if (v == outputs_seen_) return;
  outputs_seen_ = v;
  engine_->cycle_end(*g_image);
}

void BridgeHost::on_write() {
  std::lock_guard<std::mutex> lock(exchange_mu_);
  Clock::time_point now = Clock::now();
  if (cfg_.plc_link) {
    uint32_t seen = 0;
    ByteImage::Link link = image_.link_now(&seen);
    if (link == ByteImage::Link::kStopped) {
      link_off(OutputState::kPlcStopped, now);
      return;
    }
    if (link == ByteImage::Link::kMismatch) {
      if (!mismatch_logged_ || seen != mismatch_seen_)
        log_error("PLC program built for map 0x%08x, bridge serves 0x%08x: outputs stay off (rebuild and upload the "
                  "program after saving the config, or start the bridge with the config the program was built for)",
                  seen, map_hash_);
      mismatch_logged_ = true;
      mismatch_seen_ = seen;
      link_off(OutputState::kMismatch, now);
      return;
    }
    mismatch_logged_ = false;
  }
  if (supervisor_->write(now)) leave_off("a client wrote");
  push_outputs();
}

void BridgeHost::link_off(OutputState why, Clock::time_point now) {
  OutputState was = supervisor_->state();
  if (was == why || was == OutputState::kIdle) return;
  supervisor_->link_off(why);
  if (was == OutputState::kRunning) enter_off(why, now);
}

void BridgeHost::end_program_resources(const char* why) {
  if (!mailboxes_) return;
  unsigned n = mailboxes_->end_all(why);
  if (n) log_info("bridge mailboxes: %u operation(s), receiver(s) and cyclic job(s) of the program ended (%s)", n, why);
}

void BridgeHost::enter_off(OutputState why, Clock::time_point now) {
  // Idle turns the outputs off too, and a mailbox frame or SDO write is an
  // output: the program's mailbox resources end in every off state.
  end_program_resources(why == OutputState::kIdle         ? "idle"
                        : why == OutputState::kPlcStopped ? "the PLC stopped"
                        : why == OutputState::kMismatch   ? "the program was built for another map"
                                                          : "the watchdog");
  const char* reason = why == OutputState::kIdle         ? "the control block's idle command"
                       : why == OutputState::kPlcStopped ? "the PLC link header (the PLC stopped)"
                       : why == OutputState::kMismatch   ? "the PLC link header (another map hash)"
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
    case BridgeConfig::Loss::Safe: {
      log_warn("outputs off by %s: outputs set to their safe values (%zu set, the others 0) and kept sent "
               "(on_client_loss safe)",
               reason, cfg_.safe_values.size());
      write_safe_outputs();
      canopen_plugin::set_outputs_enabled(true);
      push_outputs();
      return;
    }
    case BridgeConfig::Loss::Preop: {
      log_warn("outputs off by %s: RPDOs and transmit messages stopped, output image cleared, nodes sent to "
               "pre-operational (on_client_loss preop)",
               reason);
      canopen_plugin::set_outputs_enabled(false);
      clear_outputs();
      all_nodes("preop");
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

void BridgeHost::write_safe_outputs() {
  for (const ImageUse& u : data_outputs_)
    if (u.loc.index + u.nbytes <= safe_out_.size()) image_.write_outputs(u.loc.index, &safe_out_[u.loc.index], u.nbytes);
}

void BridgeHost::leave_off(const char* why) {
  zero_pending_ = false;
  // Hold never turned them off, but a PLC link bridge starts with them off.
  canopen_plugin::set_outputs_enabled(true);
  if (cfg_.on_client_loss == BridgeConfig::Loss::Preop) all_nodes("start");
  log_info("outputs on again: %s", why);
}

void BridgeHost::all_nodes(const char* command) {
#if CANWORKS_WITH_CANOPEN
  for (unsigned n = 0; n < is_master_.size(); ++n)
    if (is_master_[n] && !canopen_plugin::HostRequests::instance().nmt(n, 0, command, "the client loss (on_client_loss preop)"))
      log_warn("network %u: NMT %s to all nodes not sent (its bus is down or its commands wait)", n, command);
#else
  (void)command;
#endif
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
        if (!canopen_plugin::HostRequests::instance().nmt(req.network, req.node, nmt_command(req.command)))
          result = kCtrlRefused;
#endif
        break;
    }
  }
  if (req.command != kCmdNone || result != kCtrlOk)
    log_info("Modbus control block: command %u, network %u, node %u (counter %u): result %u%s", req.command,
             req.network, req.node, req.counter, result,
             result == kCtrlRefused ? " (refused: the network's bus is down, or 16 of its commands wait)" : "");
  control_.handled(req.counter, result);
}

void BridgeHost::take_baselines(const uint8_t* out, bool wrote_control, bool wrote_sdo) {
  if (wrote_control) {
    control_known_ = true;
    if (control_.baseline(out + cfg_.control_location.index))
      log_info("Modbus control block: counter %u was already there when the bridge started: its command is not run "
               "(result 6)",
               control_.counter());
  }
  if (wrote_sdo) {
    sdo_known_ = true;
    const uint8_t* req = out + cfg_.sdo_request.index;
    if (sdo_->baseline(req))
      log_info("Modbus SDO bridge: request %u was already there when the bridge started: not sent (abort 0x%08X)",
               get_be16(req), kAbortLocalControl);
  }
}

void BridgeHost::read_bus_states(Clock::time_point now) {
  if (now < next_bus_read_) return;
  next_bus_read_ = now + std::chrono::milliseconds(100);
  auto* api = static_cast<const canworks_can_api_v1*>(canworks_can_api_table(1));
  std::vector<std::string> down;
  const auto& nets = engine_->set().networks;
  for (unsigned n = 0; api && n < nets.size(); ++n) {
    canworks_can_bus_info b{};
    uint16_t err = 0;
    // 3 bus-off, 4 interface down or missing; error-warning and
    // error-passive still carry frames.
    if (api->bus_info(static_cast<uint8_t>(n), &b, &err) == 0 && b.state >= 3)
      down.push_back(nets[n].network.empty() ? std::to_string(n) : nets[n].network);
  }
  bus_not_ok_ = !down.empty();
  std::lock_guard<std::mutex> lock(bus_mu_);
  bus_down_.swap(down);
}

void BridgeHost::write_blocks(Clock::time_point now) {
  std::vector<uint8_t>& in = g_image->in;
  if (cfg_.plc_link && in.size() >= canopen_plugin::kOpenplcHashBytes) {
    put_be16(&in[0], static_cast<uint16_t>(map_hash_ >> 16));
    put_be16(&in[2], static_cast<uint16_t>(map_hash_));
  }
  if (cfg_.has_status) {
    auto ticks = std::chrono::duration_cast<std::chrono::milliseconds>(now - started_).count() / 100;
    encode_status(&in[cfg_.status_location.index], supervisor_->state(), server_.clients(),
                  static_cast<uint16_t>(ticks), control_,
                  static_cast<uint8_t>((unclean_start_ ? kStatusUncleanStart : 0) | (bus_not_ok_ ? kStatusBusNotOk : 0)));
  }
#if CANWORKS_WITH_CANOPEN
  for (const auto& l : cfg_.live_lists)
    encode_live_list(&in[l.location.index], canopen_plugin::HostRequests::instance().operational(l.network));
#endif
  if (sdo_) sdo_->encode(&in[cfg_.sdo_response.index]);
}

void BridgeHost::loop() {
  canopen_plugin::set_thread_log_prefix("");
  canopen_plugin::ThreadProgress progress("bridge loop thread");
  uint64_t ctl_seen = ~0ull;
  auto next = Clock::now();
  while (!stop_) {
    progress.beat();
    {
      std::lock_guard<std::mutex> lock(exchange_mu_);
      Clock::time_point now = Clock::now();
      engine_->cycle_start(*g_image);
      read_bus_states(now);
      if (supervisor_->tick(now)) enter_off(OutputState::kWatchdog, now);
      if (zero_pending_ && now >= zero_until_) {
        zero_pending_ = false;
        canopen_plugin::set_outputs_enabled(false);
      }
      // Asked before the snapshot, so a write seen here is in it.
      bool wrote_control = !control_known_ && cfg_.has_control &&
                           image_.client_wrote(cfg_.control_location.index, 2);
      bool wrote_sdo = !sdo_known_ && sdo_ && image_.client_wrote(cfg_.sdo_request.index, 2);
      if (mailboxes_)
        for (unsigned m = 0; m < mailboxes_->layout().requests; ++m)
          if (!(mb_written_ >> m & 1u) && image_.client_wrote(mailboxes_->layout().request(m), 4))
            mb_written_ |= 1u << m;
      ctl_seen = image_.take_outputs(out_copy_.data(), ctl_seen);
      take_baselines(out_copy_.data(), wrote_control, wrote_sdo);
      if (control_known_) service_control(out_copy_.data(), now);
      if (sdo_ && sdo_known_) sdo_->service(out_copy_.data() + cfg_.sdo_request.index, g_sdo_backend);
      write_blocks(now);
      if (mailboxes_) {
        // Requests count only while the outputs run: a stopped or
        // mismatched program's words are not taken.
        bool live = ctl_seen != first_out_version_ && supervisor_->running();
        mailboxes_->service(live ? out_copy_.data() : nullptr, g_image->in.data(), now, mb_written_);
        if (uint32_t stalled = mailboxes_->take_stalled())
          log_warn("bridge receive mailbox: receivers 0x%08x closed: their records were not taken within 1 s (a "
                   "block that is no longer called, or a program that does not read them)",
                   stalled);
#if CANWORKS_WITH_CANOPEN
        // A CANopen session restart ends that network's resources (the
        // CAN receivers on its port would stay open across it).
        for (unsigned n = 0; n < sessions_ended_.size(); ++n) {
          uint32_t ended = canopen_plugin::HostRequests::instance().sessions_ended(n);
          if (ended == sessions_ended_[n]) continue;
          sessions_ended_[n] = ended;
          if (unsigned k = mailboxes_->end_network(n))
            log_info("bridge mailboxes: %u operation(s), receiver(s) and cyclic job(s) of network %u ended (its "
                     "CANopen session restarted)",
                     k, n);
        }
#endif
        if (unsigned f = mailboxes_->take_forgotten())
          log_warn("bridge cyclic jobs: %u job(s) stopped: their block stopped calling (no keepalive for 1 s)", f);
      }
      image_.publish_inputs(g_image->in.data(), g_image->in.size());
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
  else if (st == OutputState::kPlcStopped)
    cJSON_AddStringToObject(b, "reason", "plc_stopped");
  else if (st == OutputState::kMismatch)
    cJSON_AddStringToObject(b, "reason", "map_mismatch");
  else
    cJSON_AddNullToObject(b, "reason");
  char hash[16];
  std::snprintf(hash, sizeof(hash), "0x%08x", map_hash_);
  cJSON_AddStringToObject(b, "map_hash", hash);
  cJSON_AddBoolToObject(b, "plc_link", cfg_.plc_link);
  cJSON_AddStringToObject(b, "on_client_loss", loss_name(cfg_.on_client_loss));
  cJSON_AddStringToObject(b, "listen", cfg_.listen.c_str());
  cJSON_AddNumberToObject(b, "unit_id", cfg_.unit_id);
  cJSON_AddNumberToObject(b, "input_bytes", static_cast<double>(image_.input_size()));
  cJSON_AddNumberToObject(b, "output_bytes", static_cast<double>(image_.output_size()));
  cJSON_AddNumberToObject(b, "watchdog_ms", cfg_.watchdog_ms);
  cJSON_AddStringToObject(b, "last_stop", last_stop_.empty() ? "unknown" : last_stop_.c_str());
  {
    std::lock_guard<std::mutex> bl(bus_mu_);
    cJSON* down = cJSON_AddArrayToObject(b, "bus_not_ok");
    for (const auto& n : bus_down_) cJSON_AddItemToArray(down, cJSON_CreateString(n.c_str()));
  }
  // The clients with their counters, and the recently closed connections
  // (modbus-bridge "Client counters", "Recently closed clients").
  cJSON* clients = cJSON_AddArrayToObject(b, "clients");
  for (const ClientInfo& c : server_.client_list()) cJSON_AddItemToArray(clients, client_json(c));
  cJSON* closed = cJSON_AddArrayToObject(b, "closed_clients");
  uint64_t now_us = utc_now_us();
  for (const ClosedClient& c : server_.closed_list()) {
    cJSON* o = client_json(c.info);
    cJSON_AddStringToObject(o, "reason", c.reason.c_str());
    cJSON_AddNumberToObject(o, "closed_us", static_cast<double>(c.closed_us));
    cJSON_AddNumberToObject(o, "ago_s", static_cast<double>((now_us - std::min(now_us, c.closed_us)) / 1000000));
    cJSON_AddNumberToObject(o, "connected_s",
                            static_cast<double>((c.closed_us - std::min(c.closed_us, c.info.connected_us)) / 1000000));
    cJSON_AddItemToArray(closed, o);
  }
  if (size_t n = modbus_trace_.sessions()) cJSON_AddNumberToObject(b, "modbus_traces", static_cast<double>(n));
  // Mailbox use since the start (modbus-bridge-mailboxes "Mailbox use in the
  // status"): diag says when nothing has used them.
  if (mailboxes_) {
    cJSON* mb = cJSON_AddObjectToObject(b, "mailboxes");
    cJSON_AddNumberToObject(mb, "operations", static_cast<double>(mailboxes_->operations()));
    cJSON_AddNumberToObject(mb, "receivers_opened", static_cast<double>(mailboxes_->receivers_opened()));
    cJSON_AddNumberToObject(mb, "info_reads", static_cast<double>(image_.watched_reads()));
  }
  if (supervisor_ && cfg_.watchdog_ms && st == OutputState::kRunning)
    cJSON_AddNumberToObject(b, "watchdog_left_ms", static_cast<double>(supervisor_->left_ms(Clock::now())));
  // CiA 309-3 gateway sessions (modbus-bridge "CiA 309-3 gateway and the
  // output watchdog"): listed here, never counted as Modbus writers.
  if (cJSON* gw = engine_ ? engine_->cia309_status() : nullptr) {
    cJSON* sessions = cJSON_DetachItemFromObjectCaseSensitive(gw, "sessions");
    cJSON_AddItemToObject(b, "cia309_sessions", sessions ? sessions : cJSON_CreateArray());
    cJSON_Delete(gw);
  }
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


// The uploaded "canworks.json" is the running config file, whatever its name.
std::string BridgeHost::staged_path(const std::string& name) const {
  return name == "canworks.json" ? base_of(config_path_) : name;
}

// ---- Modbus trace (modbus_trace_start, _fetch, _stop) ----

bool BridgeHost::modbus_trace_op(uint64_t client, const std::string& id, const std::string& op, const cJSON* req,
                                 std::string& out) {
  using canopen_plugin::diag_error;
  using canopen_plugin::diag_ok;
  auto now = ModbusTrace::Clock::now();
  if (op == "modbus_trace_start") {
    const cJSON* co = cJSON_GetObjectItemCaseSensitive(req, "changes_only");
    if (co && !cJSON_IsBool(co)) {
      out += diag_error(id, "field 'changes_only' must be true or false");
      return true;
    }
    AddressList clients;
    const cJSON* cl = cJSON_GetObjectItemCaseSensitive(req, "clients");
    if (cl && !cJSON_IsArray(cl)) {
      out += diag_error(id, "field 'clients' must be a list of addresses or prefixes");
      return true;
    }
    const cJSON* a = nullptr;
    cJSON_ArrayForEach(a, cl) {
      std::string err;
      if (!cJSON_IsString(a) || !clients.add(a->valuestring, err)) {
        out += diag_error(id, err.empty() ? "field 'clients' must be a list of addresses or prefixes" : "clients: " + err);
        return true;
      }
    }
    bool changes = !co || cJSON_IsTrue(co);
    bool had = modbus_trace_.sessions() > 0;
    uint64_t next = modbus_trace_.start(client, changes, clients, now);
    log_info("diagnostics: Modbus trace started (%s%s)%s", changes ? "changes only" : "every request",
             cl && cJSON_GetArraySize(cl) ? ", some clients" : "", had ? "" : "; recording Modbus requests");
    cJSON* res = cJSON_CreateObject();
    cJSON_AddNumberToObject(res, "next", static_cast<double>(next));
    char hash[16];
    std::snprintf(hash, sizeof(hash), "0x%08x", map_hash_);
    cJSON_AddStringToObject(res, "map_hash", hash);
    cJSON_AddNumberToObject(res, "buffer_bytes", static_cast<double>(modbus_trace_.capacity()));
    cJSON_AddNumberToObject(res, "header_size", static_cast<double>(kModbusTraceHeader));
    cJSON_AddStringToObject(res, "listen", cfg_.listen.c_str());
    cJSON_AddNumberToObject(res, "port", server_.port());
    cJSON_AddNumberToObject(res, "unit_id", cfg_.unit_id);
    cJSON_AddBoolToObject(res, "changes_only", changes);
    out += diag_ok(id, res);
    return true;
  }
  if (op == "modbus_trace_fetch") {
    const cJSON* af = cJSON_GetObjectItemCaseSensitive(req, "after");
    if (!cJSON_IsNumber(af) || af->valuedouble < 0 || af->valuedouble > 9007199254740992.0) {
      out += diag_error(id, "field 'after' must be a sequence number");
      return true;
    }
    size_t max = ModbusTrace::kFetchDefault;
    if (const cJSON* m = cJSON_GetObjectItemCaseSensitive(req, "max")) {
      if (!cJSON_IsNumber(m) || m->valuedouble < 1 || m->valuedouble > double(ModbusTrace::kFetchMax)) {
        out += diag_error(id, "field 'max' must be 1-4000");
        return true;
      }
      max = static_cast<size_t>(m->valuedouble);
    }
    ModbusTrace::Fetch f;
    if (!modbus_trace_.fetch(client, static_cast<uint64_t>(af->valuedouble), max, now, f)) {
      out += diag_error(id, "no Modbus trace running (send modbus_trace_start)");
      return true;
    }
    cJSON* res = cJSON_CreateObject();
    cJSON_AddNumberToObject(res, "count", static_cast<double>(f.count));
    cJSON_AddNumberToObject(res, "next", static_cast<double>(f.next));
    cJSON_AddBoolToObject(res, "more", f.more);
    cJSON_AddNumberToObject(res, "lost", static_cast<double>(f.lost));
    cJSON_AddStringToObject(res, "records", base64(f.data).c_str());
    out += diag_ok(id, res);
    return true;
  }
  if (op == "modbus_trace_stop") {
    bool had = modbus_trace_.stop(client);
    if (had) log_info("diagnostics: Modbus trace stopped");
    cJSON* res = cJSON_CreateObject();
    cJSON_AddBoolToObject(res, "stopped", had);
    out += diag_ok(id, res);
    return true;
  }
  return false;
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
  // Room for the staged copy, the files put in place and the backup of the
  // previous ones, plus the generated files; a full disk is refused before
  // anything stops.
  long long need = 1 << 20;
  for (const auto& f : files) need += 3 * static_cast<long long>(f.second.size());
  long long have = free_bytes(dir_of(config_path_));
  if (have >= 0 && have < need) {
    why = "not enough space in " + dir_of(config_path_) + ": " + std::to_string(have / 1024) +
          " KiB free, the upload needs about " + std::to_string(need / 1024) + " KiB; the running config stays";
    return 0;
  }
  for (const auto& f : files) {
    std::string rel = staged_path(f.first);
    std::string err;
    if (!write_file(stage + "/" + rel, f.second, &err)) {
      why = "cannot stage " + f.first + ": " + err + "; the running config stays";
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

bool BridgeHost::apply_upload() {
  std::vector<std::string> staged;
  {
    std::lock_guard<std::mutex> lock(upload_mu_);
    if (!upload_pending_) return true;
    staged = staged_;
  }
  const std::string dir = dir_of(config_path_);
  const std::string stage = dir + "/.canworks-upload";
  const std::string backup = dir + "/.canworks-previous";
  std::string path = config_path_, version = version_;
  stop();
  remove_tree(backup);
  // Every file is replaced atomically (write_file), the previous ones kept
  // in the backup first; a step that fails puts back what was replaced.
  std::vector<std::string> created, replaced;
  std::string failed;
  for (const auto& rel : staged) {
    if (!exists(dir + "/" + rel)) {
      created.push_back(rel);
    } else if (!copy_file(dir + "/" + rel, backup + "/" + rel, &failed)) {
      break;
    }
  }
  if (failed.empty()) {
    for (const auto& rel : staged) {
      if (!copy_file(stage + "/" + rel, dir + "/" + rel, &failed)) break;
      replaced.push_back(rel);
    }
  }
  remove_tree(stage);
  auto put_back = [&] {
    for (const auto& rel : replaced) {
      if (std::find(created.begin(), created.end(), rel) != created.end()) {
        ::unlink((dir + "/" + rel).c_str());
        sync_dir(dir_of(dir + "/" + rel));
      } else {
        std::string err;
        if (!copy_file(backup + "/" + rel, dir + "/" + rel, &err))
          log_error("canworks-bridge: cannot put back %s: %s", rel.c_str(), err.c_str());
      }
    }
  };
  std::string result = "started", detail;
  bool ok = true;
  if (!failed.empty()) {
    log_error("canworks-bridge: the uploaded files could not be put in place (%s); going back to the previous config",
              failed.c_str());
    put_back();
    result = "restored";
    detail = "the uploaded files could not be put in place (" + failed + "); the previous config runs again";
    if (!start(path, version.c_str())) {
      detail = "the uploaded files could not be put in place (" + failed + "), and the previous config did not start";
      ok = false;
    }
  } else if (!start(path, version.c_str())) {
    log_error("canworks-bridge: the uploaded config did not start; going back to the previous one");
    put_back();
    result = "restored";
    detail = "the uploaded config did not start (see the log); the previous config runs again";
    if (!start(path, version.c_str())) {
      detail = "the uploaded config did not start, nor did the previous one";
      ok = false;
    }
  } else {
    detail = "the uploaded config runs";
  }
  if (!ok) log_error("canworks-bridge: neither the uploaded nor the previous config started; exiting so the service "
                     "starts the bridge again");
  std::lock_guard<std::mutex> lock(upload_mu_);
  upload_pending_ = false;
  upload_result_ = result;
  upload_detail_ = detail;
  return ok;
}

}  // namespace canworks_bridge
