// cia309_server.cpp - see cia309_server.h.

#include "cia309_server.h"

#include <algorithm>
#include <arpa/inet.h>
#include <cerrno>
#include <cstring>
#include <fcntl.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <poll.h>
#include <pthread.h>
#include <sys/socket.h>
#include <unistd.h>

#include "cJSON.h"
#include "log.h"

namespace canopen_plugin {

constexpr size_t Cia309Server::kMaxSendBuffer;
constexpr std::chrono::seconds Cia309Server::kStalledFor;
constexpr std::chrono::seconds Cia309Server::kRetryListen;

namespace {

void wake(int fd) {
  if (fd < 0) return;
  char b = 1;
  ssize_t r = write(fd, &b, 1);
  (void)r;  // a full pipe is already a wake-up
}

void drain(int fd) {
  char buf[64];
  while (fd >= 0 && read(fd, buf, sizeof buf) > 0) {
  }
}

}  // namespace

Cia309Server::Cia309Server(const Cia309Config& cfg, std::vector<Cia309Net> nets, std::string version)
    : cfg_(cfg), nets_(std::move(nets)), version_(std::move(version)) {}

Cia309Server::~Cia309Server() { stop(); }

std::string Cia309Server::numbering_text() const {
  std::string s;
  for (const auto& n : cfg_.numbering) {
    if (n.second >= nets_.size() || !nets_[n.second].cfg) continue;
    const Config& c = *nets_[n.second].cfg;
    s += (s.empty() ? "" : ", ") + std::to_string(n.first) + " = " + (c.network.empty() ? "the network" : c.network);
    if (!c.is_canopen()) s += std::string(" (") + (c.is_j1939() ? "J1939" : "plain CAN") + ", not served)";
    else if (c.is_slave()) s += " (slave: its own dictionary)";
  }
  return s.empty() ? "none" : s;
}

cJSON* Cia309Server::info() const {
  cJSON* res = cJSON_CreateObject();
  cJSON_AddStringToObject(res, "protocol", "CiA 309-3");
  cJSON_AddStringToObject(res, "version", "2.1");
  cJSON_AddBoolToObject(res, "allow_changes", cfg_.allow_changes);
  cJSON_AddBoolToObject(res, "allow_force", cfg_.allow_force);
  if (cfg_.default_net)
    cJSON_AddNumberToObject(res, "default_net", cfg_.default_net);
  else
    cJSON_AddNullToObject(res, "default_net");
  cJSON* list = cJSON_AddArrayToObject(res, "nets");
  for (const auto& n : cfg_.numbering) {
    if (n.second >= nets_.size() || !nets_[n.second].cfg) continue;
    const Config& c = *nets_[n.second].cfg;
    cJSON* o = cJSON_CreateObject();
    cJSON_AddNumberToObject(o, "number", n.first);
    cJSON_AddStringToObject(o, "name", c.network.c_str());
    cJSON_AddStringToObject(o, "protocol", protocol_name(c.protocol));
    cJSON_AddStringToObject(o, "role", !c.is_canopen() ? (c.is_j1939() ? "ecu" : "plain") : c.is_slave() ? "slave"
                                                                                                    : "master");
    cJSON_AddBoolToObject(o, "served", c.is_canopen());
    cJSON_AddItemToArray(list, o);
  }
  return res;
}

cJSON* Cia309Server::status() const {
  cJSON* res = cJSON_CreateObject();
  if (cfg_.port) {
    std::string listen = (cfg_.bind == "::1" ? "[::1]" : cfg_.bind) + ":" + std::to_string(cfg_.port);
    cJSON_AddStringToObject(res, "listen", listen.c_str());
    cJSON_AddBoolToObject(res, "listening", port_.load() != 0);
  } else {
    cJSON_AddNullToObject(res, "listen");
    cJSON_AddBoolToObject(res, "listening", false);
  }
  cJSON_AddBoolToObject(res, "allow_changes", cfg_.allow_changes);
  cJSON_AddBoolToObject(res, "allow_force", cfg_.allow_force);
  cJSON_AddNumberToObject(res, "max_clients", cfg_.max_clients);
  cJSON* list = cJSON_AddArrayToObject(res, "sessions");
  std::lock_guard<std::mutex> lock(mutex_);
  for (const auto& s : snapshot_) {
    cJSON* o = cJSON_CreateObject();
    cJSON_AddStringToObject(o, "address", s.peer.c_str());
    cJSON_AddStringToObject(o, "kind", s.tunnelled ? "tunnelled" : "plain");
    cJSON_AddNumberToObject(o, "commands", static_cast<double>(s.served));
    cJSON_AddItemToArray(list, o);
  }
  return res;
}

Cia309Hooks Cia309Server::hooks() {
  Cia309Hooks h;
  h.can_take = [this](std::string& why) { return can_take(why); };
  h.take = [this](int fd, std::unique_ptr<TlsConn> tls, const std::string& peer, std::string in) {
    return take(fd, std::move(tls), peer, std::move(in));
  };
  h.info = [this] { return info(); };
  return h;
}

bool Cia309Server::can_take(std::string& why) {
  if (!thread_.joinable()) {
    why = "cia309 gateway not running";
    return false;
  }
  if (count_.load() >= cfg_.max_clients) {
    why = "too many gateway clients";
    return false;
  }
  return true;
}

bool Cia309Server::take(int fd, std::unique_ptr<TlsConn> tls, const std::string& peer, std::string in) {
  {
    std::lock_guard<std::mutex> lock(mutex_);
    if (!thread_.joinable() || count_.load() >= cfg_.max_clients) return false;
    ++count_;
    Handover h;
    h.fd = fd;
    h.tls = std::move(tls);
    h.peer = peer;
    h.in = std::move(in);
    handovers_.push_back(std::move(h));
  }
  wake(handover_pipe_[1]);
  return true;
}

void Cia309Server::start() {
  if (thread_.joinable()) return;
  if (pipe2(stop_pipe_, O_CLOEXEC | O_NONBLOCK) != 0 || pipe2(handover_pipe_, O_CLOEXEC | O_NONBLOCK) != 0) {
    log_error("cia309: cannot create a pipe: %s; the CiA 309-3 gateway is off", std::strerror(errno));
    return;
  }
  std::string mode = cfg_.allow_changes ? "changes allowed (SDO downloads, NMT and LSS)" : "read-only";
  mode += cfg_.allow_force ? ", force allowed on OPERATIONAL nodes" : "";
  if (!cfg_.port && !any_port_)
    log_info("CiA 309-3 gateway: no plain port (sessions through the diagnostics channel only), %s; networks %s",
             mode.c_str(), numbering_text().c_str());
  thread_ = std::thread([this] { run(); });
}

void Cia309Server::stop() {
  if (thread_.joinable()) {
    wake(stop_pipe_[1]);
    thread_.join();
  }
  for (size_t i = conns_.size(); i-- > 0;) close_conn(i, nullptr);
  {
    std::lock_guard<std::mutex> lock(mutex_);
    for (auto& h : handovers_)
      if (h.fd >= 0) close(h.fd);
    handovers_.clear();
    snapshot_.clear();
  }
  count_ = 0;
  for (const auto& n : nets_)
    if (n.hub) n.hub->set_events(false);
  if (listen_fd_ >= 0) close(listen_fd_);
  listen_fd_ = -1;
  port_ = 0;
  for (int* p : {stop_pipe_, handover_pipe_})
    for (int k = 0; k < 2; ++k) {
      if (p[k] >= 0) close(p[k]);
      p[k] = -1;
    }
}

bool Cia309Server::open_listener() {
  const bool v6 = cfg_.bind == "::1";
  const unsigned want = any_port_ ? 0 : cfg_.port;
  int fd = socket(v6 ? AF_INET6 : AF_INET, SOCK_STREAM | SOCK_CLOEXEC | SOCK_NONBLOCK, 0);
  std::string why;
  if (fd < 0) {
    why = std::strerror(errno);
  } else {
    int one = 1;
    setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &one, sizeof one);
    int r;
    if (v6) {
      sockaddr_in6 a{};
      a.sin6_family = AF_INET6;
      a.sin6_port = htons(static_cast<uint16_t>(want));
      a.sin6_addr = in6addr_loopback;
      r = bind(fd, reinterpret_cast<sockaddr*>(&a), sizeof a);
    } else {
      sockaddr_in a{};
      a.sin_family = AF_INET;
      a.sin_port = htons(static_cast<uint16_t>(want));
      a.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
      r = bind(fd, reinterpret_cast<sockaddr*>(&a), sizeof a);
    }
    if (r != 0 || listen(fd, 8) != 0) {
      why = std::strerror(errno);
      close(fd);
      fd = -1;
    }
  }
  const std::string where = (v6 ? "[::1]" : "127.0.0.1") + std::string(":");
  if (fd < 0) {
    if (!warned_listen_)
      log_warn("cia309: cannot listen on %s%u: %s; CANopen runs without the plain CiA 309-3 port, retrying every "
               "%lld s",
               where.c_str(), want, why.c_str(), (long long)kRetryListen.count());
    warned_listen_ = true;
    return false;
  }
  sockaddr_storage got{};
  socklen_t len = sizeof got;
  getsockname(fd, reinterpret_cast<sockaddr*>(&got), &len);
  unsigned port = v6 ? ntohs(reinterpret_cast<sockaddr_in6*>(&got)->sin6_port)
                     : ntohs(reinterpret_cast<sockaddr_in*>(&got)->sin_port);
  listen_fd_ = fd;
  port_ = port;
  warned_listen_ = false;
  std::string mode = cfg_.allow_changes ? "changes allowed (SDO downloads, NMT and LSS)" : "read-only";
  mode += cfg_.allow_force ? ", force allowed on OPERATIONAL nodes" : "";
  log_info("CiA 309-3 gateway listens on %s%u (loopback only; other machines through the diagnostics channel), %s; "
           "networks %s",
           where.c_str(), port, mode.c_str(), numbering_text().c_str());
  return true;
}

