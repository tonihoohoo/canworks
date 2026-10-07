#include "control.h"

#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <netdb.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <poll.h>
#include <sys/socket.h>
#include <unistd.h>

#include <algorithm>
#include <chrono>
#include <cstdlib>
#include <cstring>
#include <fstream>

#include "cJSON.h"

namespace sim_tool {

namespace {

constexpr size_t kMaxClients = 8;
constexpr size_t kMaxLine = 1 << 20;   // a request line
constexpr size_t kMaxOut = 4 << 20;    // unread answers before a client is dropped

std::string trim(const std::string& s) {
  size_t b = s.find_first_not_of(" \t\r\n");
  if (b == std::string::npos) return "";
  size_t e = s.find_last_not_of(" \t\r\n");
  return s.substr(b, e - b + 1);
}

bool tokens_equal(const std::string& a, const std::string& b) {
  // Constant time in the length of the expected token.
  unsigned char diff = a.size() == b.size() ? 0 : 1;
  for (size_t i = 0; i < b.size(); ++i) diff |= static_cast<unsigned char>(b[i] ^ (i < a.size() ? a[i] : 0));
  return diff == 0;
}

std::string peer_name(const sockaddr_storage& ss) {
  char host[INET6_ADDRSTRLEN] = "?";
  unsigned port = 0;
  if (ss.ss_family == AF_INET) {
    const sockaddr_in* a = reinterpret_cast<const sockaddr_in*>(&ss);
    inet_ntop(AF_INET, &a->sin_addr, host, sizeof host);
    port = ntohs(a->sin_port);
    return std::string(host) + ":" + std::to_string(port);
  }
  if (ss.ss_family == AF_INET6) {
    const sockaddr_in6* a = reinterpret_cast<const sockaddr_in6*>(&ss);
    inet_ntop(AF_INET6, &a->sin6_addr, host, sizeof host);
    port = ntohs(a->sin6_port);
  }
  return "[" + std::string(host) + "]:" + std::to_string(port);
}

void set_nonblock(int fd) { fcntl(fd, F_SETFL, fcntl(fd, F_GETFL, 0) | O_NONBLOCK); }

std::string error_line(const std::string& id, const std::string& msg) {
  cJSON* o = cJSON_CreateObject();
  if (!id.empty()) {
    cJSON* v = cJSON_Parse(id.c_str());
    cJSON_AddItemToObject(o, "id", v ? v : cJSON_CreateNull());
  }
  cJSON_AddBoolToObject(o, "ok", false);
  cJSON_AddStringToObject(o, "error", msg.c_str());
  char* p = cJSON_PrintUnformatted(o);
  std::string s = p;
  cJSON_free(p);
  cJSON_Delete(o);
  return s;
}

}  // namespace

bool split_host_port(const std::string& text, unsigned default_port, std::string& host, unsigned& port) {
  port = default_port;
  std::string p;
  if (!text.empty() && text[0] == '[') {
    size_t e = text.find(']');
    if (e == std::string::npos) return false;
    host = text.substr(1, e - 1);
    if (e + 1 < text.size()) {
      if (text[e + 1] != ':') return false;
      p = text.substr(e + 2);
    }
  } else if (std::count(text.begin(), text.end(), ':') == 1) {
    size_t c = text.find(':');
    host = text.substr(0, c);
    p = text.substr(c + 1);
  } else {
    host = text;  // a name, IPv4, or a bare IPv6 address
  }
  if (host.empty()) return false;
  if (!p.empty() || (text.size() && text.back() == ':')) {
    char* end = nullptr;
    unsigned long v = std::strtoul(p.c_str(), &end, 10);
    if (p.empty() || *end || v == 0 || v > 65535) return false;
    port = static_cast<unsigned>(v);
  }
  return true;
}

bool resolve_token(const std::string& token, const std::string& token_file, const char* env, std::string& out,
                   std::string& err) {
  out.clear();
  if (!token.empty()) {
    out = token;
    return true;
  }
  if (!token_file.empty()) {
    std::ifstream in(token_file);
    if (!in) {
      err = "cannot read the token file " + token_file;
      return false;
    }
    std::string line;
    std::getline(in, line);
    out = trim(line);
    if (out.empty()) {
      err = "the token file " + token_file + " is empty";
      return false;
    }
    return true;
  }
  if (env) {
    const char* v = std::getenv(env);
    if (v) out = v;
  }
  return true;
}

bool is_loopback(const std::string& addr) {
  if (addr == "localhost" || addr == "::1") return true;
  in_addr a4;
  if (inet_pton(AF_INET, addr.c_str(), &a4) == 1) return (ntohl(a4.s_addr) >> 24) == 127;
  return false;
}

// ---- server ----

ControlServer::ControlServer(std::string version, std::string token, Handler handler)
    : version_(std::move(version)), token_(std::move(token)), handler_(std::move(handler)) {}

ControlServer::~ControlServer() {
  for (auto& c : clients_) close(c.fd);
  if (fd_ >= 0) close(fd_);
}

bool ControlServer::listen(const std::string& bind_addr, unsigned port, std::string& err) {
  addrinfo hints;
  std::memset(&hints, 0, sizeof hints);
  hints.ai_family = AF_UNSPEC;
  hints.ai_socktype = SOCK_STREAM;
  hints.ai_flags = AI_PASSIVE;
  addrinfo* res = nullptr;
  std::string service = std::to_string(port);
  int rc = getaddrinfo(bind_addr.empty() ? nullptr : bind_addr.c_str(), service.c_str(), &hints, &res);
  if (rc != 0) {
    err = "cannot bind to " + bind_addr + ": " + gai_strerror(rc);
    return false;
  }
  err.clear();
  for (addrinfo* ai = res; ai; ai = ai->ai_next) {
    int fd = socket(ai->ai_family, ai->ai_socktype | SOCK_CLOEXEC, ai->ai_protocol);
    if (fd < 0) continue;
    int one = 1;
    setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &one, sizeof one);
    if (::bind(fd, ai->ai_addr, ai->ai_addrlen) == 0 && ::listen(fd, 8) == 0) {
      set_nonblock(fd);
      fd_ = fd;
      sockaddr_storage ss;
      std::memcpy(&ss, ai->ai_addr, ai->ai_addrlen);
      address_ = peer_name(ss);
      break;
    }
    err = std::strerror(errno);
    close(fd);
  }
  freeaddrinfo(res);
  if (fd_ < 0) {
    err = "cannot listen on " + bind_addr + ":" + service + (err.empty() ? "" : ": " + err);
    return false;
  }
  return true;
}

