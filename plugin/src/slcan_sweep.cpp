#include "slcan_sweep.h"

#include <algorithm>
#include <cerrno>
#include <chrono>
#include <cstdlib>
#include <linux/can.h>
#include <poll.h>
#include <unistd.h>

namespace canopen_plugin {

namespace {

const unsigned kSlcanRates[9] = {10, 20, 50, 100, 125, 250, 500, 800, 1000};  // kbit/s of S0..S8
const int kReplyMs = 200;  // how long a mode command's answer may take

int wait_readable(int fd, int ms) {
  pollfd p{fd, POLLIN, 0};
  int r = poll(&p, 1, ms);
  if (r < 0) return errno == EINTR ? 0 : -errno;
  if (r > 0 && (p.revents & (POLLERR | POLLHUP | POLLNVAL)) && !(p.revents & POLLIN)) return -EIO;
  return r;
}

}  // namespace

SlcanSweepPort::~SlcanSweepPort() {
  if (fd_ >= 0) set_up("", false);
}

int SlcanSweepPort::send(const std::string& cmd) {
  std::string s = cmd + "\r";
  size_t off = 0;
  while (off < s.size()) {
    ssize_t n = ::write(fd_, s.data() + off, s.size() - off);
    if (n < 0) {
      if (errno == EINTR) continue;
      return -errno;
    }
    off += static_cast<size_t>(n);
  }
  ++unanswered_;
  return 0;
}

bool SlcanSweepPort::ask(const std::string& cmd) {
  // The firmware answers every command with CR or BEL, in order: the answer
  // to `cmd` is the one after those to the commands sent before it. Frame
  // lines received in between are no answers.
  const unsigned want = unanswered_ + 1;
  if (send(cmd) < 0) return false;
  unanswered_ = 0;
  using clock = std::chrono::steady_clock;
  const auto end = clock::now() + std::chrono::milliseconds(kReplyMs);
  unsigned got = 0;
  std::string line;
  char buf[256];
  for (;;) {
    auto left = std::chrono::duration_cast<std::chrono::milliseconds>(end - clock::now()).count();
    if (left <= 0 || wait_readable(fd_, static_cast<int>(left)) <= 0) return false;
    ssize_t n = ::read(fd_, buf, sizeof buf);
    if (n <= 0) return false;
    for (ssize_t i = 0; i < n; ++i) {
      const char c = buf[i];
      if (c != '\r' && c != '\a') {
        if (line.size() < 64) line += c;
        continue;
      }
      const bool frame = c == '\r' && !line.empty();
      line.clear();
      if (frame) continue;
      if (++got == want) return c == '\r';
    }
  }
}

int SlcanSweepPort::get(const std::string&, LinkInfo& out) {
  out = LinkInfo{};
  out.kind = "can";
  return 0;
}

int SlcanSweepPort::set_up(const std::string&, bool up) {
  if (!up) {
    int rc = send("C");
    if (silent_) {
      int m = send("m0");
      if (rc == 0) rc = m;
      silent_ = false;
    }
    return rc;
  }
  if (!listen_only_) return 0;
  silent_ = ask("m1");
  if (silent_) used_silent_ = true;
  return send(silent_ ? "O" : "L");
}

int SlcanSweepPort::set_bitrate(const std::string&, unsigned bitrate, long) {
  for (unsigned i = 0; i < 9; ++i)
    if (kSlcanRates[i] * 1000u == bitrate) return send("S" + std::to_string(i));
  return -EINVAL;
}

int SlcanSweepPort::set_listen_only(const std::string&, bool on) {
  listen_only_ = on;
  return 0;
}

void SlcanSweepPort::count(const std::string& line, SweepRate& out) {
  if (line.empty()) return;
  const char kind = line[0];
  size_t id_len;
  if (kind == 't' || kind == 'r')
    id_len = 3;
  else if (kind == 'T' || kind == 'R')
    id_len = 8;
  else
    return;  // answers to commands, status
  if (line.size() < 1 + id_len + 1) return;
  char* end = nullptr;
  std::string hex = line.substr(1, id_len);
  unsigned long id = std::strtoul(hex.c_str(), &end, 16);
  if (!end || *end) return;
  uint32_t ident = static_cast<uint32_t>(id) | (id_len == 8 ? CAN_EFF_FLAG : 0u);
  ++out.frames;
  if (out.ids.size() < 16 && std::find(out.ids.begin(), out.ids.end(), ident) == out.ids.end())
    out.ids.push_back(ident);
}

int SlcanSweepPort::listen(const std::string&, unsigned ms, SweepRate& out, const std::function<bool()>& stop) {
  using clock = std::chrono::steady_clock;
  const auto end = clock::now() + std::chrono::milliseconds(ms);
  pending_.clear();
  unanswered_ = 0;  // answers read here are empty lines
  char buf[512];
  for (;;) {
    auto now = clock::now();
    if (now >= end || stop()) return 0;
    int wait = static_cast<int>(std::chrono::duration_cast<std::chrono::milliseconds>(end - now).count());
    int r = wait_readable(fd_, std::min(wait, 100));
    if (r < 0) return r;
    if (r == 0) continue;
    ssize_t n = ::read(fd_, buf, sizeof buf);
    if (n < 0) {
      if (errno == EINTR || errno == EAGAIN) continue;
      return -errno;
    }
    if (n == 0) return -EIO;  // the adapter went away
    for (ssize_t i = 0; i < n; ++i) {
      char c = buf[i];
      if (c == '\r') {
        count(pending_, out);
        pending_.clear();
      } else if (c == '\a') {
        pending_.clear();
      } else if (pending_.size() < 64) {
        pending_ += c;
      }
    }
  }
}

}  // namespace canopen_plugin
