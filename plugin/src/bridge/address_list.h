// address_list.h - client allowlists (`readers`, `writers`) and the `listen`
// address of the bridge object.

#ifndef CANWORKS_BRIDGE_ADDRESS_LIST_H
#define CANWORKS_BRIDGE_ADDRESS_LIST_H

#include <sys/socket.h>

#include <cstdint>
#include <string>
#include <vector>

namespace canworks_bridge {

// IPv4 and IPv6 addresses or prefixes ("10.0.0.20", "192.168.10.0/24",
// "fd00::/8"). An IPv4 entry also matches the IPv4-mapped IPv6 form.
class AddressList {
 public:
  bool add(const std::string& text, std::string& err);
  bool empty() const { return entries_.empty(); }
  bool matches(const sockaddr* addr) const;

 private:
  struct Entry {
    uint8_t bytes[16];
    unsigned prefix;  // in bits of the 16-byte (IPv6 or mapped IPv4) form
  };
  std::vector<Entry> entries_;
};

// "host:port" or "[v6-host]:port"; host may be "0.0.0.0" or "::".
bool parse_listen(const std::string& text, sockaddr_storage& out, socklen_t& len, std::string& err);

// The client's address as text, for log lines.
std::string address_text(const sockaddr* addr);

}  // namespace canworks_bridge

#endif
