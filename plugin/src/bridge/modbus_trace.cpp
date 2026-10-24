// modbus_trace.cpp - see modbus_trace.h.

#include "modbus_trace.h"

#include <netinet/in.h>

#include <algorithm>
#include <cstring>

namespace canworks_bridge {

namespace {

constexpr size_t kMaxKinds = 4096;  // per connection; a scanning client starts over

uint64_t fnv(const uint8_t* p, size_t n, uint64_t h = 1469598103934665603ull) {
  for (size_t i = 0; i < n; ++i) {
    h ^= p[i];
    h *= 1099511628211ull;
  }
  return h;
}

void put16(std::string& s, size_t at, uint16_t v) {
  s[at] = static_cast<char>(v & 0xFF);
  s[at + 1] = static_cast<char>(v >> 8);
}
void put32(std::string& s, size_t at, uint32_t v) {
  for (int i = 0; i < 4; ++i) s[at + i] = static_cast<char>((v >> (8 * i)) & 0xFF);
}
void put64(std::string& s, size_t at, uint64_t v) {
  for (int i = 0; i < 8; ++i) s[at + i] = static_cast<char>((v >> (8 * i)) & 0xFF);
}

uint16_t be16(const uint8_t* p) { return static_cast<uint16_t>(p[0] << 8 | p[1]); }

// Zeroes the registers of `ignored` in the `n` bytes of register data at `p`
// that start at register `start`.
void blank(uint8_t* p, size_t n, unsigned start, const std::vector<uint16_t>& ignored) {
  if (ignored.empty()) return;
  for (size_t k = 0; k + 1 < n; k += 2)
    if (std::binary_search(ignored.begin(), ignored.end(), static_cast<uint16_t>(start + k / 2))) p[k] = p[k + 1] = 0;
}

}  // namespace

void ModbusTrace::set_ignored(std::vector<uint16_t> holding, std::vector<uint16_t> input) {
  std::sort(holding.begin(), holding.end());
  std::sort(input.begin(), input.end());
  std::lock_guard<std::mutex> lock(mu_);
  ignored_holding_ = std::move(holding);
  ignored_input_ = std::move(input);
}

constexpr size_t ModbusTrace::kDefaultBytes;
constexpr size_t ModbusTrace::kFetchDefault;
constexpr size_t ModbusTrace::kFetchMax;
constexpr size_t ModbusTrace::kFetchBytes;
constexpr std::chrono::seconds ModbusTrace::kIdleEnd;

void ModbusTrace::record(uint32_t conn, const sockaddr* peer, const std::string& peer_text, uint16_t peer_port,
                         uint16_t transaction, uint8_t unit, const uint8_t* req, size_t req_n, const uint8_t* resp,
                         size_t resp_n, bool refused, uint64_t time_us) {
  if (!active()) return;
  req_n = std::min<size_t>(req_n, 255);
  resp_n = std::min<size_t>(resp_n, 255);
  const uint8_t fn = req_n ? req[0] : 0;
  const bool always = refused || fn == 8 || fn == 43 || (resp_n && (resp[0] & 0x80));
  std::lock_guard<std::mutex> lock(mu_);
  if (sessions_.empty()) return;
  uint32_t skipped = 0;
  if (!always) {
    // The kind: function, start and count (the first 5 bytes; functions 5
    // and 6 have no count, the value follows the address); the data: the
    // rest of the request, the answer and the unit.
    size_t head = std::min<size_t>(req_n, fn == 5 || fn == 6 ? 3 : 5);
    uint64_t key = fnv(req, head);
    // The data without the words the mailboxes change on their own: a
    // request where only they changed counts as unchanged.
    uint8_t q[255], a[255];
    std::memcpy(q, req, req_n);
    std::memcpy(a, resp, resp_n);
    if (req_n >= 5 && resp_n >= 2) {
      const unsigned start = be16(req + 1);
      if (fn == 3 || fn == 4)
        blank(a + 2, std::min<size_t>(resp[1], resp_n - 2), start, fn == 3 ? ignored_holding_ : ignored_input_);
      else if (fn == 6) {  // the answer echoes the request
        blank(q + 3, std::min<size_t>(req_n - 3, 2), start, ignored_holding_);
        blank(a + 3, std::min<size_t>(resp_n - 3, 2), start, ignored_holding_);
      }
      else if (fn == 16 && req_n > 6)
        blank(q + 6, req_n - 6, start, ignored_holding_);
      else if (fn == 23 && req_n > 10) {
        blank(a + 2, std::min<size_t>(resp[1], resp_n - 2), start, ignored_holding_);
        blank(q + 10, req_n - 10, be16(req + 5), ignored_holding_);
      }
    }
    uint64_t h = fnv(q + head, req_n - head, fnv(a, resp_n, fnv(&unit, 1)));
    auto& kinds = kinds_[conn];
    auto it = kinds.find(key);
    if (it != kinds.end() && it->second.hash == h) {
      // The same as the last record of its kind: counted, not kept. Every
      // open session wanting changes only decides it.
      if (changes_only_) {
        ++it->second.skipped;
        return;
      }
    }
    if (it == kinds.end()) {
      if (kinds.size() >= kMaxKinds) kinds.clear();
      it = kinds.emplace(key, Kind{}).first;
    }
    skipped = it->second.skipped;
    it->second.hash = h;
    it->second.skipped = 0;
  }
  size_t alen = std::min<size_t>(peer_text.size(), 63);
  Entry e;
  e.bytes.assign(kModbusTraceHeader + alen + req_n + resp_n, '\0');
  std::memset(&e.addr, 0, sizeof(e.addr));
  if (peer) std::memcpy(&e.addr, peer, peer->sa_family == AF_INET6 ? sizeof(sockaddr_in6) : sizeof(sockaddr_in));
  put64(e.bytes, 0, time_us);
  put64(e.bytes, 8, ++seq_);
  put32(e.bytes, 16, conn);
  put32(e.bytes, 20, skipped);
  put16(e.bytes, 24, transaction);
  e.bytes[26] = static_cast<char>(unit);
  e.bytes[27] = static_cast<char>(refused ? kTraceRefusedWrite : 0);
  put16(e.bytes, 28, peer_port);
  e.bytes[30] = static_cast<char>(alen);
  e.bytes[31] = static_cast<char>(req_n);
  e.bytes[32] = static_cast<char>(resp_n);
  std::memcpy(&e.bytes[kModbusTraceHeader], peer_text.data(), alen);
  if (req_n) std::memcpy(&e.bytes[kModbusTraceHeader + alen], req, req_n);
  if (resp_n) std::memcpy(&e.bytes[kModbusTraceHeader + alen + req_n], resp, resp_n);
  bytes_ += e.bytes.size();
  ring_.push_back(std::move(e));
  while (bytes_ > capacity_ && !ring_.empty()) {
    bytes_ -= ring_.front().bytes.size();
    ring_.pop_front();
  }
}

void ModbusTrace::forget(uint32_t conn) {
  std::lock_guard<std::mutex> lock(mu_);
  kinds_.erase(conn);
}

void ModbusTrace::update_active() {
  bool all = true;
  for (const auto& s : sessions_) all = all && s.second.changes_only;
  changes_only_ = all;
  if (sessions_.empty()) {
    // Nothing is kept for the next trace: its first request of each kind is recorded.
    kinds_.clear();
  }
  active_.store(!sessions_.empty(), std::memory_order_relaxed);
}

uint64_t ModbusTrace::start(uint64_t session, bool changes_only, const AddressList& clients, Clock::time_point now) {
  std::lock_guard<std::mutex> lock(mu_);
  if (sessions_.empty()) kinds_.clear();
  Session& s = sessions_[session];
  s.changes_only = changes_only;
  s.clients = clients;
  s.fetched = now;
  update_active();
  return seq_;
}

bool ModbusTrace::fetch(uint64_t session, uint64_t after, size_t max, Clock::time_point now, Fetch& out) {
  std::lock_guard<std::mutex> lock(mu_);
  auto it = sessions_.find(session);
  if (it == sessions_.end()) return false;
  it->second.fetched = now;
  const AddressList& clients = it->second.clients;
  out = Fetch{};
  uint64_t first = ring_.empty() ? seq_ + 1 : seq_ + 1 - ring_.size();
  if (after + 1 < first) out.lost = first - after - 1;
  uint64_t seq = std::max(after + 1, first);
  out.next = std::max(after, first - 1);
  for (; seq <= seq_; ++seq) {
    const Entry& e = ring_[static_cast<size_t>(seq - first)];
    if (out.count >= max || out.data.size() + e.bytes.size() > kFetchBytes) {
      out.more = true;
      break;
    }
    out.next = seq;
    if (!clients.empty() && !clients.matches(reinterpret_cast<const sockaddr*>(&e.addr))) continue;
    out.data += e.bytes;
    ++out.count;
  }
  return true;
}

bool ModbusTrace::stop(uint64_t session) {
  std::lock_guard<std::mutex> lock(mu_);
  bool had = sessions_.erase(session) > 0;
  update_active();
  return had;
}

size_t ModbusTrace::expire(Clock::time_point now) {
  std::lock_guard<std::mutex> lock(mu_);
  size_t ended = 0;
  for (auto it = sessions_.begin(); it != sessions_.end();) {
    if (now - it->second.fetched > kIdleEnd) {
      it = sessions_.erase(it);
      ++ended;
    } else {
      ++it;
    }
  }
  if (ended) update_active();
  return ended;
}

uint64_t ModbusTrace::last_seq() const {
  std::lock_guard<std::mutex> lock(mu_);
  return seq_;
}

size_t ModbusTrace::sessions() const {
  std::lock_guard<std::mutex> lock(mu_);
  return sessions_.size();
}

std::string base64(const std::string& data) {
  static const char* t = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
  const auto* p = reinterpret_cast<const uint8_t*>(data.data());
  size_t n = data.size();
  std::string out;
  out.reserve((n + 2) / 3 * 4);
  size_t i = 0;
  for (; i + 3 <= n; i += 3) {
    uint32_t v = (uint32_t(p[i]) << 16) | (uint32_t(p[i + 1]) << 8) | p[i + 2];
    out += t[v >> 18];
    out += t[(v >> 12) & 63];
    out += t[(v >> 6) & 63];
    out += t[v & 63];
  }
  if (i < n) {
    uint32_t v = uint32_t(p[i]) << 16;
    if (i + 1 < n) v |= uint32_t(p[i + 1]) << 8;
    out += t[v >> 18];
    out += t[(v >> 12) & 63];
    out += i + 1 < n ? t[(v >> 6) & 63] : '=';
    out += '=';
  }
  return out;
}

}  // namespace canworks_bridge
