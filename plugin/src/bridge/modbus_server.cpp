// modbus_server.cpp - see modbus_server.h.

#include "modbus_server.h"

#include <fcntl.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <poll.h>
#include <sys/eventfd.h>
#include <unistd.h>

#include <cerrno>
#include <chrono>
#include <cstring>
#include <vector>

#include "modbus.h"

namespace canworks_bridge {

namespace {

using Clock = std::chrono::steady_clock;

constexpr size_t kMbapSize = 7;
constexpr size_t kMaxPdu = 253;

struct Client {
  int fd;
  bool may_write;
  std::string peer;
  Clock::time_point last;
  std::vector<uint8_t> rx;
  std::vector<uint8_t> tx;
  uint64_t requests = 0;
};

void close_fd(int& fd) {
  if (fd >= 0) ::close(fd);
  fd = -1;
}

}  // namespace

bool ModbusServer::start(const ServerConfig& cfg, std::string& err) {
  stop();
  cfg_ = cfg;
  sockaddr_storage addr;
  socklen_t len = 0;
  if (!parse_listen(cfg.listen, addr, len, err)) return false;
  listen_fd_ = ::socket(addr.ss_family, SOCK_STREAM | SOCK_NONBLOCK | SOCK_CLOEXEC, 0);
  if (listen_fd_ < 0) {
    err = std::string("socket: ") + std::strerror(errno);
    return false;
  }
  int one = 1;
  ::setsockopt(listen_fd_, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one));
  if (::bind(listen_fd_, reinterpret_cast<sockaddr*>(&addr), len) != 0 || ::listen(listen_fd_, 16) != 0) {
    err = "cannot listen on " + cfg.listen + ": " + std::strerror(errno);
    close_fd(listen_fd_);
    return false;
  }
  sockaddr_storage bound;
  socklen_t blen = sizeof(bound);
  ::getsockname(listen_fd_, reinterpret_cast<sockaddr*>(&bound), &blen);
  port_ = ntohs(bound.ss_family == AF_INET6 ? reinterpret_cast<sockaddr_in6*>(&bound)->sin6_port
                                             : reinterpret_cast<sockaddr_in*>(&bound)->sin_port);
  wake_fd_ = ::eventfd(0, EFD_NONBLOCK | EFD_CLOEXEC);
  stop_ = false;
  thread_ = std::thread(&ModbusServer::run, this);
  return true;
}

void ModbusServer::stop() {
  if (thread_.joinable()) {
    stop_ = true;
    uint64_t one = 1;
    if (::write(wake_fd_, &one, sizeof(one)) < 0) {
    }
    thread_.join();
  }
  close_fd(listen_fd_);
  close_fd(wake_fd_);
  clients_ = 0;
}

