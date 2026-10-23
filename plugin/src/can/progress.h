// progress.h - progress counters of the threads canworks-bridge watches
// (modbus-bridge "Stall watchdog").
//
// A watched thread keeps a ThreadProgress on its stack for as long as it
// runs and calls beat() once per round of its loop, including the rounds it
// only waits. The bridge's supervisor reads every counter with
// progress_snapshot(); a thread that has ended is no longer listed, so a
// stopped network never counts as stalled.

#ifndef CANWORKS_PROGRESS_H
#define CANWORKS_PROGRESS_H

#include <algorithm>
#include <atomic>
#include <cstdint>
#include <mutex>
#include <string>
#include <vector>

namespace canopen_plugin {

class ThreadProgress;

struct ProgressSample {
  uint64_t id;       // unique per ThreadProgress, never reused
  std::string name;  // what the log names when it stalls
  uint64_t count;
};

namespace progress_detail {
struct Registry {
  std::mutex mu;
  std::vector<ThreadProgress*> list;
};
inline Registry& registry() {
  static Registry r;
  return r;
}
inline uint64_t next_id() {
  static std::atomic<uint64_t> n{0};
  return ++n;
}
}  // namespace progress_detail

// The calling thread's counter, for beats from deep in its loop.
inline ThreadProgress*& current_progress() {
  thread_local ThreadProgress* p = nullptr;
  return p;
}

class ThreadProgress {
 public:
  // Listed from now on, and the calling thread's counter (progress_beat()).
  explicit ThreadProgress(std::string name) : name_(std::move(name)), id_(progress_detail::next_id()) {
    auto& r = progress_detail::registry();
    {
      std::lock_guard<std::mutex> lock(r.mu);
      r.list.push_back(this);
    }
    outer_ = current_progress();
    current_progress() = this;
  }
  ~ThreadProgress() {
    current_progress() = outer_;
    auto& r = progress_detail::registry();
    std::lock_guard<std::mutex> lock(r.mu);
    r.list.erase(std::remove(r.list.begin(), r.list.end(), this), r.list.end());
  }
  ThreadProgress(const ThreadProgress&) = delete;
  ThreadProgress& operator=(const ThreadProgress&) = delete;

  void beat() { count_.fetch_add(1, std::memory_order_relaxed); }
  const std::string& name() const { return name_; }
  uint64_t id() const { return id_; }
  uint64_t count() const { return count_.load(std::memory_order_relaxed); }

 private:
  std::string name_;
  uint64_t id_;
  std::atomic<uint64_t> count_{0};
  ThreadProgress* outer_ = nullptr;
};

// One beat of the calling thread's counter; nothing on an unwatched thread.
inline void progress_beat() {
  if (ThreadProgress* p = current_progress()) p->beat();
}

// "<what> of network <name>" (or its index when it has no name).
inline std::string network_thread_name(const char* what, const std::string& name, unsigned index) {
  return std::string(what) + " of network " + (name.empty() ? std::to_string(index) : name);
}

inline std::vector<ProgressSample> progress_snapshot() {
  auto& r = progress_detail::registry();
  std::lock_guard<std::mutex> lock(r.mu);
  std::vector<ProgressSample> out;
  out.reserve(r.list.size());
  for (const ThreadProgress* p : r.list) out.push_back(ProgressSample{p->id(), p->name(), p->count()});
  return out;
}

}  // namespace canopen_plugin

#endif  // CANWORKS_PROGRESS_H
