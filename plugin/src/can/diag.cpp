#include "diag.h"

#if CANWORKS_WITH_CANOPEN
#include "sim_engine.h"
#endif

#include <algorithm>
#include <arpa/inet.h>
#include <iterator>
#include <cctype>
#include <cerrno>
#include <cstdlib>
#include <cstring>
#include <fcntl.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <poll.h>
#include <pthread.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <time.h>
#include <unistd.h>

#include "cJSON.h"
#include "log.h"
#include "sha256.h"
#include "trace_capture.h"

namespace canopen_plugin {

namespace {

std::string print(cJSON* obj) {
  char* text = cJSON_PrintUnformatted(obj);
  std::string s = text ? text : "{}";
  cJSON_free(text);
  return s;
}

// The answer object with the request's id (raw JSON) put back in.
std::string answer_line(const std::string& id, cJSON* obj) {
  if (!id.empty()) {
    cJSON* idv = cJSON_Parse(id.c_str());
    if (idv) cJSON_AddItemToObject(obj, "id", idv);
  }
  std::string s = print(obj);
  cJSON_Delete(obj);
  return s + "\n";
}

// An unsigned field given as a JSON number or as a string ("0x2000", "8192").
bool get_uint(const cJSON* obj, const char* key, uint64_t max, uint64_t& out, std::string& why) {
  const cJSON* item = cJSON_GetObjectItemCaseSensitive(obj, key);
  if (!item) {
    why = std::string("missing field '") + key + "'";
    return false;
  }
  if (cJSON_IsNumber(item)) {
    double d = item->valuedouble;
    if (d < 0 || d > double(max) || d != double(uint64_t(d))) {
      why = std::string("field '") + key + "' is out of range";
      return false;
    }
    out = uint64_t(d);
    return true;
  }
  if (cJSON_IsString(item) && item->valuestring[0]) {
    errno = 0;
    char* end = nullptr;
    unsigned long long v = std::strtoull(item->valuestring, &end, 0);
    if (errno || *end || item->valuestring[0] == '-' || v > max) {
      why = std::string("field '") + key + "' is not a number in range";
      return false;
    }
    out = v;
    return true;
  }
  why = std::string("field '") + key + "' must be a number";
  return false;
}

bool parse_hex(const std::string& text, std::vector<uint8_t>& out) {
  std::string digits;
  for (char c : text)
    if (c != ' ') digits += c;
  if (digits.empty() || digits.size() % 2) return false;
  out.clear();
  for (size_t i = 0; i < digits.size(); i += 2) {
    char pair[3] = {digits[i], digits[i + 1], 0};
    if (!std::isxdigit(static_cast<unsigned char>(pair[0])) || !std::isxdigit(static_cast<unsigned char>(pair[1])))
      return false;
    out.push_back(static_cast<uint8_t>(std::strtoul(pair, nullptr, 16)));
  }
  return true;
}

bool configured(const Config& cfg, unsigned id) {
  for (const auto& n : cfg.nodes)
    if (n.node_id == id) return true;
  return false;
}

}  // namespace

std::string diag_ok(const std::string& id, cJSON* result) {
  cJSON* obj = cJSON_CreateObject();
  cJSON_AddBoolToObject(obj, "ok", true);
  cJSON_AddItemToObject(obj, "result", result ? result : cJSON_CreateObject());
  return answer_line(id, obj);
}

std::string diag_error(const std::string& id, const std::string& message) {
  cJSON* obj = cJSON_CreateObject();
  cJSON_AddBoolToObject(obj, "ok", false);
  cJSON_AddStringToObject(obj, "error", message.c_str());
  return answer_line(id, obj);
}

std::string hex_bytes(const std::vector<uint8_t>& data) {
  static const char* digits = "0123456789ABCDEF";
  std::string s;
  for (size_t i = 0; i < data.size(); ++i) {
    if (i) s += ' ';
    s += digits[data[i] >> 4];
    s += digits[data[i] & 15];
  }
  return s;
}

// ---------------------------------------------------------------------------
// DiagHub

DiagHub::DiagHub(const Config& cfg, std::string version)
    : cfg_(cfg), version_(std::move(version)), start_(std::chrono::steady_clock::now()) {
  if (pipe2(pipe_, O_CLOEXEC | O_NONBLOCK) != 0) pipe_[0] = pipe_[1] = -1;
}

DiagHub::~DiagHub() {
  for (int fd : pipe_)
    if (fd >= 0) close(fd);
}

double DiagHub::uptime_s() const {
  return std::chrono::duration<double>(std::chrono::steady_clock::now() - start_).count();
}

void DiagHub::wake() {
  if (pipe_[1] < 0) return;
  char b = 1;
  ssize_t r = write(pipe_[1], &b, 1);
  (void)r;  // a full pipe is already a wake-up
}

void DiagHub::attach() { attached_.store(true, std::memory_order_release); }

void DiagHub::detach() {
  set_operational("");
  set_used_ids({});
  {
    std::lock_guard<std::mutex> lock(mutex_);
    attached_.store(false, std::memory_order_release);
    for (auto& t : taken_) answers_.emplace_back(t.first, offline_answer(t.second));
    taken_.clear();
    for (auto& r : queue_) answers_.emplace_back(r.seq, offline_answer(r));
    queue_.clear();
  }
  wake();
}

void DiagHub::take(std::vector<DiagRequest>& out) {
  std::lock_guard<std::mutex> lock(mutex_);
  for (auto& r : queue_) {
    taken_[r.seq] = r;
    out.push_back(std::move(r));
  }
  queue_.clear();
}

void DiagHub::answer(uint64_t seq, const std::string& line) {
  {
    std::lock_guard<std::mutex> lock(mutex_);
    // Answered already by detach(): drop.
    if (!taken_.erase(seq)) return;
    answers_.emplace_back(seq, line);
  }
  wake();
}

uint64_t DiagHub::submit(DiagRequest r) {
  std::string offline;
  uint64_t seq;
  {
    std::lock_guard<std::mutex> lock(mutex_);
    seq = next_seq_++;
    r.seq = seq;
    if (attached_.load(std::memory_order_acquire)) {
      queue_.push_back(std::move(r));
      return seq;
    }
    answers_.emplace_back(seq, offline_answer(r));
  }
  wake();
  return seq;
}

void DiagHub::take_answers(std::vector<std::pair<uint64_t, std::string>>& out) {
  if (pipe_[0] >= 0) {
    char buf[64];
    while (read(pipe_[0], buf, sizeof buf) > 0) {
    }
  }
  std::lock_guard<std::mutex> lock(mutex_);
  for (auto& a : answers_) out.push_back(std::move(a));
  answers_.clear();
}

void DiagHub::set_operational(const std::string& label) {
  std::lock_guard<std::mutex> lock(state_mutex_);
  if (operational_ != label) operational_ = label;
}

std::string DiagHub::operational() const {
  std::lock_guard<std::mutex> lock(state_mutex_);
  return operational_;
}

bool DiagHub::ids_due() {
  auto now = std::chrono::steady_clock::now();
  std::lock_guard<std::mutex> lock(state_mutex_);
  if (ids_at_ != std::chrono::steady_clock::time_point{} && now - ids_at_ < std::chrono::seconds(1)) return false;
  ids_at_ = now;
  return true;
}

void DiagHub::set_used_ids(std::map<uint32_t, std::string> ids) {
  std::lock_guard<std::mutex> lock(state_mutex_);
  used_ids_.swap(ids);
  if (used_ids_.empty()) ids_at_ = {};
}

std::string DiagHub::used_id(uint32_t id, bool ext) const {
  std::lock_guard<std::mutex> lock(state_mutex_);
  auto it = used_ids_.find(id_use_key(id, ext));
  return it == used_ids_.end() ? "" : it->second;
}

void DiagHub::set_send_jobs(const std::string& json_array) {
  std::lock_guard<std::mutex> lock(state_mutex_);
  send_jobs_ = json_array;
}

void DiagHub::add_tx_status(cJSON* res) const {
  std::lock_guard<std::mutex> lock(state_mutex_);
  cJSON* jobs = cJSON_Parse(send_jobs_.c_str());
  cJSON_AddItemToObject(res, "send_jobs", jobs ? jobs : cJSON_CreateArray());
  cJSON* sw = cJSON_AddObjectToObject(res, "bitrate_sweep");
  cJSON_AddBoolToObject(sw, "running", sweep_pending_ || sweep_running_);
  if (raw_status_) cJSON_AddItemToObject(res, "raw", raw_status_());
  if (host_status_)
    if (cJSON* part = host_status_()) cJSON_AddItemToObject(res, "bridge", part);
}

bool DiagHub::request_sweep(const SweepRequest& req) {
  std::lock_guard<std::mutex> lock(state_mutex_);
  if (sweep_pending_ || sweep_running_) return false;
  sweep_pending_ = true;
  sweep_ever_ = true;
  sweep_req_ = req;
  sweep_req_.cancel = std::make_shared<std::atomic<bool>>(false);
  sweep_req_.stopped_by = std::make_shared<std::string>();
  sweep_pg_ = SweepProgress();
  std::vector<unsigned> rates = req.rates_kbit;
  if (rates.empty()) rates.assign(std::begin(kSweepRates), std::end(kSweepRates));
  sweep_pg_.total = static_cast<unsigned>(rates.size()) * std::max(1u, req.rounds);
  sweep_partial_.clear();
  for (unsigned k : rates) {
    SweepRate r;
    r.bitrate_kbit = k;
    sweep_partial_.push_back(r);
  }
  sweep_result_ = SweepResult();
  sweep_finished_at_.clear();
  return true;
}

bool DiagHub::sweep_pending() const {
  std::lock_guard<std::mutex> lock(state_mutex_);
  return sweep_pending_;
}

bool DiagHub::sweep_busy() const {
  std::lock_guard<std::mutex> lock(state_mutex_);
  return sweep_pending_ || sweep_running_;
}

bool DiagHub::stop_sweep(const std::string& peer) {
  std::lock_guard<std::mutex> lock(state_mutex_);
  if (!(sweep_pending_ || sweep_running_) || !sweep_req_.cancel) return false;
  if (!sweep_req_.cancel->load()) {
    *sweep_req_.stopped_by = peer;
    sweep_req_.cancel->store(true);
  }
  return true;
}

bool DiagHub::take_sweep(SweepRequest& out) {
  std::lock_guard<std::mutex> lock(state_mutex_);
  if (!sweep_pending_) return false;
  sweep_pending_ = false;
  sweep_running_ = true;
  out = sweep_req_;
  return true;
}

void DiagHub::sweep_progress(const SweepProgress& p) {
  std::lock_guard<std::mutex> lock(state_mutex_);
  sweep_pg_.rate_kbit = p.rate_kbit;
  sweep_pg_.round = p.round;
  sweep_pg_.done = p.done;
  sweep_pg_.total = p.total;
  if (p.results) sweep_partial_ = *p.results;
}

void DiagHub::sweep_done(const SweepResult& r) {
  std::lock_guard<std::mutex> lock(state_mutex_);
  sweep_running_ = false;
  sweep_result_ = r;
  sweep_partial_ = r.results;
  sweep_pg_.rate_kbit = 0;
  sweep_pg_.done = sweep_pg_.total;
  time_t t = time(nullptr);
  struct tm tm;
  gmtime_r(&t, &tm);
  char buf[32];
  strftime(buf, sizeof buf, "%Y-%m-%dT%H:%M:%SZ", &tm);
  sweep_finished_at_ = buf;
}

cJSON* DiagHub::sweep_status() const {
  std::lock_guard<std::mutex> lock(state_mutex_);
  cJSON* res = cJSON_CreateObject();
  const bool running = sweep_pending_ || sweep_running_;
  cJSON_AddBoolToObject(res, "running", running);
  cJSON_AddNumberToObject(res, "configured_kbit", cfg_.adapter.bitrate / 1000);
  if (!sweep_ever_) {
    cJSON_AddNullToObject(res, "verdict");
    return res;
  }
  if (running && sweep_pg_.rate_kbit)
    cJSON_AddNumberToObject(res, "rate_kbit", sweep_pg_.rate_kbit);
  else
    cJSON_AddNullToObject(res, "rate_kbit");
  cJSON_AddNumberToObject(res, "round", sweep_pg_.round);
  cJSON_AddNumberToObject(res, "done", sweep_pg_.done);
  cJSON_AddNumberToObject(res, "total", sweep_pg_.total);
  cJSON* list = cJSON_AddArrayToObject(res, "results");
  for (const auto& r : sweep_partial_) {
    cJSON* o = cJSON_CreateObject();
    cJSON_AddNumberToObject(o, "bitrate_kbit", r.bitrate_kbit);
    cJSON_AddNumberToObject(o, "frames", double(r.frames));
    cJSON_AddNumberToObject(o, "error_frames", double(r.error_frames));
    cJSON* ids = cJSON_AddArrayToObject(o, "ids");
    for (uint32_t id : r.ids) cJSON_AddItemToArray(ids, cJSON_CreateNumber(id));
    cJSON_AddItemToArray(list, o);
  }
  if (running) {
    cJSON_AddNullToObject(res, "verdict");
    return res;
  }
  const SweepResult& sr = sweep_result_;
  cJSON_AddStringToObject(res, "verdict", sweep_verdict_name(sr.verdict));
  if (sr.verdict == SweepVerdict::Detected) {
    cJSON_AddNumberToObject(res, "bitrate_kbit", sr.bitrate_kbit);
    cJSON_AddBoolToObject(res, "matches_config", sr.bitrate_kbit * 1000 == cfg_.adapter.bitrate);
  } else {
    cJSON_AddNullToObject(res, "bitrate_kbit");
  }
  cJSON* cand = cJSON_AddArrayToObject(res, "candidates");
  for (unsigned k : sr.candidates) cJSON_AddItemToArray(cand, cJSON_CreateNumber(k));
  if (sr.verdict == SweepVerdict::Failed) cJSON_AddStringToObject(res, "error", sr.error.c_str());
  cJSON_AddStringToObject(res, "finished_at", sweep_finished_at_.c_str());
  return res;
}

void diag_add_protocols(cJSON* res) {
  cJSON* p = cJSON_AddArrayToObject(res, "protocols");
  for (Protocol k : {Protocol::CANopen, Protocol::J1939, Protocol::None})
    if (protocol_built_in(k)) cJSON_AddItemToArray(p, cJSON_CreateString(protocol_name(k)));
}

std::string DiagHub::offline_answer(const DiagRequest& r) const {
  if (r.op != "status") return diag_error(r.id, "no bus");
  cJSON* res = cJSON_CreateObject();
  cJSON_AddStringToObject(res, "version", version_.c_str());
  cJSON_AddNumberToObject(res, "uptime_s", uptime_s());
  cJSON_AddStringToObject(res, "config_sha256", cfg_.file_sha256.c_str());
  cJSON_AddStringToObject(res, "network", cfg_.network.c_str());
  diag_add_protocols(res);
  cJSON_AddBoolToObject(res, "session", false);
  if (cfg_.is_plain()) {
    // A plain CAN network has no bus thread: this is its status at all times
    // (its raw path in "raw").
    cJSON_AddStringToObject(res, "protocol", "none");
    cJSON_AddBoolToObject(res, "simulated_network", cfg_.adapter.simulate);
    cJSON_AddBoolToObject(res, "simulation_forced", cfg_.adapter.simulation_forced);
    cJSON_AddBoolToObject(res, "listen_only", cfg_.adapter.listen_only);
    cJSON* b = cJSON_AddObjectToObject(res, "bus");
    cJSON_AddStringToObject(b, "interface", cfg_.adapter.simulate ? "simulated" : cfg_.adapter.interface.c_str());
    cJSON_AddNumberToObject(b, "bitrate", cfg_.adapter.bitrate);
    add_tx_status(res);
    cJSON* raw = cJSON_GetObjectItemCaseSensitive(res, "raw");
    cJSON_AddNumberToObject(b, "state", cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(raw, "running")) ? 1 : 0);
    return diag_ok(r.id, res);
  }
  if (cfg_.is_j1939()) {
    // The bus thread answers while it runs (j1939_network.h); this is before
    // it started or after it ended.
    cJSON_AddStringToObject(res, "protocol", "j1939");
    cJSON* b = cJSON_AddObjectToObject(res, "bus");
    cJSON_AddStringToObject(b, "interface", cfg_.adapter.interface.c_str());
    cJSON_AddNumberToObject(b, "state", 0);
    cJSON* j = cJSON_AddObjectToObject(res, "j1939");
    cJSON_AddNumberToObject(j, "state", static_cast<int>(J1939ClaimState::NoBus));
    cJSON_AddStringToObject(j, "state_name", "no bus");
    cJSON_AddNumberToObject(j, "address", kJ1939NullAddress);
    cJSON_AddStringToObject(j, "error", "not running");
    cJSON_AddArrayToObject(j, "ecus");
    cJSON_AddArrayToObject(j, "rx");
    cJSON_AddArrayToObject(j, "tx");
    cJSON_AddArrayToObject(j, "requests");
    return diag_ok(r.id, res);
  }
  if (cfg_.is_slave()) {
    cJSON_AddStringToObject(res, "role", "slave");
    cJSON* s = cJSON_AddObjectToObject(res, "slave");
    cJSON_AddNumberToObject(s, "node_id", cfg_.slave.lss ? 0 : cfg_.slave.node_id);
    cJSON_AddNumberToObject(s, "state", 0);
    cJSON_AddBoolToObject(s, "comm_ok", false);
    cJSON* b = cJSON_AddObjectToObject(res, "bus");
    cJSON_AddStringToObject(b, "interface", cfg_.adapter.interface.c_str());
    cJSON_AddNumberToObject(b, "state", 0);
    add_tx_status(res);
    return diag_ok(r.id, res);
  }
  cJSON* m = cJSON_AddObjectToObject(res, "master");
  cJSON_AddNumberToObject(m, "node_id", cfg_.master.node_id);
  cJSON_AddNumberToObject(m, "state", 0);
  cJSON_AddBoolToObject(res, "simulated_network", cfg_.adapter.simulate);
  cJSON_AddBoolToObject(res, "simulation_forced", cfg_.adapter.simulation_forced);
  cJSON* b = cJSON_AddObjectToObject(res, "bus");
  cJSON_AddStringToObject(b, "interface", cfg_.adapter.simulate ? "simulated" : cfg_.adapter.interface.c_str());
  cJSON_AddNumberToObject(b, "state", 0);
  cJSON* nodes = cJSON_AddArrayToObject(res, "nodes");
  for (const auto& n : cfg_.nodes) {
    cJSON* o = cJSON_CreateObject();
    cJSON_AddNumberToObject(o, "node_id", n.node_id);
    cJSON_AddStringToObject(o, "name", n.name.c_str());
    cJSON_AddNumberToObject(o, "state", 0);
    cJSON_AddBoolToObject(o, "status", false);
    cJSON_AddBoolToObject(o, "simulated", n.simulate);
    cJSON_AddBoolToObject(o, "sim_conflict", false);
    cJSON_AddItemToArray(nodes, o);
  }
  add_tx_status(res);
  return diag_ok(r.id, res);
}

