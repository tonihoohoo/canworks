// Unit tests of the standalone simulator's control channel: with a token,
// TLS and the SCRAM login of secure_channel.h; without one, plain lines.

#include <atomic>
#include <chrono>
#include <string>
#include <thread>

#include "check.hpp"
#include "cJSON.h"
#include "control.h"

using namespace sim_tool;

namespace {

// A ControlServer on 127.0.0.1 (any port) polled on its own thread; every
// request is answered with {"ok": true, "result": {"echo": op}}.
class ServerThread {
 public:
  explicit ServerThread(const std::string& token)
      : server_("v-test", token, [](const cJSON* req, const std::string& id, const std::string&) {
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
