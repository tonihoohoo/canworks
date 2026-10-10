// Unit tests of the standalone simulator's control channel: with a token,
// TLS and the SCRAM login of secure_channel.h; without one, plain lines.

#include <atomic>
#include <chrono>
#include <cstring>
#include <string>
#include <thread>

#include <arpa/inet.h>
#include <netinet/in.h>
#include <poll.h>
#include <sys/socket.h>
#include <unistd.h>

#include "check.hpp"
#include "cJSON.h"
#include "control.h"

using namespace sim_tool;

namespace {

std::atomic<int> g_handled{0};  // requests that reached the handler

// A ControlServer on 127.0.0.1 (any port) polled on its own thread; every
// request is answered with {"ok": true, "result": {"echo": op}}.
class ServerThread {
 public:
  explicit ServerThread(const std::string& token)
      : server_("v-test", token, [](const cJSON* req, const std::string& id, const std::string&) {
          ++g_handled;
          const cJSON* op = cJSON_GetObjectItemCaseSensitive(req, "op");
          return "{\"id\":" + (id.empty() ? std::string("null") : id) + ",\"ok\":true,\"result\":{\"echo\":\"" +
                 (cJSON_IsString(op) ? op->valuestring : "") + "\"}}";
        }) {
    std::string err;
    ok_ = server_.listen("127.0.0.1", 0, err);
    port_ = ok_ ? std::stoul(server_.address().substr(server_.address().rfind(':') + 1)) : 0;
    thread_ = std::thread([this] {
      while (!stop_) {
        server_.poll_once();
        std::this_thread::sleep_for(std::chrono::milliseconds(2));
      }
    });
  }
  ~ServerThread() {
    stop_ = true;
    thread_.join();
  }
  bool ok() const { return ok_; }
  unsigned port() const { return port_; }

 private:
  ControlServer server_;
  bool ok_ = false;
  unsigned port_ = 0;
  std::atomic<bool> stop_{false};
  std::thread thread_;
};

}  // namespace

TEST(control_tls_login_and_request) {
  ServerThread s("s3cret-token");
  CHECK(s.ok());
  ControlClient c;
  std::string err;
  CHECK(c.connect("127.0.0.1", s.port(), "s3cret-token", err));
  CHECK(err.empty());
  const cJSON* hello = c.hello();
  CHECK(hello != nullptr);
  if (!hello) return;
  CHECK(cJSON_GetObjectItemCaseSensitive(hello, "protocol")->valueint == static_cast<int>(kTlsProtocol));
  CHECK(cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(hello, "simulator")));
  cJSON* req = cJSON_CreateObject();
  cJSON_AddStringToObject(req, "op", "sim_status");
  cJSON* answer = c.request(req, err);
  cJSON_Delete(req);
  CHECK(answer != nullptr);
  if (answer) {
    const cJSON* result = cJSON_GetObjectItemCaseSensitive(answer, "result");
    CHECK(std::string(cJSON_GetObjectItemCaseSensitive(result, "echo")->valuestring) == "sim_status");
    cJSON_Delete(answer);
  }
}

TEST(control_tls_wrong_token_refused) {
  ServerThread s("s3cret-token");
  CHECK(s.ok());
  ControlClient c;
  std::string err;
  CHECK(!c.connect("127.0.0.1", s.port(), "wrong-token", err));
  CHECK(err.find("wrong token") != std::string::npos);
}

TEST(control_plain_client_refused_by_token_server) {
  ServerThread s("s3cret-token");
  CHECK(s.ok());
  ControlClient c;
  std::string err;
  CHECK(!c.connect("127.0.0.1", s.port(), "", err));
  CHECK(err.find("encrypted") != std::string::npos);
}

TEST(control_plain_without_token) {
  ServerThread s("");
  CHECK(s.ok());
  ControlClient c;
  std::string err;
  CHECK(c.connect("127.0.0.1", s.port(), "", err));
  CHECK(c.hello() != nullptr);
  if (!c.hello()) return;
  CHECK(cJSON_GetObjectItemCaseSensitive(c.hello(), "protocol")->valueint == static_cast<int>(kProtocol));
}

namespace {

// Sends `text` on a plain connection and reads until the server closes it
// (or 2 s pass); what came back, and whether it closed.
std::string plain_exchange(unsigned port, const std::string& text, bool& closed) {
  closed = false;
  int fd = socket(AF_INET, SOCK_STREAM, 0);
  sockaddr_in a{};
  a.sin_family = AF_INET;
  a.sin_port = htons(static_cast<uint16_t>(port));
  a.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
  std::string got;
  if (connect(fd, reinterpret_cast<sockaddr*>(&a), sizeof a) != 0) {
    close(fd);
    return got;
  }
  send(fd, text.data(), text.size(), MSG_NOSIGNAL);
  auto end = std::chrono::steady_clock::now() + std::chrono::seconds(2);
  while (std::chrono::steady_clock::now() < end) {
    pollfd p{fd, POLLIN, 0};
    if (poll(&p, 1, 50) <= 0) continue;
    char buf[1024];
    ssize_t n = recv(fd, buf, sizeof buf, 0);
    if (n <= 0) {
      closed = true;
      break;
    }
    got.append(buf, static_cast<size_t>(n));
  }
  close(fd);
  return got;
}

}  // namespace

// Without a token the first line must be the hello: a web page posting JSON
// lines to the port, or a client that skips the hello, runs nothing.
TEST(control_plain_needs_hello_first) {
  ServerThread s("");
  CHECK(s.ok());
  g_handled = 0;
  bool closed = false;
  std::string got = plain_exchange(s.port(),
                                   "POST / HTTP/1.1\r\nHost: 127.0.0.1:7532\r\nContent-Type: text/plain\r\n\r\n"
                                   "{\"op\":\"sim_fault\",\"node\":5,\"fault\":{\"power\":\"on\"}}\n"
                                   "{\"op\":\"sim_clear\",\"node\":5,\"fault\":\"all\"}\n",
                                   closed);
  CHECK(closed && got.empty());
  got = plain_exchange(s.port(), "{\"op\":\"sim_status\"}\n{\"op\":\"hello\"}\n{\"op\":\"sim_status\"}\n", closed);
  CHECK(closed && got.find("hello") != std::string::npos);
  got = plain_exchange(s.port(), "garbage\n{\"op\":\"hello\"}\n{\"op\":\"sim_status\"}\n", closed);
  CHECK(closed);
  CHECK_MSG(g_handled == 0, std::to_string(g_handled.load()));
  // The hello first: requests run, and a bad line later only gets an error.
  got = plain_exchange(s.port(), "{\"op\":\"hello\",\"id\":1}\nnot json\n{\"op\":\"sim_status\",\"id\":2}\n", closed);
  CHECK(!closed && got.find("\"echo\":\"sim_status\"") != std::string::npos);
  CHECK(g_handled == 1);
}