// ---------------------------------------------------------------------------
// DiagServer

constexpr unsigned DiagServer::kMaxClients;
constexpr size_t DiagServer::kMaxLine;
constexpr size_t DiagServer::kMaxSendBuffer;
constexpr std::chrono::seconds DiagServer::kLoginTimeout;
constexpr std::chrono::minutes DiagServer::kAuthKeep;
constexpr unsigned DiagServer::kMaxSweepMs;
constexpr std::chrono::seconds DiagServer::kRetryListen;
constexpr std::chrono::seconds DiagServer::kLoginBackoff;
constexpr size_t DiagServer::kTraceFetchDefault;
constexpr size_t DiagServer::kTraceFetchMax;
constexpr unsigned DiagServer::kMaxJobsPerNetwork;
constexpr unsigned DiagServer::kMinPeriodMs;
constexpr unsigned DiagServer::kMaxPeriodMs;
constexpr std::chrono::minutes DiagServer::kJobTimeLimit;
constexpr double DiagServer::kSingleFramesPerSecond;

DiagServer::DiagServer(DiagHub& hub) : DiagServer(std::vector<DiagHub*>{&hub}) {}

DiagServer::DiagServer(std::vector<DiagHub*> hubs) {
  chans_.resize(hubs.size());
  for (size_t i = 0; i < hubs.size(); ++i) chans_[i].hub = hubs[i];
}

std::string DiagServer::net_prefix(size_t net) const {
  const std::string& p = chans_[net].hub->config().log_prefix;
  return p.empty() ? "" : p + ": ";
}

bool DiagServer::pick_network(const cJSON* req, size_t& net, std::string& why) const {
  const cJSON* nv = cJSON_GetObjectItemCaseSensitive(req, "network");
  auto names = [this] {
    std::string s;
    for (const auto& ch : chans_) s += (s.empty() ? "" : ", ") + ch.hub->config().network;
    return s;
  };
  if (!nv || cJSON_IsNull(nv)) {
    if (chans_.size() == 1) {
      net = 0;
      return true;
    }
    why = "network required (" + names() + ")";
    return false;
  }
  if (!cJSON_IsString(nv)) {
    why = "field 'network' must be a network name";
    return false;
  }
  for (size_t i = 0; i < chans_.size(); ++i)
    if (chans_[i].hub->config().network == nv->valuestring) {
      net = i;
      return true;
    }
  why = std::string("unknown network '") + nv->valuestring + "' (" + names() + ")";
  return false;
}

DiagServer::~DiagServer() { stop(); }

void DiagServer::start() {
  if (thread_.joinable()) return;
  if (pipe2(stop_pipe_, O_CLOEXEC | O_NONBLOCK) != 0) {
    log_error("diagnostics: cannot create a pipe: %s; diagnostics are off", std::strerror(errno));
    return;
  }
  for (auto& ch : chans_) {
    if (!ch.source) ch.source = make_can_trace_source();
    if (!ch.sink && !ch.hub->config().adapter.simulate) ch.sink = make_can_frame_sink(ch.hub->config().adapter.interface);
  }
  if (!link_ops_) link_ops_ = make_netlink_ops();
  thread_ = std::thread([this] { run(); });
}

void DiagServer::stop() {
  if (thread_.joinable()) {
    char b = 1;
    ssize_t r = write(stop_pipe_[1], &b, 1);
    (void)r;
    thread_.join();
  }
  for (size_t i = clients_.size(); i-- > 0;) close_client(i);
  for (auto& ch : chans_) {
    if (ch.source) ch.source->close();
    ch.open = false;
    if (ch.sink) ch.sink->close();
  }
  jobs_.clear();
  if (listen_fd_ >= 0) close(listen_fd_);
  listen_fd_ = -1;
  port_ = 0;
  for (int& fd : stop_pipe_) {
    if (fd >= 0) close(fd);
    fd = -1;
  }
}

bool DiagServer::open_listener() {
  const MasterConfig& m = settings();
  // A new key and certificate each time the listener opens.
  if (!tls_id_.ready()) {
    std::string why;
    if (!tls_id_.create(why)) {
      if (!warned_listen_) log_warn("diagnostics: cannot make the TLS key: %s; retrying every %lld s", why.c_str(),
                                    (long long)kRetryListen.count());
      warned_listen_ = true;
      return false;
    }
  }
  int fd = socket(AF_INET, SOCK_STREAM | SOCK_CLOEXEC | SOCK_NONBLOCK, 0);
  std::string why;
  if (fd < 0) {
    why = std::strerror(errno);
  } else {
    int one = 1;
    setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &one, sizeof one);
    sockaddr_in a{};
    a.sin_family = AF_INET;
    a.sin_port = htons(static_cast<uint16_t>(m.diag_port));
    inet_pton(AF_INET, m.diag_bind.c_str(), &a.sin_addr);
    if (bind(fd, reinterpret_cast<sockaddr*>(&a), sizeof a) != 0 || listen(fd, 8) != 0) {
      why = std::strerror(errno);
      close(fd);
      fd = -1;
    }
  }
  if (fd < 0) {
    if (!warned_listen_)
      log_warn("diagnostics: cannot listen on %s:%u: %s; CANopen runs without diagnostics, retrying every %lld s",
               m.diag_bind.c_str(), m.diag_port, why.c_str(), (long long)kRetryListen.count());
    warned_listen_ = true;
    return false;
  }
  sockaddr_in got{};
  socklen_t len = sizeof got;
  getsockname(fd, reinterpret_cast<sockaddr*>(&got), &len);
  listen_fd_ = fd;
  port_ = ntohs(got.sin_port);
  log_info("diagnostics listen on %s:%u, %s, encrypted (TLS)", m.diag_bind.c_str(), port_.load(),
           m.diag_allow_changes ? "changes allowed (SDO writes and NMT commands)" : "read-only");
  return true;
}

