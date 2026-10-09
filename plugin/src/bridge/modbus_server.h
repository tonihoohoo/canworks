// modbus_server.h - the bridge's Modbus TCP server: one thread with poll(),
// MBAP framing, client limits and allowlists. Requests are answered in
// arrival order from the byte image and never wait for the bus.

#ifndef CANWORKS_BRIDGE_MODBUS_SERVER_H
#define CANWORKS_BRIDGE_MODBUS_SERVER_H

#include <atomic>
#include <cstdint>
#include <functional>
#include <string>
#include <thread>

#include "address_list.h"
#include "byte_image.h"

namespace canworks_bridge {

struct ServerConfig {
  std::string listen = "0.0.0.0:502";
  uint8_t unit_id = 1;
  int max_clients = 16;
  AddressList readers;  // empty: anyone may connect
  AddressList writers;  // empty: every connected client may write
  int idle_timeout_ms = 60000;
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

 private:
  void run();

  ByteImage& image_;
  ServerConfig cfg_;
  int listen_fd_ = -1;
  int wake_fd_ = -1;
  uint16_t port_ = 0;
  std::atomic<int> clients_{0};
  std::atomic<bool> stop_{false};
  std::thread thread_;
};

}  // namespace canworks_bridge

#endif
