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

using canopen_plugin::Bytes;
using canopen_plugin::TlsConn;

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
    : version_(std::move(version)), token_(std::move(token)), handler_(std::move(handler)) {
  if (!token_.empty())
    verifier_ = canopen_plugin::make_scram_verifier(token_, canopen_plugin::random_bytes(16),
                                                    canopen_plugin::kScramDefaultIterations);
}

ControlServer::~ControlServer() {
  for (auto& c : clients_) close(c.fd);
  if (fd_ >= 0) close(fd_);
}

bool ControlServer::listen(const std::string& bind_addr, unsigned port, std::string& err) {
  if (!tls_id_.ready() && !tls_id_.create(err)) {
    err = "cannot make the TLS key: " + err;
    return false;
  }
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
      // The bound address, with the port the system chose for port 0.
      sockaddr_storage ss;
      socklen_t len = sizeof ss;
      if (getsockname(fd, reinterpret_cast<sockaddr*>(&ss), &len) != 0) std::memcpy(&ss, ai->ai_addr, ai->ai_addrlen);
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
    clients_.push_back(std::move(c));
  }
}

void ControlServer::flush(Client& c) {
  std::string* buf = &c.out;
  if (c.tls) {
    std::string why;
    if (!c.tls->write(c.out, why)) {
      c.closing = true;
      c.out.clear();
      return;
    }
    c.out.clear();
    buf = &c.tls->wire();
  }
  while (!buf->empty()) {
    ssize_t n = send(c.fd, buf->data(), buf->size(), MSG_NOSIGNAL | MSG_DONTWAIT);
    if (n > 0) {
      buf->erase(0, static_cast<size_t>(n));
      continue;
    }
    if (n < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) break;
    c.closing = true;
    buf->clear();
    return;
  }
  if (buf->size() > kMaxOut) c.closing = true;  // it stopped reading its answers
}

void ControlServer::on_wire(Client& c, const char* data, size_t n) {
  if (c.mode == 0 && n) {
    if (static_cast<unsigned char>(data[0]) == canopen_plugin::kTlsHandshakeByte) {
      std::string why;
      c.tls = TlsConn::server(tls_id_, why);
      if (!c.tls) {
        c.closing = true;
        return;
      }
      c.mode = 2;
    } else {
      c.mode = 1;
    }
  }
  if (c.mode == 2) {
    std::string plain, why;
    if (!c.tls->feed(data, n, plain, why)) {
      c.closing = true;
      c.out.clear();
      return;
    }
    c.in += plain;
  } else {
    c.in.append(data, n);
  }
}

