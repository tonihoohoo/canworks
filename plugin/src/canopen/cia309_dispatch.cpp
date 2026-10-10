// cia309_dispatch.cpp - see cia309_dispatch.h.

// Lely's C type names (co_gw_txt_t, ...): in C++ only its .hpp wrappers define
// them otherwise.
#ifndef LELY_NO_CXX
#define LELY_NO_CXX 1
#endif

#include "cia309_dispatch.h"

#include <algorithm>
#include <cstring>

#include <lely/co/gw.h>

#include "cJSON.h"
#include "cia309_text.h"
#include "log.h"

namespace canopen_plugin {

constexpr size_t Cia309Session::kMaxLine;
constexpr size_t Cia309Session::kMaxOutstanding;
constexpr size_t Cia309Session::kMaxNotifications;
constexpr size_t Cia309Session::kNotificationRoom;
constexpr std::chrono::milliseconds Cia309Session::kLssPoll;

namespace {

// The CiA 305 bit timing table (lss_conf_bitrate 0 <index>), kbit/s; 0:
// not a rate the diagnostics channel sets (reserved, automatic).
constexpr unsigned kLssRates[] = {1000, 800, 500, 250, 125, 0, 50, 20, 10, 0};

// A bus thread answer: ok, its result (owned by the document) or its error.
struct Answer {
  cJSON* doc = nullptr;
  bool ok = false;
  const cJSON* result = nullptr;
  std::string error;
  explicit Answer(const std::string& line) {
    doc = cJSON_Parse(line.c_str());
    ok = cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(doc, "ok"));
    result = cJSON_GetObjectItemCaseSensitive(doc, "result");
    const cJSON* e = cJSON_GetObjectItemCaseSensitive(doc, "error");
    if (cJSON_IsString(e)) error = e->valuestring;
    if (!doc) error = "not an answer";
  }
  ~Answer() { cJSON_Delete(doc); }
  Answer(const Answer&) = delete;
  Answer& operator=(const Answer&) = delete;
  const cJSON* get(const char* key) const { return cJSON_GetObjectItemCaseSensitive(result, key); }
  bool truth(const char* key) const { return cJSON_IsTrue(get(key)); }
  double number(const char* key, double def = 0) const {
    const cJSON* v = get(key);
    return cJSON_IsNumber(v) ? v->valuedouble : def;
  }
  std::string text(const char* key) const {
    const cJSON* v = get(key);
    return cJSON_IsString(v) ? v->valuestring : "";
  }
};

std::vector<uint8_t> parse_hex(const std::string& text) {
  std::vector<uint8_t> out;
  std::string digits;
  for (char c : text)
    if (c != ' ') digits += c;
  for (size_t i = 0; i + 1 < digits.size(); i += 2)
    out.push_back(static_cast<uint8_t>(std::strtoul(digits.substr(i, 2).c_str(), nullptr, 16)));
  return out;
}

const char* nmt_command(int srv) {
  switch (srv) {
    case CO_GW_SRV_NMT_START: return "start";
    case CO_GW_SRV_NMT_STOP: return "stop";
    case CO_GW_SRV_NMT_ENTER_PREOP: return "preop";
    case CO_GW_SRV_NMT_RESET_NODE: return "reset";
    case CO_GW_SRV_NMT_RESET_COMM: return "reset-comm";
    default: return nullptr;
  }
}

// Why a service is not served, for the log (canopen-cia309-gateway
// "Services not served").
const char* not_served(int srv) {
  switch (srv) {
    case CO_GW_SRV_SET_RPDO:
    case CO_GW_SRV_SET_TPDO: return "the configuration owns the PDOs";
    case CO_GW_SRV_PDO_WRITE: return "the PLC program owns the outputs";
    case CO_GW_SRV_NMT_NG_ENABLE:
    case CO_GW_SRV_NMT_NG_DISABLE:
    case CO_GW_SRV_NMT_HB_ENABLE:
    case CO_GW_SRV_NMT_HB_DISABLE:
    case CO_GW_SRV_SET_HB: return "the configuration owns node guarding and heartbeats";
    case CO_GW_SRV_INIT:
    case CO_GW_SRV_SET_ID: return "the configuration owns the master's bit rate and node ID";
    case CO_GW_SRV_LSS_SWITCH_RATE: return "activating a new bit rate would cut the running network";
    default: return "not served by this gateway";
  }
}

}  // namespace

