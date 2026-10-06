// control.h - the standalone simulator's control channel (docs/simulator.md,
// "Control protocol"): one JSON object per line each way over TCP.
//
// ControlServer is the simulator's listener. It never blocks: the run loop
// calls poll_once() between slices of the Lely loop, so every request reaches
// the engine on the loop's thread. ControlClient is the minimal client the
// subcommands and the test mode use, against the standalone simulator (port
// 7532) or the plugin's diagnostics channel (port 7531), which take the same
// hello line and the same sim_ requests.

#ifndef OPENPLC_CANOPEN_SIM_CONTROL_H
#define OPENPLC_CANOPEN_SIM_CONTROL_H

#include <functional>
#include <string>
#include <vector>

typedef struct cJSON cJSON;

namespace sim_tool {

constexpr unsigned kControlPort = 7532;
constexpr unsigned kDiagPort = 7531;
constexpr unsigned kProtocol = 1;

// "HOST", "HOST:PORT", "[V6]:PORT" or "V6". False on a bad port.
bool split_host_port(const std::string& text, unsigned default_port, std::string& host, unsigned& port);

// The token from --token, else --token-file (first line, trimmed), else the
// environment variable `env` (nullptr: none). False with `err` when the file
// cannot be read or is empty.
bool resolve_token(const std::string& token, const std::string& token_file, const char* env, std::string& out,
                   std::string& err);

// Whether an address (as given to --bind) is a loopback address.
bool is_loopback(const std::string& addr);

class ControlServer {
 public:
  // Answers one request line that is not a hello: (request, id as JSON text
  // or "", peer) -> answer line without the newline.
  using Handler = std::function<std::string(const cJSON* req, const std::string& id, const std::string& peer)>;

  ControlServer(std::string version, std::string token, Handler handler);
  ~ControlServer();
  // Binds and listens. False with `err`.
  bool listen(const std::string& bind, unsigned port, std::string& err);
  // Accepts, reads and answers whatever is ready, without waiting.
  void poll_once();
  // "127.0.0.1:7532"
  std::string address() const { return address_; }

 private:
  struct Client {
    int fd = -1;
    std::string peer;
    std::string in, out;
    bool greeted = false;
    bool closing = false;
  };
  void accept_all();
  void read_client(Client& c);
  void handle_line(Client& c, const std::string& line);
  void flush(Client& c);

  std::string version_, token_;
  Handler handler_;
  int fd_ = -1;
  std::string address_;
  std::vector<Client> clients_;
};

class ControlClient {
 public:
  ~ControlClient();
  // Connects and sends the hello line (with `token`, which may be empty).
  // False with `err`; a closed connection after the hello means a wrong
  // token.
  bool connect(const std::string& host, unsigned port, const std::string& token, std::string& err);
  // Sends `req` (an id is added) and returns the parsed answer, or nullptr
  // with `err` (transport error). The caller deletes the answer.
  cJSON* request(cJSON* req, std::string& err, int timeout_ms = 15000);
  // The hello answer's result (owned by the client), or nullptr.
  const cJSON* hello() const { return hello_; }

 private:
  bool send_line(const std::string& line, std::string& err);
  bool read_line(std::string& line, int timeout_ms, std::string& err);

  int fd_ = -1;
  std::string buf_;
  unsigned next_id_ = 1;
  cJSON* hello_ = nullptr;
};

// The error text of an answer (ok false), or "" when it succeeded.
std::string answer_error(const cJSON* answer);

}  // namespace sim_tool

#endif  // OPENPLC_CANOPEN_SIM_CONTROL_H
