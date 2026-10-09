// trace_capture.h - CAN frame capture for diagnostics traces
// (canopen-online-diagnostics spec, "Frame capture").
//
// A second CAN_RAW socket on the configured interface. Lely keeps local
// loopback on for its own socket, so this socket receives every frame on the
// bus and every frame the master sends; the kernel marks the latter with
// MSG_DONTROUTE. It runs in the diagnostics server thread only, never in the
// bus thread or the PLC scan path, and only while a client has a trace.
//
// Frames go into a ring of TraceRecords with increasing sequence numbers;
// each client fetches after its own cursor.

#ifndef CANOPEN_TRACE_CAPTURE_H
#define CANOPEN_TRACE_CAPTURE_H

#include <cstddef>
#include <cstdint>
#include <memory>
#include <string>
#include <vector>

namespace canopen_plugin {

// One captured frame: 24 bytes, little-endian on the wire as stored (the
// diagnostics protocol sends these records base64-encoded).
struct TraceRecord {
  uint64_t time_us = 0;  // UTC microseconds (kernel receive time)
  uint32_t id = 0;       // SocketCAN can_id: identifier plus CAN_EFF/RTR/ERR flags
  uint8_t dlc = 0;
  uint8_t flags = 0;     // kTraceTx, kTraceGap
  uint8_t reserved[2] = {0, 0};
  uint8_t data[8] = {};
};
static_assert(sizeof(TraceRecord) == 24, "TraceRecord is 24 bytes");

constexpr uint8_t kTraceTx = 0x01;   // sent from this host
constexpr uint8_t kTraceGap = 0x02;  // no frame: capture stopped and restarted here

constexpr uint32_t kCanEff = 0x80000000u;
constexpr uint32_t kCanRtr = 0x40000000u;
constexpr uint32_t kCanErr = 0x20000000u;

struct TraceFilter {
  uint32_t id = 0;
  uint32_t mask = 0;
  bool match(uint32_t can_id) const;
};

// The frames a client asked for: no filters means every data frame; error
// frames only when asked. Gap records always pass.
bool trace_wanted(const TraceRecord& r, const std::vector<TraceFilter>& filters, bool error_frames);

// Fixed-size ring with sequence numbers starting at 1.
class TraceRing {
 public:
  explicit TraceRing(size_t capacity = 65536);

  void push(const TraceRecord& r);
  void clear();  // drops the frames; sequence numbers go on

  uint64_t last_seq() const { return next_seq_ - 1; }  // 0 = nothing recorded yet
  uint64_t oldest_seq() const;                         // first seq still held (last_seq()+1 when empty)
  size_t capacity() const { return buf_.size(); }

  struct Fetch {
    std::vector<TraceRecord> records;
    uint64_t next = 0;  // cursor for the following fetch
    uint64_t lost = 0;  // frames after `after` the ring no longer holds
  };
  // Records with seq > after that `wanted` accepts, at most max of them.
  Fetch fetch(uint64_t after, size_t max, const std::vector<TraceFilter>& filters, bool error_frames) const;

 private:
  std::vector<TraceRecord> buf_;
  uint64_t next_seq_ = 1;
  size_t count_ = 0;
};

// Where frames come from: the CAN_RAW socket, or a fake in tests.
class TraceSource {
 public:
  virtual ~TraceSource() = default;
  // Opens the capture on `interface` with a kernel filter (empty: all) and
  // error frames if asked. Returns 0 or a negative errno.
  virtual int open(const std::string& interface, const std::vector<TraceFilter>& filters, bool error_frames) = 0;
  // Replaces the kernel filter of an open capture.
  virtual int set_filters(const std::vector<TraceFilter>& filters, bool error_frames) = 0;
  virtual int fd() const = 0;  // -1 when closed
  // Reads what is waiting, appends it. Returns false when the interface is
  // gone (the caller closes). `kernel_drops` is the socket's total so far.
  virtual bool drain(std::vector<TraceRecord>& out, uint64_t& kernel_drops) = 0;
  virtual void close() = 0;
};

std::unique_ptr<TraceSource> make_can_trace_source();

// Base64 of the records' bytes.
std::string trace_base64(const std::vector<TraceRecord>& records);

}  // namespace canopen_plugin

#endif  // CANOPEN_TRACE_CAPTURE_H