void DiagServer::run() {
  pthread_setname_np(pthread_self(), "canopen_diag");
  using clock = std::chrono::steady_clock;
  for (;;) {
    auto now = clock::now();
    if (listen_fd_ < 0 && now >= next_listen_try_) {
      if (!open_listener()) next_listen_try_ = now + kRetryListen;
    }
    // stop pipe, listener, then per network its hub's wake pipe and its
    // capture, then the clients.
    const size_t nets = chans_.size(), first_client = 2 + 2 * nets;
    std::vector<pollfd> fds;
    fds.push_back({stop_pipe_[0], POLLIN, 0});
    fds.push_back({listen_fd_, static_cast<short>(listen_fd_ >= 0 ? POLLIN : 0), 0});
    bool waiting_capture = false;
    for (const auto& ch : chans_) {
      fds.push_back({ch.hub->wake_fd(), POLLIN, 0});
      int cap_fd = ch.open ? ch.source->fd() : -1;
      fds.push_back({cap_fd, static_cast<short>(cap_fd >= 0 ? POLLIN : 0), 0});
    }
    for (size_t n = 0; n < nets; ++n) waiting_capture = waiting_capture || (any_trace(n) && !chans_[n].open);
    // A trace waiting for its capture to open retries often; a send job
    // wakes the loop when it is due.
    int timeout = waiting_capture ? 200 : 1000;
    for (const auto& c : clients_) {
      short ev = pending(c) ? POLLOUT : 0;
      // Not read: a connection whose address waits after a failed login
      // (until then), and one whose request is on the bus thread while a
      // line or more waits behind it.
      if (in_backoff(c, now)) {
        auto left = std::chrono::duration_cast<std::chrono::milliseconds>(auth_failed_.at(c.peer) + kLoginBackoff - now);
        timeout = std::min<int>(timeout, static_cast<int>(left.count()) + 1);
      } else if (!c.closing && !(c.waiting && c.in.size() > kMaxLine)) {
        ev |= POLLIN;
      }
      fds.push_back({c.fd, ev, 0});
    }
    if (!jobs_.empty()) timeout = std::min<int>(timeout, static_cast<int>(service_jobs(clock::now()).count()));
    if (!replays_.empty())
      timeout = std::min<int>(timeout, static_cast<int>(service_replays(clock::now()).count()));
    int r = poll(fds.data(), fds.size(), timeout);
    if (r < 0 && errno != EINTR) {
      log_error("diagnostics: poll failed: %s; diagnostics stop", std::strerror(errno));
      return;
    }
    if (fds[0].revents) return;
    now = clock::now();
    for (size_t n = 0; n < nets; ++n)
      if (chans_[n].open && (fds[3 + 2 * n].revents & (POLLIN | POLLERR | POLLHUP))) read_capture(n);

    // Answers from the bus threads. Sequence numbers are per hub, so each
    // answer goes to the client waiting on that hub.
    for (size_t n = 0; n < nets; ++n) {
      std::vector<std::pair<uint64_t, std::string>> answers;
      chans_[n].hub->take_answers(answers);
      for (auto& a : answers)
        for (auto& c : clients_)
          if (c.waiting == a.first && c.waiting_net == n) {
            c.waiting = 0;
            c.out += a.second;
          }
    }

    // Client I/O, for the clients that existed before this poll.
    size_t polled = fds.size() - first_client;
    for (size_t i = 0; i < polled && i < clients_.size(); ++i) {
      Client& c = clients_[i];
      short re = fds[first_client + i].revents;
      if (re & (POLLERR | POLLNVAL)) {
        c.closing = true;
        drop_output(c);
        continue;
      }
      if (re & (POLLIN | POLLHUP)) {
        char buf[4096];
        ssize_t n = recv(c.fd, buf, sizeof buf, 0);
        if (n > 0) {
          on_wire(c, buf, static_cast<size_t>(n));
        } else if (n == 0 || (errno != EAGAIN && errno != EWOULDBLOCK)) {
          c.closing = true;
          drop_output(c);
        }
      }
    }
    for (auto& c : clients_) {
      if (!c.closing) process_input(c);
      if (!c.authed && !c.closing && now - c.since >= login_timeout_) {
        c.closing = true;
        drop_output(c);
      }
      if (c.frames_unlogged && now - c.frame_logged >= std::chrono::seconds(1)) log_unlogged_frames(c);
      if (pending(c) > kMaxSendBuffer) {
        log_warn("diagnostics: client %s does not read its answers; closing the connection", c.peer.c_str());
        c.closing = true;
        drop_output(c);
      }
    }
    for (size_t i = clients_.size(); i-- > 0;) {
      Client& c = clients_[i];
      bool alive = flush(c);
      if (!alive || (c.closing && !pending(c))) close_client(i);
    }
    if (listen_fd_ >= 0 && (fds[1].revents & POLLIN)) accept_clients();
    prune_auth(now);
    update_capture(clock::now());
    if (!jobs_.empty() || !ended_.empty()) service_jobs(clock::now());
    if (!replays_.empty() || !ended_replays_.empty()) service_replays(clock::now());
  }
}

void DiagServer::accept_clients() {
  for (;;) {
    sockaddr_in a{};
    socklen_t len = sizeof a;
    int fd = accept4(listen_fd_, reinterpret_cast<sockaddr*>(&a), &len, SOCK_CLOEXEC | SOCK_NONBLOCK);
    if (fd < 0) return;
    char addr[INET_ADDRSTRLEN] = "?";
    inet_ntop(AF_INET, &a.sin_addr, addr, sizeof addr);
    size_t serving = 0;
    for (const auto& c : clients_) serving += !c.refusing;
    bool refusing = serving >= kMaxClients;
    if (refusing && clients_.size() >= 2 * kMaxClients) {
      close(fd);
      continue;
    }
    int one = 1;
    setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof one);
    Client c;
    c.fd = fd;
    c.peer = addr;
    c.serial = next_client_++;
    c.since = std::chrono::steady_clock::now();
    // Told "too many clients" in its own mode (plain or TLS) once that is known.
    c.refusing = refusing;
    clients_.push_back(std::move(c));
  }
}

void DiagServer::close_client(size_t i) {
  log_unlogged_frames(clients_[i]);
  end_client_jobs(clients_[i].serial, "client disconnected");
  if (clients_[i].fd >= 0) close(clients_[i].fd);
  clients_.erase(clients_.begin() + static_cast<long>(i));
}

size_t DiagServer::pending(const Client& c) const {
  return c.out.size() + (c.tls ? c.tls->wire().size() : 0);
}

void DiagServer::drop_output(Client& c) {
  c.out.clear();
  if (c.tls) c.tls->wire().clear();
}

void DiagServer::on_wire(Client& c, const char* data, size_t n) {
  if (c.mode == Mode::unknown && n) {
    if (static_cast<unsigned char>(data[0]) == kTlsHandshakeByte) {
      std::string why;
      c.tls = TlsConn::server(tls_id_, why);
      if (!c.tls) {
        log_warn("diagnostics: TLS for %s failed: %s", c.peer.c_str(), why.c_str());
        c.closing = true;
        drop_output(c);
        return;
      }
      c.mode = Mode::tls;
    } else {
      c.mode = Mode::plain;
    }
  }
  if (c.mode == Mode::tls) {
    std::string plain, why;
    if (!c.tls->feed(data, n, plain, why)) {
      c.closing = true;  // a TLS alert in wire() still goes out
      c.out.clear();
      return;
    }
    c.in += plain;
  } else {
    c.in.append(data, n);
  }
  if (c.refusing && !c.closing && (c.mode == Mode::plain || c.tls->established())) {
    c.out += diag_error("", "too many clients");
    c.closing = true;
  }
}

bool DiagServer::flush(Client& c) {
  std::string* buf = &c.out;
  if (c.tls) {
    std::string why;
    if (!c.tls->write(c.out, why)) return false;
    c.out.clear();
    buf = &c.tls->wire();
  }
  while (!buf->empty()) {
    ssize_t n = send(c.fd, buf->data(), buf->size(), MSG_NOSIGNAL);
    if (n > 0) {
      buf->erase(0, static_cast<size_t>(n));
      continue;
    }
    if (n < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) return true;
    return false;
  }
  return true;
}

namespace {

// Whether a request line starts as a put_config request does:
// {"op":"put_config" with any spaces, within its first 64 bytes.
bool starts_put_config(const std::string& in) {
  const size_t end = std::min<size_t>(in.size(), 64);
  size_t i = 0;
  auto skip = [&] {
    while (i < end && (in[i] == ' ' || in[i] == '\t' || in[i] == '\r')) ++i;
  };
  auto take = [&](const char* word) {
    skip();
    size_t n = std::strlen(word);
    if (i + n > end || in.compare(i, n, word) != 0) return false;
    i += n;
    return true;
  };
  return take("{") && take("\"op\"") && take(":") && take("\"put_config\"");
}

}  // namespace

bool DiagServer::in_backoff(const Client& c, std::chrono::steady_clock::time_point now) const {
  if (c.authed) return false;
  auto it = auth_failed_.find(c.peer);
  return it != auth_failed_.end() && now < it->second + kLoginBackoff;
}

void DiagServer::process_input(Client& c) {
  if (c.refusing) return;
  // Only a host that takes configs reads a long line, and only a put_config
  // one after the login; every other line, and anything before the login,
  // is held up to kMaxLine.
  auto max_line = [&] {
    return c.authed && host_.put_config && starts_put_config(c.in) ? kMaxAuthedLine : kMaxLine;
  };
  auto too_long = [&] {
    c.out += diag_error("", "request line too long");
    c.closing = true;
    c.in.clear();
    c.scanned = 0;
  };
  // Checked before the login backoff below, so a connection that waits
  // cannot grow its buffer (the server does not read it while it waits).
  if (c.in.find('\n', c.scanned) == std::string::npos && c.in.size() > max_line()) return too_long();
  // After a failed login from this address, its next login waits a moment.
  if (in_backoff(c, std::chrono::steady_clock::now())) return;
  // One request at a time per connection keeps the answers in order.
  size_t start = 0;
  while (!c.closing && !c.waiting) {
    // Searched once: `scanned` is where the last search ended.
    size_t nl = c.in.find('\n', start + c.scanned);
    if (nl == std::string::npos) {
      c.scanned = c.in.size() - start;
      break;
    }
    c.scanned = 0;
    std::string line = c.in.substr(start, nl - start);
    start = nl + 1;
    if (!line.empty() && line.back() == '\r') line.pop_back();
    const bool upload = c.authed && host_.put_config && starts_put_config(line);
    if (line.size() > (upload ? kMaxAuthedLine : kMaxLine)) {
      c.in.erase(0, start);
      return too_long();
    }
    if (line.find_first_not_of(" \t") == std::string::npos) continue;
    handle_line(c, line);
  }
  if (start) c.in.erase(0, start);
  if (!c.closing && c.in.find('\n', c.scanned) == std::string::npos && c.in.size() > max_line()) too_long();
}

void DiagServer::prune_auth(std::chrono::steady_clock::time_point now) {
  for (auto* m : {&auth_failed_, &auth_logged_})
    for (auto it = m->begin(); it != m->end();)
      it = now - it->second >= kAuthKeep ? m->erase(it) : std::next(it);
}

