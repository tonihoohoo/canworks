// cia309_server.h - the CiA 309-3 gateway's thread (canopen-cia309-gateway
// spec).
//
// Cia309Server runs one thread with a poll loop, like DiagServer: a plain TCP
// listener on the loopback address (`cia309.bind`:`cia309.port`), and the
// connections the diagnostics server hands over after its `cia309` op (still
// in their TLS session). Each connection is one Cia309Session
// (cia309_dispatch.h); bus work goes to the networks' DiagHubs, and their
// answers and events come back through the hubs' gateway pipes. Nothing here
// runs on the PLC scan or the bus thread, and the bus thread never waits for
// a client.

#ifndef CANWORKS_CIA309_SERVER_H
#define CANWORKS_CIA309_SERVER_H

#include <atomic>
#include <chrono>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#include "cia309_dispatch.h"
#include "config.h"
#include "diag.h"
#include "secure_channel.h"

namespace canopen_plugin {

class Cia309Server {
 public:
  // Answers waiting longer than kStalledFor above this close the session.
  static constexpr size_t kMaxSendBuffer = 256 * 1024;
  static constexpr std::chrono::seconds kStalledFor{10};
  static constexpr std::chrono::seconds kRetryListen{10};

  // `nets`: every network of the config, in config order.
  Cia309Server(const Cia309Config& cfg, std::vector<Cia309Net> nets, std::string version);
  ~Cia309Server();
  Cia309Server(const Cia309Server&) = delete;
  Cia309Server& operator=(const Cia309Server&) = delete;

  void start();
  void stop();  // idempotent; joins, closes every session

  // The diagnostics server's side (its thread): the `cia309` op.
  Cia309Hooks hooks();
  bool can_take(std::string& why);
  bool take(int fd, std::unique_ptr<TlsConn> tls, const std::string& peer, std::string in);

  // The op's result and the status part ("cia309"); any thread.
  cJSON* info() const;
  cJSON* status() const;
  // "1 = io, 2 = drives".
  std::string numbering_text() const;

  // For tests: before start(), listen on a free port although `cia309.port`
  // says another (or none); the port listened on (0 until listening).
  void listen_any_port() { any_port_ = true; }
  unsigned port() const { return port_.load(); }
  size_t sessions() const { return count_.load(); }

 private:
  struct Conn {
    int fd = -1;
    std::unique_ptr<TlsConn> tls;  // tunnelled through the diagnostics channel
    std::unique_ptr<Cia309Session> session;
    bool closing = false;
    std::chrono::steady_clock::time_point over_since{};  // output above kMaxSendBuffer since
  };
  struct Handover {
    int fd = -1;
    std::unique_ptr<TlsConn> tls;
    std::string peer;
    std::string in;
  };

  void run();
  bool open_listener();
  void accept_clients();
  void adopt(Handover h, std::chrono::steady_clock::time_point now);
  void on_bytes(Conn& c, const char* data, size_t n, std::chrono::steady_clock::time_point now);
  bool flush(Conn& c);  // false: connection lost
  size_t pending(const Conn& c) const;
  void close_conn(size_t i, const char* why);
  void publish();

  Cia309Config cfg_;
  std::vector<Cia309Net> nets_;
  std::string version_;
  std::thread thread_;
  int stop_pipe_[2] = {-1, -1};
  int handover_pipe_[2] = {-1, -1};
  int listen_fd_ = -1;
  bool any_port_ = false;
  std::atomic<unsigned> port_{0};
  std::chrono::steady_clock::time_point next_listen_try_{};
  bool warned_listen_ = false;
  std::vector<Conn> conns_;

  mutable std::mutex mutex_;  // guards handovers_ and the status snapshot
  std::vector<Handover> handovers_;
  struct SessionInfo {
    std::string peer;
    bool tunnelled = false;
    uint64_t served = 0;
  };
  std::vector<SessionInfo> snapshot_;
  std::atomic<size_t> count_{0};  // sessions open, plus hand-overs not adopted yet
};

}  // namespace canopen_plugin

#endif  // CANWORKS_CIA309_SERVER_H
