#include "diag.h"

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

std::string DiagHub::offline_answer(const DiagRequest& r) const {
  if (r.op != "status") return diag_error(r.id, "no bus");
  cJSON* res = cJSON_CreateObject();
  cJSON_AddStringToObject(res, "version", version_.c_str());
  cJSON_AddNumberToObject(res, "uptime_s", uptime_s());
  cJSON_AddStringToObject(res, "config_sha256", cfg_.file_sha256.c_str());
  cJSON_AddBoolToObject(res, "session", false);
  cJSON* m = cJSON_AddObjectToObject(res, "master");
  cJSON_AddNumberToObject(m, "node_id", cfg_.master.node_id);
  cJSON_AddNumberToObject(m, "state", 0);
  cJSON* b = cJSON_AddObjectToObject(res, "bus");
  cJSON_AddStringToObject(b, "interface", cfg_.adapter.interface.c_str());
  cJSON_AddNumberToObject(b, "state", 0);
  cJSON* nodes = cJSON_AddArrayToObject(res, "nodes");
  for (const auto& n : cfg_.nodes) {
    cJSON* o = cJSON_CreateObject();
    cJSON_AddNumberToObject(o, "node_id", n.node_id);
    cJSON_AddStringToObject(o, "name", n.name.c_str());
    cJSON_AddNumberToObject(o, "state", 0);
    cJSON_AddBoolToObject(o, "status", false);
    cJSON_AddItemToArray(nodes, o);
  }
  return diag_ok(r.id, res);
}

// ---------------------------------------------------------------------------
// DiagServer

constexpr unsigned DiagServer::kMaxClients;
constexpr size_t DiagServer::kMaxLine;
constexpr size_t DiagServer::kMaxSendBuffer;
constexpr std::chrono::seconds DiagServer::kHelloTimeout;
constexpr std::chrono::seconds DiagServer::kRetryListen;
constexpr size_t DiagServer::kTraceFetchDefault;
constexpr size_t DiagServer::kTraceFetchMax;

DiagServer::DiagServer(DiagHub& hub) : hub_(hub) {}

DiagServer::~DiagServer() { stop(); }

void DiagServer::start() {
  if (thread_.joinable()) return;
  if (pipe2(stop_pipe_, O_CLOEXEC | O_NONBLOCK) != 0) {
    log_error("diagnostics: cannot create a pipe: %s; diagnostics are off", std::strerror(errno));
    return;
  }
  if (!trace_source_) trace_source_ = make_can_trace_source();
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
  if (trace_source_) trace_source_->close();
  capture_open_ = false;
  if (listen_fd_ >= 0) close(listen_fd_);
  listen_fd_ = -1;
  port_ = 0;
  for (int& fd : stop_pipe_) {
    if (fd >= 0) close(fd);
    fd = -1;
  }
}

bool DiagServer::open_listener() {
  const MasterConfig& m = hub_.config().master;
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
  log_info("diagnostics listen on %s:%u, %s", m.diag_bind.c_str(), port_.load(),
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
    std::vector<pollfd> fds;
    fds.push_back({stop_pipe_[0], POLLIN, 0});
    fds.push_back({hub_.wake_fd(), POLLIN, 0});
    fds.push_back({listen_fd_, static_cast<short>(listen_fd_ >= 0 ? POLLIN : 0), 0});
    int cap_fd = capture_open_ ? trace_source_->fd() : -1;
    fds.push_back({cap_fd, static_cast<short>(cap_fd >= 0 ? POLLIN : 0), 0});
    for (const auto& c : clients_) {
      short ev = c.out.empty() ? 0 : POLLOUT;
      if (!c.closing) ev |= POLLIN;
      fds.push_back({c.fd, ev, 0});
    }
    // A trace waiting for its capture to open retries often.
    int r = poll(fds.data(), fds.size(), any_trace() && !capture_open_ ? 200 : 1000);
    if (r < 0 && errno != EINTR) {
      log_error("diagnostics: poll failed: %s; diagnostics stop", std::strerror(errno));
      return;
    }
    if (fds[0].revents) return;
    now = clock::now();
    if (capture_open_ && (fds[3].revents & (POLLIN | POLLERR | POLLHUP))) read_capture();

    // Answers from the bus thread.
    std::vector<std::pair<uint64_t, std::string>> answers;
    hub_.take_answers(answers);
    for (auto& a : answers)
      for (auto& c : clients_)
        if (c.waiting == a.first) {
          c.waiting = 0;
          c.out += a.second;
        }

    // Client I/O. Indices into fds are 4 + client index, for the clients
    // that existed before this poll.
    size_t polled = fds.size() - 4;
    for (size_t i = 0; i < polled && i < clients_.size(); ++i) {
      Client& c = clients_[i];
      short re = fds[4 + i].revents;
      if (re & (POLLERR | POLLNVAL)) {
        c.closing = true;
        c.out.clear();
        continue;
      }
      if (re & (POLLIN | POLLHUP)) {
        char buf[4096];
        ssize_t n = recv(c.fd, buf, sizeof buf, 0);
        if (n > 0) {
          c.in.append(buf, static_cast<size_t>(n));
        } else if (n == 0 || (errno != EAGAIN && errno != EWOULDBLOCK)) {
          c.closing = true;
          c.out.clear();
        }
      }
    }
    for (auto& c : clients_) {
      if (!c.closing) process_input(c);
      if (!c.authed && !c.closing && now - c.since >= kHelloTimeout) {
        c.closing = true;
        c.out.clear();
      }
      if (c.out.size() > kMaxSendBuffer) {
        log_warn("diagnostics: client %s does not read its answers; closing the connection", c.peer.c_str());
        c.closing = true;
        c.out.clear();
      }
    }
    for (size_t i = clients_.size(); i-- > 0;) {
      Client& c = clients_[i];
      bool alive = flush(c);
      if (!alive || (c.closing && c.out.empty())) close_client(i);
    }
    if (listen_fd_ >= 0 && (fds[2].revents & POLLIN)) accept_clients();
    update_capture(clock::now());
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
    if (clients_.size() >= kMaxClients) {
      std::string line = diag_error("", "too many clients");
      ssize_t r = send(fd, line.data(), line.size(), MSG_NOSIGNAL);
      (void)r;
      close(fd);
      continue;
    }
    int one = 1;
    setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof one);
    Client c;
    c.fd = fd;
    c.peer = addr;
    c.since = std::chrono::steady_clock::now();
    clients_.push_back(std::move(c));
  }
}

