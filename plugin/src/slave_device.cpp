#include "slave_device.h"

#include <cstring>

#include <lely/can/msg.h>
#include <lely/can/net.hpp>
#include <lely/co/dev.hpp>
#include <lely/co/nmt.hpp>
#include <lely/co/obj.hpp>
#include <lely/co/val.hpp>
#include <lely/ev/exec.hpp>

// From <lely/co/lss.h>, which does not mix with the C++ headers.
extern "C" {
typedef void co_lss_rate_ind_t(co_lss_t* lss, co_unsigned16_t rate, int delay, void* data);
void co_lss_set_rate_ind(co_lss_t* lss, co_lss_rate_ind_t* ind, void* data);
}

namespace canopen_plugin {

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

uint32_t u32(const co_dev_t* dev, uint16_t idx, uint8_t sub) { return co_dev_get_val_u32(dev, idx, sub); }
uint8_t u8(const co_dev_t* dev, uint16_t idx, uint8_t sub) { return co_dev_get_val_u8(dev, idx, sub); }

bool has_u32(const co_dev_t* dev, uint16_t idx, uint8_t sub) {
  const co_sub_t* s = co_dev_find_sub(dev, idx, sub);
  return s && co_sub_get_type(s) == CO_DEFTYPE_UNSIGNED32;
}

int guard_hook(const can_msg* msg, void* data) {
  if (msg->flags & CAN_FLAG_RTR) return 0;  // node guarding requests come from the master
  static_cast<SlaveDevice*>(data)->Foreign();
  return 0;
}

int lss_watch(const can_msg* msg, void* data) {
  if (msg->len >= 2 && msg->data[0] == 0x04 && msg->data[1] == 0x00) static_cast<SlaveDevice*>(data)->LssWaiting();
  return 0;
}

}  // namespace

// Lely starts a slave without an NMT startup value (0x1F80) straight into
// OPERATIONAL. A CiA 301 slave waits in PRE-OPERATIONAL for the master's
// start, so an EDS without 0x1F80 gets one with bit 2 set ("do not start
// automatically"), read-only. An EDS that has 0x1F80 keeps its own value.
void SlaveDevice::WaitForNmtStart() {
  co_dev_t* d = reinterpret_cast<co_dev_t*>(dev());
  if (co_dev_find_obj(d, 0x1F80)) return;
  co_obj_t* obj = co_obj_create(0x1F80);
  if (!obj) return;
  co_obj_set_code(obj, CO_OBJECT_VAR);
  co_sub_t* sub = co_sub_create(0x00, CO_DEFTYPE_UNSIGNED32);
  if (!sub || co_obj_insert_sub(obj, sub) == -1 || co_dev_insert_obj(d, obj) == -1) {
    if (sub && !co_sub_get_obj(sub)) co_sub_destroy(sub);
    co_obj_destroy(obj);
    return;
  }
  co_sub_set_name(sub, "NMT startup");
  co_obj_set_name(obj, "NMT startup");
  co_sub_set_access(sub, CO_ACCESS_RO);
  co_unsigned32_t v = 0x04;
  co_sub_set_val(sub, &v, sizeof(v));
}