Cia309Session::Cia309Session(const Cia309Config& gw, const std::vector<Cia309Net>& nets, std::string peer,
                             bool tunnelled, std::string version)
    : gw_(gw), nets_(nets), peer_(std::move(peer)), tunnelled_(tunnelled), version_(std::move(version)) {
  text_.reset(new Cia309Text([this](const co_gw_req& r) { on_request(&r, r.size, r.srv); },
                             [this](const std::string& line) { on_text(line); }));
}

Cia309Session::~Cia309Session() = default;

void Cia309Session::on_text(const std::string& line) { out_ += line + "\r\n"; }

void Cia309Session::note(const std::string& line) {
  if (notes_.size() >= kMaxNotifications) {
    notes_.pop_front();
    ++notes_lost_;
  }
  notes_.push_back(line + "\r\n");
}

std::string& Cia309Session::output() {
  while (out_.size() < kNotificationRoom && (notes_lost_ || !notes_.empty())) {
    if (notes_lost_) {
      // A comment line: CiA 309-3 clients skip lines starting with '#'.
      out_ += "# " + std::to_string(notes_lost_) + " notification" + (notes_lost_ == 1 ? "" : "s") +
              " lost (the client did not read them in time)\r\n";
      notes_lost_ = 0;
      continue;
    }
    out_ += notes_.front();
    notes_.pop_front();
  }
  return out_;
}

bool Cia309Session::feed(const char* data, size_t n, clock::time_point now) {
  in_.append(data, n);
  size_t start = 0;
  bool ok = true;
  for (;;) {
    size_t nl = in_.find('\n', start);
    if (nl == std::string::npos) break;
    std::string line = in_.substr(start, nl - start);
    start = nl + 1;
    if (!line.empty() && line.back() == '\r') line.pop_back();
    if (line.size() > kMaxLine) {
      ok = false;
      break;
    }
    parsing_ = &line;
    uint32_t seq = 0;
    bool parsed = text_->line(line, seq);
    parsing_ = nullptr;
    if (!parsed) {
      Command c;
      c.seq = seq;
      c.srv = CO_GW_SRV_SDO_UP;  // any confirmed service: the answer is "[seq] ERROR: 101"
      c.syntax = true;
      c.text = line;
      if (queue_.size() >= kMaxOutstanding)
        confirm(c, CO_GW_IEC_INTERN);
      else
        queue_.push_back(std::move(c));
    }
  }
  in_.erase(0, start);
  if (in_.size() > kMaxLine) ok = false;
  if (!ok) {
    log_warn("cia309 %s: a request line is longer than %zu bytes; closing the session", peer_.c_str(), kMaxLine);
    in_.clear();
    return false;
  }
  run(now);
  return true;
}

void Cia309Session::on_request(const void* req, size_t size, int srv) {
  Command c;
  c.srv = srv;
  c.seq = static_cast<uint32_t>(reinterpret_cast<uintptr_t>(static_cast<const co_gw_req*>(req)->data));
  c.req.assign(static_cast<const uint8_t*>(req), static_cast<const uint8_t*>(req) + size);
  if (parsing_) c.text = *parsing_;
  if (queue_.size() >= kMaxOutstanding) {
    refuse(c, "more than " + std::to_string(kMaxOutstanding) + " commands outstanding");
    return;
  }
  queue_.push_back(std::move(c));
}

void Cia309Session::run(clock::time_point now) {
  while (!queue_.empty()) {
    Command& c = queue_.front();
    if (c.running) return;
    if (!start(c, now)) return;
    queue_.pop_front();
    ++served_;
  }
}

bool Cia309Session::answer(size_t net, uint64_t seq, const std::string& line, clock::time_point now) {
  if (queue_.empty()) return false;
  Command& c = queue_.front();
  if (!c.running || !c.hub_seq || c.net != net || c.hub_seq != seq) return false;
  c.hub_seq = 0;
  if (finish(c, line, now)) {
    queue_.pop_front();
    ++served_;
    run(now);
  }
  return true;
}