void DiagServer::close_client(size_t i) {
  if (clients_[i].fd >= 0) close(clients_[i].fd);
  clients_.erase(clients_.begin() + static_cast<long>(i));
}

bool DiagServer::flush(Client& c) {
  while (!c.out.empty()) {
    ssize_t n = send(c.fd, c.out.data(), c.out.size(), MSG_NOSIGNAL);
    if (n > 0) {
      c.out.erase(0, static_cast<size_t>(n));
      continue;
    }
    if (n < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) return true;
    return false;
  }
  return true;
}

void DiagServer::process_input(Client& c) {
  // One request at a time per connection keeps the answers in order.
  while (!c.closing && !c.waiting) {
    size_t nl = c.in.find('\n');
    if (nl == std::string::npos) {
      if (c.in.size() > kMaxLine) {
        c.out += diag_error("", "request line too long");
        c.closing = true;
      }
      return;
    }
    std::string line = c.in.substr(0, nl);
    c.in.erase(0, nl + 1);
    if (!line.empty() && line.back() == '\r') line.pop_back();
    if (line.size() > kMaxLine) {
      c.out += diag_error("", "request line too long");
      c.closing = true;
      return;
    }
    if (line.find_first_not_of(" \t") == std::string::npos) continue;
    handle_line(c, line);
  }
}

