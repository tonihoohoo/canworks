#include "plc_slave.h"

#include <algorithm>
#include <cstring>

#include <lely/co/dev.hpp>
#include <lely/co/emcy.hpp>
#include <lely/co/nmt.hpp>
#include <lely/co/obj.hpp>
#include <lely/co/val.hpp>
#include <lely/coapp/sdo_error.hpp>

#include "cJSON.h"
#include "log.h"
#include "plc_api.h"
#include "slave_state.h"

#if !defined(__BYTE_ORDER__) || __BYTE_ORDER__ != __ORDER_LITTLE_ENDIAN__
#error "the slave's raw values assume a little-endian host"
#endif

namespace canopen_plugin {

constexpr std::chrono::milliseconds PlcSlave::kPeriod;
constexpr std::chrono::milliseconds PlcSlave::kTick;

namespace {

constexpr uint8_t kStateOperational = 5;
constexpr uint32_t kAbortNoTransfer = 0x08000020u;   // data cannot be transferred or stored
constexpr uint32_t kAbortDeviceState = 0x08000022u;  // ... because of the present device state
constexpr uint32_t kAbortTimeout = 0x05040000u;
constexpr uint32_t kAbortGeneral = 0x08000000u;

co_dev_t* D(__co_dev* d) { return reinterpret_cast<co_dev_t*>(d); }
co_nmt_t* N(__co_nmt* n) { return reinterpret_cast<co_nmt_t*>(n); }

unsigned type_bytes(CoType t) {
  unsigned bits = co_type_bits(t);
  return bits < 8 ? 1 : bits / 8;
}

// The object's value as raw bits (zero-extended), 0 if it is missing.
uint64_t read_raw(co_dev_t* dev, uint16_t index, uint8_t subindex, CoType type) {
  const co_sub_t* sub = co_dev_find_sub(dev, index, subindex);
  if (!sub) return 0;
  const void* p = co_sub_get_val(sub);
  if (!p) return 0;
  uint64_t raw = 0;
  std::memcpy(&raw, p, type_bytes(type));
  if (type == CoType::BOOLEAN) raw = raw ? 1 : 0;
  return raw;
}

const char* state_name(uint8_t st) {
  switch (st) {
    case 0: return "BOOT-UP";
    case 4: return "STOPPED";
    case 5: return "OPERATIONAL";
    case 127: return "PRE-OPERATIONAL";
    default: return "UNKNOWN";
  }
}

}  // namespace

// ---------------------------------------------------------------------------
// SlaveImage

void SlaveImage::build(const Config& cfg) {
  cfg_ = &cfg.slave;
  in_objs_.clear();
  out_objs_.clear();
  for (size_t i = 0; i < cfg.slave.objects.size(); ++i) (cfg.slave.objects[i].input ? in_objs_ : out_objs_).push_back(i);
  status_slot_ = in_objs_.size();
  in_work_.assign(status_slot_ + 3, 0);
  in_.resize(in_work_.size());
  out_.resize(out_objs_.size() + 3);
  scans_ = 0;
}

void SlaveImage::commit_inputs() {
  std::memcpy(in_.back(), in_work_.data(), in_work_.size() * sizeof(uint64_t));
  in_.publish();
}

void SlaveImage::copy_to_plc(const plugin_runtime_args_t& rt) {
  const uint64_t* snap = in_.latest();
  const SlaveConfig& s = *cfg_;
  for (size_t k = 0; k < in_objs_.size(); ++k) image_write_input(rt, s.objects[in_objs_[k]].location, snap[k]);
  if (s.has_state_location) image_write_input(rt, s.state_location, snap[status_slot_]);
  if (s.has_comm_ok_location) image_write_input(rt, s.comm_ok_location, snap[status_slot_ + 1]);
  if (s.has_sync_count_location) image_write_input(rt, s.sync_count_location, snap[status_slot_ + 2]);
}

void SlaveImage::copy_from_plc(const plugin_runtime_args_t& rt) {
  uint64_t* back = out_.back();
  const SlaveConfig& s = *cfg_;
  rt.image_lock();
  for (size_t k = 0; k < out_objs_.size(); ++k) back[k] = image_read_output(rt, s.objects[out_objs_[k]].location);
  size_t n = out_objs_.size();
  back[n] = s.has_emcy_code_location ? image_read_output(rt, s.emcy_code_location) : 0;
  back[n + 1] = s.has_error_register_location ? image_read_output(rt, s.error_register_location) : 0;
  rt.image_unlock();
  back[n + 2] = ++scans_;
  out_.publish();
}

// ---------------------------------------------------------------------------
// PlcSlave

PlcSlave::PlcSlave(ev_exec_t* exec, lely::io::TimerBase& timer, lely::io::TimerBase& loop_timer,
                   lely::io::CanChannelBase& chan, const Config& cfg, SlaveImage& image,
                   std::shared_ptr<SlaveStore> store, std::string state_path, GatewayLink* gw,
                   std::function<bool()> tick)
    : SlaveDevice(exec, timer, chan, cfg.slave.eds_path,
                  cfg.slave.lss ? (store && store->lss_id ? store->lss_id : 0xFF) : static_cast<uint8_t>(cfg.slave.node_id),
                  store),
      cfg_(cfg),
      image_(image),
      loop_timer_(loop_timer),
      loop_wait_(exec, [this](int, std::error_code ec) {
        if (ec || stopped_) return;
        Period();
        if (!stopped_) loop_timer_.submit_wait(loop_wait_);
      }),
      state_path_(std::move(state_path)),
      gw_(gw && gw->cfg().enabled && gw->cfg().upper == cfg.network_index ? gw : nullptr),
      tick_(std::move(tick)) {
  last_out_.assign(image_.output_objects().size(), 0);
  last_in_.assign(image_.input_objects().size(), 0);
  on_log = [](const std::string& line) { log_info("%s", line.c_str()); };
  on_stored = [this] {
    std::string why;
    if (save_slave_state(state_path_, cfg_.slave.eds_sha256, node_id(), this->store(), why))
      log_info("stored parameters written to %s", state_path_.c_str());
    else
      log_error("%s; the stored parameters are lost at the next PLC start", why.c_str());
  };
  if (gw_) {
    const auto& routes = gw_->cfg().routes;
    route_seen_.assign(routes.size(), 0);
    route_last_.assign(routes.size(), 0);
    route_have_.assign(routes.size(), false);
    const GatewayConfig& g = gw_->cfg();
    if (g.sdo_bridge) {
      uint16_t b = g.sdo_bridge_index;
      BasicSlave::OnWrite<uint8_t>(b, 7, [this](uint16_t, uint8_t, uint8_t& v, uint8_t) -> std::error_code {
        uint32_t code = BridgeCommand(v);
        if (code) return static_cast<lely::canopen::SdoErrc>(code);
        return {};
      });
    }
  }
}

PlcSlave::~PlcSlave() {
  loop_timer_.cancel_wait(loop_wait_);
  if (bridge_.busy) {
    canopen_plc_result res;
    PlcRequests::instance().poll(bridge_.handle, &res, nullptr, 0);
  }
}

void PlcSlave::Start() {
  if (cfg_.slave.lss && node_id() == 0xFF)
    log_info("waiting for a node ID from an LSS master (node_id is null)");
  Reset();
  GuardNodeId([this] {
    log_error("another device on %s uses node ID %u (boot-up, heartbeat, EMCY or SDO answer seen); two devices "
              "with one node ID break the network",
              cfg_.adapter.interface.c_str(), node_id());
  });
  loop_timer_.settime(kPeriod, kPeriod);
  loop_timer_.submit_wait(loop_wait_);
}

void PlcSlave::Stop() {
  if (stopped_) return;
  stopped_ = true;
  loop_timer_.cancel_wait(loop_wait_);
}

void PlcSlave::MarkDown() {
  image_.set_state(0);
  image_.set_comm_ok(false);
  if (cfg_.slave.inputs_on_loss_zero)
    for (size_t k = 0; k < image_.input_objects().size(); ++k) image_.set_input(k, 0);
  image_.commit_inputs();
  if (gw_) gw_->set_upper_ok(false);
}

void PlcSlave::OnCommand(lely::canopen::NmtCommand cs) noexcept {
  SlaveDevice::OnCommand(cs);
  if (cs == lely::canopen::NmtCommand::RESET_NODE || cs == lely::canopen::NmtCommand::RESET_COMM) {
    hb_error_ = false;
    lg_error_ = false;
  }
}

void PlcSlave::OnRestored() {
  // The reset brought back the EDS (and stored) values: the PLC's outputs
  // and the routes' values go in again, and the program's EMCY is new.
  restored_ = true;
  errors_.clear();
  emcy_code_ = 0;
  emcy_er_ = 0;
  if (gw_) {
    for (size_t r = 0; r < route_have_.size(); ++r)
      if (gw_->cfg().routes[r].up && route_have_[r]) {
        const RouteConfig& rc = gw_->cfg().routes[r];
        SetObject(rc.slave_index, rc.slave_subindex, route_last_[r], rc.type, false);
      }
    states_seen_ = ~0ull;
  }
}

void PlcSlave::OnRpdoWrite(uint8_t, uint16_t, uint8_t) noexcept {
  ReadInputs();
  ReadRoutesDown();
}

void PlcSlave::OnSync(uint8_t, const time_point&) noexcept { ++sync_count_; }

void PlcSlave::OnHeartbeat(uint8_t id, bool occurred) noexcept {
  hb_error_ = occurred;
  hb_master_ = id;
  if (occurred)
    log_error("lost the heartbeat of node %u (the master); communication is not OK, error behaviour per 0x1029", id);
  else
    log_info("heartbeat of node %u (the master) is back", id);
}

void PlcSlave::OnLifeGuarding(bool occurred) noexcept {
  lg_error_ = occurred;
  if (occurred)
    log_error("life guarding error: the master stopped guarding this node; communication is not OK");
  else
    log_info("life guarding resolved");
}

void PlcSlave::SetObject(uint16_t index, uint8_t subindex, uint64_t raw, CoType type, bool event) {
  co_sub_t* sub = co_dev_find_sub(D(dev()), index, subindex);
  if (!sub) return;
  uint64_t v = type == CoType::BOOLEAN ? (raw ? 1 : 0) : raw;
  co_sub_set_val(sub, &v, type_bytes(type));
  if (event) Changed(index, subindex);
}

void PlcSlave::Period() {
  ++periods_;
  bool fresh = false;
  const uint64_t* snap = image_.latest_outputs(&fresh);
  if (fresh || restored_) {
    WriteOutputs(snap);
    if (image_.scan_count(snap)) SendProgramEmcy(snap);
  }
  restored_ = false;
  ReadInputs();
  ReadRoutesDown();
  UpdateStatus();
  if (periods_ % 10 == 0) {
    ServiceBridge();
    ServiceDiag();
  }
  if (periods_ % 100 == 0) {
    if (gw_) ServiceGateway();  // in case a wake was missed
    if (tick_ && !tick_()) Stop();
  }
}

void PlcSlave::WriteOutputs(const uint64_t* snap) {
  const auto& outs = image_.output_objects();
  for (size_t k = 0; k < outs.size(); ++k) {
    if (!restored_ && snap[k] == last_out_[k]) continue;
    const SlaveObject& o = cfg_.slave.objects[outs[k]];
    last_out_[k] = snap[k];
    SetObject(o.index, o.subindex, snap[k], o.type, true);
  }
}

void PlcSlave::SendProgramEmcy(const uint64_t* snap) {
  if (!cfg_.slave.has_emcy_code_location) return;
  uint16_t code = image_.emcy_code(snap);
  uint8_t er = image_.error_register(snap);
  if (code == emcy_code_ && (code == 0 || er == emcy_er_)) return;
  emcy_code_ = code;
  emcy_er_ = er;
  if (code) {
    uint8_t msef[5] = {0, 0, 0, 0, 0};
    PushError(0, code, er, msef);
    log_info("EMCY 0x%04X, error register 0x%02X (from the program)", code, er);
  } else {
    RemoveError(0);
    log_info("EMCY error reset (from the program)");
  }
}

void PlcSlave::PushError(uint32_t key, uint16_t code, uint8_t er, const uint8_t msef[5]) {
  co_emcy_t* emcy = co_nmt_get_emcy(N(nmt()));
  if (!emcy) return;
  auto it = std::find_if(errors_.begin(), errors_.end(), [key](const ActiveError& e) { return e.key == key; });
  if (it != errors_.end()) {
    co_emcy_remove(emcy, static_cast<size_t>(it - errors_.begin()));
    errors_.erase(it);
  }
  if (co_emcy_push(emcy, code, er, msef) == 0) errors_.insert(errors_.begin(), {key, code, er});
}

void PlcSlave::RemoveError(uint32_t key) {
  co_emcy_t* emcy = co_nmt_get_emcy(N(nmt()));
  auto it = std::find_if(errors_.begin(), errors_.end(), [key](const ActiveError& e) { return e.key == key; });
  if (!emcy || it == errors_.end()) return;
  co_emcy_remove(emcy, static_cast<size_t>(it - errors_.begin()));
  errors_.erase(it);
}

void PlcSlave::ReadInputs() {
  const auto& ins = image_.input_objects();
  if (ins.empty()) return;
  bool loss = cfg_.slave.inputs_on_loss_zero && !image_.comm_ok();
  bool changed = false;
  if (loss) {
    if (!zeroed_) {
      for (size_t k = 0; k < ins.size(); ++k) image_.set_input(k, 0);
      zeroed_ = true;
      changed = true;
    }
  } else {
    co_dev_t* d = D(dev());
    for (size_t k = 0; k < ins.size(); ++k) {
      const SlaveObject& o = cfg_.slave.objects[ins[k]];
      uint64_t v = read_raw(d, o.index, o.subindex, o.type);
      if (zeroed_ || v != last_in_[k]) {
        last_in_[k] = v;
        image_.set_input(k, v);
        changed = true;
      }
    }
    zeroed_ = false;
  }
  if (changed) image_.commit_inputs();
}

void PlcSlave::UpdateStatus() {
  uint8_t st = nmt_state();
  bool comm = st == kStateOperational && !hb_error_ && !lg_error_;
  bool changed = false;
  if (st != last_state_) {
    if (last_state_ != 0xFF || st != 0) log_info("NMT state %s (node ID %u)", state_name(st), node_id());
    // Event-driven TPDOs go out once on entering OPERATIONAL, so the master
    // has every value without waiting for its next change.
    if (st == kStateOperational) {
      ever_started_ = true;
      TpdoEvent(0);
    }
    last_state_ = st;
    image_.set_state(st);
    changed = true;
  }
  if (comm != last_comm_) {
    last_comm_ = comm;
    image_.set_comm_ok(comm);
    changed = true;
    if (gw_) {
      gw_->set_upper_ok(comm);
      if (!comm && ever_started_) {
        const char* what = gw_->cfg().on_upper_loss == GatewayConfig::UpperLoss::Zero
                               ? "routed field outputs go to 0"
                               : gw_->cfg().on_upper_loss == GatewayConfig::UpperLoss::StopNodes
                                     ? "field nodes that receive routes are stopped"
                                     : "routed field outputs hold their values";
        log_warn("gateway: the upper master is lost (%s); %s", st != kStateOperational ? "not OPERATIONAL" :
                 hb_error_ ? "no heartbeat" : "life guarding error", what);
      } else if (comm) {
        log_info("gateway: the upper master started this node; routes run");
      }
    }
  }
  if (cfg_.slave.has_sync_count_location) {
    image_.set_sync_count(sync_count_);
    changed = true;
  }
  if (changed) image_.commit_inputs();
}

// ---------------------------------------------------------------------------
// Gateway

void PlcSlave::ReadRoutesDown() {
  if (!gw_) return;
  co_dev_t* d = D(dev());
  const auto& routes = gw_->cfg().routes;
  for (size_t r = 0; r < routes.size(); ++r) {
    const RouteConfig& rc = routes[r];
    if (rc.up) continue;
    uint64_t v = read_raw(d, rc.slave_index, rc.slave_subindex, rc.type);
    if (route_have_[r] && v == route_last_[r]) continue;
    route_have_[r] = true;
    route_last_[r] = v;
    gw_->put(r, v);
  }
}

void PlcSlave::ServiceGateway() {
  if (!gw_ || stopped_) return;
  const auto& routes = gw_->cfg().routes;
  for (size_t r = 0; r < routes.size(); ++r) {
    const RouteConfig& rc = routes[r];
    if (!rc.up) continue;
    uint64_t v;
    if (!gw_->get(r, v, route_seen_[r])) continue;
    if (route_have_[r] && v == route_last_[r]) continue;
    route_have_[r] = true;
    route_last_[r] = v;
    SetObject(rc.slave_index, rc.slave_subindex, v, rc.type, true);
  }
  WriteStatusRecord(false);
  ForwardEmcy();
}

void PlcSlave::WriteStatusRecord(bool) {
  const GatewayConfig& g = gw_->cfg();
  if (!g.has_status) return;
  uint64_t version = gw_->states_version();
  if (version == states_seen_) return;
  states_seen_ = version;
  co_dev_t* d = D(dev());
  for (unsigned k = 0; k < 4; ++k) {
    int net = gw_->field_network(k);
    if (net < 0) break;
    uint16_t rec = static_cast<uint16_t>(g.status_index + k), bits = static_cast<uint16_t>(g.status_index + 0x10 + k);
    uint32_t words[4] = {0, 0, 0, 0};
    for (unsigned node = 1; node <= 127; ++node) {
      uint8_t st = gw_->node_state(static_cast<unsigned>(net), node);
      if (st == kStateOperational) words[node / 32] |= 1u << (node % 32);
      co_sub_t* sub = co_dev_find_sub(d, rec, static_cast<uint8_t>(node));
      if (!sub) continue;
      if (co_dev_get_val_u8(d, rec, static_cast<uint8_t>(node)) == st) continue;
      co_sub_set_val_u8(sub, st);
      Changed(rec, static_cast<uint8_t>(node));
    }
    for (uint8_t w = 0; w < 4; ++w) {
      co_sub_t* sub = co_dev_find_sub(d, bits, static_cast<uint8_t>(w + 1));
      if (!sub || co_sub_get_val_u32(sub) == words[w]) continue;
      co_sub_set_val_u32(sub, words[w]);
      Changed(bits, static_cast<uint8_t>(w + 1));
    }
  }
}

void PlcSlave::ForwardEmcy() {
  if (!gw_->cfg().emcy_forward) return;
  gw_->take_emcy(emcy_scratch_);
  for (const auto& e : emcy_scratch_) {
    int pos = gw_->field_position(e.network);
    uint32_t key = (e.network << 8 | e.node) + 1;
    if (e.code) {
      uint8_t msef[5] = {static_cast<uint8_t>(pos < 0 ? 0 : pos), static_cast<uint8_t>(e.node), 0, 0, 0};
      PushError(key, e.code, e.er, msef);
    } else {
      RemoveError(key);
    }
  }
}

uint32_t PlcSlave::BridgeCommand(uint8_t command) {
  const GatewayConfig& g = gw_->cfg();
  uint16_t b = g.sdo_bridge_index;
  co_dev_t* d = D(dev());
  auto status = [&](uint8_t st, uint32_t abort) {
    if (co_sub_t* s = co_dev_find_sub(d, b, 8)) co_sub_set_val_u8(s, st);
    if (co_sub_t* s = co_dev_find_sub(d, b, 9)) co_sub_set_val_u32(s, abort);
    Changed(b, 8);
  };
  if (command == 0) return 0;
  if (command != 1 && command != 2) return 0x06090030u;  // value range exceeded
  if (bridge_.busy) return kAbortDeviceState;
  bool write = command == 2;
  if (write && !g.sdo_bridge_write) {
    log_warn("gateway: SDO bridge write refused (sdo_bridge_write is not set)");
    status(kBridgeAborted, kAbortNoTransfer);
    return 0;
  }
  unsigned pos = co_dev_get_val_u8(d, b, 1);
  int net = gw_->field_network(pos);
  canopen_plc_request req{};
  req.node = co_dev_get_val_u8(d, b, 2);
  req.index = co_dev_get_val_u16(d, b, 3);
  req.subindex = co_dev_get_val_u8(d, b, 4);
  req.write = write ? 1 : 0;
  req.kind = CANOPEN_PLC_INT;
  req.timeout_ms = 1000;
  uint8_t data[8] = {0};
  uint32_t value = co_dev_get_val_u32(d, b, 5);
  uint8_t len = co_dev_get_val_u8(d, b, 6);
  if (net < 0 || req.node < 1 || req.node > 127 || (write && len > 4)) {
    status(kBridgeAborted, kAbortGeneral);
    return 0;
  }
  req.network = static_cast<uint8_t>(net);
  if (write) {
    for (int i = 0; i < 4; ++i) data[i] = static_cast<uint8_t>(value >> (8 * i));
    req.data = data;
    req.length = 8;
    req.size = len;
  }
  uint16_t err = 0;
  uint32_t handle = PlcRequests::instance().start(req, err);
  if (!handle) {
    status(kBridgeAborted, err == CANOPEN_PLC_ERR_BUSY ? kAbortDeviceState : kAbortGeneral);
    return 0;
  }
  bridge_.busy = true;
  bridge_.handle = handle;
  bridge_.write = write;
  bridge_.started = std::chrono::steady_clock::now();
  status(kBridgeBusy, 0);
  log_info("gateway: SDO bridge %s of node %u 0x%04X:%u on network %u", write ? "write" : "read", req.node, req.index,
           req.subindex, pos);
  return 0;
}

void PlcSlave::ServiceBridge() {
  if (!gw_ || !bridge_.busy) return;
  canopen_plc_result res{};
  uint8_t data[8] = {0};
  int rc = PlcRequests::instance().poll(bridge_.handle, &res, data, sizeof(data));
  if (rc == 0) return;
  bridge_.busy = false;
  co_dev_t* d = D(dev());
  uint16_t b = gw_->cfg().sdo_bridge_index;
  if (rc == 1) {
    if (!bridge_.write) {
      uint32_t v = 0;
      unsigned n = std::min<uint32_t>(res.size, 4);
      for (unsigned i = 0; i < n; ++i) v |= uint32_t(data[i]) << (8 * i);
      if (co_sub_t* s = co_dev_find_sub(d, b, 5)) co_sub_set_val_u32(s, v);
      if (co_sub_t* s = co_dev_find_sub(d, b, 6)) co_sub_set_val_u8(s, static_cast<uint8_t>(std::min<uint32_t>(res.size, 255)));
      Changed(b, 5);
    }
    if (co_sub_t* s = co_dev_find_sub(d, b, 9)) co_sub_set_val_u32(s, 0);
    if (co_sub_t* s = co_dev_find_sub(d, b, 8)) co_sub_set_val_u8(s, kBridgeDone);
  } else {
    uint32_t abort = res.abort_code;
    if (!abort) abort = res.error_id == CANOPEN_PLC_ERR_TIMEOUT ? kAbortTimeout
                        : res.error_id == CANOPEN_PLC_ERR_UNAVAILABLE ? kAbortDeviceState : kAbortGeneral;
    if (co_sub_t* s = co_dev_find_sub(d, b, 9)) co_sub_set_val_u32(s, abort);
    if (co_sub_t* s = co_dev_find_sub(d, b, 8)) co_sub_set_val_u8(s, kBridgeAborted);
  }
  Changed(b, 8);
}

// ---------------------------------------------------------------------------
// Diagnostics (canopen-online-diagnostics "Slave network status")

void PlcSlave::ServiceDiag() {
  if (!diag_ || stopped_) return;
  std::vector<DiagRequest> reqs;
  diag_->take(reqs);
  diag_->set_operational(nmt_state() == 5 ? "the plugin's own slave" : "");
  // The guard of hand-sent frames: the PDO COB-IDs as the dictionary has them now.
  if (diag_->ids_due()) diag_->set_used_ids(dictionary_id_uses(dev(), "the plugin's own slave"));
  for (auto& r : reqs) {
    if (r.op == "status")
      DiagStatus(r);
    else if (r.op == "sdo_read" || r.op == "sdo_write")
      DiagSdo(r);
    else
      diag_->answer(r.seq, diag_error(r.id, "network \"" + cfg_.network + "\" is a slave network; " + r.op +
                                                " needs a master network"));
  }
}

void PlcSlave::DiagStatus(const DiagRequest& r) {
  cJSON* res = cJSON_CreateObject();
  cJSON_AddStringToObject(res, "version", diag_->version().c_str());
  cJSON_AddNumberToObject(res, "uptime_s", diag_->uptime_s());
  cJSON_AddStringToObject(res, "config_sha256", cfg_.file_sha256.c_str());
  diag_add_protocols(res);
  cJSON_AddStringToObject(res, "network", cfg_.network.c_str());
  cJSON_AddStringToObject(res, "role", "slave");
  cJSON_AddBoolToObject(res, "session", true);
  cJSON_AddBoolToObject(res, "simulated_network", cfg_.adapter.simulate);
  cJSON_AddBoolToObject(res, "simulation_forced", cfg_.adapter.simulation_forced);
  cJSON* s = cJSON_AddObjectToObject(res, "slave");
  cJSON_AddNumberToObject(s, "node_id", node_id() == 0xFF ? 0 : node_id());
  cJSON_AddNumberToObject(s, "state", nmt_state());
  cJSON_AddBoolToObject(s, "comm_ok", last_comm_);
  cJSON_AddNumberToObject(s, "sync_count", sync_count_);
  cJSON_AddNumberToObject(s, "emcy_code", emcy_code_);
  cJSON_AddNumberToObject(s, "error_register", co_dev_get_val_u8(D(dev()), 0x1001, 0));
  for (bool tx : {true, false}) {
    cJSON* arr = cJSON_AddArrayToObject(s, tx ? "tpdos" : "rpdos");
    for (const auto& p : Pdos(tx)) {
      cJSON* o = cJSON_CreateObject();
      cJSON_AddNumberToObject(o, "number", p.number);
      cJSON_AddNumberToObject(o, "cob_id", p.cob_id);
      cJSON_AddNumberToObject(o, "transmission", p.transmission);
      cJSON* e = cJSON_AddArrayToObject(o, "entries");
      for (uint32_t m : p.entries) {
        cJSON* x = cJSON_CreateObject();
        cJSON_AddNumberToObject(x, "index", m >> 16);
        cJSON_AddNumberToObject(x, "subindex", (m >> 8) & 0xFF);
        cJSON_AddNumberToObject(x, "bits", m & 0xFF);
        cJSON_AddItemToArray(e, x);
      }
      cJSON_AddItemToArray(arr, o);
    }
  }
  cJSON* b = cJSON_AddObjectToObject(res, "bus");
  cJSON_AddStringToObject(b, "interface", cfg_.adapter.interface.c_str());
  if (gw_) {
    cJSON* g = cJSON_AddObjectToObject(res, "gateway");
    cJSON_AddNumberToObject(g, "routes", static_cast<double>(gw_->cfg().routes.size()));
    cJSON_AddBoolToObject(g, "upper_ok", gw_->upper_ok());
    cJSON_AddNumberToObject(g, "forwarded_errors", static_cast<double>(errors_.size()));
  }
  cJSON_AddArrayToObject(res, "nodes");
  diag_->add_tx_status(res);
  diag_->answer(r.seq, diag_ok(r.id, res));
}

void PlcSlave::DiagSdo(const DiagRequest& r) {
  if (r.node != node_id()) {
    diag_->answer(r.seq, diag_error(r.id, "node " + std::to_string(r.node) + " is not this slave (node ID " +
                                              std::to_string(node_id()) + "); a slave network reads and writes "
                                              "only its own dictionary"));
    return;
  }
  bool write = r.op == "sdo_write";
  cJSON* res = cJSON_CreateObject();
  cJSON_AddNumberToObject(res, "node", node_id());
  cJSON_AddNumberToObject(res, "index", r.index);
  cJSON_AddNumberToObject(res, "subindex", r.subindex);
  co_dev_t* d = D(dev());
  co_sub_t* sub = co_dev_find_sub(d, r.index, r.subindex);
  uint32_t abort = 0;
  std::vector<uint8_t> data;
  if (!sub) {
    abort = co_dev_find_obj(d, r.index) ? 0x06090011u : 0x06020000u;
  } else if (write) {
    if (!(co_sub_get_access(sub) & CO_ACCESS_WRITE)) {
      abort = 0x06010002u;
    } else {
      co_unsigned16_t type = co_sub_get_type(sub);
      union co_val val;
      co_val_init(type, &val);
      size_t n = co_val_read(type, &val, r.data.data(), r.data.data() + r.data.size());
      if (!n && !r.data.empty()) {
        abort = 0x06070010u;
      } else {
        // Through the object's download indication, as an SDO write from the
        // master: Lely's own handlers (heartbeat consumers, PDO parameters,
        // store and restore) and its range checks then apply.
        abort = co_sub_dn_ind_val(sub, type, &val);
        if (!abort) {
          Changed(r.index, r.subindex);
          log_info("own object 0x%04X sub %u written by %s", r.index, r.subindex, diag_client(r).c_str());
        }
      }
      co_val_fini(type, &val);
    }
  } else {
    co_unsigned16_t type = co_sub_get_type(sub);
    const void* val = co_sub_get_val(sub);
    size_t n = co_val_write(type, val, nullptr, nullptr);
    data.resize(n);
    if (n) co_val_write(type, val, data.data(), data.data() + n);
  }
  if (!abort) {
    cJSON_AddBoolToObject(res, "success", true);
    if (!write) {
      cJSON_AddStringToObject(res, "data", hex_bytes(data).c_str());
      cJSON_AddNumberToObject(res, "size", static_cast<double>(data.size()));
    }
  } else {
    char hex[16];
    std::snprintf(hex, sizeof(hex), "0x%08X", abort);
    cJSON_AddBoolToObject(res, "success", false);
    cJSON_AddNumberToObject(res, "abort_code", abort);
    cJSON_AddStringToObject(res, "abort_code_hex", hex);
    cJSON_AddStringToObject(res, "error", ("SDO abort " + std::string(hex)).c_str());
  }
  diag_->answer(r.seq, diag_ok(r.id, res));
}

}  // namespace canopen_plugin