void DiagServer::log_unlogged_frames(Client& c) {
  if (!c.frames_unlogged) return;
  log_info("%sdiagnostics: %llu more frame%s sent by %s (single frames are logged at most once a second)",
           net_prefix(c.frames_net).c_str(), (unsigned long long)c.frames_unlogged, c.frames_unlogged == 1 ? "" : "s",
           c.peer.c_str());
  c.frames_unlogged = 0;
  c.frame_logged = std::chrono::steady_clock::now();
}

void DiagServer::log_auth_failure(const std::string& peer) {
  auto now = std::chrono::steady_clock::now();
  auto it = auth_logged_.find(peer);
  if (it != auth_logged_.end() && now - it->second < std::chrono::minutes(1)) return;
  auth_logged_[peer] = now;
  log_warn("diagnostics: connection from %s refused: wrong token", peer.c_str());
}

void DiagServer::refuse_login(Client& c) {
  log_auth_failure(c.peer);
  auth_failed_[c.peer] = std::chrono::steady_clock::now();
  c.closing = true;
  drop_output(c);
}

cJSON* DiagServer::hello_info() const {
  const MasterConfig& m = settings();
  cJSON* res = cJSON_CreateObject();
  cJSON_AddNumberToObject(res, "protocol", kDiagProtocol);
  cJSON_AddStringToObject(res, "version", chans_[0].hub->version().c_str());
  cJSON_AddStringToObject(res, "host", host_.name.c_str());
  cJSON_AddBoolToObject(res, "allow_changes", m.diag_allow_changes);
  if (host_.put_config) cJSON_AddBoolToObject(res, "allow_config_upload", m.diag_allow_changes && m.diag_allow_config_upload);
  cJSON_AddNumberToObject(res, "master_node_id", m.node_id);
  diag_add_protocols(res);
  cJSON* list = cJSON_AddArrayToObject(res, "networks");
  for (const auto& ch : chans_) {
    const Config& nc = ch.hub->config();
    cJSON* o = cJSON_CreateObject();
    cJSON_AddStringToObject(o, "name", nc.network.c_str());
    cJSON_AddStringToObject(o, "interface", nc.adapter.interface.c_str());
    cJSON_AddNumberToObject(o, "bitrate", nc.adapter.bitrate);
    cJSON_AddStringToObject(o, "protocol", protocol_name(nc.protocol));
    if (nc.is_plain()) {
      cJSON_AddStringToObject(o, "role", "plain");
      cJSON_AddBoolToObject(o, "listen_only", nc.adapter.listen_only);
    } else if (nc.is_j1939()) {
      cJSON_AddStringToObject(o, "role", "ecu");
      cJSON_AddNumberToObject(o, "address", nc.j1939.ecu.address);
    } else if (nc.is_slave()) {
      cJSON_AddStringToObject(o, "role", "slave");
      if (nc.slave.lss)
        cJSON_AddNullToObject(o, "node_id");
      else
        cJSON_AddNumberToObject(o, "node_id", nc.slave.node_id);
    } else {
      cJSON_AddStringToObject(o, "role", "master");
      cJSON_AddNumberToObject(o, "master_node_id", nc.master.node_id);
    }
    cJSON_AddItemToArray(list, o);
  }
  return res;
}

void DiagServer::handle_login(Client& c, const std::string& id, const std::string& op, const cJSON* req) {
  const MasterConfig& m = settings();
  if (c.mode == Mode::plain) {
    // An older client: tell it why, then close.
    c.out += diag_error(id, "this runtime needs an encrypted connection; update canworks-diag");
    c.closing = true;
    return;
  }
  const ScramVerifier& v = m.diag_scram;
  const std::string salt = b64_encode(v.salt);
  if (op == "hello" && c.snonce.empty()) {
    const cJSON* mech = cJSON_GetObjectItemCaseSensitive(req, "mech");
    const cJSON* nonce = cJSON_GetObjectItemCaseSensitive(req, "nonce");
    Bytes raw;
    if (!cJSON_IsString(mech) || std::string(mech->valuestring) != kScramMechanism || !cJSON_IsString(nonce) ||
        !b64_decode(nonce->valuestring, raw) || raw.size() < 16 || raw.size() > 64) {
      c.out += diag_error(id, std::string("log in with {\"op\": \"hello\", \"mech\": \"") + kScramMechanism +
                                  "\", \"nonce\": ...}");
      c.closing = true;
      return;
    }
    c.cnonce = nonce->valuestring;
    c.snonce = b64_encode(random_bytes(kScramNonceBytes));
    cJSON* res = cJSON_CreateObject();
    cJSON_AddNumberToObject(res, "protocol", kDiagProtocol);
    cJSON_AddStringToObject(res, "nonce", c.snonce.c_str());
    cJSON_AddStringToObject(res, "salt", salt.c_str());
    cJSON_AddNumberToObject(res, "iterations", v.iterations);
    c.out += diag_ok(id, res);
    return;
  }
  const cJSON* proof = cJSON_GetObjectItemCaseSensitive(req, "proof");
  Bytes p;
  if (op != "login" || c.snonce.empty() || !cJSON_IsString(proof) || !b64_decode(proof->valuestring, p)) {
    refuse_login(c);
    return;
  }
  std::string auth = scram_auth_message(c.cnonce, c.snonce, salt, v.iterations, tls_id_.cert_hash());
  if (!scram_check_proof(v, auth, p)) {
    refuse_login(c);
    return;
  }
  c.authed = true;
  cJSON* res = hello_info();
  cJSON_AddStringToObject(res, "signature", b64_encode(scram_server_signature(v, auth)).c_str());
  c.out += diag_ok(id, res);
}

namespace {

// A file name of an uploaded config: relative, inside the config's folder.
bool safe_upload_path(const std::string& p) {
  if (p.empty() || p.size() > 255 || p[0] == '/' || p.back() == '/') return false;
  size_t start = 0;
  while (start <= p.size()) {
    size_t end = p.find('/', start);
    if (end == std::string::npos) end = p.size();
    std::string part = p.substr(start, end - start);
    if (part.empty() || part == "." || part == ".." || part[0] == '.') return false;
    for (char ch : part)
      if (!(std::isalnum(static_cast<unsigned char>(ch)) || ch == '-' || ch == '_' || ch == '.' || ch == ' '))
        return false;
    start = end + 1;
  }
  return true;
}

}  // namespace

void DiagServer::handle_put_config(Client& c, const std::string& id, const cJSON* req) {
  const MasterConfig& m = settings();
  if (!host_.put_config) {
    c.out += diag_error(id, "this runtime takes no config over the diagnostics channel: upload the PLC program "
                            "with canworks-deploy --runtime");
    return;
  }
  if (!m.diag_allow_changes || !m.diag_allow_config_upload) {
    c.out += diag_error(id, "config upload is off: the running config needs \"allow_changes\": true and "
                            "\"allow_config_upload\": true in 'diagnostics'");
    return;
  }
  const cJSON* files = cJSON_GetObjectItemCaseSensitive(req, "files");
  if (!cJSON_IsObject(files) || !cJSON_GetObjectItemCaseSensitive(files, "canworks.json")) {
    c.out += diag_error(id, "put_config needs 'files': {\"canworks.json\": base64, other files by their path}");
    return;
  }
  std::vector<std::pair<std::string, std::string>> out;
  size_t total = 0;
  const cJSON* f;
  cJSON_ArrayForEach(f, files) {
    Bytes data;
    if (!safe_upload_path(f->string)) {
      c.out += diag_error(id, std::string("file name \"") + f->string + "\" is not a plain relative path");
      return;
    }
    if (!cJSON_IsString(f) || !b64_decode(f->valuestring, data)) {
      c.out += diag_error(id, std::string("file \"") + f->string + "\" is not base64");
      return;
    }
    total += data.size();
    if (total > kMaxUploadBytes) {
      c.out += diag_error(id, "the files are larger than " + std::to_string(kMaxUploadBytes / (1024 * 1024)) + " MB");
      return;
    }
    out.emplace_back(f->string, std::string(data.begin(), data.end()));
  }
  log_info("diagnostics: %s uploads a config (%zu file%s, %zu bytes)", c.peer.c_str(), out.size(),
           out.size() == 1 ? "" : "s", total);
  std::string why;
  unsigned number = host_.put_config(out, why);
  if (!number) {
    c.out += diag_error(id, why);
    return;
  }
  cJSON* res = cJSON_CreateObject();
  cJSON_AddBoolToObject(res, "restarting", true);
  cJSON_AddNumberToObject(res, "upload", number);
  c.out += diag_ok(id, res);
}