SlaveDevice::SlaveDevice(ev_exec_t* exec, lely::io::TimerBase& timer, lely::io::CanChannelBase& chan,
                         const std::string& eds, uint8_t node_id, std::shared_ptr<SlaveStore> store,
                         Options options)
    : BasicSlave(timer, chan, eds, "", node_id), exec_(exec), store_(std::move(store)), options_(options) {
  if (!store_) store_ = std::make_shared<SlaveStore>();
  if (options_.wait_for_start) WaitForNmtStart();
  const co_dev_t* d = D(dev());
  // Parameter save and load, as a device with non-volatile memory does; the
  // master asks for it explicitly, so this is never an automatic write.
  for (uint8_t sub = 1; sub <= 0x7F; ++sub) {
    if (has_u32(d, 0x1010, sub)) {
      BasicSlave::OnWrite<uint32_t>(0x1010, sub, [this](uint16_t, uint8_t s, uint32_t& v, uint32_t) -> std::error_code {
        if (v != kSave) return lely::canopen::SdoErrc::DATA;
        Save(s);
        v = 1;  // reads back as "saves on command"
        return {};
      });
      (*this)[0x1010][sub] = static_cast<uint32_t>(1);
    }
    if (has_u32(d, 0x1011, sub)) {
      BasicSlave::OnWrite<uint32_t>(0x1011, sub, [this](uint16_t, uint8_t s, uint32_t& v, uint32_t) -> std::error_code {
        if (v != kLoad) return lely::canopen::SdoErrc::DATA;
        Load(s);
        v = 1;
        return {};
      });
      (*this)[0x1011][sub] = static_cast<uint32_t>(1);
    }
  }
  // A device without a node ID starts with the one an LSS master gave it
  // once switched to LSS waiting.
  can_net_t* net = reinterpret_cast<can_net_t*>(NetPtr());
  can_recv_t* r = can_recv_create();  // NOLINT
  if (r) {
    can_recv_set_func(r, &lss_watch, this);
    can_recv_start(r, net, 0x7E5, 0);
    recvs_.push_back(reinterpret_cast<__can_recv*>(r));
  }
}

SlaveDevice::~SlaveDevice() {
  for (auto* r : recvs_) can_recv_destroy(reinterpret_cast<can_recv_t*>(r));
}

__can_net* SlaveDevice::NetPtr() { return lely::io::CanNet::operator __can_net*(); }

uint8_t SlaveDevice::node_id() const { return co_dev_get_id(D(dev())); }

uint8_t SlaveDevice::nmt_state() const { return co_nmt_get_st(N(nmt())) & 0x7F; }

void SlaveDevice::GuardNodeId(std::function<void()> on_conflict) {
  on_conflict_ = std::move(on_conflict);
  uint8_t nid = node_id();
  if (nid == 0 || nid > 127) return;
  can_net_t* net = reinterpret_cast<can_net_t*>(NetPtr());
  for (uint32_t id : {0x700u + nid, 0x080u + nid, 0x580u + nid}) {
    can_recv_t* r = can_recv_create();  // NOLINT
    if (!r) continue;
    can_recv_set_func(r, &guard_hook, this);
    can_recv_start(r, net, id, 0);
    recvs_.push_back(reinterpret_cast<__can_recv*>(r));
  }
}

void SlaveDevice::Foreign() {
  if (conflict_posted_ || !on_conflict_) return;
  conflict_posted_ = true;
  lely::ev::Executor(exec_).post(on_conflict_);
}

void SlaveDevice::LssWaiting() {
  std::weak_ptr<bool> alive = alive_;
  lely::ev::Executor(exec_).post([this, alive]() {
    if (alive.expired()) return;
    co_nmt_t* n = N(nmt());
    if (co_dev_get_id(D(dev())) == 0xFF && co_nmt_get_id(n) != 0xFF) co_nmt_cs_ind(n, CO_NMT_CS_RESET_COMM);
  });
}

void SlaveDevice::OnStore(uint8_t id, int) {
  store_->lss_id = id;
  if (on_log) on_log("node ID " + std::to_string(id) + " stored by the LSS master");
  if (on_stored) on_stored();
}

void SlaveDevice::Save(uint8_t subindex) {
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
  if (on_log) on_log("parameters saved by the master (0x1010 sub " + std::to_string(subindex) + ")");
  if (on_stored) on_stored();
}

void SlaveDevice::Load(uint8_t subindex) {
  for (char k : ranges_of(subindex)) store_->saved.erase(k);
  if (on_log)
    on_log("stored parameters dropped by the master (0x1011 sub " + std::to_string(subindex) +
           "); EDS values at the next reset");
  if (on_stored) on_stored();
}