void Cia309Server::publish() {
  std::vector<SessionInfo> snap;
  for (const auto& c : conns_) {
    SessionInfo s;
    s.peer = c.session->peer();
    s.tunnelled = c.session->tunnelled();
    s.served = c.session->served();
    snap.push_back(std::move(s));
  }
  std::lock_guard<std::mutex> lock(mutex_);
  snapshot_.swap(snap);
}

void Cia309Server::adopt(Handover h, std::chrono::steady_clock::time_point now) {
  Conn c;
  c.fd = h.fd;
  c.tls = std::move(h.tls);
  c.session.reset(new Cia309Session(cfg_, nets_, h.peer, true, version_));
  log_info("cia309: session from %s through the diagnostics channel", h.peer.c_str());
  conns_.push_back(std::move(c));
  if (!h.in.empty() && !conns_.back().session->feed(h.in.data(), h.in.size(), now)) conns_.back().closing = true;
}

void Cia309Server::accept_clients() {
  for (;;) {
    sockaddr_storage a{};
    socklen_t len = sizeof a;
    int fd = accept4(listen_fd_, reinterpret_cast<sockaddr*>(&a), &len, SOCK_CLOEXEC | SOCK_NONBLOCK);
    if (fd < 0) return;
    char addr[INET6_ADDRSTRLEN] = "?";
    if (a.ss_family == AF_INET6)
      inet_ntop(AF_INET6, &reinterpret_cast<sockaddr_in6*>(&a)->sin6_addr, addr, sizeof addr);
    else
      inet_ntop(AF_INET, &reinterpret_cast<sockaddr_in*>(&a)->sin_addr, addr, sizeof addr);
    bool full;
    {
      std::lock_guard<std::mutex> lock(mutex_);
      full = count_.load() >= cfg_.max_clients;
      if (!full) ++count_;
    }
    if (full) {
      static const char kFull[] = "ERROR: 102 (too many gateway clients)\r\n";
      ssize_t r = send(fd, kFull, sizeof kFull - 1, MSG_NOSIGNAL | MSG_DONTWAIT);
      (void)r;
      close(fd);
      log_warn("cia309: connection from %s refused: %u gateway sessions open (cia309.max_clients)", addr,
               cfg_.max_clients);
      continue;
    }
    int one = 1;
    setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof one);
    Conn c;
    c.fd = fd;
    c.session.reset(new Cia309Session(cfg_, nets_, addr, false, version_));
    log_info("cia309: session from %s on the plain port", addr);
    conns_.push_back(std::move(c));
  }
}

