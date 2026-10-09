// network_lss.cpp - LSS (CiA 305): node IDs by device identity.
//
// At every reset communication of the master, before any slave boots, Lely
// calls LssAssigner::OnStart(); the Network then gives each node with
// lss.assign its node ID (canopen-master-bringup spec). A node with
// lss.assign that does not answer gets the same assignment again before its
// boot retries. Diagnostics clients can find, inquire and configure devices
// (canopen-online-diagnostics spec). One LSS sequence runs at a time
// (lss_busy_), and every sequence leaves all devices in the LSS waiting
// state. Runs on the bus thread like the rest of Network.

#include <algorithm>

#include "network.h"

#include "cJSON.h"
#include "log.h"

namespace canopen_plugin {

using lely::canopen::LssAddress;
using lely::canopen::LssState;

namespace {

// NMT state codes as in network.cpp.
constexpr uint8_t kStateNoContact = 0;
constexpr uint8_t kStateStopped = 4;

std::string hex32(uint32_t v) {
  char buf[16];
  std::snprintf(buf, sizeof buf, "0x%08X", v);
  return buf;
}

std::string address_text(const NodeConfig& c) {
  std::string s = "vendor ID " + hex32(c.eds_vendor_id) + ", product code " + hex32(c.eds_product_code) +
                  ", serial number " + hex32(c.serial_number);
  if (c.revision_number) s += ", revision number " + hex32(c.revision_number);
  return s;
}

std::string address_text(const uint32_t a[4]) {
  return "vendor ID " + hex32(a[0]) + ", product code " + hex32(a[1]) + ", revision number " + hex32(a[2]) +
         ", serial number " + hex32(a[3]);
}

// Why an LSS request failed, in words.
std::string lss_error_text(std::error_code ec) {
  if (ec == std::errc::timed_out) return "no answer";
  if (ec == std::errc::result_out_of_range) return "node ID out of range for the device";
  if (ec == std::errc::invalid_argument) return "bit rate not supported by the device";
  if (ec == std::errc::protocol_error) return "refused by the device";
  if (ec == std::errc::operation_not_permitted) return "LSS is not running on the master";
  return ec.message();
}

void add_address(cJSON* o, const uint32_t a[4]) {
  static const char* const kKey[] = {"vendor_id", "product_code", "revision_number", "serial_number"};
  for (int f = 0; f < 4; ++f) cJSON_AddNumberToObject(o, kKey[f], a[f]);
}

}  // namespace

LssAssigner::LssAssigner(ev_exec_t* exec, Network& net) : LssMaster(exec, net), net_(net) {}

void LssAssigner::OnStart(std::function<void(std::error_code ec)> res) noexcept { net_.LssOnStart(std::move(res)); }

// ---------------------------------------------------------------------------
// Assignment

void Network::LssOnStart(std::function<void(std::error_code)> res) {
  auto job = std::make_shared<LssJob>();
  for (const auto& it : nodes_)
    if (it.second.cfg->lss_assign) job->ids.push_back(it.first);
  if (job->ids.empty() || stopped_) {
    res({});
    return;
  }
  // The master's own start-up waits for this; a diagnostics sequence that
  // happens to run is left to finish first by Lely's request queue.
  lss_busy_ = true;
  job->done = [res] { res({}); };
  LssRun(job);
}

void Network::LssRun(std::shared_ptr<LssJob> job) {
  if (stopped_) return;
  if (job->next >= job->ids.size()) {
    lss_busy_ = false;
    if (job->done) job->done();
    return;
  }
  unsigned id = job->ids[job->next];
  NodeState& n = nodes_[id];
  const NodeConfig& c = *n.cfg;
  n.lss_running = true;
  auto found = [this, job, id](std::error_code ec) {
    if (stopped_) return;
    if (ec) {
      NodeState& n = nodes_[id];
      if (ec == std::errc::timed_out)
        log_warn("%s: no device with %s answered LSS", n.cfg->label().c_str(), address_text(*n.cfg).c_str());
      else
        log_warn("%s: LSS search failed: %s", n.cfg->label().c_str(), lss_error_text(ec).c_str());
      LssJobNext(job);
      return;
    }
    LssFound(job, id);
  };
  // Revision unknown: the EDS's revision first (one frame), then a binary
  // search over it with the rest fixed (each step nobody answers costs one
  // LSS timeout).
  auto search = [this, &c, found]() {
    LssAddress lo(c.eds_vendor_id, c.eds_product_code, 0, c.serial_number);
    LssAddress hi(c.eds_vendor_id, c.eds_product_code, 0xFFFFFFFFu, c.serial_number);
    lss_->SubmitSlowscan(exec_, lo, hi, [found](std::error_code ec, const LssAddress&) { found(ec); });
  };
  try {
    uint32_t rev = c.revision_number ? c.revision_number : c.eds_revision_number;
    LssAddress a(c.eds_vendor_id, c.eds_product_code, rev, c.serial_number);
    if (c.revision_number) {
      lss_->SubmitSwitchSelective(exec_, a, found);
    } else {
      lss_->SubmitSwitchSelective(exec_, a, [this, found, search](std::error_code ec) {
        if (stopped_) return;
        if (ec != std::errc::timed_out) {
          found(ec);
          return;
        }
        try {
          search();
        } catch (const std::exception&) {
          found(ec);
        }
      });
    }
  } catch (const std::exception& e) {
    log_error("%s: cannot start LSS: %s", c.label().c_str(), e.what());
    LssJobNext(job);
  }
}

// The device is in LSS configuration state: inquire its node ID, set it when
// it differs, store it when asked.
void Network::LssFound(std::shared_ptr<LssJob> job, unsigned id) {
  lss_->SubmitGetId(exec_, [this, job, id](std::error_code ec, uint8_t prev) {
    if (stopped_) return;
    NodeState& n = nodes_[id];
    std::string label = n.cfg->label();
    if (ec) {
      log_warn("%s: LSS inquire node ID failed: %s", label.c_str(), lss_error_text(ec).c_str());
      LssJobNext(job);
      return;
    }
    if (prev == id) {
      log_info("%s: LSS: the device already has node ID %u", label.c_str(), id);
      LssJobNext(job);
      return;
    }
    lss_->SubmitSetId(exec_, static_cast<uint8_t>(id), [this, job, id, prev, label](std::error_code ec) {
      if (stopped_) return;
      if (ec) {
        log_error("%s: LSS: the device refused node ID %u (%s)", label.c_str(), id, lss_error_text(ec).c_str());
        LssJobNext(job);
        return;
      }
      std::string was = prev == 0xFF ? std::string("none") : std::to_string(prev);
      if (job->retry && prev != 0xFF)
        log_warn("%s: LSS assigned node ID %u; the device keeps node ID %u until it is reset or power-cycled",
                 label.c_str(), id, prev);
      else
        log_info("%s: LSS assigned node ID %u (previous: %s)", label.c_str(), id, was.c_str());
      if (!nodes_[id].cfg->lss_store) {
        LssJobNext(job);
        return;
      }
      lss_->SubmitStore(exec_, [this, job, id, label](std::error_code ec) {
        if (stopped_) return;
        if (ec)
          log_warn("%s: LSS store configuration refused (%s); the device loses node ID %u at power-off",
                   label.c_str(), lss_error_text(ec).c_str(), id);
        else
          log_info("%s: LSS stored node ID %u in the device", label.c_str(), id);
        LssJobNext(job);
      });
    });
  });
}

// Back to the LSS waiting state (a device that had no node ID starts with
// its new one), then the next node.
void Network::LssJobNext(std::shared_ptr<LssJob> job) {
  nodes_[job->ids[job->next]].lss_running = false;
  ++job->next;
  try {
    lss_->SubmitSwitch(exec_, LssState::WAITING, [this, job](std::error_code) {
      if (!stopped_) LssRun(job);
    });
  } catch (const std::exception& e) {
    log_error("LSS: cannot switch devices to the waiting state: %s", e.what());
    LssRun(job);
  }
}

// From the supervision tick: a node with lss.assign that does not answer
// (lost, or never there) gets the assignment again before its boot retry.
void Network::LssRecover(clock::time_point now) {
  if (!lss_ || lss_busy_ || master_state_ == kStateStopped) return;
  for (auto& it : nodes_) {
    NodeState& n = it.second;
    if (!n.cfg->lss_assign || n.up || n.lss_running || now < n.lss_next) continue;
    if (image_.node_state(it.first) != kStateNoContact) continue;
    bool due = n.retry_pending ? now >= n.next_retry : (!n.booted && n.warned_absent);
    if (!due) continue;
    n.lss_next = now + n.lss_backoff;
    n.lss_backoff = std::min(n.lss_backoff * 2, kRetryMax);
    auto job = std::make_shared<LssJob>();
    job->ids.push_back(it.first);
    job->retry = true;
    lss_busy_ = true;
    LssRun(job);
    return;  // one at a time
  }
}

// ---------------------------------------------------------------------------
// Diagnostics

void Network::LssDiagDone(uint64_t seq, const std::string& line) {
  lss_busy_ = false;
  if (diag_) diag_->answer(seq, line);
}

void Network::DiagLss(const DiagRequest& r) {
  if (r.op == "lss_find" || r.op == "lss_find_status") {
    DiagLssFind(r, r.op == "lss_find");
    return;
  }
  if (!lss_) {
    diag_->answer(r.seq, diag_error(r.id, "LSS is not available (diagnostics changes are not allowed)"));
    return;
  }
  if (lss_busy_) {
    diag_->answer(r.seq, diag_error(r.id, "LSS busy"));
    return;
  }
  if (r.op == "lss_set_id") {
    auto it = nodes_.find(r.node);
    if (it != nodes_.end() && it->second.booted) {
      diag_->answer(r.seq, diag_error(r.id, "node ID " + std::to_string(r.node) + " is in use by " +
                                                it->second.cfg->label() + ", which is booted"));
      return;
    }
  }
  lss_busy_ = true;
  uint32_t a[4] = {r.lss[0], r.lss[1], r.lss[2], r.lss[3]};
  std::string addr = address_text(a);
  uint64_t seq = r.seq;
  std::string rid = r.id;
  DiagRequest req = r;
  // Ends every sequence: devices back to waiting, then the answer.
  auto finish = [this, seq](std::string line) {
    try {
      lss_->SubmitSwitch(exec_, LssState::WAITING, [this, seq, line](std::error_code) { LssDiagDone(seq, line); });
    } catch (const std::exception&) {
      LssDiagDone(seq, line);
    }
  };
  auto fail = [finish, rid](const std::string& what, std::error_code ec) {
    finish(diag_error(rid, what + ": " + lss_error_text(ec)));
  };
  auto selected = [this, req, addr, finish, fail, rid](std::error_code ec) {
    if (stopped_) return;
    if (ec) {
      if (ec == std::errc::timed_out)
        finish(diag_error(rid, "not found: no device with " + addr + " answered"));
      else
        fail("LSS switch selective failed", ec);
      return;
    }
    lss_->SubmitGetId(exec_, [this, req, addr, finish, fail, rid](std::error_code ec, uint8_t prev) {
      if (stopped_) return;
      if (ec) {
        fail("LSS inquire node ID failed", ec);
        return;
      }
      if (req.op == "lss_inquire") {
        cJSON* res = cJSON_CreateObject();
        cJSON_AddNumberToObject(res, "node_id", prev);
        cJSON_AddBoolToObject(res, "configured", prev != 0xFF);
        log_info("LSS inquire of %s by diagnostics client %s: node ID %u", addr.c_str(), req.peer.c_str(), prev);
        finish(diag_ok(rid, res));
        return;
      }
      // What happens after the set, and the store when asked.
      auto stored = [this, req, finish, fail, rid](cJSON* res, const std::string& logged) {
        if (!req.store) {
          cJSON_AddBoolToObject(res, "stored", false);
          log_info("%s by diagnostics client %s (not stored)", logged.c_str(), req.peer.c_str());
          finish(diag_ok(rid, res));
          return;
        }
        lss_->SubmitStore(exec_, [this, req, finish, fail, rid, res, logged](std::error_code ec) {
          if (stopped_) {
            cJSON_Delete(res);
            return;
          }
          if (ec) {
            cJSON_Delete(res);
            log_warn("%s by diagnostics client %s; store refused: %s", logged.c_str(), req.peer.c_str(),
                     lss_error_text(ec).c_str());
            fail("set, but LSS store configuration failed", ec);
            return;
          }
          cJSON_AddBoolToObject(res, "stored", true);
          log_info("%s by diagnostics client %s, stored in the device", logged.c_str(), req.peer.c_str());
          finish(diag_ok(rid, res));
        });
      };
      if (req.op == "lss_set_id") {
        lss_->SubmitSetId(exec_, static_cast<uint8_t>(req.node),
                          [this, req, addr, prev, stored, fail](std::error_code ec) {
                            if (stopped_) return;
                            if (ec) {
                              log_warn("LSS set node ID %u on %s for diagnostics client %s: %s", req.node,
                                       addr.c_str(), req.peer.c_str(), lss_error_text(ec).c_str());
                              fail("LSS configure node-ID failed", ec);
                              return;
                            }
                            cJSON* res = cJSON_CreateObject();
                            cJSON_AddNumberToObject(res, "node_id", req.node);
                            cJSON_AddNumberToObject(res, "previous_node_id", prev);
                            bool had = prev != 0xFF;
                            cJSON_AddBoolToObject(res, "had_node_id", had);
                            cJSON_AddStringToObject(
                                res, "note",
                                had ? "the device had another node ID; the new one becomes active after its next "
                                      "communication reset or power cycle"
                                    : "the device had no node ID and starts with the new one now");
                            stored(res, "LSS set node ID " + std::to_string(req.node) + " (previous " +
                                            (had ? std::to_string(prev) : std::string("none")) + ") on " + addr);
                          });
      } else {  // lss_set_bitrate
        lss_->SubmitSetBitrate(exec_, static_cast<int>(req.bitrate_kbit) * 1000,
                               [this, req, addr, stored, fail](std::error_code ec) {
                                 if (stopped_) return;
                                 if (ec) {
                                   log_warn("LSS set bit rate %u kbit/s on %s for diagnostics client %s: %s",
                                            req.bitrate_kbit, addr.c_str(), req.peer.c_str(),
                                            lss_error_text(ec).c_str());
                                   fail("LSS configure bit timing failed", ec);
                                   return;
                                 }
                                 cJSON* res = cJSON_CreateObject();
                                 cJSON_AddNumberToObject(res, "bitrate_kbit", req.bitrate_kbit);
                                 cJSON_AddStringToObject(
                                     res, "note",
                                     "the device uses the new bit rate after its next power cycle; change "
                                     "adapter.bitrate to match");
                                 stored(res, "LSS set bit rate " + std::to_string(req.bitrate_kbit) +
                                                 " kbit/s on " + addr);
                               });
      }
    });
  };
  try {
    lss_->SubmitSwitchSelective(exec_, LssAddress(a[0], a[1], a[2], a[3]), selected);
  } catch (const std::exception& e) {
    LssDiagDone(seq, diag_error(rid, std::string("cannot start LSS: ") + e.what()));
  }
}

void Network::DiagLssFind(const DiagRequest& r, bool start) {
  if (start && !lss_find_running_) {
    if (!lss_) {
      diag_->answer(r.seq, diag_error(r.id, "LSS is not available (diagnostics changes are not allowed)"));
      return;
    }
    if (lss_busy_) {
      diag_->answer(r.seq, diag_error(r.id, "LSS busy"));
      return;
    }
    lss_busy_ = true;
    lss_find_running_ = true;
    lss_find_found_ = false;
    lss_find_node_id_ = -1;
    lss_find_error_.clear();
    lss_find_started_ = clock::now();
    log_info("LSS search for a device without node ID started by diagnostics client %s", r.peer.c_str());
    LssAddress addr, mask;
    if (r.lss_known) {
      addr.vendor_id = r.lss[0];
      addr.product_code = r.lss[1];
      mask.vendor_id = 0xFFFFFFFFu;
      mask.product_code = 0xFFFFFFFFu;
    }
    auto end = [this](bool found, const std::string& error) {
      lss_find_found_ = found;
      lss_find_error_ = error;
      lss_find_seconds_ = std::chrono::duration<double>(clock::now() - lss_find_started_).count();
      auto done = [this] {
        lss_find_running_ = false;
        lss_find_have_ = true;
        lss_busy_ = false;
        if (lss_find_found_)
          log_info("LSS search found %s (node ID %s) in %.1f s", address_text(lss_find_addr_).c_str(),
                   lss_find_node_id_ < 0 || lss_find_node_id_ == 0xFF ? "none"
                                                                       : std::to_string(lss_find_node_id_).c_str(),
                   lss_find_seconds_);
        else
          log_info("LSS search ended: %s", lss_find_error_.empty() ? "none found" : lss_find_error_.c_str());
      };
      try {
        lss_->SubmitSwitch(exec_, LssState::WAITING, [done](std::error_code) { done(); });
      } catch (const std::exception&) {
        done();
      }
    };
    try {
      lss_->SubmitFastscan(exec_, addr, mask, [this, end](std::error_code ec, const LssAddress& a) {
        if (stopped_) return;
        if (ec) {
          end(false, ec == std::errc::timed_out ? "" : lss_error_text(ec));
          return;
        }
        lss_find_addr_[0] = a.vendor_id;
        lss_find_addr_[1] = a.product_code;
        lss_find_addr_[2] = a.revision;
        lss_find_addr_[3] = a.serial_nr;
        // The found device is in configuration state: read its node ID.
        lss_->SubmitGetId(exec_, [this, end](std::error_code ec, uint8_t id) {
          if (stopped_) return;
          lss_find_node_id_ = ec ? -1 : id;
          end(true, "");
        });
      });
    } catch (const std::exception& e) {
      lss_busy_ = false;
      lss_find_running_ = false;
      diag_->answer(r.seq, diag_error(r.id, std::string("cannot start LSS: ") + e.what()));
      return;
    }
  }
  cJSON* res = cJSON_CreateObject();
  cJSON_AddBoolToObject(res, "running", lss_find_running_);
  if (lss_find_running_)
    cJSON_AddNumberToObject(
        res, "seconds", std::chrono::duration<double>(clock::now() - lss_find_started_).count());
  if (!lss_find_running_ && lss_find_have_) {
    cJSON_AddNumberToObject(res, "seconds", lss_find_seconds_);
    cJSON_AddBoolToObject(res, "found", lss_find_found_);
    if (!lss_find_error_.empty()) cJSON_AddStringToObject(res, "error", lss_find_error_.c_str());
    if (lss_find_found_) {
      cJSON* dev = cJSON_AddObjectToObject(res, "device");
      add_address(dev, lss_find_addr_);
      if (lss_find_node_id_ >= 0) cJSON_AddNumberToObject(dev, "node_id", lss_find_node_id_);
    }
  }
  diag_->answer(r.seq, diag_ok(r.id, res));
}

}  // namespace canopen_plugin
