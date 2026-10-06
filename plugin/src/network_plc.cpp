// network_plc.cpp - the Network's side of the PLC program's SDO function
// blocks (spec canopen-plc-sdo). Requests arrive through PlcRequests on the
// request timer; each node's program transfers run oldest first, one at a
// time per node, taking turns with the node's SDO variables.

#include <cstring>

#include <lely/co/type.h>
#include <lely/coapp/sdo_error.hpp>

#include "eds_check.h"
#include "network.h"

namespace canopen_plugin {

using lely::canopen::SdoErrc;

namespace {

constexpr uint8_t kStatePreop = 127;
constexpr uint32_t kAbortTimeout = 0x05040000u;
constexpr uint32_t kAbortGeneral = 0x08000000u;

uint32_t object_key(unsigned node, uint16_t index, uint8_t subindex) {
  return uint32_t(node) << 24 | uint32_t(index) << 8 | subindex;
}

const char* kind_name(uint8_t kind) {
  switch (kind) {
    case CANOPEN_PLC_REAL: return "REAL ";
    case CANOPEN_PLC_STRING: return "STRING ";
    case CANOPEN_PLC_BYTES: return "BYTES ";
    default: return "";
  }
}

}  // namespace

uint16_t Network::EdsType(const NodeConfig& n, uint16_t index, uint8_t subindex) {
  uint32_t key = object_key(n.node_id, index, subindex);
  auto it = eds_types_.find(key);
  if (it != eds_types_.end()) return it->second;
  uint16_t type = 0;
  if (!eds_sub_type(n, index, subindex, type)) type = 0;
  eds_types_[key] = type;
  return type;
}

uint16_t Network::ResolveWrite(unsigned id, ProgJob& p) {
  p.resolved = true;
  canopen_plc_request& r = p.job.req;
  if (!r.write || (r.kind != CANOPEN_PLC_INT && r.kind != CANOPEN_PLC_REAL)) return 0;
  unsigned size = r.size;
  uint16_t type = 0;
  if (!size || r.kind == CANOPEN_PLC_REAL) {
    auto it = nodes_.find(id);
    if (it != nodes_.end()) type = EdsType(*it->second.cfg, r.index, r.subindex);
  }
  if (r.kind == CANOPEN_PLC_INT) {
    if (!size) size = co_type_bytes(type);
    if (!size || size > 8) return CANOPEN_PLC_ERR_INPUT;
    p.job.data.resize(size);
    return 0;
  }
  // REAL: 4 or 8 bytes, from the EDS type when not given.
  if (!size) size = type == CO_DEFTYPE_REAL32 ? 4 : type == CO_DEFTYPE_REAL64 ? 8 : 0;
  if (size != 4 && size != 8) return CANOPEN_PLC_ERR_INPUT;
  if (size == 4) {
    double d;
    std::memcpy(&d, p.job.data.data(), sizeof d);
    float f = static_cast<float>(d);
    uint32_t bits;
    std::memcpy(&bits, &f, sizeof bits);
    p.job.data.resize(4);
    for (int b = 0; b < 4; ++b) p.job.data[b] = static_cast<uint8_t>(bits >> (8 * b));
  } else {
    uint64_t bits;
    std::memcpy(&bits, p.job.data.data(), sizeof bits);
    for (int b = 0; b < 8; ++b) p.job.data[b] = static_cast<uint8_t>(bits >> (8 * b));
  }
  return 0;
}

void Network::ServiceProgram(clock::time_point now) {
  PlcRequests& api = PlcRequests::instance();
  if (uint32_t v = api.take_unknown_version())
    log_warn("the PLC program's CANopen library asks for SDO block API version %u, this plugin offers version %u; "
             "update the plugin (install-stock.sh) or use the library that comes with it",
             v, CANOPEN_PLC_API_VERSION);
  api.expire(now);
  prog_taken_.clear();
  api.take(prog_taken_);
  for (auto& j : prog_taken_) {
    ProgJob p;
    p.job = std::move(j);
    prog_[p.job.req.node].push_back(std::move(p));
  }
  for (auto it = prog_.begin(); it != prog_.end();) {
    unsigned id = it->first;
    auto& q = it->second;
    auto node = nodes_.find(id);
    NodeState* n = node != nodes_.end() ? &node->second : nullptr;
    // End what cannot run; leave the first runnable request at the front.
    while (!q.empty()) {
      ProgJob& p = q.front();
      if (!p.resolved) {
        if (uint16_t err = ResolveWrite(id, p)) {
          EndProgram(id, p.job.handle, err, 0, nullptr, 0);
          q.pop_front();
          continue;
        }
      }
      if (now >= p.job.deadline) {
        EndProgram(id, p.job.handle, CANOPEN_PLC_ERR_TIMEOUT, kAbortTimeout, nullptr, 0);
        q.pop_front();
        continue;
      }
      if (n && !SdoAvailable(id, *n)) {
        // Being configured after its boot-up message, in a boot retry, or not
        // heard from yet since the master started (its first boot is still
        // to come): wait. Lost, not booted or STOPPED: not available.
        bool first_boot = !n->warned_absent && now - started_ < kAbsentAfter;
        bool booting = n->cfg->boot && !n->booted &&
                       (image_.node_state(id) == kStatePreop || n->boot_waiting || first_boot);
        if (!booting) {
          EndProgram(id, p.job.handle, CANOPEN_PLC_ERR_UNAVAILABLE, 0, nullptr, 0);
          q.pop_front();
          continue;
        }
      }
      break;
    }
    // A node the configuration does not list goes straight to its default
    // Client-SDO; configured nodes are started in ServiceRequests.
    if (!n && !q.empty() && !prog_foreign_busy_.count(id)) StartProgram(id, nullptr, now);
    if (q.empty())
      it = prog_.erase(it);
    else
      ++it;
  }
}

void Network::StartProgram(unsigned id, NodeState* n, clock::time_point now) {
  auto qit = prog_.find(id);
  if (qit == prog_.end() || qit->second.empty()) return;
  PlcRequests::Job job = std::move(qit->second.front().job);
  qit->second.pop_front();
  const canopen_plc_request& r = job.req;
  if (n && r.write && plugin_owned_object(r.index) &&
      prog_owned_warned_.insert(object_key(id, r.index, r.subindex)).second)
    log_warn("%s: the PLC program writes 0x%04X sub %u, which the plugin configures (%s); the program overrides "
             "the configured value",
             n->cfg->label().c_str(), r.index, r.subindex, plugin_owned_object(r.index));
  auto left = std::chrono::duration_cast<std::chrono::milliseconds>(job.deadline - now);
  if (left < std::chrono::milliseconds(1)) left = std::chrono::milliseconds(1);
  uint8_t node = static_cast<uint8_t>(id);
  uint32_t handle = job.handle;
  auto shared = std::make_shared<PlcRequests::Job>(std::move(job));
  std::error_code ec;
  if (!shared->req.write) {
    Submit([&] {
      SubmitRead<std::vector<uint8_t>>(
          exec_, node, shared->req.index, shared->req.subindex,
          [this, id, shared](uint8_t, uint16_t, uint8_t, std::error_code ec, std::vector<uint8_t> data) {
            Defer([this, id, shared, ec, data] { FinishProgram(id, shared->handle, *shared, ec, &data); });
          },
          left, ec);
    }, ec);
  } else {
    Submit([&] {
      SubmitWrite(
          exec_, node, shared->req.index, shared->req.subindex, std::vector<uint8_t>(shared->data),
          [this, id, shared](uint8_t, uint16_t, uint8_t, std::error_code ec) {
            Defer([this, id, shared, ec] { FinishProgram(id, shared->handle, *shared, ec, nullptr); });
          },
          left, ec);
    }, ec);
  }
  if (ec == SdoErrc::NO_SDO) {
    // The master is booting the node after all: try again on the next tick.
    ProgJob p;
    p.job = std::move(*shared);
    p.resolved = true;
    prog_[id].push_front(std::move(p));
    return;
  }
  if (n) {
    n->sdo_busy = true;
    n->last_prog = true;
  } else {
    prog_foreign_busy_.insert(id);
    ++foreign_sdo_[id];
  }
  if (ec) Defer([this, id, handle, shared, ec] { FinishProgram(id, handle, *shared, ec, nullptr); });
}

void Network::FinishProgram(unsigned id, uint32_t handle, const PlcRequests::Job& job, std::error_code ec,
                            const std::vector<uint8_t>* data) {
  auto node = nodes_.find(id);
  if (node != nodes_.end()) {
    node->second.sdo_busy = false;
  } else {
    prog_foreign_busy_.erase(id);
    ReleaseForeignSdo(id);
  }
  if (stopped_) {
    // Cancelled because the session ends (CancelPrograms): not the node's doing.
    EndProgram(id, handle, CANOPEN_PLC_ERR_CANCELLED, 0, nullptr, 0);
    return;
  }
  const canopen_plc_request& r = job.req;
  uint32_t key = object_key(id, r.index, r.subindex);
  if (!ec) {
    // A success clears what was logged for this object.
    auto lo = prog_aborts_logged_.lower_bound(uint64_t(key) << 32);
    auto hi = prog_aborts_logged_.upper_bound(uint64_t(key) << 32 | 0xFFFFFFFFu);
    prog_aborts_logged_.erase(lo, hi);
    EndProgram(id, handle, 0, 0, data ? data->data() : nullptr, data ? data->size() : 0);
    return;
  }
  uint16_t err = CANOPEN_PLC_ERR_ABORT;
  uint32_t abort = kAbortGeneral;
  if (ec == SdoErrc::TIMEOUT) {
    err = CANOPEN_PLC_ERR_TIMEOUT;
    abort = kAbortTimeout;
  } else if (ec.category() == lely::canopen::SdoCategory()) {
    abort = static_cast<uint32_t>(ec.value());
  }
  if (prog_aborts_logged_.size() < 256 && prog_aborts_logged_.insert(uint64_t(key) << 32 | abort).second) {
    std::string who = node != nodes_.end() ? node->second.cfg->label() : "node " + std::to_string(id);
    if (err == CANOPEN_PLC_ERR_TIMEOUT)
      log_warn("%s: PLC program %sSDO %s of 0x%04X sub %u timed out (no answer, abort code 0x%08X)", who.c_str(),
               kind_name(r.kind), r.write ? "write" : "read", r.index, r.subindex, abort);
    else
      log_warn("%s: PLC program %sSDO %s of 0x%04X sub %u aborted, abort code 0x%08X (%s)", who.c_str(),
               kind_name(r.kind), r.write ? "write" : "read", r.index, r.subindex, abort, ec.message().c_str());
  }
  EndProgram(id, handle, err, abort, nullptr, 0);
}

void Network::CancelPrograms() {
  std::vector<unsigned> ids(prog_foreign_busy_.begin(), prog_foreign_busy_.end());
  for (auto& n : nodes_)
    if (n.second.sdo_busy && n.second.last_prog) ids.push_back(n.first);
  if (ids.empty()) return;
  log_info("CANopen stops: %zu PLC program SDO transfer%s in progress cancelled", ids.size(),
           ids.size() == 1 ? "" : "s");
  std::lock_guard<lely::util::BasicLockable> lock(*this);
  for (unsigned id : ids) CancelSdo(static_cast<uint8_t>(id));
}

void Network::EndProgram(unsigned, uint32_t handle, uint16_t error_id, uint32_t abort, const uint8_t* data,
                         size_t size) {
  PlcRequests::instance().finish(handle, error_id, abort, data, size);
}

}  // namespace canopen_plugin