Cia309Session::clock::time_point Cia309Session::poll(clock::time_point now) {
  if (queue_.empty() || !queue_.front().running) return clock::time_point::max();
  Command& c = queue_.front();
  if (now >= c.deadline) {
    log_warn("cia309 %s: %s: no answer from the bus thread in time; answered with error 103", peer_.c_str(),
             c.text.c_str());
    confirm(c, CO_GW_IEC_TIMEOUT);
    // A late answer finds no command waiting for it and is dropped.
    queue_.pop_front();
    ++served_;
    run(now);
    return poll(now);
  }
  if (c.srv == CO_GW_SRV__LSS_FASTSCAN && c.step == 1 && !c.hub_seq) {
    if (now >= c.next) {
      c.hub_seq = nets_[c.net].hub->submit(request("lss_find_status"));
    } else {
      return std::min(c.deadline, c.next);
    }
  }
  return c.deadline;
}

DiagRequest Cia309Session::request(const std::string& op) const {
  DiagRequest r;
  r.op = op;
  r.peer = peer_;
  r.from_cia309 = true;
  // What the diagnostics channel refuses without force, the gateway refuses
  // unless allow_force: the text protocol has no per-request force.
  r.force = gw_.allow_force;
  return r;
}

void Cia309Session::submit(Command& c, size_t net, unsigned number, DiagRequest r, clock::time_point now,
                           unsigned timeout_ms) {
  c.net = net;
  c.number = number;
  c.running = true;
  c.deadline = now + std::chrono::milliseconds(timeout_ms);
  c.hub_seq = nets_[net].hub->submit(std::move(r));
}

void Cia309Session::confirm(const Command& c, int iec, uint32_t ac) { text_->confirm(c.seq, c.srv, iec, ac); }

void Cia309Session::refuse(const Command& c, const std::string& why, int iec) {
  log_info("cia309 %s: %s refused: %s", peer_.c_str(), c.text.c_str(), why.c_str());
  confirm(c, iec);
}

void Cia309Session::fail(const Command& c, const std::string& why) {
  if (why.size() >= 12 && why.compare(why.size() - 12, 12, "force needed") == 0)
    refuse(c, why + "; force is not allowed on the CiA 309-3 gateway (cia309.allow_force)");
  else if (why.find("not in the configuration") != std::string::npos || why.find("is not this slave") != std::string::npos)
    refuse(c, why, CO_GW_IEC_BAD_NODE);
  else if (why.compare(0, 7, "timeout") == 0)
    refuse(c, why, CO_GW_IEC_TIMEOUT);
  else
    refuse(c, why);
}

bool Cia309Session::changes_allowed(const Command& c) {
  if (gw_.allow_changes) return true;
  refuse(c, "changes not allowed (cia309.allow_changes is off)");
  return false;
}

bool Cia309Session::is_configured(size_t net, unsigned node) const {
  for (const auto& n : nets_[net].cfg->nodes)
    if (n.node_id == node) return true;
  return false;
}

bool Cia309Session::pick_net(unsigned requested, size_t& index, unsigned& number, int& iec) const {
  number = requested ? requested : default_net_ ? default_net_ : gw_.default_net;
  if (!number && gw_.numbering.size() == 1) number = gw_.numbering.begin()->first;
  if (!number) {
    iec = CO_GW_IEC_NO_DEF_NET;
    return false;
  }
  auto it = gw_.numbering.find(number);
  if (it == gw_.numbering.end() || it->second >= nets_.size()) {
    iec = CO_GW_IEC_BAD_NET;
    return false;
  }
  index = it->second;
  const Cia309Net& n = nets_[index];
  // J1939 and plain CAN networks have no CANopen services.
  if (!n.cfg || !n.hub || !n.cfg->is_canopen()) {
    iec = CO_GW_IEC_BAD_NET;
    return false;
  }
  return true;
}

bool Cia309Session::pick_node(unsigned number, unsigned requested, unsigned& node, int& iec) const {
  if (requested != 0xFF) {
    node = requested;
    return true;
  }
  auto it = default_node_.find(number);
  if (it == default_node_.end()) {
    iec = CO_GW_IEC_NO_DEF_NODE;
    return false;
  }
  node = it->second;
  return true;
}

