// iface_lock.h - one owner per real CAN interface (modbus-bridge "One owner
// per interface"): every canworks process (OpenPLC plugin or Modbus bridge)
// takes an exclusive flock on <lock dir>/<interface>.lock before it brings
// the interface up, and keeps it while the network runs. The lock dir is
// $CANWORKS_LOCK_DIR, else /run/canworks. A lock dir that cannot be made or
// written is not an error: the network runs without the lock (logged once).

#ifndef CANWORKS_IFACE_LOCK_H
#define CANWORKS_IFACE_LOCK_H

#include <string>

namespace canopen_plugin {

class InterfaceLock {
 public:
  InterfaceLock() = default;
  ~InterfaceLock() { release(); }
  InterfaceLock(const InterfaceLock&) = delete;
  InterfaceLock& operator=(const InterfaceLock&) = delete;

  // True when this process holds the lock now (or no lock could be used).
  // False when another process holds it: `problem` names the interface and
  // the owner's process ID.
  bool acquire(const std::string& interface, std::string& problem);
  void release();
  bool held() const { return fd_ >= 0; }

 private:
  int fd_ = -1;
};

std::string interface_lock_dir();

}  // namespace canopen_plugin

#endif  // CANWORKS_IFACE_LOCK_H
