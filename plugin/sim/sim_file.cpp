#include "sim_file.h"

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <set>
#include <sstream>

#include "cJSON.h"
#include "sim_expr.h"
#include "sim_source.h"

namespace canopen_sim {

namespace {

bool known_keys(const cJSON* o, std::initializer_list<const char*> keys, std::string& err) {
  for (const cJSON* c = o->child; c; c = c->next) {
    bool ok = false;
    for (const char* k : keys) ok = ok || std::strcmp(c->string, k) == 0;
    if (!ok) {
      err = std::string("unknown key \"") + c->string + "\"";
      return false;
    }
  }
  return true;
}

bool get_uint(const cJSON* o, const char* key, unsigned min, unsigned max, unsigned& out, std::string& err) {
  const cJSON* v = cJSON_GetObjectItemCaseSensitive(o, key);
  if (!v) return true;
  if (!cJSON_IsNumber(v) || v->valuedouble != static_cast<double>(static_cast<long long>(v->valuedouble)) ||
      v->valuedouble < min || v->valuedouble > max) {
    err = std::string("\"") + key + "\" must be an integer " + std::to_string(min) + "-" + std::to_string(max);
    return false;
  }
  out = static_cast<unsigned>(v->valuedouble);
  return true;
}

bool parse_hex_bytes(const std::string& s, uint8_t* out, size_t n) {
  if (s.size() != n * 2) return false;
  for (size_t i = 0; i < n; ++i) {
    char b[3] = {s[2 * i], s[2 * i + 1], 0};
    char* e = nullptr;
    long v = std::strtol(b, &e, 16);
    if (*e) return false;
    out[i] = static_cast<uint8_t>(v);
  }
  return true;
}

std::string join_path(const std::string& dir, const std::string& file) {
  if (file.empty() || file[0] == '/' || dir.empty()) return file;
  return dir + "/" + file;
}

bool parse_identity(const cJSON* o, std::map<uint8_t, uint32_t>& out, std::string& err) {
  if (!cJSON_IsObject(o)) {
    err = "must be an object";
    return false;
  }
  static const char* names[] = {"vendor_id", "product_code", "revision_number", "serial_number"};
  if (!known_keys(o, {names[0], names[1], names[2], names[3]}, err)) return false;
  for (uint8_t i = 0; i < 4; ++i) {
    const cJSON* v = cJSON_GetObjectItemCaseSensitive(o, names[i]);
    if (!v) continue;
    uint32_t x = 0;
    if (!parse_u32(v, x)) {
      err = std::string("\"") + names[i] + "\" must be a 32-bit number";
      return false;
    }
    out[static_cast<uint8_t>(i + 1)] = x;
  }
  if (out.empty()) {
    err = "names no identity field";
    return false;
  }
  return true;
}

bool parse_condition(const cJSON* o, Condition& c, std::string& err) {
  if (!cJSON_IsObject(o)) {
    err = "a condition must be an object";
    return false;
  }
  if (!known_keys(o, {"node", "object", "bit", "eq", "ne", "lt", "le", "gt", "ge", "expr"}, err)) return false;
  const cJSON* e = cJSON_GetObjectItemCaseSensitive(o, "expr");
  if (e) {
    if (!cJSON_IsString(e) || !*e->valuestring) {
      err = "\"expr\" must be a non-empty string";
      return false;
    }
    if (o->child->next) {
      err = "a condition is either \"expr\" or node, object and a comparison";
      return false;
    }
    c.is_expr = true;
    c.expr = e->valuestring;
    return true;
  }
  const cJSON* n = cJSON_GetObjectItemCaseSensitive(o, "node");
  const cJSON* ob = cJSON_GetObjectItemCaseSensitive(o, "object");
  if (!n || !ob) {
    err = "a condition needs \"node\" and \"object\" (or \"expr\")";
    return false;
  }
  if (!parse_device_ref(n, c.node)) {
    err = "\"node\" must be a node ID 1-127 or a device name";
    return false;
  }
  if (!cJSON_IsString(ob) || !parse_obj_key(ob->valuestring, c.object)) {
    err = "\"object\" must be \"0xIIII:S\"";
    return false;
  }
  unsigned bit = 64;
  if (!get_uint(o, "bit", 0, 63, bit, err)) return false;
  if (cJSON_GetObjectItemCaseSensitive(o, "bit")) c.bit = static_cast<int>(bit);
  int ops = 0;
  for (const char* op : {"eq", "ne", "lt", "le", "gt", "ge"}) {
    const cJSON* v = cJSON_GetObjectItemCaseSensitive(o, op);
    if (!v) continue;
    ++ops;
    c.op = op;
    bool string_ok = c.op == "eq" || c.op == "ne";
    if (!parse_value(v, c.value) || (c.value.is_string && !string_ok)) {
      err = std::string("\"") + op + "\" must be a number" + (string_ok ? ", string or boolean" : "");
      return false;
    }
  }
  if (ops != 1) {
    err = "a condition needs exactly one of eq, ne, lt, le, gt, ge";
    return false;
  }
  return true;
}

bool parse_values(const cJSON* o, std::vector<std::pair<ObjKey, Value>>& out, std::string& err) {
  if (!cJSON_IsObject(o) || !o->child) {
    err = "must be an object of object -> value";
    return false;
  }
  for (const cJSON* c = o->child; c; c = c->next) {
    ObjKey k;
    Value v;
    if (!parse_obj_key(c->string, k)) {
      err = std::string("\"") + c->string + "\" is not an object (\"0xIIII:S\")";
      return false;
    }
    if (!parse_value(c, v)) {
      err = std::string("the value of ") + c->string + " must be a number, string or boolean";
      return false;
    }
    out.emplace_back(k, v);
  }
  return true;
}

bool parse_steps(const cJSON* arr, std::vector<Step>& out, const std::string& where, std::string& err);

bool parse_step(const cJSON* o, Step& s, std::string& err) {
  if (!cJSON_IsObject(o)) {
    err = "must be an object";
    return false;
  }
  if (!known_keys(o, {"node", "at_ms", "after_ms", "set", "override", "release", "source", "fault", "clear", "wait",
                      "expect", "timeout_ms", "within_ms", "for_ms", "log", "repeat"},
                  err))
    return false;
  const cJSON* n = cJSON_GetObjectItemCaseSensitive(o, "node");
  if (n && !parse_device_ref(n, s.node)) {
    err = "\"node\" must be a node ID 1-127 or a device name";
    return false;
  }
  const unsigned kMax = 0x7FFFFFFF;
  if (!get_uint(o, "at_ms", 0, kMax, s.at_ms, err) || !get_uint(o, "after_ms", 0, kMax, s.after_ms, err) ||
      !get_uint(o, "timeout_ms", 1, kMax, s.timeout_ms, err) || !get_uint(o, "within_ms", 1, kMax, s.within_ms, err) ||
      !get_uint(o, "for_ms", 1, kMax, s.for_ms, err))
    return false;
  s.has_at = cJSON_GetObjectItemCaseSensitive(o, "at_ms") != nullptr;
  s.has_after = cJSON_GetObjectItemCaseSensitive(o, "after_ms") != nullptr;
  if (s.has_at && s.has_after) {
    err = "a step has \"at_ms\" or \"after_ms\", not both";
    return false;
  }
  int actions = 0;
  for (const char* a : {"set", "override", "release", "source", "fault", "clear", "wait", "expect", "log", "repeat"}) {
    if (cJSON_GetObjectItemCaseSensitive(o, a)) {
      ++actions;
      s.action = a;
    }
  }
  if (actions != 1) {
    err = "a step needs exactly one action (set, override, release, source, fault, clear, wait, expect, log, repeat)";
    return false;
  }
  const cJSON* a = cJSON_GetObjectItemCaseSensitive(o, s.action.c_str());
  bool needs_node = s.action == "set" || s.action == "override" || s.action == "release" || s.action == "source" ||
                    s.action == "fault" || s.action == "clear";
  if (needs_node && s.node.empty()) {
    err = "\"" + s.action + "\" needs \"node\"";
    return false;
  }
  if (cJSON_GetObjectItemCaseSensitive(o, "timeout_ms") && s.action != "wait") {
    err = "\"timeout_ms\" belongs to a \"wait\" step";
    return false;
  }
  if ((s.within_ms || s.for_ms) && s.action != "expect") {
    err = "\"within_ms\" and \"for_ms\" belong to an \"expect\" step";
    return false;
  }
  if (s.within_ms && s.for_ms) {
    err = "an \"expect\" step has \"within_ms\" or \"for_ms\", not both";
    return false;
  }
  if (s.action == "set" || s.action == "override") return parse_values(a, s.values, err);
  if (s.action == "release") {
    if (cJSON_IsString(a) && std::strcmp(a->valuestring, "all") == 0) {
      s.release_all = true;
      return true;
    }
    if (!cJSON_IsArray(a)) {
      err = "\"release\" must be \"all\" or a list of objects";
      return false;
    }
    for (const cJSON* c = a->child; c; c = c->next) {
      ObjKey k;
      if (!cJSON_IsString(c) || !parse_obj_key(c->valuestring, k)) {
        err = "\"release\" must list objects (\"0xIIII:S\")";
        return false;
      }
      s.release.push_back(k);
    }
    return true;
  }
  if (s.action == "source") {
    if (!cJSON_IsObject(a) || !a->child) {
      err = "\"source\" must be an object of object -> source (or null)";
      return false;
    }
    for (const cJSON* c = a->child; c; c = c->next) {
      ObjKey k;
      if (!parse_obj_key(c->string, k)) {
        err = std::string("\"") + c->string + "\" is not an object (\"0xIIII:S\")";
        return false;
      }
      if (cJSON_IsNull(c)) {
        s.sources.emplace_back(k, "");
        continue;
      }
      std::string e;
      if (!Source::parse(c, "", e)) {
        // CSV files are only checked when the engine resolves them.
        if (e.find("cannot read") == std::string::npos) {
          err = std::string("source of ") + c->string + ": " + e;
          return false;
        }
      }
      s.sources.emplace_back(k, sim_json_text(c));
    }
    return true;
  }
  if (s.action == "fault") {
    std::string e;
    if (!parse_fault(a, s.fault, e)) {
      err = "\"fault\": " + e;
      return false;
    }
    return true;
  }
  if (s.action == "clear") {
    if (!cJSON_IsString(a) || !is_clear_name(a->valuestring)) {
      err = "\"clear\" must be a fault name or \"all\"";
      return false;
    }
    s.clear = a->valuestring;
    return true;
  }
  if (s.action == "wait" || s.action == "expect") {
    std::string e;
    if (!parse_condition(a, s.cond, e)) {
      err = "\"" + s.action + "\": " + e;
      return false;
    }
    if (s.action == "wait" && !s.timeout_ms) s.timeout_ms = 0;  // waits forever
    return true;
  }
  if (s.action == "log") {
    if (!cJSON_IsString(a)) {
      err = "\"log\" must be text";
      return false;
    }
    s.log = a->valuestring;
    return true;
  }
  // repeat
  if (!cJSON_IsObject(a)) {
    err = "\"repeat\" must be an object with \"steps\"";
    return false;
  }
  if (!known_keys(a, {"count", "steps"}, err)) return false;
  s.count = 1;
  if (!get_uint(a, "count", 0, 0x7FFFFFFF, s.count, err)) return false;
  if (!cJSON_GetObjectItemCaseSensitive(a, "count")) s.count = 0;
  return parse_steps(cJSON_GetObjectItemCaseSensitive(a, "steps"), s.steps, "repeat", err);
}

bool parse_steps(const cJSON* arr, std::vector<Step>& out, const std::string& where, std::string& err) {
  if (!cJSON_IsArray(arr) || !arr->child) {
    err = where + ": \"steps\" must be a non-empty list";
    return false;
  }
  int i = 0;
  for (const cJSON* c = arr->child; c; c = c->next) {
    ++i;
    Step s;
    std::string e;
    if (!parse_step(c, s, e)) {
      err = "step " + std::to_string(i) + ": " + e;
      return false;
    }
    out.push_back(std::move(s));
  }
  return true;
}

bool parse_behaviour(const cJSON* o, NodeBehaviour& b, const std::string& dir, bool extra, std::string& err) {
  if (!cJSON_IsObject(o)) {
    err = "must be an object";
    return false;
  }
  if (extra) {
    if (!known_keys(o, {"default_behaviour", "tick_ms", "sources", "drive", "faults", "identity", "device_type", "node",
                        "name", "eds"},
                    err))
      return false;
  } else if (!known_keys(o, {"default_behaviour", "tick_ms", "sources", "drive", "faults", "identity", "device_type"},
                         err)) {
    return false;
  }
  const cJSON* d = cJSON_GetObjectItemCaseSensitive(o, "default_behaviour");
  if (d) {
    if (!cJSON_IsBool(d)) {
      err = "\"default_behaviour\" must be true or false";
      return false;
    }
    b.default_behaviour = cJSON_IsTrue(d);
  }
  if (!get_uint(o, "tick_ms", 1, 60000, b.tick_ms, err)) return false;
  const cJSON* src = cJSON_GetObjectItemCaseSensitive(o, "sources");
  if (src) {
    if (!cJSON_IsObject(src)) {
      err = "\"sources\" must be an object of object -> source";
      return false;
    }
    for (const cJSON* c = src->child; c; c = c->next) {
      ObjKey k;
      if (!parse_obj_key(c->string, k)) {
        err = std::string("sources: \"") + c->string + "\" is not an object (\"0xIIII:S\")";
        return false;
      }
      std::string e;
      if (!Source::parse(c, dir, e)) {
        err = std::string("sources: ") + c->string + ": " + e;
        return false;
      }
      b.sources.emplace_back(k, sim_json_text(c));
    }
  }
  const cJSON* drive = cJSON_GetObjectItemCaseSensitive(o, "drive");
  if (drive) {
    // The engine reads the settings (sim_drive.h); the keys are checked here.
    std::string e;
    if (!cJSON_IsObject(drive) || !known_keys(drive, {"max_velocity", "max_acceleration", "lag_ms", "start_position"}, e)) {
      err = "drive: " + (e.empty() ? std::string("must be an object") : e);
      return false;
    }
    for (const cJSON* c = drive->child; c; c = c->next) {
      if (!cJSON_IsNumber(c)) {
        err = std::string("drive: \"") + c->string + "\" must be a number";
        return false;
      }
    }
    b.has_drive = true;
    b.drive_json = sim_json_text(drive);
  }
  const cJSON* faults = cJSON_GetObjectItemCaseSensitive(o, "faults");
  if (faults) {
    if (!cJSON_IsArray(faults)) {
      err = "\"faults\" must be a list";
      return false;
    }
    int i = 0;
    for (const cJSON* c = faults->child; c; c = c->next) {
      ++i;
      Fault f;
      std::string e;
      if (!parse_fault(c, f, e)) {
        err = "faults[" + std::to_string(i - 1) + "]: " + e;
        return false;
      }
      b.faults.push_back(f);
    }
  }
  const cJSON* id = cJSON_GetObjectItemCaseSensitive(o, "identity");
  if (id) {
    std::string e;
    if (!parse_identity(id, b.identity, e)) {
      err = "\"identity\" " + e;
      return false;
    }
  }
  const cJSON* dt = cJSON_GetObjectItemCaseSensitive(o, "device_type");
  if (dt) {
    if (!parse_u32(dt, b.device_type)) {
      err = "\"device_type\" must be a 32-bit number";
      return false;
    }
    b.has_device_type = true;
  }
  return true;
}

bool valid_name(const std::string& s) {
  if (s.empty() || s.size() > 32 || !std::isalpha(static_cast<unsigned char>(s[0]))) return false;
  for (char c : s)
    if (!std::isalnum(static_cast<unsigned char>(c)) && c != '_' && c != '-') return false;
  return true;
}

}  // namespace

std::string ObjKey::str() const { return object_key(index, subindex); }

std::string sim_json_text(const cJSON* v) {
  char* p = cJSON_PrintUnformatted(v);
  std::string s = p ? p : "null";
  cJSON_free(p);
  return s;
}

bool parse_obj_key(const std::string& text, ObjKey& out) { return parse_object_key(text, out.index, out.subindex); }

bool parse_u32(const cJSON* v, uint32_t& out) {
  if (cJSON_IsNumber(v)) {
    double d = v->valuedouble;
    if (d < 0 || d > 4294967295.0 || d != static_cast<double>(static_cast<long long>(d))) return false;
    out = static_cast<uint32_t>(d);
    return true;
  }
  if (!cJSON_IsString(v) || !*v->valuestring) return false;
  const char* s = v->valuestring;
  char* e = nullptr;
  unsigned long long x = 0;
  if (s[0] == '0' && (s[1] == 'x' || s[1] == 'X')) {
    if (!s[2]) return false;
    x = std::strtoull(s + 2, &e, 16);
  } else {
    if (!std::isdigit(static_cast<unsigned char>(s[0]))) return false;
    x = std::strtoull(s, &e, 10);
  }
  if (*e || x > 0xFFFFFFFFull) return false;
  out = static_cast<uint32_t>(x);
  return true;
}

bool parse_value(const cJSON* v, Value& out) {
  if (cJSON_IsNumber(v)) {
    out = Value::number(v->valuedouble);
    return true;
  }
  if (cJSON_IsBool(v)) {
    out = Value::number(cJSON_IsTrue(v) ? 1 : 0);
    return true;
  }
  if (cJSON_IsString(v)) {
    out = Value::text(v->valuestring);
    return true;
  }
  return false;
}

bool parse_device_ref(const cJSON* v, std::string& out) {
  if (cJSON_IsNumber(v)) {
    double d = v->valuedouble;
    if (d < 1 || d > 127 || d != static_cast<int>(d)) return false;
    out = std::to_string(static_cast<int>(d));
    return true;
  }
  if (cJSON_IsString(v)) {
    std::string s = v->valuestring;
    char* e = nullptr;
    long n = std::strtol(s.c_str(), &e, 10);
    if (!s.empty() && !*e) {
      if (n < 1 || n > 127) return false;
      out = std::to_string(n);
      return true;
    }
    if (!valid_name(s)) return false;
    out = s;
    return true;
  }
  return false;
}

bool is_clear_name(const std::string& n) {
  for (const char* k : {"all", "emcy", "heartbeat", "power", "sdo_abort", "sdo_delay", "refuse_write_operational",
                        "tpdo_stop", "identity", "device_type", "drive_input"})
    if (n == k) return true;
  return false;
}

bool parse_fault(const cJSON* o, Fault& f, std::string& err) {
  if (!cJSON_IsObject(o) || !o->child) {
    err = "a fault must be an object with one key";
    return false;
  }
  f.json = sim_json_text(o);
  int kinds = 0;
  for (const cJSON* c = o->child; c; c = c->next) {
    if (std::strcmp(c->string, "off_ms") == 0) continue;
    ++kinds;
    f.kind = c->string;
  }
  if (kinds != 1) {
    err = "a fault has exactly one kind";
    return false;
  }
  const cJSON* v = cJSON_GetObjectItemCaseSensitive(o, f.kind.c_str());
  const cJSON* off = cJSON_GetObjectItemCaseSensitive(o, "off_ms");
  if (off && f.kind != "power") {
    err = "\"off_ms\" belongs to a power cycle";
    return false;
  }
  if (f.kind == "emcy") {
    if (!cJSON_IsObject(v) || !known_keys(v, {"code", "register", "msef", "period_ms"}, err)) {
      if (err.empty()) err = "\"emcy\" must be an object";
      err = "emcy: " + err;
      return false;
    }
    uint32_t code = 0, reg = 0;
    const cJSON* c = cJSON_GetObjectItemCaseSensitive(v, "code");
    if (!c || !parse_u32(c, code) || code > 0xFFFF) {
      err = "emcy: \"code\" must be a 16-bit error code";
      return false;
    }
    f.code = static_cast<uint16_t>(code);
    const cJSON* r = cJSON_GetObjectItemCaseSensitive(v, "register");
    if (r && (!parse_u32(r, reg) || reg > 0xFF)) {
      err = "emcy: \"register\" must be 0-255";
      return false;
    }
    f.error_register = static_cast<uint8_t>(reg);
    const cJSON* m = cJSON_GetObjectItemCaseSensitive(v, "msef");
    if (m && (!cJSON_IsString(m) || !parse_hex_bytes(m->valuestring, f.msef, 5))) {
      err = "emcy: \"msef\" must be 5 bytes as 10 hex digits";
      return false;
    }
    if (!get_uint(v, "period_ms", 10, 3600000, f.period_ms, err)) {
      err = "emcy: " + err;
      return false;
    }
    return true;
  }
  auto one_of = [&](std::initializer_list<const char*> modes) {
    if (cJSON_IsString(v))
      for (const char* m : modes)
        if (std::strcmp(v->valuestring, m) == 0) {
          f.mode = m;
          return true;
        }
    std::string list;
    for (const char* m : modes) list += std::string(list.empty() ? "" : ", ") + "\"" + m + "\"";
    err = f.kind + " must be one of " + list;
    return false;
  };
  if (f.kind == "heartbeat") return one_of({"stop"});
  if (f.kind == "power") {
    if (!one_of({"off", "on", "cycle"})) return false;
    if (off) {
      if (f.mode != "cycle") {
        err = "\"off_ms\" belongs to a power cycle";
        return false;
      }
      if (!get_uint(o, "off_ms", 1, 3600000, f.off_ms, err)) return false;
    }
    return true;
  }
  if (f.kind == "reset") return one_of({"node", "comm"});
  if (f.kind == "nmt_state") return one_of({"stopped", "preop", "operational"});
  if (f.kind == "sdo_abort") {
    if (!cJSON_IsObject(v) || !known_keys(v, {"object", "code", "on", "count"}, err)) {
      err = "sdo_abort: " + (err.empty() ? std::string("must be an object") : err);
      return false;
    }
    const cJSON* ob = cJSON_GetObjectItemCaseSensitive(v, "object");
    if (!cJSON_IsString(ob) || !parse_obj_key(ob->valuestring, f.object)) {
      err = "sdo_abort: \"object\" must be \"0xIIII:S\"";
      return false;
    }
    f.has_object = true;
    const cJSON* c = cJSON_GetObjectItemCaseSensitive(v, "code");
    if (!c || !parse_u32(c, f.abort_code) || !f.abort_code) {
      err = "sdo_abort: \"code\" must be a non-zero 32-bit abort code";
      return false;
    }
    const cJSON* on = cJSON_GetObjectItemCaseSensitive(v, "on");
    if (on) {
      std::string s = cJSON_IsString(on) ? on->valuestring : "";
      if (s != "read" && s != "write" && s != "both") {
        err = "sdo_abort: \"on\" must be \"read\", \"write\" or \"both\"";
        return false;
      }
      f.on_read = s != "write";
      f.on_write = s != "read";
    }
    unsigned count = 0;
    if (!get_uint(v, "count", 1, 0x7FFFFFFF, count, err)) {
      err = "sdo_abort: " + err;
      return false;
    }
    if (count) f.count = static_cast<int>(count);
    return true;
  }
  if (f.kind == "sdo_delay") {
    if (!cJSON_IsObject(v) || !known_keys(v, {"ms", "object"}, err)) {
      err = "sdo_delay: " + (err.empty() ? std::string("must be an object") : err);
      return false;
    }
    if (!cJSON_GetObjectItemCaseSensitive(v, "ms") || !get_uint(v, "ms", 1, 60000, f.ms, err)) {
      err = "sdo_delay: \"ms\" must be an integer 1-60000";
      return false;
    }
    const cJSON* ob = cJSON_GetObjectItemCaseSensitive(v, "object");
    if (ob) {
      if (!cJSON_IsString(ob) || !parse_obj_key(ob->valuestring, f.object)) {
        err = "sdo_delay: \"object\" must be \"0xIIII:S\"";
        return false;
      }
      f.has_object = true;
    }
    return true;
  }
  if (f.kind == "refuse_write_operational" || f.kind == "forget_node_id") {
    if (!cJSON_IsTrue(v)) {
      err = f.kind + " must be true";
      return false;
    }
    return true;
  }
  if (f.kind == "tpdo_stop") {
    if (!cJSON_IsNumber(v) || v->valuedouble < 1 || v->valuedouble > 512 ||
        v->valuedouble != static_cast<int>(v->valuedouble)) {
      err = "tpdo_stop must be a TPDO number 1-512";
      return false;
    }
    f.tpdo = static_cast<unsigned>(v->valuedouble);
    return true;
  }
  if (f.kind == "identity") {
    std::string e;
    if (!parse_identity(v, f.identity, e)) {
      err = "identity " + e;
      return false;
    }
    return true;
  }
  if (f.kind == "device_type") {
    if (!parse_u32(v, f.value)) {
      err = "device_type must be a 32-bit number";
      return false;
    }
    return true;
  }
  if (f.kind == "drive_input") {
    if (!cJSON_IsObject(v) || !v->child || !known_keys(v, {"blocked", "positive_limit", "negative_limit", "home_switch"}, err)) {
      err = "drive_input: " + (err.empty() ? std::string("must name blocked, positive_limit, negative_limit or home_switch") : err);
      return false;
    }
    for (const cJSON* c = v->child; c; c = c->next) {
      if (!cJSON_IsBool(c)) {
        err = std::string("drive_input: \"") + c->string + "\" must be true or false";
        return false;
      }
      f.inputs[c->string] = cJSON_IsTrue(c);
    }
    return true;
  }
  err = "unknown fault \"" + f.kind + "\"";
  return false;
}

std::string Condition::text() const {
  if (is_expr) return expr;
  std::string s = "[" + node + "/" + object.str() + "]";
  if (bit >= 0) s = "bit(" + s + ", " + std::to_string(bit) + ")";
  static const std::map<std::string, std::string> ops = {{"eq", "=="}, {"ne", "!="}, {"lt", "<"},
                                                         {"le", "<="}, {"gt", ">"},  {"ge", ">="}};
  std::string v = value.is_string ? "\"" + value.str + "\"" : "";
  if (!value.is_string) {
    char b[32];
    std::snprintf(b, sizeof b, "%.10g", value.num);
    v = b;
  }
  return s + " " + ops.at(op) + " " + v;
}

bool parse_scenario(const cJSON* o, const std::string& name, Scenario& sc, std::string& err) {
  if (!cJSON_IsObject(o)) {
    err = "must be an object";
    return false;
  }
  if (!known_keys(o, {"autostart", "test", "description", "steps"}, err)) return false;
  sc.name = name;
  for (const char* k : {"autostart", "test"}) {
    const cJSON* b = cJSON_GetObjectItemCaseSensitive(o, k);
    if (b && !cJSON_IsBool(b)) {
      err = std::string("\"") + k + "\" must be true or false";
      return false;
    }
  }
  sc.autostart = cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(o, "autostart"));
  sc.test = cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(o, "test"));
  const cJSON* d = cJSON_GetObjectItemCaseSensitive(o, "description");
  if (d) {
    if (!cJSON_IsString(d)) {
      err = "\"description\" must be text";
      return false;
    }
    sc.description = d->valuestring;
  }
  return parse_steps(cJSON_GetObjectItemCaseSensitive(o, "steps"), sc.steps, "scenario", err);
}

