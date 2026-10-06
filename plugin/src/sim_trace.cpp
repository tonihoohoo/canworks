#include "sim_trace.h"

#include <cerrno>
#include <cstring>
#include <fcntl.h>
#include <sys/time.h>
#include <unistd.h>

#include <lely/can/msg.h>

namespace canopen_plugin {

SimTraceTap::SimTraceTap() {
  if (pipe2(pipe_, O_NONBLOCK | O_CLOEXEC) != 0) pipe_[0] = pipe_[1] = -1;
}

SimTraceTap::~SimTraceTap() {
  for (int fd : pipe_)
    if (fd >= 0) ::close(fd);
}

void SimTraceTap::push(const can_msg& msg) {
  if (!on_.load(std::memory_order_acquire) || pipe_[1] < 0) return;
  TraceRecord r;
  timeval tv{};
  gettimeofday(&tv, nullptr);
  r.time_us = uint64_t(tv.tv_sec) * 1000000u + uint64_t(tv.tv_usec);
  r.id = msg.id & ((msg.flags & CAN_FLAG_IDE) ? 0x1FFFFFFFu : 0x7FFu);
  if (msg.flags & CAN_FLAG_IDE) r.id |= kCanEff;
  if (msg.flags & CAN_FLAG_RTR) r.id |= kCanRtr;
  r.dlc = msg.len > 8 ? 8 : msg.len;
  std::memcpy(r.data, msg.data, r.dlc);
  // A record is far below PIPE_BUF, so it is written whole or not at all.
  if (write(pipe_[1], &r, sizeof r) != static_cast<ssize_t>(sizeof r)) drops_.fetch_add(1);
}

namespace {

class SimTraceSource : public TraceSource {
 public:
  explicit SimTraceSource(std::shared_ptr<SimTraceTap> tap) : tap_(std::move(tap)) {}
  int open(const std::string&, const std::vector<TraceFilter>&, bool) override {
    if (tap_->read_fd() < 0) return -EIO;
    Flush();
    tap_->enable(true);
    open_ = true;
    return 0;
  }
  int set_filters(const std::vector<TraceFilter>&, bool) override { return 0; }  // the ring filters
  int fd() const override { return open_ ? tap_->read_fd() : -1; }
  bool drain(std::vector<TraceRecord>& out, uint64_t& kernel_drops) override {
    TraceRecord r;
    while (read(tap_->read_fd(), &r, sizeof r) == static_cast<ssize_t>(sizeof r)) out.push_back(r);
    kernel_drops = tap_->drops();
    return true;
  }
  void close() override {
    tap_->enable(false);
    open_ = false;
    Flush();
  }

 private:
  void Flush() {
    TraceRecord r;
    while (read(tap_->read_fd(), &r, sizeof r) > 0) {
    }
  }
  std::shared_ptr<SimTraceTap> tap_;
  bool open_ = false;
};

}  // namespace

std::unique_ptr<TraceSource> make_sim_trace_source(std::shared_ptr<SimTraceTap> tap) {
  return std::unique_ptr<TraceSource>(new SimTraceSource(std::move(tap)));
}

}  // namespace canopen_plugin
