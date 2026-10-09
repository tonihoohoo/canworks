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
  if (self->Blocked(msg->id, msg->data, msg->len)) return 0;
  if (self->Hold(msg, sizeof *msg, msg->id, msg->data, msg->len)) return 0;
  return self->SendOriginal(msg);
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
}

SimDevice::~SimDevice() {
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

uint32_t SimDevice::Rule(uint16_t index, uint8_t subindex, bool write) {
  // RPDO data goes through the same indication: process data is never refused.
  if (write && InRpdo(index, subindex)) return 0;
  for (auto it = sdo_rules.begin(); it != sdo_rules.end(); ++it) {
    if (it->index != index || it->subindex != subindex) continue;
    if (write ? !it->on_write : !it->on_read) continue;
    // TPDOs read their objects through the same indication.
    if (!write && InTpdo(index, subindex)) return 0;
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
}

void SimDevice::SendEmcy(uint16_t code, uint8_t reg, const uint8_t msef[5]) { Error(code, reg, msef); }

void SimDevice::ClearEmcy() { co_emcy_clear(co_nmt_get_emcy(N(nmt()))); }

void SimDevice::SelfCommand(uint8_t cs) { co_nmt_cs_ind(N(nmt()), cs); }

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
