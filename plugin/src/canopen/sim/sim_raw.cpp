#include "sim_raw.h"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <limits>

#include "can/signals.h"
#include "cJSON.h"

namespace canopen_sim {

namespace {

constexpr uint32_t kStdMax = 0x7FF;
constexpr uint32_t kExtMax = 0x1FFFFFFF;

struct Ctx {
  std::string path;
  std::vector<std::string>& errors;
  bool fail(const std::string& what) {
    errors.push_back(path + ": " + what);
    return false;
  }
};

std::string at(const std::string& path, const std::string& key) { return path + "." + key; }
std::string at(const std::string& path, const std::string& key, size_t i) {
  return path + "." + key + "[" + std::to_string(i) + "]";
}

bool keys(Ctx& c, const cJSON* o, std::initializer_list<const char*> allowed) {
  bool ok = true;
  for (const cJSON* k = o->child; k; k = k->next) {
    bool found = false;
    for (const char* a : allowed) found = found || std::strcmp(k->string, a) == 0;
    if (!found) ok = c.fail(std::string("unknown key \"") + k->string + "\"");
  }
  return ok;
}

bool get_uint(Ctx& c, const cJSON* o, const char* key, uint64_t min, uint64_t max, uint64_t& out, bool required) {
  const cJSON* v = cJSON_GetObjectItemCaseSensitive(o, key);
  if (!v) return required ? c.fail(std::string("\"") + key + "\" is missing") : true;
  if (!cJSON_IsNumber(v) || v->valuedouble != std::floor(v->valuedouble) || v->valuedouble < static_cast<double>(min) ||
      v->valuedouble > static_cast<double>(max))
    return c.fail(std::string("\"") + key + "\" must be an integer " + std::to_string(min) + "-" + std::to_string(max));
  out = static_cast<uint64_t>(v->valuedouble);
  return true;
}

bool get_bool(Ctx& c, const cJSON* o, const char* key, bool& out) {
  const cJSON* v = cJSON_GetObjectItemCaseSensitive(o, key);
  if (!v) return true;
  if (!cJSON_IsBool(v)) return c.fail(std::string("\"") + key + "\" must be true or false");
  out = cJSON_IsTrue(v);
  return true;
}

bool get_bytes(Ctx& c, const cJSON* o, const char* key, std::vector<uint8_t>& out) {
  const cJSON* v = cJSON_GetObjectItemCaseSensitive(o, key);
  if (!v) return true;
  if (!cJSON_IsArray(v) || cJSON_GetArraySize(v) > 8)
    return c.fail(std::string("\"") + key + "\" must be a list of up to 8 bytes");
  for (const cJSON* b = v->child; b; b = b->next) {
    if (!cJSON_IsNumber(b) || b->valuedouble != std::floor(b->valuedouble) || b->valuedouble < 0 || b->valuedouble > 255)
      return c.fail(std::string("\"") + key + "\" must be a list of up to 8 bytes (0-255)");
    out.push_back(static_cast<uint8_t>(b->valuedouble));
  }
  return true;
}

// id, extended, rtr, dlc and data of a frame object.
bool parse_frame(Ctx& c, const cJSON* o, RawFrame& f, bool need_dlc_or_data) {
  bool ok = true;
  ok = get_bool(c, o, "extended", f.extended) && ok;
  ok = get_bool(c, o, "rtr", f.rtr) && ok;
  uint64_t id = 0;
  if (get_uint(c, o, "id", 0, f.extended ? kExtMax : kStdMax, id, true))
    f.id = static_cast<uint32_t>(id);
  else
    ok = false;
  std::vector<uint8_t> data;
  ok = get_bytes(c, o, "data", data) && ok;
  std::copy(data.begin(), data.end(), f.data);
  uint64_t dlc = data.size();
  bool has_dlc = cJSON_GetObjectItemCaseSensitive(o, "dlc") != nullptr;
  if (!get_uint(c, o, "dlc", 0, 8, dlc, false)) return false;
  if (has_dlc && dlc < data.size()) ok = c.fail("\"dlc\" is shorter than \"data\"");
  if (!has_dlc && data.empty() && need_dlc_or_data) ok = c.fail("needs \"dlc\" or \"data\"");
  f.dlc = static_cast<uint8_t>(dlc);
  return ok;
}

bool parse_signal(Ctx& c, const cJSON* o, const RawFrame& f, RawSimSignal& s) {
  if (!cJSON_IsObject(o)) return c.fail("must be an object");
  bool ok = keys(c, o, {"name", "start_bit", "length", "byte_order", "signed", "scale", "offset", "source"});
  const cJSON* name = cJSON_GetObjectItemCaseSensitive(o, "name");
  if (name && !cJSON_IsString(name)) ok = c.fail("\"name\" must be text");
  if (cJSON_IsString(name)) s.name = name->valuestring;
  uint64_t start = 0, length = 0;
  ok = get_uint(c, o, "start_bit", 0, 63, start, true) && ok;
  ok = get_uint(c, o, "length", 1, 64, length, true) && ok;
  const cJSON* order = cJSON_GetObjectItemCaseSensitive(o, "byte_order");
  if (order && !(cJSON_IsString(order) && (std::strcmp(order->valuestring, "little") == 0 ||
                                           std::strcmp(order->valuestring, "big") == 0)))
    ok = c.fail("\"byte_order\" must be little or big");
  s.big_endian = cJSON_IsString(order) && std::strcmp(order->valuestring, "big") == 0;
  ok = get_bool(c, o, "signed", s.is_signed) && ok;
  for (const char* k : {"scale", "offset"}) {
    const cJSON* v = cJSON_GetObjectItemCaseSensitive(o, k);
    if (!v) continue;
    if (!cJSON_IsNumber(v) || (std::strcmp(k, "scale") == 0 && v->valuedouble == 0)) {
      ok = c.fail(std::string("\"") + k + "\" must be a number" + (std::strcmp(k, "scale") == 0 ? " other than 0" : ""));
      continue;
    }
    (std::strcmp(k, "scale") == 0 ? s.scale : s.offset) = v->valuedouble;
  }
  const cJSON* src = cJSON_GetObjectItemCaseSensitive(o, "source");
  if (!src) {
    ok = c.fail("\"source\" is missing");
  } else {
    char* text = cJSON_PrintUnformatted(src);
    s.source_json = text ? text : "";
    cJSON_free(text);
  }
  s.start_bit = static_cast<unsigned>(start);
  s.length = static_cast<unsigned>(length);
  if (ok && !canworks_can::signal_fits(s.start_bit, s.length, s.big_endian, f.dlc))
    ok = c.fail("does not fit the frame's " + std::to_string(f.dlc) + " bytes");
  return ok;
}

bool parse_send(Ctx& c, const cJSON* o, RawSimSend& s) {
  if (!cJSON_IsObject(o)) return c.fail("must be an object");
  bool ok = keys(c, o, {"name", "id", "extended", "rtr", "dlc", "data", "period_ms", "signals"});
  const cJSON* name = cJSON_GetObjectItemCaseSensitive(o, "name");
  if (name && !cJSON_IsString(name)) ok = c.fail("\"name\" must be text");
  if (cJSON_IsString(name)) s.name = name->valuestring;
  ok = parse_frame(c, o, s.frame, true) && ok;
  uint64_t period = 0;
  ok = get_uint(c, o, "period_ms", 1, 60000, period, true) && ok;
  s.period_ms = static_cast<unsigned>(period);
  const cJSON* sigs = cJSON_GetObjectItemCaseSensitive(o, "signals");
  if (sigs && !cJSON_IsArray(sigs)) return c.fail("\"signals\" must be a list");
  if (sigs && s.frame.rtr && cJSON_GetArraySize(sigs) > 0) ok = c.fail("a remote frame has no signals");
  size_t i = 0;
  for (const cJSON* j = sigs ? sigs->child : nullptr; j; j = j->next, ++i) {
    Ctx sc{at(c.path, "signals", i), c.errors};
    RawSimSignal sig;
    if (parse_signal(sc, j, s.frame, sig))
      s.signals.push_back(sig);
    else
      ok = false;
  }
  return ok;
}

bool parse_reply(Ctx& c, const cJSON* o, RawSimReply& r) {
  if (!cJSON_IsObject(o)) return c.fail("must be an object");
  bool ok = keys(c, o, {"on", "send", "delay_ms"});
  const cJSON* on = cJSON_GetObjectItemCaseSensitive(o, "on");
  const cJSON* send = cJSON_GetObjectItemCaseSensitive(o, "send");
  if (!cJSON_IsObject(on)) ok = c.fail("\"on\" must be an object with \"id\"");
  if (!cJSON_IsObject(send)) ok = c.fail("\"send\" must be a frame object");
  uint64_t delay = 0;
  ok = get_uint(c, o, "delay_ms", 0, 60000, delay, false) && ok;
  r.delay_ms = static_cast<unsigned>(delay);
  if (cJSON_IsObject(on)) {
    Ctx oc{at(c.path, "on"), c.errors};
    ok = keys(oc, on, {"id", "extended", "data", "mask"}) && ok;
    ok = get_bool(oc, on, "extended", r.on_extended) && ok;
    uint64_t id = 0;
    if (get_uint(oc, on, "id", 0, r.on_extended ? kExtMax : kStdMax, id, true))
      r.on_id = static_cast<uint32_t>(id);
    else
      ok = false;
    ok = get_bytes(oc, on, "data", r.on_data) && ok;
    ok = get_bytes(oc, on, "mask", r.on_mask) && ok;
    if (!r.on_mask.empty() && r.on_mask.size() != r.on_data.size())
      ok = oc.fail("\"mask\" must have as many bytes as \"data\"");
    if (r.on_mask.empty()) r.on_mask.assign(r.on_data.size(), 0xFF);
  }
  if (cJSON_IsObject(send)) {
    Ctx sc{at(c.path, "send"), c.errors};
    ok = keys(sc, send, {"id", "extended", "rtr", "dlc", "data"}) && ok;
    ok = parse_frame(sc, send, r.send, false) && ok;
  }
  return ok;
}

}  // namespace

bool parse_raw_devices(const cJSON* list, std::vector<RawDeviceSpec>& out, std::vector<std::string>& errors) {
  size_t before = errors.size();
  if (!cJSON_IsArray(list)) {
    errors.push_back("raw_devices: must be a list");
    return false;
  }
  size_t i = 0;
  for (const cJSON* d = list->child; d; d = d->next, ++i) {
    Ctx c{"raw_devices[" + std::to_string(i) + "]", errors};
    if (!cJSON_IsObject(d)) {
      c.fail("must be an object");
      continue;
    }
    keys(c, d, {"name", "network", "send", "replies"});
    RawDeviceSpec spec;
    const cJSON* name = cJSON_GetObjectItemCaseSensitive(d, "name");
    if (!cJSON_IsString(name) || !*name->valuestring)
      c.fail("\"name\" is missing");
    else
      spec.name = name->valuestring;
    for (const RawDeviceSpec& o : out)
      if (!spec.name.empty() && o.name == spec.name) c.fail("another plain CAN device is also called \"" + spec.name + "\"");
    const cJSON* net = cJSON_GetObjectItemCaseSensitive(d, "network");
    if (net && !cJSON_IsString(net)) c.fail("\"network\" must be text");
    if (cJSON_IsString(net)) spec.network = net->valuestring;
    const cJSON* sends = cJSON_GetObjectItemCaseSensitive(d, "send");
    const cJSON* replies = cJSON_GetObjectItemCaseSensitive(d, "replies");
    if (sends && !cJSON_IsArray(sends)) c.fail("\"send\" must be a list");
    if (replies && !cJSON_IsArray(replies)) c.fail("\"replies\" must be a list");
    if (cJSON_GetArraySize(sends) + cJSON_GetArraySize(replies) == 0) c.fail("has neither \"send\" nor \"replies\"");
    size_t j = 0;
    for (const cJSON* s = cJSON_IsArray(sends) ? sends->child : nullptr; s; s = s->next, ++j) {
      Ctx sc{at(c.path, "send", j), errors};
      RawSimSend send;
      if (parse_send(sc, s, send)) spec.sends.push_back(send);
    }
    j = 0;
    for (const cJSON* r = cJSON_IsArray(replies) ? replies->child : nullptr; r; r = r->next, ++j) {
      Ctx rc{at(c.path, "replies", j), errors};
      RawSimReply reply;
      if (parse_reply(rc, r, reply)) spec.replies.push_back(reply);
    }
    out.push_back(std::move(spec));
  }
  return errors.size() == before;
}

struct RawDevice::Bound {
  std::vector<std::unique_ptr<Source>> sources;  // one per signal of the send
};

RawDevice::RawDevice(RawDeviceSpec spec) : spec_(std::move(spec)), next_due_(spec_.sends.size(), 0) {}
RawDevice::~RawDevice() = default;

bool RawDevice::bind(const std::string& base_dir, const ExprResolver& resolver, std::vector<std::string>& errors) {
  bool ok = true;
  bound_.clear();
  for (size_t i = 0; i < spec_.sends.size(); ++i) {
    std::unique_ptr<Bound> b(new Bound);
    for (size_t j = 0; j < spec_.sends[i].signals.size(); ++j) {
      const RawSimSignal& s = spec_.sends[i].signals[j];
      std::string where = "plain CAN device " + spec_.name + ", " +
                          (spec_.sends[i].name.empty() ? raw_frame_text(spec_.sends[i].frame) : spec_.sends[i].name) +
                          ", signal " + (s.name.empty() ? std::to_string(j) : s.name);
      cJSON* json = cJSON_Parse(s.source_json.c_str());
      std::string err;
      std::unique_ptr<Source> src = Source::parse(json, base_dir, err);
      cJSON_Delete(json);
      ExprError xerr;
      if (src && !src->bind(resolver, xerr)) {
        err = xerr.message + " (at " + std::to_string(xerr.position) + ")";
        src.reset();
      }
      if (!src) {
        errors.push_back(where + ": " + err);
        ok = false;
      }
      b->sources.push_back(std::move(src));
    }
    bound_.push_back(std::move(b));
  }
  return ok;
}

void RawDevice::power_on(uint64_t now_ms) {
  powered_ = true;
  start_ms_ = now_ms;
  std::fill(next_due_.begin(), next_due_.end(), now_ms);
  pending_.clear();
  for (auto& b : bound_)
    for (auto& s : b->sources)
      if (s) s->restart();
}

void RawDevice::power_off() {
  powered_ = false;
  pending_.clear();
}

RawFrame RawDevice::build(size_t i, double t, ExprContext& ctx) {
  const RawSimSend& send = spec_.sends[i];
  RawFrame f = send.frame;
  for (size_t j = 0; j < send.signals.size() && i < bound_.size(); ++j) {
    Source* src = bound_[i]->sources[j].get();
    if (!src) continue;
    const RawSimSignal& s = send.signals[j];
    ctx.t = t;
    Value v = src->eval(t, ctx);
    if (v.is_string || !std::isfinite(v.num)) continue;
    double raw = std::round((v.num - s.offset) / s.scale);
    double lo = s.is_signed ? -std::ldexp(1.0, static_cast<int>(s.length) - 1) : 0;
    double hi = s.is_signed ? std::ldexp(1.0, static_cast<int>(s.length) - 1) - 1 : std::ldexp(1.0, static_cast<int>(s.length)) - 1;
    raw = std::min(std::max(raw, lo), hi);
    uint64_t bits = s.is_signed && raw < 0 ? static_cast<uint64_t>(static_cast<int64_t>(raw))
                                           : static_cast<uint64_t>(raw);
    canworks_can::pack_signal(f.data, s.start_bit, s.length, s.big_endian, bits);
  }
  if (dlc_fault_ >= 0) f.dlc = static_cast<uint8_t>(dlc_fault_);
  return f;
}

void RawDevice::due(uint64_t now_ms, std::vector<RawFrame>& out, ExprContext& ctx) {
  if (!powered_) return;
  double t = static_cast<double>(now_ms - start_ms_) / 1000.0;
  for (size_t i = 0; i < spec_.sends.size(); ++i) {
    if (now_ms < next_due_[i]) continue;
    out.push_back(build(i, t, ctx));
    ++sent_;
    uint64_t period = spec_.sends[i].period_ms;
    next_due_[i] += period;
    // Late by more than a period (a stalled loop): send once and go on from
    // now rather than catching up with a burst.
    if (next_due_[i] <= now_ms) next_due_[i] = now_ms + period;
  }
  for (size_t k = 0; k < pending_.size();) {
    if (pending_[k].at <= now_ms) {
      RawFrame f = pending_[k].frame;
      if (dlc_fault_ >= 0) f.dlc = static_cast<uint8_t>(dlc_fault_);
      out.push_back(f);
      ++sent_;
      pending_.erase(pending_.begin() + static_cast<long>(k));
    } else {
      ++k;
    }
  }
}

void RawDevice::on_frame(const RawFrame& frame, uint64_t now_ms) {
  if (!powered_) return;
  for (const RawSimReply& r : spec_.replies) {
    if (frame.id != r.on_id || frame.extended != r.on_extended) continue;
    bool match = frame.dlc >= r.on_data.size();
    for (size_t b = 0; match && b < r.on_data.size(); ++b)
      match = (frame.data[b] & r.on_mask[b]) == (r.on_data[b] & r.on_mask[b]);
    if (!match) continue;
    if (pending_.size() >= 64) return;  // a flood of requests: drop, as a busy device would
    pending_.push_back({now_ms + r.delay_ms, r.send});
  }
}

uint64_t RawDevice::next_in(uint64_t now_ms) const {
  if (!powered_) return std::numeric_limits<uint64_t>::max();
  uint64_t next = std::numeric_limits<uint64_t>::max();
  for (uint64_t d : next_due_) next = std::min(next, d);
  for (const Pending& p : pending_) next = std::min(next, p.at);
  if (next == std::numeric_limits<uint64_t>::max()) return next;
  return next <= now_ms ? 0 : next - now_ms;
}

std::string raw_frame_text(const RawFrame& f) {
  char buf[64];
  int n = std::snprintf(buf, sizeof buf, f.extended ? "0x%08X [%u]" : "0x%03X [%u]", f.id, f.dlc);
  std::string s(buf, static_cast<size_t>(n));
  if (f.rtr) return s + " remote";
  for (unsigned i = 0; i < f.dlc && i < 8; ++i) {
    std::snprintf(buf, sizeof buf, " %02X", f.data[i]);
    s += buf;
  }
  return s;
}

}  // namespace canopen_sim