void DiagServer::handle_line(Client& c, const std::string& line) {
  cJSON* req = cJSON_ParseWithLength(line.data(), line.size());
  if (!req || !cJSON_IsObject(req)) {
    cJSON_Delete(req);
    c.out += diag_error("", "not a JSON object");
    if (!c.authed) c.closing = true;
    return;
  }
  DiagRequest r;
  r.peer = c.peer;
  const cJSON* idv = cJSON_GetObjectItemCaseSensitive(req, "id");
  if (idv) {
    char* t = cJSON_PrintUnformatted(idv);
    if (t) r.id = t;
    cJSON_free(t);
  }
  const cJSON* opv = cJSON_GetObjectItemCaseSensitive(req, "op");
  r.op = cJSON_IsString(opv) ? opv->valuestring : "";
  const MasterConfig& m = settings();

  if (c.authed && r.op == "put_config") {
    handle_put_config(c, r.id, req);
    cJSON_Delete(req);
    return;
  }
  size_t net = 0;
  if (c.authed && r.op != "hello") {
    std::string why;
    if (!pick_network(req, net, why)) {
      cJSON_Delete(req);
      c.out += diag_error(r.id, why);
      return;
    }
  }
  DiagHub& hub = *chans_[net].hub;

  if (c.authed && r.op.compare(0, 6, "trace_") == 0) {
    handle_trace(c, net, r.op, r.id, req);
    cJSON_Delete(req);
    return;
  }
  if (c.authed && (r.op == "send_frame" || r.op == "send_frame_stop" || r.op == "detect_bitrate" ||
                   r.op == "detect_bitrate_status" || r.op == "detect_bitrate_stop" || r.op == "replay" ||
                   r.op == "replay_status" || r.op == "replay_stop")) {
    handle_tx(c, net, r.op, r.id, req);
    cJSON_Delete(req);
    return;
  }

  if (!c.authed) {
    // Nothing but the login is answered before authentication.
    handle_login(c, r.id, r.op, req);
    cJSON_Delete(req);
    return;
  }

  // A J1939 or plain CAN network serves its status only.
  if (!hub.config().is_canopen() && r.op != "status" && r.op != "hello") {
    cJSON_Delete(req);
    c.out += diag_error(r.id, "network \"" + hub.config().network + "\" is a " +
                                  (hub.config().is_j1939() ? "J1939" : "plain CAN") + " network; " + r.op +
                                  " needs a CANopen network");
    return;
  }
  // A slave network serves its status and its own dictionary; everything
  // else needs a master network, refused before the fields are checked.
  if (hub.config().is_slave() && r.op != "status" && r.op != "sdo_read" && r.op != "sdo_write" && r.op != "hello") {
    cJSON_Delete(req);
    c.out += diag_error(r.id, "network \"" + hub.config().network + "\" is a slave network; " + r.op +
                                  " needs a master network");
    return;
  }

  std::string why;
  uint64_t v = 0;
  auto get_node = [&](bool any_id) -> bool {
    if (!get_uint(req, "node", 127, v, why)) return false;
    if (v < 1) {
      why = "field 'node' must be 1-127";
      return false;
    }
    r.node = static_cast<unsigned>(v);
    if (any_id && !hub.config().is_slave() && r.node == hub.config().master.node_id) {
      why = "node " + std::to_string(r.node) + " is the master itself";
      return false;
    }
    return true;
  };
  auto get_object = [&]() -> bool {
    if (!get_uint(req, "index", 0xFFFF, v, why)) return false;
    r.index = static_cast<uint16_t>(v);
    if (!get_uint(req, "subindex", 0xFF, v, why)) return false;
    r.subindex = static_cast<uint8_t>(v);
    if (cJSON_GetObjectItemCaseSensitive(req, "timeout_ms")) {
      if (!get_uint(req, "timeout_ms", 10000, v, why)) return false;
      if (v < 10) {
        why = "field 'timeout_ms' must be 10-10000";
        return false;
      }
      r.timeout_ms = static_cast<unsigned>(v);
    }
    return true;
  };

  static const char* const kLssKey[] = {"vendor_id", "product_code", "revision_number", "serial_number"};
  auto get_lss_address = [&]() -> bool {
    for (int f = 0; f < 4; ++f) {
      if (!get_uint(req, kLssKey[f], 0xFFFFFFFF, v, why)) return false;
      r.lss[f] = static_cast<uint32_t>(v);
    }
    return true;
  };
  // force: the bus thread refuses sdo_write, nmt (but start) and scan
  // without it while a configured node is OPERATIONAL.
  auto get_force = [&]() -> bool {
    const cJSON* fv = cJSON_GetObjectItemCaseSensitive(req, "force");
    if (fv && !cJSON_IsBool(fv)) {
      why = "field 'force' must be true or false";
      return false;
    }
    r.force = cJSON_IsTrue(fv);
    return true;
  };
  auto get_store = [&]() -> bool {
    const cJSON* st = cJSON_GetObjectItemCaseSensitive(req, "store");
    if (st && !cJSON_IsBool(st)) {
      why = "field 'store' must be true or false";
      return false;
    }
    r.store = cJSON_IsTrue(st);
    return true;
  };

  bool valid = true;
  bool lss = r.op.compare(0, 4, "lss_") == 0;
  if (r.op == "status" || r.op == "scan_status") {
  } else if (r.op == "scan") {
    valid = get_force();
  } else if (r.op == "lss_find" || r.op == "lss_find_status") {
    const cJSON* vend = cJSON_GetObjectItemCaseSensitive(req, "vendor_id");
    const cJSON* prod = cJSON_GetObjectItemCaseSensitive(req, "product_code");
    if (vend || prod) {
      valid = get_uint(req, "vendor_id", 0xFFFFFFFF, v, why);
      r.lss[0] = static_cast<uint32_t>(v);
      valid = valid && get_uint(req, "product_code", 0xFFFFFFFF, v, why);
      r.lss[1] = static_cast<uint32_t>(v);
      r.lss_known = true;
    }
  } else if (r.op == "lss_inquire") {
    valid = get_lss_address();
  } else if (r.op == "lss_set_id") {
    valid = get_lss_address() && get_node(true) && get_store();
  } else if (r.op == "lss_set_bitrate") {
    valid = get_lss_address() && get_store() && get_uint(req, "bitrate_kbit", 1000, v, why);
    r.bitrate_kbit = static_cast<unsigned>(v);
    static const unsigned kRates[] = {10, 20, 50, 125, 250, 500, 800, 1000};
    if (valid && std::find(std::begin(kRates), std::end(kRates), r.bitrate_kbit) == std::end(kRates)) {
      why = "field 'bitrate_kbit' must be 10, 20, 50, 125, 250, 500, 800 or 1000";
      valid = false;
    }
  } else if (r.op == "emcy") {
    valid = get_node(false);
    if (valid && !configured(hub.config(), r.node)) {
      why = "node " + std::to_string(r.node) + " is not in the configuration";
      valid = false;
    }
  } else if (r.op == "sdo_read") {
    valid = get_node(true) && get_object();
  } else if (r.op == "sdo_write") {
    valid = get_node(true) && get_object() && get_force();
    const cJSON* d = cJSON_GetObjectItemCaseSensitive(req, "data");
    if (valid && (!cJSON_IsString(d) || !parse_hex(d->valuestring, r.data))) {
      why = "field 'data' must be hexadecimal bytes such as \"1E 00\"";
      valid = false;
    }
    if (valid && r.data.size() > kDiagMaxSdoBytes) {
      why = "at most " + std::to_string(kDiagMaxSdoBytes) + " bytes can be written";
      valid = false;
    }
    if (valid && !m.diag_allow_changes) {
      why = "changes not allowed";
      valid = false;
    }
  } else if (r.op == "nmt") {
    valid = get_node(false) && get_force();
    const cJSON* cmd = cJSON_GetObjectItemCaseSensitive(req, "command");
    r.command = cJSON_IsString(cmd) ? cmd->valuestring : "";
    if (valid && r.command != "start" && r.command != "stop" && r.command != "preop" && r.command != "reset" &&
        r.command != "reset-comm") {
      why = "field 'command' must be start, stop, preop, reset or reset-comm";
      valid = false;
    }
    if (valid && !m.diag_allow_changes) {
      why = "changes not allowed";
      valid = false;
    }
    if (valid && !configured(hub.config(), r.node)) {
      why = "node " + std::to_string(r.node) + " is not in the configuration";
      valid = false;
    }
  } else if (r.op.compare(0, 4, "sim_") == 0) {
    // The simulator checks the request itself (on the bus thread).
    if (!simulates_anything(hub.config())) {
      why = "nothing simulated";
      valid = false;
    }
#if CANWORKS_WITH_CANOPEN
    else if (!canopen_sim::Simulator::ReadOnlyOp(r.op) && !m.diag_allow_changes) {
      why = "changes not allowed";
      valid = false;
    }
#endif
    r.raw = line;
  } else if (r.op == "hello") {
    why = "already authenticated";
    valid = false;
  } else {
    why = r.op.empty() ? "missing field 'op'" : "unknown op '" + r.op + "'";
    valid = false;
  }
  // Every LSS request changes the devices' LSS state, even one that stores
  // nothing; reading a finished search's result does not.
  if (valid && lss && r.op != "lss_find_status" && !m.diag_allow_changes) {
    why = "changes not allowed";
    valid = false;
  }
  cJSON_Delete(req);
  if (!valid) {
    c.out += diag_error(r.id, why);
    return;
  }
  c.waiting_net = net;
  c.waiting = hub.submit(std::move(r));
}

// ---------------------------------------------------------------------------
// Traces (frame capture)

bool DiagServer::any_trace(size_t net) const {
  for (const auto& c : clients_)
    if (c.tracing && c.trace_net == net) return true;
  return false;
}

bool DiagServer::any_trace() const {
  for (const auto& c : clients_)
    if (c.tracing) return true;
  return false;
}

void DiagServer::close_capture(size_t net, bool gap) {
  Channel& ch = chans_[net];
  if (!ch.open) return;
  ch.source->close();
  ch.open = false;
  ch.kernel_drops += ch.kernel_drops_sock;
  ch.kernel_drops_sock = 0;
  if (gap) ch.gap = true;
}

void DiagServer::read_capture(size_t net) {
  Channel& ch = chans_[net];
  std::vector<TraceRecord> got;
  bool alive = ch.source->drain(got, ch.kernel_drops_sock);
  for (const auto& r : got) ch.ring.push(r);
  if (!alive) {
    log_warn("%sdiagnostics: trace capture on %s lost (interface gone); resuming when it is back",
             net_prefix(net).c_str(), ch.hub->config().adapter.interface.c_str());
    close_capture(net, true);
    ch.next_try = std::chrono::steady_clock::now() + std::chrono::milliseconds(500);
  }
}

void DiagServer::update_capture(std::chrono::steady_clock::time_point now) {
  for (auto& c : clients_)
    if (c.tracing && now - c.trace_fetched >= trace_idle_) {
      c.tracing = false;
      log_info("diagnostics: trace of %s ended: no fetch for %lld ms", c.peer.c_str(),
               (long long)trace_idle_.count());
    }
  for (size_t n = 0; n < chans_.size(); ++n) update_channel(n, now);
}

void DiagServer::update_channel(size_t net, std::chrono::steady_clock::time_point now) {
  Channel& ch = chans_[net];
  if (!any_trace(net)) {
    if (ch.open) log_info("%sdiagnostics: trace capture stopped", net_prefix(net).c_str());
    close_capture(net, false);
    ch.ring.clear();
    ch.gap = false;
    ch.kernel_drops = ch.kernel_drops_sock = 0;
    return;
  }
  if (!ch.hub->attached()) {
    close_capture(net, true);
    return;
  }
  // The kernel filter is the union of the clients' filters; a client without
  // filters takes everything.
  std::vector<TraceFilter> filters;
  bool all = false, errors = false;
  for (const auto& c : clients_) {
    if (!c.tracing || c.trace_net != net) continue;
    errors = errors || c.trace_errors;
    if (c.trace_filters.empty()) all = true;
    filters.insert(filters.end(), c.trace_filters.begin(), c.trace_filters.end());
  }
  if (all) filters.clear();
  auto same = [](const std::vector<TraceFilter>& a, const std::vector<TraceFilter>& b) {
    if (a.size() != b.size()) return false;
    for (size_t i = 0; i < a.size(); ++i)
      if (a[i].id != b[i].id || a[i].mask != b[i].mask) return false;
    return true;
  };
  const std::string& ifname = ch.hub->config().adapter.interface;
  if (!ch.open) {
    if (now < ch.next_try) return;
    int e = ch.source->open(ifname, filters, errors);
    if (e) {
      if (!ch.warned)
        log_warn("%sdiagnostics: cannot capture frames on %s: %s; retrying", net_prefix(net).c_str(),
                 ifname.c_str(), std::strerror(-e));
      ch.warned = true;
      ch.next_try = now + std::chrono::seconds(1);
      return;
    }
    ch.warned = false;
    ch.open = true;
    ch.filters = filters;
    ch.errors = errors;
    log_info("%sdiagnostics: trace capture on %s started", net_prefix(net).c_str(), ifname.c_str());
    if (ch.gap) {
      TraceRecord gap;
      gap.flags = kTraceGap;
      timeval tv{};
      gettimeofday(&tv, nullptr);
      gap.time_us = uint64_t(tv.tv_sec) * 1000000u + uint64_t(tv.tv_usec);
      ch.ring.push(gap);
      ch.gap = false;
    }
  } else if (!same(filters, ch.filters) || errors != ch.errors) {
    ch.source->set_filters(filters, errors);
    ch.filters = filters;
    ch.errors = errors;
  }
}