bool Cia309Session::start(Command& c, clock::time_point now) {
  if (c.syntax) {
    confirm(c, CO_GW_IEC_SYNTAX);
    return true;
  }
  const uint8_t* raw = c.req.data();
  size_t index = 0;
  unsigned number = 0, node = 0;
  int iec = 0;
  // The network of a network-level request, or false (answered).
  auto net_of = [&](unsigned requested, bool master_only) {
    if (!pick_net(requested, index, number, iec)) {
      confirm(c, iec);
      return false;
    }
    if (master_only && nets_[index].cfg->is_slave()) {
      // A slave network serves its own dictionary only.
      confirm(c, CO_GW_IEC_BAD_NODE);
      return false;
    }
    return true;
  };
  auto need_selection = [&]() {
    if (selected_) return true;
    refuse(c, "no LSS device selected (lss_switch_sel or _lss_fastscan first)");
    return false;
  };
  auto lss_request = [&](const std::string& op) {
    DiagRequest r = request(op);
    std::copy(selection_.begin(), selection_.end(), r.lss);
    return r;
  };

  switch (c.srv) {
    case CO_GW_SRV_SDO_UP:
    case CO_GW_SRV_SDO_DN: {
      const bool up = c.srv == CO_GW_SRV_SDO_UP;
      unsigned net_req = 0, node_req = 0;
      uint16_t idx = 0;
      uint8_t sub = 0;
      if (up) {
        const auto* q = reinterpret_cast<const co_gw_req_sdo_up*>(raw);
        net_req = q->net, node_req = q->node, idx = q->idx, sub = q->subidx;
      } else {
        const auto* q = reinterpret_cast<const co_gw_req_sdo_dn*>(raw);
        net_req = q->net, node_req = q->node, idx = q->idx, sub = q->subidx;
      }
      if (!net_of(net_req, false)) return true;
      if (!pick_node(number, node_req, node, iec)) {
        confirm(c, iec);
        return true;
      }
      const Config& cfg = *nets_[index].cfg;
      if (node < 1 || node > 127 || (!cfg.is_slave() && node == cfg.master.node_id)) {
        confirm(c, CO_GW_IEC_BAD_NODE);
        return true;
      }
      DiagRequest r = request(up ? "sdo_read" : "sdo_write");
      r.node = node;
      r.index = idx;
      r.subindex = sub;
      r.timeout_ms = sdo_timeout_ms_;
      if (!up) {
        if (!changes_allowed(c)) return true;
        const auto* q = reinterpret_cast<const co_gw_req_sdo_dn*>(raw);
        if (q->len > kDiagMaxSdoBytes) {
          refuse(c, "at most " + std::to_string(kDiagMaxSdoBytes) + " bytes can be written");
          return true;
        }
        r.data.assign(q->val, q->val + q->len);
      }
      submit(c, index, number, std::move(r), now, std::max(command_timeout_ms_, sdo_timeout_ms_ + 500));
      return false;
    }
    case CO_GW_SRV_SET_SDO_TIMEOUT: {
      const auto* q = reinterpret_cast<const co_gw_req_set_sdo_timeout*>(raw);
      if (q->net && !net_of(q->net, false)) return true;
      sdo_timeout_ms_ = static_cast<unsigned>(std::min(10000, std::max(10, q->timeout)));
      confirm(c, 0);
      return true;
    }
    case CO_GW_SRV_PDO_READ: {
      const auto* q = reinterpret_cast<const co_gw_req_pdo_read*>(raw);
      if (!net_of(q->net, true)) return true;
      // Gateway RPDO numbers: node k's TPDO n (1-4) is (k - 1) * 4 + n.
      unsigned num = q->num;
      node = (num - 1) / 4 + 1;
      unsigned tpdo = (num - 1) % 4 + 1;
      if (num < 1 || node > 127 || !is_configured(index, node)) {
        refuse(c, "PDO not configured: gateway RPDO " + std::to_string(num) + " is node " + std::to_string(node) +
                      " TPDO " + std::to_string(tpdo) + ", which is not a configured node");
        return true;
      }
      DiagRequest r = request("pdo_read");
      r.node = node;
      r.pdo = tpdo;
      submit(c, index, number, std::move(r), now, command_timeout_ms_);
      return false;
    }
    case CO_GW_SRV_NMT_START:
    case CO_GW_SRV_NMT_STOP:
    case CO_GW_SRV_NMT_ENTER_PREOP:
    case CO_GW_SRV_NMT_RESET_NODE:
    case CO_GW_SRV_NMT_RESET_COMM: {
      const auto* q = reinterpret_cast<const co_gw_req_node*>(raw);
      if (!net_of(q->net, true)) return true;
      if (!pick_node(number, q->node, node, iec)) {
        confirm(c, iec);
        return true;
      }
      if (node && !is_configured(index, node)) {
        confirm(c, CO_GW_IEC_BAD_NODE);
        return true;
      }
      if (!changes_allowed(c)) return true;
      DiagRequest r = request("nmt");
      r.node = node;  // 0: every configured node
      r.command = nmt_command(c.srv);
      submit(c, index, number, std::move(r), now, command_timeout_ms_);
      return false;
    }
    case CO_GW_SRV_SET_CMD_TIMEOUT: {
      const auto* q = reinterpret_cast<const co_gw_req_set_cmd_timeout*>(raw);
      command_timeout_ms_ = static_cast<unsigned>(std::min(60000, std::max(100, q->timeout)));
      confirm(c, 0);
      return true;
    }
    case CO_GW_SRV_SET_BOOTUP_IND: {
      const auto* q = reinterpret_cast<const co_gw_req_set_bootup_ind*>(raw);
      if (!net_of(q->net, false)) return true;
      if (q->cs)
        bootup_off_.erase(number);
      else
        bootup_off_.insert(number);
      confirm(c, 0);
      return true;
    }
    case CO_GW_SRV_SET_NET: {
      const auto* q = reinterpret_cast<const co_gw_req_net*>(raw);
      if (q->net && !gw_.numbering.count(q->net)) {
        confirm(c, CO_GW_IEC_BAD_NET);
        return true;
      }
      default_net_ = q->net;
      confirm(c, 0);
      return true;
    }
    case CO_GW_SRV_SET_NODE: {
      const auto* q = reinterpret_cast<const co_gw_req_node*>(raw);
      if (!net_of(q->net, false)) return true;
      if (q->node)
        default_node_[number] = q->node;
      else
        default_node_.erase(number);
      confirm(c, 0);
      return true;
    }
    case CO_GW_SRV_GET_VERSION: {
      // The identity of the default (else the first) master network's master.
      const MasterConfig* m = nullptr;
      if (pick_net(0, index, number, iec) && !nets_[index].cfg->is_slave()) m = &nets_[index].cfg->master;
      for (const auto& n : gw_.numbering)
        if (!m && n.second < nets_.size() && nets_[n.second].cfg && nets_[n.second].cfg->is_canopen() &&
            !nets_[n.second].cfg->is_slave())
          m = &nets_[n.second].cfg->master;
      co_gw_con_get_version con{};
      con.size = sizeof con;
      con.srv = c.srv;
      con.data = reinterpret_cast<void*>(static_cast<uintptr_t>(c.seq));
      if (m) {
        con.vendor_id = m->vendor_id;
        con.product_code = m->product_code;
        con.revision = m->revision_number;
        con.serial_nr = m->serial_number;
      }
      con.gw_class = 3;  // a gateway with an NMT master
      con.prot_hi = CO_GW_PROT_HI;
      con.prot_lo = CO_GW_PROT_LO;
      text_->format(*reinterpret_cast<const co_gw_srv*>(&con));
      return true;
    }
    case CO_GW_SRV_LSS_SWITCH: {
      const auto* q = reinterpret_cast<const co_gw_req_lss_switch*>(raw);
      if (q->mode != 0) {
        refuse(c, "lss_switch_glob 1 (every device to LSS configuration) is not served: use lss_switch_sel",
               CO_GW_IEC_BAD_SRV);
        return true;
      }
      if (!net_of(q->net, true) || !changes_allowed(c)) return true;
      // Every LSS operation of the gateway ends with all devices in LSS
      // waiting already: nothing to send.
      selected_ = false;
      confirm(c, 0);
      return true;
    }
    case CO_GW_SRV_LSS_SWITCH_SEL: {
      const auto* q = reinterpret_cast<const co_gw_req_lss_switch_sel*>(raw);
      if (!net_of(q->net, true) || !changes_allowed(c)) return true;
      // Remembered for the session's next LSS requests; each of them selects
      // the device again as one LSS operation.
      selection_ = {q->id.vendor_id, q->id.product_code, q->id.revision, q->id.serial_nr};
      selected_ = true;
      confirm(c, 0);
      return true;
    }
    case CO_GW_SRV_LSS_SET_ID: {
      const auto* q = reinterpret_cast<const co_gw_req_node*>(raw);
      if (!net_of(q->net, true) || !changes_allowed(c) || !need_selection()) return true;
      const Config& cfg = *nets_[index].cfg;
      if (q->node < 1 || q->node > 127) {
        refuse(c, "node ID " + std::to_string(q->node) + " cannot be set (1-127)");
        return true;
      }
      if (q->node == cfg.master.node_id) {
        refuse(c, "node ID " + std::to_string(q->node) + " is the master's");
        return true;
      }
      DiagRequest r = lss_request("lss_set_id");
      r.node = q->node;
      r.store = false;  // only lss_store stores
      submit(c, index, number, std::move(r), now, command_timeout_ms_);
      return false;
    }
    case CO_GW_SRV_LSS_SET_RATE: {
      const auto* q = reinterpret_cast<const co_gw_req_lss_set_rate*>(raw);
      if (!net_of(q->net, true) || !changes_allowed(c) || !need_selection()) return true;
      unsigned kbit = q->bitsel == 0 && q->bitidx < sizeof kLssRates / sizeof *kLssRates ? kLssRates[q->bitidx] : 0;
      if (!kbit) {
        refuse(c, "bit timing table " + std::to_string(q->bitsel) + " index " + std::to_string(q->bitidx) +
                      " is not a CiA 305 rate this gateway sets (table 0, index 0-4 or 6-8)");
        return true;
      }
      DiagRequest r = lss_request("lss_set_bitrate");
      r.bitrate_kbit = kbit;
      r.store = false;
      submit(c, index, number, std::move(r), now, command_timeout_ms_);
      return false;
    }
    case CO_GW_SRV_LSS_STORE: {
      const auto* q = reinterpret_cast<const co_gw_req_net*>(raw);
      if (!net_of(q->net, true) || !changes_allowed(c) || !need_selection()) return true;
      submit(c, index, number, lss_request("lss_store"), now, command_timeout_ms_);
      return false;
    }
    case CO_GW_SRV_LSS_GET_ID:
    case CO_GW_SRV_LSS_GET_LSSID: {
      const unsigned net_req = c.srv == CO_GW_SRV_LSS_GET_ID ? reinterpret_cast<const co_gw_req_net*>(raw)->net
                                                             : reinterpret_cast<const co_gw_req_lss_get_lssid*>(raw)->net;
      // LSS frames are sent, so this needs allow_changes too.
      if (!net_of(net_req, true) || !changes_allowed(c) || !need_selection()) return true;
      submit(c, index, number, lss_request("lss_inquire"), now, command_timeout_ms_);
      return false;
    }
    case CO_GW_SRV__LSS_FASTSCAN: {
      const auto* q = reinterpret_cast<const co_gw_req__lss_scan*>(raw);
      if (!net_of(q->net, true) || !changes_allowed(c)) return true;
      const co_id& id = q->id_1;
      const co_id& mask = q->id_2;
      const bool known = mask.vendor_id == 0xFFFFFFFFu && mask.product_code == 0xFFFFFFFFu;
      const bool unknown = mask.vendor_id == 0 && mask.product_code == 0;
      if ((!known && !unknown) || mask.revision || mask.serial_nr) {
        refuse(c, "only the vendor ID and product code can be fixed in the search (masks 0 or 0xFFFFFFFF; "
                  "revision and serial number masks 0)");
        return true;
      }
      DiagRequest r = request("lss_find");
      if (known) {
        r.lss_known = true;
        r.lss[0] = id.vendor_id;
        r.lss[1] = id.product_code;
      }
      c.step = 0;
      submit(c, index, number, std::move(r), now, std::max(command_timeout_ms_, kLssSearchTimeoutMs));
      return false;
    }
    default:
      refuse(c, not_served(c.srv), CO_GW_IEC_BAD_SRV);
      return true;
  }
}

