// iface_lock.h - one owner per real CAN interface (modbus-bridge "One owner
// per interface"): every canworks process (OpenPLC plugin or Modbus bridge)
// binds the abstract Unix socket "canworks-iface:<interface>" before it
// brings the interface up, and keeps it while the network runs. Abstract
// sockets live in the network namespace, the same scope as the interface
// names, so the lock also holds between the runtime's Docker container (on
// the host network) and a bridge on the host, and it goes away with its
// process. $CANWORKS_LOCK_PREFIX replaces "canworks-iface:" (tests). A lock
// that cannot be used is not an error: the network runs without it (logged
// once).

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
  // False when another process holds it: `problem` names the interface and,
  // when it can be seen from here, the owner's process ID.
  bool acquire(const std::string& interface, std::string& problem);
  void release();
  bool held() const { return fd_ >= 0; }

 private:
  int fd_ = -1;
};

}  // namespace canopen_plugin

#endif  // CANWORKS_IFACE_LOCK_H
