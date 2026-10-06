// process_image.h - binding table between CANopen PDO objects and the PLC I/O
// image, with lock-free triple buffers between the bus thread and the scan.
//
// Inputs:  bus thread -> set_input()/set_node_status() on its private working
//          copy -> commit_inputs() publishes a full snapshot. cycle_start
//          takes the latest snapshot and writes it to %I* through the
//          runtime's lock-free journal.
// Outputs: cycle_end reads %Q* (under the runtime's image lock, as the
//          runtime requires for reads) into a snapshot and publishes it. The
//          bus thread takes the latest snapshot before each SYNC.
//          For SDO variables and NMT command bytes cycle_end also counts
//          rising trigger edges and reset requests in the snapshot, so a
//          pulse that lasts one scan is not lost between two samples.
//
// Neither side ever waits for the other, allocates or logs after build().

#ifndef CANOPEN_PROCESS_IMAGE_H
#define CANOPEN_PROCESS_IMAGE_H

#include <atomic>
#include <cstdint>
#include <vector>

#include "config.h"
#include "plugin_types.h"

namespace canopen_plugin {

// Single-producer/single-consumer triple buffer of fixed-size uint64 arrays.
class TripleBuffer {
 public:
  void resize(size_t n);
  size_t size() const { return size_; }

  // Producer: the buffer to fill, then publish().
  uint64_t* back() { return bufs_[back_].data(); }
  void publish();

  // Consumer: returns the newest published snapshot (or the previous one if
  // nothing new was published). Never blocks.
  const uint64_t* latest(bool* fresh = nullptr);

 private:
  static constexpr uint8_t kDirty = 0x4;
  std::vector<uint64_t> bufs_[3];
  size_t size_ = 0;
  uint8_t back_ = 0;
  uint8_t front_ = 1;
  std::atomic<uint8_t> middle_{2};
};

struct Binding {
  unsigned node_id = 0;
  uint16_t index = 0;
  uint8_t subindex = 0;
  CoType type = CoType::UNSIGNED8;
  IecLocation location;
};

// An SDO variable's place in the image (config order across all nodes).
struct SdoVarSlot {
  unsigned node_id = 0;
  SdoVariable var;
};

class ProcessImage {
 public:
  // Builds the binding tables and preallocates every buffer.
  void build(const Config& cfg);

  const std::vector<Binding>& inputs() const { return inputs_; }
  const std::vector<Binding>& outputs() const { return outputs_; }
  const std::vector<unsigned>& nodes() const { return node_ids_; }
  const std::vector<SdoVarSlot>& sdo_vars() const { return sdo_vars_; }
  // Whether the node has an NMT command byte.
  bool has_nmt_command(unsigned node_id) const;

