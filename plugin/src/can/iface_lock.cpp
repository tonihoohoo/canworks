// iface_lock.cpp - see iface_lock.h.

#include "iface_lock.h"

#include <fcntl.h>
#include <sys/file.h>
#include <sys/stat.h>
#include <unistd.h>

#include <cerrno>
#include <cstdlib>
#include <cstring>

#include "log.h"

namespace canopen_plugin {

std::string interface_lock_dir() {
  const char* d = std::getenv("CANWORKS_LOCK_DIR");
  return d && *d ? d : "/run/canworks";
}

bool InterfaceLock::acquire(const std::string& interface, std::string& problem) {
  if (fd_ >= 0) return true;
  std::string dir = interface_lock_dir();
  std::string path = dir + "/" + interface + ".lock";
  ::mkdir(dir.c_str(), 0755);
  int fd = ::open(path.c_str(), O_RDWR | O_CREAT | O_CLOEXEC, 0644);
  if (fd < 0) {
    static bool warned = false;
    if (!warned) log_warn("cannot use the interface lock %s (%s); running without it", path.c_str(), strerror(errno));
    warned = true;
    return true;
  }
  if (::flock(fd, LOCK_EX | LOCK_NB) != 0) {
    char buf[32] = {0};
    ssize_t n = ::pread(fd, buf, sizeof(buf) - 1, 0);
    ::close(fd);
    long pid = n > 0 ? std::strtol(buf, nullptr, 10) : 0;
    problem = "CAN interface " + interface + " is owned by another canworks process" +
              (pid > 0 ? " (process ID " + std::to_string(pid) + ")" : "") + "; not touching it";
    return false;
  }
  std::string pid = std::to_string(static_cast<long>(::getpid())) + "\n";
  if (::ftruncate(fd, 0) == 0) (void)!::pwrite(fd, pid.data(), pid.size(), 0);
  fd_ = fd;
  return true;
}

void InterfaceLock::release() {
  if (fd_ < 0) return;
  ::close(fd_);  // drops the flock
  fd_ = -1;
}

}  // namespace canopen_plugin