bool DiagServer::handle_trace(Client& c, size_t net, const std::string& op, const std::string& id,
                              const cJSON* req) {
  auto now = std::chrono::steady_clock::now();
  Channel& ch = chans_[net];
  std::string why;
  uint64_t v = 0;
  if (op == "trace_start") {
    if (!ch.hub->attached()) {
      c.out += diag_error(id, "no bus");
      return false;
    }
    std::vector<TraceFilter> filters;
    const cJSON* fl = cJSON_GetObjectItemCaseSensitive(req, "filters");
    if (fl && !cJSON_IsArray(fl)) {
      c.out += diag_error(id, "field 'filters' must be a list of {\"id\", \"mask\"}");
      return false;
    }
    if (fl && cJSON_GetArraySize(fl) > 16) {
      c.out += diag_error(id, "at most 16 filters");
      return false;
    }
    const cJSON* f = nullptr;
    cJSON_ArrayForEach(f, fl) {
      TraceFilter tf;
      if (!cJSON_IsObject(f) || !get_uint(f, "id", 0x1FFFFFFF, v, why)) {
        c.out += diag_error(id, why.empty() ? "each filter must be an object with id and mask" : why);
        return false;
      }
      tf.id = static_cast<uint32_t>(v);
      tf.mask = 0x1FFFFFFF;
      if (cJSON_GetObjectItemCaseSensitive(f, "mask")) {
        if (!get_uint(f, "mask", 0x1FFFFFFF, v, why)) {
          c.out += diag_error(id, why);
          return false;
        }
        tf.mask = static_cast<uint32_t>(v);
      }
      filters.push_back(tf);
    }
    const cJSON* ef = cJSON_GetObjectItemCaseSensitive(req, "error_frames");
    if (ef && !cJSON_IsBool(ef)) {
      c.out += diag_error(id, "field 'error_frames' must be true or false");
      return false;
    }
    if (!c.tracing || c.trace_net != net)
      log_info("%sdiagnostics: trace started by %s", net_prefix(net).c_str(), c.peer.c_str());
    c.tracing = true;
    c.trace_net = net;
    c.trace_filters = filters;
    c.trace_errors = cJSON_IsTrue(ef);
    c.trace_fetched = now;
    update_capture(now);
    cJSON* res = cJSON_CreateObject();
    cJSON_AddNumberToObject(res, "next", double(ch.ring.last_seq()));
    cJSON_AddNumberToObject(res, "buffer_frames", double(ch.ring.capacity()));
    cJSON_AddNumberToObject(res, "record_size", double(sizeof(TraceRecord)));
    cJSON_AddStringToObject(res, "network", ch.hub->config().network.c_str());
    cJSON_AddStringToObject(res, "interface",
                            ch.hub->config().adapter.simulate ? "simulated" : ch.hub->config().adapter.interface.c_str());
    cJSON_AddNumberToObject(res, "bitrate", ch.hub->config().adapter.bitrate);
    c.out += diag_ok(id, res);
    return true;
  }
  if (op == "trace_fetch") {
    if (!c.tracing || c.trace_net != net) {
      c.out += diag_error(id, "no trace running (send trace_start)");
      return false;
    }
    if (!get_uint(req, "after", uint64_t(1) << 53, v, why)) {
      c.out += diag_error(id, why);
      return false;
    }
    uint64_t after = v;
    size_t max = kTraceFetchDefault;
    if (cJSON_GetObjectItemCaseSensitive(req, "max")) {
      if (!get_uint(req, "max", kTraceFetchMax, v, why) || v < 1) {
        c.out += diag_error(id, why.empty() ? "field 'max' must be 1-4000" : why);
        return false;
      }
      max = static_cast<size_t>(v);
    }
    c.trace_fetched = now;
    if (ch.open) read_capture(net);
    TraceRing::Fetch f = ch.ring.fetch(after, max, c.trace_filters, c.trace_errors);
    cJSON* res = cJSON_CreateObject();
    cJSON_AddNumberToObject(res, "count", double(f.records.size()));
    cJSON_AddNumberToObject(res, "next", double(f.next));
    cJSON_AddBoolToObject(res, "more", f.next < ch.ring.last_seq());
    cJSON_AddNumberToObject(res, "lost", double(f.lost));
    cJSON_AddNumberToObject(res, "kernel_drops", double(ch.kernel_drops + ch.kernel_drops_sock));
    cJSON_AddBoolToObject(res, "session", ch.hub->attached() && ch.open);
    cJSON_AddStringToObject(res, "frames", trace_base64(f.records).c_str());
    c.out += diag_ok(id, res);
    return true;
  }
  if (op == "trace_stop") {
    if (c.tracing) log_info("diagnostics: trace stopped by %s", c.peer.c_str());
    c.tracing = false;
    update_capture(now);
    c.out += diag_ok(id, nullptr);
    return true;
  }
  c.out += diag_error(id, "unknown op '" + op + "'");
  return false;
}

// ---------------------------------------------------------------------------
// Raw frames and bit rate detection

namespace {

constexpr std::chrono::seconds kEndedKeep{60};

bool get_bool(const cJSON* req, const char* key, bool& out, std::string& why) {
  const cJSON* v = cJSON_GetObjectItemCaseSensitive(req, key);
  if (v && !cJSON_IsBool(v)) {
    why = std::string("field '") + key + "' must be true or false";
    return false;
  }
  out = cJSON_IsTrue(v);
  return true;
}

std::string id_text(const RawFrame& f) {
  char buf[16];
  std::snprintf(buf, sizeof buf, f.ext ? "0x%08X" : "0x%03X", f.id);
  return buf;
}

std::string errno_text(int rc) { return std::strerror(-rc); }

}  // namespace

void DiagServer::handle_tx(Client& c, size_t net, const std::string& op, const std::string& id, const cJSON* req) {
  if (op == "send_frame") return handle_send(c, net, id, req);
  if (op == "detect_bitrate_status") {
    c.out += diag_ok(id, chans_[net].hub->sweep_status());
    return;
  }
  if (op == "detect_bitrate") return handle_detect(c, net, id, req);
  if (op == "detect_bitrate_stop") return handle_detect_stop(c, net, id);
  if (op.compare(0, 6, "replay") == 0) return handle_replay(c, net, op, id, req);
  // send_frame_stop: one of this connection's jobs, or all of them; ended
  // jobs are reported too, so a client learns why its job stopped.
  uint64_t job = 0, v = 0;
  std::string why;
  if (cJSON_GetObjectItemCaseSensitive(req, "job")) {
    if (!get_uint(req, "job", uint64_t(1) << 53, v, why)) {
      c.out += diag_error(id, why);
      return;
    }
    job = v;
  }
  auto now = std::chrono::steady_clock::now();
  bool found = false;
  for (size_t i = jobs_.size(); i-- > 0;)
    if (jobs_[i].client == c.serial && (!job || jobs_[i].job == job)) {
      end_job(i, "stopped", now);
      found = true;
    }
  cJSON* res = cJSON_CreateObject();
  cJSON* list = cJSON_AddArrayToObject(res, "stopped");
  for (size_t i = ended_.size(); i-- > 0;) {
    const TxJob& j = ended_[i];
    if (j.client != c.serial || (job && j.job != job)) continue;
    found = true;
    cJSON* o = cJSON_CreateObject();
    cJSON_AddNumberToObject(o, "job", double(j.job));
    cJSON_AddNumberToObject(o, "id", j.frame.id);
    cJSON_AddNumberToObject(o, "period_ms", j.period_ms);
    cJSON_AddNumberToObject(o, "sent", double(j.sent));
    cJSON_AddStringToObject(o, "reason", j.reason.c_str());
    cJSON_AddItemToArray(list, o);
    ended_.erase(ended_.begin() + static_cast<long>(i));
  }
  if (job && !found) {
    cJSON_Delete(res);
    c.out += diag_error(id, "no job " + std::to_string(job) + " of this connection");
    return;
  }
  c.out += diag_ok(id, res);
}

std::string DiagServer::force_reason(size_t net, const RawFrame& f) const {
  const DiagHub& hub = *chans_[net].hub;
  std::string use = protocol_id_use(hub.config(), f.id, f.ext);
  if (use.empty()) use = hub.used_id(f.id, f.ext);
  if (use.empty()) use = raw_id_use(hub.config(), f.id, f.ext);
  if (!use.empty()) return id_text(f) + " is " + use + " on network " + (hub.config().network.empty() ? hub.config().adapter.interface : hub.config().network);
  std::string op = hub.operational();
  if (!op.empty()) return op + " is OPERATIONAL";
  return "";
}

int DiagServer::send_now(size_t net, const RawFrame& f) {
  Channel& ch = chans_[net];
  if (!ch.sink) return -EOPNOTSUPP;
  if (!ch.sink->is_open()) {
    int rc = ch.sink->open();
    if (rc < 0) return rc;
  }
  return ch.sink->send(f);
}

void DiagServer::handle_send(Client& c, size_t net, const std::string& id, const cJSON* req) {
  DiagHub& hub = *chans_[net].hub;
  const Config& cfg = hub.config();
  std::string why;
  uint64_t v = 0;
  RawFrame f;
  bool force = false;
  if (!get_bool(req, "ext", f.ext, why) || !get_bool(req, "rtr", f.rtr, why) || !get_bool(req, "force", force, why) ||
      !get_uint(req, "can_id", f.ext ? 0x1FFFFFFF : 0x7FF, v, why)) {
    c.out += diag_error(id, why);
    return;
  }
  f.id = static_cast<uint32_t>(v);
  const cJSON* data = cJSON_GetObjectItemCaseSensitive(req, "data");
  if (f.rtr) {
    if (data) {
      c.out += diag_error(id, "a remote frame has no data (give 'dlc')");
      return;
    }
    if (cJSON_GetObjectItemCaseSensitive(req, "dlc")) {
      if (!get_uint(req, "dlc", 8, v, why)) {
        c.out += diag_error(id, why);
        return;
      }
      f.dlc = static_cast<uint8_t>(v);
    }
  } else {
    std::vector<uint8_t> bytes;
    if (data && (!cJSON_IsString(data) || !parse_hex(data->valuestring, bytes))) {
      c.out += diag_error(id, "field 'data' must be hexadecimal bytes such as \"40 18 10 01\"");
      return;
    }
    if (bytes.size() > 8) {
      c.out += diag_error(id, "a CAN frame carries at most 8 data bytes");
      return;
    }
    f.dlc = static_cast<uint8_t>(bytes.size());
    std::copy(bytes.begin(), bytes.end(), f.data);
  }
  unsigned period = 0;
  uint64_t count = 0;
  if (cJSON_GetObjectItemCaseSensitive(req, "period_ms")) {
    if (!get_uint(req, "period_ms", kMaxPeriodMs, v, why)) {
      c.out += diag_error(id, "field 'period_ms' must be 0 (one frame) or " + std::to_string(kMinPeriodMs) + "-" +
                                  std::to_string(kMaxPeriodMs));
      return;
    }
    period = static_cast<unsigned>(v);
    if (period && period < kMinPeriodMs) {
      c.out += diag_error(id, "field 'period_ms' must be 0 (one frame) or " + std::to_string(kMinPeriodMs) + "-" +
                                  std::to_string(kMaxPeriodMs));
      return;
    }
  }
  if (cJSON_GetObjectItemCaseSensitive(req, "count")) {
    if (!period) {
      c.out += diag_error(id, "field 'count' needs 'period_ms'");
      return;
    }
    if (!get_uint(req, "count", 1000000, v, why) || v < 1) {
      c.out += diag_error(id, why.empty() ? "field 'count' must be 1-1000000" : why);
      return;
    }
    count = v;
  }
  if (!settings().diag_allow_changes) {
    c.out += diag_error(id, "changes not allowed");
    return;
  }
  if (cfg.adapter.simulate && !chans_[net].sink) {
    c.out += diag_error(id, "sending frames is not available on this simulated network");
    return;
  }
  if (cfg.adapter.listen_only) {
    c.out += diag_error(id, "network \"" + cfg.network + "\" is listen-only: nothing is sent on it");
    return;
  }
  if (!hub.can_send() || hub.sweep_busy()) {
    c.out += diag_error(id, "no bus");
    return;
  }
  std::string reason = force_reason(net, f);
  if (!reason.empty() && !force) {
    c.out += diag_error(id, reason + "; force needed");
    return;
  }
  auto now = std::chrono::steady_clock::now();
  const std::string forced = reason.empty() ? "" : " (forced: " + reason + ")";
  if (!period) {
    if (!c.tx_limit.take(now)) {
      c.out += diag_error(id, "rate limit");
      return;
    }
    int rc = send_now(net, f);
    if (rc < 0) {
      c.out += diag_error(id, rc == -ENOBUFS ? "transmit queue full" : "cannot send: " + errno_text(rc));
      return;
    }
    // One line a second per client; the frames in between are counted
    // (log_unlogged_frames).
    if (now - c.frame_logged >= std::chrono::seconds(1) || c.frame_logged == std::chrono::steady_clock::time_point{}) {
      log_unlogged_frames(c);
      log_info("%sdiagnostics: frame %s sent by %s%s", net_prefix(net).c_str(), raw_frame_text(f).c_str(),
               c.peer.c_str(), forced.c_str());
      c.frame_logged = now;
    } else {
      if (c.frames_unlogged && c.frames_net != net) log_unlogged_frames(c);
      ++c.frames_unlogged;
      c.frames_net = net;
    }
    cJSON* res = cJSON_CreateObject();
    cJSON_AddBoolToObject(res, "sent", true);
    c.out += diag_ok(id, res);
    return;
  }
  unsigned on_net = 0;
  for (const auto& j : jobs_)
    if (j.net == net) ++on_net;
  if (on_net >= kMaxJobsPerNetwork) {
    c.out += diag_error(id, "too many jobs (at most " + std::to_string(kMaxJobsPerNetwork) + " per network)");
    return;
  }
  TxJob j;
  j.job = next_job_++;
  j.net = net;
  j.client = c.serial;
  j.peer = c.peer;
  j.frame = f;
  j.period_ms = period;
  j.count = count;
  j.forced = !reason.empty();
  j.started = j.next = now;
  log_info("%sdiagnostics: cyclic frame %s every %u ms (job %llu%s) started by %s%s", net_prefix(net).c_str(),
           raw_frame_text(f).c_str(), period, (unsigned long long)j.job,
           count ? (", " + std::to_string(count) + " frames").c_str() : "", c.peer.c_str(), forced.c_str());
  jobs_.push_back(j);
  cJSON* res = cJSON_CreateObject();
  cJSON_AddNumberToObject(res, "job", double(j.job));
  cJSON_AddNumberToObject(res, "period_ms", period);
  if (count)
    cJSON_AddNumberToObject(res, "count", double(count));
  else
    cJSON_AddNullToObject(res, "count");
  c.out += diag_ok(id, res);
  // The first frame goes out now.
  service_jobs(now);
}

