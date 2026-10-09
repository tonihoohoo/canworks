// network_diag.cpp - the Network's side of the diagnostics channel (spec
// canopen-online-diagnostics): live status, EMCY history, manual SDO and NMT,
// and the network scan. Runs on the bus thread like the rest of Network;
// requests arrive through DiagHub on the request timer.

#include <algorithm>
#include <ctime>

#include "network.h"

#include <lely/coapp/sdo_error.hpp>

#include "cJSON.h"
#include "eds_check.h"
#include "log.h"

// From <lely/co/nmt.h>, which does not mix with the C++ headers.
extern "C" const char* co_nmt_es2str(char es);

namespace canopen_plugin {

using lely::canopen::NmtCommand;
using lely::canopen::SdoErrc;

namespace {

std::string iso_time(std::chrono::system_clock::time_point t) {
  auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(t.time_since_epoch()).count();
  std::time_t secs = static_cast<std::time_t>(ms / 1000);
  std::tm tm{};
  gmtime_r(&secs, &tm);
  char buf[64];
  std::snprintf(buf, sizeof buf, "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ", tm.tm_year + 1900, tm.tm_mon + 1, tm.tm_mday,
                tm.tm_hour, tm.tm_min, tm.tm_sec, static_cast<int>(ms % 1000));
  return buf;
}

std::string hex32(uint32_t v) {
  char buf[16];
  std::snprintf(buf, sizeof buf, "0x%08X", v);
  return buf;
}

const char* hold_name(uint8_t hold) { return hold == 1 ? "stopped" : hold == 2 ? "preop" : "none"; }

// The text of a request that ended with `ec`: "timeout", the abort code's
// meaning, or the error.
std::string sdo_error_text(std::error_code ec) {
  if (ec == SdoErrc::TIMEOUT) return "timeout";
  return ec.message();
}

bool is_abort(std::error_code ec) { return ec.category() == lely::canopen::SdoCategory() && ec != SdoErrc::TIMEOUT; }

}  // namespace

void Network::ServiceDiag() {
  if (!diag_ || stopped_) return;
  std::vector<DiagRequest> reqs;
  diag_->take(reqs);
  auto now = clock::now();
  // For the guards of hand-sent frames and bit rate detection (diag.h).
  std::string operational;
  for (const auto& it : nodes_)
    if (image_.node_state(it.first) == 5) {
      operational = it.second.cfg->label();
      break;
    }
  diag_->set_operational(operational);
  for (auto& r : reqs) {
    if (r.op == "status") {
      DiagStatus(r);
    } else if (r.op == "emcy") {
      DiagEmcy(r);
    } else if (r.op == "nmt") {
      DiagNmt(r);
    } else if (r.op == "scan" || r.op == "scan_status") {
      DiagScan(r, r.op == "scan");
    } else if (r.op.compare(0, 4, "lss_") == 0) {
      DiagLss(r);
    } else if (r.op.compare(0, 4, "sim_") == 0) {
      if (!sim_handler_) {
        diag_->answer(r.seq, diag_error(r.id, "nothing simulated"));
        continue;
      }
      cJSON* req = cJSON_Parse(r.raw.c_str());
      std::string line = req ? sim_handler_(req, r.id, r.peer) : diag_error(r.id, "not a JSON object");
      cJSON_Delete(req);
      // The engine answers without the line end the diagnostics protocol needs.
      if (line.empty() || line.back() != '\n') line += '\n';
      diag_->answer(r.seq, line);
    } else if (r.op == "sdo_read" || r.op == "sdo_write") {
      ManualSdo m;
      m.deadline = now + std::chrono::milliseconds(r.timeout_ms);
      if (r.op == "sdo_write")
        log_info("node %u: SDO write to 0x%04X sub %u (%zu bytes: %s) from diagnostics client %s", r.node, r.index,
                 r.subindex, r.data.size(), hex_bytes(r.data).c_str(), r.peer.c_str());
      m.req = std::move(r);
      manual_.push_back(std::move(m));
    } else {
      diag_->answer(r.seq, diag_error(r.id, "unknown op"));
    }
  }
  // Manual transfers that wait for their node (it is booting).
  for (size_t i = 0; i < manual_.size();) {
    ManualSdo& m = manual_[i];
    if (!m.in_flight && now >= m.deadline) {
      diag_->answer(m.req.seq, diag_error(m.req.id, "timeout (the node is booting)"));
      manual_.erase(manual_.begin() + static_cast<long>(i));
      continue;
    }
    if (!m.in_flight) StartManual(m);
    ++i;
  }
  // The scan keeps up to kScanParallel node IDs in progress.
  if (scan_running_) {
    while (scan_active_ < kScanParallel && scan_next_ < scan_.size()) {
      ScanEntry& e = scan_[scan_next_++];
      ++scan_active_;
      ScanNext(e);
    }
    if (scan_active_ == 0 && scan_next_ >= scan_.size()) FinishScan();
  }
}

// ---------------------------------------------------------------------------
// Status and EMCY history

void Network::DiagStatus(const DiagRequest& r) {
  cJSON* res = cJSON_CreateObject();
  cJSON_AddStringToObject(res, "version", diag_->version().c_str());
  cJSON_AddNumberToObject(res, "uptime_s", diag_->uptime_s());
  cJSON_AddStringToObject(res, "config_sha256", cfg_.file_sha256.c_str());
  cJSON_AddStringToObject(res, "network", cfg_.network.c_str());
  diag_add_protocols(res);
  cJSON_AddBoolToObject(res, "session", true);
  cJSON* m = cJSON_AddObjectToObject(res, "master");
  cJSON_AddNumberToObject(m, "node_id", cfg_.master.node_id);
  cJSON_AddNumberToObject(m, "state", master_state_);
  cJSON_AddBoolToObject(res, "simulated_network", cfg_.adapter.simulate);
  cJSON_AddBoolToObject(res, "simulation_forced", cfg_.adapter.simulation_forced);
  cJSON* b = cJSON_AddObjectToObject(res, "bus");
  cJSON_AddStringToObject(b, "interface", cfg_.adapter.simulate ? "simulated" : cfg_.adapter.interface.c_str());
  cJSON_AddNumberToObject(b, "state", image_.bus_state());
  cJSON_AddNumberToObject(b, "tx_errors", image_.bus_tx_errors());
  cJSON_AddNumberToObject(b, "rx_errors", image_.bus_rx_errors());
  cJSON_AddNumberToObject(b, "bus_off_count", image_.bus_off_count());
  const MasterConfig& mc = cfg_.master;
  cJSON* sy = cJSON_AddObjectToObject(res, "sync");
  cJSON_AddStringToObject(sy, "source", mc.sync_plc_cycle ? "plc_cycle" : mc.sync_period_us ? "timer" : "none");
  if (mc.sync_plc_cycle) cJSON_AddNumberToObject(sy, "cycles", mc.sync_cycles);
  if (mc.sync_period_us) cJSON_AddNumberToObject(sy, "period_us", mc.sync_period_us);
  const SyncStats& ss = sync_stats_;
  cJSON_AddNumberToObject(sy, "count", static_cast<double>(ss.count));
  cJSON_AddNumberToObject(sy, "last_us", static_cast<double>(ss.last_us));
  cJSON_AddNumberToObject(sy, "min_us", static_cast<double>(ss.min_us));
  cJSON_AddNumberToObject(sy, "max_us", static_cast<double>(ss.max_us));
  cJSON_AddNumberToObject(sy, "skipped", static_cast<double>(ss.skipped));
  cJSON_AddNumberToObject(sy, "late_pdos", static_cast<double>(ss.late));
  cJSON* nodes = cJSON_AddArrayToObject(res, "nodes");
  const auto& vars = image_.sdo_vars();
  for (const auto& it : nodes_) {
    unsigned id = it.first;
    const NodeState& n = it.second;
    cJSON* o = cJSON_CreateObject();
    cJSON_AddNumberToObject(o, "node_id", id);
    cJSON_AddStringToObject(o, "name", n.cfg->name.c_str());
    cJSON_AddNumberToObject(o, "state", image_.node_state(id));
    cJSON_AddBoolToObject(o, "status", n.up);
    cJSON_AddBoolToObject(o, "booted", n.booted);
    const bool conflict = sim_conflicts_.count(id) > 0;
    cJSON_AddBoolToObject(o, "simulated", n.cfg->simulate && !conflict);
    cJSON_AddBoolToObject(o, "sim_conflict", conflict);
    if (n.cfg->interpolation_write_us)
      cJSON_AddNumberToObject(o, "interpolation_period_us", n.cfg->interpolation_write_us);
    uint8_t letter = image_.node_boot_error(id);
    if (letter) {
      char es[2] = {static_cast<char>(letter), 0};
      cJSON_AddStringToObject(o, "boot_error", es);
      std::string text = n.boot_what.empty() ? co_nmt_es2str(static_cast<char>(letter)) : n.boot_what;
      cJSON_AddStringToObject(o, "boot_error_text", text.c_str());
    } else {
      cJSON_AddNullToObject(o, "boot_error");
    }
    cJSON_AddBoolToObject(o, "retry_pending", n.retry_pending);
    uint8_t hold = n.hold == Hold::Stopped ? 1 : n.hold == Hold::Preop ? 2 : 0;
    cJSON_AddStringToObject(o, "hold", hold_name(hold));
    if (hold)
      cJSON_AddStringToObject(o, "hold_by", n.hold_by_operator ? "operator" : "program");
    else
      cJSON_AddNullToObject(o, "hold_by");
    cJSON* e = cJSON_AddObjectToObject(o, "emcy");
    cJSON_AddNumberToObject(e, "code", image_.node_emcy_code(id));
    cJSON_AddNumberToObject(e, "error_register", image_.node_error_register(id));
    cJSON_AddNumberToObject(e, "count", static_cast<double>(n.emcy_total));
    cJSON* pt = cJSON_AddArrayToObject(o, "pdo_timeouts");
    auto now = clock::now();
    for (const auto& ip : in_pdos_) {
      const InputPdo& p = ip.second;
      if (p.node_id != id || !p.timeout_ms) continue;
      cJSON* t = cJSON_CreateObject();
      cJSON_AddNumberToObject(t, "tpdo", p.pdo);
      cJSON_AddNumberToObject(t, "timeout_ms", p.timeout_ms);
      cJSON_AddBoolToObject(t, "timed_out", p.timed_out);
      cJSON_AddNumberToObject(t, "count", static_cast<double>(p.timeouts));
      if (p.last_rx == clock::time_point{})
        cJSON_AddNullToObject(t, "since_ms");
      else
        cJSON_AddNumberToObject(
            t, "since_ms",
            static_cast<double>(std::chrono::duration_cast<std::chrono::milliseconds>(now - p.last_rx).count()));
      cJSON_AddItemToArray(pt, t);
    }
    cJSON* sv = cJSON_AddArrayToObject(o, "sdo_variables");
    for (size_t k : n.vars) {
      const SdoVariable& var = vars[k].var;
      cJSON* v = cJSON_CreateObject();
      cJSON_AddStringToObject(v, "name", var.label().c_str());
      cJSON_AddNumberToObject(v, "index", var.index);
      cJSON_AddNumberToObject(v, "subindex", var.subindex);
      cJSON_AddStringToObject(v, "type", co_type_name(var.type));
      cJSON_AddStringToObject(v, "direction", var.is_read() ? "read" : "write");
      // Raw bits, as the PLC sees them (write entries: the value last
      // written); a string keeps 64-bit values exact.
      uint64_t raw = var.is_read() ? image_.sdo_value(k) : vars_[k].last_written;
      cJSON_AddStringToObject(v, "raw", std::to_string(raw).c_str());
      cJSON_AddNumberToObject(v, "status", image_.sdo_status(k));
      cJSON_AddNumberToObject(v, "abort_code", image_.sdo_abort(k));
      cJSON_AddItemToArray(sv, v);
    }
    cJSON_AddItemToArray(nodes, o);
  }
  diag_->add_tx_status(res);
  diag_->answer(r.seq, diag_ok(r.id, res));
}

void Network::DiagEmcy(const DiagRequest& r) {
  auto it = nodes_.find(r.node);
  if (it == nodes_.end()) {
    diag_->answer(r.seq, diag_error(r.id, "node " + std::to_string(r.node) + " is not in the configuration"));
    return;
  }
  const NodeState& n = it->second;
  cJSON* res = cJSON_CreateObject();
  cJSON_AddNumberToObject(res, "node_id", r.node);
  cJSON* list = cJSON_AddArrayToObject(res, "emcy");
  for (size_t i = 0; i < n.emcy_n; ++i) {
    const NodeState::Emcy& e = n.emcy_hist[(n.emcy_head + kEmcyHistory - 1 - i) % kEmcyHistory];
    cJSON* o = cJSON_CreateObject();
    cJSON_AddStringToObject(o, "time", iso_time(e.time).c_str());
    cJSON_AddNumberToObject(o, "code", e.code);
    cJSON_AddNumberToObject(o, "error_register", e.er);
    std::vector<uint8_t> msef(e.msef.begin(), e.msef.end());
    cJSON_AddStringToObject(o, "manufacturer", hex_bytes(msef).c_str());
    cJSON_AddItemToArray(list, o);
  }
  diag_->answer(r.seq, diag_ok(r.id, res));
}

// ---------------------------------------------------------------------------
// Manual NMT

void Network::DiagNmt(const DiagRequest& r) {
  auto it = nodes_.find(r.node);
  if (it == nodes_.end()) {
    diag_->answer(r.seq, diag_error(r.id, "node " + std::to_string(r.node) + " is not in the configuration"));
    return;
  }
  NodeState& n = it->second;
  unsigned id = r.node;
  std::string by = "diagnostics client " + r.peer;
  cJSON* res = cJSON_CreateObject();
  if (r.command == "stop" || r.command == "preop") {
    n.hold = r.command == "stop" ? Hold::Stopped : Hold::Preop;
    n.hold_by_operator = true;
    if (n.cfg->boot && !n.booted) {
      log_info("%s: NMT %s requested by %s; sent when the node has booted", n.cfg->label().c_str(),
               r.command == "stop" ? "STOP" : "ENTER PRE-OPERATIONAL", by.c_str());
      cJSON_AddStringToObject(res, "note", "the node has not booted; the hold applies once it has");
    } else {
      log_info("%s: NMT %s requested by %s", n.cfg->label().c_str(),
               r.command == "stop" ? "STOP" : "ENTER PRE-OPERATIONAL", by.c_str());
      SendHold(id, n);
    }
  } else if (r.command == "start") {
    n.hold = Hold::None;
    n.hold_by_operator = false;
    if (n.booted || !n.cfg->boot) {
      log_info("%s: NMT START (from %s)", n.cfg->label().c_str(), by.c_str());
      Command(NmtCommand::START, static_cast<uint8_t>(id));
    } else {
      log_info("%s: hold released by %s; the node has not booted, so the master starts it when it has",
               n.cfg->label().c_str(), by.c_str());
      cJSON_AddStringToObject(res, "note", "the node has not booted; the master starts it when it has");
    }
  } else {
    ResetNode(id, n, r.command == "reset-comm", by.c_str());
  }
  diag_->answer(r.seq, diag_ok(r.id, res));
}

// ---------------------------------------------------------------------------
// Manual SDO

void Network::ReleaseForeignSdo(unsigned id) {
  auto it = foreign_sdo_.find(id);
  if (it == foreign_sdo_.end()) return;
  if (--it->second) return;
  foreign_sdo_.erase(it);
  // The default Client-SDO Lely made for an unconfigured node is not needed
  // any more.
  std::lock_guard<lely::util::BasicLockable> lock(*this);
  CancelSdo(static_cast<uint8_t>(id));
}

void Network::StartManual(ManualSdo& m) {
  const DiagRequest& r = m.req;
  uint64_t seq = r.seq;
  uint8_t node = static_cast<uint8_t>(r.node);
  std::chrono::milliseconds timeout(r.timeout_ms);
  std::error_code ec;
  if (r.op == "sdo_read") {
    Submit([&] {
      SubmitRead<std::vector<uint8_t>>(
          exec_, node, r.index, r.subindex,
          [this, seq](uint8_t, uint16_t, uint8_t, std::error_code ec, std::vector<uint8_t> data) {
            Defer([this, seq, ec, data] { FinishManual(seq, ec, &data); });
          },
          timeout, ec);
    }, ec);
  } else {
    Submit([&] {
      SubmitWrite(
          exec_, node, r.index, r.subindex, std::vector<uint8_t>(r.data),
          [this, seq](uint8_t, uint16_t, uint8_t, std::error_code ec) {
            Defer([this, seq, ec] { FinishManual(seq, ec, nullptr); });
          },
          timeout, ec);
    }, ec);
  }
  if (ec == SdoErrc::NO_SDO) return;  // the master is booting the node: try again
  m.in_flight = true;
  if (!nodes_.count(r.node)) ++foreign_sdo_[r.node];
  if (ec) {
    std::error_code e = ec;
    Defer([this, seq, e] { FinishManual(seq, e, nullptr); });
  }
}

void Network::FinishManual(uint64_t seq, std::error_code ec, const std::vector<uint8_t>* data) {
  auto it = std::find_if(manual_.begin(), manual_.end(), [seq](const ManualSdo& m) { return m.req.seq == seq; });
  if (it == manual_.end()) return;
  DiagRequest r = std::move(it->req);
  manual_.erase(it);
  if (!nodes_.count(r.node)) ReleaseForeignSdo(r.node);
  if (!diag_) return;
  bool write = r.op == "sdo_write";
  if (!ec && data && data->size() > kDiagMaxSdoBytes) {
    diag_->answer(seq, diag_error(r.id, "the object holds " + std::to_string(data->size()) + " bytes, more than the " +
                                            std::to_string(kDiagMaxSdoBytes) + " a manual read returns"));
    return;
  }
  cJSON* res = cJSON_CreateObject();
  cJSON_AddNumberToObject(res, "node", r.node);
  cJSON_AddNumberToObject(res, "index", r.index);
  cJSON_AddNumberToObject(res, "subindex", r.subindex);
  if (!ec) {
    cJSON_AddBoolToObject(res, "success", true);
    if (data) {
      cJSON_AddStringToObject(res, "data", hex_bytes(*data).c_str());
      cJSON_AddNumberToObject(res, "size", static_cast<double>(data->size()));
    }
    if (write) log_info("node %u: SDO write to 0x%04X sub %u done", r.node, r.index, r.subindex);
  } else {
    cJSON_AddBoolToObject(res, "success", false);
    if (is_abort(ec)) {
      cJSON_AddNumberToObject(res, "abort_code", static_cast<uint32_t>(ec.value()));
      cJSON_AddStringToObject(res, "abort_code_hex", hex32(static_cast<uint32_t>(ec.value())).c_str());
    }
    cJSON_AddStringToObject(res, "error", sdo_error_text(ec).c_str());
    if (write)
      log_warn("node %u: SDO write to 0x%04X sub %u from diagnostics client %s failed: %s", r.node, r.index,
               r.subindex, r.peer.c_str(), sdo_error_text(ec).c_str());
  }
  diag_->answer(seq, diag_ok(r.id, res));
}

// ---------------------------------------------------------------------------
// Network scan

void Network::DiagScan(const DiagRequest& r, bool start) {
  if (start && !scan_running_) {
    if (master_state_ != 127 && master_state_ != 5) {  // PRE-OPERATIONAL, OPERATIONAL
      diag_->answer(r.seq, diag_error(r.id, "the master is not PRE-OPERATIONAL or OPERATIONAL; no SDO is possible"));
      return;
    }
    scan_.clear();
    for (unsigned id = 1; id <= 127; ++id)
      if (id != cfg_.master.node_id) {
        ScanEntry e;
        e.id = id;
        scan_.push_back(e);
      }
    scan_next_ = 0;
    scan_active_ = 0;
    scan_running_ = true;
    scan_started_ = clock::now();
    log_info("network scan of node IDs 1-127 started by diagnostics client %s", r.peer.c_str());
  }
  cJSON* res = cJSON_CreateObject();
  size_t done = 0;
  for (const auto& e : scan_)
    if (e.phase == ScanEntry::Done) ++done;
  cJSON_AddBoolToObject(res, "running", scan_running_);
  cJSON_AddNumberToObject(res, "done", static_cast<double>(done));
  cJSON_AddNumberToObject(res, "total", static_cast<double>(scan_running_ || scan_have_result_ ? scan_.size() : 0));
  if (!scan_running_ && scan_have_result_) {
    cJSON_AddStringToObject(res, "finished_at", iso_time(scan_finished_at_).c_str());
    cJSON_AddNumberToObject(res, "seconds", scan_seconds_);
    cJSON_AddStringToObject(res, "note", "devices in STOPPED do not answer SDO and are not found");
    cJSON* list = cJSON_AddArrayToObject(res, "nodes");
    static const char* const kField[] = {"vendor ID", "product code", "revision number", "serial number"};
    static const char* const kKey[] = {"vendor_id", "product_code", "revision_number", "serial_number",
                                       "device_type"};
    for (const auto& e : scan_) {
      auto nit = nodes_.find(e.id);
      bool cfgd = nit != nodes_.end();
      if (!e.answered && !e.booting && !cfgd) continue;
      cJSON* o = cJSON_CreateObject();
      cJSON_AddNumberToObject(o, "node_id", e.id);
      for (int f = 0; f < 5; ++f)
        if (e.has[f]) cJSON_AddNumberToObject(o, kKey[f], e.values[f]);
      if (e.has_name) cJSON_AddStringToObject(o, "device_name", e.name.c_str());
      std::string match;
      std::string differs;
      if (cfgd) cJSON_AddStringToObject(o, "name", nit->second.cfg->name.c_str());
      if (e.booting) {
        match = "booting";
      } else if (!e.answered) {
        match = "configured, no answer";
      } else if (!cfgd) {
        match = "not configured";
      } else {
        // Expected identity: the values the master checks (0x1F85-0x1F88,
        // from the configuration), else the EDS [DeviceInfo].
        const NodeConfig& nc = *nit->second.cfg;
        uint32_t expect[4] = {};
        bool known[4] = {};
        for (int f = 0; f < 4; ++f) {
          std::error_code ec;
          uint32_t v = (*this)[static_cast<uint16_t>(0x1F85 + f)][static_cast<uint8_t>(e.id)].Read<uint32_t>(ec);
          if (!ec && v) expect[f] = v, known[f] = true;
        }
        if (!known[2] && nc.has_revision_number && nc.revision_number)
          expect[2] = nc.revision_number, known[2] = true;
        if (!known[3] && nc.has_serial_number) expect[3] = nc.serial_number, known[3] = true;
        if (!known[0] || !known[1]) {
          uint32_t vend = 0, prod = 0;
          if (eds_identity(nc, vend, prod)) {
            if (!known[0] && vend) expect[0] = vend, known[0] = true;
            if (!known[1] && prod) expect[1] = prod, known[1] = true;
          }
        }
        for (int f = 0; f < 4 && differs.empty(); ++f)
          if (known[f] && e.has[f] && e.values[f] != expect[f])
            differs = std::string(kField[f]) + " " + hex32(e.values[f]) + ", expected " + hex32(expect[f]);
        match = differs.empty() ? "configured" : "configured, different device";
      }
      cJSON_AddStringToObject(o, "match", match.c_str());
      if (!differs.empty()) cJSON_AddStringToObject(o, "differs", differs.c_str());
      cJSON_AddItemToArray(list, o);
    }
  }
  diag_->answer(r.seq, diag_ok(r.id, res));
}

void Network::ScanNext(ScanEntry& e) {
  // Step 0 probes 0x1018 sub 1; steps 1-4 read 0x1018 sub 2-4 and 0x1000;
  // step 5 reads 0x1008.
  unsigned id = e.id;
  uint8_t node = static_cast<uint8_t>(id);
  std::error_code ec;
  if (e.step == 0) e.phase = ScanEntry::Probing;
  if (e.step <= 4) {
    uint16_t idx = e.step == 4 ? 0x1000 : 0x1018;
    uint8_t sub = e.step == 4 ? 0 : static_cast<uint8_t>(e.step + 1);
    auto timeout = e.step == 0 ? kScanProbeTimeout : kScanReadTimeout;
    Submit([&] {
      SubmitRead<uint32_t>(
          exec_, node, idx, sub,
          [this, id](uint8_t, uint16_t, uint8_t, std::error_code ec, uint32_t value) {
            Defer([this, id, ec, value] { ScanStep(id, ec, value, nullptr); });
          },
          timeout, ec);
    }, ec);
  } else {
    Submit([&] {
      SubmitRead<std::vector<uint8_t>>(
          exec_, node, 0x1008, 0,
          [this, id](uint8_t, uint16_t, uint8_t, std::error_code ec, std::vector<uint8_t> data) {
            Defer([this, id, ec, data] { ScanStep(id, ec, 0, &data); });
          },
          kScanReadTimeout, ec);
    }, ec);
  }
  if (!ec) {
    if (!nodes_.count(id)) ++foreign_sdo_[id];
    return;
  }
  // Not submitted: the master boots this node right now, or no SDO at all.
  if (e.step == 0) e.booting = ec == SdoErrc::NO_SDO;
  e.phase = ScanEntry::Done;
  --scan_active_;
}

void Network::ScanStep(unsigned id, std::error_code ec, uint32_t value, const std::vector<uint8_t>* data) {
  // Release this transfer's Client-SDO only after the next one was
  // submitted, so an unconfigured node keeps one SDO client for all reads.
  struct Release {
    Network* net;
    unsigned id;
    ~Release() {
      if (!net->nodes_.count(id)) net->ReleaseForeignSdo(id);
    }
  } release{this, id};
  auto it = std::find_if(scan_.begin(), scan_.end(), [id](const ScanEntry& e) { return e.id == id; });
  if (!scan_running_ || it == scan_.end()) return;
  ScanEntry& e = *it;
  if (e.step == 0) {
    if (ec) {
      e.phase = ScanEntry::Done;
      --scan_active_;
      return;
    }
    e.answered = true;
    e.phase = ScanEntry::Reading;
  }
  if (!ec) {
    if (data) {
      e.name.assign(data->begin(), data->end());
      while (!e.name.empty() && e.name.back() == '\0') e.name.pop_back();
      e.has_name = true;
    } else {
      // Steps 0-3: 0x1018 sub 1-4; step 4: 0x1000.
      e.values[e.step] = value;
      e.has[e.step] = true;
    }
  }
  if (++e.step > 5) {
    e.phase = ScanEntry::Done;
    --scan_active_;
    return;
  }
  ScanNext(e);
}

void Network::FinishScan() {
  scan_running_ = false;
  scan_have_result_ = true;
  scan_finished_at_ = std::chrono::system_clock::now();
  scan_seconds_ = std::chrono::duration<double>(clock::now() - scan_started_).count();
  unsigned found = 0;
  for (const auto& e : scan_) found += e.answered;
  log_info("network scan done in %.1f s: %u device%s answered", scan_seconds_, found, found == 1 ? "" : "s");
}

}  // namespace canopen_plugin