void ControlServer::login(Client& c, const std::string& id, const std::string& op, const cJSON* req) {
  using namespace canopen_plugin;
  if (token_.empty()) {
    c.out += error_line(id, "this simulator has no token; connect without one") + "\n";
    c.closing = true;
    return;
  }
  const std::string salt = b64_encode(verifier_.salt);
  if (op == "hello" && c.snonce.empty()) {
    const cJSON* mech = cJSON_GetObjectItemCaseSensitive(req, "mech");
    const cJSON* nonce = cJSON_GetObjectItemCaseSensitive(req, "nonce");
    Bytes raw;
    if (!cJSON_IsString(mech) || std::string(mech->valuestring) != kScramMechanism || !cJSON_IsString(nonce) ||
        !b64_decode(nonce->valuestring, raw) || raw.size() < 16 || raw.size() > 64) {
      c.closing = true;
      c.out.clear();
      return;
    }
    c.cnonce = nonce->valuestring;
    c.snonce = b64_encode(random_bytes(kScramNonceBytes));
    cJSON* o = cJSON_CreateObject();
    if (!id.empty()) cJSON_AddItemToObject(o, "id", cJSON_Parse(id.c_str()));
    cJSON_AddBoolToObject(o, "ok", true);
    cJSON* r = cJSON_AddObjectToObject(o, "result");
    cJSON_AddNumberToObject(r, "protocol", kTlsProtocol);
    cJSON_AddStringToObject(r, "nonce", c.snonce.c_str());
    cJSON_AddStringToObject(r, "salt", salt.c_str());
    cJSON_AddNumberToObject(r, "iterations", verifier_.iterations);
    char* p = cJSON_PrintUnformatted(o);
    c.out += std::string(p) + "\n";
    cJSON_free(p);
    cJSON_Delete(o);
    return;
  }
  const cJSON* proof = cJSON_GetObjectItemCaseSensitive(req, "proof");
  Bytes pr;
  std::string auth;
  if (op == "login" && !c.snonce.empty() && cJSON_IsString(proof) && b64_decode(proof->valuestring, pr))
    auth = scram_auth_message(c.cnonce, c.snonce, salt, verifier_.iterations, tls_id_.cert_hash());
  if (auth.empty() || !scram_check_proof(verifier_, auth, pr)) {
    // As the diagnostics channel: a wrong token closes without an answer.
    c.closing = true;
    c.out.clear();
    return;
  }
  c.greeted = true;
  cJSON* o = cJSON_CreateObject();
  if (!id.empty()) cJSON_AddItemToObject(o, "id", cJSON_Parse(id.c_str()));
  cJSON_AddBoolToObject(o, "ok", true);
  cJSON* r = cJSON_AddObjectToObject(o, "result");
  cJSON_AddNumberToObject(r, "protocol", kTlsProtocol);
  cJSON_AddStringToObject(r, "version", version_.c_str());
  cJSON_AddBoolToObject(r, "simulator", true);
  cJSON_AddStringToObject(r, "signature", b64_encode(scram_server_signature(verifier_, auth)).c_str());
  char* p = cJSON_PrintUnformatted(o);
  c.out += std::string(p) + "\n";
  cJSON_free(p);
  cJSON_Delete(o);
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
    if (!c.greeted && (c.mode == 2 || !token_.empty())) c.closing = true;
    answer = error_line("", "a request must be one JSON object per line");
  } else if (c.mode == 2 && !c.greeted) {
    login(c, id, op, req);
    cJSON_Delete(req);
    return;
  } else if (c.mode != 2 && !token_.empty()) {
    answer = error_line(id, "this simulator needs an encrypted connection; update canworks-diag");
    c.closing = true;
  } else if (op == "hello") {
    if (c.greeted) {
      answer = error_line(id, "already logged in");
    } else {
      // A simulator without a token, on loopback: the plain hello.
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
    }
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
    on_wire(c, buf, static_cast<size_t>(n));
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
  for (const auto& c : clients_)
    fds.push_back({c.fd, static_cast<short>(POLLIN | (c.out.empty() && !(c.tls && !c.tls->wire().empty()) ? 0 : POLLOUT)), 0});
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
      flush(c);  // the last answer (an error) still goes out
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

bool ControlClient::send_wire(std::string& err) {
  std::string& w = tls_->wire();
  size_t off = 0;
  while (off < w.size()) {
    ssize_t n = send(fd_, w.data() + off, w.size() - off, MSG_NOSIGNAL);
    if (n < 0) {
      if (errno == EINTR) continue;
      err = std::string("connection lost: ") + std::strerror(errno);
      return false;
    }
    off += static_cast<size_t>(n);
  }
  w.clear();
  return true;
}

bool ControlClient::send_line(const std::string& line, std::string& err) {
  std::string s = line + "\n";
  if (tls_) {
    if (!tls_->write(s, err)) return false;
    return send_wire(err);
  }
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
      err = tls_ && !tls_->established() ? "no TLS handshake" : "connection closed";
      return false;
    }
    if (n < 0) {
      if (errno == EINTR) continue;
      err = std::string("connection lost: ") + std::strerror(errno);
      return false;
    }
    if (tls_) {
      std::string why;
      bool was = tls_->established();
      if (!tls_->feed(b, static_cast<size_t>(n), buf_, why)) {
        err = was ? "connection closed" : "no TLS handshake";
        return false;
      }
      if (!send_wire(err)) return false;
    } else {
      buf_.append(b, static_cast<size_t>(n));
    }
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
  std::string where = host + ":" + service;
  if (!token.empty()) return login(token, where, err);
  cJSON* h = cJSON_CreateObject();
  cJSON_AddStringToObject(h, "op", "hello");
  std::string e;
  cJSON* a = request(h, e, 10000);
  cJSON_Delete(h);
  if (!a) {
    err = where + ": " + e;
    return false;
  }
  std::string ae = answer_error(a);
  if (!ae.empty()) {
    err = where + ": " + ae;
    cJSON_Delete(a);
    return false;
  }
  hello_ = cJSON_DetachItemFromObjectCaseSensitive(a, "result");
  cJSON_Delete(a);
  return true;
}

