#include "sim_machine.h"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <fstream>
#include <functional>
#include <memory>
#include <set>
#include <sstream>

#include "cJSON.h"

namespace canopen_sim {

namespace {

constexpr double kGravity = 9810;  // mm/s²
constexpr double kEps = 1e-6;

const char* state_name(MachineModel::PartState s) {
  switch (s) {
    case MachineModel::PartState::Belt: return "belt";
    case MachineModel::PartState::Held: return "held";
    case MachineModel::PartState::Falling: return "falling";
    case MachineModel::PartState::Placed: return "placed";
    case MachineModel::PartState::Misplaced: return "misplaced";
    case MachineModel::PartState::Table: return "table";
  }
  return "";
}

double smooth(double t) {
  t = std::min(1.0, std::max(0.0, t));
  return t * t * (3 - 2 * t);
}

double overlap(double alo, double ahi, double blo, double bhi) { return std::min(ahi, bhi) - std::max(alo, blo); }

double round_to(double v, double step) { return std::round(v / step) * step; }

// Reads one JSON object, collecting errors with their JSON path.
class Reader {
 public:
  Reader(const std::string& path, std::vector<std::string>& errors) : path_(path), errors_(errors) {}
  void fail(const std::string& where, const std::string& msg) {
    errors_.push_back(path_ + ": " + where + (where.empty() ? "" : ": ") + msg);
  }
  bool keys(const cJSON* o, const std::string& where, std::initializer_list<const char*> allowed) {
    bool ok = true;
    for (const cJSON* c = o->child; c; c = c->next) {
      bool known = false;
      for (const char* k : allowed) known = known || std::strcmp(c->string, k) == 0;
      if (!known) {
        fail(where, std::string("unknown key \"") + c->string + "\"");
        ok = false;
      }
    }
    return ok;
  }
  bool object(const cJSON* o, const std::string& where) {
    if (cJSON_IsObject(o)) return true;
    fail(where, "must be an object");
    return false;
  }
  // number in [min, max]; absent keeps `out` unless required
  bool number(const cJSON* o, const char* key, const std::string& where, double min, double max, double& out,
              bool required = false) {
    const cJSON* v = cJSON_GetObjectItemCaseSensitive(o, key);
    if (!v) {
      if (required) fail(where, std::string("\"") + key + "\" is required");
      return !required;
    }
    if (!cJSON_IsNumber(v) || !std::isfinite(v->valuedouble) || v->valuedouble < min || v->valuedouble > max) {
      fail(where + "." + key, "must be a number " + fmt(min) + " to " + fmt(max));
      return false;
    }
    out = v->valuedouble;
    return true;
  }
  bool uint(const cJSON* o, const char* key, const std::string& where, unsigned min, unsigned max, unsigned& out,
            bool required = false) {
    double d = out;
    if (!number(o, key, where, min, max, d, required)) return false;
    if (d != std::floor(d)) {
      fail(where + "." + key, "must be an integer");
      return false;
    }
    out = static_cast<unsigned>(d);
    return true;
  }
  bool numbers(const cJSON* o, const char* key, const std::string& where, size_t n, double* out, bool required = false,
               double min = -1e6, double max = 1e6) {
    const cJSON* v = cJSON_GetObjectItemCaseSensitive(o, key);
    if (!v) {
      if (required) fail(where, std::string("\"") + key + "\" is required");
      return !required;
    }
    if (!cJSON_IsArray(v) || static_cast<size_t>(cJSON_GetArraySize(v)) != n) {
      fail(where + "." + key, "must be a list of " + std::to_string(n) + " numbers");
      return false;
    }
    size_t i = 0;
    for (const cJSON* c = v->child; c; c = c->next, ++i) {
      if (!cJSON_IsNumber(c) || !std::isfinite(c->valuedouble) || c->valuedouble < min || c->valuedouble > max) {
        fail(where + "." + key, "must be a list of " + std::to_string(n) + " numbers " + fmt(min) + " to " + fmt(max));
        return false;
      }
      out[i] = c->valuedouble;
    }
    return true;
  }
  bool text(const cJSON* o, const char* key, const std::string& where, std::string& out, bool required = false) {
    const cJSON* v = cJSON_GetObjectItemCaseSensitive(o, key);
    if (!v) {
      if (required) fail(where, std::string("\"") + key + "\" is required");
      return !required;
    }
    if (!cJSON_IsString(v) || !*v->valuestring) {
      fail(where + "." + key, "must be a non-empty string");
      return false;
    }
    out = v->valuestring;
    return true;
  }
  bool bit(const cJSON* o, const char* key, const std::string& where, IoBit& out, bool required = true) {
    const cJSON* v = cJSON_GetObjectItemCaseSensitive(o, key);
    std::string at = where + "." + key;
    if (!v) {
      if (required) fail(where, std::string("\"") + key + "\" is required");
      return false;
    }
    if (!object(v, at) || !keys(v, at, {"node", "object", "bit"})) return false;
    bool ok = uint(v, "node", at, 1, 127, out.node, true);
    std::string obj;
    if (!text(v, "object", at, obj, true)) {
      ok = false;
    } else if (!parse_obj_key(obj, out.object)) {
      fail(at + ".object", "must be \"0xIIII:S\"");
      ok = false;
    }
    ok = uint(v, "bit", at, 0, 63, out.bit, true) && ok;
    return ok;
  }
  static std::string fmt(double v) {
    char b[32];
    std::snprintf(b, sizeof b, "%g", v);
    return b;
  }

