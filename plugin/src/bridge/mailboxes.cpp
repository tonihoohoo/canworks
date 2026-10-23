// mailboxes.cpp - see mailboxes.h.

#include "mailboxes.h"

#include <algorithm>
#include <cstring>

#include "byte_image.h"

namespace canworks_bridge {

namespace {

constexpr auto kStall = std::chrono::milliseconds(1000);
constexpr auto kStallFetching = std::chrono::milliseconds(5000);
constexpr auto kKeepalive = std::chrono::milliseconds(1000);

uint16_t word(const uint8_t* block, unsigned w) { return get_be16(block + 2 * w); }
void set_word(uint8_t* block, unsigned w, uint16_t v) { put_be16(block + 2 * w, v); }

// Data bytes of a request or response: byte 2k is the high byte of word 8 + k.
void copy_data_in(const uint8_t* block, size_t n, std::vector<uint8_t>& out) {
  out.assign(block + 16, block + 16 + std::min<size_t>(n, kMbChunk));
}

}  // namespace

uint8_t family_of(uint8_t op) {
  switch (op) {
    case kOpSdoRead:
    case kOpSdoWrite: return kFamilySdo;
    case kOpJ1939Send:
    case kOpJ1939Request:
    case kOpDmRead:
    case kOpDmClear:
    case kOpFindEcu: return kFamilyJ1939;
    default: return kFamilyCan;
  }
}
uint8_t err_input(Family f) { return f == kFamilySdo ? 6 : 3; }
uint8_t err_network(Family f) { return f == kFamilySdo ? 6 : 2; }
uint8_t err_cancelled(Family) { return 8; }
uint8_t err_full(Family f) { return f == kFamilySdo ? 5 : f == kFamilyJ1939 ? 9 : 5; }

unsigned record_words(uint8_t kind) {
  switch (kind) {
    case kRxCan: return 10;
    case kRxJ1939: return 12;
    case kRxEmcy: return 12;
    default: return 7;
  }
}

void encode_record(uint8_t receiver, uint8_t kind, const RxRecord& rec, bool long_record,
                   std::vector<uint16_t>& out) {
  uint8_t flags = rec.flags & (kRecRestart | kRecOverflow);
  if (long_record) flags |= kRecLong;
  out.push_back(static_cast<uint16_t>(receiver << 8 | (kind & 0x0F) << 4 | flags));
  out.push_back(rec.queued);
  out.push_back(static_cast<uint16_t>(rec.dropped));
  auto bytes = [&](size_t from, size_t n) {
    for (size_t i = 0; i < n; i += 2) {
      uint8_t hi = from + i < rec.data.size() ? rec.data[from + i] : 0;
      uint8_t lo = from + i + 1 < rec.data.size() ? rec.data[from + i + 1] : 0;
      out.push_back(static_cast<uint16_t>(hi << 8 | lo));
    }
  };
  switch (kind) {
    case kRxCan:
      out.push_back(static_cast<uint16_t>(rec.id >> 16));
      out.push_back(static_cast<uint16_t>(rec.id));
      out.push_back(static_cast<uint16_t>(rec.can_flags << 8 | rec.dlc));
      bytes(0, 8);
      break;
    case kRxJ1939:
      out.push_back(static_cast<uint16_t>(rec.pgn >> 16));
      out.push_back(static_cast<uint16_t>(rec.pgn));
      out.push_back(static_cast<uint16_t>(rec.source << 8 | rec.destination));
      out.push_back(rec.priority);
      out.push_back(static_cast<uint16_t>(rec.data.size()));
      bytes(0, 8);
      break;
    case kRxEmcy:
      for (int s = 48; s >= 0; s -= 16) out.push_back(static_cast<uint16_t>(rec.time_us >> s));
      out.push_back(static_cast<uint16_t>(rec.node << 8 | rec.error_register));
      out.push_back(rec.error_code);
      bytes(0, 6);
      break;
    default: break;
  }
}

// ---- state ----

struct Mailboxes::Request {
  bool busy = false;
  uint16_t counter = 0;  // the last request taken
  bool known = false;    // a request word was seen since the start
  uint8_t op = 0;
  uint8_t state = kMbIdle;
  uint8_t error = 0;
  uint16_t r[kMbArgs] = {};
  std::vector<uint8_t> result;   // the whole result
  std::vector<uint8_t> shown;    // what the response shows
  std::vector<uint8_t> staging;  // STAGE bytes
  size_t staged = 0;             // bytes staged (highest end written)
  std::unique_ptr<MbJob> job;
  uint8_t network = 0;
  uint8_t fetching_rx = 0xFF;  // RX_FETCH of this receiver in progress
};

struct Mailboxes::Receiver {
  uint32_t handle = 0;
  uint8_t gen = 0;
  RxSpec spec;
  bool stashed = false;  // `next` holds the oldest record not yet shown
  RxRecord next;
  std::vector<uint8_t> held;  // the long J1939 message of the current batch
  bool fetching = false;      // an RX_FETCH ran since the batch was shown
};

struct Mailboxes::Job {
  uint32_t handle = 0;
  uint8_t gen = 0;
  uint8_t network = 0;
  uint8_t state = 0;  // 0 free, 1 active, 2 error
  uint8_t error = 0;
  uint32_t count = 0;
  uint16_t keepalive = 0;
  Clock::time_point kept;
};

Mailboxes::Mailboxes(const MailboxLayout& layout, MailboxBackend& backend)
    : layout_(layout), backend_(backend), started_(Clock::now()) {
  // A batch sequence of an earlier run must not be taken as acknowledged:
  // start somewhere else each run.
  batch_seq_ = static_cast<uint16_t>(started_.time_since_epoch().count() >> 10);
  for (unsigned m = 0; m < layout_.requests; ++m) requests_.emplace_back(new Request);
  if (layout_.receive)
    for (unsigned i = 0; i < kMaxReceivers; ++i) receivers_.emplace_back(new Receiver);
  for (unsigned j = 0; j < layout_.cyclic_jobs; ++j) jobs_.emplace_back(new Job);
}

Mailboxes::~Mailboxes() { end_all(nullptr); }

uint16_t Mailboxes::tick(Clock::time_point now) const {
  return static_cast<uint16_t>(std::chrono::duration_cast<std::chrono::milliseconds>(now - started_).count());
}

void Mailboxes::service(const uint8_t* out, uint8_t* in, Clock::time_point now) {
  tick_ = tick(now);
  if (out) {
    for (unsigned m = 0; m < layout_.requests; ++m) serve_request(m, out + layout_.request(m), now);
    if (layout_.receive) serve_receive(out, now);
    serve_jobs(out, now);
  } else {
    for (unsigned m = 0; m < layout_.requests; ++m)
      if (requests_[m]->busy) serve_request(m, nullptr, now);
    serve_jobs(nullptr, now);
  }
  for (unsigned m = 0; m < layout_.requests; ++m) encode_response(*requests_[m], in + layout_.response(m));
  if (layout_.receive) encode_receive(in + layout_.receive_block());
  encode_info(in);
  if (layout_.cyclic_jobs) encode_jobs(in + layout_.cyclic_table());
}

// ---- request mailboxes ----

void Mailboxes::serve_request(unsigned m, const uint8_t* req, Clock::time_point now) {
  Request& r = *requests_[m];
  if (r.busy) {
    MbAnswer a;
    if (r.job && r.job->poll(a)) {
      r.job.reset();
      finish(r, a.error, &a);
    }
    return;
  }
  if (!req) return;
  uint16_t counter = word(req, 0);
  // The first request words after a start may be an earlier run's: their
  // counter becomes the baseline and they are not run, so a bridge restart
  // never repeats a send or an SDO write. A request really meant now ends
  // with ERROR_ID 8 (cancelled).
  if (!r.known) {
    r.known = true;
    r.counter = counter;
    if (req[2] != kOpNone) {
      ++operations_;
      finish(r, err_cancelled(kFamilyCan), nullptr);
    }
    return;
  }
  if (counter == r.counter) return;
  r.counter = counter;
  MbCall call;
  call.op = req[2];
  call.network = req[3];
  for (unsigned i = 0; i < kMbArgs; ++i) call.a[i] = word(req, 2 + i);
  copy_data_in(req, kMbChunk, call.data);
  r.op = call.op;
  r.network = call.network;
  r.error = 0;
  std::fill(std::begin(r.r), std::end(r.r), 0);
  if (call.op != kOpFetch && call.op != kOpRxFetch) r.shown.clear();
  if (call.op == kOpNone) {
    r.state = kMbIdle;
    return;
  }
  ++operations_;
  // STAGE: bytes into the staging buffer.
  if (call.op == kOpStage) {
    unsigned offset = call.a[0], length = call.a[1];
    if (length > kMbChunk || offset + length > kMbBuffer) {
      finish(r, err_input(kFamilyCan), nullptr);
      return;
    }
    if (r.staging.size() < offset + length) r.staging.resize(offset + length, 0);
    std::memcpy(r.staging.data() + offset, req + 16, length);
    r.staged = std::max(r.staged, size_t(offset) + length);
    finish(r, 0, nullptr);
    return;
  }
  // FETCH: the next part of the result.
  if (call.op == kOpFetch) {
    size_t offset = call.a[0];
    if (offset > r.result.size()) {
      finish(r, err_input(kFamilyCan), nullptr);
      return;
    }
    size_t n = std::min<size_t>(kMbChunk, r.result.size() - offset);
    r.shown.assign(r.result.begin() + offset, r.result.begin() + offset + n);
    r.r[0] = static_cast<uint16_t>(r.result.size());
    r.state = kMbDone;
    r.error = 0;
    return;
  }
  // Every other operation clears the result; the staged bytes stay for the
  // writes that use them, then go.
  r.result.clear();
  run(r, call, now);
}

void Mailboxes::run(Request& r, const MbCall& in_call, Clock::time_point now) {
  MbCall call = in_call;
  Family fam = static_cast<Family>(family_of(call.op));
  switch (call.op) {
    case kOpRxOpen: rx_open(r, call); break;
    case kOpRxClose: {
      unsigned slot = call.a[0];
      if (!layout_.receive || slot >= receivers_.size()) {
        finish(r, err_input(fam), nullptr);
        break;
      }
      rx_close(slot);
      finish(r, 0, nullptr);
      break;
    }
    case kOpRxFetch: rx_fetch(r, call); break;
    case kOpCyclicSet: cyclic_set(r, call, now); break;
    case kOpCyclicStop: cyclic_stop(r, call); break;
    case kOpSdoRead:
    case kOpSdoWrite:
    case kOpCanSend:
    case kOpJ1939Send:
    case kOpJ1939Request:
    case kOpDmRead:
    case kOpDmClear:
    case kOpFindEcu: {
      if (!backend_.has_network(call.network)) {
        finish(r, err_network(fam), nullptr);
        break;
      }
      // The data: inline up to 128 bytes, else the staging buffer.
      size_t length = 0;
      if (call.op == kOpSdoWrite) length = call.a[4];
      if (call.op == kOpJ1939Send) length = call.a[3];
      if (call.op == kOpCanSend) length = 8;
      if (call.op == kOpFindEcu) length = 16;
      if (length > kMbChunk) {
        if (r.staged < length) {
          finish(r, err_input(fam), nullptr);
          break;
        }
        call.data.assign(r.staging.begin(), r.staging.begin() + length);
      } else {
        call.data.resize(length, 0);
      }
      r.staging.clear();
      r.staged = 0;
      MbAnswer a;
      std::unique_ptr<MbJob> job = backend_.start(call, a);
      if (!job) {
        finish(r, a.error, &a);
        break;
      }
      r.job = std::move(job);
      r.busy = true;
      r.state = kMbBusy;
      break;
    }
    default: finish(r, err_input(fam), nullptr); break;
  }
}

void Mailboxes::finish(Request& r, uint8_t error, const MbAnswer* a) {
  r.busy = false;
  r.state = error ? kMbError : kMbDone;
  r.error = error;
  if (a) {
    std::copy(std::begin(a->r), std::end(a->r), std::begin(r.r));
    r.result = a->data;
    if (r.result.size() > kMbBuffer) r.result.resize(kMbBuffer);
    r.shown.assign(r.result.begin(), r.result.begin() + std::min<size_t>(kMbChunk, r.result.size()));
  }
}

void Mailboxes::encode_response(const Request& r, uint8_t* block) const {
  std::memset(block, 0, kMbBytes);
  set_word(block, 0, r.counter);
  block[2] = r.state;
  block[3] = r.error;
  for (unsigned i = 0; i < kMbArgs; ++i) set_word(block, 2 + i, r.r[i]);
  if (!r.shown.empty()) std::memcpy(block + 16, r.shown.data(), std::min<size_t>(r.shown.size(), kMbChunk));
}

// ---- receivers ----

void Mailboxes::rx_open(Request& r, const MbCall& call) {
  uint8_t kind = call.a[0] >> 8;
  Family fam = kind == kRxJ1939 ? kFamilyJ1939 : kind == kRxEmcy ? kFamilySdo : kFamilyCan;
  if (!layout_.receive) {
    finish(r, err_input(fam), nullptr);
    return;
  }
  if (kind < kRxCan || kind > kRxEmcy) {
    finish(r, err_input(fam), nullptr);
    return;
  }
  if (!backend_.has_network(call.network)) {
    finish(r, kind == kRxEmcy ? 6 : err_network(fam), nullptr);
    return;
  }
  unsigned slot = kMaxReceivers;
  for (unsigned i = 0; i < receivers_.size(); ++i)
    if (!receivers_[i]->handle) {
      slot = i;
      break;
    }
  if (slot == kMaxReceivers) {
    finish(r, kind == kRxJ1939 ? 9 : 5, nullptr);
    return;
  }
  RxSpec s;
  s.kind = kind;
  s.network = call.network;
  s.flags = static_cast<uint8_t>(call.a[0]);
  s.depth = call.a[1];
  s.id = uint32_t(call.a[2]) << 16 | call.a[3];
  s.mask = uint32_t(call.a[4]) << 16 | call.a[5];
  uint8_t error = 0;
  uint32_t h = backend_.rx_open(s, error);
  if (!h) {
    finish(r, error ? error : err_full(fam), nullptr);
    return;
  }
  ++receivers_opened_;
  Receiver& rx = *receivers_[slot];
  rx = Receiver();
  rx.handle = h;
  rx.spec = s;
  rx.gen = next_gen_;
  next_gen_ = static_cast<uint8_t>(next_gen_ == 255 ? 1 : next_gen_ + 1);
  MbAnswer a;
  a.r[0] = static_cast<uint16_t>(slot);
  a.r[1] = rx.gen;
  a.r[2] = tick_;
  finish(r, 0, &a);
}

void Mailboxes::rx_close(unsigned slot) {
  Receiver& rx = *receivers_[slot];
  if (!rx.handle) return;
  backend_.rx_close(rx.handle);
  rx = Receiver();
  batch_present_ &= ~(1u << slot);
}

void Mailboxes::rx_fetch(Request& r, const MbCall& call) {
  unsigned slot = call.a[0];
  size_t offset = call.a[1];
  if (!layout_.receive || slot >= receivers_.size() || !receivers_[slot]->handle) {
    finish(r, 8, nullptr);
    return;
  }
  Receiver& rx = *receivers_[slot];
  if (offset > rx.held.size()) {
    finish(r, 3, nullptr);
    return;
  }
  rx.fetching = true;
  MbAnswer a;
  a.r[0] = static_cast<uint16_t>(rx.held.size());
  // The rest from `offset` becomes the result: its first 128 bytes show, FETCH gives the others.
  a.data.assign(rx.held.begin() + offset, rx.held.end());
  finish(r, 0, &a);
}

void Mailboxes::serve_receive(const uint8_t* out, Clock::time_point now) {
  const uint8_t* ack = out + layout_.ack();
  uint16_t seen = word(ack, 0);
  uint32_t pending = uint32_t(word(ack, 1)) << 16 | word(ack, 2);
  if (batch_seq_ && !batch_acked_) {
    if (seen == batch_seq_) {
      last_pending_ = pending & batch_present_;
      if (!last_pending_) batch_acked_ = true;
    }
    if (!batch_acked_) {
      bool fetching = false;
      for (unsigned i = 0; i < receivers_.size(); ++i)
        if ((last_pending_ ? last_pending_ : batch_present_) >> i & 1u && receivers_[i]->fetching) fetching = true;
      if (now - batch_shown_ >= (fetching ? kStallFetching : kStall)) {
        uint32_t stalled = seen == batch_seq_ ? last_pending_ : batch_present_;
        for (unsigned i = 0; i < receivers_.size(); ++i)
          if (stalled >> i & 1u) rx_close(i);
        batch_acked_ = true;
        stalled_ = stalled;
      }
    }
  }
  // Records from the receivers: read what waits into the stash.
  for (unsigned i = 0; i < receivers_.size(); ++i) {
    Receiver& rx = *receivers_[i];
    if (!rx.handle || rx.stashed) continue;
    uint8_t error = 0;
    int rc = backend_.rx_read(rx.handle, rx.next, error);
    if (rc > 0) {
      rx.stashed = true;
    } else if (rc < 0) {
      // The receiver ended (network restart): its block sees the closed
      // generation and opens a new one.
      rx_close(i);
    }
  }
  if (batch_acked_) build_batch();
}

void Mailboxes::build_batch() {
  bool any = false;
  for (const auto& rx : receivers_)
    if (rx->handle && rx->stashed) any = true;
  if (!any) return;
  for (auto& rx : receivers_) {
    rx->held.clear();
    rx->fetching = false;
  }
  std::vector<uint16_t> words;
  uint32_t present = 0, long_taken = 0;
  uint64_t first_time = 0;
  const size_t room = layout_.receive_bytes() / 2 - kRxHeaderWords;
  for (;;) {
    // The oldest stashed record of the receivers that may still add one.
    int pick = -1;
    for (unsigned i = 0; i < receivers_.size(); ++i) {
      const Receiver& rx = *receivers_[i];
      if (!rx.handle || !rx.stashed || (long_taken >> i & 1u)) continue;
      if (pick < 0 || rx.next.time_us < receivers_[pick]->next.time_us) pick = static_cast<int>(i);
    }
    if (pick < 0) break;
    Receiver& rx = *receivers_[pick];
    if (words.size() + record_words(rx.spec.kind) > room) break;
    bool is_long = rx.spec.kind == kRxJ1939 && rx.next.data.size() > 8;
    if (!present) first_time = rx.next.time_us;
    encode_record(static_cast<uint8_t>(pick), rx.spec.kind, rx.next, is_long, words);
    present |= 1u << pick;
    if (is_long) {
      rx.held = rx.next.data;
      long_taken |= 1u << pick;
    }
    rx.stashed = false;
    uint8_t error = 0;
    int rc = backend_.rx_read(rx.handle, rx.next, error);
    if (rc > 0) rx.stashed = true;
  }
  if (!present) return;
  batch_seq_ = static_cast<uint16_t>(batch_seq_ == 0xFFFF ? 1 : batch_seq_ + 1);
  batch_present_ = present;
  batch_words_ = words;
  batch_time_ = first_time;
  batch_acked_ = false;
  last_pending_ = present;
  batch_shown_ = Clock::now();
}

void Mailboxes::encode_receive(uint8_t* block) const {
  const unsigned words = layout_.receive_bytes() / 2;
  std::memset(block, 0, words * 2);
  set_word(block, 0, batch_seq_);
  set_word(block, 1, static_cast<uint16_t>(batch_present_ >> 16));
  set_word(block, 2, static_cast<uint16_t>(batch_present_));
  set_word(block, 3, static_cast<uint16_t>(batch_words_.size()));
  set_word(block, 4, tick_);
  for (unsigned i = 0; i < receivers_.size(); ++i) block[10 + i] = receivers_[i]->handle ? receivers_[i]->gen : 0;
  for (unsigned k = 0; k < 4; ++k) set_word(block, 21 + k, static_cast<uint16_t>(batch_time_ >> (48 - 16 * k)));
  for (size_t k = 0; k < batch_words_.size() && kRxHeaderWords + k < words; ++k)
    set_word(block, kRxHeaderWords + static_cast<unsigned>(k), batch_words_[k]);
}

// ---- cyclic jobs ----

namespace {
CyclicFrame frame_of(const MbCall& c) {
  CyclicFrame f;
  f.id = uint32_t(c.a[1]) << 16 | c.a[2];
  f.flags = c.a[3] >> 8;
  f.dlc = static_cast<uint8_t>(c.a[3]);
  f.period_ms = c.a[4];
  for (unsigned i = 0; i < 8 && i < c.data.size(); ++i) f.data[i] = c.data[i];
  return f;
}
}  // namespace

void Mailboxes::cyclic_set(Request& r, const MbCall& in_call, Clock::time_point now) {
  const MbCall& call = in_call;
  if (jobs_.empty()) {
    finish(r, 5, nullptr);
    return;
  }
  if (!backend_.has_network(call.network)) {
    finish(r, 2, nullptr);
    return;
  }
  CyclicFrame f = frame_of(call);
  if (f.period_ms < 1 || f.period_ms > 60000 || f.dlc > 8) {
    finish(r, 3, nullptr);
    return;
  }
  uint16_t want = call.a[0];
  MbAnswer a;
  if (want != 0xFFFF) {
    if (want >= jobs_.size() || !jobs_[want]->handle || jobs_[want]->network != call.network) {
      finish(r, 8, nullptr);
      return;
    }
    Job& j = *jobs_[want];
    uint8_t error = 0;
    if (!backend_.cyc_update(j.handle, &f, j.count, error)) {
      j = Job();
      finish(r, error ? error : 8, nullptr);
      return;
    }
    a.r[0] = want;
    a.r[1] = j.gen;
    a.r[2] = tick_;
    finish(r, 0, &a);
    return;
  }
  unsigned slot = static_cast<unsigned>(jobs_.size());
  for (unsigned i = 0; i < jobs_.size(); ++i)
    if (!jobs_[i]->handle) {
      slot = i;
      break;
    }
  if (slot == jobs_.size()) {
    finish(r, 5, nullptr);
    return;
  }
  uint8_t error = 0;
  uint32_t h = backend_.cyc_start(call.network, f, error);
  if (!h) {
    finish(r, error ? error : 5, nullptr);
    return;
  }
  Job& j = *jobs_[slot];
  j = Job();
  j.handle = h;
  j.network = call.network;
  j.state = 1;
  j.gen = next_gen_;
  next_gen_ = static_cast<uint8_t>(next_gen_ == 255 ? 1 : next_gen_ + 1);
  j.kept = now;
  j.keepalive = keepalive_seen_.size() > slot ? keepalive_seen_[slot] : 0;
  a.r[0] = static_cast<uint16_t>(slot);
  a.r[1] = j.gen;
  a.r[2] = tick_;
  finish(r, 0, &a);
}

void Mailboxes::cyclic_stop(Request& r, const MbCall& call) {
  unsigned slot = call.a[0];
  if (slot < jobs_.size() && jobs_[slot]->handle) {
    backend_.cyc_stop(jobs_[slot]->handle);
    *jobs_[slot] = Job();
  }
  finish(r, 0, nullptr);
}

void Mailboxes::serve_jobs(const uint8_t* out, Clock::time_point now) {
  if (keepalive_seen_.size() != jobs_.size()) keepalive_seen_.assign(jobs_.size(), 0);
  for (unsigned i = 0; i < jobs_.size(); ++i) {
    Job& j = *jobs_[i];
    uint16_t k = out ? word(out + layout_.keepalive(i), 0) : keepalive_seen_[i];
    keepalive_seen_[i] = k;
    if (!j.handle) continue;
    if (k != j.keepalive) {
      j.keepalive = k;
      j.kept = now;
    } else if (now - j.kept >= kKeepalive) {
      backend_.cyc_stop(j.handle);
      j = Job();
      ++forgotten_;
      continue;
    }
    uint8_t error = 0;
    if (!backend_.cyc_update(j.handle, nullptr, j.count, error)) {
      // Ended by the engine (network restart): the slot frees; its block
      // sees the generation change.
      j = Job();
      continue;
    }
    j.error = error;
    j.state = error ? 2 : 1;
  }
}

void Mailboxes::encode_jobs(uint8_t* block) const {
  std::memset(block, 0, 2 + jobs_.size() * kJobWords * 2);
  set_word(block, 0, tick_);
  for (unsigned i = 0; i < jobs_.size(); ++i) {
    const Job& j = *jobs_[i];
    uint8_t* p = block + 2 + i * kJobWords * 2;
    p[0] = j.handle ? j.state : 0;
    p[1] = j.handle ? j.error : 0;
    set_word(p, 1, j.handle ? j.gen : 0);
    set_word(p, 2, static_cast<uint16_t>(j.count >> 16));
    set_word(p, 3, static_cast<uint16_t>(j.count));
  }
}

// ---- network info ----

void Mailboxes::encode_info(uint8_t* in) {
  if (!layout_.info_networks) return;
  ++info_count_;
  for (unsigned n = 0; n < layout_.info_networks; ++n) {
    uint8_t* p = in + layout_.info(n);
    std::memset(p, 0, kInfoBytes);
    NetInfo info;
    if (!backend_.net_info(n, info)) continue;
    p[0] = info.can_state;
    p[1] = info.bus_load;
    set_word(p, 1, info.tx_errors);
    set_word(p, 2, info.rx_errors);
    put_be32(p + 6, info.bus_off_count);
    put_be32(p + 10, info.rx_count);
    put_be32(p + 14, info.tx_count);
    put_be32(p + 18, info.error_frames);
    p[22] = info.j1939 ? info.j1939_state : 0xFF;
    p[23] = info.j1939 ? info.address : info.j1939_error;
    for (unsigned w = 0; w < 4; ++w) set_word(p, 12 + w, static_cast<uint16_t>(info.name >> (48 - 16 * w)));
    set_word(p, 16, info.ecu_count);
    set_word(p, 17, static_cast<uint16_t>(info_count_));
  }
}

// ---- ending everything ----

unsigned Mailboxes::end_all(const char*) {
  unsigned n = 0;
  for (auto& r : requests_) {
    if (r->busy) {
      if (r->job) r->job->cancel();
      r->job.reset();
      finish(*r, 8, nullptr);
      ++n;
    }
    r->staging.clear();
    r->staged = 0;
  }
  for (unsigned i = 0; i < receivers_.size(); ++i)
    if (receivers_[i]->handle) {
      rx_close(i);
      ++n;
    }
  for (auto& j : jobs_)
    if (j->handle) {
      backend_.cyc_stop(j->handle);
      *j = Job();
      ++n;
    }
  batch_words_.clear();
  batch_time_ = 0;
  batch_present_ = 0;
  batch_acked_ = true;
  last_pending_ = 0;
  return n;
}

unsigned Mailboxes::end_network(unsigned network) {
  unsigned n = 0;
  for (auto& r : requests_)
    if (r->busy && r->network == network) {
      if (r->job) r->job->cancel();
      r->job.reset();
      finish(*r, 8, nullptr);
      ++n;
    }
  for (unsigned i = 0; i < receivers_.size(); ++i)
    if (receivers_[i]->handle && receivers_[i]->spec.network == network) {
      rx_close(i);
      ++n;
    }
  for (auto& j : jobs_)
    if (j->handle && j->network == network) {
      backend_.cyc_stop(j->handle);
      *j = Job();
      ++n;
    }
  return n;
}

unsigned Mailboxes::open_receivers() const {
  unsigned n = 0;
  for (const auto& r : receivers_) n += r->handle ? 1 : 0;
  return n;
}

unsigned Mailboxes::active_jobs() const {
  unsigned n = 0;
  for (const auto& j : jobs_) n += j->handle ? 1 : 0;
  return n;
}

}  // namespace canworks_bridge