bool ControlClient::login(const std::string& token, const std::string& where, std::string& err) {
  using namespace canopen_plugin;
  std::string e;
  tls_ = TlsConn::client(e);
  if (!tls_ || !tls_->start(e) || !send_wire(e)) {
    err = where + ": TLS: " + e;
    return false;
  }
  auto fail = [&](const std::string& why) {
    if (why == "no TLS handshake" || why.find("no answer within") == 0)
      err = where + ": no encrypted connection: the plugin (or simulator) there is too old for encrypted "
                    "diagnostics; update it";
    else if (why == "connection closed")
      err = where + ": the login was refused (wrong token)";
    else
      err = where + ": " + why;
    return false;
  };
  std::string cnonce = b64_encode(random_bytes(kScramNonceBytes));
  cJSON* h = cJSON_CreateObject();
  cJSON_AddStringToObject(h, "op", "hello");
  cJSON_AddStringToObject(h, "mech", kScramMechanism);
  cJSON_AddStringToObject(h, "nonce", cnonce.c_str());
  cJSON* a = request(h, e, 10000);
  cJSON_Delete(h);
  if (!a) return fail(e);
  std::string ae = answer_error(a);
  const cJSON* r = cJSON_GetObjectItemCaseSensitive(a, "result");
  const cJSON* sn = cJSON_GetObjectItemCaseSensitive(r, "nonce");
  const cJSON* sa = cJSON_GetObjectItemCaseSensitive(r, "salt");
  const cJSON* it = cJSON_GetObjectItemCaseSensitive(r, "iterations");
  Bytes salt;
  if (!ae.empty() || !cJSON_IsString(sn) || !cJSON_IsString(sa) || !cJSON_IsNumber(it) ||
      !b64_decode(sa->valuestring, salt) || it->valuedouble < kScramMinIterations ||
      it->valuedouble > kScramMaxIterations) {
    cJSON_Delete(a);
    return fail(ae.empty() ? "unexpected login answer" : ae);
  }
  unsigned iterations = static_cast<unsigned>(it->valuedouble);
  std::string auth = scram_auth_message(cnonce, sn->valuestring, sa->valuestring, iterations, tls_->peer_cert_hash());
  cJSON_Delete(a);
  Bytes proof, want;
  scram_client(token, salt, iterations, auth, proof, want);
  cJSON* l = cJSON_CreateObject();
  cJSON_AddStringToObject(l, "op", "login");
  cJSON_AddStringToObject(l, "proof", b64_encode(proof).c_str());
  a = request(l, e, 10000);
  cJSON_Delete(l);
  if (!a) return fail(e);
  ae = answer_error(a);
  if (!ae.empty()) {
    cJSON_Delete(a);
    return fail(ae);
  }
  cJSON* result = cJSON_DetachItemFromObjectCaseSensitive(a, "result");
  cJSON_Delete(a);
  const cJSON* sig = cJSON_GetObjectItemCaseSensitive(result, "signature");
  Bytes got;
  if (!cJSON_IsString(sig) || !b64_decode(sig->valuestring, got) || !bytes_equal(got, want)) {
    cJSON_Delete(result);
    err = where + ": the runtime could not prove it knows this project's token (a machine in the middle?)";
    return false;
  }
  hello_ = result;
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
