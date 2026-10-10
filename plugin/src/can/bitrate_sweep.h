// bitrate_sweep.h - bit rate detection on a network's interface
// (canopen-online-diagnostics spec, "Bit rate detection").
//
// Runs in the bus thread between two CANopen sessions: for each rate the
// link is taken down, set to that rate in listen-only mode and brought up,
// and a CAN_RAW socket counts the valid frames, error frames and identifiers
// it receives. Listen-only: the controller sends nothing, not even an
// acknowledge or an error flag. At the end the link gets its configured rate
// without listen-only again, also when the sweep failed or was stopped.

#ifndef CANOPEN_BITRATE_SWEEP_H
#define CANOPEN_BITRATE_SWEEP_H

#include <atomic>
#include <cstdint>
#include <functional>
#include <memory>
#include <string>
#include <vector>

#include "can_adapter.h"

typedef struct cJSON cJSON;

namespace canopen_plugin {

// The CiA 301 bit rates, in the default sweep order.
extern const unsigned kSweepRates[8];

struct SweepRequest {
  std::vector<unsigned> rates_kbit;  // default: kSweepRates
  unsigned per_rate_ms = 1000;
  unsigned rounds = 1;
  std::string peer;  // the client, for the log
  // Sweep also on an adapter that does not confirm listen-only (slcan
  // firmware that answers nothing to its silent mode command), which may
  // disturb the bus at a wrong bit rate.
  bool disturb_bus = false;
  // Set by detect_bitrate_stop (DiagHub::stop_sweep): the sweep ends after
  // its current rate. `stopped_by` names the client (read once it is set).
  std::shared_ptr<std::atomic<bool>> cancel;
  std::shared_ptr<std::string> stopped_by;
};

// The refusal when the adapter does not confirm listen-only; the request may
// be repeated with disturb_bus.
extern const char* const kUnconfirmedListenOnly;

struct SweepRate {
  unsigned bitrate_kbit = 0;
  uint64_t frames = 0;
  uint64_t error_frames = 0;
  std::vector<uint32_t> ids;  // first 16 distinct identifiers (with CAN_EFF_FLAG for extended ones)
};

enum class SweepVerdict { None, Detected, Ambiguous, Silent, Failed };
const char* sweep_verdict_name(SweepVerdict v);

struct SweepResult {
  SweepVerdict verdict = SweepVerdict::None;
  unsigned bitrate_kbit = 0;           // Detected
  std::vector<unsigned> candidates;    // Ambiguous
  std::vector<SweepRate> results;      // per rate, summed over the rounds, in sweep order
  std::string error;                   // Failed
};

// The verdict from per-rate counts (design D5): a rate matches when it saw a
// valid frame and its error frames are at most 1 % of its valid frames.
void decide_sweep(SweepResult& r);

// Counts what arrives on the interface for a while; behind an interface so
// tests can fake the bus.
class SweepListener {
 public:
  virtual ~SweepListener() = default;
  // Listens on `interface` for `ms`, adding to `out`. Returns 0 or a negative
  // errno. `stop` is polled; true ends the listening early.
  virtual int listen(const std::string& interface, unsigned ms, SweepRate& out,
                     const std::function<bool()>& stop) = 0;
};

std::unique_ptr<SweepListener> make_can_sweep_listener();

struct SweepProgress {
  unsigned rate_kbit = 0;
  unsigned round = 0;  // 1-based
  unsigned done = 0, total = 0;
  const std::vector<SweepRate>* results = nullptr;
};

// The sweep. `restart_ms` is the adapter's bus-off restart (-1: not set),
// restored with the configured bit rate. `stop` ends it early (PLC stop),
// `req.cancel` after the current rate; the link is restored anyway: the
// configured bit rate is always set, and bringing the link up is tried
// twice.
SweepResult run_bitrate_sweep(LinkOps& ops, SweepListener& listener, const std::string& interface,
                              unsigned configured_bitrate, long restart_ms, const SweepRequest& req,
                              const std::function<void(const SweepProgress&)>& progress,
                              const std::function<bool()>& stop);

}  // namespace canopen_plugin

#endif  // CANOPEN_BITRATE_SWEEP_H