  // ---- bus thread ----
  // Stores a received value (raw bits, zero-extended) for input binding i.
  void set_input(size_t i, uint64_t raw) { in_work_[i] = raw; }
  // Sets node status (true = operational and exchanging PDOs).
  void set_node_status(unsigned node_id, bool up);
  bool node_status(unsigned node_id) const;
  // Sets the node's NMT state byte (CiA 301 code, 0 = no contact).
  void set_node_state(unsigned node_id, uint8_t state);
  uint8_t node_state(unsigned node_id) const;
  // Sets the node's boot error byte (ASCII CiA 302 error status, 0 = none).
  void set_node_boot_error(unsigned node_id, uint8_t letter);
  uint8_t node_boot_error(unsigned node_id) const;
  // Sets the node's latest EMCY error code and error register.
  void set_node_emcy(unsigned node_id, uint16_t code, uint8_t error_register);
  uint16_t node_emcy_code(unsigned node_id) const;
  uint8_t node_error_register(unsigned node_id) const;
  // Sets the master's own NMT state byte (same codes as a node's).
  void set_master_state(uint8_t state) { in_work_[bus_slot_ + 4] = state; }
  uint8_t master_state() const { return static_cast<uint8_t>(in_work_[bus_slot_ + 4]); }
  // Sets the bus diagnostics (bus_monitor.h); only the slots the config maps
  // reach the PLC.
  void set_bus_state(uint8_t code) { in_work_[bus_slot_ + 0] = code; }
  void set_bus_errors(uint8_t tx, uint8_t rx) {
    in_work_[bus_slot_ + 1] = tx;
    in_work_[bus_slot_ + 2] = rx;
  }
  void set_bus_off_count(uint16_t n) { in_work_[bus_slot_ + 3] = n; }
  uint8_t bus_state() const { return static_cast<uint8_t>(in_work_[bus_slot_]); }
  uint8_t bus_tx_errors() const { return static_cast<uint8_t>(in_work_[bus_slot_ + 1]); }
  uint8_t bus_rx_errors() const { return static_cast<uint8_t>(in_work_[bus_slot_ + 2]); }
  uint16_t bus_off_count() const { return static_cast<uint16_t>(in_work_[bus_slot_ + 3]); }
  // SDO variable k (index into sdo_vars()): the value read (read entries),
  // the transfer status and the abort code.
  void set_sdo_value(size_t k, uint64_t raw) { in_work_[sdo_in_slot_ + 3 * k] = raw; }
  void set_sdo_status(size_t k, uint8_t status) { in_work_[sdo_in_slot_ + 3 * k + 1] = status; }
  void set_sdo_abort(size_t k, uint32_t code) { in_work_[sdo_in_slot_ + 3 * k + 2] = code; }
  uint64_t sdo_value(size_t k) const { return in_work_[sdo_in_slot_ + 3 * k]; }
  uint8_t sdo_status(size_t k) const { return static_cast<uint8_t>(in_work_[sdo_in_slot_ + 3 * k + 1]); }
  uint32_t sdo_abort(size_t k) const { return static_cast<uint32_t>(in_work_[sdo_in_slot_ + 3 * k + 2]); }
  void commit_inputs();
  // Newest output snapshot: one raw value per output binding, then the SDO
  // variable and NMT command slots read through the accessors below.
  const uint64_t* latest_outputs(bool* fresh = nullptr) { return out_.latest(fresh); }
  // In a snapshot: SDO variable k's output value (write entries) and its
  // count of rising trigger edges.
  uint64_t sdo_out_value(const uint64_t* snap, size_t k) const { return snap[sdo_out_slot_ + 2 * k]; }
  uint64_t sdo_trigger_count(const uint64_t* snap, size_t k) const { return snap[sdo_out_slot_ + 2 * k + 1]; }
  // The node's NMT command byte, the number of reset requests (changes to
  // 129 or 130) and the latest of those codes. False if it has no byte.
  bool nmt_command(const uint64_t* snap, unsigned node_id, uint8_t& level, uint64_t& resets,
                   uint8_t& reset_code) const;
  // Scans completed since build(); 0 until the program has run once.
  uint64_t scan_count(const uint64_t* snap) const { return snap[scan_slot_]; }

  // ---- PLC scan (cycle_start / cycle_end) ----
  // Copies the newest inputs and status bits to %I* via the journal.
  void copy_to_plc(const plugin_runtime_args_t& rt);
  // Copies %Q* into a new output snapshot.
  void copy_from_plc(const plugin_runtime_args_t& rt);

 private:
  int node_slot(unsigned node_id) const;

  std::vector<Binding> inputs_;
  std::vector<Binding> outputs_;
  std::vector<unsigned> node_ids_;
  std::vector<bool> node_has_status_;
  std::vector<IecLocation> node_status_loc_;
  std::vector<bool> node_has_state_;
  std::vector<IecLocation> node_state_loc_;
  std::vector<bool> node_has_boot_error_;
  std::vector<IecLocation> node_boot_error_loc_;
  std::vector<bool> node_has_emcy_;
  std::vector<IecLocation> node_emcy_loc_;
  std::vector<bool> node_has_errreg_;
  std::vector<IecLocation> node_errreg_loc_;
  // Bus diagnostics: state, TX errors, RX errors, bus-off count.
  bool bus_has_[4] = {};
  IecLocation bus_loc_[4];
  size_t bus_slot_ = 0;
  bool master_has_state_ = false;
  IecLocation master_state_loc_;
  std::vector<SdoVarSlot> sdo_vars_;
  std::vector<bool> node_has_nmt_;
  std::vector<IecLocation> node_nmt_loc_;
  size_t sdo_in_slot_ = 0;
  size_t sdo_out_slot_ = 0;
  size_t nmt_out_slot_ = 0;
  size_t scan_slot_ = 0;
  // Scan-thread state for edge and change detection (cycle_end only).
  std::vector<uint8_t> trig_prev_;
  std::vector<uint64_t> trig_count_;
  std::vector<uint8_t> nmt_prev_;
  std::vector<uint64_t> nmt_resets_;
  std::vector<uint8_t> nmt_reset_code_;
  uint64_t scans_ = 0;

  // Input snapshot layout: one slot per input binding, then one status slot,
  // one state slot, one boot error slot, one EMCY code slot and one error
  // register slot per node, then four bus diagnostic slots and the master
  // state slot, then value, status and abort code per SDO variable.
  // Output snapshot layout: one slot per output binding, then value and
  // trigger edge count per SDO variable, then NMT byte, reset count and
  // reset code per node, then the scan count.
  std::vector<uint64_t> in_work_;
  TripleBuffer in_;
  TripleBuffer out_;
};

}  // namespace canopen_plugin

#endif  // CANOPEN_PROCESS_IMAGE_H
