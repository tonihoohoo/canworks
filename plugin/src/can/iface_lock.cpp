// iface_lock.cpp - see iface_lock.h.

#include "iface_lock.h"

#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

#include <algorithm>
#include <cerrno>
#include <cstddef>
#include <cstdlib>
#include <cstring>

#include "log.h"

namespace canopen_plugin {

namespace {

// The abstract address of an interface's lock: a leading NUL, then the name.
socklen_t lock_address(const std::string& interface, sockaddr_un& addr) {
  const char* p = std::getenv("CANWORKS_LOCK_PREFIX");
  std::string name = std::string(p && *p ? p : "canworks-iface:") + interface;
  std::memset(&addr, 0, sizeof(addr));
  addr.sun_family = AF_UNIX;
  size_t n = std::min(name.size(), sizeof(addr.sun_path) - 1);
  std::memcpy(addr.sun_path + 1, name.data(), n);
  return static_cast<socklen_t>(offsetof(sockaddr_un, sun_path) + 1 + n);
}

// The process ID behind a held lock, 0 when it cannot be seen (a full
// backlog, or an owner in another PID namespace).
long owner_pid(const sockaddr_un& addr, socklen_t len) {
  int fd = ::socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC | SOCK_NONBLOCK, 0);
  if (fd < 0) return 0;
  long pid = 0;
  if (::connect(fd, reinterpret_cast<const sockaddr*>(&addr), len) == 0) {
    ucred cred{};
    socklen_t cl = sizeof(cred);
    if (::getsockopt(fd, SOL_SOCKET, SO_PEERCRED, &cred, &cl) == 0) pid = cred.pid;
  }
  ::close(fd);
  return pid;
}

}  // namespace

bool InterfaceLock::acquire(const std::string& interface, std::string& problem) {
  if (fd_ >= 0) return true;
  sockaddr_un addr;
  socklen_t len = lock_address(interface, addr);
  int fd = ::socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC | SOCK_NONBLOCK, 0);
  if (fd < 0) {
    static bool warned = false;
    if (!warned) log_warn("cannot use the interface lock (%s); running without it", strerror(errno));
    warned = true;
    return true;
  }
  if (::bind(fd, reinterpret_cast<const sockaddr*>(&addr), len) != 0) {
    int err = errno;
    ::close(fd);
    if (err != EADDRINUSE) {
      static bool warned = false;
      if (!warned) log_warn("cannot use the interface lock (%s); running without it", strerror(err));
      warned = true;
      return true;
    }
    long pid = owner_pid(addr, len);
    problem = "CAN interface " + interface + " is owned by another canworks process" +
              (pid > 0 ? " (process ID " + std::to_string(pid) + ")" : "") + "; not touching it";
    return false;
  }
  // Listening lets another process ask for the owner's process ID; nothing
  // is ever accepted, and a full backlog only hides the ID.
  ::listen(fd, 8);
  fd_ = fd;
  return true;
}

void InterfaceLock::release() {
  if (fd_ < 0) return;
  ::close(fd_);  // frees the abstract name
  fd_ = -1;
}

}  // namespace canopen_plugin
