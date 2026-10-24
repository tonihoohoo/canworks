// modbus_trace.h - the bridge's Modbus trace recorder (modbus-bridge "Modbus
// trace recorder"): while a diagnostics client traces Modbus, each answered
// request goes into a byte ring as one record with its request and answer
// PDUs. With "changes only" a request whose client, function, start, count,
// values and result equal the previous one of its kind is counted, not
// recorded; the next record of that kind carries the count. Nothing is
// recorded while no session is open.
//
// A record, little endian, as modbus_trace_fetch sends it (base64):
//   0 u64 time (UTC microseconds of the answer)   8 u64 sequence number
//  16 u32 connection number                      20 u32 requests skipped before it
//  24 u16 MBAP transaction                       26 u8 unit   27 u8 flags (1: refused write)
//  28 u16 client port                            30 u8 address length
//  31 u8 request PDU length                      32 u8 answer PDU length   33 u8 0
//  34 address text, request PDU, answer PDU

#ifndef CANWORKS_BRIDGE_MODBUS_TRACE_H
#define CANWORKS_BRIDGE_MODBUS_TRACE_H

#include <sys/socket.h>

#include <atomic>
#include <chrono>
#include <cstddef>
#include <cstdint>
#include <deque>
#include <map>
#include <mutex>
#include <string>
#include <unordered_map>
#include <vector>

#include "address_list.h"

namespace canworks_bridge {

constexpr size_t kModbusTraceHeader = 34;
constexpr uint8_t kTraceRefusedWrite = 1;

class ModbusTrace {
 public:
  using Clock = std::chrono::steady_clock;
  static constexpr size_t kDefaultBytes = size_t(4) << 20;
  static constexpr size_t kFetchDefault = 2000;
  static constexpr size_t kFetchMax = 4000;
  static constexpr size_t kFetchBytes = size_t(256) << 10;
  static constexpr std::chrono::seconds kIdleEnd{10};

  explicit ModbusTrace(size_t capacity = kDefaultBytes) : capacity_(capacity) {}

  // Whether a session is open (the server's cheap check before record()).
  bool active() const { return active_.load(std::memory_order_relaxed); }

  // One answered request (server thread, after its answer is queued).
  void record(uint32_t conn, const sockaddr* peer, const std::string& peer_text, uint16_t peer_port,
              uint16_t transaction, uint8_t unit, const uint8_t* req, size_t req_n, const uint8_t* resp,
              size_t resp_n, bool refused, uint64_t time_us);
  // A connection closed: its change filter goes.
  void forget(uint32_t conn);
  // Registers the change filter leaves out (modbus-bridge "Modbus trace
  // recorder"): words the mailboxes change on their own, the keepalive
  // holding registers and the input clock words.
  void set_ignored(std::vector<uint16_t> holding, std::vector<uint16_t> input);

  // Sessions, by the diagnostics client's number. start() returns the
  // sequence number to fetch after.
  uint64_t start(uint64_t session, bool changes_only, const AddressList& clients, Clock::time_point now);
  struct Fetch {
    std::string data;  // the records, back to back
    size_t count = 0;
    uint64_t next = 0;
    uint64_t lost = 0;  // records after `after` the ring no longer holds
    bool more = false;
  };
  // False: no session (never started, stopped or ended idle).
  bool fetch(uint64_t session, uint64_t after, size_t max, Clock::time_point now, Fetch& out);
  bool stop(uint64_t session);
  // Ends sessions not fetched for kIdleEnd; returns how many ended.
  size_t expire(Clock::time_point now);

  size_t capacity() const { return capacity_; }
  uint64_t last_seq() const;
  size_t sessions() const;

 private:
  struct Entry {
    std::string bytes;
    sockaddr_storage addr;
  };
  struct Session {
    bool changes_only = true;
    AddressList clients;
    Clock::time_point fetched;
  };
  struct Kind {
    uint64_t hash = 0;
    uint32_t skipped = 0;
  };
  void update_active();  // under mu_

  const size_t capacity_;
  mutable std::mutex mu_;
  std::atomic<bool> active_{false};
  bool changes_only_ = true;  // every open session wants changes only
  std::deque<Entry> ring_;
  size_t bytes_ = 0;
  uint64_t seq_ = 0;        // the last record's number
  std::map<uint64_t, Session> sessions_;
  std::unordered_map<uint32_t, std::unordered_map<uint64_t, Kind>> kinds_;
  std::vector<uint16_t> ignored_holding_, ignored_input_;  // sorted
};

std::string base64(const std::string& data);

}  // namespace canworks_bridge

#endif