void DiagServer::log_auth_failure(const std::string& peer) {
  auto now = std::chrono::steady_clock::now();
  auto it = auth_logged_.find(peer);
  if (it != auth_logged_.end() && now - it->second < std::chrono::minutes(1)) return;
  auth_logged_[peer] = now;
  log_warn("diagnostics: connection from %s refused: wrong token", peer.c_str());
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
  const MasterConfig& m = hub_.config().master;

  if (c.authed && r.op.compare(0, 6, "trace_") == 0) {
    handle_trace(c, r.op, r.id, req);
    cJSON_Delete(req);
    return;
  }

  if (!c.authed) {
    // Nothing but a matching hello is answered before authentication.
    const cJSON* tok = cJSON_GetObjectItemCaseSensitive(req, "token");
    bool ok = r.op == "hello" && cJSON_IsString(tok) &&
              equal_constant_time(sha256_hex(tok->valuestring), m.diag_token_sha256);
    cJSON_Delete(req);
    if (!ok) {
      log_auth_failure(c.peer);
      c.closing = true;
      c.out.clear();
      return;
    }
    c.authed = true;
    cJSON* res = cJSON_CreateObject();
    cJSON_AddNumberToObject(res, "protocol", kDiagProtocol);
    cJSON_AddStringToObject(res, "version", hub_.version().c_str());
    cJSON_AddBoolToObject(res, "allow_changes", m.diag_allow_changes);
    cJSON_AddNumberToObject(res, "master_node_id", m.node_id);
    c.out += diag_ok(r.id, res);
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
    if (any_id && r.node == m.node_id) {
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
  if (r.op == "status" || r.op == "scan" || r.op == "scan_status") {
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
    if (valid && !configured(hub_.config(), r.node)) {
      why = "node " + std::to_string(r.node) + " is not in the configuration";
      valid = false;
    }
  } else if (r.op == "sdo_read") {
    valid = get_node(true) && get_object();
  } else if (r.op == "sdo_write") {
    valid = get_node(true) && get_object();
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
    valid = get_node(false);
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
    if (valid && !configured(hub_.config(), r.node)) {
      why = "node " + std::to_string(r.node) + " is not in the configuration";
      valid = false;
    }
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
  c.waiting = hub_.submit(std::move(r));
}

// ---------------------------------------------------------------------------
// Traces (frame capture)

bool DiagServer::any_trace() const {
  for (const auto& c : clients_)
    if (c.tracing) return true;
  return false;
}

void DiagServer::close_capture(bool gap) {
  if (!capture_open_) return;
  trace_source_->close();
  capture_open_ = false;
  kernel_drops_ += kernel_drops_sock_;
  kernel_drops_sock_ = 0;
  if (gap) capture_gap_ = true;
}

void DiagServer::read_capture() {
  std::vector<TraceRecord> got;
  bool alive = trace_source_->drain(got, kernel_drops_sock_);
  for (const auto& r : got) ring_.push(r);
  if (!alive) {
    log_warn("diagnostics: trace capture on %s lost (interface gone); resuming when it is back",
             hub_.config().adapter.interface.c_str());
    close_capture(true);
    next_capture_try_ = std::chrono::steady_clock::now() + std::chrono::milliseconds(500);
  }
}

void DiagServer::update_capture(std::chrono::steady_clock::time_point now) {
  for (auto& c : clients_)
    if (c.tracing && now - c.trace_fetched >= trace_idle_) {
      c.tracing = false;
      log_info("diagnostics: trace of %s ended: no fetch for %lld ms", c.peer.c_str(),
               (long long)trace_idle_.count());
    }
  bool tracing = any_trace();
  if (!tracing) {
    if (capture_open_) log_info("diagnostics: trace capture stopped");
    close_capture(false);
    ring_.clear();
    capture_gap_ = false;
    kernel_drops_ = kernel_drops_sock_ = 0;
    return;
  }
  if (!hub_.attached()) {
    close_capture(true);
    return;
  }
  // The kernel filter is the union of the clients' filters; a client without
  // filters takes everything.
  std::vector<TraceFilter> filters;
  bool all = false, errors = false;
  for (const auto& c : clients_) {
    if (!c.tracing) continue;
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
  const std::string& ifname = hub_.config().adapter.interface;
  if (!capture_open_) {
    if (now < next_capture_try_) return;
    int e = trace_source_->open(ifname, filters, errors);
    if (e) {
      if (!warned_capture_)
        log_warn("diagnostics: cannot capture frames on %s: %s; retrying", ifname.c_str(), std::strerror(-e));
      warned_capture_ = true;
      next_capture_try_ = now + std::chrono::seconds(1);
      return;
    }
    warned_capture_ = false;
    capture_open_ = true;
    capture_filters_ = filters;
    capture_errors_ = errors;
    log_info("diagnostics: trace capture on %s started", ifname.c_str());
    if (capture_gap_) {
      TraceRecord gap;
      gap.flags = kTraceGap;
      timeval tv{};
      gettimeofday(&tv, nullptr);
      gap.time_us = uint64_t(tv.tv_sec) * 1000000u + uint64_t(tv.tv_usec);
      ring_.push(gap);
      capture_gap_ = false;
    }
  } else if (!same(filters, capture_filters_) || errors != capture_errors_) {
    trace_source_->set_filters(filters, errors);
    capture_filters_ = filters;
    capture_errors_ = errors;
  }
}

bool DiagServer::handle_trace(Client& c, const std::string& op, const std::string& id, const cJSON* req) {
  auto now = std::chrono::steady_clock::now();
  std::string why;
  uint64_t v = 0;
  if (op == "trace_start") {
    if (!hub_.attached()) {
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
    if (!c.tracing) log_info("diagnostics: trace started by %s", c.peer.c_str());
    c.tracing = true;
    c.trace_filters = filters;
    c.trace_errors = cJSON_IsTrue(ef);
    c.trace_fetched = now;
    update_capture(now);
    cJSON* res = cJSON_CreateObject();
    cJSON_AddNumberToObject(res, "next", double(ring_.last_seq()));
    cJSON_AddNumberToObject(res, "buffer_frames", double(ring_.capacity()));
    cJSON_AddNumberToObject(res, "record_size", double(sizeof(TraceRecord)));
    cJSON_AddStringToObject(res, "interface", hub_.config().adapter.interface.c_str());
    cJSON_AddNumberToObject(res, "bitrate", hub_.config().adapter.bitrate);
    c.out += diag_ok(id, res);
    return true;
  }
  if (op == "trace_fetch") {
    if (!c.tracing) {
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
    if (capture_open_) read_capture();
    TraceRing::Fetch f = ring_.fetch(after, max, c.trace_filters, c.trace_errors);
    cJSON* res = cJSON_CreateObject();
    cJSON_AddNumberToObject(res, "count", double(f.records.size()));
    cJSON_AddNumberToObject(res, "next", double(f.next));
    cJSON_AddBoolToObject(res, "more", f.next < ring_.last_seq());
    cJSON_AddNumberToObject(res, "lost", double(f.lost));
    cJSON_AddNumberToObject(res, "kernel_drops", double(kernel_drops_ + kernel_drops_sock_));
    cJSON_AddBoolToObject(res, "session", hub_.attached() && capture_open_);
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

}  // namespace canopen_plugin