namespace canopen_sim {

bool raw_device_action(RawDevice& d, const std::string& action, const std::string& what, int dlc, uint64_t now_ms,
                       std::string& err) {
  if (action == "fault" && what == "stop") {
    d.power_off();
  } else if (action == "fault" && what == "wrong_dlc" && dlc >= 0 && dlc <= 8) {
    d.set_dlc_fault(dlc);
  } else if (action == "clear" && (what == "stop" || what == "all")) {
    if (!d.powered()) d.power_on(now_ms);
    if (what == "all") d.set_dlc_fault(-1);
  } else if (action == "clear" && what == "wrong_dlc") {
    d.set_dlc_fault(-1);
  } else {
    err = "unknown " + action + " \"" + what + "\" for a plain CAN device";
    return false;
  }
  return true;
}

namespace {

bool parse_raw_steps(Ctx& c, const cJSON* arr, std::vector<RawScenarioStep>& out);

bool parse_raw_step(Ctx& c, const cJSON* o, RawScenarioStep& s) {
  if (!cJSON_IsObject(o)) return c.fail("must be an object");
  bool ok = keys(c, o, {"device", "at_ms", "after_ms", "fault", "clear", "log", "repeat"});
  uint64_t v = 0;
  if (get_uint(c, o, "at_ms", 0, 0x7FFFFFFF, v, false) && cJSON_GetObjectItemCaseSensitive(o, "at_ms")) {
    s.has_at = true;
    s.at_ms = static_cast<unsigned>(v);
  }
  if (get_uint(c, o, "after_ms", 0, 0x7FFFFFFF, v, false) && cJSON_GetObjectItemCaseSensitive(o, "after_ms")) {
    s.has_after = true;
    s.after_ms = static_cast<unsigned>(v);
  }
  if (s.has_at && s.has_after) ok = c.fail("a step has \"at_ms\" or \"after_ms\", not both");
  int actions = 0;
  for (const char* a : {"fault", "clear", "log", "repeat"})
    if (cJSON_GetObjectItemCaseSensitive(o, a)) {
      ++actions;
      s.action = a;
    }
  if (actions != 1)
    return c.fail("a step on a plain CAN network needs one action: \"fault\" or \"clear\" with \"device\", "
                  "\"log\" or \"repeat\"");
  const cJSON* a = cJSON_GetObjectItemCaseSensitive(o, s.action.c_str());
  const cJSON* dev = cJSON_GetObjectItemCaseSensitive(o, "device");
  if (s.action == "fault" || s.action == "clear") {
    if (!cJSON_IsString(dev) || !*dev->valuestring) return c.fail("\"" + s.action + "\" needs \"device\"");
    s.device = dev->valuestring;
    if (s.action == "clear") {
      if (!cJSON_IsString(a) || (std::strcmp(a->valuestring, "stop") != 0 &&
                                 std::strcmp(a->valuestring, "wrong_dlc") != 0 && std::strcmp(a->valuestring, "all") != 0))
        return c.fail("\"clear\" must be \"stop\", \"wrong_dlc\" or \"all\"");
      s.what = a->valuestring;
      return ok;
    }
    const cJSON* stop = cJSON_GetObjectItemCaseSensitive(a, "stop");
    const cJSON* dlc = cJSON_GetObjectItemCaseSensitive(a, "wrong_dlc");
    if (!cJSON_IsObject(a) || cJSON_GetArraySize(a) != 1 || (!cJSON_IsTrue(stop) && !dlc))
      return c.fail("\"fault\" must be {\"stop\": true} or {\"wrong_dlc\": 0-8}");
    if (stop) {
      s.what = "stop";
      return ok;
    }
    Ctx fc{at(c.path, "fault"), c.errors};
    if (!get_uint(fc, a, "wrong_dlc", 0, 8, v, true)) return false;
    s.what = "wrong_dlc";
    s.dlc = static_cast<int>(v);
    return ok;
  }
  if (dev) ok = c.fail("\"device\" belongs to a \"fault\" or \"clear\" step");
  if (s.action == "log") {
    if (!cJSON_IsString(a)) return c.fail("\"log\" must be text");
    s.log = a->valuestring;
    return ok;
  }
  Ctx rc{at(c.path, "repeat"), c.errors};
  if (!cJSON_IsObject(a)) return c.fail("\"repeat\" must be an object with \"steps\"");
  ok = keys(rc, a, {"count", "steps"}) && ok;
  if (get_uint(rc, a, "count", 0, 0x7FFFFFFF, v, false) && cJSON_GetObjectItemCaseSensitive(a, "count"))
    s.count = static_cast<unsigned>(v);
  return parse_raw_steps(rc, cJSON_GetObjectItemCaseSensitive(a, "steps"), s.steps) && ok;
}

bool parse_raw_steps(Ctx& c, const cJSON* arr, std::vector<RawScenarioStep>& out) {
  if (!cJSON_IsArray(arr) || !arr->child) return c.fail("\"steps\" must be a non-empty list");
  bool ok = true;
  size_t i = 0;
  for (const cJSON* o = arr->child; o; o = o->next, ++i) {
    Ctx sc{at(c.path, "steps", i), c.errors};
    RawScenarioStep s;
    if (parse_raw_step(sc, o, s))
      out.push_back(std::move(s));
    else
      ok = false;
  }
  return ok;
}

void collect_devices(const std::vector<RawScenarioStep>& steps, std::vector<std::string>& out) {
  for (const auto& s : steps) {
    if (!s.device.empty()) out.push_back(s.device);
    collect_devices(s.steps, out);
  }
}

}  // namespace

bool parse_raw_scenarios(const cJSON* scenarios, std::vector<RawScenario>& out, std::vector<std::string>& errors) {
  size_t before = errors.size();
  if (!cJSON_IsObject(scenarios)) {
    errors.push_back("scenarios: must be an object of name -> scenario");
    return false;
  }
  for (const cJSON* o = scenarios->child; o; o = o->next) {
    Ctx c{std::string("scenarios.") + o->string, errors};
    if (!cJSON_IsObject(o)) {
      c.fail("must be an object");
      continue;
    }
    keys(c, o, {"autostart", "test", "description", "steps"});
    RawScenario sc;
    sc.name = o->string;
    get_bool(c, o, "autostart", sc.autostart);
    if (parse_raw_steps(c, cJSON_GetObjectItemCaseSensitive(o, "steps"), sc.steps)) out.push_back(std::move(sc));
  }
  return errors.size() == before;
}

void RawScenarioRunner::start(const RawScenario& sc, uint64_t now_ms) {
  std::vector<std::string> names;
  collect_devices(sc.steps, names);
  for (const auto& n : names) {
    bool found = false;
    for (RawDevice* d : devices_) found = found || d->name() == n;
    if (!found) {
      if (log_) log_("scenario " + sc.name + ": no plain CAN device \"" + n + "\" is simulated on this network; not started");
      return;
    }
  }
  Run r;
  r.name = sc.name;
  r.start = r.prev_end = now_ms;
  Frame f;
  f.steps = &sc.steps;
  r.stack.push_back(f);
  runs_.push_back(std::move(r));
  if (log_) log_("scenario " + sc.name + " started");
}

bool RawScenarioRunner::due_at(const Run& r, uint64_t& at) const {
  const Frame& f = r.stack.back();
  if (f.i >= f.steps->size()) return false;
  const RawScenarioStep& s = (*f.steps)[f.i];
  at = s.has_at ? r.start + s.at_ms : s.has_after ? r.prev_end + s.after_ms : 0;
  return true;
}

void RawScenarioRunner::step(uint64_t now_ms) {
  for (size_t k = runs_.size(); k-- > 0;) {
    Run& r = runs_[k];
    // A bounded number of steps per call: "repeat forever" without times
    // cannot hang the I/O thread.
    for (int n = 0; n < 1000; ++n) {
      Frame& f = r.stack.back();
      if (f.i >= f.steps->size()) {
        if (f.forever || f.remaining) {
          if (!f.forever) --f.remaining;
          f.i = 0;
          continue;
        }
        r.stack.pop_back();
        if (r.stack.empty()) break;
        r.stack.back().i++;
        continue;
      }
      uint64_t at = 0;
      due_at(r, at);
      if (at > now_ms) break;
      const RawScenarioStep& s = (*f.steps)[f.i];
      if (s.action == "repeat") {
        Frame nf;
        nf.steps = &s.steps;
        nf.forever = s.count == 0;
        nf.remaining = s.count ? s.count - 1 : 0;
        r.stack.push_back(nf);
        continue;
      }
      if (s.action == "log") {
        if (log_) log_("scenario " + r.name + ": " + s.log);
      } else {
        for (RawDevice* d : devices_) {
          if (d->name() != s.device) continue;
          std::string err;
          if (!raw_device_action(*d, s.action, s.what, s.dlc, now_ms, err) && log_)
            log_("scenario " + r.name + ": " + err);
          else if (log_)
            log_("scenario " + r.name + ": " + s.action + " " + s.what + " on plain CAN device " + s.device);
        }
      }
      r.prev_end = now_ms;
      f.i++;
    }
    if (r.stack.empty()) {
      if (log_) log_("scenario " + r.name + " ended");
      runs_.erase(runs_.begin() + static_cast<long>(k));
    }
  }
}

uint64_t RawScenarioRunner::next_in(uint64_t now_ms) const {
  uint64_t next = UINT64_MAX;
  for (const Run& r : runs_) {
    uint64_t at = 0;
    if (!due_at(r, at)) {
      next = 0;  // a frame ends or repeats: at once
      continue;
    }
    uint64_t d = at > now_ms ? at - now_ms : 0;
    if (d < next) next = d;
  }
  return next;
}

}  // namespace canopen_sim
