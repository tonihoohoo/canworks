// The control subcommands (docs/simulator.md, "Control subcommands"): each
// builds one sim_ request, sends it over the control channel and prints the
// answer for people. Exit 0 on success, 1 on an error answer, 2 on a usage
// or connection error.

#include <cerrno>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

#include "cJSON.h"
#include "control.h"
#include "sim_tool.h"

namespace sim_tool {

namespace {

const char* const kCommands[] = {"status", "get", "set", "override", "release", "source", "fault", "clear", "scenario"};

std::string underscores(std::string s) {
  for (auto& c : s)
    if (c == '-') c = '_';
  return s;
}

bool parse_number(const std::string& s, double& out) {
  if (s.empty()) return false;
  errno = 0;
  char* end = nullptr;
  long long v = std::strtoll(s.c_str(), &end, 0);
  if (*end == 0 && errno == 0) {
    out = static_cast<double>(v);
    return true;
  }
  errno = 0;
  unsigned long long u = std::strtoull(s.c_str(), &end, 0);
  if (*end == 0 && errno == 0 && s[0] != '-') {
    out = static_cast<double>(u);
    return true;
  }
  errno = 0;
  double d = std::strtod(s.c_str(), &end);
  if (*end == 0 && errno == 0 && std::isfinite(d)) {
    out = d;
    return true;
  }
  return false;
}

// A node: a node ID, or the name of an extra device.
cJSON* node_json(const std::string& s) {
  double d;
  if (parse_number(s, d)) return cJSON_CreateNumber(d);
  return cJSON_CreateString(s.c_str());
}

// A value on the command line: a number (decimal, 0x hex, or with a
// fraction), true/false, or text (VISIBLE_STRING objects).
cJSON* value_json(const std::string& s) {
  double d;
  if (parse_number(s, d)) return cJSON_CreateNumber(d);
  if (s == "true") return cJSON_CreateTrue();
  if (s == "false") return cJSON_CreateFalse();
  return cJSON_CreateString(s.c_str());
}

std::string json_text(const cJSON* j) {
  if (!j) return "";
  if (cJSON_IsString(j)) return j->valuestring;
  char* p = cJSON_PrintUnformatted(j);
  std::string s = p ? p : "";
  cJSON_free(p);
  return s;
}

std::string str(const cJSON* o, const char* k) {
  const cJSON* v = cJSON_GetObjectItemCaseSensitive(o, k);
  return cJSON_IsString(v) ? v->valuestring : "";
}

struct UsageError {
  std::string message;
};

[[noreturn]] void usage(const std::string& m) { throw UsageError{m}; }

std::string need(std::vector<std::string>& pos, size_t& i, const char* what) {
  if (i >= pos.size()) usage(std::string("missing ") + what);
  return pos[i++];
}

// Options of the fault kinds (--register, --off-ms, ...): "--name" -> value
// ("" for a flag).
struct Opts {
  std::vector<std::pair<std::string, std::string>> list;
  bool has(const std::string& n) const {
    for (const auto& kv : list)
      if (kv.first == n) return true;
    return false;
  }
  std::string get(const std::string& n) const {
    for (const auto& kv : list)
      if (kv.first == n) return kv.second;
    return "";
  }
};

cJSON* number_arg(const std::string& s, const char* what) {
  double d;
  if (!parse_number(s, d)) usage(std::string(what) + " must be a number, not \"" + s + "\"");
  return cJSON_CreateNumber(d);
}

void check_opts(const Opts& o, std::initializer_list<const char*> allowed, const std::string& kind) {
  for (const auto& kv : o.list) {
    bool ok = false;
    for (const char* a : allowed) ok = ok || kv.first == a;
    if (!ok) usage("fault " + kind + " takes no option " + kv.first);
  }
}

cJSON* build_fault(const std::string& kind_in, std::vector<std::string>& pos, size_t& i, const Opts& o) {
  std::string kind = underscores(kind_in);
  cJSON* f = cJSON_CreateObject();
  auto mode = [&](const char* what) { return need(pos, i, what); };
  if (kind == "json") {
    std::string text = need(pos, i, "the fault's JSON");
    cJSON_Delete(f);
    cJSON* j = cJSON_Parse(text.c_str());
    if (!cJSON_IsObject(j)) {
      cJSON_Delete(j);
      usage("fault json takes a JSON object, like '{\"heartbeat\": \"stop\"}'");
    }
    check_opts(o, {}, kind_in);
    return j;
  }
  if (kind == "emcy") {
    check_opts(o, {"--register", "--msef", "--period-ms"}, kind_in);
    cJSON* e = cJSON_AddObjectToObject(f, "emcy");
    cJSON_AddStringToObject(e, "code", need(pos, i, "the EMCY error code").c_str());
    if (o.has("--register")) cJSON_AddStringToObject(e, "register", o.get("--register").c_str());
    if (o.has("--msef")) cJSON_AddStringToObject(e, "msef", o.get("--msef").c_str());
    if (o.has("--period-ms")) cJSON_AddItemToObject(e, "period_ms", number_arg(o.get("--period-ms"), "--period-ms"));
  } else if (kind == "heartbeat_stop" || kind == "heartbeat") {
    check_opts(o, {}, kind_in);
    if (kind == "heartbeat" && mode("stop") != "stop") usage("fault heartbeat takes: stop");
    cJSON_AddStringToObject(f, "heartbeat", "stop");
  } else if (kind == "power") {
    check_opts(o, {"--off-ms"}, kind_in);
    cJSON_AddStringToObject(f, "power", mode("off, on or cycle").c_str());
    if (o.has("--off-ms")) cJSON_AddItemToObject(f, "off_ms", number_arg(o.get("--off-ms"), "--off-ms"));
  } else if (kind == "reset" || kind == "nmt_state") {
    check_opts(o, {}, kind_in);
    cJSON_AddStringToObject(f, kind.c_str(), mode(kind == "reset" ? "node or comm" : "stopped, preop or operational").c_str());
  } else if (kind == "sdo_abort") {
    check_opts(o, {"--on", "--count"}, kind_in);
    cJSON* a = cJSON_AddObjectToObject(f, "sdo_abort");
    cJSON_AddStringToObject(a, "object", need(pos, i, "the object").c_str());
    cJSON_AddStringToObject(a, "code", need(pos, i, "the SDO abort code").c_str());
    if (o.has("--on")) cJSON_AddStringToObject(a, "on", o.get("--on").c_str());
    if (o.has("--count")) cJSON_AddItemToObject(a, "count", number_arg(o.get("--count"), "--count"));
  } else if (kind == "sdo_delay") {
    check_opts(o, {"--object"}, kind_in);
    cJSON* a = cJSON_AddObjectToObject(f, "sdo_delay");
    cJSON_AddItemToObject(a, "ms", number_arg(need(pos, i, "the delay in ms"), "the delay"));
    if (o.has("--object")) cJSON_AddStringToObject(a, "object", o.get("--object").c_str());
  } else if (kind == "refuse_write_operational" || kind == "forget_node_id") {
    check_opts(o, {}, kind_in);
    cJSON_AddTrueToObject(f, kind.c_str());
  } else if (kind == "tpdo_stop") {
    check_opts(o, {}, kind_in);
    cJSON_AddItemToObject(f, "tpdo_stop", number_arg(need(pos, i, "the TPDO number"), "the TPDO number"));
  } else if (kind == "identity") {
    check_opts(o, {"--vendor-id", "--product-code", "--revision-number", "--serial-number"}, kind_in);
    if (o.list.empty()) usage("fault identity needs at least one of --vendor-id, --product-code, --revision-number, --serial-number");
    cJSON* a = cJSON_AddObjectToObject(f, "identity");
    for (const auto& kv : o.list) cJSON_AddItemToObject(a, underscores(kv.first.substr(2)).c_str(), number_arg(kv.second, kv.first.c_str()));
  } else if (kind == "device_type") {
    check_opts(o, {}, kind_in);
    cJSON_AddItemToObject(f, "device_type", number_arg(need(pos, i, "the device type"), "the device type"));
  } else if (kind == "drive_input") {
    check_opts(o, {"--blocked", "--positive-limit", "--negative-limit", "--home-switch", "--no-blocked",
                   "--no-positive-limit", "--no-negative-limit", "--no-home-switch"},
               kind_in);
    if (o.list.empty()) usage("fault drive-input needs --blocked, --positive-limit, --negative-limit or --home-switch (--no-... for false)");
    cJSON* a = cJSON_AddObjectToObject(f, "drive_input");
    for (const auto& kv : o.list) {
      bool off = kv.first.compare(0, 5, "--no-") == 0;
      std::string name = underscores(kv.first.substr(off ? 5 : 2));
      cJSON_DeleteItemFromObjectCaseSensitive(a, name.c_str());
      cJSON_AddBoolToObject(a, name.c_str(), !off);
    }
  } else {
    cJSON_Delete(f);
    usage("unknown fault kind \"" + kind_in + "\"");
  }
  return f;
}

// Options of the fault kinds that take a value.
bool fault_option_has_value(const std::string& name) {
  for (const char* n : {"--register", "--msef", "--period-ms", "--off-ms", "--on", "--count", "--object", "--vendor-id",
                        "--product-code", "--revision-number", "--serial-number"})
    if (name == n) return true;
  return false;
}

void print_status(const cJSON* res) {
  bool simnet = cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(res, "simulated_network"));
  std::printf("%s\n", simnet ? "simulated network" : ("interface " + str(res, "interface")).c_str());
  const cJSON* d;
  cJSON_ArrayForEach(d, cJSON_GetObjectItemCaseSensitive(res, "devices")) {
    const cJSON* node = cJSON_GetObjectItemCaseSensitive(d, "node");
    std::string name = str(d, "name");
    std::string label = cJSON_IsNumber(node) ? "node " + std::to_string(node->valueint) + (name.empty() ? "" : " (" + name + ")")
                                             : name + " (no node ID)";
    const cJSON* nid = cJSON_GetObjectItemCaseSensitive(d, "node_id");
    if (cJSON_IsNumber(nid)) label += " now node " + std::to_string(nid->valueint);
    std::string line = label + ": power " + str(d, "power") + ", " + str(d, "nmt");
    if (cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(d, "conflict"))) line += ", NODE ID CONFLICT";
    const cJSON* prof = cJSON_GetObjectItemCaseSensitive(d, "profile");
    line += ", " + str(d, "eds");
    if (cJSON_IsNumber(prof) && prof->valueint) line += ", CiA " + std::to_string(prof->valueint);
    const cJSON* x;
    std::string faults;
    cJSON_ArrayForEach(x, cJSON_GetObjectItemCaseSensitive(d, "faults")) faults += (faults.empty() ? "" : " ") + json_text(x);
    if (!faults.empty()) line += ", faults: " + faults;
    std::string srcs;
    cJSON_ArrayForEach(x, cJSON_GetObjectItemCaseSensitive(d, "sources")) srcs += (srcs.empty() ? "" : " ") + std::string(x->string);
    if (!srcs.empty()) line += ", sources: " + srcs;
    std::string ovs;
    cJSON_ArrayForEach(x, cJSON_GetObjectItemCaseSensitive(d, "overrides")) ovs += (ovs.empty() ? "" : " ") + std::string(x->string) + "=" + json_text(x);
    if (!ovs.empty()) line += ", overrides: " + ovs;
    std::printf("%s\n", line.c_str());
  }
}

