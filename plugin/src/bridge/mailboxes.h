// mailboxes.h - the bridge's mailboxes (modbus-bridge-mailboxes spec): the
// request mailboxes, the receive mailbox, the network info blocks and the
// cyclic job table the function blocks over Modbus use (bridge-plc-blocks).
//
// Like bridge_blocks.h this works on plain byte blocks of the image; what a
// request does on the bus goes through a MailboxBackend (mailbox_engine.cpp
// for the engine, a fake in the tests). One thread calls service() and the
// other members (the bridge loop, every millisecond).
//
// Register layout, one word per register, high byte first:
//
//   request (72 holding registers)   response (72 input registers)
//   0     counter                    0     counter echo
//   1     op << 8 | network          1     state << 8 | ERROR_ID
//   2-7   arguments                  2-7   results
//   8-71  data, 128 bytes            8-71  data, 128 bytes
//
//   receive mailbox (120 input registers per receive block, 1 or 2 blocks
//   one after the other; a batch spans all of them)
//   0     batch sequence (starts at a different value each run)
//   1-2   receivers present in the batch (word 1 bits 31-16, word 2 bits 15-0)
//   3     record words used
//   4     tick (milliseconds, wraps)
//   5-20  receiver generations, receiver 2k in the high byte of word 5 + k
//         (0: closed)
//   21-24 batch time: the first record's receive time in UTC microseconds
//   25-   records
//   acknowledgement (3 holding registers): batch seen, pending (2 words)
//
//   network info (18 input registers per network, the first 8)
//   0 CAN state << 8 | bus load %, 1 TX errors, 2 RX errors, 3-4 bus-offs,
//   5-6 frames received, 7-8 frames sent, 9-10 error frames, 11 J1939 state
//   << 8 | address (16#FF << 8 | the J1939 ERROR_ID when the network has no
//   J1939 view: 1 not running, 10 not a J1939 network), 12-15 NAME, 16 ECU
//   count, 17 update counter
//
//   cyclic job table (input): 0 tick, then per job 4 registers: state << 8
//   | ERROR_ID, generation, frame count (2); keepalive (1 holding register
//   per job)
//
// A record: 0 receiver << 8 | kind << 4 | flags, 1 still queued, 2 dropped
// (low 16 bits), then CAN (10 words): id (2), flags << 8 | DLC, data (4);
// J1939 (12 words): PGN (2), source << 8 | destination, priority, length,
// first 8 bytes (4); EMCY (12 words): receive time in UTC microseconds (4),
// node << 8 | error register, error code, manufacturer bytes (3).

#ifndef CANWORKS_BRIDGE_MAILBOXES_H
#define CANWORKS_BRIDGE_MAILBOXES_H

#include <array>
#include <chrono>
#include <cstdint>
#include <memory>
#include <string>
#include <vector>

namespace canworks_bridge {

constexpr unsigned kMbWords = 72;
constexpr unsigned kMbBytes = kMbWords * 2;
constexpr unsigned kMbArgs = 6;
constexpr unsigned kMbChunk = 128;
constexpr unsigned kMbBuffer = 1785;
constexpr unsigned kRxWords = 120;  // one receive block
constexpr unsigned kRxBytes = kRxWords * 2;
constexpr unsigned kRxHeaderWords = 25;
constexpr unsigned kMaxRxBlocks = 2;
constexpr unsigned kRxAckBytes = 6;
constexpr unsigned kInfoWords = 18;
constexpr unsigned kInfoBytes = kInfoWords * 2;
constexpr unsigned kJobWords = 4;
constexpr unsigned kMaxRequestMailboxes = 4;
constexpr unsigned kMaxReceivers = 32;
constexpr unsigned kMaxCyclicJobs = 16;
constexpr unsigned kInfoNetworks = 8;

enum MbOp : uint8_t {
  kOpNone = 0,
  kOpStage = 1,
  kOpFetch = 2,
  kOpSdoRead = 3,
  kOpSdoWrite = 4,
  kOpCanSend = 5,
  kOpCyclicSet = 6,
  kOpCyclicStop = 7,
  kOpRxOpen = 8,
  kOpRxClose = 9,
  kOpRxFetch = 10,
  kOpJ1939Send = 11,
  kOpJ1939Request = 12,
  kOpDmRead = 13,
  kOpDmClear = 14,
  kOpFindEcu = 15,
};
enum MbState : uint8_t { kMbIdle = 0, kMbBusy = 1, kMbDone = 2, kMbError = 3 };
enum RxKind : uint8_t { kRxCan = 1, kRxJ1939 = 2, kRxEmcy = 3 };
enum RxFlag : uint8_t { kRecLong = 0x01, kRecRestart = 0x02, kRecOverflow = 0x04 };
// RX_OPEN flags per kind.
constexpr uint8_t kRxCanExtended = 0x01, kRxCanAny = 0x04;
constexpr uint8_t kRxJ1939Any = 0x01, kRxJ1939AllDestinations = 0x02, kRxJ1939FilterSource = 0x04;
constexpr uint8_t kRxEmcySkipOld = 0x01;

// The block families' ERROR_IDs the mailboxes give themselves.
enum Family : uint8_t { kFamilySdo, kFamilyCan, kFamilyJ1939 };
uint8_t family_of(uint8_t op);
// "invalid input", "no such network", "cancelled", "no free receiver or job".
uint8_t err_input(Family f);
uint8_t err_network(Family f);
uint8_t err_cancelled(Family f);
uint8_t err_full(Family f);

// Where the blocks are, as byte offsets in the image.
struct MailboxLayout {
  unsigned requests = 0;
  bool receive = false;
  unsigned receive_blocks = 1;
  unsigned info_networks = 0;
  unsigned cyclic_jobs = 0;
  uint32_t in_base = 0, out_base = 0;

