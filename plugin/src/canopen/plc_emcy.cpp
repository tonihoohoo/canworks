// plc_emcy.cpp - per-network EMCY queues for the PLC program's CO_RECV_EMCY.

#include "plc_emcy.h"

#include <cstring>

namespace canopen_plugin {

constexpr unsigned EmcyQueues::kNetworks;
constexpr uint32_t EmcyQueues::kDepth;

EmcyQueues& EmcyQueues::instance() {
  static EmcyQueues queues;
  return queues;
}

void EmcyQueues::reset(unsigned network) {
  if (network >= kNetworks) return;
  std::lock_guard<std::mutex> lock(mutex_);
  Ring& r = rings_[network];
  r.session = ++sessions_;
  if (!r.session) r.session = ++sessions_;  // 0 is never a session
  r.next = 1;
}

void EmcyQueues::push(unsigned network, uint8_t node, uint16_t code, uint8_t error_register, const uint8_t msef[5],
                      uint64_t time_us) {
  if (network >= kNetworks) return;
  std::lock_guard<std::mutex> lock(mutex_);
  Ring& r = rings_[network];
  canopen_plc_emcy& e = r.entries[r.next % kDepth];
  e = canopen_plc_emcy{};
  e.time_us = time_us;
  e.seq = r.next;
  e.error_code = code;
  e.node = node;
  e.error_register = error_register;
  if (msef) std::memcpy(e.msef, msef, sizeof e.msef);
  ++r.next;
}

void EmcyQueues::begin(unsigned network, bool skip_old, canopen_plc_emcy_cursor& cursor) {
  std::lock_guard<std::mutex> lock(mutex_);
  const Ring& r = rings_[network];
  cursor.session = r.session;
  cursor.next = skip_old ? r.next : r.oldest();
}

int EmcyQueues::read(unsigned network, uint8_t node, canopen_plc_emcy_cursor& cursor, canopen_plc_emcy& entry,
                     canopen_plc_emcy_info& info) {
  info = canopen_plc_emcy_info{};
  std::lock_guard<std::mutex> lock(mutex_);
  const Ring& r = rings_[network];
  if (cursor.session != r.session) {
    // A new CANopen session: start again at its oldest message, nothing lost.
    cursor.session = r.session;
    cursor.next = r.oldest();
    return -CANOPEN_PLC_ERR_CANCELLED;
  }
  uint32_t oldest = r.oldest();
  if (cursor.next < oldest) {
    // Overwritten before this reader got to them (with a node filter this
    // counts the other nodes' messages too).
    info.lost = oldest - cursor.next;
    cursor.next = oldest;
  }
  if (cursor.next > r.next) cursor.next = r.next;
  int found = 0;
  for (uint32_t s = cursor.next; s < r.next; ++s) {
    const canopen_plc_emcy& e = r.entries[s % kDepth];
    if (node && e.node != node) continue;
    entry = e;
    cursor.next = s + 1;
    found = 1;
    break;
  }
  if (!found) cursor.next = r.next;
  unsigned queued = 0;
  for (uint32_t s = cursor.next; s < r.next; ++s)
    if (!node || r.entries[s % kDepth].node == node) ++queued;
  info.queued = static_cast<uint16_t>(queued);
  return found;
}

}  // namespace canopen_plugin