bool Cia309Session::finish(Command& c, const std::string& line, clock::time_point now) {
  Answer a(line);
  if (!a.ok) {
    fail(c, a.error.empty() ? "refused" : a.error);
    return true;
  }
  switch (c.srv) {
    case CO_GW_SRV_SDO_UP:
    case CO_GW_SRV_SDO_DN: {
      if (!a.truth("success")) {
        const cJSON* ac = a.get("abort_code");
        if (cJSON_IsNumber(ac)) {
          confirm(c, 0, static_cast<uint32_t>(ac->valuedouble));
        } else {
          std::string why = a.text("error");
          if (why == "timeout")
            confirm(c, CO_GW_IEC_TIMEOUT);
          else
            fail(c, why.empty() ? "SDO failed" : why);
        }
        return true;
      }
      if (c.srv == CO_GW_SRV_SDO_DN) {
        confirm(c, 0);
        return true;
      }
      const auto* q = reinterpret_cast<const co_gw_req_sdo_up*>(c.req.data());
      std::vector<uint8_t> data = parse_hex(a.text("data"));
      if (!Cia309Text::value_fits(q->type, data.data(), data.size())) {
        // The object is not of the type the client named.
        confirm(c, 0, 0x06070010u);
        return true;
      }
      std::vector<uint8_t> buf(std::max(CO_GW_CON_SDO_UP_SIZE + data.size(), sizeof(co_gw_con_sdo_up)), 0);
      auto* con = reinterpret_cast<co_gw_con_sdo_up*>(buf.data());
      con->size = buf.size();
      con->srv = c.srv;
      con->data = reinterpret_cast<void*>(static_cast<uintptr_t>(c.seq));
      con->type = q->type;
      con->len = static_cast<co_unsigned32_t>(data.size());
      if (!data.empty()) std::memcpy(con->val, data.data(), data.size());
      text_->format(*reinterpret_cast<const co_gw_srv*>(con));
      return true;
    }
    case CO_GW_SRV_PDO_READ: {
      const auto* q = reinterpret_cast<const co_gw_req_pdo_read*>(c.req.data());
      co_gw_con_pdo_read con{};
      con.srv = c.srv;
      con.data = reinterpret_cast<void*>(static_cast<uintptr_t>(c.seq));
      con.net = static_cast<co_unsigned16_t>(c.number);
      con.num = q->num;
      const cJSON* values = a.get("values");
      const cJSON* v;
      cJSON_ArrayForEach(v, values) {
        if (con.n >= 0x40) break;
        const cJSON* raw = cJSON_GetObjectItemCaseSensitive(v, "raw");
        con.val[con.n++] = cJSON_IsString(raw) ? std::strtoull(raw->valuestring, nullptr, 10) : 0;
      }
      con.size = CO_GW_CON_PDO_READ_SIZE + con.n * sizeof con.val[0];
      text_->format(*reinterpret_cast<const co_gw_srv*>(&con));
      return true;
    }
    case CO_GW_SRV_LSS_GET_ID: {
      co_gw_con_lss_get_id con{};
      con.size = sizeof con;
      con.srv = c.srv;
      con.data = reinterpret_cast<void*>(static_cast<uintptr_t>(c.seq));
      con.id = static_cast<co_unsigned8_t>(a.number("node_id", 0xFF));
      text_->format(*reinterpret_cast<const co_gw_srv*>(&con));
      return true;
    }
    case CO_GW_SRV_LSS_GET_LSSID: {
      // The device answered its address: the part asked for (0x5A vendor
      // ID ... 0x5D serial number) is the selected one.
      const auto* q = reinterpret_cast<const co_gw_req_lss_get_lssid*>(c.req.data());
      co_gw_con_lss_get_lssid con{};
      con.size = sizeof con;
      con.srv = c.srv;
      con.data = reinterpret_cast<void*>(static_cast<uintptr_t>(c.seq));
      con.id = selection_[std::min<unsigned>(3, q->cs - 0x5A)];
      text_->format(*reinterpret_cast<const co_gw_srv*>(&con));
      return true;
    }
    case CO_GW_SRV__LSS_FASTSCAN: {
      if (a.truth("running")) {
        c.step = 1;
        c.next = now + kLssPoll;
        return false;
      }
      if (c.step == 0) {
        // Another search was running and has ended: ask for ours.
        c.step = 1;
        c.next = now;
        return false;
      }
      std::string why = a.text("error");
      const cJSON* dev = a.get("device");
      if (!why.empty()) {
        fail(c, "LSS search failed: " + why);
        return true;
      }
      if (!a.truth("found") || !dev) {
        refuse(c, "no device without a node ID answered the LSS search", CO_GW_IEC_TIMEOUT);
        return true;
      }
      static const char* const kKey[] = {"vendor_id", "product_code", "revision_number", "serial_number"};
      for (int f = 0; f < 4; ++f) {
        const cJSON* v = cJSON_GetObjectItemCaseSensitive(dev, kKey[f]);
        selection_[f] = cJSON_IsNumber(v) ? static_cast<uint32_t>(v->valuedouble) : 0;
      }
      selected_ = true;
      log_info("cia309 %s: LSS search found vendor ID 0x%08X, product code 0x%08X, revision number 0x%08X, serial "
               "number 0x%08X (now selected)",
               peer_.c_str(), selection_[0], selection_[1], selection_[2], selection_[3]);
      co_gw_con__lss_scan con{};
      con.size = sizeof con;
      con.srv = c.srv;
      con.data = reinterpret_cast<void*>(static_cast<uintptr_t>(c.seq));
      con.id.vendor_id = selection_[0];
      con.id.product_code = selection_[1];
      con.id.revision = selection_[2];
      con.id.serial_nr = selection_[3];
      text_->format(*reinterpret_cast<const co_gw_srv*>(&con));
      return true;
    }
    default:
      // NMT, LSS configure and store: done.
      confirm(c, 0);
      return true;
  }
}

