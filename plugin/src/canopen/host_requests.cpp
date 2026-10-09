// host_requests.cpp - see host_requests.h.

#include "host_requests.h"

namespace canopen_plugin {

HostRequests& HostRequests::instance() {
  static HostRequests r;
  return r;
}

void HostRequests::nmt(unsigned network, unsigned node, const std::string& command) {
  std::lock_guard<std::mutex> lock(mu_);
  queue_.push_back(HostNmt{network, node, command});
}

void HostRequests::take(unsigned network, std::vector<HostNmt>& out) {
  std::lock_guard<std::mutex> lock(mu_);
  for (auto it = queue_.begin(); it != queue_.end();) {
    if (it->network == network) {
      out.push_back(*it);
      it = queue_.erase(it);
    } else {
      ++it;
    }
  }
}

void HostRequests::set_operational(unsigned network, unsigned node, bool up) {
  if (network >= kMaxNetworks || node > 127) return;
  uint64_t bit = uint64_t(1) << (node % 64);
  std::atomic<uint64_t>& w = up_[network][node / 64];
  if (up)
    w.fetch_or(bit, std::memory_order_acq_rel);
  else
    w.fetch_and(~bit, std::memory_order_acq_rel);
}

void HostRequests::clear(unsigned network) {
  if (network >= kMaxNetworks) return;
  up_[network][0].store(0, std::memory_order_release);
  up_[network][1].store(0, std::memory_order_release);
}

std::bitset<128> HostRequests::operational(unsigned network) const {
  std::bitset<128> b;
  if (network >= kMaxNetworks) return b;
  for (unsigned w = 0; w < 2; ++w) {
    uint64_t v = up_[network][w].load(std::memory_order_acquire);
    for (unsigned i = 0; i < 64; ++i)
      if (v >> i & 1) b[w * 64 + i] = true;
  }
  return b;
}

}  // namespace canopen_plugin
