#include "bitrate_sweep.h"

#include <algorithm>
#include <cerrno>
#include <chrono>
#include <cstring>
#include <linux/can.h>
#include <linux/can/raw.h>
#include <net/if.h>
#include <poll.h>
#include <sys/socket.h>
#include <unistd.h>

#include "log.h"

namespace canopen_plugin {

const char* const kUnconfirmedListenOnly =
    "the adapter did not answer its silent mode command, so it may not only listen: at a wrong bit rate it can "
    "send error frames that disturb the devices on the bus; disturb_bus needed";

const unsigned kSweepRates[8] = {1000, 800, 500, 250, 125, 50, 20, 10};

const char* sweep_verdict_name(SweepVerdict v) {
  switch (v) {
    case SweepVerdict::Detected: return "detected";
    case SweepVerdict::Ambiguous: return "ambiguous";
    case SweepVerdict::Silent: return "silent";
    case SweepVerdict::Failed: return "failed";
    default: return "";
  }
}

void decide_sweep(SweepResult& r) {
  if (r.verdict == SweepVerdict::Failed) return;
  r.candidates.clear();
  r.bitrate_kbit = 0;
  uint64_t total = 0;
  const SweepRate* most = nullptr;
  for (const auto& s : r.results) {
    total += s.frames;
    if (s.frames && s.error_frames * 100 <= s.frames) r.candidates.push_back(s.bitrate_kbit);
    if (s.frames && (!most || s.frames > most->frames)) most = &s;
  }
  if (r.candidates.size() == 1) {
    r.verdict = SweepVerdict::Detected;
    r.bitrate_kbit = r.candidates[0];
    r.candidates.clear();
  } else if (!r.candidates.empty()) {
    r.verdict = SweepVerdict::Ambiguous;
  } else if (total) {
    // Frames, but with errors everywhere: the best guess is where most came.
    r.verdict = SweepVerdict::Ambiguous;
    r.candidates.push_back(most->bitrate_kbit);
  } else {
    r.verdict = SweepVerdict::Silent;
  }
}

namespace {

class CanSweepListener : public SweepListener {
 public:
  int listen(const std::string& interface, unsigned ms, SweepRate& out, const std::function<bool()>& stop) override {
    int fd = socket(PF_CAN, SOCK_RAW | SOCK_NONBLOCK | SOCK_CLOEXEC, CAN_RAW);
    if (fd < 0) return -errno;
    can_err_mask_t err_mask = CAN_ERR_MASK;
    setsockopt(fd, SOL_CAN_RAW, CAN_RAW_ERR_FILTER, &err_mask, sizeof err_mask);
    unsigned index = if_nametoindex(interface.c_str());
    sockaddr_can addr{};
    addr.can_family = AF_CAN;
    addr.can_ifindex = static_cast<int>(index);
    if (!index || bind(fd, reinterpret_cast<sockaddr*>(&addr), sizeof addr) < 0) {
      int e = index ? -errno : -ENODEV;
      close(fd);
      return e;
    }
    using clock = std::chrono::steady_clock;
    const auto end = clock::now() + std::chrono::milliseconds(ms);
    int rc = 0;
    for (;;) {
      auto now = clock::now();
      if (now >= end || stop()) break;
      int wait = static_cast<int>(std::chrono::duration_cast<std::chrono::milliseconds>(end - now).count());
      pollfd p{fd, POLLIN, 0};
      int r = poll(&p, 1, std::min(wait, 100));
      if (r < 0 && errno != EINTR) {
        rc = -errno;
        break;
      }
      if (r <= 0) continue;
      can_frame f;
      ssize_t n;
      while ((n = read(fd, &f, sizeof f)) == static_cast<ssize_t>(sizeof f)) {
        if (f.can_id & CAN_ERR_FLAG) {
          ++out.error_frames;
          continue;
        }
        ++out.frames;
        uint32_t id = f.can_id & ((f.can_id & CAN_EFF_FLAG) ? (CAN_EFF_MASK | CAN_EFF_FLAG) : CAN_SFF_MASK);
        if (out.ids.size() < 16 && std::find(out.ids.begin(), out.ids.end(), id) == out.ids.end())
          out.ids.push_back(id);
      }
      if (n < 0 && errno != EAGAIN && errno != EWOULDBLOCK) {
        rc = -errno;
        break;
      }
    }
    close(fd);
    return rc;
  }
};

std::string errtext(int rc) { return std::strerror(-rc); }

}  // namespace

std::unique_ptr<SweepListener> make_can_sweep_listener() {
  return std::unique_ptr<SweepListener>(new CanSweepListener);
}

SweepResult run_bitrate_sweep(LinkOps& ops, SweepListener& listener, const std::string& interface,
                              unsigned configured_bitrate, long restart_ms, const SweepRequest& req,
                              const std::function<void(const SweepProgress&)>& progress,
                              const std::function<bool()>& stop) {
  SweepResult res;
  std::vector<unsigned> rates = req.rates_kbit;
  if (rates.empty()) rates.assign(std::begin(kSweepRates), std::end(kSweepRates));
  for (unsigned k : rates) {
    SweepRate s;
    s.bitrate_kbit = k;
    res.results.push_back(s);
  }
  const unsigned rounds = std::max(1u, req.rounds);
  SweepProgress pg;
  pg.total = static_cast<unsigned>(rates.size()) * rounds;
  pg.results = &res.results;
  auto fail = [&](const std::string& why) {
    res.verdict = SweepVerdict::Failed;
    res.error = why;
  };

  bool stopped = false;
  for (unsigned round = 1; round <= rounds && res.verdict != SweepVerdict::Failed && !stopped; ++round) {
    for (size_t i = 0; i < rates.size(); ++i) {
      if (stop()) {
        stopped = true;
        break;
      }
      pg.rate_kbit = rates[i];
      pg.round = round;
      progress(pg);
      int rc = ops.set_up(interface, false);
      if (rc == 0) rc = ops.set_bitrate(interface, rates[i] * 1000u, -1);
      if (rc < 0) {
        fail("cannot set " + interface + " to " + std::to_string(rates[i]) + " kbit/s: " + errtext(rc));
        break;
      }
      rc = ops.set_listen_only(interface, true);
      if (rc == -EOPNOTSUPP || rc == -EINVAL) {
        fail("the adapter's driver has no listen-only mode");
        break;
      }
      if (rc < 0) {
        fail("cannot set " + interface + " listen-only: " + errtext(rc));
        break;
      }
      if ((rc = ops.set_up(interface, true)) < 0) {
        fail("cannot bring " + interface + " up: " + errtext(rc));
        break;
      }
      rc = listener.listen(interface, req.per_rate_ms, res.results[i], stop);
      if (rc < 0) {
        fail("cannot listen on " + interface + ": " + errtext(rc));
        break;
      }
      ++pg.done;
    }
    if (res.verdict == SweepVerdict::Failed || stopped) break;
    // A clear answer ends the sweep early.
    SweepResult probe = res;
    decide_sweep(probe);
    if (probe.verdict == SweepVerdict::Detected) break;
  }
  pg.rate_kbit = 0;
  pg.done = pg.total;
  progress(pg);

  // Back to the configured rate, without listen-only, whatever happened.
  int rc = ops.set_up(interface, false);
  int lo = ops.set_listen_only(interface, false);
  if (lo < 0 && lo != -EOPNOTSUPP && lo != -EINVAL && rc == 0) rc = lo;
  if (rc == 0) rc = ops.set_bitrate(interface, configured_bitrate, restart_ms);
  if (rc == 0) rc = ops.set_up(interface, true);
  if (rc < 0)
    log_warn("bit rate detection: cannot restore %s to %u bit/s: %s; retrying with the next CANopen session",
             interface.c_str(), configured_bitrate, errtext(rc).c_str());
  if (stopped && res.verdict != SweepVerdict::Failed) fail("stopped (the PLC stopped)");
  decide_sweep(res);
  return res;
}

}  // namespace canopen_plugin
