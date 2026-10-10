// engine.h - config-mapped raw messages at run time (spec can-raw-messages):
// matches received frames to `rx` entries and keeps their PLC input values,
// supervises timeouts, and decides when each `tx` entry is sent from the PLC
// output values. It owns no socket and no thread: the network's raw I/O path
// feeds it frames and the time, and moves values to and from the process
// image in the order of input_locations() / output_locations().

#ifndef CANWORKS_RAW_ENGINE_H
#define CANWORKS_RAW_ENGINE_H

#include <cstdint>
#include <deque>
#include <utility>
#include <vector>

#include "../can_plc_api.h"
#include "config.h"

namespace canworks_raw {

class RawEngine {
 public:
  explicit RawEngine(const RawConfig& cfg);

  // --- Inputs (to the PLC) ---
  const std::vector<IecLocation>& input_locations() const { return in_locs_; }
  const std::vector<uint64_t>& input_values() const { return in_vals_; }
  // A frame from the bus (also one this plugin sent: config messages may
  // receive frames the program sends). True when an input value changed.
  bool on_frame(const canworks_can_frame& f, uint64_t now_us);
  // Status bits of entries whose timeout passed go FALSE. True on a change.
  bool check_timeouts(uint64_t now_us);

  // --- Outputs (from the PLC) ---
  const std::vector<IecLocation>& output_locations() const { return out_locs_; }
  // The PLC runs (sending allowed) or not. Starting sends periodic entries
  // at once.
  void set_plc_running(bool running, uint64_t now_us);
  // The latest output values, in output_locations() order.
  void set_outputs(const uint64_t* values, uint64_t now_us);
  // Appends the frames due now; `tx_index` gets each frame's entry. Report
  // each with sent() before the next due().
  void due(uint64_t now_us, std::vector<canworks_can_frame>& frames, std::vector<size_t>& tx_index);
  // Records that an entry's frame was written (or failed with errno). Only a
  // written frame counts as sent: after a failure an on-change or trigger
  // send stays pending, and a periodic one waits for its next period.
  void sent(size_t tx_index, uint64_t now_us, int error);
  // Microseconds until the next send or timeout (UINT64_MAX: nothing).
  uint64_t next_event_in(uint64_t now_us) const;

  // Status for diagnostics.
  struct RxStatus {
    uint32_t count = 0;
    uint32_t short_frames = 0;
    uint32_t unknown_pages = 0;  // multiplexed frames whose switch selects no page
    bool seen = false;
    bool timed_out = false;
    uint64_t last_us = 0;
    canworks_can_frame last{};
  };
  struct TxStatus {
    uint32_t count = 0;
    int last_error = 0;
    bool unknown_page = false;  // pages "program": the switches select no page
  };
  const std::vector<RxStatus>& rx_status() const { return rx_; }
  const std::vector<TxStatus>& tx_status() const { return tx_st_; }
  const RawConfig& config() const { return cfg_; }

  // The frame an entry sends with the given output values (for tests and
  // the trace's "would send"). For pages "all" and "rotate", `page` picks the
  // page (index into pages()); with pages "program" it is ignored and the
  // switch outputs pick it.
  canworks_can_frame build(size_t tx_index, const uint64_t* values, size_t page = 0) const;
  // The pages of a send entry with pages "all" or "rotate" (empty otherwise).
  const std::vector<canworks_can::MuxLayout::Page>& pages(size_t tx_index) const { return tx_pages_[tx_index]; }

 private:
  struct RxMap {
    int status = -1, counter = -1, id = -1, dlc = -1, data = -1;
    std::vector<int> signals;
    std::vector<int> valid;  // valid bit per signal, -1: none
  };
  // Per received signal: when it was last in a frame (valid bits).
  struct SigState {
    bool seen = false;
    bool timed_out = false;
    uint64_t last_us = 0;
  };
  struct TxMap {
    int trigger = -1, enable = -1, data = -1;
    std::vector<int> signals;  // -1: a switch the plugin sets
    std::vector<int> all;      // every output slot of the entry (change detection)
    std::vector<std::vector<size_t>> page_all;  // per page: the indices into `all` it sends
  };
  struct TxState {
    bool started = false;
    uint64_t last_sent = 0;
    uint64_t next_periodic = 0;
    bool change_pending = false;
    bool trigger_pending = false;
    bool prev_trigger = false;
    std::vector<uint64_t> sent_values;
    bool has_sent = false;
    // Frames due() gave and sent() has not reported yet: the page (-1: not
    // paged) and the output values they carry.
    std::deque<std::pair<int, std::vector<uint64_t>>> inflight;
    // Pages "all" and "rotate".
    std::vector<std::vector<uint64_t>> page_sent;  // per page: the `all` values last sent
    std::vector<uint8_t> page_has_sent, page_pending, page_retry;
    size_t cursor = 0;  // rotate: the next page
  };
  int add_in(const IecLocation& l);
  int add_out(const IecLocation& l);
  bool enabled(size_t i) const;
  bool paged(size_t i) const { return !tx_pages_[i].empty(); }
  void reset_tx(size_t i, uint64_t now_us);
  void due_paged(size_t i, uint64_t now_us, std::vector<canworks_can_frame>& frames, std::vector<size_t>& tx_index);
  void push(size_t i, int page, std::vector<canworks_can_frame>& frames, std::vector<size_t>& tx_index);

  RawConfig cfg_;
  std::vector<IecLocation> in_locs_, out_locs_;
  std::vector<uint64_t> in_vals_, out_vals_;
  std::vector<RxMap> rx_map_;
  std::vector<TxMap> tx_map_;
  std::vector<RxStatus> rx_;
  std::vector<std::vector<SigState>> rx_sig_;
  std::vector<std::vector<uint8_t>> rx_active_;  // scratch per entry
  std::vector<TxState> tx_;
  std::vector<std::vector<canworks_can::MuxLayout::Page>> tx_pages_;
  mutable std::vector<uint64_t> sw_values_;  // scratch for build()
  mutable std::vector<uint8_t> sw_active_;
  mutable bool built_unknown_ = false;
  std::vector<TxStatus> tx_st_;
  bool running_ = false;
  bool have_outputs_ = false;
};

}  // namespace canworks_raw

#endif  // CANWORKS_RAW_ENGINE_H