void ControlServer::accept_all() {
  while (true) {
    sockaddr_storage ss;
    socklen_t len = sizeof ss;
    int fd = accept4(fd_, reinterpret_cast<sockaddr*>(&ss), &len, SOCK_NONBLOCK | SOCK_CLOEXEC);
    if (fd < 0) return;
    if (clients_.size() >= kMaxClients) {
      std::string line = error_line("", "too many clients") + "\n";
      if (send(fd, line.data(), line.size(), MSG_NOSIGNAL | MSG_DONTWAIT) < 0) {
      }
      close(fd);
      continue;
    }
    int one = 1;
    setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof one);
    Client c;
    c.fd = fd;
    c.peer = peer_name(ss);
    clients_.push_back(c);
  }
}

void ControlServer::flush(Client& c) {
  while (!c.out.empty()) {
    ssize_t n = send(c.fd, c.out.data(), c.out.size(), MSG_NOSIGNAL | MSG_DONTWAIT);
    if (n > 0) {
      c.out.erase(0, static_cast<size_t>(n));
      continue;
    }
    if (n < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) break;
    c.closing = true;
    c.out.clear();
    return;
  }
  if (c.out.size() > kMaxOut) c.closing = true;  // it stopped reading its answers
}

void ControlServer::handle_line(Client& c, const std::string& raw) {
  std::string line = trim(raw);
  if (line.empty()) return;
  cJSON* req = cJSON_Parse(line.c_str());
  std::string id;
  if (cJSON_IsObject(req)) {
    const cJSON* idj = cJSON_GetObjectItemCaseSensitive(req, "id");
    if (idj) {
      char* p = cJSON_PrintUnformatted(idj);
      id = p;
      cJSON_free(p);
    }
  }
  const cJSON* opj = cJSON_IsObject(req) ? cJSON_GetObjectItemCaseSensitive(req, "op") : nullptr;
  std::string op = cJSON_IsString(opj) ? opj->valuestring : "";
  std::string answer;
  if (!cJSON_IsObject(req)) {
    if (!token_.empty() && !c.greeted) c.closing = true;
    answer = error_line("", "a request must be one JSON object per line");
  } else if (op == "hello") {
    const cJSON* tj = cJSON_GetObjectItemCaseSensitive(req, "token");
    std::string tok = cJSON_IsString(tj) ? tj->valuestring : "";
    if (!token_.empty() && !tokens_equal(tok, token_)) {
      // As the diagnostics channel: a wrong token closes without an answer.
      c.closing = true;
      c.out.clear();
      cJSON_Delete(req);
      return;
    }
    c.greeted = true;
    cJSON* o = cJSON_CreateObject();
    if (!id.empty()) cJSON_AddItemToObject(o, "id", cJSON_Parse(id.c_str()));
    cJSON_AddBoolToObject(o, "ok", true);
    cJSON* r = cJSON_AddObjectToObject(o, "result");
    cJSON_AddNumberToObject(r, "protocol", kProtocol);
    cJSON_AddStringToObject(r, "version", version_.c_str());
    cJSON_AddBoolToObject(r, "simulator", true);
    char* p = cJSON_PrintUnformatted(o);
    answer = p;
    cJSON_free(p);
    cJSON_Delete(o);
  } else if (!token_.empty() && !c.greeted) {
    answer = error_line(id, "the first request must be {\"op\": \"hello\", \"token\": ...}");
    c.closing = true;
  } else {
    answer = handler_(req, id, c.peer);
  }
  cJSON_Delete(req);
  c.out += answer + "\n";
}

