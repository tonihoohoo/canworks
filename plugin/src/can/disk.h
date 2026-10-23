// disk.h - why a folder cannot take the bridge's generated files
// (modbus-bridge "Full or read-only config folder").

#ifndef CANWORKS_DISK_H
#define CANWORKS_DISK_H

#include <sys/statvfs.h>

#include <cstdlib>
#include <string>

namespace canopen_plugin {

// Below this much free space a folder counts as full.
constexpr unsigned long long kMinFreeBytes = 1ull << 20;

// "" when `dir` is writable and has room; otherwise the reason, naming the
// folder and its free space, for a message that the bridge writes its
// generated files there.
inline std::string disk_problem(const std::string& dir) {
  struct statvfs vfs;
  if (::statvfs(dir.c_str(), &vfs) != 0) return "";
  if (vfs.f_flag & ST_RDONLY) return dir + " is on a read-only file system";
  unsigned long long avail = static_cast<unsigned long long>(vfs.f_bavail) * vfs.f_frsize;
  unsigned long long min = kMinFreeBytes;
  if (const char* t = std::getenv("CANWORKS_TEST_MIN_FREE_BYTES")) min = std::strtoull(t, nullptr, 10);  // tests
  if (avail >= min) return "";
  return "no space left in " + dir + " (" + std::to_string(avail / 1024) + " KiB free)";
}

}  // namespace canopen_plugin

#endif  // CANWORKS_DISK_H