void SlaveDevice::ApplyStored(bool node) {
  for (auto& kv : store_->saved) {
    if (!node && kv.first != 'C') continue;
    void* dom = nullptr;
    co_val_make(CO_DEFTYPE_DOMAIN, &dom, kv.second.data(), kv.second.size());
    co_dev_read_dcf(D(dev()), nullptr, nullptr, &dom);
    co_val_fini(CO_DEFTYPE_DOMAIN, &dom);
  }
  // Store values read back as "saves on command" whatever was restored.
  co_dev_t* d = D(dev());
  for (uint8_t sub = 1; sub <= 0x7F; ++sub) {
    if (has_u32(d, 0x1010, sub)) co_dev_set_val_u32(d, 0x1010, sub, 1);
    if (has_u32(d, 0x1011, sub)) co_dev_set_val_u32(d, 0x1011, sub, 1);
  }
}

void SlaveDevice::OnCommand(lely::canopen::NmtCommand cs) noexcept {
  if (cs == lely::canopen::NmtCommand::RESET_NODE) node_reset_ = true;
  if (cs == lely::canopen::NmtCommand::RESET_COMM) {
    // Lely has just restored the defaults; the stored values come back
    // before the boot-up message.
    ApplyStored(node_reset_);
    node_reset_ = false;
    // The plugin owns the adapter's bit rate: an LSS bit timing request is
    // answered "not supported" (Lely does that without a rate indication).
    if (options_.refuse_lss_bitrate) {
      co_lss_t* lss = co_nmt_get_lss(N(nmt()));
      if (lss) co_lss_set_rate_ind(lss, nullptr, nullptr);
    }
    OnRestored();
  }
}

void SlaveDevice::Changed(uint16_t index, uint8_t subindex) {
  std::error_code ec;
  SetEvent(index, subindex, ec);
}

bool SlaveDevice::InRpdo(uint16_t index, uint8_t subindex) const { return InPdo(0x1400, index, subindex); }

bool SlaveDevice::InTpdo(uint16_t index, uint8_t subindex) const { return InPdo(0x1800, index, subindex); }

bool SlaveDevice::InPdo(uint16_t base, uint16_t index, uint8_t subindex) const {
  const co_dev_t* d = D(dev());
  for (const co_obj_t* o = co_dev_first_obj(d); o; o = co_obj_next(o)) {
    uint16_t comm = co_obj_get_idx(o);
    if (comm < base) continue;
    if (comm >= base + 0x200) break;
    if (!co_dev_find_sub(d, comm, 1) || (u32(d, comm, 1) & 0x80000000u)) continue;
    uint16_t map = static_cast<uint16_t>(comm + 0x200);
    unsigned count = co_dev_find_sub(d, map, 0) ? u8(d, map, 0) : 0;
    for (unsigned k = 1; k <= count && k <= 64; ++k) {
      if (!co_dev_find_sub(d, map, static_cast<uint8_t>(k))) continue;
      uint32_t e = u32(d, map, static_cast<uint8_t>(k));
      if ((e >> 16) == index && ((e >> 8) & 0xFF) == subindex) return true;
    }
  }
  return false;
}

std::vector<SlaveDevice::PdoMap> SlaveDevice::Pdos(bool tpdo) const {
  std::vector<PdoMap> out;
  const co_dev_t* d = D(dev());
  uint16_t base = tpdo ? 0x1800 : 0x1400;
  for (const co_obj_t* o = co_dev_first_obj(d); o; o = co_obj_next(o)) {
    uint16_t comm = co_obj_get_idx(o);
    if (comm < base) continue;
    if (comm >= base + 0x200) break;
    if (!co_dev_find_sub(d, comm, 1)) continue;
    uint32_t cob = u32(d, comm, 1);
    if (cob & 0x80000000u) continue;
    uint16_t map = static_cast<uint16_t>(comm + 0x200);
    PdoMap p;
    p.number = comm - base + 1u;
    p.cob_id = cob & 0x1FFFFFFFu;
    p.transmission = co_dev_find_sub(d, comm, 2) ? u8(d, comm, 2) : 255;
    unsigned count = co_dev_find_sub(d, map, 0) ? u8(d, map, 0) : 0;
    for (unsigned k = 1; k <= count && k <= 64; ++k) {
      if (!co_dev_find_sub(d, map, static_cast<uint8_t>(k))) continue;
      p.entries.push_back(u32(d, map, static_cast<uint8_t>(k)));
    }
    out.push_back(p);
  }
  return out;
}

}  // namespace canopen_plugin