std::chrono::milliseconds DiagServer::service_jobs(std::chrono::steady_clock::time_point now) {
  using std::chrono::milliseconds;
  std::vector<bool> changed(chans_.size(), false);
  for (size_t i = jobs_.size(); i-- > 0;) {
    TxJob& j = jobs_[i];
    if (now < j.next) continue;
    changed[j.net] = true;
    if (now - j.started >= kJobTimeLimit) {
      end_job(i, "time limit", now);
      continue;
    }
    if (!chans_[j.net].hub->attached() || chans_[j.net].hub->sweep_busy()) {
      end_job(i, "no bus", now);
      continue;
    }
    int rc = send_now(j.net, j.frame);
    if (rc < 0) {
      end_job(i, rc == -ENOBUFS ? "transmit queue full" : "cannot send: " + errno_text(rc), now);
      continue;
    }
    ++j.sent;
    if (j.count && j.sent >= j.count) {
      end_job(i, "count reached", now);
      continue;
    }
    j.next += milliseconds(j.period_ms);
    // Behind by more than a period (the thread was busy): no burst to catch up.
    if (j.next < now) j.next = now + milliseconds(j.period_ms);
  }
  for (size_t i = ended_.size(); i-- > 0;)
    if (now - ended_[i].ended >= kEndedKeep) {
      changed[ended_[i].net] = true;
      ended_.erase(ended_.begin() + static_cast<long>(i));
    }
  for (size_t n = 0; n < chans_.size(); ++n)
    if (changed[n]) publish_jobs(n);
  milliseconds wait(1000);
  for (const auto& j : jobs_) {
    auto d = std::chrono::duration_cast<milliseconds>(j.next - now);
    if (d < wait) wait = d;
  }
  return wait < milliseconds(0) ? milliseconds(0) : wait;
}

void DiagServer::end_job(size_t i, const std::string& reason, std::chrono::steady_clock::time_point now) {
  TxJob j = jobs_[i];
  jobs_.erase(jobs_.begin() + static_cast<long>(i));
  j.reason = reason;
  j.ended = now;
  log_info("%sdiagnostics: cyclic frame %s (job %llu) of %s ended: %s, %llu sent", net_prefix(j.net).c_str(),
           raw_frame_text(j.frame).c_str(), (unsigned long long)j.job, j.peer.c_str(), reason.c_str(),
           (unsigned long long)j.sent);
  // Nobody can ask about a disconnected client's jobs.
  if (reason != "client disconnected") ended_.push_back(j);
  publish_jobs(j.net);
}

void DiagServer::end_client_jobs(uint64_t client, const std::string& reason) {
  auto now = std::chrono::steady_clock::now();
  for (size_t i = replays_.size(); i-- > 0;)
    if (replays_[i].client == client) end_replay(i, reason, now);
  for (size_t i = ended_replays_.size(); i-- > 0;)
    if (ended_replays_[i].client == client) ended_replays_.erase(ended_replays_.begin() + static_cast<long>(i));
  for (size_t i = jobs_.size(); i-- > 0;)
    if (jobs_[i].client == client) end_job(i, reason, now);
  for (size_t i = ended_.size(); i-- > 0;)
    if (ended_[i].client == client) ended_.erase(ended_.begin() + static_cast<long>(i));
}

void DiagServer::publish_jobs(size_t net) {
  cJSON* list = cJSON_CreateArray();
  for (const auto& j : jobs_) {
    if (j.net != net) continue;
    cJSON* o = cJSON_CreateObject();
    cJSON_AddNumberToObject(o, "job", double(j.job));
    cJSON_AddNumberToObject(o, "id", j.frame.id);
    cJSON_AddBoolToObject(o, "ext", j.frame.ext);
    cJSON_AddNumberToObject(o, "period_ms", j.period_ms);
    cJSON_AddNumberToObject(o, "sent", double(j.sent));
    if (j.count)
      cJSON_AddNumberToObject(o, "count", double(j.count));
    else
      cJSON_AddNullToObject(o, "count");
    cJSON_AddStringToObject(o, "peer", j.peer.c_str());
    cJSON_AddItemToArray(list, o);
  }
  char* t = cJSON_PrintUnformatted(list);
  chans_[net].hub->set_send_jobs(t ? t : "[]");
  cJSON_free(t);
  cJSON_Delete(list);
}

namespace {

cJSON* replay_json(bool running, uint64_t sent, size_t queued, uint64_t rounds,
                   const std::string& reason) {
  cJSON* res = cJSON_CreateObject();
  cJSON_AddBoolToObject(res, "running", running);
  cJSON_AddNumberToObject(res, "sent", double(sent));
  cJSON_AddNumberToObject(res, "queued", double(queued));
  cJSON_AddNumberToObject(res, "rounds", double(rounds));
  if (!reason.empty()) cJSON_AddStringToObject(res, "reason", reason.c_str());
  return res;
}

// One frame of a `replay` batch: {t_us, id, dlc, data, extended, rtr}.
bool replay_frame(const cJSON* o, uint64_t& t_us, RawFrame& f, std::string& why) {
  uint64_t v = 0;
  if (!cJSON_IsObject(o)) {
    why = "each frame must be an object";
    return false;
  }
  if (!get_uint(o, "t_us", uint64_t(1) << 40, t_us, why) || !get_bool(o, "extended", f.ext, why) ||
      !get_bool(o, "rtr", f.rtr, why) || !get_uint(o, "id", f.ext ? 0x1FFFFFFF : 0x7FF, v, why))
    return false;
  f.id = static_cast<uint32_t>(v);
  const cJSON* data = cJSON_GetObjectItemCaseSensitive(o, "data");
  std::vector<uint8_t> bytes;
  if (data && (!cJSON_IsString(data) || (data->valuestring[0] && !parse_hex(data->valuestring, bytes)))) {
    why = "field 'data' must be hexadecimal bytes";
    return false;
  }
  if (bytes.size() > 8 || (f.rtr && !bytes.empty())) {
    why = f.rtr ? "a remote frame has no data" : "a CAN frame carries at most 8 data bytes";
    return false;
  }
  f.dlc = static_cast<uint8_t>(bytes.size());
  if (cJSON_GetObjectItemCaseSensitive(o, "dlc")) {
    if (!get_uint(o, "dlc", 8, v, why)) return false;
    if (!f.rtr && v != bytes.size()) {
      why = "field 'dlc' does not match the data";
      return false;
    }
    f.dlc = static_cast<uint8_t>(v);
  }
  std::copy(bytes.begin(), bytes.end(), f.data);
  return true;
}

// The gap a looping replay leaves between its last frame and the next
// round's first: the gap of its last two frames, at least 1 ms.
uint64_t loop_gap_us(const std::vector<std::pair<uint64_t, RawFrame>>& frames) {
  const size_t n = frames.size();
  return std::max<uint64_t>(n > 1 ? frames[n - 1].first - frames[n - 2].first : 0, 1000);
}

// The most frames a looping replay of `frames` (times from 0) sends in any
// one second, the rounds repeating every `period` µs.
uint64_t loop_max_per_second(const std::vector<std::pair<uint64_t, RawFrame>>& frames, uint64_t period) {
  const uint64_t n = frames.size();
  if (!n || !period) return n;
  const uint64_t second = 1000000;
  // Whole rounds in a second, then the most frames in the rest of it over
  // the round's end (two rounds side by side).
  const uint64_t whole = second / period, rest = second % period;
  uint64_t most = 0;
  size_t hi = 0;
  for (size_t lo = 0; lo < n; ++lo) {
    const uint64_t from = frames[lo].first;
    if (hi < lo) hi = lo;
    auto at = [&](size_t k) { return k < n ? frames[k].first : frames[k - n].first + period; };
    while (hi < lo + n && at(hi) < from + rest) ++hi;
    most = std::max<uint64_t>(most, hi - lo);
  }
  return whole * n + most;
}

}  // namespace

void DiagServer::handle_replay(Client& c, size_t net, const std::string& op, const std::string& id,
                               const cJSON* req) {
  auto now = std::chrono::steady_clock::now();
  Replay* mine = nullptr;
  size_t mine_i = 0;
  for (size_t i = 0; i < replays_.size(); ++i)
    if (replays_[i].net == net && replays_[i].client == c.serial) {
      mine = &replays_[i];
      mine_i = i;
    }
  if (op == "replay_status" || op == "replay_stop") {
    if (mine) {
      if (op == "replay_stop") {
        Replay r = *mine;
        end_replay(mine_i, "stopped", now);
        c.out += diag_ok(id, replay_json(false, r.sent, r.frames.size(), r.rounds, "stopped"));
      } else {
        c.out += diag_ok(id, replay_json(true, mine->sent, mine->frames.size(), mine->rounds, ""));
      }
      return;
    }
    for (size_t i = ended_replays_.size(); i-- > 0;) {
      const Replay& r = ended_replays_[i];
      if (r.net != net || r.client != c.serial) continue;
      c.out += diag_ok(id, replay_json(false, r.sent, r.pos, r.rounds, r.reason));
      return;
    }
    c.out += diag_error(id, "no replay of this connection on this network");
    return;
  }

  // replay: the first batch starts it, later ones (same connection) add to it.
  DiagHub& hub = *chans_[net].hub;
  const Config& cfg = hub.config();
  std::string why;
  bool force = false, more = false, loop = false;
  if (!get_bool(req, "force", force, why) || !get_bool(req, "more", more, why) || !get_bool(req, "loop", loop, why)) {
    c.out += diag_error(id, why);
    return;
  }
  const cJSON* list = cJSON_GetObjectItemCaseSensitive(req, "frames");
  if (!cJSON_IsArray(list) || cJSON_GetArraySize(list) < 1 ||
      static_cast<size_t>(cJSON_GetArraySize(list)) > kReplayBatch) {
    c.out += diag_error(id, "field 'frames' must hold 1-" + std::to_string(kReplayBatch) + " frames");
    return;
  }
  if (!settings().diag_allow_changes) {
    c.out += diag_error(id, "changes not allowed");
    return;
  }
  if (cfg.adapter.listen_only) {
    c.out += diag_error(id, "network \"" + cfg.network + "\" is listen-only: nothing is sent on it");
    return;
  }
  if (cfg.adapter.simulate && !chans_[net].sink) {
    c.out += diag_error(id, "sending frames is not available on this simulated network");
    return;
  }
  if (!mine) {
    for (const auto& r : replays_)
      if (r.net == net) {
        c.out += diag_error(id, "a replay of " + r.peer + " is running on this network (one per network)");
        return;
      }
    if (!hub.can_send() || hub.sweep_busy()) {
      c.out += diag_error(id, "no bus");
      return;
    }
  } else if (!mine->more) {
    c.out += diag_error(id, "this replay has all its frames ('more' was false)");
    return;
  }
  std::vector<std::pair<uint64_t, RawFrame>> batch;
  uint64_t last = mine && !mine->frames.empty() ? mine->frames.back().first : 0;
  std::string forced_reason;
  for (const cJSON* o = list->child; o; o = o->next) {
    uint64_t t = 0;
    RawFrame f;
    if (!replay_frame(o, t, f, why)) {
      c.out += diag_error(id, "frame " + std::to_string(batch.size() + 1) + ": " + why);
      return;
    }
    if (t < last) {
      c.out += diag_error(id, "frame " + std::to_string(batch.size() + 1) + ": 't_us' goes back in time");
      return;
    }
    last = t;
    std::string reason = force_reason(net, f);
    if (!reason.empty()) {
      if (!force && !(mine && mine->forced)) {
        c.out += diag_error(id, reason + "; force needed");
        return;
      }
      if (forced_reason.empty()) forced_reason = reason;
    }
    batch.emplace_back(t, f);
  }
  size_t before = mine ? mine->frames.size() : 0;
  if (before + batch.size() > kReplayMaxFrames) {
    c.out += diag_error(id, "a replay holds at most " + std::to_string(kReplayMaxFrames) + " frames");
    return;
  }
  // The limit over any second, across the batch boundary.
  std::vector<uint64_t> times;
  if (mine)
    for (size_t k = before > kReplayMaxRate ? before - kReplayMaxRate : 0; k < before; ++k)
      times.push_back(mine->frames[k].first);
  for (const auto& b : batch) times.push_back(b.first);
  for (size_t hi = kReplayMaxRate; hi < times.size(); ++hi)
    if (times[hi] - times[hi - kReplayMaxRate] < 1000000) {
      c.out += diag_error(id, "more than " + std::to_string(kReplayMaxRate) + " frames in one second (at " +
                                  std::to_string(times[hi] / 1000) + " ms); the limit is " +
                                  std::to_string(kReplayMaxRate) + " frames per second");
      return;
    }
  // A looping replay repeats: checked as one repeating sequence once all its
  // frames are known, the gap back to its first frame included.
  if ((mine ? mine->loop : loop) && !more) {
    std::vector<std::pair<uint64_t, RawFrame>> all;
    if (mine) all = mine->frames;
    uint64_t t0 = all.empty() ? batch.front().first : 0;
    for (const auto& b : batch) all.emplace_back(b.first - t0, b.second);
    const uint64_t most = loop_max_per_second(all, all.back().first + loop_gap_us(all));
    if (most > kReplayMaxRate) {
      c.out += diag_error(id, "looping, these frames repeat at " + std::to_string(most) + " frames in one second; the limit is " +
                                  std::to_string(kReplayMaxRate) + " frames per second");
      if (mine) end_replay(mine_i, "refused: over the frame rate limit when looping", now);
      return;
    }
  }
  if (!mine) {
    Replay r;
    r.net = net;
    r.client = c.serial;
    r.peer = c.peer;
    r.forced = force;
    r.loop = loop;
    r.started = r.round_start = now;
    // Times count from the first frame.
    uint64_t t0 = batch.front().first;
    for (auto& b : batch) b.first -= t0;
    replays_.push_back(r);
    mine = &replays_.back();
    log_info("%sdiagnostics: replay started by %s%s%s", net_prefix(net).c_str(), c.peer.c_str(),
             loop ? " (looping)" : "", forced_reason.empty() ? "" : (" (forced: " + forced_reason + ")").c_str());
  }
  mine->frames.insert(mine->frames.end(), batch.begin(), batch.end());
  mine->more = more;
  c.out += diag_ok(id, replay_json(true, mine->sent, mine->frames.size(), mine->rounds, ""));
  service_replays(now);
}

