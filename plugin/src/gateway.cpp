#include "gateway.h"

#include <sys/eventfd.h>
#include <unistd.h>

namespace canopen_plugin {

GatewayLink::GatewayLink(const ConfigSet& set)
    : cfg_(set.gateway), fds_(set.networks.size(), -1), slots_(new Slot[set.gateway.routes.size() + 1]),
      positions_(set.networks.size(), -1), states_(new std::atomic<uint8_t>[set.networks.size() * 128]) {
  for (size_t i = 0; i < set.networks.size() * 128; ++i) states_[i].store(0, std::memory_order_relaxed);
  int k = 0;
  for (const auto& c : set.networks) {
    if (c.is_slave()) continue;
    positions_[c.network_index] = k++;
    by_position_.push_back(static_cast<int>(c.network_index));
  }
  if (!cfg_.enabled) return;
  // The upper network and every master network: field networks read routes
  // down and the upper state.
  for (const auto& c : set.networks)
    if (!c.is_slave() || c.network_index == cfg_.upper)
      fds_[c.network_index] = eventfd(0, EFD_NONBLOCK | EFD_CLOEXEC);
}

GatewayLink::~GatewayLink() {
  for (int fd : fds_)
    if (fd >= 0) close(fd);
}

int GatewayLink::fd(unsigned network) const { return network < fds_.size() ? fds_[network] : -1; }

void GatewayLink::wake(unsigned network) {
  int f = fd(network);
  if (f < 0) return;
  uint64_t one = 1;
  ssize_t r = write(f, &one, sizeof(one));
  (void)r;
}

void GatewayLink::put(size_t r, uint64_t raw) {
  if (r >= cfg_.routes.size()) return;
  Slot& s = slots_[r];
  s.value.store(raw, std::memory_order_relaxed);
  s.version.fetch_add(1, std::memory_order_release);
  const RouteConfig& rc = cfg_.routes[r];
  wake(rc.up ? cfg_.upper : rc.field_network);
}

bool GatewayLink::get(size_t r, uint64_t& raw, uint32_t& seen) const {
  if (r >= cfg_.routes.size()) return false;
  const Slot& s = slots_[r];
  // One writer: read the version, the value, and the version again; a
  // change in between means a newer value, which the next wake brings.
  for (int attempt = 0; attempt < 4; ++attempt) {
    uint32_t v1 = s.version.load(std::memory_order_acquire);
    if (v1 == seen) return false;
    uint64_t value = s.value.load(std::memory_order_relaxed);
    std::atomic_thread_fence(std::memory_order_acquire);
    if (s.version.load(std::memory_order_relaxed) == v1) {
      raw = value;
      seen = v1;
      return true;
    }
  }
  return false;
}

int GatewayLink::field_position(unsigned network) const {
  return network < positions_.size() ? positions_[network] : -1;
}

int GatewayLink::field_network(unsigned position) const {
  return position < by_position_.size() ? by_position_[position] : -1;
}

void GatewayLink::set_node_state(unsigned network, unsigned node, uint8_t state) {
  if (network >= fds_.size() || node > 127) return;
  if (states_[network * 128 + node].exchange(state, std::memory_order_acq_rel) == state) return;
  states_version_.fetch_add(1, std::memory_order_acq_rel);
  if (cfg_.enabled && cfg_.has_status) wake(cfg_.upper);
}

uint8_t GatewayLink::node_state(unsigned network, unsigned node) const {
  if (network >= fds_.size() || node > 127) return 0;
  return states_[network * 128 + node].load(std::memory_order_acquire);
}

void GatewayLink::emcy(unsigned network, unsigned node, uint16_t code, uint8_t er) {
  if (!cfg_.enabled || !cfg_.emcy_forward) return;
  {
    std::lock_guard<std::mutex> lock(emcy_mutex_);
    if (emcys_.size() >= kMaxQueuedEmcy) emcys_.pop_front();
    emcys_.push_back({network, node, code, er});
  }
  wake(cfg_.upper);
}

void GatewayLink::take_emcy(std::vector<Emcy>& out) {
  out.clear();
  std::lock_guard<std::mutex> lock(emcy_mutex_);
  out.assign(emcys_.begin(), emcys_.end());
  emcys_.clear();
}

void GatewayLink::set_upper_ok(bool ok) {
  if (upper_ok_.exchange(ok, std::memory_order_acq_rel) == ok) return;
  for (unsigned i = 0; i < fds_.size(); ++i)
    if (i != cfg_.upper) wake(i);
}

}  // namespace canopen_plugin
