#include "process_image.h"

#include <algorithm>
#include <cstring>
#include <sys/eventfd.h>
#include <unistd.h>

namespace canopen_plugin {

// ---------------------------------------------------------------------------
// ProcessImage

ProcessImage::~ProcessImage() {
  if (sync_fd_ >= 0) close(sync_fd_);
}

void ProcessImage::request_sync() {
  if (!sync_cycles_ || ++sync_frames_ < sync_cycles_) return;
  sync_frames_ = 0;
  sync_requests_.fetch_add(1, std::memory_order_acq_rel);
  uint64_t one = 1;
  ssize_t r = write(sync_fd_, &one, sizeof(one));  // EAGAIN only with 2^64-2 unread requests
  (void)r;
}

void ProcessImage::build(const Config& cfg) {
  sync_cycles_ = cfg.master.sync_plc_cycle ? cfg.master.sync_cycles : 0;
  sync_frames_ = 0;
  if (sync_cycles_ && sync_fd_ < 0) sync_fd_ = eventfd(0, EFD_NONBLOCK | EFD_CLOEXEC);
  if (sync_fd_ < 0) sync_cycles_ = 0;
  inputs_.clear();
  outputs_.clear();
  node_ids_.clear();
  node_has_status_.clear();
  node_status_loc_.clear();
  node_has_state_.clear();
  node_state_loc_.clear();
  node_has_boot_error_.clear();
  node_boot_error_loc_.clear();
  node_has_emcy_.clear();
  node_emcy_loc_.clear();
  node_has_errreg_.clear();
  node_errreg_loc_.clear();
  sdo_vars_.clear();
  timeouts_.clear();
  node_has_nmt_.clear();
  node_nmt_loc_.clear();
  for (const auto& n : cfg.nodes) {
    node_ids_.push_back(n.node_id);
    node_has_nmt_.push_back(n.has_nmt_command_location);
    node_nmt_loc_.push_back(n.nmt_command_location);
    for (const auto& sv : n.sdo_variables) sdo_vars_.push_back({n.node_id, sv});
    node_has_status_.push_back(n.has_status_location);
    node_status_loc_.push_back(n.status_location);
    node_has_state_.push_back(n.has_state_location);
    node_state_loc_.push_back(n.state_location);
    node_has_boot_error_.push_back(n.has_boot_error_location);
    node_boot_error_loc_.push_back(n.boot_error_location);
    node_has_emcy_.push_back(n.has_emcy_code_location);
    node_emcy_loc_.push_back(n.emcy_code_location);
    node_has_errreg_.push_back(n.has_error_register_location);
    node_errreg_loc_.push_back(n.error_register_location);
    for (const auto& p : n.tx_pdos) {
      for (const auto& e : p.entries)
        if (e.has_location) inputs_.push_back({n.node_id, e.index, e.subindex, e.type, e.location});
      if (p.has_timeout && p.has_timeout_location) timeouts_.push_back({n.node_id, p.number, p.timeout_location});
    }
    for (const auto& p : n.rx_pdos)
      for (const auto& e : p.entries)
        if (e.has_location) outputs_.push_back({n.node_id, e.index, e.subindex, e.type, e.location});
  }
  const MasterConfig& m = cfg.master;
  bus_has_[0] = m.has_bus_state_location;
  bus_loc_[0] = m.bus_state_location;
  bus_has_[1] = m.has_tx_error_count_location;
  bus_loc_[1] = m.tx_error_count_location;
  bus_has_[2] = m.has_rx_error_count_location;
  bus_loc_[2] = m.rx_error_count_location;
  bus_has_[3] = m.has_bus_off_count_location;
  bus_loc_[3] = m.bus_off_count_location;
  master_has_state_ = m.has_state_location;
  master_state_loc_ = m.state_location;
  bus_slot_ = inputs_.size() + 5 * node_ids_.size();
  sdo_in_slot_ = bus_slot_ + 5;
  timeout_slot_ = sdo_in_slot_ + 3 * sdo_vars_.size();
  in_work_.assign(timeout_slot_ + timeouts_.size(), 0);
  in_.resize(in_work_.size());
  sdo_out_slot_ = outputs_.size();
  nmt_out_slot_ = sdo_out_slot_ + 2 * sdo_vars_.size();
  scan_slot_ = nmt_out_slot_ + 3 * node_ids_.size();
  out_.resize(scan_slot_ + 1);
  trig_prev_.assign(sdo_vars_.size(), 0);
  trig_count_.assign(sdo_vars_.size(), 0);
  nmt_prev_.assign(node_ids_.size(), 0);
  nmt_resets_.assign(node_ids_.size(), 0);
  nmt_reset_code_.assign(node_ids_.size(), 0);
  scans_ = 0;
}

bool ProcessImage::has_nmt_command(unsigned node_id) const {
  int s = node_slot(node_id);
  return s >= 0 && node_has_nmt_[s];
}

bool ProcessImage::nmt_command(const uint64_t* snap, unsigned node_id, uint8_t& level, uint64_t& resets,
                               uint8_t& reset_code) const {
  int s = node_slot(node_id);
  if (s < 0 || !node_has_nmt_[s]) return false;
  level = static_cast<uint8_t>(snap[nmt_out_slot_ + 3 * s]);
  resets = snap[nmt_out_slot_ + 3 * s + 1];
  reset_code = static_cast<uint8_t>(snap[nmt_out_slot_ + 3 * s + 2]);
  return true;
}

int ProcessImage::node_slot(unsigned node_id) const {
  for (size_t i = 0; i < node_ids_.size(); ++i)
    if (node_ids_[i] == node_id) return static_cast<int>(i);
  return -1;
}

void ProcessImage::set_node_status(unsigned node_id, bool up) {
  int s = node_slot(node_id);
  if (s >= 0) in_work_[inputs_.size() + s] = up ? 1 : 0;
}

bool ProcessImage::node_status(unsigned node_id) const {
  int s = node_slot(node_id);
  return s >= 0 && in_work_[inputs_.size() + s] != 0;
}

void ProcessImage::set_node_state(unsigned node_id, uint8_t state) {
  int s = node_slot(node_id);
  if (s >= 0) in_work_[inputs_.size() + node_ids_.size() + s] = state;
}

uint8_t ProcessImage::node_state(unsigned node_id) const {
  int s = node_slot(node_id);
  return s >= 0 ? static_cast<uint8_t>(in_work_[inputs_.size() + node_ids_.size() + s]) : 0;
}

void ProcessImage::set_node_boot_error(unsigned node_id, uint8_t letter) {
  int s = node_slot(node_id);
  if (s >= 0) in_work_[inputs_.size() + 2 * node_ids_.size() + s] = letter;
}

uint8_t ProcessImage::node_boot_error(unsigned node_id) const {
  int s = node_slot(node_id);
  return s >= 0 ? static_cast<uint8_t>(in_work_[inputs_.size() + 2 * node_ids_.size() + s]) : 0;
}

void ProcessImage::set_node_emcy(unsigned node_id, uint16_t code, uint8_t error_register) {
  int s = node_slot(node_id);
  if (s < 0) return;
  in_work_[inputs_.size() + 3 * node_ids_.size() + s] = code;
  in_work_[inputs_.size() + 4 * node_ids_.size() + s] = error_register;
}

uint16_t ProcessImage::node_emcy_code(unsigned node_id) const {
  int s = node_slot(node_id);
  return s >= 0 ? static_cast<uint16_t>(in_work_[inputs_.size() + 3 * node_ids_.size() + s]) : 0;
}

uint8_t ProcessImage::node_error_register(unsigned node_id) const {
  int s = node_slot(node_id);
  return s >= 0 ? static_cast<uint8_t>(in_work_[inputs_.size() + 4 * node_ids_.size() + s]) : 0;
}

void ProcessImage::commit_inputs() {
  std::memcpy(in_.back(), in_work_.data(), in_work_.size() * sizeof(uint64_t));
  in_.publish();
}



void ProcessImage::copy_to_plc(const plugin_runtime_args_t& rt) {
  const uint64_t* snap = in_.latest();
  for (size_t i = 0; i < inputs_.size(); ++i) image_write_input(rt, inputs_[i].location, snap[i]);
  for (size_t s = 0; s < node_ids_.size(); ++s) {
    if (node_has_status_[s]) image_write_input(rt, node_status_loc_[s], snap[inputs_.size() + s]);
    if (node_has_state_[s]) image_write_input(rt, node_state_loc_[s], snap[inputs_.size() + node_ids_.size() + s]);
    if (node_has_boot_error_[s])
      image_write_input(rt, node_boot_error_loc_[s], snap[inputs_.size() + 2 * node_ids_.size() + s]);
    if (node_has_emcy_[s]) image_write_input(rt, node_emcy_loc_[s], snap[inputs_.size() + 3 * node_ids_.size() + s]);
    if (node_has_errreg_[s])
      image_write_input(rt, node_errreg_loc_[s], snap[inputs_.size() + 4 * node_ids_.size() + s]);
  }
  for (size_t k = 0; k < 4; ++k)
    if (bus_has_[k]) image_write_input(rt, bus_loc_[k], snap[bus_slot_ + k]);
  if (master_has_state_) image_write_input(rt, master_state_loc_, snap[bus_slot_ + 4]);
  for (size_t k = 0; k < sdo_vars_.size(); ++k) {
    const SdoVariable& v = sdo_vars_[k].var;
    const uint64_t* slot = snap + sdo_in_slot_ + 3 * k;
    if (v.is_read()) image_write_input(rt, v.location, slot[0]);
    if (v.has_status) image_write_input(rt, v.status_location, slot[1]);
    if (v.has_abort_code) image_write_input(rt, v.abort_code_location, slot[2]);
  }
  for (size_t k = 0; k < timeouts_.size(); ++k) image_write_input(rt, timeouts_[k].location, snap[timeout_slot_ + k]);
}

void ProcessImage::copy_from_plc(const plugin_runtime_args_t& rt) {
  uint64_t* back = out_.back();
  rt.image_lock();
  for (size_t i = 0; i < outputs_.size(); ++i) back[i] = image_read_output(rt, outputs_[i].location);
  for (size_t k = 0; k < sdo_vars_.size(); ++k) {
    const SdoVariable& v = sdo_vars_[k].var;
    uint64_t* slot = back + sdo_out_slot_ + 2 * k;
    if (!v.is_read()) slot[0] = image_read_output(rt, v.location);
    if (v.has_trigger) {
      // A rising edge as R_TRIG sees it: TRUE in the first scan counts.
      uint8_t now = image_read_output(rt, v.trigger_location) ? 1 : 0;
      if (now && !trig_prev_[k]) ++trig_count_[k];
      trig_prev_[k] = now;
      slot[1] = trig_count_[k];
    }
  }
  for (size_t s = 0; s < node_ids_.size(); ++s) {
    if (!node_has_nmt_[s]) continue;
    uint8_t now = static_cast<uint8_t>(image_read_output(rt, node_nmt_loc_[s]));
    if (now != nmt_prev_[s] && (now == 129 || now == 130)) {
      ++nmt_resets_[s];
      nmt_reset_code_[s] = now;
    }
    nmt_prev_[s] = now;
    uint64_t* slot = back + nmt_out_slot_ + 3 * s;
    slot[0] = now;
    slot[1] = nmt_resets_[s];
    slot[2] = nmt_reset_code_[s];
  }
  rt.image_unlock();
  back[scan_slot_] = ++scans_;
  out_.publish();
}

}  // namespace canopen_plugin