std::chrono::milliseconds DiagServer::service_replays(std::chrono::steady_clock::time_point now) {
  using std::chrono::microseconds;
  using std::chrono::milliseconds;
  milliseconds wait(1000);
  for (size_t i = replays_.size(); i-- > 0;) {
    Replay& r = replays_[i];
    if (now - r.started >= kJobTimeLimit) {
      end_replay(i, "time limit", now);
      continue;
    }
    if (!chans_[r.net].hub->attached() || chans_[r.net].hub->sweep_busy()) {
      end_replay(i, "no bus", now);
      continue;
    }
    for (;;) {
      if (r.pos == r.frames.size()) {
        if (r.more) break;  // waits for the next batch
        if (!r.loop || r.frames.empty()) {
          end_replay(i, "done", now);
          break;
        }
        // The next round keeps the recorded gap of the last two frames.
        r.round_start += microseconds(r.frames.back().first + loop_gap_us(r.frames));
        r.pos = 0;
        ++r.rounds;
      }
      auto due = r.round_start + microseconds(r.frames[r.pos].first);
      if (due > now) {
        auto ms = std::chrono::duration_cast<milliseconds>(due - now + microseconds(999));
        if (ms < wait) wait = ms;
        break;
      }
      // At most kReplayMaxRate frames in any second, whatever the schedule
      // (a busy thread catching up, a loop's restart).
      auto t = std::chrono::steady_clock::now();
      while (!r.recent.empty() && t - r.recent.front() >= std::chrono::seconds(1)) r.recent.pop_front();
      if (r.recent.size() >= kReplayMaxRate) {
        auto ms = std::chrono::duration_cast<milliseconds>(r.recent.front() + std::chrono::seconds(1) - t +
                                                           microseconds(999));
        if (ms < wait) wait = ms;
        break;
      }
      // Far behind (the thread was busy): no burst to catch up.
      if (now - due > milliseconds(100) && r.blocked_since == std::chrono::steady_clock::time_point{})
        r.round_start += std::chrono::duration_cast<std::chrono::steady_clock::duration>(now - due);
      int rc = send_now(r.net, r.frames[r.pos].second);
      if (rc == -ENOBUFS) {
        if (r.blocked_since == std::chrono::steady_clock::time_point{}) r.blocked_since = now;
        if (now - r.blocked_since >= std::chrono::seconds(1)) {
          end_replay(i, "transmit queue full", now);
        } else if (milliseconds(1) < wait) {
          wait = milliseconds(1);
        }
        break;
      }
      if (rc < 0) {
        end_replay(i, "cannot send: " + errno_text(rc), now);
        break;
      }
      r.blocked_since = {};
      r.recent.push_back(std::chrono::steady_clock::now());
      if (r.recent.size() > kReplayMaxRate) r.recent.pop_front();
      ++r.sent;
      ++r.pos;
    }
  }
  for (size_t i = ended_replays_.size(); i-- > 0;)
    if (now - ended_replays_[i].ended >= kEndedKeep) ended_replays_.erase(ended_replays_.begin() + static_cast<long>(i));
  return wait;
}

void DiagServer::end_replay(size_t i, const std::string& reason, std::chrono::steady_clock::time_point now) {
  Replay r = std::move(replays_[i]);
  replays_.erase(replays_.begin() + static_cast<long>(i));
  log_info("%sdiagnostics: replay of %s ended: %s, %llu frame%s sent", net_prefix(r.net).c_str(), r.peer.c_str(),
           reason.c_str(), (unsigned long long)r.sent, r.sent == 1 ? "" : "s");
  if (reason == "client disconnected") return;
  r.reason = reason;
  r.ended = now;
  size_t queued = r.frames.size();
  std::vector<std::pair<uint64_t, RawFrame>>().swap(r.frames);
  r.pos = queued;  // the frame count, for replay_status
  ended_replays_.push_back(std::move(r));
}

void DiagServer::handle_detect(Client& c, size_t net, const std::string& id, const cJSON* req) {
  DiagHub& hub = *chans_[net].hub;
  auto status = [&]() { c.out += diag_ok(id, hub.sweep_status()); };
  const Config& cfg = hub.config();
  if (!cfg.is_canopen()) {
    c.out += diag_error(id, "bit rate detection runs on CANopen networks; network \"" + cfg.network + "\" is a " +
                                (cfg.is_j1939() ? "J1939" : "plain CAN") + " network");
    return;
  }
  std::string why;
  uint64_t v = 0;
  SweepRequest sr;
  sr.peer = c.peer;
  bool force = false;
  if (!get_bool(req, "force", force, why) || !get_bool(req, "disturb_bus", sr.disturb_bus, why)) {
    c.out += diag_error(id, why);
    return;
  }
  const cJSON* rates = cJSON_GetObjectItemCaseSensitive(req, "rates");
  if (rates) {
    if (!cJSON_IsArray(rates) || cJSON_GetArraySize(rates) < 1) {
      c.out += diag_error(id, "field 'rates' must be a list of bit rates in kbit/s");
      return;
    }
    const cJSON* r = nullptr;
    cJSON_ArrayForEach(r, rates) {
      unsigned k = cJSON_IsNumber(r) ? static_cast<unsigned>(r->valuedouble) : 0;
      if (!cJSON_IsNumber(r) || r->valuedouble != k ||
          std::find(std::begin(kSweepRates), std::end(kSweepRates), k) == std::end(kSweepRates)) {
        c.out += diag_error(id, "field 'rates' takes 1000, 800, 500, 250, 125, 50, 20 and 10");
        return;
      }
      if (std::find(sr.rates_kbit.begin(), sr.rates_kbit.end(), k) == sr.rates_kbit.end()) sr.rates_kbit.push_back(k);
    }
  }
  if (cJSON_GetObjectItemCaseSensitive(req, "per_rate_ms")) {
    if (!get_uint(req, "per_rate_ms", 10000, v, why) || v < 100) {
      c.out += diag_error(id, "field 'per_rate_ms' must be 100-10000");
      return;
    }
    sr.per_rate_ms = static_cast<unsigned>(v);
  }
  if (cJSON_GetObjectItemCaseSensitive(req, "rounds")) {
    if (!get_uint(req, "rounds", 20, v, why) || v < 1) {
      c.out += diag_error(id, "field 'rounds' must be 1-20");
      return;
    }
    sr.rounds = static_cast<unsigned>(v);
  }
  const uint64_t total_ms = uint64_t(sr.per_rate_ms) * (sr.rates_kbit.empty() ? 8 : sr.rates_kbit.size()) * sr.rounds;
  if (total_ms > kMaxSweepMs) {
    c.out += diag_error(id, "the sweep would listen " + std::to_string(total_ms / 1000) +
                                " s; per_rate_ms times rates times rounds may be at most " +
                                std::to_string(kMaxSweepMs / 1000) + " s");
    return;
  }
  if (!settings().diag_allow_changes) {
    c.out += diag_error(id, "changes not allowed");
    return;
  }
  if (hub.sweep_busy()) return status();  // the running sweep's progress
  if (cfg.adapter.simulate) {
    c.out += diag_error(id, "no bit rate on a virtual bus");
    return;
  }
  if (cfg.adapter.type == "socketcan" && !cfg.adapter.configure_link) {
    c.out += diag_error(id, "the link is configured by the system (configure_link false)");
    return;
  }
  LinkInfo li;
  int rc = link_ops_ ? link_ops_->get(cfg.adapter.interface, li) : -ENODEV;
  if (rc == -ENODEV || !hub.attached()) {
    c.out += diag_error(id, "no bus");
    return;
  }
  if (rc == 0 && li.kind != "can") {
    c.out += diag_error(id, "no bit rate on a virtual bus");
    return;
  }
  std::string op = hub.operational();
  const std::string netname = cfg.network.empty() ? cfg.adapter.interface : cfg.network;
  if (!op.empty() && !force) {
    c.out += diag_error(id, op + " is OPERATIONAL; CANopen on network " + netname + " would stop for the sweep; force needed");
    return;
  }
  // Hand-sent frames stop with the session.
  auto now = std::chrono::steady_clock::now();
  for (size_t i = jobs_.size(); i-- > 0;)
    if (jobs_[i].net == net) end_job(i, "bit rate detection", now);
  hub.request_sweep(sr);
  log_info("%sdiagnostics: bit rate detection on %s started by %s%s; CANopen on this network stops until it ends",
           net_prefix(net).c_str(), cfg.adapter.interface.c_str(), c.peer.c_str(),
           op.empty() ? "" : (" (forced: " + op + " was OPERATIONAL)").c_str());
  status();
}

void DiagServer::handle_detect_stop(Client& c, size_t net, const std::string& id) {
  DiagHub& hub = *chans_[net].hub;
  if (!settings().diag_allow_changes) {
    c.out += diag_error(id, "changes not allowed");
    return;
  }
  if (!hub.stop_sweep(c.peer)) {
    const Config& cfg = hub.config();
    c.out += diag_error(id, "no bit rate detection is running on network " +
                                (cfg.network.empty() ? cfg.adapter.interface : cfg.network));
    return;
  }
  log_info("%sdiagnostics: bit rate detection on %s stopped by %s; it ends after the current rate",
           net_prefix(net).c_str(), hub.config().adapter.interface.c_str(), c.peer.c_str());
  c.out += diag_ok(id, hub.sweep_status());
}

}  // namespace canopen_plugin