  uint32_t response(unsigned m) const { return in_base + m * kMbBytes; }
  uint32_t receive_block() const { return in_base + requests * kMbBytes; }
  uint32_t receive_bytes() const { return receive ? receive_blocks * kRxBytes : 0; }
  uint32_t info(unsigned n) const { return receive_block() + receive_bytes() + n * kInfoBytes; }
  uint32_t cyclic_table() const { return info(info_networks); }
  uint32_t input_bytes() const {
    return requests * kMbBytes + receive_bytes() + info_networks * kInfoBytes +
           (cyclic_jobs ? 2 + cyclic_jobs * kJobWords * 2 : 0);
  }
  uint32_t request(unsigned m) const { return out_base + m * kMbBytes; }
  uint32_t ack() const { return out_base + requests * kMbBytes; }
  uint32_t keepalive(unsigned j) const { return ack() + (receive ? kRxAckBytes : 0) + j * 2; }
  uint32_t output_bytes() const { return requests * kMbBytes + (receive ? kRxAckBytes : 0) + cyclic_jobs * 2; }
};

// One request as the backend gets it; data already taken from the request or
// the staging buffer.
struct MbCall {
  uint8_t op = 0;
  uint8_t network = 0;
  uint16_t a[kMbArgs] = {};
  std::vector<uint8_t> data;
};
struct MbAnswer {
  uint8_t error = 0;
  uint16_t r[kMbArgs] = {};
  std::vector<uint8_t> data;  // the result; the response shows its first 128 bytes
};
// A running operation.
class MbJob {
 public:
  virtual ~MbJob() = default;
  // True once it ended, with `out` its result.
  virtual bool poll(MbAnswer& out) = 0;
  // The link stopped or the network restarted: end now.
  virtual void cancel() {}
};

struct RxSpec {
  uint8_t kind = 0;
  uint8_t network = 0;
  uint8_t flags = 0;
  uint16_t depth = 0;
  uint32_t id = 0;    // CAN identifier, J1939 PGN
  uint32_t mask = 0;  // CAN mask, J1939 source, EMCY node
};
struct RxRecord {
  uint8_t flags = 0;  // kRecRestart, kRecOverflow (kRecLong is set by the mailbox)
  uint16_t queued = 0;
  uint32_t dropped = 0;
  uint64_t time_us = 0;
  // CAN
  uint32_t id = 0;
  uint8_t can_flags = 0;
  uint8_t dlc = 0;
  // J1939
  uint32_t pgn = 0;
  uint8_t source = 0, destination = 0, priority = 0;
  // EMCY
  uint8_t node = 0, error_register = 0;
  uint16_t error_code = 0;
  std::vector<uint8_t> data;  // CAN: up to 8, J1939: the message, EMCY: 5 bytes
};

struct NetInfo {
  uint8_t can_state = 4;
  uint8_t bus_load = 0;
  uint16_t tx_errors = 0, rx_errors = 0;
  uint32_t bus_off_count = 0, rx_count = 0, tx_count = 0, error_frames = 0;
  bool j1939 = false;
  uint8_t j1939_state = 3;
  uint8_t address = 254;
  uint64_t name = 0;
  uint16_t ecu_count = 0;
  uint8_t j1939_error = 10;  // without a J1939 view: why
};

struct CyclicFrame {
  uint32_t id = 0;
  uint8_t flags = 0;  // CAN extended 0x01
  uint8_t dlc = 0;
  uint8_t data[8] = {};
  uint32_t period_ms = 0;
};

class MailboxBackend {
 public:
  virtual ~MailboxBackend() = default;
  // Starts SDO_READ, SDO_WRITE, CAN_SEND, J1939_SEND, J1939_REQUEST,
  // DM_READ, DM_CLEAR or FIND_ECU. Null: it ended at once with `now`.
  virtual std::unique_ptr<MbJob> start(const MbCall& call, MbAnswer& now) = 0;
  // Receivers: a handle, or 0 with `error` (the family's ERROR_ID).
  virtual uint32_t rx_open(const RxSpec& spec, uint8_t& error) = 0;
  // 1 a record, 0 none waiting, -1 the receiver ended (`error`).
  virtual int rx_read(uint32_t handle, RxRecord& rec, uint8_t& error) = 0;
  virtual void rx_close(uint32_t handle) = 0;
  // Cyclic jobs: a handle, or 0 with `error`.
  virtual uint32_t cyc_start(uint8_t network, const CyclicFrame& f, uint8_t& error) = 0;
  // New data and period (when `f` is given) and the frames sent; false when
  // the job ended (`error`). A running job may report an error (bus-off)
  // and stay.
  virtual bool cyc_update(uint32_t handle, const CyclicFrame* f, uint32_t& count, uint8_t& error) = 0;
  virtual void cyc_stop(uint32_t handle) = 0;
  // False: no such network.
  virtual bool net_info(unsigned network, NetInfo& out) = 0;
  // Whether network `network` exists.
  virtual bool has_network(unsigned network) const = 0;
};

class Mailboxes {
 public:
  using Clock = std::chrono::steady_clock;

