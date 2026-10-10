// mux.cpp - see mux.h.

#include "mux.h"

#include <algorithm>

#include "cJSON.h"
#include "signals.h"

namespace canworks_can {

namespace {

constexpr uint64_t kSaturate = uint64_t{1} << 40;

uint64_t sat_add(uint64_t a, uint64_t b) { return a + b > kSaturate ? kSaturate : a + b; }
uint64_t sat_mul(uint64_t a, uint64_t b) {
  if (a == 0 || b == 0) return 0;
  return a > kSaturate / b ? kSaturate : (a * b > kSaturate ? kSaturate : a * b);
}

bool whole(const cJSON* v, uint64_t& out) {
  if (!cJSON_IsNumber(v)) return false;
  double d = v->valuedouble;
  if (d < 0 || d > 4294967295.0 || d != static_cast<double>(static_cast<uint64_t>(d))) return false;
  out = static_cast<uint64_t>(d);
  return true;
}

std::string label(const MuxSignalDef& s) { return s.name.empty() ? s.path : s.name; }

bool intersects(const std::vector<MuxRange>& a, const std::vector<MuxRange>& b) {
  for (const MuxRange& x : a)
    for (const MuxRange& y : b)
      if (x.lo <= y.hi && y.lo <= x.hi) return true;
  return false;
}

}  // namespace

std::vector<MuxRange> mux_merge(std::vector<MuxRange> r) {
  std::sort(r.begin(), r.end(), [](const MuxRange& a, const MuxRange& b) { return a.lo < b.lo; });
  std::vector<MuxRange> out;
  for (const MuxRange& x : r) {
    if (!out.empty() && x.lo <= out.back().hi + 1) {
      out.back().hi = std::max(out.back().hi, x.hi);
    } else {
      out.push_back(x);
    }
  }
  return out;
}

void parse_mux_fields(const cJSON* sig, const std::string& path, MuxSpec& out, std::vector<std::string>& errors) {
  out = MuxSpec{};
  const cJSON* m = cJSON_GetObjectItemCaseSensitive(sig, "multiplexer");
  if (m) {
    if (!cJSON_IsBool(m)) {
      errors.push_back(path + ".multiplexer: must be true or false");
      out.bad = true;
    }
    else
      out.is_switch = cJSON_IsTrue(m);
  }
  const cJSON* mux = cJSON_GetObjectItemCaseSensitive(sig, "mux");
  if (!mux) return;
  std::string mp = path + ".mux";
  if (!cJSON_IsObject(mux)) {
    errors.push_back(mp + ": must be an object with values (and on)");
    out.bad = true;
    return;
  }
  bool ok = true;
  for (const cJSON* it = mux->child; it; it = it->next)
    if (it->string && std::string(it->string) != "on" && std::string(it->string) != "values") {
      errors.push_back(mp + "." + it->string + ": unknown field '" + it->string + "'");
      ok = false;
    }
  const cJSON* on = cJSON_GetObjectItemCaseSensitive(mux, "on");
  if (on) {
    if (!cJSON_IsString(on) || !*on->valuestring) {
      errors.push_back(mp + ".on: must be a switch name");
      ok = false;
    } else {
      out.on = on->valuestring;
    }
  }
  const cJSON* values = cJSON_GetObjectItemCaseSensitive(mux, "values");
  if (!cJSON_IsArray(values) || !values->child) {
    errors.push_back(mp + ".values: must be a list of switch values or [low, high] ranges");
    ok = false;
  } else {
    int k = 0;
    for (const cJSON* v = values->child; v; v = v->next, ++k) {
      std::string vp = mp + ".values[" + std::to_string(k) + "]";
      MuxRange r;
      if (whole(v, r.lo)) {
        r.hi = r.lo;
      } else if (cJSON_IsArray(v) && cJSON_GetArraySize(v) == 2 && whole(v->child, r.lo) &&
                 whole(v->child->next, r.hi)) {
        if (r.lo > r.hi) {
          errors.push_back(vp + ": low " + std::to_string(r.lo) + " is above high " + std::to_string(r.hi));
          ok = false;
          continue;
        }
      } else {
        errors.push_back(vp + ": must be a whole number 0..4294967295 or [low, high]");
        ok = false;
        continue;
      }
      out.values.push_back(r);
    }
  }
  out.has_mux = ok;
  if (!ok) {
    out.values.clear();
    out.bad = true;
  }
}

bool parse_mux_pages(const std::string& text, MuxPages& out) {
  if (text == "program") out = MuxPages::Program;
  else if (text == "all") out = MuxPages::All;
  else if (text == "rotate") out = MuxPages::Rotate;
  else return false;
  return true;
}

const char* mux_pages_name(MuxPages p) {
  switch (p) {
    case MuxPages::All: return "all";
    case MuxPages::Rotate: return "rotate";
    default: return "program";
  }
}

bool MuxLayout::build(const std::vector<MuxSignalDef>& sigs, std::vector<std::string>& errors,
                      std::vector<std::string>& warnings) {
  size_t n = sigs.size();
  size_t before = errors.size();
  has_switch_ = false;
  parent_.assign(n, -1);
  is_switch_.assign(n, 0);
  ranges_.assign(n, {});
  order_.clear();
  start_.assign(n, 0);
  length_.assign(n, 0);
  big_.assign(n, 0);
  scratch_.assign(n, 0);
  std::vector<size_t> switches;
  bool bad = false;
  for (size_t i = 0; i < n; ++i) {
    const MuxSignalDef& s = sigs[i];
    bad = bad || s.mux.bad;
    start_[i] = s.start_bit;
    length_[i] = s.length;
    big_[i] = s.big_endian ? 1 : 0;
    if (!s.mux.is_switch) continue;
    switches.push_back(i);
    if (s.is_signed) errors.push_back(s.path + ": switch " + label(s) + " must be unsigned");
    if (s.length > 32)
      errors.push_back(s.path + ": switch " + label(s) + " has " + std::to_string(s.length) +
                       " bits; a switch has at most 32");
    if (!s.name.empty())
      for (size_t j : switches)
        if (j < i && sigs[j].name == s.name) {
          errors.push_back(s.path + ": another switch is also named '" + s.name + "'");
          break;
        }
  }
  std::string names;
  for (size_t j : switches) names += (names.empty() ? "" : ", ") + label(sigs[j]);
  for (size_t i = 0; i < n; ++i) {
    const MuxSignalDef& s = sigs[i];
    if (!s.mux.has_mux) continue;
    std::string mp = s.path + ".mux";
    int p = -1;
    if (switches.empty()) {
      errors.push_back(mp + ": the message has no switch (multiplexer: true)");
      continue;
    }
    if (s.mux.on.empty()) {
      if (switches.size() > 1) {
        errors.push_back(mp + ".on: missing; the message has several switches (" + names + ")");
        continue;
      }
      p = static_cast<int>(switches[0]);
    } else {
      for (size_t j : switches)
        if (sigs[j].name == s.mux.on) {
          p = static_cast<int>(j);
          break;
        }
      if (p < 0) {
        errors.push_back(mp + ".on: no switch named '" + s.mux.on + "' in this message");
        continue;
      }
    }
    if (static_cast<size_t>(p) == i) {
      errors.push_back(mp + ".on: a switch cannot depend on itself");
      continue;
    }
    uint64_t top = sigs[p].length >= 32 ? 0xFFFFFFFFull : (uint64_t{1} << sigs[p].length) - 1;
    bool ok = true;
    for (size_t k = 0; k < s.mux.values.size(); ++k) {
      const MuxRange& r = s.mux.values[k];
      if (r.hi > top) {
        uint64_t wrong = r.lo > top ? r.lo : r.hi;
        errors.push_back(mp + ".values[" + std::to_string(k) + "]: " + std::to_string(wrong) + " is outside switch " +
                         label(sigs[p]) + " (0.." + std::to_string(top) + ")");
        ok = false;
      }
    }
    if (!ok) continue;
    parent_[i] = p;
    ranges_[i] = mux_merge(s.mux.values);
  }
  // Cycles among switches.
  std::vector<uint8_t> reported(n, 0);
  for (size_t i : switches) {
    if (reported[i]) continue;
    std::vector<size_t> chain{i};
    int x = parent_[i];
    while (x >= 0 && std::find(chain.begin(), chain.end(), static_cast<size_t>(x)) == chain.end()) {
      chain.push_back(static_cast<size_t>(x));
      x = parent_[x];
    }
    if (x < 0) continue;
    // x closes a cycle; report it from x.
    std::string text = label(sigs[x]);
    size_t y = static_cast<size_t>(x);
    do {
      reported[y] = 1;
      y = static_cast<size_t>(parent_[y]);
      text += " -> " + label(sigs[y]);
    } while (y != static_cast<size_t>(x));
    errors.push_back(sigs[x].path + ": switch cycle " + text);
  }
  if (errors.size() != before || bad) {
    parent_.assign(n, -1);
    ranges_.assign(n, {});
    order_.clear();
    for (size_t i = 0; i < n; ++i) order_.push_back(i);
    return false;
  }
  for (size_t i : switches) {
    is_switch_[i] = 1;
    bool used = false;
    for (size_t j = 0; j < n && !used; ++j) used = parent_[j] == static_cast<int>(i);
    if (!used) warnings.push_back(sigs[i].path + ": switch " + label(sigs[i]) + " has no signal that depends on it");
  }
  has_switch_ = !switches.empty();
  // Parents before dependents: by depth.
  std::vector<unsigned> depth(n, 0);
  for (size_t i = 0; i < n; ++i)
    for (int x = parent_[i]; x >= 0; x = parent_[x]) ++depth[i];
  for (size_t i = 0; i < n; ++i) order_.push_back(i);
  std::stable_sort(order_.begin(), order_.end(), [&](size_t a, size_t b) { return depth[a] < depth[b]; });
  return true;
}

bool MuxLayout::in_values(size_t i, uint64_t v) const {
  for (const MuxRange& r : ranges_[i])
    if (v >= r.lo && v <= r.hi) return true;
  return false;
}

bool MuxLayout::can_share(size_t a, size_t b) const {
  for (size_t x = a; parent_[x] >= 0; x = static_cast<size_t>(parent_[x]))
    for (size_t y = b; parent_[y] >= 0; y = static_cast<size_t>(parent_[y]))
      if (parent_[x] == parent_[y] && !intersects(ranges_[x], ranges_[y])) return false;
  return true;
}

MuxLayout::Eval MuxLayout::evaluate(const uint8_t* data, unsigned bytes, uint8_t* active) const {
  Eval e;
  for (size_t i : order_) {
    int p = parent_[i];
    bool a = p < 0 || (active[p] && in_values(i, scratch_[p]));
    active[i] = a ? 1 : 0;
    if (a && is_switch_[i]) {
      if (!signal_fits(start_[i], length_[i], big_[i] != 0, bytes)) {
        e.short_frame = true;
        e.need = signal_last_byte(start_[i], length_[i], big_[i] != 0) + 1;
        return e;
      }
      scratch_[i] = unpack_signal(data, bytes, start_[i], length_[i], big_[i] != 0);
    }
  }
  e.unknown = activity(scratch_.data(), active);
  for (size_t i = 0; i < parent_.size(); ++i)
    if (active[i]) e.need = std::max(e.need, signal_last_byte(start_[i], length_[i], big_[i] != 0) + 1);
  return e;
}

bool MuxLayout::activity(const uint64_t* values, uint8_t* active) const {
  for (size_t i : order_) {
    int p = parent_[i];
    active[i] = (p < 0 || (active[p] && in_values(i, values[p]))) ? 1 : 0;
  }
  // An active switch with dependents of which none is active.
  for (size_t s = 0; s < parent_.size(); ++s) {
    if (!is_switch_[s] || !active[s]) continue;
    bool has = false, hit = false;
    for (size_t j = 0; j < parent_.size() && !hit; ++j)
      if (parent_[j] == static_cast<int>(s)) {
        has = true;
        hit = active[j] != 0;
      }
    if (has && !hit) return true;
  }
  return false;
}

std::vector<MuxRange> MuxLayout::candidates(size_t s) const {
  std::vector<MuxRange> all;
  for (size_t j = 0; j < parent_.size(); ++j)
    if (parent_[j] == static_cast<int>(s)) all.insert(all.end(), ranges_[j].begin(), ranges_[j].end());
  return mux_merge(all);
}

uint64_t MuxLayout::count_switch(size_t s) const {
  std::vector<MuxRange> cand = candidates(s);
  if (cand.empty()) return 1;
  std::vector<size_t> children;
  for (size_t j = 0; j < parent_.size(); ++j)
    if (parent_[j] == static_cast<int>(s) && is_switch_[j]) children.push_back(j);
  std::vector<uint64_t> points;
  for (const MuxRange& r : cand) {
    points.push_back(r.lo);
    points.push_back(r.hi + 1);
  }
  for (size_t c : children)
    for (const MuxRange& r : ranges_[c]) {
      points.push_back(r.lo);
      points.push_back(r.hi + 1);
    }
  std::sort(points.begin(), points.end());
  points.erase(std::unique(points.begin(), points.end()), points.end());
  uint64_t total = 0;
  for (size_t k = 0; k + 1 < points.size(); ++k) {
    uint64_t a = points[k];
    bool in = false;
    for (const MuxRange& r : cand) in = in || (a >= r.lo && a <= r.hi);
    if (!in) continue;
    uint64_t mult = 1;
    for (size_t c : children)
      if (in_values(c, a)) mult = sat_mul(mult, count_switch(c));
    total = sat_add(total, sat_mul(points[k + 1] - a, mult));
  }
  return total;
}

uint64_t MuxLayout::page_count() const {
  if (!has_switch_) return 1;
  uint64_t n = 1;
  for (size_t s = 0; s < parent_.size(); ++s)
    if (is_switch_[s] && parent_[s] < 0) n = sat_mul(n, count_switch(s));
  return n;
}

void MuxLayout::enumerate(std::vector<size_t> pending, std::vector<uint64_t>& values, std::vector<Page>& out) const {
  if (pending.empty()) {
    Page p;
    p.values = values;
    p.active.assign(parent_.size(), 0);
    activity(values.data(), p.active.data());
    out.push_back(p);
    return;
  }
  size_t s = pending.front();
  std::vector<size_t> rest(pending.begin() + 1, pending.end());
  std::vector<MuxRange> cand = candidates(s);
  if (cand.empty()) {
    values[s] = 0;
    enumerate(rest, values, out);
    return;
  }
  for (const MuxRange& r : cand)
    for (uint64_t v = r.lo; v <= r.hi; ++v) {
      values[s] = v;
      std::vector<size_t> next = rest;
      for (size_t c = 0; c < parent_.size(); ++c)
        if (is_switch_[c] && parent_[c] == static_cast<int>(s) && in_values(c, v)) next.push_back(c);
      enumerate(next, values, out);
      for (size_t c = 0; c < parent_.size(); ++c)
        if (is_switch_[c] && parent_[c] == static_cast<int>(s)) values[c] = 0;
    }
  values[s] = 0;
}

std::vector<MuxLayout::Page> MuxLayout::pages() const {
  std::vector<Page> out;
  std::vector<uint64_t> values(parent_.size(), 0);
  std::vector<size_t> top;
  for (size_t s = 0; s < parent_.size(); ++s)
    if (is_switch_[s] && parent_[s] < 0) top.push_back(s);
  enumerate(top, values, out);
  return out;
}

}  // namespace canworks_can
