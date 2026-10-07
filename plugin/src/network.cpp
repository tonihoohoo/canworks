#include "network.h"

#include <algorithm>
#include <cstring>
#include <mutex>
#include <unistd.h>

#include <lely/can/msg.h>
#include <lely/ev/exec.hpp>

// <lely/can/net.h> clashes with the C++ headers; only this is needed.
extern "C" int can_net_send(__can_net* net, const can_msg* msg);

#include "log.h"

// From <lely/co/nmt.h> (C header): sends the synchronous TPDOs and actuates
// the synchronous RPDOs after a SYNC, then calls the SYNC indication (OnSync).
extern "C" void co_nmt_on_sync(__co_nmt* nmt, uint8_t cnt);

namespace canopen_plugin {

using lely::canopen::NmtCommand;
using lely::canopen::NmtState;

constexpr std::chrono::milliseconds Network::kTick;
constexpr std::chrono::milliseconds Network::kRetryMin;
constexpr std::chrono::milliseconds Network::kRetryMax;
constexpr std::chrono::seconds Network::kSyncWarnPeriod;
constexpr std::chrono::milliseconds Network::kAbsentAfter;
constexpr std::chrono::milliseconds Network::kNoAnswerAfter;
constexpr unsigned Network::kLoggedEmcyPerSecond;
constexpr std::chrono::milliseconds Network::kRequestPeriod;
constexpr std::chrono::milliseconds Network::kOutputPeriod;
constexpr size_t Network::kEmcyHistory;
constexpr unsigned Network::kScanParallel;
constexpr std::chrono::milliseconds Network::kScanProbeTimeout;
constexpr std::chrono::milliseconds Network::kScanReadTimeout;

namespace {

std::string master_bin(const GeneratedConfig& gen) {
  std::string bin = gen.work_dir + "/master.bin";
  return access(bin.c_str(), R_OK) == 0 ? bin : "";
}

const char* state_name(NmtState st) {
  switch (st) {
    case NmtState::BOOTUP: return "BOOT-UP";
    case NmtState::STOP: return "STOPPED";
    case NmtState::START: return "OPERATIONAL";
    case NmtState::RESET_NODE: return "RESET NODE";
    case NmtState::RESET_COMM: return "RESET COMMUNICATION";
    case NmtState::PREOP: return "PRE-OPERATIONAL";
    default: return "UNKNOWN";
  }
}

// Values of the node state byte (state_location): CiA 301 NMT state codes,
// with 0 for a node the master has no contact with.
constexpr uint8_t kStateNoContact = 0;
constexpr uint8_t kStateStopped = 4;
constexpr uint8_t kStateOperational = 5;
constexpr uint8_t kStatePreop = 127;

// A boot-up message puts the node in PRE-OPERATIONAL right away, so it reads
// 127; a BOOTUP state that comes from no message at all (a boot that got no
// answer) reads as no contact.
uint8_t state_code(NmtState st, bool from_message) {
  switch (st) {
    case NmtState::STOP: return kStateStopped;
    case NmtState::START: return kStateOperational;
    case NmtState::PREOP: return kStatePreop;
    case NmtState::BOOTUP: return from_message ? kStatePreop : kStateNoContact;
    default: return kStateNoContact;  // resetting
  }
}

// The CiA 301 error class of an emergency error code, in words.
const char* emcy_class(uint16_t eec) {
  if (eec == 0) return "error reset";
  switch (eec >> 8) {
    case 0x81: return "communication";
    case 0x82: return "protocol";
    case 0xFF: return "device specific";
  }
  switch (eec >> 12) {
    case 0x1: return "generic";
    case 0x2: return "current";
    case 0x3: return "voltage";
    case 0x4: return "temperature";
    case 0x5: return "device hardware";
    case 0x6: return "device software";
    case 0x7: return "additional modules";
    case 0x8: return "monitoring";
    case 0x9: return "external error";
    case 0xF: return "additional functions";
    default: return "unknown class";
  }
}

}  // namespace

void encode_time_of_day(int64_t unix_ms, uint8_t out[6]) {
  constexpr int64_t kDay = 86400000;
  constexpr int64_t kDays1970To1984 = 5113;
  int64_t days = unix_ms / kDay, ms = unix_ms % kDay;
  if (ms < 0) ms += kDay, --days;
  days -= kDays1970To1984;
  if (days < 0) days = 0, ms = 0;
  uint32_t m = static_cast<uint32_t>(ms) & 0x0FFFFFFFu;
  uint16_t d = static_cast<uint16_t>(days);
  for (int b = 0; b < 4; ++b) out[b] = static_cast<uint8_t>(m >> (8 * b));
  out[4] = static_cast<uint8_t>(d);
  out[5] = static_cast<uint8_t>(d >> 8);
}

Network::Network(ev_exec_t* exec, lely::io::TimerBase& timer, lely::io::TimerBase& sup_timer,
                 lely::io::CanChannelBase& chan, const Config& cfg, const GeneratedConfig& gen,
                 ProcessImage& image, std::function<bool()> tick, lely::io::TimerBase* req_timer,
                 lely::io::TimerBase* out_timer)
    : BasicMaster(exec, timer, chan, gen.master_dcf, master_bin(gen), cfg.master.node_id),
      cfg_(cfg),
      gen_(gen),
      image_(image),
      sup_timer_(sup_timer),
      exec_(exec),
      tick_(std::move(tick)),
      tick_wait_(exec, [this](int, std::error_code ec) {
        if (!ec) OnTick();
      }),
      req_timer_(req_timer),
      req_wait_(exec, [this](int, std::error_code ec) {
        if (ec || stopped_) return;
        ServiceDiag();
        ServiceRequests();
        req_timer_->submit_wait(req_wait_);
      }),
      out_timer_(out_timer),
      out_wait_(exec, [this](int, std::error_code ec) {
        if (ec || stopped_) return;
        // Only when the scan published new outputs; WriteOutputs sends the
        // event-driven PDOs whose data changed.
        bool fresh = false;
        image_.latest_outputs(&fresh);
        if (fresh) WriteOutputs();
        out_timer_->submit_wait(out_wait_);
      }) {
  for (const auto& n : cfg.nodes) {
    NodeState& s = nodes_[n.node_id];
    s.cfg = &n;
    auto it = gen.slave_sdos.find(n.node_id);
    s.sdos = it != gen.slave_sdos.end() ? &it->second : nullptr;
  }
  const auto& in = image_.inputs();
  for (size_t i = 0; i < in.size(); ++i) nodes_[in[i].node_id].inputs.push_back(i);
  last_out_.assign(image_.outputs().size(), 0);
  const auto& vars = image_.sdo_vars();
  vars_.assign(vars.size(), VarState());
  for (size_t k = 0; k < vars.size(); ++k) nodes_[vars[k].node_id].vars.push_back(k);
  has_requests_ = !vars.empty();
  for (const auto& n : cfg.nodes) has_requests_ |= n.has_nmt_command_location;
  // Lely's NMT boot steps and the configuration downloads below (which pass
  // no timeout) use this; Lely's own default is 100 ms.
  SetTimeout(std::chrono::milliseconds(cfg.master.sdo_timeout_ms));
  // LSS only when a node is assigned by it or diagnostics may change things;
  // otherwise Lely's start-up runs without the LSS step and sends no LSS frame.
  bool lss = cfg.master.has_diagnostics && cfg.master.diag_allow_changes;
  for (const auto& n : cfg.nodes) lss |= n.lss_assign;
  if (lss) lss_.reset(new LssAssigner(exec, *this));
}

Network::~Network() {
  if (lss_) lss_->AbortAll();
  sup_timer_.cancel_wait(tick_wait_);
  if (req_timer_) req_timer_->cancel_wait(req_wait_);
  if (out_timer_) out_timer_->cancel_wait(out_wait_);
  // Program transfers this session took never finish now.
  PlcRequests::instance().cancel_taken(cfg_.network_index);
}

void Network::Start() {
  // Reset() runs the master's own NMT reset synchronously, which restores its
  // object dictionary from the DCF; the TPDOs are switched off after that and
  // only switched on for nodes that are operational.
  Reset();
  MapTpdos();
  MapSyncRpdos();
  sync_seen_ = image_.sync_requests();
  for (const auto& t : tpdo_cob_) {
    std::error_code ec;
    (*this)[0x1800 + t.first - 1][1].Write<uint32_t>(t.second | 0x80000000u, ec);
  }
  started_ = clock::now();
  if (cfg_.master.time_period_ms) {
    char now[32];
    std::time_t t = std::time(nullptr);
    std::strftime(now, sizeof now, "%Y-%m-%d %H:%M:%S UTC", std::gmtime(&t));
    log_info("producing TIME on COB-ID 0x%03X every %u ms (host clock now %s)", cfg_.master.time_producer_cob_id(),
             cfg_.master.time_period_ms, now);
    SendTime();
  }
  sup_timer_.settime(kTick, kTick);
  sup_timer_.submit_wait(tick_wait_);
  // Always: the program's SDO function blocks may start transfers any time.
  if (req_timer_) {
    req_timer_->settime(kRequestPeriod, kRequestPeriod);
    req_timer_->submit_wait(req_wait_);
  }
  // No SYNC: outputs no longer wait for OnSync.
  if (out_timer_ && !cfg_.master.produces_sync()) {
    out_timer_->settime(kOutputPeriod, kOutputPeriod);
    out_timer_->submit_wait(out_wait_);
  }
}

void Network::SendTime() {
  auto period = std::chrono::milliseconds(cfg_.master.time_period_ms);
  auto now = clock::now();
  // Keep the period's phase; after a long stall start again from now.
  next_time_ = next_time_ + period > now ? next_time_ + period : now + period;
  timespec ts{};
  clock_gettime(CLOCK_REALTIME, &ts);
  can_msg msg = CAN_MSG_INIT;
  uint32_t cob = cfg_.master.time_producer_cob_id();
  if (cob > 0x7FF) {
    msg.id = cob & CAN_MASK_EID;
    msg.flags |= CAN_FLAG_IDE;
  } else {
    msg.id = cob;
  }
  msg.len = 6;
  encode_time_of_day(static_cast<int64_t>(ts.tv_sec) * 1000 + ts.tv_nsec / 1000000, msg.data);
  std::lock_guard<lely::util::BasicLockable> lock(*this);
  can_net_send(net(), &msg);
}

void Network::Stop() {
  if (stopped_) return;
  stopped_ = true;
  if (lss_) lss_->CancelAll();
  CancelPrograms();
}

void Network::MapTpdos() {
  tpdo_cob_.clear();
  tpdo_event_.clear();
  for (auto& n : nodes_) n.second.tpdos.clear();
  for (unsigned num = 1; num <= 512; ++num) {
    std::error_code ec;
    uint32_t cob = (*this)[0x1800 + num - 1][1].Read<uint32_t>(ec);
    if (ec) continue;
    cob &= 0x1FFFFFFFu & ~0x20000000u;  // strip the valid/RTR/frame bits
    cob &= 0x7FF;
    tpdo_cob_[num] = cob;
    uint8_t trans = (*this)[0x1800 + num - 1][2].Read<uint8_t>(ec);
    if (!ec && trans >= 254) tpdo_event_.insert(num);
    for (auto& n : nodes_)
      for (const auto& p : n.second.cfg->rx_pdos)
        if (n.second.cfg->rpdo_cob_id(p) == cob) n.second.tpdos.push_back(num);
  }
}

void Network::EnableTpdos(const NodeState& n, bool enable) {
  for (unsigned num : n.tpdos) {
    std::error_code ec;
    uint32_t cob = tpdo_cob_[num];
    (*this)[0x1800 + num - 1][1].Write<uint32_t>(enable ? cob : (cob | 0x80000000u), ec);
    if (ec)
      log_error("node %u: cannot %s master TPDO %u: %s", n.cfg->node_id, enable ? "enable" : "disable",
                num, ec.message().c_str());
  }
  // Lely rebuilds its table of TPDO-mapped objects (used by TpdoWrite) only
  // on an NMT command, from the TPDOs valid at that moment; a master that
  // starts after its nodes came up would otherwise keep a table without them.
  if (!n.tpdos.empty()) {
    std::lock_guard<lely::util::BasicLockable> lock(*this);
    UpdateTpdoMapping();
  }
}

bool Network::IsOperational(unsigned id) const {
  auto it = nodes_.find(id);
  return it != nodes_.end() && it->second.up;
}

void Network::SetUp(unsigned id, bool up, const char* why) {
  auto it = nodes_.find(id);
  if (it == nodes_.end()) return;
  NodeState& n = it->second;
  if (n.up == up) return;
  n.up = up;
  if (up) n.warned_absent = false;
  image_.set_node_status(id, up);
  image_.commit_inputs();
  EnableTpdos(n, up);
  if (up)
    log_info("%s is operational", n.cfg->label().c_str());
  else
    log_warn("%s is not operational: %s", n.cfg->label().c_str(), why);
}

void Network::Update(unsigned id, const char* why) {
  auto it = nodes_.find(id);
  if (it == nodes_.end()) return;
  const NodeState& n = it->second;
  // PDOs flow only while both the node and the master are OPERATIONAL. A node
  // with boot: false is never configured by the master, so its own state
  // decides.
  bool ready = n.cfg->boot ? n.booted : true;
  SetUp(id, ready && n.node_op && master_op_, why);
}

void Network::SetBootError(unsigned id, uint8_t letter) {
  if (image_.node_boot_error(id) == letter) return;
  image_.set_node_boot_error(id, letter);
  image_.commit_inputs();
}

void Network::SetMasterState(uint8_t state) {
  master_state_ = state;
  if (image_.master_state() == state) return;
  image_.set_master_state(state);
  image_.commit_inputs();
}

void Network::MarkAllDown() {
  master_op_ = false;
  master_state_ = kStateNoContact;
  image_.set_master_state(kStateNoContact);
  for (auto& n : nodes_) {
    n.second.up = false;
    n.second.booted = false;
    n.second.node_op = false;
    image_.set_node_status(n.first, false);
    image_.set_node_state(n.first, kStateNoContact);
  }
  image_.commit_inputs();
}

void Network::SetState(unsigned id, uint8_t state) {
  if (gw_) gw_->set_node_state(cfg_.network_index, id, state);
  if (image_.node_state(id) == state) return;
  image_.set_node_state(id, state);
  image_.commit_inputs();
}

void Network::ScheduleRetry(NodeState& n, bool quiet) {
  // A boot: false node is not the master's to boot; a STOPPED master boots
  // nothing until the plugin restarts.
  if (n.retry_pending || stopped_ || !n.cfg->boot || master_state_ == kStateStopped) return;
  n.retry_pending = true;
  n.next_retry = clock::now() + n.backoff;
  if (!quiet) log_info("%s: retrying boot in %lld ms", n.cfg->label().c_str(), (long long)n.backoff.count());
  n.backoff = std::min(n.backoff * 2, kRetryMax);
}

void Network::OnTick() {
  if (stopped_) return;
  if (tick_ && !tick_()) {
    Stop();
    return;
  }
  if (!req_timer_) {
    ServiceDiag();
    ServiceRequests();
  }
  auto now = clock::now();
  if (cfg_.master.time_period_ms && now >= next_time_) SendTime();
  LssRecover(now);
  for (auto& it : nodes_) {
    NodeState& n = it.second;
    FlushEmcySummary(n, now, false);
    // Lely keeps re-trying the boot of a silent slave by itself (every second,
    // CiA 302 error status B) without reporting it, so say so once.
    if (n.cfg->boot && !n.up && !n.booted && !n.warned_absent && now - started_ >= kAbsentAfter) {
      n.warned_absent = true;
      SetBootError(it.first, 'B');
      if (n.cfg->mandatory && !master_op_)
        log_error("%s is mandatory and not answering: the master holds the whole network in PRE-OPERATIONAL "
                  "(no PDOs for any node) until it boots",
                  n.cfg->label().c_str());
      else
        log_warn("%s is not answering; its inputs stay at their last values (zero if it never came up) and the master keeps trying to boot it",
                 n.cfg->label().c_str());
    }
    // While Lely boots a node it ignores its heartbeat, so a node that stops
    // answering during a boot retry is never reported lost: clear its state.
    if (n.boot_waiting && now - n.boot_since >= kNoAnswerAfter) {
      n.boot_waiting = false;
      SetState(it.first, kStateNoContact);
      SetBootError(it.first, 'B');
    }
    // An LSS assignment for this node runs first (network_lss.cpp).
    if (n.lss_running) continue;
    if (!n.retry_pending || n.up || now < n.next_retry || master_state_ == kStateStopped) continue;
    if (n.reset_on_retry) {
      // The node is running without our configuration (it started itself, or
      // it refused a download, which many devices do for some objects while
      // OPERATIONAL): reset it; its boot-up message makes the master boot and
      // configure it again from PRE-OPERATIONAL.
      n.reset_on_retry = false;
      n.retry_pending = false;
      Command(NmtCommand::RESET_NODE, static_cast<uint8_t>(it.first));
      SetState(it.first, kStateNoContact);  // until its boot-up message
      ScheduleRetry(n);
    } else if (Boot(static_cast<uint8_t>(it.first))) {
      n.retry_pending = false;
      n.boot_waiting = true;
      n.boot_since = now;
    } else {
      n.next_retry = now + kRetryMin;  // boot already in progress
    }
  }
  sup_timer_.submit_wait(tick_wait_);
}

// Lely invokes the On*() callbacks with the master's mutex held, and every
// BasicMaster call takes that mutex again. So each callback only posts its
// work to the executor, where it runs outside the lock.
void Network::OnBoot(uint8_t id, NmtState st, char es, const std::string& what) noexcept {
  BasicMaster::OnBoot(id, st, es, what);
  Defer([this, id, st, es, what] { HandleBoot(id, st, es, what); });
}

void Network::HandleBoot(uint8_t id, NmtState st, char es, const std::string& what) {
  auto it = nodes_.find(id);
  if (it == nodes_.end()) return;
  NodeState& n = it->second;
  n.boot_waiting = false;
  // With config_check, Lely skips the configuration step (no OnConfig) when
  // the node's 0x1020 equals the master's 0x1F26/0x1F27: the node already has
  // this configuration.
  bool unchanged = n.cfg->config_check && !n.cfg_ran && (!es || es == 'L');
  // 'L': the slave was already operational (it started itself). The master
  // still ran the configuration step, so if our downloads all succeeded the
  // node is configured and running, and Lely has resumed error control.
  bool configured_running = es == 'L' && (n.cfg_ok || unchanged);
  n.cfg_ok = false;
  n.cfg_ran = false;
  if (unchanged)
    log_info("%s: configuration unchanged (0x1020 matches), nothing downloaded", n.cfg->label().c_str());
  n.boot_what = es && !configured_running ? what : "";
  if (!es || configured_running) {
    n.booted = true;
    n.retry_pending = false;
    n.backoff = kRetryMin;
    n.lss_backoff = kRetryMin;
    n.identity_logged.clear();
    // Lely starts a booted node right away, unless the master may not start
    // nodes, or starts them all at once when it becomes OPERATIONAL itself.
    const MasterConfig& m = cfg_.master;
    n.node_op = configured_running || (m.start_nodes && (!m.start_all_nodes || master_op_));
    SetState(id, n.node_op ? kStateOperational : kStatePreop);
    SetBootError(id, 0);
    Update(id, "");
    if (!n.node_op && n.hold == Hold::None)
      log_info("%s: configured; %s", n.cfg->label().c_str(),
               m.start_nodes ? "it starts when the master starts all nodes"
                             : "it stays PRE-OPERATIONAL (master start_nodes is false)");
    OnBooted(id, n);
    // After the master has started (or found the network held), the
    // master's own queued work runs first.
    if (n.cfg->mandatory) Defer([this] { StartHeldMaster(); });
    return;
  }
  n.booted = false;
  n.node_op = false;
  Update(id, "boot failed");
  // The state Lely last saw; BOOTUP here means the node never answered.
  SetState(id, state_code(st, false));
  SetBootError(id, static_cast<uint8_t>(es));
  if (es == 'D' || es == 'M' || es == 'N' || es == 'O') {
    // It answered, but it is not the device the EDS describes. A reset would
    // not change that, so the retry only boots it again (a replaced device
    // comes up), and the error is logged once per identity found.
    n.warned_absent = true;
    ReportIdentity(id, es);
    ScheduleRetry(n, true);
    return;
  }
  log_error("%s: boot failed (error status %c: %s)", n.cfg->label().c_str(), es, what.c_str());
  // 'L': running unconfigured; 'J': a configuration download was refused.
  if (es == 'L' || es == 'J') n.reset_on_retry = true;
  ScheduleRetry(n);
}

namespace {

std::string base_name(const std::string& path) {
  size_t slash = path.find_last_of('/');
  return slash == std::string::npos ? path : path.substr(slash + 1);
}

}  // namespace

void Network::ReportIdentity(uint8_t id, char es) {
  NodeState& n = nodes_[id];
  static const char* const kField[] = {"vendor ID", "product code", "revision number", "serial number"};
  uint8_t sub = es == 'D' ? 1 : es == 'M' ? 2 : es == 'N' ? 3 : 4;
  std::error_code ec;
  // The expected values the master checks (0x1F85-0x1F88, sub-index = node).
  uint32_t expected = (*this)[static_cast<uint16_t>(0x1F84 + sub)][id].Read<uint32_t>(ec);
  bool from_json = (sub == 3 && n.cfg->has_revision_number) || (sub == 4 && n.cfg->has_serial_number);
  std::string source = from_json ? "the configuration" : base_name(n.cfg->eds);
  std::string label = n.cfg->label();
  const char* field = kField[sub - 1];
  auto report = [this, id, es, field, expected, source, label](bool read, uint32_t value) {
    NodeState& n = nodes_[id];
    std::string key = std::string(1, es) + (read ? std::to_string(value) : "?");
    if (key == n.identity_logged) return;
    n.identity_logged = key;
    if (read)
      log_error("%s: wrong device: %s %u (0x%08X), expected %u (0x%08X) from %s", label.c_str(), field, value, value,
                expected, expected, source.c_str());
    else
      log_error("%s: wrong device: %s differs from the expected %u (0x%08X) from %s", label.c_str(), field, expected,
                expected, source.c_str());
  };
  try {
    SubmitRead<uint32_t>(exec_, id, 0x1018, sub,
                         [report](uint8_t, uint16_t, uint8_t, std::error_code ec, uint32_t value) {
                           report(!ec, value);
                         });
  } catch (const std::exception&) {
    report(false, 0);
  }
}

void Network::StartHeldMaster() {
  // Lely halts the network boot-up for good once a mandatory node has failed
  // to boot, even after the node boots on a retry: start the master when
  // every mandatory node has booted.
  if (!cfg_.master.start || master_state_ != kStatePreop) return;
  for (const auto& it : nodes_)
    if (it.second.cfg->mandatory && !it.second.booted) return;
  log_info("all mandatory nodes have booted: starting the master");
  Command(NmtCommand::START, static_cast<uint8_t>(cfg_.master.node_id));
}

void Network::OnCommand(NmtCommand cs) noexcept {
  BasicMaster::OnCommand(cs);
  Defer([this, cs] { HandleCommand(cs); });
}

void Network::HandleCommand(NmtCommand cs) {
  // The master's own NMT state: Lely reports it only as the command that
  // made it enter the state.
  switch (cs) {
    case NmtCommand::START: SetMasterState(kStateOperational); break;
    case NmtCommand::ENTER_PREOP: SetMasterState(kStatePreop); break;
    case NmtCommand::STOP: SetMasterState(kStateStopped); break;
    default: SetMasterState(kStateNoContact); break;  // resetting
  }
  bool was_op = master_op_;
  master_op_ = cs == NmtCommand::START;
  if (master_op_ && !was_op) {
    log_info("master is operational");
    // Starting all nodes at once: Lely starts every booted node now.
    const MasterConfig& m = cfg_.master;
    if (m.start_nodes && m.start_all_nodes)
      for (auto& it : nodes_)
        if (it.second.cfg->boot && it.second.booted && !it.second.node_op) {
          it.second.node_op = true;
          SetState(it.first, kStateOperational);
        }
  } else if (cs == NmtCommand::STOP) {
    log_error("master is STOPPED: no PDOs are exchanged until the plugin restarts");
  } else if (cs == NmtCommand::ENTER_PREOP && was_op) {
    log_warn("master is PRE-OPERATIONAL: no PDOs are exchanged");
  }
  for (const auto& it : nodes_) Update(it.first, master_op_ ? "" : "the master is not OPERATIONAL");
}

void Network::OnConfig(uint8_t id) noexcept {
  Defer([this, id] { HandleConfig(id); });
}

void Network::HandleConfig(uint8_t id) {
  auto it = nodes_.find(id);
  if (it == nodes_.end()) {
    ConfigResult(id, {});
    return;
  }
  it->second.boot_waiting = false;  // it answers
  it->second.warned_absent = true;  // so it is not reported as not answering
  it->second.cfg_step = 0;
  it->second.cfg_ok = false;
  it->second.cfg_ran = true;
  size_t count = it->second.sdos ? it->second.sdos->size() : 0;
  log_info("%s: configuring (%zu SDO downloads)", it->second.cfg->label().c_str(), count);
  ConfigNext(id);
}

void Network::ConfigNext(uint8_t id) {
  NodeState& n = nodes_[id];
  if (!n.sdos || n.cfg_step >= n.sdos->size()) {
    n.cfg_ok = true;
    ConfigResult(id, {});
    return;
  }
  const SdoWrite& w = (*n.sdos)[n.cfg_step];
  try {
    SubmitWrite(exec_, id, w.index, w.subindex, std::vector<uint8_t>(w.data),
                [this](uint8_t id, uint16_t idx, uint8_t subidx, std::error_code ec) {
                  NodeState& n = nodes_[id];
                  if (ec) {
                    std::string hint;
                    if (ec == lely::canopen::SdoErrc::TIMEOUT)
                      hint = ", no answer within " + std::to_string(cfg_.master.sdo_timeout_ms) +
                             " ms (master.sdo_timeout_ms)";
                    log_error("node %u: SDO download to index 0x%04X subindex %u aborted, abort code 0x%08X (%s)%s",
                              id, idx, subidx, static_cast<unsigned>(ec.value()), ec.message().c_str(),
                              hint.c_str());
                    ConfigResult(id, ec);
                    return;
                  }
                  ++n.cfg_step;
                  ConfigNext(id);
                });
  } catch (const std::exception& e) {
    log_error("node %u: cannot start SDO download to index 0x%04X subindex %u: %s", id, w.index,
              w.subindex, e.what());
    ConfigResult(id, std::make_error_code(std::errc::io_error));
  }
}

void Network::OnRpdoWrite(uint8_t id, uint16_t idx, uint8_t subidx) noexcept {
  BasicMaster::OnRpdoWrite(id, idx, subidx);
  Defer([this, id, idx, subidx] { HandleRpdoWrite(id, idx, subidx); });
}

void Network::HandleRpdoWrite(uint8_t id, uint16_t idx, uint8_t subidx) {
  auto it = nodes_.find(id);
  if (it == nodes_.end()) return;
  const auto& bindings = image_.inputs();
  bool changed = false;
  for (size_t i : it->second.inputs) {
    const Binding& b = bindings[i];
    if (b.index != idx || b.subindex != subidx) continue;
    std::error_code ec;
    uint64_t raw = RpdoRaw(id, idx, subidx, b.type, ec);
    if (ec) continue;
    image_.set_input(i, raw);
    changed = true;
  }
  if (changed) image_.commit_inputs();
  if (!gw_) return;
  for (size_t r : routes_up_) {
    const RouteConfig& rc = gw_->cfg().routes[r];
    if (rc.node != id || rc.index != idx || rc.subindex != subidx) continue;
    std::error_code ec;
    uint64_t raw = RpdoRaw(id, idx, subidx, rc.type, ec);
    if (!ec) gw_->put(r, raw);
  }
}

uint64_t Network::RpdoRaw(uint8_t id, uint16_t idx, uint8_t subidx, CoType type, std::error_code& ec) {
  switch (type) {
    case CoType::BOOLEAN: return RpdoRead<bool>(id, idx, subidx, ec) ? 1 : 0;
    case CoType::INTEGER8: return static_cast<uint8_t>(RpdoRead<int8_t>(id, idx, subidx, ec));
    case CoType::UNSIGNED8: return RpdoRead<uint8_t>(id, idx, subidx, ec);
    case CoType::INTEGER16: return static_cast<uint16_t>(RpdoRead<int16_t>(id, idx, subidx, ec));
    case CoType::UNSIGNED16: return RpdoRead<uint16_t>(id, idx, subidx, ec);
    case CoType::INTEGER32: return static_cast<uint32_t>(RpdoRead<int32_t>(id, idx, subidx, ec));
    case CoType::UNSIGNED32: return RpdoRead<uint32_t>(id, idx, subidx, ec);
    case CoType::REAL32: {
      float f = RpdoRead<float>(id, idx, subidx, ec);
      uint32_t u;
      std::memcpy(&u, &f, sizeof(u));
      return u;
    }
    case CoType::INTEGER64: return static_cast<uint64_t>(RpdoRead<int64_t>(id, idx, subidx, ec));
    case CoType::UNSIGNED64: return RpdoRead<uint64_t>(id, idx, subidx, ec);
    case CoType::REAL64: {
      double d = RpdoRead<double>(id, idx, subidx, ec);
      uint64_t raw;
      std::memcpy(&raw, &d, sizeof(raw));
      return raw;
    }
  }
  return 0;
}

void Network::TpdoRaw(uint8_t id, uint16_t idx, uint8_t subidx, CoType type, uint64_t v, std::error_code& ec) {
  switch (type) {
    case CoType::BOOLEAN: TpdoWrite<bool>(id, idx, subidx, v != 0, ec); break;
    case CoType::INTEGER8: TpdoWrite<int8_t>(id, idx, subidx, static_cast<int8_t>(v), ec); break;
    case CoType::UNSIGNED8: TpdoWrite<uint8_t>(id, idx, subidx, static_cast<uint8_t>(v), ec); break;
    case CoType::INTEGER16: TpdoWrite<int16_t>(id, idx, subidx, static_cast<int16_t>(v), ec); break;
    case CoType::UNSIGNED16: TpdoWrite<uint16_t>(id, idx, subidx, static_cast<uint16_t>(v), ec); break;
    case CoType::INTEGER32: TpdoWrite<int32_t>(id, idx, subidx, static_cast<int32_t>(v), ec); break;
    case CoType::UNSIGNED32: TpdoWrite<uint32_t>(id, idx, subidx, static_cast<uint32_t>(v), ec); break;
    case CoType::REAL32: {
      uint32_t u = static_cast<uint32_t>(v);
      float f;
      std::memcpy(&f, &u, sizeof(f));
      TpdoWrite<float>(id, idx, subidx, f, ec);
      break;
    }
    case CoType::INTEGER64: TpdoWrite<int64_t>(id, idx, subidx, static_cast<int64_t>(v), ec); break;
    case CoType::UNSIGNED64: TpdoWrite<uint64_t>(id, idx, subidx, v, ec); break;
    case CoType::REAL64: {
      double d;
      std::memcpy(&d, &v, sizeof(d));
      TpdoWrite<double>(id, idx, subidx, d, ec);
      break;
    }
  }
}

void Network::SetGateway(GatewayLink* gw) {
  if (!gw || !gw->cfg().enabled) return;
  gw_ = gw;
  const auto& routes = gw->cfg().routes;
  route_seen_.assign(routes.size(), 0);
  route_value_.assign(routes.size(), 0);
  for (size_t r = 0; r < routes.size(); ++r) {
    if (routes[r].field_network != cfg_.network_index) continue;
    (routes[r].up ? routes_up_ : routes_down_).push_back(r);
  }
  for (const auto& n : nodes_) gw_->set_node_state(cfg_.network_index, n.first, image_.node_state(n.first));
}

void Network::ServiceGateway() {
  if (!gw_ || stopped_) return;
  bool ok = gw_->upper_ok();
  if (ok != upper_ok_) UpperLoss(ok);
  bool zero = !ok && gw_->cfg().on_upper_loss == GatewayConfig::UpperLoss::Zero;
  std::set<unsigned> changed;
  for (size_t r : routes_down_) {
    const RouteConfig& rc = gw_->cfg().routes[r];
    uint64_t v;
    if (!gw_->get(r, v, route_seen_[r])) continue;
    route_value_[r] = v;
    if (zero) continue;  // applied when the upper master is back
    std::error_code ec;
    TpdoRaw(static_cast<uint8_t>(rc.node), rc.index, rc.subindex, rc.type, v, ec);
    if (!ec) changed.insert(rc.node);
  }
  for (unsigned id : changed) {
    auto it = nodes_.find(id);
    if (it == nodes_.end() || !it->second.up) continue;
    for (unsigned num : it->second.tpdos)
      if (tpdo_event_.count(num)) TpdoEvent(static_cast<int>(num));
  }
}

void Network::UpperLoss(bool ok) {
  upper_ok_ = ok;
  auto loss = gw_->cfg().on_upper_loss;
  std::set<unsigned> targets;
  for (size_t r : routes_down_) targets.insert(gw_->cfg().routes[r].node);
  if (loss == GatewayConfig::UpperLoss::Zero) {
    // Lost: every routed field output to 0; back: the newest routed values.
    for (size_t r : routes_down_) {
      const RouteConfig& rc = gw_->cfg().routes[r];
      std::error_code ec;
      TpdoRaw(static_cast<uint8_t>(rc.node), rc.index, rc.subindex, rc.type, ok ? route_value_[r] : 0, ec);
    }
    if (!ok && !routes_down_.empty()) log_warn("gateway: the upper master is lost; routed outputs set to 0");
    for (unsigned id : targets) {
      auto it = nodes_.find(id);
      if (it == nodes_.end() || !it->second.up) continue;
      for (unsigned num : it->second.tpdos)
        if (tpdo_event_.count(num)) TpdoEvent(static_cast<int>(num));
    }
  } else if (loss == GatewayConfig::UpperLoss::StopNodes) {
    for (unsigned id : targets) {
      auto it = nodes_.find(id);
      if (it == nodes_.end()) continue;
      NodeState& n = it->second;
      if (!ok) {
        if (n.hold != Hold::None && !n.hold_by_gateway) continue;  // the program or an operator holds it
        n.hold = Hold::Stopped;
        n.hold_by_gateway = true;
        SendHold(id, n);
      } else if (n.hold_by_gateway) {
        n.hold = Hold::None;
        n.hold_by_gateway = false;
        if (n.booted) {
          log_info("%s: NMT START (the upper master started the gateway)", n.cfg->label().c_str());
          Command(NmtCommand::START, static_cast<uint8_t>(id));
        }
      }
    }
  }
}

void Network::OnSync(uint8_t cnt, const time_point& t) noexcept {
  BasicMaster::OnSync(cnt, t);
  CountSync();
  // With PLC-cycle SYNC the outputs went out with this SYNC (SendSync).
  bool plc = cfg_.master.sync_plc_cycle;
  Defer([this, plc] {
    if (!plc) WriteOutputs();
    ServiceRequests();
  });
}

void Network::OnRpdo(int num, std::error_code ec, const void* p, std::size_t n) noexcept {
  (void)p;
  (void)n;
  if (ec) return;
  auto it = sync_rpdos_.find(static_cast<unsigned>(num));
  if (it == sync_rpdos_.end()) return;
  it->second.since = 0;
  it->second.armed = true;
}

void Network::MapSyncRpdos() {
  sync_rpdos_.clear();
  for (unsigned num = 1; num <= 512; ++num) {
    std::error_code ec;
    uint32_t cob = (*this)[0x1400 + num - 1][1].Read<uint32_t>(ec);
    if (ec) continue;
    uint8_t trans = (*this)[0x1400 + num - 1][2].Read<uint8_t>(ec);
    if (ec || trans < 1 || trans > 240) continue;
    cob &= 0x7FF;
    SyncRpdo r;
    r.trans = trans;
    for (const auto& n : cfg_.nodes)
      for (const auto& pdo : n.tx_pdos)
        if (n.tpdo_cob_id(pdo) == cob) r.node_id = n.node_id, r.pdo = pdo.number;
    if (!r.node_id) continue;
    sync_rpdos_[num] = r;
    // PLC-cycle SYNC: take the inputs as they arrive, so the next frame's
    // cycle_start() sees them (Lely would hold a synchronous RPDO until the
    // next SYNC). The node keeps its own synchronous type.
    if (cfg_.master.sync_plc_cycle) {
      (*this)[0x1400 + num - 1][2].Write<uint8_t>(0xFF, ec);
      if (ec) log_warn("cannot make master RPDO %u event-driven: %s", num, ec.message().c_str());
    }
  }
}

// After every SYNC the master sends (timer or PLC cycle): the interval and
// the late PDO check. Runs on the loop thread with the master locked.
void Network::CountSync() {
  auto now = clock::now();
  SyncStats& st = sync_stats_;
  if (st.count) {
    auto d = std::chrono::duration_cast<std::chrono::microseconds>(now - last_sync_);
    uint64_t us = static_cast<uint64_t>(d.count());
    st.last_us = us;
    if (st.count == 1 || us < st.min_us) st.min_us = us;
    if (us > st.max_us) st.max_us = us;
  }
  ++st.count;
  last_sync_ = now;
  for (auto& it : sync_rpdos_) {
    SyncRpdo& r = it.second;
    auto n = nodes_.find(r.node_id);
    if (n == nodes_.end() || !n->second.up) {
      r.armed = false;
      continue;
    }
    if (!r.armed) continue;
    if (r.since >= r.trans) {
      ++st.late;
      r.since = 0;
      if (now - r.warned >= kSyncWarnPeriod) {
        r.warned = now;
        log_warn("%s TPDO %u (transmission type %u) did not arrive before the next SYNC (%llu late PDOs so far)",
                 n->second.cfg->label().c_str(), r.pdo, r.trans, static_cast<unsigned long long>(st.late));
      }
    }
    ++r.since;
  }
}

void Network::ServiceSyncRequests() {
  uint64_t req = image_.sync_requests();
  if (req == sync_seen_ || stopped_) {
    sync_seen_ = req;
    return;
  }
  uint64_t skipped = req - sync_seen_ - 1;
  sync_seen_ = req;
  if (skipped) {
    sync_stats_.skipped += skipped;
    auto now = clock::now();
    if (now - skip_warned_ >= kSyncWarnPeriod) {
      skip_warned_ = now;
      log_warn("the bus thread fell behind the PLC cycle: %llu SYNCs merged into one (%llu skipped so far)",
               static_cast<unsigned long long>(skipped + 1), static_cast<unsigned long long>(sync_stats_.skipped));
    }
  }
  WriteOutputs();
  SendSync();
}

// One SYNC as Lely's own producer sends it (co_sync_timer), then Lely's
// synchronous PDO processing for it.
void Network::SendSync() {
  std::error_code ec;
  uint32_t cobid = (*this)[0x1005][0].Read<uint32_t>(ec);
  if (ec) cobid = 0x80;
  uint8_t max_cnt = (*this)[0x1019][0].Read<uint8_t>(ec);
  if (ec) max_cnt = 0;
  can_msg msg = CAN_MSG_INIT;
  if (cobid & 0x20000000u) {
    msg.id = cobid & CAN_MASK_EID;
    msg.flags |= CAN_FLAG_IDE;
  } else {
    msg.id = cobid & CAN_MASK_BID;
  }
  uint8_t cnt = 0;
  if (max_cnt > 1) {
    msg.len = 1;
    msg.data[0] = cnt = sync_cnt_;
    sync_cnt_ = sync_cnt_ < max_cnt ? sync_cnt_ + 1 : 1;
  }
  std::lock_guard<lely::util::BasicLockable> lock(*this);
  can_net_send(net(), &msg);
  co_nmt_on_sync(nmt(), cnt);
}

void Network::WriteOutputs() {
  const uint64_t* out = image_.latest_outputs();
  const auto& bindings = image_.outputs();
  std::map<unsigned, bool> changed;
  for (size_t i = 0; i < bindings.size(); ++i) {
    const Binding& b = bindings[i];
    auto it = nodes_.find(b.node_id);
    if (it == nodes_.end() || !it->second.up) continue;
    uint64_t v = out[i];
    uint8_t id = static_cast<uint8_t>(b.node_id);
    std::error_code ec;
    TpdoRaw(id, b.index, b.subindex, b.type, v, ec);
    if (v != last_out_[i]) {
      last_out_[i] = v;
      changed[b.node_id] = true;
    }
  }
  // Event-driven master TPDOs only go out when triggered: send them when
  // their data changed.
  for (const auto& c : changed)
    for (unsigned num : nodes_[c.first].tpdos)
      if (tpdo_event_.count(num)) TpdoEvent(static_cast<int>(num));
}

void Network::OnHeartbeat(uint8_t id, bool occurred) noexcept {
  BasicMaster::OnHeartbeat(id, occurred);
  Defer([this, id, occurred] { HandleHeartbeat(id, occurred); });
}

void Network::HandleHeartbeat(uint8_t id, bool occurred) {
  auto it = nodes_.find(id);
  if (it == nodes_.end()) return;
  if (occurred) {
    it->second.node_op = false;
    if (it->second.cfg->heartbeat_timeout_ms)
      log_error("%s lost: no heartbeat within %u ms", it->second.cfg->label().c_str(),
                it->second.cfg->heartbeat_timeout_ms);
    else
      log_error("%s lost: no heartbeat within 3 x its EDS heartbeat period", it->second.cfg->label().c_str());
    Update(id, "heartbeat timeout");
    SetState(id, kStateNoContact);
    ScheduleRetry(it->second);
  } else {
    log_info("%s: heartbeat resumed", it->second.cfg->label().c_str());
  }
}

void Network::OnNodeGuarding(uint8_t id, bool occurred) noexcept {
  BasicMaster::OnNodeGuarding(id, occurred);
  Defer([this, id, occurred] { HandleNodeGuarding(id, occurred); });
}

void Network::HandleNodeGuarding(uint8_t id, bool occurred) {
  auto it = nodes_.find(id);
  if (it == nodes_.end()) return;
  if (occurred) {
    it->second.node_op = false;
    log_error("%s lost: no node guarding response", it->second.cfg->label().c_str());
    Update(id, "node guarding timeout");
    SetState(id, kStateNoContact);
    ScheduleRetry(it->second);
  } else {
    log_info("%s: node guarding resumed", it->second.cfg->label().c_str());
  }
}

void Network::OnState(uint8_t id, NmtState st) noexcept {
  BasicMaster::OnState(id, st);
  Defer([this, id, st] { HandleState(id, st); });
}

void Network::HandleState(uint8_t id, NmtState st) {
  auto it = nodes_.find(id);
  if (it == nodes_.end()) return;
  NodeState& n = it->second;
  st = static_cast<NmtState>(static_cast<uint8_t>(st) & 0x7F);  // drop the toggle bit
  SetState(id, state_code(st, true));
  switch (st) {
    case NmtState::BOOTUP:
      // The node (re)started. The master boots it again on its own; the retry
      // is the backstop. A restart clears the device's errors.
      SetEmcy(id, 0, 0);
      n.booted = false;
      n.node_op = false;
      Update(id, "node restarted (boot-up message)");
      ScheduleRetry(n, true);
      break;
    case NmtState::START:
      if (n.hold != Hold::None && (n.booted || !n.cfg->boot)) {
        // Started by someone else (the master's own start of all nodes):
        // the program holds it, so put it back.
        SendHold(id, n);
        break;
      }
      n.node_op = true;
      Update(id, "");
      break;
    case NmtState::STOP:
    case NmtState::PREOP: {
      // A configured node that leaves OPERATIONAL is booted again, unless
      // the program holds it out of OPERATIONAL.
      bool was_running = n.node_op && n.booted;
      n.node_op = false;
      Update(id, state_name(st));
      if (n.hold != Hold::None) {
        if ((n.hold == Hold::Stopped) != (st == NmtState::STOP)) SendHold(id, n);
        break;
      }
      if (was_running && master_state_ != kStateStopped) {
        n.booted = false;
        ScheduleRetry(n);
      }
      break;
    }
    default:
      break;
  }
}

void Network::OnEmcy(uint8_t id, uint16_t eec, uint8_t er, uint8_t msef[5]) noexcept {
  BasicMaster::OnEmcy(id, eec, er, msef);
  std::array<uint8_t, 5> m{};
  if (msef) std::copy(msef, msef + 5, m.begin());
  Defer([this, id, eec, er, m] { HandleEmcy(id, eec, er, m); });
}

void Network::SetEmcy(unsigned id, uint16_t code, uint8_t er) {
  if (image_.node_emcy_code(id) == code && image_.node_error_register(id) == er) return;
  if (gw_) gw_->emcy(cfg_.network_index, id, code, er);
  image_.set_node_emcy(id, code, er);
  image_.commit_inputs();
}

void Network::FlushEmcySummary(NodeState& n, clock::time_point now, bool force) {
  if (!n.emcy_unlogged || (!force && now - n.emcy_window < std::chrono::seconds(1))) return;
  log_warn("%s: %u more EMCY in the last second, latest 0x%04X (%s), error register 0x%02X",
           n.cfg->label().c_str(), n.emcy_unlogged, n.emcy_code, emcy_class(n.emcy_code), n.emcy_er);
  n.emcy_unlogged = 0;
}

void Network::HandleEmcy(uint8_t id, uint16_t eec, uint8_t er, const std::array<uint8_t, 5>& msef) {
  auto it = nodes_.find(id);
  if (it == nodes_.end()) {
    if (emcy_unknown_.insert(id).second)
      log_warn("EMCY from node %u, which is not in the configuration: code 0x%04X; further EMCY from it are ignored",
               id, eec);
    return;
  }
  NodeState& n = it->second;
  // The inputs and the history follow every EMCY; only the log is throttled.
  SetEmcy(id, eec, er);
  NodeState::Emcy& rec = n.emcy_hist[n.emcy_head];
  rec.time = std::chrono::system_clock::now();
  rec.code = eec;
  rec.er = er;
  rec.msef = msef;
  n.emcy_head = (n.emcy_head + 1) % kEmcyHistory;
  n.emcy_n = std::min(n.emcy_n + 1, kEmcyHistory);
  auto now = clock::now();
  if (now - n.emcy_window >= std::chrono::seconds(1)) {
    FlushEmcySummary(n, now, true);
    n.emcy_window = now;
    n.emcy_count = 0;
  }
  n.emcy_code = eec;
  n.emcy_er = er;
  if (++n.emcy_count > kLoggedEmcyPerSecond) {
    ++n.emcy_unlogged;
    return;
  }
  if (eec == 0)
    log_info("%s: EMCY error reset (error register 0x%02X)", n.cfg->label().c_str(), er);
  else
    log_warn("%s: EMCY 0x%04X (%s), error register 0x%02X, manufacturer bytes %02X %02X %02X %02X %02X",
             n.cfg->label().c_str(), eec, emcy_class(eec), er, msef[0], msef[1], msef[2], msef[3], msef[4]);
}


// ---------------------------------------------------------------------------
// SDO variables and NMT command bytes

namespace {

// Bytes of an SDO variable's type (BOOLEAN takes one).
size_t type_bytes(CoType t) {
  unsigned bits = co_type_bits(t);
  return bits == 1 ? 1 : bits / 8;
}

}  // namespace

bool Network::SdoAvailable(unsigned id, const NodeState& n) const {
  // SDO works in PRE-OPERATIONAL and OPERATIONAL, and the master leaves a
  // node it boots alone until the boot has ended.
  if (n.cfg->boot && !n.booted) return false;
  uint8_t st = image_.node_state(id);
  return st == kStateOperational || st == kStatePreop;
}

void Network::SetSdoStatus(size_t k, uint8_t status, uint32_t abort, bool set_abort) {
  bool changed = image_.sdo_status(k) != status;
  image_.set_sdo_status(k, status);
  if (set_abort && image_.sdo_abort(k) != abort) {
    image_.set_sdo_abort(k, abort);
    changed = true;
  }
  if (changed) image_.commit_inputs();
}

void Network::OnBooted(unsigned id, NodeState& n) {
  // Every read entry is read once after each boot; every owned write is
  // written again with the program's current value.
  for (size_t k : n.vars) {
    VarState& v = vars_[k];
    v.boot_read = true;
    v.written = false;
  }
  if (n.hold != Hold::None) SendHold(id, n);
}

void Network::SendHold(unsigned id, const NodeState& n) {
  if (n.cfg->boot && !n.booted) return;  // applied when the boot ends
  NmtCommand cs = n.hold == Hold::Stopped ? NmtCommand::STOP : NmtCommand::ENTER_PREOP;
  log_info("%s: NMT %s (held by %s)", n.cfg->label().c_str(), n.hold == Hold::Stopped ? "STOP" : "ENTER PRE-OPERATIONAL",
           n.hold_by_gateway ? "the gateway: the upper master is lost"
                             : n.hold_by_operator ? "a diagnostics client" : "the program");
  Command(cs, static_cast<uint8_t>(id));
}

void Network::ResetNode(unsigned id, NodeState& n, bool comm, const char* by) {
  n.hold = Hold::None;
  n.hold_by_operator = false;
  log_info("%s: NMT %s (from %s)", n.cfg->label().c_str(), comm ? "RESET COMMUNICATION" : "RESET NODE", by);
  Command(comm ? NmtCommand::RESET_COMM : NmtCommand::RESET_NODE, static_cast<uint8_t>(id));
  n.booted = false;
  n.node_op = false;
  std::string why = std::string(comm ? "communication reset by " : "reset by ") + by;
  Update(id, why.c_str());
  SetState(id, kStateNoContact);  // until its boot-up message
  ScheduleRetry(n, true);
}

void Network::ApplyNmtCommand(unsigned id, NodeState& n, uint8_t level, uint64_t resets, uint8_t reset_code) {
  const std::string label = n.cfg->label();
  if (resets != n.nmt_resets) {
    // A reset asked for (a change to 129 or 130), even if the byte moved on
    // since: send it once, then run the node as usual.
    n.nmt_resets = resets;
    n.nmt_level = level;
    ResetNode(id, n, reset_code == 130, "the program");
    return;
  }
  if (level == n.nmt_level) return;
  n.nmt_level = level;
  switch (level) {
    case 0:
    case 1: {
      bool was_held = n.hold != Hold::None;
      n.hold = Hold::None;
      n.hold_by_operator = false;
      // Release a held node; a node the master does not boot starts on 1.
      if ((was_held && n.booted) || (!n.cfg->boot && level == 1)) {
        log_info("%s: NMT START (from the program)", label.c_str());
        Command(NmtCommand::START, static_cast<uint8_t>(id));
      }
      break;
    }
    case 2:
      n.hold = Hold::Stopped;
      n.hold_by_operator = false;
      SendHold(id, n);
      break;
    case 128:
      n.hold = Hold::Preop;
      n.hold_by_operator = false;
      SendHold(id, n);
      break;
    case 129:
    case 130:
      break;  // counted as a reset request in the snapshot
    default:
      log_warn("%s: NMT command byte %u is not a command (0/1 run, 2 stop, 128 pre-operational, 129 reset node, "
               "130 reset communication); ignored",
               label.c_str(), level);
      break;
  }
}

void Network::ServiceRequests() {
  if (stopped_) return;
  auto now = clock::now();
  // The program's SDO blocks name network 0, the first network.
  ServiceProgram(now);
  if (!has_requests_ && prog_.empty()) return;
  const uint64_t* snap = image_.latest_outputs();
  // Nothing before the program has run once: the outputs are not its yet.
  bool scanned = image_.scan_count(snap) != 0;
  for (auto& it : nodes_) {
    unsigned id = it.first;
    NodeState& n = it.second;
    if (scanned) {
      uint8_t level = 0, code = 0;
      uint64_t resets = 0;
      if (image_.nmt_command(snap, id, level, resets, code)) ApplyNmtCommand(id, n, level, resets, code);
    }
    bool avail = SdoAvailable(id, n);
    if (scanned) {
      for (size_t k : n.vars) {
        VarState& v = vars_[k];
        const SdoVariable& var = image_.sdo_vars()[k].var;
        if (var.has_trigger) {
          uint64_t count = image_.sdo_trigger_count(snap, k);
          if (count != v.trig_seen) {
            v.trig_seen = count;
            if (avail) {
              v.trig_pending = true;
            } else {
              v.trig_pending = false;
              SetSdoStatus(k, kSdoUnavailable, 0, false);  // dropped
            }
          }
        }
        // Automatic transfers wait for the node, showing that they do.
        bool automatic = var.is_read() || !var.has_trigger;
        if (!avail && automatic && !(n.sdo_busy && image_.sdo_status(k) == kSdoBusy))
          SetSdoStatus(k, kSdoUnavailable, 0, false);
      }
    }
    if (!avail || n.sdo_busy) continue;
    // Next SDO variable transfer: triggered ones, owned writes, post-boot
    // reads, periodic reads.
    size_t pick = SIZE_MAX;
    for (int pass = 0; scanned && pass < 4 && pick == SIZE_MAX; ++pass)
      for (size_t k : n.vars) {
        VarState& v = vars_[k];
        const SdoVariable& var = image_.sdo_vars()[k].var;
        bool due = false;
        switch (pass) {
          case 0: due = v.trig_pending; break;
          case 1:
            due = !var.is_read() && !var.has_trigger &&
                  (!v.written || image_.sdo_out_value(snap, k) != v.last_written);
            break;
          case 2: due = var.is_read() && v.boot_read; break;
          case 3: due = var.is_read() && var.period_ms && now >= v.next_read; break;
        }
        if (due) {
          pick = k;
          break;
        }
      }
    // Program transfers and SDO variables take turns on the node.
    auto q = prog_.find(id);
    bool prog = q != prog_.end() && !q->second.empty();
    if (prog && (pick == SIZE_MAX || !n.last_prog)) {
      StartProgram(id, &n, now);
    } else if (pick != SIZE_MAX) {
      n.last_prog = false;
      StartTransfer(id, n, pick, snap);
    }
  }
}

void Network::StartTransfer(unsigned id, NodeState& n, size_t k, const uint64_t* snap) {
  VarState& v = vars_[k];
  const SdoVariable& var = image_.sdo_vars()[k].var;
  v.trig_pending = false;
  if (var.is_read()) {
    v.boot_read = false;
    if (var.period_ms) v.next_read = clock::now() + std::chrono::milliseconds(var.period_ms);
  }
  uint64_t value = var.is_read() ? 0 : image_.sdo_out_value(snap, k);
  n.sdo_busy = true;
  SetSdoStatus(k, kSdoBusy, 0, false);
  std::chrono::milliseconds timeout(var.timeout_ms);
  uint8_t node = static_cast<uint8_t>(id);
  std::error_code ec;
  if (var.is_read()) {
    Submit([&] {
      SubmitRead<std::vector<uint8_t>>(
          exec_, node, var.index, var.subindex,
          [this, id, k](uint8_t, uint16_t, uint8_t, std::error_code ec, std::vector<uint8_t> data) {
            FinishTransfer(id, k, ec, &data, 0);
          },
          timeout, ec);
    }, ec);
  } else {
    std::vector<uint8_t> data(type_bytes(var.type));
    uint64_t raw = var.type == CoType::BOOLEAN ? (value ? 1 : 0) : value;
    for (size_t b = 0; b < data.size(); ++b) data[b] = static_cast<uint8_t>(raw >> (8 * b));
    Submit([&] {
      SubmitWrite(
          exec_, node, var.index, var.subindex, std::vector<uint8_t>(data),
          [this, id, k, value](uint8_t, uint16_t, uint8_t, std::error_code ec) {
            FinishTransfer(id, k, ec, nullptr, value);
          },
          timeout, ec);
    }, ec);
  }
  if (ec) FinishTransfer(id, k, ec, nullptr, value);
}

void Network::FinishTransfer(unsigned id, size_t k, std::error_code ec, const std::vector<uint8_t>* data,
                             uint64_t value) {
  auto it = nodes_.find(id);
  if (it == nodes_.end()) return;
  NodeState& n = it->second;
  n.sdo_busy = false;
  VarState& v = vars_[k];
  const SdoVariable& var = image_.sdo_vars()[k].var;
  if (!var.is_read() && !var.has_trigger) {
    // Tried with this value: a refused value is not sent again until the
    // program changes it or the node boots again.
    v.written = true;
    v.last_written = value;
  }
  uint32_t abort = 0;
  if (ec) {
    abort = static_cast<uint32_t>(ec.value());
  } else if (data && data->size() != type_bytes(var.type)) {
    abort = 0x06070010;  // data type does not match, length does not match
    ec = lely::canopen::SdoErrc::TYPE_LEN;
  }
  if (abort) {
    SetSdoStatus(k, kSdoAborted, abort, true);
    if (v.logged_abort != abort) {
      v.logged_abort = abort;
      log_warn("%s: %s: %s aborted, abort code 0x%08X (%s)", n.cfg->label().c_str(), var.label().c_str(),
               var.is_read() ? "read" : "write", abort, ec.message().c_str());
    }
    return;
  }
  v.logged_abort = 0;
  if (data) {
    uint64_t raw = 0;
    for (size_t b = 0; b < data->size() && b < 8; ++b) raw |= uint64_t((*data)[b]) << (8 * b);
    if (var.type == CoType::BOOLEAN) raw = raw ? 1 : 0;
    image_.set_sdo_value(k, raw);
  }
  image_.set_sdo_status(k, kSdoDone);
  image_.set_sdo_abort(k, 0);
  image_.commit_inputs();
}

SyncWake::SyncWake(lely::io::Poll& poll, int fd, Network& net) : poll_(poll), fd_(fd), net_(net) {
  watch_.w = IO_POLL_WATCH_INIT(&SyncWake::OnEvent);
  watch_.self = this;
  Arm();
}

SyncWake::~SyncWake() {
  if (fd_ < 0) return;
  std::error_code ec;
  poll_.watch(fd_, lely::io::Event::NONE, watch_.w, ec);
}

void SyncWake::Arm() {
  if (fd_ < 0) return;
  std::error_code ec;
  poll_.watch(fd_, lely::io::Event::IN, watch_.w, ec);
  if (ec) log_error("cannot watch the PLC-cycle SYNC requests: %s", ec.message().c_str());
}

void SyncWake::OnEvent(struct ::io_poll_watch* watch, int) noexcept {
  SyncWake* self = reinterpret_cast<Watch*>(watch)->self;
  uint64_t n;
  while (read(self->fd_, &n, sizeof(n)) == static_cast<ssize_t>(sizeof(n))) {
  }
  self->net_.ServiceSyncRequests();
  self->Arm();  // a watch reports one event
}

FdWake::FdWake(lely::io::Poll& poll, int fd, std::function<void()> fn) : poll_(poll), fd_(fd), fn_(std::move(fn)) {
  watch_.w = IO_POLL_WATCH_INIT(&FdWake::OnEvent);
  watch_.self = this;
  Arm();
}

FdWake::~FdWake() {
  if (fd_ < 0) return;
  std::error_code ec;
  poll_.watch(fd_, lely::io::Event::NONE, watch_.w, ec);
}

void FdWake::Arm() {
  if (fd_ < 0) return;
  std::error_code ec;
  poll_.watch(fd_, lely::io::Event::IN, watch_.w, ec);
  if (ec) log_error("cannot watch the gateway's wake-ups: %s", ec.message().c_str());
}

void FdWake::OnEvent(struct ::io_poll_watch* watch, int) noexcept {
  FdWake* self = reinterpret_cast<Watch*>(watch)->self;
  uint64_t n;
  while (read(self->fd_, &n, sizeof(n)) == static_cast<ssize_t>(sizeof(n))) {
  }
  if (self->fn_) self->fn_();
  self->Arm();  // a watch reports one event
}

}  // namespace canopen_plugin