  Mailboxes(const MailboxLayout& layout, MailboxBackend& backend);
  ~Mailboxes();

  const MailboxLayout& layout() const { return layout_; }

  // One loop round: `out` the newest output image (requests, acknowledgement,
  // keepalives) or null while no client has written yet, `in` the input
  // image to fill (responses, receive mailbox, info, cyclic table).
  void service(const uint8_t* out, uint8_t* in, Clock::time_point now);
  // The link stopped or mismatched, or the watchdog fired: every running
  // operation ends cancelled, every job stops, every receiver closes.
  // Returns how many it ended.
  unsigned end_all(const char* why);
  // A network restarted: the same for that network's.
  unsigned end_network(unsigned network);

  // Diagnostics.
  unsigned open_receivers() const;
  unsigned active_jobs() const;

 private:
  struct Request;
  struct Receiver;
  struct Job;

  void serve_request(unsigned m, const uint8_t* req, Clock::time_point now);
  void run(Request& r, const MbCall& call, Clock::time_point now);
  void finish(Request& r, uint8_t error, const MbAnswer* a);
  void encode_response(const Request& r, uint8_t* block) const;
  void rx_open(Request& r, const MbCall& call);
  void rx_close(unsigned slot);
  void rx_fetch(Request& r, const MbCall& call);
  void cyclic_set(Request& r, const MbCall& call, Clock::time_point now);
  void cyclic_stop(Request& r, const MbCall& call);
  void serve_receive(const uint8_t* out, Clock::time_point now);
  void build_batch();
  void encode_receive(uint8_t* block) const;
  void serve_jobs(const uint8_t* out, Clock::time_point now);
  void encode_jobs(uint8_t* block) const;
  void encode_info(uint8_t* in);
  uint16_t tick(Clock::time_point now) const;

  MailboxLayout layout_;
  MailboxBackend& backend_;
  Clock::time_point started_;
  uint16_t tick_ = 0;
  std::vector<std::unique_ptr<Request>> requests_;
  std::vector<std::unique_ptr<Receiver>> receivers_;  // kMaxReceivers slots
  std::vector<std::unique_ptr<Job>> jobs_;             // layout_.cyclic_jobs slots
  uint8_t next_gen_ = 1;
  // Receive mailbox.
  uint16_t batch_seq_ = 0;
  uint32_t batch_present_ = 0;
  std::vector<uint16_t> batch_words_;
  uint64_t batch_time_ = 0;  // the first record's receive time
  bool batch_acked_ = true;
  Clock::time_point batch_shown_{};
  uint32_t last_pending_ = 0;
  uint32_t stalled_ = 0;  // receivers the last stall closed (for the log)
  std::vector<uint16_t> keepalive_seen_;
  unsigned forgotten_ = 0;  // jobs stopped for a missing keepalive
  unsigned info_count_ = 0;

 public:
  // Receivers closed by the last stall since the previous call, and jobs
  // stopped for a missing keepalive (the host logs them).
  uint32_t take_stalled() {
    uint32_t s = stalled_;
    stalled_ = 0;
    return s;
  }
  unsigned take_forgotten() {
    unsigned f = forgotten_;
    forgotten_ = 0;
    return f;
  }
};

// The words of a record, for tests and the batch.
void encode_record(uint8_t receiver, uint8_t kind, const RxRecord& rec, bool long_record,
                   std::vector<uint16_t>& out);
unsigned record_words(uint8_t kind);

}  // namespace canworks_bridge

#endif  // CANWORKS_BRIDGE_MAILBOXES_H
