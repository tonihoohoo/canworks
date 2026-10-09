// gateway.h - what crosses between the bus threads of a gateway
// (canopen-gateway spec): route values, field node states, field EMCYs and
// the upper network's state.
//
// Each network runs on its own bus thread and Lely loop. A route has one
// writer (the loop that receives the value) and one reader (the loop that
// sends it on); the value is a 64-bit atomic with a version counter, and the
// writer wakes the reader's loop through that network's eventfd (fd()).
// Field node states and the upper network's state are atomics; forwarded
// EMCYs go through a short queue under a mutex (bus threads only, never the
// PLC scan).

#ifndef CANOPEN_GATEWAY_H
#define CANOPEN_GATEWAY_H

#include <atomic>
#include <cstdint>
#include <deque>
#include <memory>
#include <mutex>
#include <vector>

#include "config.h"

namespace canopen_plugin {

class GatewayLink {
 public:
  explicit GatewayLink(const ConfigSet& set);
  ~GatewayLink();
  GatewayLink(const GatewayLink&) = delete;
  GatewayLink& operator=(const GatewayLink&) = delete;

  const GatewayConfig& cfg() const { return cfg_; }
  // The eventfd that becomes readable when something for `network` (an index
  // into ConfigSet::networks) arrived; -1 for a network the gateway does not
  // use. The reader drains it.
  int fd(unsigned network) const;
  void wake(unsigned network);

  // ---- routes ----
  // The writer side: a new value (raw bits, zero-extended) for route `r`
  // (index into cfg().routes); wakes the reading network.
  void put(size_t r, uint64_t raw);
  // The reader side: true when route `r` has a value newer than `seen`
  // (updated). Values only ever written once are also reported once.
  bool get(size_t r, uint64_t& raw, uint32_t& seen) const;

  // ---- field networks (written by their loops, read by the upper's) ----
  // The position of a master network among the master networks (status
  // records, the SDO bridge's network sub-object, forwarded EMCYs), or -1.
  int field_position(unsigned network) const;
  // The ConfigSet index of the master network at `position`, or -1.
  int field_network(unsigned position) const;
  void set_node_state(unsigned network, unsigned node, uint8_t state);
  uint8_t node_state(unsigned network, unsigned node) const;
  // Bumped on every node state change.
  uint64_t states_version() const { return states_version_.load(std::memory_order_acquire); }

  struct Emcy {
    unsigned network = 0;  // ConfigSet index
    unsigned node = 0;
    uint16_t code = 0;
    uint8_t er = 0;
  };
  // A field node's EMCY (code 0: its error reset); wakes the upper network.
  void emcy(unsigned network, unsigned node, uint16_t code, uint8_t er);
  void take_emcy(std::vector<Emcy>& out);

  // ---- the upper network (written by its loop, read by the fields') ----
  // OPERATIONAL with no heartbeat consumer or life guarding error; a change
  // wakes every field network.
  void set_upper_ok(bool ok);
  bool upper_ok() const { return upper_ok_.load(std::memory_order_acquire); }

 private:
  struct Slot {
    std::atomic<uint64_t> value{0};
    std::atomic<uint32_t> version{0};
  };
  GatewayConfig cfg_;
  std::vector<int> fds_;  // per ConfigSet network
  std::unique_ptr<Slot[]> slots_;
  std::vector<int> positions_;  // per ConfigSet network: master position or -1
  std::vector<int> by_position_;
  std::unique_ptr<std::atomic<uint8_t>[]> states_;  // network * 128 + node
  std::atomic<uint64_t> states_version_{0};
  std::atomic<bool> upper_ok_{false};
  std::mutex emcy_mutex_;
  std::deque<Emcy> emcys_;
  static constexpr size_t kMaxQueuedEmcy = 256;
};

}  // namespace canopen_plugin

#endif  // CANOPEN_GATEWAY_H
