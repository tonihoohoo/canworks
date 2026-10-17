#include "sim_device.h"

#include <cstring>

#include <lely/can/msg.h>
#include <lely/can/net.hpp>
#include <lely/co/dev.hpp>
#include <lely/co/emcy.hpp>
#include <lely/co/nmt.hpp>
#include <lely/co/obj.hpp>
#include <lely/co/val.hpp>
#include <lely/ev/exec.hpp>

#include "sim_od.h"

namespace canopen_sim {

namespace {

co_nmt_t* N(__co_nmt* n) { return reinterpret_cast<co_nmt_t*>(n); }

int send_hook(const can_msg* msg, void* data) {
  auto* self = static_cast<SimDevice*>(data);
  self->SdoEnd();  // the SDO server answers after the indications
  if (self->DropLelyReset(msg->id, msg->data, msg->len)) return 0;
  if (self->Blocked(msg->id, msg->data, msg->len)) return 0;
  if (self->Hold(msg, sizeof *msg, msg->id, msg->data, msg->len)) return 0;
  return self->SendOriginal(msg);
}

int sdo_begin(const can_msg* msg, void* data) {
  static_cast<SimDevice*>(data)->SdoBegin(msg->data, msg->len);
  return 0;
}


}  // namespace

struct SimDevice::IndCtx {
  SimDevice* dev = nullptr;
  uint16_t index = 0;
  uint8_t subindex = 0;
  co_sub_dn_ind_t* dn = nullptr;
  void* dn_data = nullptr;
  co_sub_up_ind_t* up = nullptr;
  void* up_data = nullptr;
};

namespace {

co_unsigned32_t dn_ind(co_sub_t* sub, co_sdo_req* req, void* data) {
  auto* c = static_cast<SimDevice::IndCtx*>(data);
  uint32_t code = c->dev->Rule(c->index, c->subindex, true);
  if (code) return code;
  return c->dn ? c->dn(sub, req, c->dn_data) : 0;
}

co_unsigned32_t up_ind(const co_sub_t* sub, co_sdo_req* req, void* data) {
  auto* c = static_cast<SimDevice::IndCtx*>(data);
  uint32_t code = c->dev->Rule(c->index, c->subindex, false);
  if (code) return code;
  return c->up ? c->up(sub, req, c->up_data) : 0;
}

}  // namespace

SimDevice::SimDevice(ev_exec_t* exec, lely::io::TimerBase& timer, lely::io::CanChannelBase& chan,
                     const std::string& dcf, uint8_t node_id, std::shared_ptr<StoredState> store)
    : SlaveDevice(exec, timer, chan, dcf, node_id, std::move(store), Options{false, false}) {
  can_net_t* net = reinterpret_cast<can_net_t*>(NetPtr());
  can_send_func_t* f = nullptr;
  void* d = nullptr;
  can_net_get_send_func(net, &f, &d);
  send_func_ = reinterpret_cast<void*>(f);
  send_data_ = d;
  can_net_set_send_func(net, &send_hook, this);
  InstallIndications();
  can_recv_t* b = can_recv_create();  // NOLINT
  if (b) can_recv_set_func(b, &sdo_begin, this);
  sdo_begin_ = b;
}

SimDevice::~SimDevice() {
  can_recv_destroy(static_cast<can_recv_t*>(sdo_begin_));
  can_net_t* net = reinterpret_cast<can_net_t*>(NetPtr());
  can_net_set_send_func(net, reinterpret_cast<can_send_func_t*>(send_func_), send_data_);
}

void SimDevice::InstallIndications() {
  co_dev_t* d = reinterpret_cast<co_dev_t*>(dev());
  // Existing contexts by sub-object; Lely may have replaced our indication
  // after a reset (it sets its own on the communication objects).
  std::map<co_sub_t*, IndCtx*> known;
  for (auto& c : inds_) {
    co_sub_t* s = co_dev_find_sub(d, c->index, c->subindex);
    if (s) known[s] = c.get();
  }
  for (co_obj_t* o = co_dev_first_obj(d); o; o = co_obj_next(o)) {
    for (co_sub_t* s = co_obj_first_sub(o); s; s = co_sub_next(s)) {
      IndCtx* c = nullptr;
      auto it = known.find(s);
      if (it != known.end()) {
        c = it->second;
      } else {
        inds_.emplace_back(new IndCtx);
        c = inds_.back().get();
        c->dev = this;
        c->index = co_obj_get_idx(o);
        c->subindex = co_sub_get_subidx(s);
      }
      co_sub_dn_ind_t* dn = nullptr;
      void* dn_data = nullptr;
      co_sub_get_dn_ind(s, &dn, &dn_data);
      if (dn != &dn_ind) {
        c->dn = dn;
        c->dn_data = dn_data;
        co_sub_set_dn_ind(s, &dn_ind, c);
      }
      co_sub_up_ind_t* up = nullptr;
      void* up_data = nullptr;
      co_sub_get_up_ind(s, &up, &up_data);
      if (up != &up_ind) {
        c->up = up;
        c->up_data = up_data;
        co_sub_set_up_ind(s, &up_ind, c);
      }
    }
  }
}

// Lely's CAN network calls the receivers of an identifier head first, and
// its SDO server ends the frame's dispatch: with this receiver started before
// the server (which Lely starts when the device enters PRE-OPERATIONAL, after
// the reset), it marks the server's processing of each request. The mark
// ends with the next frame the device sends (the server answers after the
// indications) or, for a request that gets no answer, once the loop has run
// the frame's dispatch. It follows the node ID at every reset. Only the
// default SDO server (0x1200) is marked; transfers through further servers
// see no rules.
void SimDevice::InstallSdoMark() {
  auto* b = static_cast<can_recv_t*>(sdo_begin_);
  in_sdo_ = sdo_block_dn_ = false;
  if (!b) return;
  can_recv_stop(b);
  uint8_t nid = node_id();
  if (nid == 0 || nid > 127) return;  // no SDO server without a node ID
  uint32_t cob = 0x600u + nid;
  const co_dev_t* d = reinterpret_cast<const co_dev_t*>(dev());
  if (co_dev_find_sub(d, 0x1200, 1)) cob = co_dev_get_val_u32(d, 0x1200, 1);
  if (cob & 0x80000000u) return;
  uint8_t flags = cob & 0x20000000u ? CAN_FLAG_IDE : 0;
  cob &= flags ? 0x1FFFFFFFu : 0x7FFu;
  can_recv_start(b, reinterpret_cast<can_net_t*>(NetPtr()), cob, flags);
}

void SimDevice::SdoBegin(const uint8_t* data, uint8_t len) {
  in_sdo_ = len > 0;
  if (!in_sdo_) return;
  unsigned gen = ++sdo_gen_;
  std::weak_ptr<bool> alive = alive_;
  lely::ev::Executor(exec_).post([this, alive, gen]() {
    if (!alive.expired() && sdo_gen_ == gen) in_sdo_ = false;
  });
  uint8_t ccs = data[0] >> 5;
  // Block download segments carry a sequence number, not a command, until
  // the end of the transfer.
  if (sdo_block_dn_) {
    sdo_write_ = true;
    if (ccs == 4 || (ccs == 6 && (data[0] & 0x01))) sdo_block_dn_ = false;
    return;
  }
  sdo_write_ = ccs == 0 || ccs == 1 || ccs == 6;
  sdo_block_dn_ = ccs == 6 && !(data[0] & 0x01);
  if (ccs == 4) in_sdo_ = false;  // abort
}

uint32_t SimDevice::Rule(uint16_t index, uint8_t subindex, bool write) {
  // Only SDO access: PDOs read and write their objects through the same
  // indications, as does a TPDO event a write sends while it is processed.
  if (!in_sdo_ || write != sdo_write_) return 0;
  for (auto it = sdo_rules.begin(); it != sdo_rules.end(); ++it) {
    if (it->index != index || it->subindex != subindex) continue;
    if (write ? !it->on_write : !it->on_read) continue;
    uint32_t code = it->code;
    if (it->count > 0 && --it->count == 0) sdo_rules.erase(it);
    return code;
  }
  if (write && refuse_write_operational && nmt_state() == 5) return 0x08000022u;
  return 0;
}

bool SimDevice::Blocked(uint32_t id, const uint8_t* data, uint8_t len) const {
  if (!powered) return true;
  uint8_t nid = node_id();
  if (nid == 0 || nid > 127) return false;
  if (heartbeat_stopped && id == 0x700u + nid && len == 1 && data[0] != 0) return true;
  for (unsigned n : stopped_tpdos) {
    uint32_t cob = static_cast<uint32_t>(od_number(od(), static_cast<uint16_t>(0x1800 + n - 1), 1));
    if (!(cob & 0x80000000u) && (cob & 0x1FFFFFFFu) == id) return true;
  }
  return false;
}

bool SimDevice::Hold(const void* msg, size_t size, uint32_t id, const uint8_t* data, uint8_t len) {
  uint8_t nid = node_id();
  if (!sdo_delay_ms || nid == 0 || nid > 127 || id != 0x580u + nid) return false;
  if (!sdo_delay_all) {
    // Only initiate answers carry the object; segments follow theirs.
    if (len < 4) return false;
    uint16_t idx = static_cast<uint16_t>(data[1] | (data[2] << 8));
    if (idx != sdo_delay_index || data[3] != sdo_delay_subindex) return false;
  }
  Held h;
  h.due = Clock::now() + std::chrono::milliseconds(sdo_delay_ms);
  h.raw.assign(static_cast<const uint8_t*>(msg), static_cast<const uint8_t*>(msg) + size);
  held_.push_back(std::move(h));
  return true;
}

int SimDevice::SendOriginal(const void* msg) {
  auto* f = reinterpret_cast<can_send_func_t*>(send_func_);
  return f ? f(static_cast<const can_msg*>(msg), send_data_) : 0;
}

void SimDevice::FlushDelayed(Clock::time_point now) {
  while (!held_.empty() && held_.front().due <= now) {
    can_msg m;
    std::memcpy(&m, held_.front().raw.data(), sizeof m);
    held_.pop_front();
    SendOriginal(&m);
  }
}

void SimDevice::OnSync(uint8_t, const time_point&) noexcept {
  if (on_sync) on_sync();
}

void SimDevice::OnRpdoWrite(uint8_t, uint16_t, uint8_t) noexcept {
  if (on_rpdo) on_rpdo();
}

void SimDevice::ApplyOverrides() {
  for (auto& kv : identity) od_write(od(), 0x1018, kv.first, Value::number(kv.second));
  if (has_device_type) od_write(od(), 0x1000, 0, Value::number(device_type));
}

void SimDevice::OnRestored() {
  // After the stored values: the overrides win, and Lely may have replaced
  // the indications on the communication objects.
  ApplyOverrides();
  InstallIndications();
  InstallSdoMark();
}

void SimDevice::SendEmcy(uint16_t code, uint8_t reg, const uint8_t msef[5]) { Error(code, reg, msef); }

void SimDevice::ClearEmcy() { co_emcy_clear(co_nmt_get_emcy(N(nmt()))); }

bool SimDevice::DropLelyReset(uint32_t id, const uint8_t* data, uint8_t len) {
  if (!drop_reset_ || len < 2 || data[0] || data[1]) return false;
  uint32_t cob = static_cast<uint32_t>(od_number(od(), 0x1014, 0));
  if ((cob & (cob & 0x20000000u ? 0x1FFFFFFFu : 0x7FFu)) != id) return false;
  drop_reset_ = false;
  return true;
}

void SimDevice::SendErrorReset(uint8_t reg, const uint8_t msef[5]) {
  co_dev_t* d = reinterpret_cast<co_dev_t*>(dev());
  co_emcy_t* e = co_nmt_get_emcy(N(nmt()));
  if (e) {
    // Lely refuses code 0 as an error, and clears with its own reset frame
    // (register 0) only when its stack has entries: that frame is dropped
    // (also when the inhibit time sends it later), and this one goes out.
    co_unsigned16_t eec = 0;
    co_emcy_peek(e, &eec, nullptr);
    if (eec) {
      drop_reset_ = true;
      co_emcy_clear(e);
    }
  }
  if (co_dev_find_sub(d, 0x1001, 0)) co_dev_set_val_u8(d, 0x1001, 0, reg);
  if (!co_dev_find_sub(d, 0x1014, 0)) return;
  uint32_t cob = static_cast<uint32_t>(od_number(od(), 0x1014, 0));
  if (cob & 0x80000000u) return;  // EMCY producer off
  can_msg m = CAN_MSG_INIT;
  if (cob & 0x20000000u) {
    m.id = cob & 0x1FFFFFFFu;
    m.flags |= CAN_FLAG_IDE;
  } else {
    m.id = cob & 0x7FFu;
  }
  m.len = 8;
  m.data[2] = reg;
  if (msef) std::memcpy(m.data + 3, msef, 5);
  if (Blocked(m.id, m.data, m.len)) return;
  SendOriginal(&m);
}

void SimDevice::SelfCommand(uint8_t cs) { co_nmt_cs_ind(N(nmt()), cs); }

bool SimDevice::lss_supported() const { return co_dev_get_lss(reinterpret_cast<const co_dev_t*>(dev())) != 0; }

void SimDevice::ForgetNodeId() {
  co_nmt_t* n = N(nmt());
  store_->lss_id = 0;
  co_nmt_set_id(n, 0xFF);
  co_nmt_cs_ind(n, CO_NMT_CS_RESET_COMM);
}

std::vector<std::pair<uint16_t, uint8_t>> SimDevice::PdoObjects() const {
  std::vector<std::pair<uint16_t, uint8_t>> out;
  for (bool tpdo : {true, false}) {
    for (const auto& p : Pdos(tpdo)) {
      for (uint32_t e : p.entries) {
        uint16_t idx = static_cast<uint16_t>(e >> 16);
        uint8_t sub = static_cast<uint8_t>((e >> 8) & 0xFF);
        if (idx < 0x20) continue;  // dummy entries
        std::pair<uint16_t, uint8_t> q(idx, sub);
        bool dup = false;
        for (auto& o : out) dup = dup || o == q;
        if (!dup) out.push_back(q);
      }
    }
  }
  return out;
}

}  // namespace canopen_sim