void print_scenarios(const cJSON* res) {
  const cJSON* s;
  bool any = false;
  cJSON_ArrayForEach(s, cJSON_GetObjectItemCaseSensitive(res, "scenarios")) {
    any = true;
    std::string line = "scenario " + str(s, "name") + ": " + str(s, "state");
    std::string flags;
    if (cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(s, "test"))) flags += " test";
    if (cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(s, "autostart"))) flags += " autostart";
    if (!flags.empty()) line += " [" + flags.substr(1) + "]";
    if (str(s, "state") == "running" && !str(s, "step").empty()) line += ", " + str(s, "step");
    if (!str(s, "message").empty() && str(s, "state") != "running") line += ": " + str(s, "message");
    std::printf("%s\n", line.c_str());
  }
  if (!any) std::printf("no scenarios\n");
}

int print_get(const cJSON* res) {
  int rc = kExitOk;
  const cJSON* v;
  cJSON_ArrayForEach(v, cJSON_GetObjectItemCaseSensitive(res, "values")) {
    const cJSON* node = cJSON_GetObjectItemCaseSensitive(v, "node");
    std::string who = cJSON_IsNumber(node) ? "node " + std::to_string(node->valueint) : json_text(node);
    std::string err = str(v, "error");
    if (!err.empty()) {
      std::fprintf(stderr, "%s %s: %s\n", who.c_str(), str(v, "object").c_str(), err.c_str());
      rc = kExitFailed;
      continue;
    }
    const cJSON* val = cJSON_GetObjectItemCaseSensitive(v, "value");
    std::string text;
    if (cJSON_IsString(val)) {
      char* p = cJSON_PrintUnformatted(val);
      text = p;
      cJSON_free(p);
    } else if (cJSON_IsNumber(val)) {
      char b[40];
      std::snprintf(b, sizeof b, "%.17g", val->valuedouble);
      text = b;
    } else {
      text = json_text(val);
    }
    std::string writer = str(v, "writer");
    std::printf("%s %s = %s (%s%s)\n", who.c_str(), str(v, "object").c_str(), text.c_str(), str(v, "type").c_str(),
                writer.empty() ? "" : (", " + writer).c_str());
  }
  return rc;
}

}  // namespace

