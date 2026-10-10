// modbus_client.hpp - a small Modbus TCP client for the bridge tests.

#ifndef CANWORKS_TEST_MODBUS_CLIENT_HPP
#define CANWORKS_TEST_MODBUS_CLIENT_HPP

#include <arpa/inet.h>
#include <fcntl.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <poll.h>
#include <sys/socket.h>
#include <unistd.h>

#include <algorithm>
#include <chrono>
#include <cstdint>
#include <functional>
#include <thread>
#include <vector>

#include "modbus.h"

namespace canworks_bridge {

using Bytes = std::vector<uint8_t>;

// A Modbus TCP client: sends one request PDU, returns the response PDU.
class Client {
 public:
  // `rcvbuf`: a small receive buffer (0: the default); `source`: the local
  // address to connect from (127.0.0.x on loopback).
  explicit Client(uint16_t port, const char* host = "127.0.0.1", int rcvbuf = 0, const char* source = nullptr) {
    fd_ = ::socket(AF_INET, SOCK_STREAM, 0);
    if (rcvbuf) ::setsockopt(fd_, SOL_SOCKET, SO_RCVBUF, &rcvbuf, sizeof(rcvbuf));
    if (source) {
      sockaddr_in s{};
      s.sin_family = AF_INET;
      inet_pton(AF_INET, source, &s.sin_addr);
      (void)::bind(fd_, reinterpret_cast<sockaddr*>(&s), sizeof(s));
    }
    sockaddr_in a{};
    a.sin_family = AF_INET;
    a.sin_port = htons(port);
    inet_pton(AF_INET, host, &a.sin_addr);
    connected_ = ::connect(fd_, reinterpret_cast<sockaddr*>(&a), sizeof(a)) == 0;
    int one = 1;
    ::setsockopt(fd_, IPPROTO_TCP, TCP_NODELAY, &one, sizeof(one));
  }
  ~Client() { ::close(fd_); }
  bool connected() const { return connected_; }
  void set_nonblocking() { ::fcntl(fd_, F_SETFL, ::fcntl(fd_, F_GETFL) | O_NONBLOCK); }

  // Raw bytes out.
  void send_raw(const Bytes& b) { (void)::send(fd_, b.data(), b.size(), MSG_NOSIGNAL); }

  Bytes frame(const Bytes& pdu, uint8_t unit = 1) {
    Bytes f = {static_cast<uint8_t>(tid_ >> 8), static_cast<uint8_t>(tid_), 0, 0, 0, 0, unit};
    put_be16(&f[4], static_cast<uint16_t>(pdu.size() + 1));
    f.insert(f.end(), pdu.begin(), pdu.end());
    ++tid_;
    return f;
  }

  // Reads one response frame; empty when the server closed or timed out.
  Bytes read_frame(uint16_t* tid = nullptr, int timeout_ms = 2000) {
    Bytes head = read_n(7, timeout_ms);
    if (head.size() != 7) return {};
    if (tid) *tid = get_be16(&head[0]);
    Bytes pdu = read_n(get_be16(&head[4]) - 1u, timeout_ms);
    return pdu;
  }

  Bytes request(const Bytes& pdu, uint8_t unit = 1) {
    send_raw(frame(pdu, unit));
    return read_frame();
  }

  // True when the server closed the connection.
  bool closed(int timeout_ms = 2000) {
    pollfd p{fd_, POLLIN, 0};
    if (::poll(&p, 1, timeout_ms) <= 0) return false;
    char c;
    return ::recv(fd_, &c, 1, MSG_PEEK) == 0;
  }

 private:
  Bytes read_n(size_t n, int timeout_ms) {
    Bytes out;
    while (out.size() < n) {
      pollfd p{fd_, POLLIN, 0};
      if (::poll(&p, 1, timeout_ms) <= 0) return out;
      uint8_t buf[512];
      ssize_t got = ::recv(fd_, buf, std::min(sizeof(buf), n - out.size()), 0);
      if (got <= 0) return out;
      out.insert(out.end(), buf, buf + got);
    }
    return out;
  }
  int fd_;
  bool connected_ = false;
  uint16_t tid_ = 1;
};

inline Bytes read_req(uint8_t f, uint16_t addr, uint16_t count) {
  Bytes p = {f, 0, 0, 0, 0};
  put_be16(&p[1], addr);
  put_be16(&p[3], count);
  return p;
}

inline Bytes write_regs(uint16_t addr, const std::vector<uint16_t>& v) {
  Bytes p = {kWriteMultipleRegisters, 0, 0, 0, 0, static_cast<uint8_t>(v.size() * 2)};
  put_be16(&p[1], addr);
  put_be16(&p[3], static_cast<uint16_t>(v.size()));
  for (uint16_t w : v) {
    p.push_back(static_cast<uint8_t>(w >> 8));
    p.push_back(static_cast<uint8_t>(w));
  }
  return p;
}

inline Bytes exc(uint8_t f, uint8_t code) { return {static_cast<uint8_t>(f | 0x80), code}; }

inline bool wait_for(const std::function<bool()>& f, int ms = 2000) {
  auto end = std::chrono::steady_clock::now() + std::chrono::milliseconds(ms);
  while (std::chrono::steady_clock::now() < end) {
    if (f()) return true;
    std::this_thread::sleep_for(std::chrono::milliseconds(5));
  }
  return f();
}


}  // namespace canworks_bridge

#endif  // CANWORKS_TEST_MODBUS_CLIENT_HPP
