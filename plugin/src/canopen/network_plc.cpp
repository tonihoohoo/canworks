// network_plc.cpp - the Network's side of the PLC program's SDO function
// blocks (spec canopen-plc-sdo). Requests arrive through PlcRequests on the
// request timer; each node's program transfers run oldest first, one at a
// time per node, taking turns with the node's SDO variables.

#include <algorithm>
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
  // NMT requests first: their own slots, so queued SDO transfers never delay them.
  ServiceNmtProgram();
  if (uint32_t v = api.take_unknown_version())
    log_warn("the PLC program's CANopen library asks for SDO block API version %u, this plugin offers version %u; "
             "update the plugin (install-stock.sh) or use the library that comes with it",
             v, CANOPEN_PLC_API_VERSION);
  api.expire(now);
  prog_taken_.clear();
  api.take(cfg_.network_index, prog_taken_);
  for (auto& j : prog_taken_) {
    ProgJob p;
    p.job = std::move(j);
    p.limit = p.job.deadline + kAbsentAfter;
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
      if (n && !SdoAvailable(id, *n)) {
        // Being configured after its boot-up message, in a boot retry, or not
        // heard from yet since the master started (its first boot is still
        // to come): wait, and start TIMEOUT only once the node can be asked,
        // so a read at startup works with the default timeout. The wait
        // ends with the boot: the node comes up, or it is reported absent
        // and the request ends here with ERROR_ID 3. Lost, not booted or
        // STOPPED: not available.
        // A boot that ended with an error other than no answer (a wrong
        // device, a refused download): not available, at once.
        bool first_boot = !n->warned_absent && now - started_ < kAbsentAfter;
        uint8_t boot_error = image_.node_boot_error(id);
        bool booting = n->cfg->boot && !n->booted && (!boot_error || boot_error == 'B') &&
                       (image_.node_state(id) == kStatePreop || n->boot_waiting || first_boot);
        if (!booting) {
          EndProgram(id, p.job.handle, CANOPEN_PLC_ERR_UNAVAILABLE, 0, nullptr, 0);
          q.pop_front();
          continue;
        }
        // The wait never goes past TIMEOUT plus kAbsentAfter from the start.
        if (now >= p.limit) {
          EndProgram(id, p.job.handle, CANOPEN_PLC_ERR_TIMEOUT, kAbortTimeout, nullptr, 0);
          q.pop_front();
          continue;
        }
        auto from_now = now + std::chrono::milliseconds(p.job.req.timeout_ms);
        if (p.job.deadline < from_now) p.job.deadline = std::min(from_now, p.limit);
        break;
      }
      if (now >= p.job.deadline) {
        EndProgram(id, p.job.handle, CANOPEN_PLC_ERR_TIMEOUT, kAbortTimeout, nullptr, 0);
        q.pop_front();
        continue;
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

// ---------------------------------------------------------------------------
// NMT function blocks (spec canopen-plc-nmt)

namespace {

const char* cs_name(uint8_t cs) {
  switch (cs) {
    case CANOPEN_PLC_NMT_CS_START: return "START";
    case CANOPEN_PLC_NMT_CS_STOP: return "STOP";
    case CANOPEN_PLC_NMT_CS_PREOP: return "ENTER PRE-OPERATIONAL";
    case CANOPEN_PLC_NMT_CS_RESET_NODE: return "RESET NODE";
    default: return "RESET COMMUNICATION";
  }
}

constexpr uint8_t kMasterOperational = 5;
constexpr uint8_t kMasterStopped = 4;

}  // namespace

void Network::ServiceNmtProgram() {
  PlcRequests& api = PlcRequests::instance();
  if (uint32_t v = api.take_unknown_nmt_version())
    log_warn("the PLC program's CANopen library asks for NMT block API version %u, this plugin offers version %u; "
             "the program's library needs a newer plugin (install-stock.sh), or use the library that comes with it",
             v, CANOPEN_PLC_NMT_API_VERSION);
  nmt_taken_.clear();
  api.take_nmt(cfg_.network_index, nmt_taken_);
  for (const auto& j : nmt_taken_) {
    switch (j.req.op) {
      case CANOPEN_PLC_NMT_NODE: api.finish_nmt(j.handle, ProgramNmt(j.req)); break;
      case CANOPEN_PLC_NMT_START: ProgramStart(j.handle, j.req); break;
      case CANOPEN_PLC_NMT_STOP: api.finish_nmt(j.handle, ProgramStop(j.req)); break;
      default: api.finish_nmt(j.handle, CANOPEN_PLC_ERR_INPUT); break;
    }
  }
  // CO_NETWORK_START requests waiting for the master (their TIMEOUT runs in
  // PlcRequests::poll_nmt; a request that timed out is no longer there).
  if (prog_start_waits_.empty()) return;
  if (master_state_ == kMasterOperational || master_state_ == kMasterStopped) {
    uint16_t err = master_state_ == kMasterOperational ? 0 : CANOPEN_PLC_ERR_REFUSED;
    for (uint32_t h : prog_start_waits_) api.finish_nmt(h, err);
    prog_start_waits_.clear();
  }
}

uint16_t Network::ProgramNmt(const canopen_plc_nmt_request& r) {
  static const std::string by = "the program (CO_NMT)";
  const uint8_t cs = r.command;
  if (r.node == 0) {
    // One broadcast (node ID 0) reaches every node, the unlisted ones too;
    // the holds and resets of the configured nodes are kept by hand. Lely
    // sends it without applying it to the master itself (checked by
    // sim_lely_broadcast_command_and_master).
    if (cs == CANOPEN_PLC_NMT_CS_START)
      for (const auto& it : nodes_)
        if (it.second.hold != Hold::None && it.second.hold_src == HoldSource::Gateway) {
          log_warn("NMT START to all nodes from the program (CO_NMT) refused: the gateway holds %s STOPPED while "
                   "the upper master is lost",
                   it.second.cfg->label().c_str());
          return CANOPEN_PLC_ERR_REFUSED;
        }
    for (auto& it : nodes_) NodeCommand(it.first, it.second, cs, HoldSource::Block, by, false);
    log_info("NMT %s to all nodes (node ID 0, from the program, CO_NMT)", cs_name(cs));
    Command(static_cast<lely::canopen::NmtCommand>(cs), 0);
    return 0;
  }
  auto it = nodes_.find(r.node);
  if (it == nodes_.end()) {
    // Not in the configuration: sent, and nothing kept (the program owns
    // that node's NMT state).
    log_info("node %u (not in the configuration): NMT %s (from the program, CO_NMT)", r.node, cs_name(cs));
    // Lely sends it and keeps nothing for a node outside 0x1F81 (checked by
    // sim_lely_command_unlisted_node).
    Command(static_cast<lely::canopen::NmtCommand>(cs), r.node);
    return 0;
  }
  NodeState& n = it->second;
  if (cs == CANOPEN_PLC_NMT_CS_START && n.hold != Hold::None && n.hold_src == HoldSource::Gateway) {
    log_warn("%s: NMT START from the program (CO_NMT) refused: the gateway holds the node STOPPED while the upper "
             "master is lost, and starts it when the upper master is back",
             n.cfg->label().c_str());
    return CANOPEN_PLC_ERR_REFUSED;
  }
  NodeCommand(r.node, n, cs, HoldSource::Block, by);
  return 0;
}

void Network::ProgramStart(uint32_t handle, const canopen_plc_nmt_request&) {
  PlcRequests& api = PlcRequests::instance();
  if (master_state_ == kMasterStopped) {
    // The configuration's safety reaction to a lost mandatory node.
    log_error("CO_NETWORK_START refused: the master is STOPPED after a mandatory node was lost "
              "(master.stop_all_nodes); the plugin must restart (stop and start the PLC)");
    api.finish_nmt(handle, CANOPEN_PLC_ERR_REFUSED);
    return;
  }
  bool was_running = MayRun();
  bool was_stopped = prog_stopped_;
  prog_start_ = true;
  prog_stopped_ = false;
  PublishMaster();
  // A master the network stop held while Lely kept it OPERATIONAL runs again.
  if (was_stopped) ApplyMasterState(false);
  if (was_stopped) {
    // Nodes the network stop held start again (not those with a hold of
    // their own, nor any when the master may not start nodes).
    unsigned started = 0;
    for (auto& it : nodes_) {
      NodeState& n = it.second;
      if (n.hold == Hold::None || n.hold_src != HoldSource::Network) continue;
      SetHold(it.first, n, Hold::None, HoldSource::Network);
      if (!cfg_.master.start_nodes || !(n.booted || !n.cfg->boot)) continue;
      Command(lely::canopen::NmtCommand::START, static_cast<uint8_t>(it.first));
      ++started;
    }
    log_info("the PLC program starts the network (CO_NETWORK_START)%s", started ? "; NMT START to the nodes the "
             "network stop held" : "");
  } else if (!was_running) {
    log_info("the PLC program starts the network (CO_NETWORK_START)");
  }
  if (master_state_ == kMasterOperational) {
    api.finish_nmt(handle, 0);
    return;
  }
  prog_start_waits_.push_back(handle);
  for (const auto& it : nodes_)
    if (it.second.cfg->mandatory && !it.second.booted) {
      log_info("CO_NETWORK_START: the master goes OPERATIONAL once every mandatory node has booted (%s has not)",
               it.second.cfg->label().c_str());
      break;
    }
  StartHeldMaster();
}

uint16_t Network::ProgramStop(const canopen_plc_nmt_request& r) {
  if (master_state_ == kMasterStopped) {
    log_warn("CO_NETWORK_STOP refused: the master is STOPPED after a mandatory node was lost (master.stop_all_nodes)");
    return CANOPEN_PLC_ERR_REFUSED;
  }
  uint8_t mode = r.command;
  if (mode == CANOPEN_PLC_NMT_NODES_DEFAULT) {
    switch (cfg_.master.on_plc_stop) {
      case OnPlcStop::Preop: mode = CANOPEN_PLC_NMT_CS_PREOP; break;
      case OnPlcStop::Stop: mode = CANOPEN_PLC_NMT_CS_STOP; break;
      case OnPlcStop::Keep: mode = CANOPEN_PLC_NMT_NODES_NONE; break;
    }
  }
  // No output PDO from here on: the master TPDOs off first (they come back
  // per node once the master runs again and the node is up). The master
  // then reads PRE-OPERATIONAL; Lely's own master stays as it is, since
  // Lely restarts its network start-up (a reset communication of every
  // node) whenever its master enters PRE-OPERATIONAL (design.md, task 1).
  for (auto& it : nodes_) EnableTpdos(it.second, false);
  std::vector<unsigned> up;
  for (const auto& it : nodes_)
    if (it.second.up || it.second.node_op) up.push_back(it.first);
  prog_stopped_ = true;
  PublishMaster();
  ApplyMasterState(false);
  unsigned sent = 0;
  if (mode != CANOPEN_PLC_NMT_NODES_NONE) {
    Hold h = mode == CANOPEN_PLC_NMT_CS_STOP ? Hold::Stopped : Hold::Preop;
    // Every configured node without a hold of its own is held, so a node
    // that boots while the network is stopped gets the command too.
    for (auto& it : nodes_) {
      NodeState& n = it.second;
      if (n.hold != Hold::None && n.hold_src != HoldSource::Network) continue;
      SetHold(it.first, n, h, HoldSource::Network);
      if (std::find(up.begin(), up.end(), it.first) == up.end()) continue;
      SendHold(it.first, n);
      ++sent;
    }
  }
  log_info("the PLC program stops the network (CO_NETWORK_STOP): master PRE-OPERATIONAL, %s%s",
           mode == CANOPEN_PLC_NMT_NODES_NONE ? "the nodes keep their state"
           : mode == CANOPEN_PLC_NMT_CS_STOP  ? "NMT STOP to "
                                              : "NMT ENTER PRE-OPERATIONAL to ",
           mode == CANOPEN_PLC_NMT_NODES_NONE ? ""
           : (std::to_string(sent) + (sent == 1 ? " node" : " nodes")).c_str());
  return 0;
}

}  // namespace canopen_plugin