void ControlServer::read_client(Client& c) {
  char buf[4096];
  while (!c.closing) {
    ssize_t n = recv(c.fd, buf, sizeof buf, MSG_DONTWAIT);
    if (n == 0) {
      c.closing = true;
      return;
    }
    if (n < 0) {
      if (errno != EAGAIN && errno != EWOULDBLOCK) c.closing = true;
      return;
    }
    c.in.append(buf, static_cast<size_t>(n));
    size_t nl;
    while (!c.closing && (nl = c.in.find('\n')) != std::string::npos) {
      std::string line = c.in.substr(0, nl);
      c.in.erase(0, nl + 1);
      handle_line(c, line);
    }
    if (c.in.size() > kMaxLine) {
      c.out += error_line("", "request line too long") + "\n";
      c.closing = true;
    }
  }
}

void ControlServer::poll_once() {
  if (fd_ < 0) return;
  std::vector<pollfd> fds;
  fds.push_back({fd_, POLLIN, 0});
  for (const auto& c : clients_) fds.push_back({c.fd, static_cast<short>(POLLIN | (c.out.empty() ? 0 : POLLOUT)), 0});
  if (::poll(fds.data(), fds.size(), 0) <= 0) return;
  for (size_t i = 0; i < clients_.size(); ++i) {
    short ev = fds[i + 1].revents;
    if (ev & (POLLIN | POLLHUP | POLLERR)) read_client(clients_[i]);
    if (ev & (POLLHUP | POLLERR) && !(ev & POLLIN)) clients_[i].closing = true;
    flush(clients_[i]);
  }
  for (size_t i = 0; i < clients_.size();) {
    Client& c = clients_[i];
    if (c.closing) {
      if (!c.out.empty()) flush(c);  // the last answer (an error) still goes out
      close(c.fd);
      clients_.erase(clients_.begin() + static_cast<long>(i));
    } else {
      ++i;
    }
  }
  if (fds[0].revents & POLLIN) accept_all();
}

// ---- client ----

ControlClient::~ControlClient() {
  if (fd_ >= 0) close(fd_);
  cJSON_Delete(hello_);
}

bool ControlClient::send_line(const std::string& line, std::string& err) {
  std::string s = line + "\n";
  size_t off = 0;
  while (off < s.size()) {
    ssize_t n = send(fd_, s.data() + off, s.size() - off, MSG_NOSIGNAL);
    if (n < 0) {
      if (errno == EINTR) continue;
      err = std::string("connection lost: ") + std::strerror(errno);
      return false;
    }
    off += static_cast<size_t>(n);
  }
  return true;
}

bool ControlClient::read_line(std::string& line, int timeout_ms, std::string& err) {
  auto end = std::chrono::steady_clock::now() + std::chrono::milliseconds(timeout_ms);
  while (true) {
    size_t nl = buf_.find('\n');
    if (nl != std::string::npos) {
      line = buf_.substr(0, nl);
      buf_.erase(0, nl + 1);
      return true;
    }
    long left = static_cast<long>(
        std::chrono::duration_cast<std::chrono::milliseconds>(end - std::chrono::steady_clock::now()).count());
    if (left <= 0) {
      err = "no answer within " + std::to_string(timeout_ms / 1000) + " s";
      return false;
    }
    pollfd p = {fd_, POLLIN, 0};
    int r = ::poll(&p, 1, static_cast<int>(left));
    if (r < 0 && errno == EINTR) continue;
    if (r <= 0) continue;
    char b[4096];
    ssize_t n = recv(fd_, b, sizeof b, 0);
    if (n == 0) {
      err = "connection closed";
      return false;
    }
    if (n < 0) {
      if (errno == EINTR) continue;
      err = std::string("connection lost: ") + std::strerror(errno);
      return false;
    }
    buf_.append(b, static_cast<size_t>(n));
  }
}