size_t Cia309Server::pending(const Conn& c) const {
  return c.session->output().size() + (c.tls ? c.tls->wire().size() : 0);
}

void Cia309Server::on_bytes(Conn& c, const char* data, size_t n, std::chrono::steady_clock::time_point now) {
  if (c.tls) {
    std::string plain, why;
    if (!c.tls->feed(data, n, plain, why)) {
      c.closing = true;
      return;
    }
    if (!plain.empty() && !c.session->feed(plain.data(), plain.size(), now)) c.closing = true;
  } else if (!c.session->feed(data, n, now)) {
    c.closing = true;
  }
}

bool Cia309Server::flush(Conn& c) {
  std::string& out = c.session->output();
  std::string* buf = &out;
  if (c.tls) {
    std::string why;
    if (!out.empty()) {
      if (!c.tls->write(out, why)) return false;
      out.clear();
    }
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

void Cia309Server::close_conn(size_t i, const char* why) {
  Conn& c = conns_[i];
  if (why) log_info("cia309: session from %s closed (%s)", c.session->peer().c_str(), why);
  if (c.fd >= 0) close(c.fd);
  conns_.erase(conns_.begin() + static_cast<long>(i));
  if (count_.load()) --count_;
}

void Cia309Server::run() {
  pthread_setname_np(pthread_self(), "canworks_cia309");
  using clock = std::chrono::steady_clock;
  const bool plain_port = cfg_.port || any_port_;
  for (;;) {
    auto now = clock::now();
    if (plain_port && listen_fd_ < 0 && now >= next_listen_try_) {
      if (!open_listener()) next_listen_try_ = now + kRetryListen;
    }
    // Events only while a session is open: the bus thread records none
    // otherwise.
    for (const auto& n : nets_)
      if (n.hub && n.hub->events_on() != !conns_.empty()) n.hub->set_events(!conns_.empty());

    std::vector<pollfd> fds;
    fds.push_back({stop_pipe_[0], POLLIN, 0});
    fds.push_back({handover_pipe_[0], POLLIN, 0});
    fds.push_back({listen_fd_, static_cast<short>(listen_fd_ >= 0 ? POLLIN : 0), 0});
    for (const auto& n : nets_) {
      int fd = n.hub ? n.hub->gateway_wake_fd() : -1;
      fds.push_back({fd, static_cast<short>(fd >= 0 ? POLLIN : 0), 0});
    }
    const size_t first_conn = fds.size();
    auto due = clock::time_point::max();
    for (auto& c : conns_) {
      due = std::min(due, c.session->poll(now));
      short ev = pending(c) ? POLLOUT : 0;
      // A session whose answers are not read is not read either.
      if (!c.closing && pending(c) <= kMaxSendBuffer) ev |= POLLIN;
      fds.push_back({c.fd, ev, 0});
    }
    int timeout = 1000;
    if (plain_port && listen_fd_ < 0) timeout = 1000;
    if (due != clock::time_point::max()) {
      auto left = std::chrono::duration_cast<std::chrono::milliseconds>(due - now).count();
      timeout = static_cast<int>(std::max<long long>(0, std::min<long long>(timeout, left + 1)));
    }
    int r = poll(fds.data(), fds.size(), timeout);
    if (r < 0 && errno != EINTR) {
      log_error("cia309: poll failed: %s; the CiA 309-3 gateway stops", std::strerror(errno));
      return;
    }
    if (fds[0].revents) return;
    now = clock::now();

    // Connections switched over from the diagnostics channel.
    if (fds[1].revents & POLLIN) {
      drain(handover_pipe_[0]);
      std::vector<Handover> got;
      {
        std::lock_guard<std::mutex> lock(mutex_);
        got.swap(handovers_);
      }
      for (auto& h : got) adopt(std::move(h), now);
    }

    // Answers and events from the bus threads.
    for (size_t n = 0; n < nets_.size(); ++n) {
      DiagHub* hub = nets_[n].hub;
      if (!hub) continue;
      std::vector<std::pair<uint64_t, std::string>> answers;
      hub->take_gateway_answers(answers);
      for (auto& a : answers)
        for (auto& c : conns_)
          if (c.session->answer(n, a.first, a.second, now)) break;
      std::vector<DiagEvent> events;
      uint64_t lost = hub->take_events(events);
      for (auto& c : conns_) {
        if (lost) c.session->lost(lost);
        for (const auto& e : events) c.session->event(n, e);
      }
    }

    // Client I/O, for the connections that existed before this poll.
    const size_t polled = fds.size() - first_conn;
    for (size_t i = 0; i < polled && i < conns_.size(); ++i) {
      Conn& c = conns_[i];
      short re = fds[first_conn + i].revents;
      if (re & (POLLERR | POLLNVAL)) {
        c.closing = true;
        continue;
      }
      if (re & (POLLIN | POLLHUP)) {
        char buf[4096];
        ssize_t n = recv(c.fd, buf, sizeof buf, 0);
        if (n > 0)
          on_bytes(c, buf, static_cast<size_t>(n), now);
        else if (n == 0 || (errno != EAGAIN && errno != EWOULDBLOCK))
          c.closing = true;
      }
    }
    for (auto& c : conns_) c.session->poll(now);
    for (size_t i = conns_.size(); i-- > 0;) {
      Conn& c = conns_[i];
      if (c.closing) {
        flush(c);  // what is ready still goes out, if the socket takes it
        close_conn(i, "disconnected");
        continue;
      }
      if (!flush(c)) {
        close_conn(i, "connection lost");
        continue;
      }
      if (pending(c) > kMaxSendBuffer) {
        if (c.over_since == clock::time_point{}) {
          c.over_since = now;
        } else if (now - c.over_since >= kStalledFor) {
          log_warn("cia309: client %s does not read its answers (%zu bytes waiting for %lld s); closing the session",
                   c.session->peer().c_str(), pending(c), (long long)kStalledFor.count());
          close_conn(i, nullptr);
          continue;
        }
      } else {
        c.over_since = {};
      }
    }
    if (listen_fd_ >= 0 && (fds[2].revents & POLLIN)) accept_clients();
    publish();
  }
}

}  // namespace canopen_plugin