bool is_command(const std::string& word) {
  for (const char* c : kCommands)
    if (word == c) return true;
  return false;
}

int command_main(const std::string& cmd, Args& args) {
  std::string target = "127.0.0.1", token, token_file, value;
  bool json = false;
  std::vector<std::string> pos;
  Opts opts;
  try {
    while (!args.done()) {
      bool missing = false;
      if (args.option("--sim", value, missing)) {
        if (missing) usage("--sim needs HOST[:PORT]");
        target = value;
      } else if (args.option("--token-file", value, missing)) {
        if (missing) usage("--token-file needs a file");
        token_file = value;
      } else if (args.option("--token", value, missing)) {
        if (missing) usage("--token needs a value");
        token = value;
      } else if (args.flag("--json")) {
        json = true;
      } else if (args.flag("--help") || args.flag("-h")) {
        print_usage(true);
        return kExitOk;
      } else if (cmd == "fault" && args.peek().compare(0, 2, "--") == 0 && args.peek().size() > 2) {
        std::string w = args.next();
        std::string name = w, v;
        size_t eq = w.find('=');
        if (eq != std::string::npos) {
          name = w.substr(0, eq);
          v = w.substr(eq + 1);
        } else if (fault_option_has_value(name)) {
          if (args.done()) usage(name + " needs a value");
          v = args.next();
        }
        opts.list.emplace_back(name, v);
      } else {
        pos.push_back(args.next());
      }
    }

    // Build the request.
    cJSON* req = cJSON_CreateObject();
    size_t i = 0;
    struct Guard {
      cJSON*& r;
      ~Guard() { cJSON_Delete(r); }
    } guard{req};
    if (cmd == "status") {
      cJSON_AddStringToObject(req, "op", "sim_status");
    } else if (cmd == "get") {
      cJSON_AddStringToObject(req, "op", "sim_get");
      std::string node = need(pos, i, "the node");
      if (i == pos.size()) {
        cJSON_AddItemToObject(req, "node", node_json(node));
        cJSON_AddTrueToObject(req, "pdo");
      }
      cJSON* items = i < pos.size() ? cJSON_AddArrayToObject(req, "items") : nullptr;
      while (i < pos.size()) {
        cJSON* it = cJSON_CreateObject();
        cJSON_AddItemToObject(it, "node", node_json(node));
        cJSON_AddStringToObject(it, "object", pos[i++].c_str());
        cJSON_AddItemToArray(items, it);
      }
    } else if (cmd == "set" || cmd == "override") {
      cJSON_AddStringToObject(req, "op", cmd == "set" ? "sim_set" : "sim_override");
      cJSON_AddItemToObject(req, "node", node_json(need(pos, i, "the node")));
      cJSON* vals = cJSON_AddObjectToObject(req, "values");
      if (i >= pos.size()) usage(cmd + " needs OBJECT VALUE");
      while (i < pos.size()) {
        std::string obj = pos[i++];
        std::string v = need(pos, i, ("the value of " + obj).c_str());
        cJSON_DeleteItemFromObjectCaseSensitive(vals, obj.c_str());
        cJSON_AddItemToObject(vals, obj.c_str(), value_json(v));
      }
    } else if (cmd == "release") {
      cJSON_AddStringToObject(req, "op", "sim_release");
      cJSON_AddItemToObject(req, "node", node_json(need(pos, i, "the node")));
      if (i == pos.size() || (pos.size() == i + 1 && pos[i] == "all")) {
        cJSON_AddStringToObject(req, "objects", "all");
        i = pos.size();
      } else {
        cJSON* objs = cJSON_AddArrayToObject(req, "objects");
        while (i < pos.size()) cJSON_AddItemToArray(objs, cJSON_CreateString(pos[i++].c_str()));
      }
    } else if (cmd == "source") {
      cJSON_AddStringToObject(req, "op", "sim_source");
      cJSON_AddItemToObject(req, "node", node_json(need(pos, i, "the node")));
      cJSON_AddStringToObject(req, "object", need(pos, i, "the object").c_str());
      std::string s = need(pos, i, "the source's JSON (or none)");
      if (s == "none" || s == "null") {
        cJSON_AddNullToObject(req, "source");
      } else {
        cJSON* j = cJSON_Parse(s.c_str());
        if (!cJSON_IsObject(j)) {
          cJSON_Delete(j);
          usage("the source must be a JSON object, like '{\"sine\": {\"min\": 0, \"max\": 10, \"period_s\": 5}}', or none");
        }
        cJSON_AddItemToObject(req, "source", j);
      }
    } else if (cmd == "fault") {
      cJSON_AddStringToObject(req, "op", "sim_fault");
      cJSON_AddItemToObject(req, "node", node_json(need(pos, i, "the node")));
      std::string kind = need(pos, i, "the fault kind");
      cJSON_AddItemToObject(req, "fault", build_fault(kind, pos, i, opts));
    } else if (cmd == "clear") {
      cJSON_AddStringToObject(req, "op", "sim_clear");
      cJSON_AddItemToObject(req, "node", node_json(need(pos, i, "the node")));
      std::string name = underscores(need(pos, i, "the fault name (or all)"));
      if (name == "heartbeat_stop") name = "heartbeat";
      cJSON_AddStringToObject(req, "fault", name.c_str());
      if (i < pos.size()) {
        if (name == "tpdo_stop")
          cJSON_AddItemToObject(req, "tpdo", number_arg(pos[i++], "the TPDO number"));
        else if (name == "sdo_abort" || name == "sdo_delay")
          cJSON_AddStringToObject(req, "object", pos[i++].c_str());
        else
          usage("clear " + name + " takes no object");
      }
    } else if (cmd == "scenario") {
      std::string sub = need(pos, i, "list, start or stop");
      if (sub == "list") {
        cJSON_AddStringToObject(req, "op", "sim_scenario_list");
      } else if (sub == "start" || sub == "stop") {
        cJSON_AddStringToObject(req, "op", sub == "start" ? "sim_scenario_start" : "sim_scenario_stop");
        cJSON_AddStringToObject(req, "name", need(pos, i, "the scenario's name").c_str());
      } else {
        usage("scenario takes list, start NAME or stop NAME");
      }
    }
    if (i < pos.size()) usage("unexpected \"" + pos[i] + "\"");
    if (cmd != "fault" && !opts.list.empty()) usage("unknown option " + opts.list[0].first);

    std::string host, err, tok;
    unsigned port = 0;
    if (!split_host_port(target, kControlPort, host, port)) usage("--sim takes HOST[:PORT], not \"" + target + "\"");
    if (!resolve_token(token, token_file, nullptr, tok, err)) {
      std::fprintf(stderr, "canworks-sim: %s\n", err.c_str());
      return kExitUsage;
    }
    ControlClient client;
    if (!client.connect(host, port, tok, err)) {
      std::fprintf(stderr, "canworks-sim: %s\n", err.c_str());
      return kExitUsage;
    }
    cJSON* ans = client.request(req, err);
    if (!ans) {
      std::fprintf(stderr, "canworks-sim: %s\n", err.c_str());
      return kExitUsage;
    }
    struct AnsGuard {
      cJSON* a;
      ~AnsGuard() { cJSON_Delete(a); }
    } ag{ans};
    if (json) std::printf("%s\n", json_text(ans).c_str());
    std::string ae = answer_error(ans);
    if (!ae.empty()) {
      std::fprintf(stderr, "canworks-sim %s: %s\n", cmd.c_str(), ae.c_str());
      return kExitFailed;
    }
    if (json) return kExitOk;
    const cJSON* res = cJSON_GetObjectItemCaseSensitive(ans, "result");
    if (cmd == "status") {
      print_status(res);
      print_scenarios(res);
    } else if (cmd == "get") {
      return print_get(res);
    } else if (cmd == "scenario" && pos[0] == "list") {
      print_scenarios(res);
    } else {
      std::printf("ok\n");
    }
    return kExitOk;
  } catch (const UsageError& e) {
    std::fprintf(stderr, "canworks-sim %s: %s\n", cmd.c_str(), e.message.c_str());
    return kExitUsage;
  }
}

}  // namespace sim_tool
