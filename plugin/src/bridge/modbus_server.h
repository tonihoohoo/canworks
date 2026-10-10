// modbus_server.h - the bridge's Modbus TCP server: one thread with poll(),
// MBAP framing, client limits, allowlists and a cap on unsent replies. Requests are answered in
// arrival order from the byte image and never wait for the bus.

#ifndef CANWORKS_BRIDGE_MODBUS_SERVER_H
#define CANWORKS_BRIDGE_MODBUS_SERVER_H

#include <atomic>
#include <cstddef>
#include <cstdint>
#include <functional>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#include "address_list.h"
#include "byte_image.h"

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

// One connected client, for status reports.
struct ClientInfo {
  std::string address;
  uint64_t requests = 0;
  bool writer = false;
  size_t queued = 0;  // unsent reply bytes
};

class ModbusServer {
 public:
  explicit ModbusServer(ByteImage& image) : image_(image) {}
  ~ModbusServer() { stop(); }

  // Called on the server thread after each accepted write request.
  std::function<void()> on_write;
  // Log lines (connections refused or closed). Default: none.
  std::function<void(const std::string&)> log;

  // Binds and starts the server thread; false with `err` if the address
  // cannot be bound.
  bool start(const ServerConfig& cfg, std::string& err);
  void stop();

  uint16_t port() const { return port_; }  // the bound port (listen port 0 in tests)
  int clients() const { return clients_.load(std::memory_order_relaxed); }
  std::vector<ClientInfo> client_list() const;

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
  std::atomic<bool> stop_{false};
  std::thread thread_;
};

}  // namespace canworks_bridge

#endif
