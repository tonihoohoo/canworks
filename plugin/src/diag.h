// diag.h - the diagnostics channel (canopen-online-diagnostics spec).
//
// DiagServer runs its own thread: it listens on TCP, checks each client's
// token and parses its requests (one JSON object per line). Requests that
// need the bus go through DiagHub to the Network on the bus thread, which
// polls the hub on its request timer and answers through it. The server
// thread never touches the Network, and the bus thread never blocks on a
// socket.
//
// Protocol 1: the client's first line is {"op":"hello","token":"..."}. Every
// request may carry an "id", echoed in its answer. Answers are
// {"id":...,"ok":true,"result":{...}} or {"id":...,"ok":false,"error":"..."}.
// Each connection gets its answers in the order it sent the requests.

#ifndef CANOPEN_DIAG_H
#define CANOPEN_DIAG_H

#include <atomic>
#include <chrono>
#include <cstdint>
#include <map>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#include "config.h"
#include "trace_capture.h"

typedef struct cJSON cJSON;

namespace canopen_plugin {

constexpr unsigned kDiagProtocol = 1;
constexpr size_t kDiagMaxSdoBytes = 4096;

// One request for the bus thread, already checked by the server.
struct DiagRequest {
  uint64_t seq = 0;   // set by the hub
  std::string op;     // status, emcy, sdo_read, sdo_write, nmt, scan, scan_status,
                      // lss_find, lss_find_status, lss_inquire, lss_set_id, lss_set_bitrate
  std::string id;     // the request's "id" as JSON text ("" = none)
  std::string peer;   // client address, for the log
  unsigned node = 0;
  uint16_t index = 0;
  uint8_t subindex = 0;
  std::vector<uint8_t> data;  // sdo_write
  unsigned timeout_ms = 1000;
  std::string command;  // nmt: start, stop, preop, reset, reset-comm
  // LSS: the device's address (vendor ID, product code, revision number,
  // serial number); lss_find uses only vendor and product, when lss_known.
  uint32_t lss[4] = {};
  bool lss_known = false;
  unsigned bitrate_kbit = 0;  // lss_set_bitrate
  bool store = false;         // lss_set_id, lss_set_bitrate
};

// Builds answer lines.
std::string diag_ok(const std::string& id, cJSON* result);  // takes ownership of result
std::string diag_error(const std::string& id, const std::string& message);
std::string hex_bytes(const std::vector<uint8_t>& data);

// Thread-safe hand-off between the server thread and the bus thread.
class DiagHub {
 public:
  DiagHub(const Config& cfg, std::string version);
  ~DiagHub();

  const Config& config() const { return cfg_; }
  const std::string& version() const { return version_; }
  // Seconds since the hub was made (the CANopen session's start).
  double uptime_s() const;

  // ---- bus thread ----
  // A Network serves requests from now on.
  void attach();
  // No Network any more: every request taken and not answered yet, and
  // every request still queued, gets the "no bus" answer.
  void detach();
  // Moves the queued requests into `out` (appends).
  void take(std::vector<DiagRequest>& out);
  void answer(uint64_t seq, const std::string& line);

  // ---- server thread ----
  bool attached() const { return attached_.load(std::memory_order_acquire); }
  // Queues a request for the bus thread; returns its sequence number.
  uint64_t submit(DiagRequest r);
  // Moves the answers ready so far into `out` as (seq, line).
  void take_answers(std::vector<std::pair<uint64_t, std::string>>& out);
  // Readable when answers are ready (a pipe; drained by take_answers()).
  int wake_fd() const { return pipe_[0]; }

  // The answer when no Network runs: status with bus state 0 and every node
  // at 0, every other request refused with "no bus".
  std::string offline_answer(const DiagRequest& r) const;

 private:
  void wake();

  const Config& cfg_;
  std::string version_;
  std::chrono::steady_clock::time_point start_;
  std::atomic<bool> attached_{false};
  mutable std::mutex mutex_;
  uint64_t next_seq_ = 1;
  std::vector<DiagRequest> queue_;
  std::map<uint64_t, DiagRequest> taken_;  // taken by the bus thread, not answered
  std::vector<std::pair<uint64_t, std::string>> answers_;
  int pipe_[2] = {-1, -1};
};

class DiagServer {
 public:
  static constexpr unsigned kMaxClients = 4;
  static constexpr size_t kMaxLine = 16384;
  static constexpr size_t kMaxSendBuffer = 256 * 1024;
  static constexpr std::chrono::seconds kHelloTimeout{10};
  static constexpr std::chrono::seconds kRetryListen{10};

  static constexpr size_t kTraceFetchDefault = 2000;
  static constexpr size_t kTraceFetchMax = 4000;

  explicit DiagServer(DiagHub& hub);
  ~DiagServer();

  void start();
  void stop();  // idempotent; joins

  // For tests: the port actually listened on (0 until listening).
  unsigned port() const { return port_.load(); }
  // For tests, before start(): where trace frames come from, the ring size
  // and how long a trace lives without a fetch.
  void set_trace_source(std::unique_ptr<TraceSource> source) { trace_source_ = std::move(source); }
  void set_trace_ring(size_t capacity) { ring_ = TraceRing(capacity); }
  void set_trace_idle(std::chrono::milliseconds idle) { trace_idle_ = idle; }

 private:
  struct Client {
    int fd = -1;
    std::string peer;  // address only
    std::string in;
    std::string out;
    bool authed = false;
    uint64_t waiting = 0;  // seq of the request on the bus thread, 0 = none
    std::chrono::steady_clock::time_point since;
    bool closing = false;  // close after `out` is sent
    // Trace (frame capture) state of this client.
    bool tracing = false;
    std::vector<TraceFilter> trace_filters;
    bool trace_errors = false;
    std::chrono::steady_clock::time_point trace_fetched;
  };

  void run();
  bool open_listener();
  void accept_clients();
  void handle_line(Client& c, const std::string& line);
  void process_input(Client& c);
  bool flush(Client& c);  // false: connection lost
  void close_client(size_t i);
  void log_auth_failure(const std::string& peer);
  // Trace ops, answered here without the bus thread.
  bool handle_trace(Client& c, const std::string& op, const std::string& id, const cJSON* req);
  // Opens, re-filters or closes the capture to match the clients' traces and
  // the session; reads waiting frames into the ring.
  void update_capture(std::chrono::steady_clock::time_point now);
  void read_capture();
  void close_capture(bool gap);
  bool any_trace() const;

  DiagHub& hub_;
  std::thread thread_;
  int stop_pipe_[2] = {-1, -1};
  int listen_fd_ = -1;
  std::atomic<unsigned> port_{0};
  std::vector<Client> clients_;
  std::map<std::string, std::chrono::steady_clock::time_point> auth_logged_;
  std::chrono::steady_clock::time_point next_listen_try_{};
  bool warned_listen_ = false;

  std::unique_ptr<TraceSource> trace_source_;
  TraceRing ring_;
  std::chrono::milliseconds trace_idle_{10000};
  bool capture_open_ = false;
  bool capture_gap_ = false;  // put a gap record before the next frame
  std::vector<TraceFilter> capture_filters_;
  bool capture_errors_ = false;
  uint64_t kernel_drops_ = 0;      // since the trace started (all sockets so far)
  uint64_t kernel_drops_sock_ = 0;  // the open socket's count
  std::chrono::steady_clock::time_point next_capture_try_{};
  bool warned_capture_ = false;
};

}  // namespace canopen_plugin

#endif  // CANOPEN_DIAG_H
