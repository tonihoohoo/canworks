// engine.cpp - see engine.h.

#include "engine.h"

#include <cstring>

#include "../signals.h"

namespace canworks_raw {

namespace {
uint64_t le64(const uint8_t* d) {
  uint64_t v = 0;
  for (unsigned i = 0; i < 8; ++i) v |= static_cast<uint64_t>(d[i]) << (8 * i);
  return v;
}
// Signed signals go to the PLC sign-extended to the location's width, so an
// INT location reads -1 for a 12-bit all-ones value.
uint64_t to_location(uint64_t raw, const RawSignal& s) {
  if (!s.is_signed) return raw;
  return static_cast<uint64_t>(canworks_can::sign_extend(raw, s.length));
}
}  // namespace

RawEngine::RawEngine(const RawConfig& cfg) : cfg_(cfg) {
  for (const RawRx& m : cfg_.rx) {
    RxMap map;
    if (m.status.set) map.status = add_in(m.status.loc);
    if (m.counter.set) map.counter = add_in(m.counter.loc);
    if (m.id_loc.set) map.id = add_in(m.id_loc.loc);
    if (m.dlc_loc.set) map.dlc = add_in(m.dlc_loc.loc);
    if (m.data.set) map.data = add_in(m.data.loc);
    for (const RawSignal& s : m.signals) map.signals.push_back(add_in(s.loc));
    rx_map_.push_back(map);
  }
  for (const RawTx& m : cfg_.tx) {
    TxMap map;
    if (m.trigger.set) map.trigger = add_out(m.trigger.loc);
    if (m.enable.set) map.enable = add_out(m.enable.loc);
    if (m.data.set) {
      map.data = add_out(m.data.loc);
      map.all.push_back(map.data);
    }
    for (const RawSignal& s : m.signals) {
      map.signals.push_back(add_out(s.loc));
      map.all.push_back(map.signals.back());
    }
    tx_map_.push_back(map);
  }
  in_vals_.assign(in_locs_.size(), 0);
  out_vals_.assign(out_locs_.size(), 0);
  rx_.assign(cfg_.rx.size(), RxStatus{});
  tx_.assign(cfg_.tx.size(), TxState{});
  tx_st_.assign(cfg_.tx.size(), TxStatus{});
}

int RawEngine::add_in(const IecLocation& l) {
  in_locs_.push_back(l);
  return static_cast<int>(in_locs_.size() - 1);
}

int RawEngine::add_out(const IecLocation& l) {
  out_locs_.push_back(l);
  return static_cast<int>(out_locs_.size() - 1);
}

bool RawEngine::on_frame(const canworks_can_frame& f, uint64_t now_us) {
  bool ext = (f.flags & CANWORKS_CAN_EXTENDED) != 0;
  bool rtr = (f.flags & CANWORKS_CAN_RTR) != 0;
  bool changed = false;
  for (size_t i = 0; i < cfg_.rx.size(); ++i) {
    const RawRx& m = cfg_.rx[i];
    if (m.extended != ext || m.rtr != rtr) continue;
    if ((f.id & m.mask) != (m.id & m.mask)) continue;
    RxStatus& st = rx_[i];
    if (!rtr && f.dlc < m.need) {
      ++st.short_frames;
      continue;
    }
    const RxMap& map = rx_map_[i];
    auto put = [&](int slot, uint64_t v) {
      if (slot < 0) return;
      if (in_vals_[slot] != v) changed = true;
      in_vals_[slot] = v;
    };
    ++st.count;
    st.seen = true;
    st.timed_out = false;
    st.last_us = now_us;
    st.last = f;
    put(map.status, 1);
    put(map.counter, st.count & 0xFFFFu);
    put(map.id, f.id);
    put(map.dlc, f.dlc);
    uint8_t data[8] = {};
    if (!rtr) std::memcpy(data, f.data, f.dlc > 8 ? 8 : f.dlc);
    put(map.data, le64(data));
    for (size_t k = 0; k < m.signals.size(); ++k) {
      const RawSignal& s = m.signals[k];
      uint64_t raw = canworks_can::unpack_signal(data, f.dlc, s.start_bit, s.length, s.big_endian);
      put(map.signals[k], to_location(raw, s));
    }
  }
  return changed;
}

bool RawEngine::check_timeouts(uint64_t now_us) {
  bool changed = false;
  for (size_t i = 0; i < cfg_.rx.size(); ++i) {
    const RawRx& m = cfg_.rx[i];
    RxStatus& st = rx_[i];
    if (!m.timeout_ms || st.timed_out || !st.seen) continue;
    if (now_us - st.last_us < static_cast<uint64_t>(m.timeout_ms) * 1000u) continue;
    st.timed_out = true;
    int slot = rx_map_[i].status;
    if (slot >= 0 && in_vals_[slot] != 0) {
      in_vals_[slot] = 0;
      changed = true;
    }
  }
  return changed;
}

bool RawEngine::enabled(size_t i) const {
  int slot = tx_map_[i].enable;
  return slot < 0 || out_vals_[slot] != 0;
}

void RawEngine::set_plc_running(bool running, uint64_t now_us) {
  if (running == running_) return;
  running_ = running;
  for (size_t i = 0; i < tx_.size(); ++i) {
    TxState& t = tx_[i];
    t = TxState{};
    if (running) {
      t.next_periodic = now_us;
      // A trigger already TRUE at start is not an edge.
      int slot = tx_map_[i].trigger;
      t.prev_trigger = slot >= 0 && have_outputs_ && out_vals_[slot] != 0;
    }
  }
}

void RawEngine::set_outputs(const uint64_t* values, uint64_t now_us) {
  (void)now_us;
  std::memcpy(out_vals_.data(), values, out_vals_.size() * sizeof(uint64_t));
  bool first = !have_outputs_;
  have_outputs_ = true;
  for (size_t i = 0; i < cfg_.tx.size(); ++i) {
    TxState& t = tx_[i];
    const TxMap& map = tx_map_[i];
    if (map.trigger >= 0) {
      bool now = out_vals_[map.trigger] != 0;
      if (now && !t.prev_trigger && !first && running_) t.trigger_pending = true;
      t.prev_trigger = now;
    }
    if (cfg_.tx[i].on_change && t.has_sent) {
      for (size_t k = 0; k < map.all.size(); ++k)
        if (out_vals_[map.all[k]] != t.sent_values[k]) {
          t.change_pending = true;
          break;
        }
    }
  }
}

canworks_can_frame RawEngine::build(size_t i, const uint64_t* values) const {
  const RawTx& m = cfg_.tx[i];
  const TxMap& map = tx_map_[i];
  canworks_can_frame f{};
  f.id = m.id;
  f.flags = static_cast<uint8_t>((m.extended ? CANWORKS_CAN_EXTENDED : 0) | (m.rtr ? CANWORKS_CAN_RTR : 0));
  f.dlc = static_cast<uint8_t>(m.dlc);
  if (m.rtr) return f;
  std::memset(f.data, m.fill, sizeof f.data);
  if (map.data >= 0) {
    uint64_t v = values[map.data];
    for (unsigned b = 0; b < 8; ++b) f.data[b] = static_cast<uint8_t>(v >> (8 * b));
  }
  for (size_t k = 0; k < m.signals.size(); ++k) {
    const RawSignal& s = m.signals[k];
    canworks_can::pack_signal(f.data, s.start_bit, s.length, s.big_endian, values[map.signals[k]]);
  }
  for (unsigned b = f.dlc; b < 8; ++b) f.data[b] = 0;
  return f;
}

void RawEngine::due(uint64_t now_us, std::vector<canworks_can_frame>& frames, std::vector<size_t>& tx_index) {
  if (!running_ || !have_outputs_) return;
  for (size_t i = 0; i < cfg_.tx.size(); ++i) {
    const RawTx& m = cfg_.tx[i];
    TxState& t = tx_[i];
    bool send = false;
    if (t.trigger_pending) send = true;
    if (enabled(i)) {
      if (m.period_ms && now_us >= t.next_periodic) send = true;
      if (m.on_change && !t.has_sent && !m.period_ms && !m.trigger.set) send = true;  // first value
      if (t.change_pending && now_us - t.last_sent >= static_cast<uint64_t>(m.min_gap_ms) * 1000u) send = true;
    } else {
      t.change_pending = false;
    }
    if (!send) continue;
    frames.push_back(build(i, out_vals_.data()));
    tx_index.push_back(i);
    t.trigger_pending = false;
    t.change_pending = false;
    t.last_sent = now_us;
    t.has_sent = true;
    t.next_periodic = now_us + static_cast<uint64_t>(m.period_ms) * 1000u;
    const TxMap& map = tx_map_[i];
    t.sent_values.resize(map.all.size());
    for (size_t k = 0; k < map.all.size(); ++k) t.sent_values[k] = out_vals_[map.all[k]];
  }
}

void RawEngine::sent(size_t i, uint64_t now_us, int error) {
  (void)now_us;
  if (i >= tx_st_.size()) return;
  if (error) {
    tx_st_[i].last_error = error;
  } else {
    ++tx_st_[i].count;
    tx_st_[i].last_error = 0;
  }
}

uint64_t RawEngine::next_event_in(uint64_t now_us) const {
  uint64_t best = UINT64_MAX;
  auto take = [&](uint64_t at) {
    uint64_t in = at > now_us ? at - now_us : 0;
    if (in < best) best = in;
  };
  if (running_ && have_outputs_) {
    for (size_t i = 0; i < cfg_.tx.size(); ++i) {
      const RawTx& m = cfg_.tx[i];
      const TxState& t = tx_[i];
      if (t.trigger_pending) take(now_us);
      if (!enabled(i)) continue;
      if (m.period_ms) take(t.next_periodic);
      if (t.change_pending) take(t.last_sent + static_cast<uint64_t>(m.min_gap_ms) * 1000u);
    }
  }
  for (size_t i = 0; i < cfg_.rx.size(); ++i) {
    const RxStatus& st = rx_[i];
    if (cfg_.rx[i].timeout_ms && st.seen && !st.timed_out)
      take(st.last_us + static_cast<uint64_t>(cfg_.rx[i].timeout_ms) * 1000u);
  }
  return best;
}

}  // namespace canworks_raw
