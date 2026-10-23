// supervisor.cpp - see supervisor.h.

#include "supervisor.h"

#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

#include <cstddef>
#include <cstdlib>
#include <cstring>
#include <map>

#include "progress.h"

namespace canworks_bridge {

bool sd_notify_state(const std::string& state) {
  const char* path = std::getenv("NOTIFY_SOCKET");
  if (!path || !*path) return false;
  sockaddr_un addr;
  std::memset(&addr, 0, sizeof(addr));
  addr.sun_family = AF_UNIX;
  size_t len = std::strlen(path);
  if (len >= sizeof(addr.sun_path)) return false;
  std::memcpy(addr.sun_path, path, len);
  if (addr.sun_path[0] == '@') addr.sun_path[0] = '\0';  // abstract namespace
  int fd = ::socket(AF_UNIX, SOCK_DGRAM | SOCK_CLOEXEC, 0);
  if (fd < 0) return false;
  socklen_t alen = static_cast<socklen_t>(offsetof(sockaddr_un, sun_path) + len);
  bool ok = ::sendto(fd, state.data(), state.size(), MSG_NOSIGNAL, reinterpret_cast<sockaddr*>(&addr), alen) ==
            static_cast<ssize_t>(state.size());
  ::close(fd);
  return ok;
}

Supervisor::Supervisor(Options opt) : opt_(std::move(opt)) {
  if (!opt_.notify) opt_.notify = [](const std::string& s) { sd_notify_state(s); };
  if (!opt_.on_stall) opt_.on_stall = [](const std::string&) { std::abort(); };
}

void Supervisor::start() {
  if (thread_.joinable()) return;
  stop_ = false;
  thread_ = std::thread(&Supervisor::run, this);
}

void Supervisor::stop() {
  {
    std::lock_guard<std::mutex> lock(mu_);
    stop_ = true;
  }
  cv_.notify_all();
  if (thread_.joinable()) thread_.join();
}

void Supervisor::run() {
  using Clock = std::chrono::steady_clock;
  struct Seen {
    uint64_t count;
    Clock::time_point since;  // when the count last changed
  };
  std::map<uint64_t, Seen> seen;
  Clock::time_point next_notify = Clock::now();
  std::unique_lock<std::mutex> lock(mu_);
  while (!stop_) {
    cv_.wait_for(lock, opt_.tick, [this] { return stop_; });
    if (stop_) break;
    Clock::time_point now = Clock::now();
    bool fresh = true;
    if (paused_) {
      seen.clear();  // the threads after the pause start their own count
    } else {
      std::map<uint64_t, Seen> next;
      for (const auto& s : canopen_plugin::progress_snapshot()) {
        auto it = seen.find(s.id);
        Seen v = it == seen.end() || it->second.count != s.count ? Seen{s.count, now} : it->second;
        next[s.id] = v;
        if (now - v.since >= opt_.stall) {
          lock.unlock();
          opt_.on_stall(s.name);
          lock.lock();
          v.since = now;  // a test's on_stall returns: report again only after another stall time
          next[s.id] = v;
        }
        if (now - v.since >= opt_.fresh) fresh = false;
      }
      seen.swap(next);
    }
    if (fresh && now >= next_notify) {
      next_notify = now + opt_.notify_every;
      lock.unlock();
      opt_.notify("WATCHDOG=1");
      lock.lock();
    }
  }
}

}  // namespace canworks_bridge