bool parse_sim_file(const std::string& json, const std::string& path, SimFile& out, std::vector<std::string>& errors) {
  out = SimFile();
  out.path = path;
  size_t slash = path.rfind('/');
  out.dir = slash == std::string::npos ? "." : path.substr(0, slash);
  if (out.dir.empty()) out.dir = "/";
  cJSON* root = cJSON_Parse(json.c_str());
  if (!root) {
    errors.push_back(path + ": not valid JSON");
    return false;
  }
  std::unique_ptr<cJSON, void (*)(cJSON*)> guard(root, cJSON_Delete);
  auto fail = [&](const std::string& where, const std::string& msg) {
    errors.push_back(path + ": " + where + (where.empty() ? "" : ": ") + msg);
  };
  if (!cJSON_IsObject(root)) {
    fail("", "must be a JSON object");
    return false;
  }
  std::string err;
  if (!known_keys(root, {"schema_version", "tick_ms", "nodes", "extra_devices", "scenarios", "$schema"}, err)) {
    fail("", err);
    return false;
  }
  const cJSON* ver = cJSON_GetObjectItemCaseSensitive(root, "schema_version");
  if (ver) {
    if (!cJSON_IsNumber(ver) || ver->valuedouble < 1 || ver->valuedouble != static_cast<int>(ver->valuedouble)) {
      fail("schema_version", "must be a positive integer");
      return false;
    }
    out.schema_version = static_cast<unsigned>(ver->valuedouble);
    if (out.schema_version > kSimSchemaVersion) {
      fail("schema_version", "the file is version " + std::to_string(out.schema_version) + ", this simulator reads up to " +
                                 std::to_string(kSimSchemaVersion));
      return false;
    }
  }
  if (!get_uint(root, "tick_ms", 1, 60000, out.tick_ms, err)) fail("", err);
  const cJSON* nodes = cJSON_GetObjectItemCaseSensitive(root, "nodes");
  if (nodes) {
    if (!cJSON_IsObject(nodes)) {
      fail("nodes", "must be an object keyed by node ID");
    } else {
      for (const cJSON* c = nodes->child; c; c = c->next) {
        char* e = nullptr;
        long id = std::strtol(c->string, &e, 10);
        if (!*c->string || *e || id < 1 || id > 127) {
          fail(std::string("nodes.") + c->string, "the key must be a node ID 1-127");
          continue;
        }
        NodeBehaviour b;
        std::string e2;
        if (!parse_behaviour(c, b, out.dir, false, e2)) {
          fail(std::string("nodes.") + c->string, e2);
          continue;
        }
        out.nodes[static_cast<unsigned>(id)] = std::move(b);
      }
    }
  }
  const cJSON* extra = cJSON_GetObjectItemCaseSensitive(root, "extra_devices");
  if (extra) {
    if (!cJSON_IsArray(extra)) {
      fail("extra_devices", "must be a list");
    } else {
      int i = 0;
      std::set<std::string> names;
      std::set<unsigned> ids;
      for (const cJSON* c = extra->child; c; c = c->next, ++i) {
        std::string where = "extra_devices[" + std::to_string(i) + "]";
        ExtraDevice x;
        std::string e2;
        if (!parse_behaviour(c, x.behaviour, out.dir, true, e2)) {
          fail(where, e2);
          continue;
        }
        unsigned node = 200;
        if (!get_uint(c, "node", 0, 127, node, e2) || node == 200) {
          fail(where, e2.empty() ? "\"node\" (0-127) is required" : e2);
          continue;
        }
        x.node = node;
        const cJSON* n = cJSON_GetObjectItemCaseSensitive(c, "name");
        if (n) {
          if (!cJSON_IsString(n) || !valid_name(n->valuestring)) {
            fail(where, "\"name\" must start with a letter and have only letters, digits, _ and - (at most 32)");
            continue;
          }
          x.name = n->valuestring;
        }
        if (!x.node && x.name.empty()) {
          fail(where, "a device without a node ID (node 0) needs a \"name\"");
          continue;
        }
        const cJSON* eds = cJSON_GetObjectItemCaseSensitive(c, "eds");
        if (!cJSON_IsString(eds) || !*eds->valuestring) {
          fail(where, "\"eds\" (an EDS or DCF file) is required");
          continue;
        }
        x.eds = eds->valuestring;
        x.eds_path = join_path(out.dir, x.eds);
        if (!x.name.empty() && !names.insert(x.name).second) {
          fail(where, "the name " + x.name + " is used twice");
          continue;
        }
        if (x.node && !ids.insert(x.node).second) {
          fail(where, "node " + std::to_string(x.node) + " is used by two extra devices");
          continue;
        }
        out.extra.push_back(std::move(x));
      }
    }
  }
  const cJSON* sc = cJSON_GetObjectItemCaseSensitive(root, "scenarios");
  if (sc) {
    if (!cJSON_IsObject(sc)) {
      fail("scenarios", "must be an object keyed by scenario name");
    } else {
      for (const cJSON* c = sc->child; c; c = c->next) {
        Scenario s;
        std::string e2;
        if (!parse_scenario(c, c->string, s, e2)) {
          fail(std::string("scenarios.") + c->string, e2);
          continue;
        }
        out.scenarios.push_back(std::move(s));
      }
    }
  }
  return errors.empty();
}

bool load_sim_file(const std::string& path, SimFile& out, std::vector<std::string>& errors) {
  std::ifstream in(path);
  if (!in) {
    errors.push_back(path + ": cannot read the file");
    return false;
  }
  std::stringstream ss;
  ss << in.rdbuf();
  return parse_sim_file(ss.str(), path, out, errors);
}

}  // namespace canopen_sim
