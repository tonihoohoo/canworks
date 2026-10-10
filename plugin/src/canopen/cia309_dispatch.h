// cia309_dispatch.h - one CiA 309-3 session's commands (canopen-cia309-gateway
// spec).
//
// Cia309Session parses its client's lines with Lely's text layer
// (cia309_text.h) and carries the requests out through the networks'
// DiagHubs, as the diagnostics channel's requests (marked from_cia309): SDO
// transfers queue behind boot configuration and SDO variables, NMT keeps the
// hold rules and the bus thread's "OPERATIONAL, force needed" check, LSS
// keeps its one-at-a-time lock. Answers and notifications are formatted by
// Lely again. The gateway's own guards (allow_changes, allow_force) are
// checked here. Lely's CiA 309-1 service object (co_gw_t) is not used.
//
// Not thread-safe: the gateway thread (cia309_server.h) owns its sessions.
// Commands are answered in the order sent, one at a time on the bus thread.

#ifndef CANWORKS_CIA309_DISPATCH_H
#define CANWORKS_CIA309_DISPATCH_H

#include <array>
#include <chrono>
#include <cstdint>
#include <deque>
#include <map>
#include <memory>
#include <set>
#include <string>
#include <vector>

#include "config.h"
#include "diag.h"

namespace canopen_plugin {

class Cia309Text;

// A network the gateway serves, by its index in the config: its settings
// and its hub (null: no hub, a J1939 or plain CAN network).
struct Cia309Net {
  const Config* cfg = nullptr;
  DiagHub* hub = nullptr;
};

class Cia309Session {
 public:
  using clock = std::chrono::steady_clock;
  static constexpr size_t kMaxLine = 16384;
  static constexpr size_t kMaxOutstanding = 8;
  static constexpr size_t kMaxNotifications = 1024;
  // Notifications move into the output while less than this waits there.
  static constexpr size_t kNotificationRoom = 64 * 1024;
  static constexpr unsigned kDefaultCommandTimeoutMs = 5000;
  static constexpr unsigned kDefaultSdoTimeoutMs = 1000;
  // An LSS search takes up to Network::kLssFindLimit (20 s): its command
  // waits at least this long whatever the command timeout.
  static constexpr unsigned kLssSearchTimeoutMs = 25000;
  static constexpr std::chrono::milliseconds kLssPoll{200};

  Cia309Session(const Cia309Config& gw, const std::vector<Cia309Net>& nets, std::string peer, bool tunnelled,
                std::string version);
  ~Cia309Session();
  Cia309Session(const Cia309Session&) = delete;
  Cia309Session& operator=(const Cia309Session&) = delete;

  // Bytes from the client; complete lines are carried out. False: a line
  // longer than kMaxLine came (the session must close).
  bool feed(const char* data, size_t n, clock::time_point now);
  // An answer from the hub of network `net` (index in the config); false
  // when it is not this session's.
  bool answer(size_t net, uint64_t seq, const std::string& line, clock::time_point now);
  // An event of network `net`, and events lost before they reached the
  // gateway (the hub's queue was full).
  void event(size_t net, const DiagEvent& e);
  void lost(uint64_t n);
  // Command timeouts and LSS search polling; returns when it is due next
  // (clock::time_point::max() when nothing waits).
  clock::time_point poll(clock::time_point now);

  // Text to send: answers, then notifications while there is room. The
  // caller sends from the front and erases what went out.
  std::string& output();
  size_t notifications_waiting() const { return notes_.size(); }

  const std::string& peer() const { return peer_; }
  bool tunnelled() const { return tunnelled_; }
  uint64_t served() const { return served_; }
  size_t outstanding() const { return queue_.size(); }

 private:
  struct Command {
    uint32_t seq = 0;
    int srv = 0;
    std::vector<uint8_t> req;  // the co_gw_req Lely parsed (copied)
    std::string text;          // the line, for the log
    bool syntax = false;       // Lely could not parse the line (error 101)
    bool running = false;      // waits for the bus thread
    size_t net = 0;            // the network it went to (index)
    unsigned number = 0;       // that network's CiA 309 number
    uint64_t hub_seq = 0;
    clock::time_point deadline{};
    int step = 0;              // multi-step commands (LSS search, inquire address)
    clock::time_point next{};  // LSS search: the next status poll
  };

  void on_request(const void* req, size_t size, int srv);
  void on_text(const std::string& line);
  // Starts the commands at the front until one has to wait for the bus.
  void run(clock::time_point now);
  // Starts one command; true when it is done (answered).
  bool start(Command& c, clock::time_point now);
  // A bus thread answer for the front command; true when it is done.
  bool finish(Command& c, const std::string& line, clock::time_point now);

  // The network a request names (0: the default), as a config index and its
  // CiA 309 number; false with the internal error code to answer.
  bool pick_net(unsigned requested, size_t& index, unsigned& number, int& iec) const;
  bool pick_node(unsigned number, unsigned requested, unsigned& node, int& iec) const;
  void submit(Command& c, size_t net, unsigned number, DiagRequest r, clock::time_point now, unsigned timeout_ms);
  DiagRequest request(const std::string& op) const;
  // Answers the command with a confirmation without data.
  void confirm(const Command& c, int iec, uint32_t ac = 0);
  // A refused request: logged with the client and reason, answered 102.
  void refuse(const Command& c, const std::string& why, int iec = 102);
  // Maps a diagnostics error text from the bus thread to a CiA 309-3 code
  // (logged as a refusal).
  void fail(const Command& c, const std::string& why);
  bool changes_allowed(const Command& c);
  void note(const std::string& line);
  bool is_configured(size_t net, unsigned node) const;

  const Cia309Config& gw_;
  const std::vector<Cia309Net>& nets_;
  std::string peer_;
  bool tunnelled_ = false;
  std::string version_;
  std::unique_ptr<Cia309Text> text_;
  std::string in_;
  std::string out_;
  std::deque<Command> queue_;
  std::deque<std::string> notes_;
  uint64_t notes_lost_ = 0;
  uint64_t served_ = 0;
  // Session settings (CiA 309-3 "set" commands).
  unsigned default_net_ = 0;
  std::map<unsigned, unsigned> default_node_;  // network number -> node ID
  unsigned sdo_timeout_ms_ = kDefaultSdoTimeoutMs;
  unsigned command_timeout_ms_ = kDefaultCommandTimeoutMs;
  std::set<unsigned> bootup_off_;  // network numbers with boot-up indication off
  // lss_switch_sel (or a found device): the LSS address the next LSS
  // requests go to.
  bool selected_ = false;
  std::array<uint32_t, 4> selection_{};
  // While parsing a line: its text (for the command it becomes).
  const std::string* parsing_ = nullptr;
  bool parsed_ = false;
};

}  // namespace canopen_plugin

#endif  // CANWORKS_CIA309_DISPATCH_H