bool ControlClient::connect(const std::string& host, unsigned port, const std::string& token, std::string& err) {
  addrinfo hints;
  std::memset(&hints, 0, sizeof hints);
  hints.ai_family = AF_UNSPEC;
  hints.ai_socktype = SOCK_STREAM;
  addrinfo* res = nullptr;
  std::string service = std::to_string(port);
  int rc = getaddrinfo(host.c_str(), service.c_str(), &hints, &res);
  if (rc != 0) {
    err = "cannot resolve " + host + ": " + gai_strerror(rc);
    return false;
  }
  std::string why = "no address";
  for (addrinfo* ai = res; ai && fd_ < 0; ai = ai->ai_next) {
    int fd = socket(ai->ai_family, ai->ai_socktype | SOCK_CLOEXEC, ai->ai_protocol);
    if (fd < 0) continue;
    // Connect with a 5 s limit.
    set_nonblock(fd);
    int c = ::connect(fd, ai->ai_addr, ai->ai_addrlen);
    if (c < 0 && errno == EINPROGRESS) {
      pollfd p = {fd, POLLOUT, 0};
      if (::poll(&p, 1, 5000) == 1) {
        int so = 0;
        socklen_t sl = sizeof so;
        getsockopt(fd, SOL_SOCKET, SO_ERROR, &so, &sl);
        c = so ? -1 : 0;
        errno = so ? so : ETIMEDOUT;
      } else {
        errno = ETIMEDOUT;
      }
    }
    if (c == 0) {
      fcntl(fd, F_SETFL, fcntl(fd, F_GETFL, 0) & ~O_NONBLOCK);
      fd_ = fd;
    } else {
      why = std::strerror(errno);
      close(fd);
    }
  }
  freeaddrinfo(res);
  if (fd_ < 0) {
    err = "cannot connect to " + host + ":" + service + ": " + why;
    return false;
  }
  cJSON* h = cJSON_CreateObject();
  cJSON_AddStringToObject(h, "op", "hello");
  cJSON_AddStringToObject(h, "token", token.c_str());
  std::string e;
  cJSON* a = request(h, e, 10000);
  cJSON_Delete(h);
  if (!a) {
    err = host + ":" + service + ": " +
          (e == "connection closed" ? std::string("the hello was refused (wrong or missing token?)") : e);
    return false;
  }
  std::string ae = answer_error(a);
  if (!ae.empty()) {
    err = host + ":" + service + ": " + ae;
    cJSON_Delete(a);
    return false;
  }
  hello_ = cJSON_DetachItemFromObjectCaseSensitive(a, "result");
  cJSON_Delete(a);
  return true;
}

cJSON* ControlClient::request(cJSON* req, std::string& err, int timeout_ms) {
  unsigned id = next_id_++;
  cJSON_DeleteItemFromObjectCaseSensitive(req, "id");
  cJSON_AddNumberToObject(req, "id", id);
  char* p = cJSON_PrintUnformatted(req);
  std::string line = p;
  cJSON_free(p);
  if (!send_line(line, err)) return nullptr;
  while (true) {
    std::string in;
    if (!read_line(in, timeout_ms, err)) return nullptr;
    cJSON* a = cJSON_Parse(in.c_str());
    if (!cJSON_IsObject(a)) {
      cJSON_Delete(a);
      err = "the answer is not JSON";
      return nullptr;
    }
    const cJSON* idj = cJSON_GetObjectItemCaseSensitive(a, "id");
    // Answers to other requests (none in this client) and id-less error
    // lines: an id-less error is ours.
    if (!idj && cJSON_IsFalse(cJSON_GetObjectItemCaseSensitive(a, "ok"))) return a;
    if (cJSON_IsNumber(idj) && static_cast<unsigned>(idj->valuedouble) == id) return a;
    cJSON_Delete(a);
  }
}

std::string answer_error(const cJSON* answer) {
  if (cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(answer, "ok"))) return "";
  const cJSON* e = cJSON_GetObjectItemCaseSensitive(answer, "error");
  return cJSON_IsString(e) ? e->valuestring : "request failed";
}

}  // namespace sim_tool