void ModbusServer::run() {
  auto say = [this](const std::string& s) {
    if (log) log(s);
  };
  std::vector<Client> clients;
  std::vector<pollfd> fds;
  std::vector<uint8_t> resp;
  while (!stop_) {
    fds.clear();
    fds.push_back({wake_fd_, POLLIN, 0});
    fds.push_back({listen_fd_, POLLIN, 0});
    for (const Client& c : clients)
      fds.push_back({c.fd, static_cast<short>(POLLIN | (c.tx.empty() ? 0 : POLLOUT)), 0});
    int timeout = 1000;
    if (::poll(fds.data(), fds.size(), timeout) < 0 && errno != EINTR) break;
    if (stop_) break;
    Clock::time_point now = Clock::now();

    // Existing clients first, so a freed slot can be reused in this round.
    for (size_t i = 0; i < clients.size(); ++i) {
      Client& c = clients[i];
      short re = fds[i + 2].revents;
      bool drop = false;
      if (re & (POLLERR | POLLNVAL)) drop = true;
      if (!drop && (re & (POLLIN | POLLHUP))) {
        uint8_t buf[1024];
        ssize_t got = ::recv(c.fd, buf, sizeof(buf), 0);
        if (got <= 0) {
          drop = !(got < 0 && (errno == EAGAIN || errno == EINTR));
        } else {
          c.rx.insert(c.rx.end(), buf, buf + got);
          c.last = now;
        }
      }
      // Every complete frame in the buffer, in order.
      while (!drop && c.rx.size() >= kMbapSize) {
        uint16_t proto = get_be16(&c.rx[2]);
        uint16_t len = get_be16(&c.rx[4]);
        if (proto != 0 || len < 2 || len > kMaxPdu + 1) {
          say("modbus: closing " + c.peer + ": not a Modbus TCP frame");
          drop = true;
          break;
        }
        if (c.rx.size() < 6u + len) break;
        uint8_t unit = c.rx[6];
        ++c.requests;
        const uint8_t* pdu = &c.rx[kMbapSize];
        size_t n = len - 1u;
        if (unit != cfg_.unit_id && unit != 0 && unit != 255) {
          exception_pdu(pdu[0], kGatewayTargetFailed, resp);
        } else if (handle_pdu(image_, pdu, n, c.may_write, resp) && on_write) {
          on_write();
        }
        uint8_t head[kMbapSize] = {c.rx[0], c.rx[1], 0, 0, 0, 0, unit};
        put_be16(head + 4, static_cast<uint16_t>(resp.size() + 1));
        c.tx.insert(c.tx.end(), head, head + kMbapSize);
        c.tx.insert(c.tx.end(), resp.begin(), resp.end());
        c.rx.erase(c.rx.begin(), c.rx.begin() + 6 + len);
      }
      if (!drop && !c.tx.empty()) {
        ssize_t sent = ::send(c.fd, c.tx.data(), c.tx.size(), MSG_NOSIGNAL);
        if (sent > 0)
          c.tx.erase(c.tx.begin(), c.tx.begin() + sent);
        else if (sent < 0 && errno != EAGAIN && errno != EINTR)
          drop = true;
      }
      if (!drop && now - c.last > std::chrono::milliseconds(cfg_.idle_timeout_ms)) {
        say("modbus: closing " + c.peer + ": idle");
        drop = true;
      }
      if (drop) c.fd = -c.fd - 1;  // marked; removed below
    }
    for (size_t i = clients.size(); i-- > 0;) {
      if (clients[i].fd < 0) {
        ::close(-clients[i].fd - 1);
        clients.erase(clients.begin() + static_cast<std::ptrdiff_t>(i));
      }
    }

    if (fds[1].revents & POLLIN) {
      for (;;) {
        sockaddr_storage peer;
        socklen_t plen = sizeof(peer);
        int fd = ::accept4(listen_fd_, reinterpret_cast<sockaddr*>(&peer), &plen, SOCK_NONBLOCK | SOCK_CLOEXEC);
        if (fd < 0) break;
        const sockaddr* pa = reinterpret_cast<sockaddr*>(&peer);
        std::string who = address_text(pa);
        if (!cfg_.readers.empty() && !cfg_.readers.matches(pa)) {
          say("modbus: refused " + who + ": not in readers");
          ::close(fd);
          continue;
        }
        if (static_cast<int>(clients.size()) >= cfg_.max_clients) {
          say("modbus: refused " + who + ": max_clients reached");
          ::close(fd);
          continue;
        }
        int one = 1;
        ::setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof(one));
        bool writer = cfg_.writers.empty() || cfg_.writers.matches(pa);
        clients.push_back(Client{fd, writer, who, now, {}, {}, 0});
      }
    }
    clients_.store(static_cast<int>(clients.size()), std::memory_order_relaxed);
    {
      std::lock_guard<std::mutex> lock(info_mu_);
      info_.clear();
      for (const Client& c : clients) info_.push_back(ClientInfo{c.peer, c.requests, c.may_write});
    }
  }
  for (Client& c : clients) ::close(c.fd);
  clients_ = 0;
  std::lock_guard<std::mutex> lock(info_mu_);
  info_.clear();
}

std::vector<ClientInfo> ModbusServer::client_list() const {
  std::lock_guard<std::mutex> lock(info_mu_);
  return info_;
}

}  // namespace canworks_bridge