 private:
  std::string path_;
  std::vector<std::string>& errors_;
};

}  // namespace

std::string IoBit::str() const {
  return "node " + std::to_string(node) + " " + object.str() + " bit " + std::to_string(bit);
}

std::vector<std::pair<IoBit, std::string>> MachineSpec::outputs() const {
  std::vector<std::pair<IoBit, std::string>> v;
  if (tool.present) v.emplace_back(tool.close, "tool.close");
  for (const auto& c : conveyors) v.emplace_back(c.run, "conveyor " + c.name + " run");
  for (const auto& f : fixtures)
    if (f.has_change) v.emplace_back(f.change_request, "fixture " + f.name + " change request");
  return v;
}

std::vector<std::pair<IoBit, std::string>> MachineSpec::inputs() const {
  std::vector<std::pair<IoBit, std::string>> v;
  if (tool.present && tool.has_gripped) v.emplace_back(tool.gripped, "tool.gripped");
  for (const auto& s : sensors) v.emplace_back(s.output, "sensor " + s.name);
  for (const auto& f : fixtures)
    if (f.has_change) v.emplace_back(f.change_ready, "fixture " + f.name + " ready");
  return v;
}

bool parse_machine_file(const std::string& json, const std::string& path, MachineSpec& out,
                        std::vector<std::string>& errors) {
  out = MachineSpec();
  out.path = path;
  cJSON* root = cJSON_Parse(json.c_str());
  if (!root) {
    errors.push_back(path + ": not valid JSON");
    return false;
  }
  std::unique_ptr<cJSON, void (*)(cJSON*)> guard(root, cJSON_Delete);
  size_t before = errors.size();
  Reader r(path, errors);
  if (!r.object(root, "")) return false;
  r.keys(root, "", {"schema_version", "name", "kind", "units", "tick_ms", "seed", "joints", "tool", "parts",
                    "conveyors", "sensors", "fixtures", "visual"});
  unsigned ver = 0;
  if (!r.uint(root, "schema_version", "", 1, 1000, ver, true)) return false;
  if (ver > kMachineSchemaVersion) {
    r.fail("schema_version", "the file is version " + std::to_string(ver) + ", this simulator reads up to " +
                                 std::to_string(kMachineSchemaVersion));
    return false;
  }
  r.text(root, "name", "", out.name);
  r.text(root, "kind", "", out.kind, true);
  if (!out.kind.empty() && out.kind != "gantry_xyz") r.fail("kind", "must be \"gantry_xyz\" (the only kind in this version)");
  std::string units = "mm";
  r.text(root, "units", "", units);
  if (units != "mm") r.fail("units", "must be \"mm\"");
  r.uint(root, "tick_ms", "", 1, 100, out.tick_ms);
  unsigned seed = 1;
  r.uint(root, "seed", "", 0, 0x7FFFFFFF, seed);
  out.seed = seed;

  // Joints.
  const cJSON* js = cJSON_GetObjectItemCaseSensitive(root, "joints");
  if (!js) {
    r.fail("", "\"joints\" is required");
  } else if (r.object(js, "joints")) {
    for (const cJSON* c = js->child; c; c = c->next) {
      std::string at = std::string("joints.") + c->string;
      if (std::strcmp(c->string, "x") && std::strcmp(c->string, "y") && std::strcmp(c->string, "z")) {
        r.fail(at, "a gantry_xyz machine has the joints x, y and z");
        continue;
      }
      if (!r.object(c, at)) continue;
      r.keys(c, at, {"node", "travel", "counts_per_mm", "offset_mm", "direction", "down", "home_flag", "limits",
                     "hard_stops", "load"});
      MachineJoint j;
      j.name = c->string;
      r.uint(c, "node", at, 1, 127, j.node, true);
      r.numbers(c, "travel", at, 2, j.travel, true);
      r.number(c, "counts_per_mm", at, 1e-6, 1e9, j.counts_per_mm);
      r.number(c, "offset_mm", at, -1e6, 1e6, j.offset_mm);
      const cJSON* d = cJSON_GetObjectItemCaseSensitive(c, "direction");
      if (d) {
        if (!cJSON_IsNumber(d) || (d->valuedouble != 1 && d->valuedouble != -1))
          r.fail(at + ".direction", "must be 1 or -1");
        else
          j.direction = static_cast<int>(d->valuedouble);
      }
      const cJSON* dn = cJSON_GetObjectItemCaseSensitive(c, "down");
      if (dn) {
        if (!cJSON_IsBool(dn))
          r.fail(at + ".down", "must be true or false");
        else
          j.down = cJSON_IsTrue(dn);
      }
      if (cJSON_GetObjectItemCaseSensitive(c, "home_flag")) {
        j.has_home = r.number(c, "home_flag", at, -1e6, 1e6, j.home_flag);
      }
      if (cJSON_GetObjectItemCaseSensitive(c, "limits")) j.has_limits = r.numbers(c, "limits", at, 2, j.limits);
      if (cJSON_GetObjectItemCaseSensitive(c, "hard_stops")) j.has_stops = r.numbers(c, "hard_stops", at, 2, j.hard_stops);
      if (!(j.travel[0] < j.travel[1])) r.fail(at + ".travel", "must be [low, high] with low < high");
      if (j.has_limits && !(j.limits[0] < j.limits[1])) r.fail(at + ".limits", "must be [low, high] with low < high");
      if (j.has_stops && !(j.hard_stops[0] < j.hard_stops[1]))
        r.fail(at + ".hard_stops", "must be [low, high] with low < high");
      if (j.has_limits && j.has_stops && (j.hard_stops[0] > j.limits[0] || j.hard_stops[1] < j.limits[1]))
        r.fail(at + ".hard_stops", "must lie outside the limit switches (" + Reader::fmt(j.limits[0]) + ", " +
                                       Reader::fmt(j.limits[1]) + ")");
      if (j.has_stops && (j.hard_stops[0] > j.travel[0] || j.hard_stops[1] < j.travel[1]))
        r.fail(at + ".hard_stops", "must lie outside the travel (" + Reader::fmt(j.travel[0]) + ", " +
                                       Reader::fmt(j.travel[1]) + ")");
      const cJSON* ld = cJSON_GetObjectItemCaseSensitive(c, "load");
      if (ld && r.object(ld, at + ".load")) {
        r.keys(ld, at + ".load", {"hold_permille", "per_kg_permille", "per_m_s2_permille"});
        r.number(ld, "hold_permille", at + ".load", -5000, 5000, j.hold_permille);
        r.number(ld, "per_kg_permille", at + ".load", -5000, 5000, j.per_kg_permille);
        r.number(ld, "per_m_s2_permille", at + ".load", -5000, 5000, j.per_m_s2_permille);
      }
      out.joints.push_back(j);
    }
    for (const char* n : {"x", "y", "z"}) {
      if (!cJSON_GetObjectItemCaseSensitive(js, n)) r.fail("joints", std::string("joint \"") + n + "\" is missing");
    }
    // In x, y, z order.
    std::sort(out.joints.begin(), out.joints.end(),
              [](const MachineJoint& a, const MachineJoint& b) { return a.name < b.name; });
    std::set<unsigned> nodes;
    for (const auto& j : out.joints)
      if (j.node && !nodes.insert(j.node).second)
        r.fail("joints." + j.name, "node " + std::to_string(j.node) + " drives another joint too");
  }

  // Part kinds.
  const cJSON* ps = cJSON_GetObjectItemCaseSensitive(root, "parts");
  if (ps && r.object(ps, "parts")) {
    for (const cJSON* c = ps->child; c; c = c->next) {
      std::string at = std::string("parts.") + c->string;
      if (!r.object(c, at)) continue;
      r.keys(c, at, {"size", "mass_kg"});
      MachinePartKind k;
      k.name = c->string;
      r.numbers(c, "size", at, 3, k.size, true, 1, 2000);
      r.number(c, "mass_kg", at, 0, 1000, k.mass_kg);
      out.parts[k.name] = k;
    }
  }

  // Tool.
  const cJSON* tl = cJSON_GetObjectItemCaseSensitive(root, "tool");
  if (tl && r.object(tl, "tool")) {
    MachineTool& t = out.tool;
    r.keys(tl, "tool", {"type", "close", "gripped", "stroke_ms", "open_mm", "closed_mm", "axis", "offset",
                        "pick_tolerance_mm", "finger"});
    std::string type;
    r.text(tl, "type", "tool", type, true);
    if (!type.empty() && type != "gripper") r.fail("tool.type", "must be \"gripper\"");
    t.present = true;
    r.bit(tl, "close", "tool", t.close);
    t.has_gripped = r.bit(tl, "gripped", "tool", t.gripped, false);
    r.number(tl, "stroke_ms", "tool", 1, 60000, t.stroke_ms);
    r.number(tl, "open_mm", "tool", 1, 2000, t.open_mm);
    r.number(tl, "closed_mm", "tool", 0, 2000, t.closed_mm);
    if (t.closed_mm >= t.open_mm) r.fail("tool.closed_mm", "must be smaller than open_mm");
    std::string axis = "x";
    r.text(tl, "axis", "tool", axis);
    if (axis != "x" && axis != "y")
      r.fail("tool.axis", "must be \"x\" or \"y\"");
    else
      t.axis = axis[0];
    r.numbers(tl, "offset", "tool", 3, t.offset);
    r.number(tl, "pick_tolerance_mm", "tool", 0, 1000, t.pick_tolerance_mm);
    r.numbers(tl, "finger", "tool", 3, t.finger, false, 1, 1000);
  }

  // Conveyors.
  std::set<std::string> names = {"x", "y", "z", "tool"};
  auto unique = [&](const std::string& at, const std::string& name) {
    if (!names.insert(name).second) r.fail(at, "the name \"" + name + "\" is used by another element");
  };
  auto list = [&](const char* key, const std::function<void(const cJSON*, const std::string&)>& each) {
    const cJSON* a = cJSON_GetObjectItemCaseSensitive(root, key);
    if (!a) return;
    if (!cJSON_IsArray(a)) {
      r.fail(key, "must be a list");
      return;
    }
    int i = 0;
    for (const cJSON* c = a->child; c; c = c->next, ++i) {
      std::string at = std::string(key) + "[" + std::to_string(i) + "]";
      if (r.object(c, at)) each(c, at);
    }
  };
  list("conveyors", [&](const cJSON* c, const std::string& at) {
    r.keys(c, at, {"name", "from", "to", "width", "height", "speed_mm_s", "gap_mm", "run", "feed"});
    MachineConveyor v;
    r.text(c, "name", at, v.name, true);
    unique(at, v.name);
    r.numbers(c, "from", at, 2, v.from, true);
    r.numbers(c, "to", at, 2, v.to, true);
    r.number(c, "width", at, 1, 5000, v.width);
    r.number(c, "height", at, 0, 5000, v.height);
    r.number(c, "speed_mm_s", at, 0, 10000, v.speed_mm_s);
    r.number(c, "gap_mm", at, 0, 1000, v.gap_mm);
    r.bit(c, "run", at, v.run);
    bool along_x = std::fabs(v.from[1] - v.to[1]) < kEps, along_y = std::fabs(v.from[0] - v.to[0]) < kEps;
    if (along_x == along_y) r.fail(at, "a conveyor runs along x or y: \"from\" and \"to\" share x or y, not both");
    const cJSON* f = cJSON_GetObjectItemCaseSensitive(c, "feed");
    if (f && r.object(f, at + ".feed")) {
      r.keys(f, at + ".feed", {"part", "every_s"});
      v.has_feed = r.text(f, "part", at + ".feed", v.feed_part, true);
      if (r.numbers(f, "every_s", at + ".feed", 2, v.every_s, true, 0.01, 3600) && v.every_s[0] > v.every_s[1])
        r.fail(at + ".feed.every_s", "must be [shortest, longest]");
      if (v.has_feed && !out.parts.count(v.feed_part))
        r.fail(at + ".feed.part", "part kind \"" + v.feed_part + "\" is not defined in \"parts\"");
    }
    out.conveyors.push_back(v);
  });
  list("sensors", [&](const cJSON* c, const std::string& at) {
    r.keys(c, at, {"name", "at", "size", "detects", "output"});
    MachineSensor v;
    r.text(c, "name", at, v.name, true);
    unique(at, v.name);
    r.numbers(c, "at", at, 3, v.at, true);
    r.numbers(c, "size", at, 3, v.size, true, 0.1, 10000);
    std::string det = "part";
    r.text(c, "detects", at, det);
    if (det != "part" && det != "tool") r.fail(at + ".detects", "must be \"part\" or \"tool\"");
    v.detects_tool = det == "tool";
    r.bit(c, "output", at, v.output);
    out.sensors.push_back(v);
  });
  list("fixtures", [&](const cJSON* c, const std::string& at) {
    r.keys(c, at, {"name", "slots", "height", "margin", "place_tolerance_mm", "change"});
    MachineFixture v;
    r.text(c, "name", at, v.name, true);
    unique(at, v.name);
    const cJSON* s = cJSON_GetObjectItemCaseSensitive(c, "slots");
    if (!s) {
      r.fail(at, "\"slots\" is required");
    } else if (r.object(s, at + ".slots")) {
      r.keys(s, at + ".slots", {"origin", "pitch", "count"});
      r.numbers(s, "origin", at + ".slots", 2, v.origin, true);
      r.numbers(s, "pitch", at + ".slots", 2, v.pitch, true, 1, 10000);
      double n[2] = {1, 1};
      if (r.numbers(s, "count", at + ".slots", 2, n, true, 1, 20)) {
        if (n[0] != std::floor(n[0]) || n[1] != std::floor(n[1]))
          r.fail(at + ".slots.count", "must be two integers");
        v.count[0] = static_cast<unsigned>(n[0]);
        v.count[1] = static_cast<unsigned>(n[1]);
      }
    }
    r.number(c, "height", at, 0, 5000, v.height);
    r.number(c, "margin", at, 0, 1000, v.margin);
    r.number(c, "place_tolerance_mm", at, 0, 1000, v.place_tolerance_mm);
    const cJSON* ch = cJSON_GetObjectItemCaseSensitive(c, "change");
    if (ch && r.object(ch, at + ".change")) {
      r.keys(ch, at + ".change", {"request", "ready", "time_s", "move"});
      v.has_change = true;
      r.bit(ch, "request", at + ".change", v.change_request);
      r.bit(ch, "ready", at + ".change", v.change_ready);
      r.number(ch, "time_s", at + ".change", 0.01, 3600, v.change_time_s);
      r.numbers(ch, "move", at + ".change", 2, v.change_move);
    }
    out.fixtures.push_back(v);
  });

  // No input bit bound twice, and no bit both read and written.
  std::map<std::string, std::string> seen;
  for (const auto& b : out.inputs()) {
    auto ins = seen.emplace(b.first.str(), b.second);
    if (!ins.second) r.fail("", b.first.str() + " is bound twice: " + ins.first->second + " and " + b.second);
  }
  for (const auto& b : out.outputs()) {
    auto it = seen.find(b.first.str());
    if (it != seen.end()) r.fail("", b.first.str() + " is both an output (" + b.second + ") and an input (" + it->second + ")");
  }
  return errors.size() == before;
}

bool load_machine_file(const std::string& path, MachineSpec& out, std::vector<std::string>& errors) {
  std::ifstream in(path);
  if (!in) {
    errors.push_back(path + ": cannot read the machine file");
    return false;
  }
  std::stringstream ss;
  ss << in.rdbuf();
  return parse_machine_file(ss.str(), path, out, errors);
}

bool parse_machine_fault(const cJSON* f, std::string& err) {
  if (!cJSON_IsObject(f) || !f->child || f->child->next) {
    err = "a machine fault is an object with one of jam, stuck, slip, feeder, misaligned_mm";
    return false;
  }
  const char* k = f->child->string;
  if (!std::strcmp(k, "jam") || !std::strcmp(k, "slip")) {
    if (!cJSON_IsTrue(f->child)) {
      err = std::string("\"") + k + "\" must be true";
      return false;
    }
    return true;
  }
  if (!std::strcmp(k, "stuck")) {
    if (!cJSON_IsString(f->child) || (std::strcmp(f->child->valuestring, "on") && std::strcmp(f->child->valuestring, "off"))) {
      err = "\"stuck\" must be \"on\" or \"off\"";
      return false;
    }
    return true;
  }
  if (!std::strcmp(k, "feeder")) {
    if (!cJSON_IsString(f->child) ||
        (std::strcmp(f->child->valuestring, "stop") && std::strcmp(f->child->valuestring, "empty"))) {
      err = "\"feeder\" must be \"stop\" or \"empty\"";
      return false;
    }
    return true;
  }
  if (!std::strcmp(k, "misaligned_mm")) {
    if (!cJSON_IsNumber(f->child) || !std::isfinite(f->child->valuedouble) || std::fabs(f->child->valuedouble) > 1000) {
      err = "\"misaligned_mm\" must be a number -1000 to 1000";
      return false;
    }
    return true;
  }
  err = std::string("unknown machine fault \"") + k + "\" (jam, stuck, slip, feeder, misaligned_mm)";
  return false;
}

bool is_machine_clear_name(const std::string& n) {
  return n == "jam" || n == "stuck" || n == "feeder" || n == "misaligned_mm" || n == "all";
}

// ---- the model ----

MachineModel::MachineModel(const MachineSpec& spec, MachineIo& io) : spec_(spec), io_(io) { Reset(); }

void MachineModel::Reset() {
  rng_.seed(spec_.seed);
  next_id_ = 1;
  parts_.clear();
  parts_.reserve(kMaxMachineParts + 1);
  counters_ = Counters();
  size_t nj = spec_.joints.size();
  jp_.assign(nj, 0);
  jv_.assign(nj, 0);
  ja_.assign(nj, 0);
  jpush_.assign(nj, 0);
  jd_.assign(nj, MachineIo::Drive());
  jam_.assign(nj, false);
  opening_ = spec_.tool.open_mm;
  close_cmd_ = false;
  stroke_ = 0;
  held_ = -1;
  size_t nc = spec_.conveyors.size();
  feed_wait_.assign(nc, 0);
  for (size_t i = 0; i < nc; ++i)
    if (spec_.conveyors[i].has_feed) feed_wait_[i] = Random(spec_.conveyors[i].every_s[0], spec_.conveyors[i].every_s[1]);
  belt_travel_.assign(nc, 0);
  feeder_fault_.assign(nc, 0);
  misalign_.assign(nc, 0);
  misalign_pending_.assign(nc, false);
  stuck_.assign(spec_.sensors.size(), 0);
  sensor_on_.assign(spec_.sensors.size(), false);
  size_t nf = spec_.fixtures.size();
  change_.assign(nf, -1);
  offset_x_.assign(nf, 0);
  offset_y_.assign(nf, 0);
  ready_.assign(nf, true);
  request_prev_.assign(nf, false);
  emptied_.assign(nf, false);
  for (size_t i = 0; i < nj; ++i) jp_[i] = spec_.joints[i].travel[0];
  UpdateTool();
}

double MachineModel::Random(double a, double b) {
  // mt19937's output is the same on every platform; the distributions are not.
  uint32_t x = rng_();
  return a + (b - a) * (static_cast<double>(x) / 4294967295.0);
}

int MachineModel::JointIndex(const std::string& n) const {
  for (size_t i = 0; i < spec_.joints.size(); ++i)
    if (spec_.joints[i].name == n) return static_cast<int>(i);
  return -1;
}
int MachineModel::ConveyorIndex(const std::string& n) const {
  for (size_t i = 0; i < spec_.conveyors.size(); ++i)
    if (spec_.conveyors[i].name == n) return static_cast<int>(i);
  return -1;
}
int MachineModel::SensorIndex(const std::string& n) const {
  for (size_t i = 0; i < spec_.sensors.size(); ++i)
    if (spec_.sensors[i].name == n) return static_cast<int>(i);
  return -1;
}
int MachineModel::FixtureIndex(const std::string& n) const {
  for (size_t i = 0; i < spec_.fixtures.size(); ++i)
    if (spec_.fixtures[i].name == n) return static_cast<int>(i);
  return -1;
}

double MachineModel::SlotX(const MachineFixture& f, unsigned i) const { return f.origin[0] + i * f.pitch[0]; }
double MachineModel::SlotY(const MachineFixture& f, unsigned j) const { return f.origin[1] + j * f.pitch[1]; }

MachineModel::Box MachineModel::PartBox(const Part& p) const {
  const double* s = p.kind->size;
  return Box{{p.pos[0] - s[0] / 2, p.pos[1] - s[1] / 2, p.pos[2]}, {p.pos[0] + s[0] / 2, p.pos[1] + s[1] / 2, p.pos[2] + s[2]}};
}

MachineModel::Box MachineModel::ConveyorBox(size_t i) const {
  const MachineConveyor& c = spec_.conveyors[i];
  bool along_x = std::fabs(c.from[1] - c.to[1]) < kEps;
  Box b;
  if (along_x) {
    b.lo[0] = std::min(c.from[0], c.to[0]);
    b.hi[0] = std::max(c.from[0], c.to[0]);
    b.lo[1] = c.from[1] - c.width / 2;
    b.hi[1] = c.from[1] + c.width / 2;
  } else {
    b.lo[0] = c.from[0] - c.width / 2;
    b.hi[0] = c.from[0] + c.width / 2;
    b.lo[1] = std::min(c.from[1], c.to[1]);
    b.hi[1] = std::max(c.from[1], c.to[1]);
  }
  b.lo[2] = 0;
  b.hi[2] = c.height;
  return b;
}

MachineModel::Box MachineModel::FixtureBox(size_t i) const {
  const MachineFixture& f = spec_.fixtures[i];
  // The pallet covers the slots' parts (the largest part kind) and its margin.
  double px = 0, py = 0;
  for (const auto& k : spec_.parts) {
    px = std::max(px, k.second.size[0]);
    py = std::max(py, k.second.size[1]);
  }
  Box b;
  b.lo[0] = f.origin[0] - px / 2 - f.margin + offset_x_[i];
  b.hi[0] = SlotX(f, f.count[0] - 1) + px / 2 + f.margin + offset_x_[i];
  b.lo[1] = f.origin[1] - py / 2 - f.margin + offset_y_[i];
  b.hi[1] = SlotY(f, f.count[1] - 1) + py / 2 + f.margin + offset_y_[i];
  b.lo[2] = 0;
  b.hi[2] = f.height;
  return b;
}

std::vector<MachineModel::Box> MachineModel::ToolBoxes(bool with_part) const {
  std::vector<Box> v;
  if (!spec_.tool.present) return v;
  const MachineTool& t = spec_.tool;
  int a = t.axis == 'x' ? 0 : 1, o = 1 - a;
  for (int side : {-1, 1}) {
    Box b;
    double c = tool_[a] + side * (opening_ / 2 + t.finger[0] / 2);
    b.lo[a] = c - t.finger[0] / 2;
    b.hi[a] = c + t.finger[0] / 2;
    b.lo[o] = tool_[o] - t.finger[1] / 2;
    b.hi[o] = tool_[o] + t.finger[1] / 2;
    b.lo[2] = tool_[2];
    b.hi[2] = tool_[2] + t.finger[2];
    v.push_back(b);
  }
  if (with_part && held_ >= 0) v.push_back(PartBox(parts_[held_]));
  return v;
}

double MachineModel::Support(const Box& b, unsigned skip_id, Obstacle& what, int& index) const {
  double top = 0;
  what = Obstacle::Table;
  index = -1;
  auto under = [&](const Box& o) {
    return overlap(b.lo[0], b.hi[0], o.lo[0], o.hi[0]) > 0.01 && overlap(b.lo[1], b.hi[1], o.lo[1], o.hi[1]) > 0.01 &&
           o.hi[2] <= b.lo[2] + 0.5;
  };
  for (size_t i = 0; i < spec_.conveyors.size(); ++i) {
    Box o = ConveyorBox(i);
    if (under(o) && o.hi[2] > top) {
      top = o.hi[2];
      what = Obstacle::Conveyor;
      index = static_cast<int>(i);
    }
  }
  for (size_t i = 0; i < spec_.fixtures.size(); ++i) {
    Box o = FixtureBox(i);
    if (under(o) && o.hi[2] > top) {
      top = o.hi[2];
      what = Obstacle::Fixture;
      index = static_cast<int>(i);
    }
  }
  for (size_t i = 0; i < parts_.size(); ++i) {
    const Part& p = parts_[i];
    if (p.id == skip_id || p.state == PartState::Held || p.state == PartState::Falling) continue;
    Box o = PartBox(p);
    if (under(o) && o.hi[2] > top) {
      top = o.hi[2];
      what = Obstacle::Part;
      index = static_cast<int>(i);
    }
  }
  return top;
}

// Whether moving joint `j` in direction `dir` (joint coordinates) pushes the
// tool, a finger or the held part further into a part, a pallet, a conveyor
// or the table.
bool MachineModel::Blocks(size_t j, int dir) const {
  if (!dir || !spec_.tool.present) return false;
  const MachineJoint& jt = spec_.joints[j];
  int axis = jt.name == "x" ? 0 : jt.name == "y" ? 1 : 2;
  double step = 0.5 * dir;
  if (axis == 2 && jt.down) step = -step;
  std::vector<Box> obstacles;
  obstacles.push_back(Box{{-1e9, -1e9, -1e9}, {1e9, 1e9, 0}});
  for (size_t i = 0; i < spec_.conveyors.size(); ++i) obstacles.push_back(ConveyorBox(i));
  for (size_t i = 0; i < spec_.fixtures.size(); ++i) obstacles.push_back(FixtureBox(i));
  for (size_t i = 0; i < parts_.size(); ++i)
    if (static_cast<int>(i) != held_ && parts_[i].state != PartState::Falling) obstacles.push_back(PartBox(parts_[i]));
  for (const Box& b : ToolBoxes(true)) {
    Box m = b;
    m.lo[axis] += step;
    m.hi[axis] += step;
    for (const Box& o : obstacles) {
      bool others = true;
      for (int k = 0; k < 3 && others; ++k)
        if (k != axis) others = overlap(b.lo[k], b.hi[k], o.lo[k], o.hi[k]) > 0.05;
      if (!others) continue;
      double now = overlap(b.lo[axis], b.hi[axis], o.lo[axis], o.hi[axis]);
      double next = overlap(m.lo[axis], m.hi[axis], o.lo[axis], o.hi[axis]);
      if (next > 0.01 && next > now + 1e-9) return true;
    }
  }
  return false;
}

void MachineModel::UpdateTool() {
  const MachineTool& t = spec_.tool;
  tool_[0] = t.offset[0];
  tool_[1] = t.offset[1];
  tool_[2] = t.offset[2];
  for (size_t i = 0; i < spec_.joints.size(); ++i) {
    const MachineJoint& j = spec_.joints[i];
    if (j.name == "x") tool_[0] += jp_[i];
    else if (j.name == "y") tool_[1] += jp_[i];
    else tool_[2] += j.down ? -jp_[i] : jp_[i];
  }
  if (held_ >= 0) {
    Part& p = parts_[held_];
    for (int k = 0; k < 3; ++k) p.pos[k] = tool_[k] + p.hold[k];
  }
}

void MachineModel::Release() {
  if (held_ < 0) return;
  Part& p = parts_[held_];
  p.state = PartState::Falling;
  p.vz = 0;
  held_ = -1;
}

void MachineModel::StepGripper(double dt) {
  const MachineTool& t = spec_.tool;
  if (!t.present) return;
  bool close = io_.output(t.close);
  if (!close && close_cmd_) Release();
  close_cmd_ = close;
  double rate = dt * 1000 / t.stroke_ms;
  double before = stroke_;
  stroke_ = close ? std::min(1.0, stroke_ + rate) : std::max(0.0, stroke_ - rate);
  double target = t.open_mm - stroke_ * (t.open_mm - t.closed_mm);
  int a = t.axis == 'x' ? 0 : 1;
  if (held_ >= 0) {
    opening_ = parts_[held_].kind->size[a];
    return;
  }
  // Fingers close on a part between them.
  double stop = t.closed_mm;
  int between = -1;
  for (size_t i = 0; i < parts_.size(); ++i) {
    const Part& p = parts_[i];
    if (p.state == PartState::Falling) continue;
    const double* s = p.kind->size;
    if (s[a] >= t.open_mm) continue;
    double d = std::fabs(p.pos[a] - tool_[a]), e = std::fabs(p.pos[1 - a] - tool_[1 - a]);
    if (d > t.pick_tolerance_mm || e > t.pick_tolerance_mm) continue;
    // The fingers overlap the part's side by at least 10 mm.
    if (tool_[2] < p.pos[2] - 1 || tool_[2] > p.pos[2] + s[2] - 10) continue;
    if (s[a] > stop) {
      stop = s[a];
      between = static_cast<int>(i);
    }
  }
  opening_ = std::max(target, stop);
  if (close && between >= 0 && stroke_ >= 1 && before >= 0) {
    Part& p = parts_[between];
    if (p.state == PartState::Placed) --counters_.placed;
    if (p.state == PartState::Misplaced) --counters_.misplaced;
    p.state = PartState::Held;
    p.conveyor = p.fixture = p.slot = -1;
    for (int k = 0; k < 3; ++k) p.hold[k] = p.pos[k] - tool_[k];
    held_ = between;
    ++counters_.picked;
  }
}

void MachineModel::StepConveyors(double dt) {
  for (size_t ci = 0; ci < spec_.conveyors.size(); ++ci) {
    const MachineConveyor& c = spec_.conveyors[ci];
    bool along_x = std::fabs(c.from[1] - c.to[1]) < kEps;
    int a = along_x ? 0 : 1;
    double len = std::fabs(along_x ? c.to[0] - c.from[0] : c.to[1] - c.from[1]);
    double dir = (along_x ? c.to[0] - c.from[0] : c.to[1] - c.from[1]) > 0 ? 1 : -1;
    bool run = io_.output(c.run);
    // Parts on this belt, front first.
    std::vector<size_t> on;
    for (size_t i = 0; i < parts_.size(); ++i)
      if (parts_[i].state == PartState::Belt && parts_[i].conveyor == static_cast<int>(ci)) on.push_back(i);
    std::sort(on.begin(), on.end(), [&](size_t x, size_t y) { return parts_[x].s > parts_[y].s; });
    if (run) belt_travel_[ci] += c.speed_mm_s * dt;
    double limit = len;  // the end stop
    for (size_t i : on) {
      Part& p = parts_[i];
      double half = p.kind->size[a] / 2;
      double max_s = limit - half;
      if (run && p.s < max_s) p.s = std::min(p.s + c.speed_mm_s * dt, max_s);
      limit = p.s - half - c.gap_mm;
      p.pos[a] = (along_x ? c.from[0] : c.from[1]) + dir * p.s;
      p.pos[1 - a] = (along_x ? c.from[1] : c.from[0]) + p.lateral;
      p.pos[2] = c.height;
    }
    // Feeder.
    if (!c.has_feed) continue;
    feed_wait_[ci] -= dt;
    if (feed_wait_[ci] > 0 || feeder_fault_[ci]) continue;
    const MachinePartKind& k = spec_.parts.at(c.feed_part);
    double half = k.size[a] / 2;
    bool room = limit >= half;  // the last part on the belt leaves room at the start
    if (!room || parts_.size() >= kMaxMachineParts) {
      // Remove the oldest part on the table to make room.
      if (room) {
        auto it = std::find_if(parts_.begin(), parts_.end(), [](const Part& p) { return p.state == PartState::Table; });
        if (it == parts_.end()) continue;
        size_t idx = static_cast<size_t>(it - parts_.begin());
        if (held_ > static_cast<int>(idx)) --held_;
        parts_.erase(it);
      } else {
        continue;
      }
    }
    Part p;
    p.id = next_id_++;
    p.kind = &k;
    p.state = PartState::Belt;
    p.conveyor = static_cast<int>(ci);
    p.s = half;
    if (misalign_pending_[ci]) {
      p.lateral = misalign_[ci];
      misalign_pending_[ci] = false;
    }
    p.pos[a] = (along_x ? c.from[0] : c.from[1]) + dir * p.s;
    p.pos[1 - a] = (along_x ? c.from[1] : c.from[0]) + p.lateral;
    p.pos[2] = c.height;
    parts_.push_back(p);
    ++counters_.fed;
    feed_wait_[ci] = Random(c.every_s[0], c.every_s[1]);
  }
}

void MachineModel::Land(Part& p, Obstacle what, int index) {
  p.vz = 0;
  if (what == Obstacle::Conveyor) {
    const MachineConveyor& c = spec_.conveyors[index];
    bool along_x = std::fabs(c.from[1] - c.to[1]) < kEps;
    double dir = (along_x ? c.to[0] - c.from[0] : c.to[1] - c.from[1]) > 0 ? 1 : -1;
    p.state = PartState::Belt;
    p.conveyor = index;
    p.s = dir * (along_x ? p.pos[0] - c.from[0] : p.pos[1] - c.from[1]);
    p.lateral = along_x ? p.pos[1] - c.from[1] : p.pos[0] - c.from[0];
    return;
  }
  if (what == Obstacle::Fixture) {
    const MachineFixture& f = spec_.fixtures[index];
    p.fixture = index;
    double best = 1e18;
    int slot = -1;
    for (unsigned j = 0; j < f.count[1]; ++j)
      for (unsigned i = 0; i < f.count[0]; ++i) {
        double dx = p.pos[0] - (SlotX(f, i) + offset_x_[index]), dy = p.pos[1] - (SlotY(f, j) + offset_y_[index]);
        double d = std::sqrt(dx * dx + dy * dy);
        if (d < best) {
          best = d;
          slot = static_cast<int>(j * f.count[0] + i);
        }
      }
    bool free = true;
    for (const Part& o : parts_)
      if (&o != &p && o.state == PartState::Placed && o.fixture == index && o.slot == slot) free = false;
    if (slot >= 0 && free && best <= f.place_tolerance_mm && change_[index] < 0) {
      p.state = PartState::Placed;
      p.slot = slot;
      p.pos[0] = SlotX(f, slot % f.count[0]) + offset_x_[index];
      p.pos[1] = SlotY(f, slot / f.count[0]) + offset_y_[index];
      ++counters_.placed;
    } else {
      p.state = PartState::Misplaced;
      p.slot = -1;
      ++counters_.misplaced;
    }
    return;
  }
  if (what == Obstacle::Part) {
    // On another part: on a pallet it counts with that pallet.
    const Part& under = parts_[index];
    p.fixture = under.fixture;
    p.slot = -1;
    if (under.state == PartState::Table) {
      p.state = PartState::Table;
      ++counters_.dropped;
    } else {
      p.state = PartState::Misplaced;
      ++counters_.misplaced;
    }
    return;
  }
  p.state = PartState::Table;
  ++counters_.dropped;
}

void MachineModel::StepFalling(double dt) {
  for (auto& p : parts_) {
    if (p.state != PartState::Falling) continue;
    p.vz -= kGravity * dt;
    double next = p.pos[2] + p.vz * dt;
    Obstacle what;
    int index;
    Box b = PartBox(p);
    double top = Support(b, p.id, what, index);
    if (next <= top) {
      p.pos[2] = top;
      Land(p, what, index);
    } else {
      p.pos[2] = next;
    }
  }
}

void MachineModel::StepFixtures(double dt) {
  for (size_t i = 0; i < spec_.fixtures.size(); ++i) {
    const MachineFixture& f = spec_.fixtures[i];
    if (!f.has_change) continue;
    bool req = io_.output(f.change_request);
    if (req && !request_prev_[i] && change_[i] < 0) {
      change_[i] = 0;
      ready_[i] = false;
      emptied_[i] = false;
    }
    request_prev_[i] = req;
    if (change_[i] < 0) continue;
    double before_x = offset_x_[i], before_y = offset_y_[i];
    change_[i] += dt / f.change_time_s;
    double k = change_[i] < 0.5 ? smooth(change_[i] * 2) : smooth(2 - change_[i] * 2);
    offset_x_[i] = f.change_move[0] * k;
    offset_y_[i] = f.change_move[1] * k;
    // Parts on the pallet go with it.
    for (auto& p : parts_)
      if ((p.state == PartState::Placed || p.state == PartState::Misplaced) && p.fixture == static_cast<int>(i)) {
        p.pos[0] += offset_x_[i] - before_x;
        p.pos[1] += offset_y_[i] - before_y;
      }
    if (change_[i] >= 0.5 && !emptied_[i]) {
      emptied_[i] = true;
      parts_.erase(std::remove_if(parts_.begin(), parts_.end(),
                                  [&](const Part& p) {
                                    return (p.state == PartState::Placed || p.state == PartState::Misplaced) &&
                                           p.fixture == static_cast<int>(i);
                                  }),
                   parts_.end());
      held_ = -1;
      for (size_t k2 = 0; k2 < parts_.size(); ++k2)
        if (parts_[k2].state == PartState::Held) held_ = static_cast<int>(k2);
    }
    if (change_[i] >= 1) {
      change_[i] = -1;
      offset_x_[i] = offset_y_[i] = 0;
      ready_[i] = true;
      ++counters_.pallets;
    }
  }
}

void MachineModel::WriteInputs() {
  const MachineTool& t = spec_.tool;
  if (t.present && t.has_gripped) io_.set_input(t.gripped, held_ >= 0 && close_cmd_);
  std::vector<Box> tool = ToolBoxes(false);
  for (size_t i = 0; i < spec_.sensors.size(); ++i) {
    const MachineSensor& s = spec_.sensors[i];
    Box sb{{s.at[0] - s.size[0] / 2, s.at[1] - s.size[1] / 2, s.at[2] - s.size[2] / 2},
           {s.at[0] + s.size[0] / 2, s.at[1] + s.size[1] / 2, s.at[2] + s.size[2] / 2}};
    auto hit = [&](const Box& b) {
      for (int k = 0; k < 3; ++k)
        if (overlap(b.lo[k], b.hi[k], sb.lo[k], sb.hi[k]) <= 0) return false;
      return true;
    };
    bool on = false;
    if (s.detects_tool) {
      for (const Box& b : tool) on = on || hit(b);
    } else {
      for (const Part& p : parts_) on = on || hit(PartBox(p));
    }
    sensor_on_[i] = on;
    if (stuck_[i] == 1) on = true;
    if (stuck_[i] == 2) on = false;
    io_.set_input(s.output, on);
  }
  for (size_t i = 0; i < spec_.fixtures.size(); ++i)
    if (spec_.fixtures[i].has_change) io_.set_input(spec_.fixtures[i].change_ready, ready_[i]);
}

void MachineModel::Step(double dt) {
  if (!(dt > 0)) return;
  // Joints from the drives.
  for (size_t i = 0; i < spec_.joints.size(); ++i) {
    const MachineJoint& j = spec_.joints[i];
    MachineIo::Drive d = io_.drive(j.node);
    jd_[i] = d;
    if (!d.present) continue;
    double pos = j.direction * d.actual / j.counts_per_mm + j.offset_mm;
    double v = (pos - jp_[i]) / dt;
    double a = (v - jv_[i]) / dt;
    double k = 1 - std::exp(-dt / 0.01);  // 10 ms filter on velocity and acceleration
    jv_[i] += (v - jv_[i]) * k;
    ja_[i] += (a - ja_[i]) * k;
    jp_[i] = pos;
    double e = (d.demand - d.actual) * j.direction;
    jpush_[i] = std::fabs(e) > 0.5 ? (e > 0 ? 1 : -1) : d.demand_velocity * j.direction > 0 ? 1
                                                       : d.demand_velocity * j.direction < 0 ? -1
                                                                                             : 0;
  }
  UpdateTool();
  StepGripper(dt);
  StepConveyors(dt);
  StepFalling(dt);
  StepFixtures(dt);
  UpdateTool();
  // Drive inputs and load.
  double payload = held_ >= 0 ? parts_[held_].kind->mass_kg : 0;
  for (size_t i = 0; i < spec_.joints.size(); ++i) {
    const MachineJoint& j = spec_.joints[i];
    if (!jd_[i].present) continue;
    DriveInputs in;
    double p = jp_[i];
    // The switches' direction in drive counts: a joint running against the counts swaps them.
    bool lo_sw = j.has_limits && p <= j.limits[0], hi_sw = j.has_limits && p >= j.limits[1];
    in.positive_limit = j.direction > 0 ? hi_sw : lo_sw;
    in.negative_limit = j.direction > 0 ? lo_sw : hi_sw;
    in.home_switch = j.has_home && p <= j.home_flag;
    int push = jpush_[i];
    bool stop = j.has_stops && ((push > 0 && p >= j.hard_stops[1] - 1e-3) || (push < 0 && p <= j.hard_stops[0] + 1e-3));
    in.blocked = jam_[i] || stop || Blocks(i, push);
    double load = j.hold_permille + j.per_kg_permille * payload + j.per_m_s2_permille * ja_[i] / 1000.0;
    io_.set_drive(j.node, in, load);
  }
  WriteInputs();
}

// ---- faults, values, snapshot ----

bool MachineModel::Fault(const std::string& el, const cJSON* f, std::string& err) {
  if (!parse_machine_fault(f, err)) return false;
  std::string k = f->child->string;
  int j = JointIndex(el), c = ConveyorIndex(el), s = SensorIndex(el);
  auto wrong = [&](const std::string& what) {
    err = "\"" + k + "\" is a fault of " + what + ", not of " + el;
    return false;
  };
  if (j < 0 && c < 0 && s < 0 && el != "tool" && FixtureIndex(el) < 0) {
    err = "the machine has no element \"" + el + "\"";
    return false;
  }
  if (k == "jam") {
    if (j < 0) return wrong("a joint");
    jam_[j] = true;
    return true;
  }
  if (k == "stuck") {
    if (s < 0) return wrong("a sensor");
    stuck_[s] = std::strcmp(f->child->valuestring, "on") == 0 ? 1 : 2;
    return true;
  }
  if (k == "slip") {
    if (el != "tool") return wrong("the tool");
    Release();
    return true;
  }
  if (k == "feeder") {
    if (c < 0 || !spec_.conveyors[c].has_feed) return wrong("a conveyor with a feeder");
    feeder_fault_[c] = std::strcmp(f->child->valuestring, "stop") == 0 ? 1 : 2;
    return true;
  }
  // misaligned_mm
  if (c < 0 || !spec_.conveyors[c].has_feed) return wrong("a conveyor with a feeder");
  misalign_[c] = f->child->valuedouble;
  misalign_pending_[c] = true;
  return true;
}

bool MachineModel::Clear(const std::string& el, const std::string& name, std::string& err) {
  if (!is_machine_clear_name(name)) {
    err = "\"" + name + "\" is not a machine fault (jam, stuck, feeder, misaligned_mm, all)";
    return false;
  }
  bool all_elements = el == "all" || el.empty();
  int j = JointIndex(el), c = ConveyorIndex(el), s = SensorIndex(el);
  if (!all_elements && j < 0 && c < 0 && s < 0 && el != "tool" && FixtureIndex(el) < 0) {
    err = "the machine has no element \"" + el + "\"";
    return false;
  }
  bool all = name == "all";
  for (size_t i = 0; i < jam_.size(); ++i)
    if ((all_elements || static_cast<int>(i) == j) && (all || name == "jam")) jam_[i] = false;
  for (size_t i = 0; i < stuck_.size(); ++i)
    if ((all_elements || static_cast<int>(i) == s) && (all || name == "stuck")) stuck_[i] = 0;
  for (size_t i = 0; i < feeder_fault_.size(); ++i) {
    if (!all_elements && static_cast<int>(i) != c) continue;
    if (all || name == "feeder") feeder_fault_[i] = 0;
    if (all || name == "misaligned_mm") misalign_pending_[i] = false;
  }
  return true;
}

cJSON* MachineModel::FaultsJson() const {
  cJSON* a = cJSON_CreateArray();
  auto add = [&](const std::string& el, cJSON* f) {
    cJSON* o = cJSON_CreateObject();
    cJSON_AddStringToObject(o, "machine", el.c_str());
    cJSON_AddItemToObject(o, "fault", f);
    cJSON_AddItemToArray(a, o);
  };
  for (size_t i = 0; i < jam_.size(); ++i)
    if (jam_[i]) {
      cJSON* f = cJSON_CreateObject();
      cJSON_AddBoolToObject(f, "jam", true);
      add(spec_.joints[i].name, f);
    }
  for (size_t i = 0; i < stuck_.size(); ++i)
    if (stuck_[i]) {
      cJSON* f = cJSON_CreateObject();
      cJSON_AddStringToObject(f, "stuck", stuck_[i] == 1 ? "on" : "off");
      add(spec_.sensors[i].name, f);
    }
  for (size_t i = 0; i < feeder_fault_.size(); ++i) {
    if (feeder_fault_[i]) {
      cJSON* f = cJSON_CreateObject();
      cJSON_AddStringToObject(f, "feeder", feeder_fault_[i] == 1 ? "stop" : "empty");
      add(spec_.conveyors[i].name, f);
    }
    if (misalign_pending_[i]) {
      cJSON* f = cJSON_CreateObject();
      cJSON_AddNumberToObject(f, "misaligned_mm", misalign_[i]);
      add(spec_.conveyors[i].name, f);
    }
  }
  return a;
}

bool MachineModel::Value(const std::string& n, double& out) const {
  const Counters& c = counters_;
  if (n == "fed") out = c.fed;
  else if (n == "picked") out = c.picked;
  else if (n == "placed") out = c.placed;
  else if (n == "misplaced") out = c.misplaced;
  else if (n == "dropped") out = c.dropped;
  else if (n == "pallets") out = c.pallets;
  else if (SensorIndex(n) >= 0) {
    int s = SensorIndex(n);
    out = stuck_[s] == 1 ? 1 : stuck_[s] == 2 ? 0 : sensor_on_[s] ? 1 : 0;
  } else if (FixtureIndex(n) >= 0) {
    int f = FixtureIndex(n);
    out = 0;
    for (const Part& p : parts_)
      if (p.state == PartState::Placed && p.fixture == f) out += 1;
  } else if (JointIndex(n) >= 0) {
    out = jp_[JointIndex(n)];
  } else {
    return false;
  }
  return true;
}

std::vector<std::string> MachineModel::Names() const {
  std::vector<std::string> v = {"fed", "picked", "placed", "misplaced", "dropped", "pallets"};
  for (const auto& j : spec_.joints) v.push_back(j.name);
  for (const auto& s : spec_.sensors) v.push_back(s.name);
  for (const auto& f : spec_.fixtures) v.push_back(f.name);
  return v;
}

cJSON* MachineModel::Snapshot() const {
  cJSON* o = cJSON_CreateObject();
  cJSON_AddStringToObject(o, "name", spec_.name.c_str());
  cJSON_AddStringToObject(o, "kind", spec_.kind.c_str());
  auto num = [](cJSON* to, const char* k, double v, double step) { cJSON_AddNumberToObject(to, k, round_to(v, step)); };
  cJSON* js = cJSON_AddObjectToObject(o, "joints");
  for (size_t i = 0; i < spec_.joints.size(); ++i) {
    const MachineJoint& j = spec_.joints[i];
    const MachineIo::Drive& d = jd_[i];
    cJSON* x = cJSON_AddObjectToObject(js, j.name.c_str());
    cJSON_AddNumberToObject(x, "node", j.node);
    num(x, "position", jp_[i], 0.01);
    num(x, "velocity", jv_[i], 0.1);
    num(x, "demand", j.direction * d.demand / j.counts_per_mm + j.offset_mm, 0.01);
    cJSON_AddNumberToObject(x, "actual_counts", std::round(d.actual));
    cJSON_AddStringToObject(x, "state", d.present ? d.state.c_str() : "off");
    cJSON_AddNumberToObject(x, "mode", d.mode);
    cJSON_AddNumberToObject(x, "statusword", d.statusword);
    cJSON_AddBoolToObject(x, "fault", d.fault);
    if (d.error_code) cJSON_AddNumberToObject(x, "error_code", d.error_code);
    cJSON_AddNumberToObject(x, "torque", std::round(d.torque));
  }
  cJSON* t = cJSON_AddObjectToObject(o, "tool");
  cJSON* tp = cJSON_AddArrayToObject(t, "position");
  for (int k = 0; k < 3; ++k) cJSON_AddItemToArray(tp, cJSON_CreateNumber(round_to(tool_[k], 0.01)));
  num(t, "opening", opening_, 0.01);
  cJSON_AddBoolToObject(t, "closed", close_cmd_);
  if (held_ >= 0)
    cJSON_AddNumberToObject(t, "holding", parts_[held_].id);
  else
    cJSON_AddNullToObject(t, "holding");
  cJSON* ps = cJSON_AddArrayToObject(o, "parts");
  for (const Part& p : parts_) {
    cJSON* x = cJSON_CreateObject();
    cJSON_AddNumberToObject(x, "id", p.id);
    cJSON_AddStringToObject(x, "kind", p.kind->name.c_str());
    cJSON* pp = cJSON_AddArrayToObject(x, "position");
    for (int k = 0; k < 3; ++k) cJSON_AddItemToArray(pp, cJSON_CreateNumber(round_to(p.pos[k], 0.1)));
    cJSON_AddNumberToObject(x, "yaw", 0);
    cJSON_AddStringToObject(x, "state", state_name(p.state));
    cJSON_AddItemToArray(ps, x);
  }
  cJSON* ss = cJSON_AddObjectToObject(o, "sensors");
  for (size_t i = 0; i < spec_.sensors.size(); ++i) {
    bool on = stuck_[i] == 1 ? true : stuck_[i] == 2 ? false : static_cast<bool>(sensor_on_[i]);
    cJSON_AddBoolToObject(ss, spec_.sensors[i].name.c_str(), on);
  }
  cJSON* cs = cJSON_AddObjectToObject(o, "conveyors");
  for (size_t i = 0; i < spec_.conveyors.size(); ++i) {
    cJSON* x = cJSON_AddObjectToObject(cs, spec_.conveyors[i].name.c_str());
    cJSON_AddBoolToObject(x, "running", io_.output(spec_.conveyors[i].run));
    num(x, "travel", std::fmod(belt_travel_[i], 100000.0), 0.1);
  }
  cJSON* fs = cJSON_AddObjectToObject(o, "fixtures");
  for (size_t i = 0; i < spec_.fixtures.size(); ++i) {
    cJSON* x = cJSON_AddObjectToObject(fs, spec_.fixtures[i].name.c_str());
    cJSON* off = cJSON_AddArrayToObject(x, "offset");
    cJSON_AddItemToArray(off, cJSON_CreateNumber(round_to(offset_x_[i], 0.1)));
    cJSON_AddItemToArray(off, cJSON_CreateNumber(round_to(offset_y_[i], 0.1)));
    cJSON_AddBoolToObject(x, "ready", ready_[i]);
    cJSON_AddBoolToObject(x, "changing", change_[i] >= 0);
    double filled = 0;
    Value(spec_.fixtures[i].name, filled);
    cJSON_AddNumberToObject(x, "filled", filled);
  }
  cJSON* c = cJSON_AddObjectToObject(o, "counters");
  cJSON_AddNumberToObject(c, "fed", counters_.fed);
  cJSON_AddNumberToObject(c, "picked", counters_.picked);
  cJSON_AddNumberToObject(c, "placed", counters_.placed);
  cJSON_AddNumberToObject(c, "misplaced", counters_.misplaced);
  cJSON_AddNumberToObject(c, "dropped", counters_.dropped);
  cJSON_AddNumberToObject(c, "pallets", counters_.pallets);
  cJSON_AddItemToObject(o, "faults", FaultsJson());
  return o;
}

}  // namespace canopen_sim