void Cia309Session::event(size_t net, const DiagEvent& e) {
  unsigned number = gw_.number_of(static_cast<unsigned>(net));
  if (!number) return;
  std::string line;
  auto keep = [&](const co_gw_srv& srv) {
    // Formatted into this session's notifications, not its answers.
    std::string saved;
    saved.swap(out_);
    text_->format(srv);
    line.swap(out_);
    out_.swap(saved);
  };
  if (e.kind == DiagEvent::Emcy) {
    co_gw_ind_emcy ind{};
    ind.size = sizeof ind;
    ind.srv = CO_GW_SRV_EMCY;
    ind.net = static_cast<co_unsigned16_t>(number);
    ind.node = e.node;
    ind.ec = e.code;
    ind.er = e.er;
    std::copy(e.msef.begin(), e.msef.end(), ind.msef);
    keep(*reinterpret_cast<const co_gw_srv*>(&ind));
  } else {
    if (e.kind == DiagEvent::Bootup && bootup_off_.count(number)) return;
    co_gw_ind_ec ind{};
    ind.size = sizeof ind;
    ind.srv = CO_GW_SRV_EC;
    ind.net = static_cast<co_unsigned16_t>(number);
    ind.node = e.node;
    ind.st = e.kind == DiagEvent::State ? e.state : 0;
    ind.iec = e.kind == DiagEvent::Bootup          ? CO_GW_IEC_BOOTUP
              : e.kind == DiagEvent::HeartbeatLost ? CO_GW_IEC_HB_OCCURRED
              : e.kind == DiagEvent::GuardingLost  ? CO_GW_IEC_NG_OCCURRED
                                                   : 0;
    keep(*reinterpret_cast<const co_gw_srv*>(&ind));
  }
  // Lely's line already ends in "\r\n" (on_text); note() adds its own.
  while (!line.empty() && (line.back() == '\n' || line.back() == '\r')) line.pop_back();
  if (!line.empty()) note(line);
}

void Cia309Session::lost(uint64_t n) { notes_lost_ += n; }

}  // namespace canopen_plugin
