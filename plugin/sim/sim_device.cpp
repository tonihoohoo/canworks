#include "sim_device.h"

#include <cstring>

#include <lely/can/msg.h>
#include <lely/can/net.hpp>
#include <lely/co/dev.hpp>
#include <lely/co/emcy.hpp>
#include <lely/co/lss.hpp>
#include <lely/co/nmt.hpp>
#include <lely/co/obj.hpp>
#include <lely/co/val.hpp>
#include <lely/ev/exec.hpp>

#include "sim_od.h"

namespace canopen_sim {

namespace {

constexpr uint32_t kSave = 0x65766173u;  // "save"
constexpr uint32_t kLoad = 0x64616F6Cu;  // "load"

co_dev_t* D(__co_dev* d) { return reinterpret_cast<co_dev_t*>(d); }
co_nmt_t* N(__co_nmt* n) { return reinterpret_cast<co_nmt_t*>(n); }

struct Range {
  char key;
  uint16_t min, max;
};
const Range kRanges[] = {{'C', 0x1000, 0x1FFF}, {'M', 0x2000, 0x5FFF}, {'A', 0x6000, 0x9FFF}};

// The ranges a 0x1010/0x1011 subindex covers (CiA 301).
std::string ranges_of(uint8_t sub) {
  if (sub == 1) return "CMA";
  if (sub == 2) return "C";
  if (sub == 3) return "A";
  return "M";
}

int send_hook(const can_msg* msg, void* data) {
  auto* self = static_cast<SimDevice*>(data);
  if (self->Blocked(msg->id, msg->data, msg->len)) return 0;
  if (self->Hold(msg, sizeof *msg, msg->id, msg->data, msg->len)) return 0;
  return self->SendOriginal(msg);
}

int guard_hook(const can_msg* msg, void* data) {
  if (msg->flags & CAN_FLAG_RTR) return 0;  // node guarding requests come from the master
  static_cast<SimDevice*>(data)->Foreign();
  return 0;
}

int lss_watch(const can_msg* msg, void* data) {
  if (msg->len >= 2 && msg->data[0] == 0x04 && msg->data[1] == 0x00) static_cast<SimDevice*>(data)->LssWaiting();
  return 0;
}

int lss_store(co_lss_t*, co_unsigned8_t id, co_unsigned16_t, void* data) {
  static_cast<SimDevice*>(data)->LssStored(id);
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
    : BasicSlave(timer, chan, dcf, "", node_id), exec_(exec), store_(std::move(store)) {
  if (!store_) store_ = std::make_shared<StoredState>();
  can_net_t* net = reinterpret_cast<can_net_t*>(NetPtr());
  can_send_func_t* f = nullptr;
  void* d = nullptr;
  can_net_get_send_func(net, &f, &d);
  send_func_ = reinterpret_cast<void*>(f);
  send_data_ = d;
  can_net_set_send_func(net, &send_hook, this);

  // Parameter save and load, as a device with non-volatile memory does.
  for (uint8_t sub = 1; sub <= 0x7F; ++sub) {
    if (od_type(od(), 0x1010, sub) == 7 /* UNSIGNED32 */) {
      BasicSlave::OnWrite<uint32_t>(0x1010, sub, [this](uint16_t, uint8_t s, uint32_t& v, uint32_t) -> std::error_code {
        if (v != kSave) return lely::canopen::SdoErrc::DATA;
        Save(s);
        v = 1;  // reads back as "saves on command"
        return {};
      });
      (*this)[0x1010][sub] = static_cast<uint32_t>(1);
    }
    if (od_type(od(), 0x1011, sub) == 7) {
      BasicSlave::OnWrite<uint32_t>(0x1011, sub, [this](uint16_t, uint8_t s, uint32_t& v, uint32_t) -> std::error_code {
        if (v != kLoad) return lely::canopen::SdoErrc::DATA;
        Load(s);
        v = 1;
        return {};
      });
      (*this)[0x1011][sub] = static_cast<uint32_t>(1);
    }
  }
  // Devices without a node ID get theirs over LSS; they start with it once
  // switched to LSS waiting.
  can_recv_t* r = can_recv_create();  // NOLINT
  if (r) {
    can_recv_set_func(r, &lss_watch, this);
    can_recv_start(r, net, 0x7E5, 0);
    recvs_.push_back(reinterpret_cast<__can_recv*>(r));
  }
  InstallIndications();
}

SimDevice::~SimDevice() {
  for (auto* r : recvs_) can_recv_destroy(reinterpret_cast<can_recv_t*>(r));
  can_net_t* net = reinterpret_cast<can_net_t*>(NetPtr());
  can_net_set_send_func(net, reinterpret_cast<can_send_func_t*>(send_func_), send_data_);
}

__can_net* SimDevice::NetPtr() { return lely::io::CanNet::operator __can_net*(); }

uint8_t SimDevice::node_id() const { return co_dev_get_id(D(dev())); }

uint8_t SimDevice::nmt_state() const { return co_nmt_get_st(N(nmt())) & 0x7F; }

void SimDevice::InstallIndications() {
  co_dev_t* d = D(dev());
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

void SimDevice::GuardNodeId(std::function<void()> on_conflict) {
  on_conflict_ = std::move(on_conflict);
  uint8_t nid = node_id();
  if (nid == 0 || nid > 127) return;
  can_net_t* net = reinterpret_cast<can_net_t*>(NetPtr());
  for (uint32_t id : {0x700u + nid, 0x080u + nid}) {
    can_recv_t* r = can_recv_create();  // NOLINT
    if (!r) continue;
    can_recv_set_func(r, &guard_hook, this);
    can_recv_start(r, net, id, 0);
    recvs_.push_back(reinterpret_cast<__can_recv*>(r));
  }
}

void SimDevice::Foreign() {
  if (conflict_posted_ || !on_conflict_) return;
  conflict_posted_ = true;
  lely::ev::Executor(exec_).post(on_conflict_);
}

void SimDevice::LssWaiting() {
  lely::ev::Executor(exec_).post([this]() {
    co_nmt_t* n = N(nmt());
    if (co_dev_get_id(D(dev())) == 0xFF && co_nmt_get_id(n) != 0xFF) co_nmt_cs_ind(n, CO_NMT_CS_RESET_COMM);
  });
}

void SimDevice::LssStored(uint8_t id) {
  store_->lss_id = id;
  if (on_log) on_log("stored node ID " + std::to_string(id) + " (LSS)");
}

void SimDevice::Save(uint8_t subindex) {
  for (char k : ranges_of(subindex)) {
    for (const auto& r : kRanges) {
      if (r.key != k) continue;
      void* dom = nullptr;
      if (co_dev_write_dcf(D(dev()), r.min, r.max, &dom) == -1) continue;
      const uint8_t* p = static_cast<const uint8_t*>(dom);
      store_->saved[k].assign(p, p + co_val_sizeof(CO_DEFTYPE_DOMAIN, &dom));
      co_val_fini(CO_DEFTYPE_DOMAIN, &dom);
    }
  }
  if (on_log) on_log("saved parameters (0x1010 sub " + std::to_string(subindex) + ")");
}

void SimDevice::Load(uint8_t subindex) {
  for (char k : ranges_of(subindex)) store_->saved.erase(k);
  if (on_log) on_log("restore defaults at the next reset (0x1011 sub " + std::to_string(subindex) + ")");
}

void SimDevice::ApplyStored(bool node) {
  for (auto& kv : store_->saved) {
    if (!node && kv.first != 'C') continue;
    void* dom = nullptr;
    co_val_make(CO_DEFTYPE_DOMAIN, &dom, kv.second.data(), kv.second.size());
    co_dev_read_dcf(D(dev()), nullptr, nullptr, &dom);
    co_val_fini(CO_DEFTYPE_DOMAIN, &dom);
  }
  // Store values read back as "saves on command" whatever was restored.
  for (uint8_t sub = 1; sub <= 0x7F; ++sub) {
    if (od_type(od(), 0x1010, sub) == 7) od_write(od(), 0x1010, sub, Value::number(1));
    if (od_type(od(), 0x1011, sub) == 7) od_write(od(), 0x1011, sub, Value::number(1));
  }
}

void SimDevice::ApplyOverrides() {
  for (auto& kv : identity) od_write(od(), 0x1018, kv.first, Value::number(kv.second));
  if (has_device_type) od_write(od(), 0x1000, 0, Value::number(device_type));
}

void SimDevice::OnCommand(lely::canopen::NmtCommand cs) noexcept {
  if (cs == lely::canopen::NmtCommand::RESET_NODE) node_reset_ = true;
  if (cs == lely::canopen::NmtCommand::RESET_COMM) {
    // Lely has just restored the defaults; the stored values and overrides
    // come back before the boot-up message.
    ApplyStored(node_reset_);
    node_reset_ = false;
    ApplyOverrides();
    co_lss_t* lss = co_nmt_get_lss(N(nmt()));
    if (lss) co_lss_set_store_ind(lss, &lss_store, this);
    InstallIndications();
  }
}

void SimDevice::SendEmcy(uint16_t code, uint8_t reg, const uint8_t msef[5]) { Error(code, reg, msef); }

void SimDevice::ClearEmcy() { co_emcy_clear(co_nmt_get_emcy(N(nmt()))); }

void SimDevice::SelfCommand(uint8_t cs) { co_nmt_cs_ind(N(nmt()), cs); }

void SimDevice::ForgetNodeId() {
  co_nmt_t* n = N(nmt());
  co_nmt_set_id(n, 0xFF);
  co_nmt_cs_ind(n, CO_NMT_CS_RESET_COMM);
}

void SimDevice::Changed(uint16_t index, uint8_t subindex) {
  std::error_code ec;
  SetEvent(index, subindex, ec);
}

bool SimDevice::InRpdo(uint16_t index, uint8_t subindex) const { return InPdo(0x1400, index, subindex); }

bool SimDevice::InTpdo(uint16_t index, uint8_t subindex) const { return InPdo(0x1800, index, subindex); }

bool SimDevice::InPdo(uint16_t base, uint16_t index, uint8_t subindex) const {
  for (uint16_t n = 0; n < 512; ++n) {
    uint16_t comm = static_cast<uint16_t>(base + n), map = static_cast<uint16_t>(base + 0x200 + n);
    if (!od_has(od(), comm, 1)) {
      if (n > 64) break;
      continue;
    }
    uint32_t cob = static_cast<uint32_t>(od_number(od(), comm, 1));
    if (cob & 0x80000000u) continue;
    unsigned count = static_cast<unsigned>(od_number(od(), map, 0));
    for (unsigned k = 1; k <= count && k <= 64; ++k) {
      uint32_t e = static_cast<uint32_t>(od_number(od(), map, static_cast<uint8_t>(k)));
      if ((e >> 16) == index && ((e >> 8) & 0xFF) == subindex) return true;
    }
  }
  return false;
}

std::vector<std::pair<uint16_t, uint8_t>> SimDevice::PdoObjects() const {
  std::vector<std::pair<uint16_t, uint8_t>> out;
  for (uint16_t base : {static_cast<uint16_t>(0x1800), static_cast<uint16_t>(0x1400)}) {
    uint16_t map_base = base == 0x1800 ? 0x1A00 : 0x1600;
    for (uint16_t n = 0; n < 512; ++n) {
      uint16_t comm = static_cast<uint16_t>(base + n), map = static_cast<uint16_t>(map_base + n);
      if (!od_has(od(), comm, 1)) {
        if (n > 64) break;
        continue;
      }
      uint32_t cob = static_cast<uint32_t>(od_number(od(), comm, 1));
      if (cob & 0x80000000u) continue;
      unsigned count = static_cast<unsigned>(od_number(od(), map, 0));
      for (unsigned k = 1; k <= count && k <= 64; ++k) {
        uint32_t e = static_cast<uint32_t>(od_number(od(), map, static_cast<uint8_t>(k)));
        uint16_t idx = static_cast<uint16_t>(e >> 16);
        uint8_t sub = static_cast<uint8_t>((e >> 8) & 0xFF);
        if (idx < 0x20) continue;  // dummy entries
        std::pair<uint16_t, uint8_t> p(idx, sub);
        bool dup = false;
        for (auto& q : out) dup = dup || q == p;
        if (!dup) out.push_back(p);
      }
    }
  }
  return out;
}

}  // namespace canopen_sim
