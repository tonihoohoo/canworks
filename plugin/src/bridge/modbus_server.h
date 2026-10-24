// modbus_server.h - the bridge's Modbus TCP server: one thread with poll(),
// MBAP framing, client limits, allowlists and a cap on unsent replies. Requests are answered in
// arrival order from the byte image and never wait for the bus.

#ifndef CANWORKS_BRIDGE_MODBUS_SERVER_H
#define CANWORKS_BRIDGE_MODBUS_SERVER_H

#include <atomic>
#include <chrono>
#include <cstddef>
#include <cstdint>
#include <functional>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#include "address_list.h"
#include "byte_image.h"
#include "modbus.h"
#include "modbus_trace.h"

namespace canworks_bridge {

struct ServerConfig {
  std::string listen = "0.0.0.0:502";
  uint8_t unit_id = 1;
  int max_clients = 16;
  int max_clients_per_address = 4;
  AddressList readers;  // empty: anyone may connect
  AddressList writers;  // empty: nobody may write
  int idle_timeout_ms = 60000;     // no complete request for this long: closed
  int partial_timeout_ms = 5000;   // an incomplete request held this long: closed
  size_t max_queued = 8192;        // unsent reply bytes; over it nothing more is read
  int over_queued_ms = 10000;      // over max_queued this long: closed
};

// The functions counted one by one (modbus-bridge "Client counters"); the
// rest count as "other" (the last slot).
constexpr uint8_t kCountedFunctions[] = {1, 2, 3, 4, 5, 6, 8, 15, 16, 23, 43};
constexpr size_t kFunctionSlots = sizeof(kCountedFunctions) + 1;
// The exception codes counted; any other code counts in the last slot.
constexpr uint8_t kCountedExceptions[] = {0x01, 0x02, 0x03, 0x04, 0x0B};
constexpr size_t kExceptionSlots = sizeof(kCountedExceptions) + 1;

// One connected client, for status reports.
struct ClientInfo {
  std::string address;
  uint16_t port = 0;
  uint32_t connection = 0;  // numbers the server's connections from 1
  uint64_t requests = 0;
  bool writer = false;
  size_t queued = 0;    // unsent reply bytes
  size_t buffered = 0;  // received request bytes not yet answered
  uint64_t connected_us = 0;  // UTC
  uint64_t functions[kFunctionSlots] = {};
  uint64_t exceptions[kExceptionSlots] = {};
  uint64_t refused_writes = 0;
  // The last accepted write: UTC time (0: none), function, first register or
  // coil and count.
  uint64_t last_write_us = 0;
  uint8_t last_write_function = 0;
  uint16_t last_write_start = 0, last_write_count = 0;
  uint64_t recent = 0;  // requests answered in the last 5 s
};

// A connection that closed or was refused, kept 10 minutes (the last 8).
struct ClosedClient {
  ClientInfo info;
  std::string reason;
  uint64_t closed_us = 0;  // UTC
  std::chrono::steady_clock::time_point closed;
};

class ModbusServer {
 public:
  explicit ModbusServer(ByteImage& image) : image_(image) {}
  ~ModbusServer() { stop(); }

  // Called on the server thread after each accepted write request.
  std::function<void()> on_write;
  // Log lines (connections refused or closed). Default: none.
  std::function<void(const std::string&)> log;
  // Function 43 / MEI 14's answer; set before start().
  DeviceIdentity identity;
  // The Modbus trace; set before start(). Null: nothing is recorded.
  ModbusTrace* trace = nullptr;

  // Binds and starts the server thread; false with `err` if the address
  // cannot be bound.
  bool start(const ServerConfig& cfg, std::string& err);
  void stop();

  uint16_t port() const { return port_; }  // the bound port (listen port 0 in tests)
  int clients() const { return clients_.load(std::memory_order_relaxed); }
  std::vector<ClientInfo> client_list() const;
  // The recently closed connections, newest last.
  std::vector<ClosedClient> closed_list() const;
  static constexpr size_t kClosedKept = 8;
  static constexpr std::chrono::minutes kClosedFor{10};

 private:
  void run();

  ByteImage& image_;
  ServerConfig cfg_;
  int listen_fd_ = -1;
  int wake_fd_ = -1;
  uint16_t port_ = 0;
  std::atomic<int> clients_{0};
  mutable std::mutex info_mu_;
  std::vector<ClientInfo> info_;
  std::vector<ClosedClient> closed_;  // under info_mu_
  std::atomic<bool> stop_{false};
  std::thread thread_;
};

}  // namespace canworks_bridge

#endif
