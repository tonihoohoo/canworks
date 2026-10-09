// address_list.cpp - see address_list.h.

#include "address_list.h"

#include <arpa/inet.h>
#include <netinet/in.h>

#include <cstdlib>
#include <cstring>

namespace canworks_bridge {

namespace {

// The 16-byte form: IPv6 as is, IPv4 as ::ffff:a.b.c.d.
bool to16(const sockaddr* sa, uint8_t out[16]) {
  if (sa->sa_family == AF_INET6) {
    std::memcpy(out, &reinterpret_cast<const sockaddr_in6*>(sa)->sin6_addr, 16);
    return true;
  }
  if (sa->sa_family == AF_INET) {
    std::memset(out, 0, 10);
    out[10] = out[11] = 0xFF;
    std::memcpy(out + 12, &reinterpret_cast<const sockaddr_in*>(sa)->sin_addr, 4);
    return true;
  }
  return false;
}

}  // namespace

bool AddressList::add(const std::string& text, std::string& err) {
  std::string host = text;
  long bits = -1;
  size_t slash = text.find('/');
  if (slash != std::string::npos) {
    host = text.substr(0, slash);
    std::string p = text.substr(slash + 1);
    char* end = nullptr;
    bits = std::strtol(p.c_str(), &end, 10);
    if (p.empty() || *end) bits = -2;
  }
  Entry e{};
  in_addr v4;
  in6_addr v6;
  unsigned max_bits;
  if (inet_pton(AF_INET, host.c_str(), &v4) == 1) {
    e.bytes[10] = e.bytes[11] = 0xFF;
    std::memcpy(e.bytes + 12, &v4, 4);
    max_bits = 32;
  } else if (inet_pton(AF_INET6, host.c_str(), &v6) == 1) {
    std::memcpy(e.bytes, &v6, 16);
    max_bits = 128;
  } else {
    err = "'" + text + "' is not an IPv4 or IPv6 address or prefix";
    return false;
  }
  if (bits == -1) bits = max_bits;
  if (bits < 0 || bits > static_cast<long>(max_bits)) {
    err = "'" + text + "' has a bad prefix length";
    return false;
  }
  e.prefix = static_cast<unsigned>(bits) + (max_bits == 32 ? 96 : 0);
  entries_.push_back(e);
  return true;
}

bool AddressList::matches(const sockaddr* addr) const {
  uint8_t a[16];
  if (!to16(addr, a)) return false;
  for (const Entry& e : entries_) {
    unsigned full = e.prefix / 8, rest = e.prefix % 8;
    if (std::memcmp(a, e.bytes, full) != 0) continue;
    if (rest) {
      uint8_t mask = static_cast<uint8_t>(0xFF << (8 - rest));
      if ((a[full] & mask) != (e.bytes[full] & mask)) continue;
    }
    return true;
  }
  return false;
}

bool parse_listen(const std::string& text, sockaddr_storage& out, socklen_t& len, std::string& err) {
  std::string host, port;
  if (!text.empty() && text[0] == '[') {
    size_t close = text.find("]:");
    if (close == std::string::npos) {
      err = "listen '" + text + "' must be [address]:port";
      return false;
    }
    host = text.substr(1, close - 1);
    port = text.substr(close + 2);
  } else {
    size_t colon = text.rfind(':');
    if (colon == std::string::npos || text.find(':') != colon) {
      err = "listen '" + text + "' must be address:port";
      return false;
    }
    host = text.substr(0, colon);
    port = text.substr(colon + 1);
  }
  char* end = nullptr;
  long p = std::strtol(port.c_str(), &end, 10);
  if (port.empty() || *end || p < 0 || p > 65535) {
    err = "listen '" + text + "' has a bad port";
    return false;
  }
  std::memset(&out, 0, sizeof(out));
  auto* v4 = reinterpret_cast<sockaddr_in*>(&out);
  auto* v6 = reinterpret_cast<sockaddr_in6*>(&out);
  if (inet_pton(AF_INET, host.c_str(), &v4->sin_addr) == 1) {
    v4->sin_family = AF_INET;
    v4->sin_port = htons(static_cast<uint16_t>(p));
    len = sizeof(sockaddr_in);
    return true;
  }
  if (inet_pton(AF_INET6, host.c_str(), &v6->sin6_addr) == 1) {
    v6->sin6_family = AF_INET6;
    v6->sin6_port = htons(static_cast<uint16_t>(p));
    len = sizeof(sockaddr_in6);
    return true;
  }
  err = "listen '" + text + "' needs a numeric IPv4 or IPv6 address";
  return false;
}

std::string address_text(const sockaddr* addr) {
  char buf[INET6_ADDRSTRLEN] = "?";
  if (addr->sa_family == AF_INET)
    inet_ntop(AF_INET, &reinterpret_cast<const sockaddr_in*>(addr)->sin_addr, buf, sizeof(buf));
  else if (addr->sa_family == AF_INET6)
    inet_ntop(AF_INET6, &reinterpret_cast<const sockaddr_in6*>(addr)->sin6_addr, buf, sizeof(buf));
  return buf;
}

}  // namespace canworks_bridge
