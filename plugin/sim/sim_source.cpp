#include "sim_source.h"

#include <cmath>
#include <cstdlib>
#include <fstream>
#include <sstream>

#include "cJSON.h"

namespace canopen_sim {

namespace {

constexpr double kPi = 3.14159265358979323846;

bool num(const cJSON* o, const char* key, double& out, bool required, std::string& err) {
  const cJSON* v = cJSON_GetObjectItemCaseSensitive(o, key);
  if (!v) {
    if (required) err = std::string("missing \"") + key + "\"";
    return !required;
  }
  if (!cJSON_IsNumber(v)) {
    err = std::string("\"") + key + "\" must be a number";
    return false;
  }
  out = v->valuedouble;
  return true;
}

std::string join_path(const std::string& dir, const std::string& file) {
  if (file.empty() || file[0] == '/' || dir.empty()) return file;
  return dir + "/" + file;
}

bool load_csv(const std::string& path, unsigned column, double scale, std::vector<std::pair<double, double>>& out,
              std::string& err) {
  std::ifstream in(path);
  if (!in) {
    err = "cannot read " + path;
    return false;
  }
  std::string line;
  unsigned lineno = 0;
  while (std::getline(in, line)) {
    ++lineno;
    if (!line.empty() && line.back() == '\r') line.pop_back();
    if (line.empty()) continue;
    std::vector<std::string> cells;
    std::stringstream ss(line);
    std::string cell;
    char sep = line.find(';') != std::string::npos && line.find(',') == std::string::npos ? ';' : ',';
    while (std::getline(ss, cell, sep)) cells.push_back(cell);
    if (cells.size() <= column) {
      if (lineno == 1) continue;
      err = path + " line " + std::to_string(lineno) + " has no column " + std::to_string(column);
      return false;
    }
    char* e1 = nullptr;
    char* e2 = nullptr;
    double t = std::strtod(cells[0].c_str(), &e1);
    double v = std::strtod(cells[column].c_str(), &e2);
    if (e1 == cells[0].c_str() || e2 == cells[column].c_str()) {
      if (lineno == 1 && out.empty()) continue;  // header
      err = path + " line " + std::to_string(lineno) + " is not numeric";
      return false;
    }
    if (!out.empty() && t * scale < out.back().first) {
      err = path + " line " + std::to_string(lineno) + ": time goes backwards";
      return false;
    }
    out.emplace_back(t * scale, v);
  }
  if (out.empty()) {
    err = path + " has no data rows";
    return false;
  }
  return true;
}

double wave_phase(double t, double period, double phase_deg) {
  double p = t / period + phase_deg / 360.0;
  p -= std::floor(p);
  return p;
}

}  // namespace

Source::~Source() = default;

std::unique_ptr<Source> Source::parse(const cJSON* json, const std::string& base_dir, std::string& err) {
  if (!cJSON_IsObject(json)) {
    err = "a source must be an object such as {\"sine\": {...}}";
    return nullptr;
  }
  std::unique_ptr<Source> s(new Source);
  char* text = cJSON_PrintUnformatted(json);
  s->json_ = text ? text : "{}";
  cJSON_free(text);
  const cJSON* kind = nullptr;
  int kinds = 0;
  for (const cJSON* c = json->child; c; c = c->next) {
    std::string k = c->string ? c->string : "";
    if (k == "noise") {
      if (!cJSON_IsNumber(c) || c->valuedouble < 0) {
        err = "\"noise\" must be a number of 0 or more";
        return nullptr;
      }
      s->noise_ = c->valuedouble;
    } else if (k == "tick_ms") {
      if (!cJSON_IsNumber(c) || c->valuedouble < 1 || c->valuedouble > 60000) {
        err = "\"tick_ms\" must be 1-60000";
        return nullptr;
      }
      s->tick_ms_ = static_cast<unsigned>(c->valuedouble);
    } else {
      kind = c;
      ++kinds;
    }
  }
  if (kinds != 1) {
    err = kinds == 0 ? "the source has no type (constant, sine, triangle, sawtooth, square, ramp, steps, random_walk, counter, csv, expr)"
                     : "a source has exactly one type";
    return nullptr;
  }
  std::string k = kind->string;
  const cJSON* o = kind;
  auto need_obj = [&]() {
    if (!cJSON_IsObject(o)) {
      err = "\"" + k + "\" must be an object";
      return false;
    }
    return true;
  };
  if (k == "constant") {
    s->type_ = Type::Constant;
    if (cJSON_IsNumber(o)) s->constant_ = Value::number(o->valuedouble);
    else if (cJSON_IsBool(o)) s->constant_ = Value::number(cJSON_IsTrue(o) ? 1 : 0);
    else if (cJSON_IsString(o)) s->constant_ = Value::text(o->valuestring);
    else {
      err = "\"constant\" must be a number, a boolean or a string";
      return nullptr;
    }
  } else if (k == "sine" || k == "triangle" || k == "sawtooth" || k == "square") {
    s->type_ = k == "sine" ? Type::Sine : k == "triangle" ? Type::Triangle : k == "sawtooth" ? Type::Sawtooth : Type::Square;
    if (!need_obj() || !num(o, "min", s->min_, true, err) || !num(o, "max", s->max_, true, err) ||
        !num(o, "period_s", s->period_, true, err) || !num(o, "phase_deg", s->phase_, false, err) ||
        (s->type_ == Type::Square && !num(o, "duty", s->duty_, false, err)))
      return nullptr;
    if (!(s->period_ > 0)) {
      err = "\"period_s\" must be more than 0";
      return nullptr;
    }
    if (s->duty_ < 0 || s->duty_ > 1) {
      err = "\"duty\" must be 0-1";
      return nullptr;
    }
  } else if (k == "ramp") {
    s->type_ = Type::Ramp;
    if (!need_obj() || !num(o, "from", s->from_, true, err) || !num(o, "to", s->to_, true, err) ||
        !num(o, "duration_s", s->duration_, true, err))
      return nullptr;
    if (!(s->duration_ > 0)) {
      err = "\"duration_s\" must be more than 0";
      return nullptr;
    }
    const cJSON* then = cJSON_GetObjectItemCaseSensitive(o, "then");
    if (then) {
      if (!cJSON_IsString(then) || (std::string(then->valuestring) != "hold" && std::string(then->valuestring) != "repeat" &&
                                    std::string(then->valuestring) != "reverse")) {
        err = "\"then\" must be hold, repeat or reverse";
        return nullptr;
      }
      s->then_ = then->valuestring;
    }
  } else if (k == "steps") {
    s->type_ = Type::Steps;
    if (!need_obj()) return nullptr;
    const cJSON* vals = cJSON_GetObjectItemCaseSensitive(o, "values");
    if (!cJSON_IsArray(vals) || !vals->child) {
      err = "\"steps\" needs \"values\": a list of [value, duration_s]";
      return nullptr;
    }
    for (const cJSON* v = vals->child; v; v = v->next) {
      if (!cJSON_IsArray(v) || cJSON_GetArraySize(v) != 2 || !cJSON_IsNumber(cJSON_GetArrayItem(v, 0)) ||
          !cJSON_IsNumber(cJSON_GetArrayItem(v, 1)) || !(cJSON_GetArrayItem(v, 1)->valuedouble > 0)) {
        err = "each step is [value, duration_s] with a duration above 0";
        return nullptr;
      }
      s->steps_.emplace_back(cJSON_GetArrayItem(v, 0)->valuedouble, cJSON_GetArrayItem(v, 1)->valuedouble);
    }
    const cJSON* rep = cJSON_GetObjectItemCaseSensitive(o, "repeat");
    if (rep) s->repeat_ = cJSON_IsTrue(rep);
  } else if (k == "random_walk") {
    s->type_ = Type::RandomWalk;
    if (!need_obj() || !num(o, "min", s->min_, true, err) || !num(o, "max", s->max_, true, err) ||
        !num(o, "max_step", s->max_step_, true, err))
      return nullptr;
    s->has_start_ = cJSON_GetObjectItemCaseSensitive(o, "start") != nullptr;
    if (!num(o, "start", s->start_, false, err)) return nullptr;
    if (s->min_ > s->max_ || !(s->max_step_ > 0)) {
      err = "random_walk needs min <= max and max_step above 0";
      return nullptr;
    }
  } else if (k == "counter") {
    s->type_ = Type::Counter;
    if (!need_obj() || !num(o, "start", s->start_, false, err) || !num(o, "step", s->step_, false, err)) return nullptr;
    s->has_min_ = cJSON_GetObjectItemCaseSensitive(o, "min") != nullptr;
    s->has_max_ = cJSON_GetObjectItemCaseSensitive(o, "max") != nullptr;
    if (!num(o, "min", s->min_, false, err) || !num(o, "max", s->max_, false, err)) return nullptr;
  } else if (k == "csv") {
    s->type_ = Type::Csv;
    if (!need_obj()) return nullptr;
    const cJSON* f = cJSON_GetObjectItemCaseSensitive(o, "file");
    if (!cJSON_IsString(f) || !*f->valuestring) {
      err = "\"csv\" needs \"file\"";
      return nullptr;
    }
    double column = 1, scale = 1;
    if (!num(o, "column", column, false, err) || !num(o, "time_scale", scale, false, err)) return nullptr;
    if (column < 1 || !(scale > 0)) {
      err = "\"column\" must be 1 or more and \"time_scale\" above 0";
      return nullptr;
    }
    const cJSON* interp = cJSON_GetObjectItemCaseSensitive(o, "interpolate");
    if (interp) {
      if (!cJSON_IsString(interp) || (std::string(interp->valuestring) != "linear" && std::string(interp->valuestring) != "step")) {
        err = "\"interpolate\" must be linear or step";
        return nullptr;
      }
      s->linear_ = std::string(interp->valuestring) == "linear";
    }
    s->loop_ = cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(o, "loop"));
    if (!load_csv(join_path(base_dir, f->valuestring), static_cast<unsigned>(column), scale, s->csv_, err)) return nullptr;
  } else if (k == "expr") {
    s->type_ = Type::Expr;
    if (!cJSON_IsString(o) || !*o->valuestring) {
      err = "\"expr\" must be the expression text";
      return nullptr;
    }
    s->expr_text_ = o->valuestring;
  } else {
    err = "unknown source type \"" + k + "\"";
    return nullptr;
  }
  return s;
}

bool Source::bind(const ExprResolver& res, ExprError& err) {
  if (type_ != Type::Expr) return true;
  expr_ = Expr::compile(expr_text_, res, err);
  return expr_ != nullptr;
}

void Source::restart() {
  started_ = false;
  state_ = 0;
  if (expr_) expr_->reset();
}

Value Source::eval(double t, ExprContext& ctx) {
  double v = 0;
  switch (type_) {
    case Type::Constant:
      if (constant_.is_string) return constant_;
      v = constant_.num;
      break;
    case Type::Sine: {
      double p = wave_phase(t, period_, phase_);
      v = (min_ + max_) / 2 + (max_ - min_) / 2 * std::sin(2 * kPi * p);
      break;
    }
    case Type::Triangle: {
      double p = wave_phase(t, period_, phase_);
      v = p < 0.5 ? min_ + (max_ - min_) * 2 * p : max_ - (max_ - min_) * (2 * p - 1);
      break;
    }
    case Type::Sawtooth: v = min_ + (max_ - min_) * wave_phase(t, period_, phase_); break;
    case Type::Square: v = wave_phase(t, period_, phase_) < duty_ ? max_ : min_; break;
    case Type::Ramp: {
      double p = t / duration_;
      if (p >= 1) {
        if (then_ == "hold") p = 1;
        else if (then_ == "repeat") p -= std::floor(p);
        else {
          double q = std::fmod(p, 2.0);
          p = q <= 1 ? q : 2 - q;
        }
      }
      v = from_ + (to_ - from_) * p;
      break;
    }
    case Type::Steps: {
      double total = 0;
      for (auto& st : steps_) total += st.second;
      double tt = t;
      if (tt >= total) {
        if (!repeat_) {
          v = steps_.back().first;
          break;
        }
        tt = std::fmod(tt, total);
      }
      v = steps_.back().first;
      for (auto& st : steps_) {
        if (tt < st.second) {
          v = st.first;
          break;
        }
        tt -= st.second;
      }
      break;
    }
    case Type::RandomWalk: {
      if (!started_) {
        started_ = true;
        state_ = has_start_ ? start_ : (min_ + max_) / 2;
      } else if (ctx.rng) {
        std::uniform_real_distribution<double> d(-max_step_, max_step_);
        state_ += d(*ctx.rng);
      }
      state_ = state_ < min_ ? min_ : (state_ > max_ ? max_ : state_);
      v = state_;
      break;
    }
    case Type::Counter: {
      if (!started_) {
        started_ = true;
        state_ = start_;
      } else {
        state_ += step_;
        if (has_max_ && state_ > max_) state_ = has_min_ ? min_ : start_;
        if (has_min_ && state_ < min_) state_ = has_max_ ? max_ : start_;
      }
      v = state_;
      break;
    }
    case Type::Csv: {
      double tt = t;
      double end = csv_.back().first;
      if (loop_ && end > 0) tt = std::fmod(tt, end);
      if (tt <= csv_.front().first) {
        v = csv_.front().second;
      } else if (tt >= end) {
        v = csv_.back().second;
      } else {
        size_t i = 1;
        while (i < csv_.size() && csv_[i].first < tt) ++i;
        const auto& a = csv_[i - 1];
        const auto& b = csv_[i];
        if (!linear_ || b.first == a.first) v = tt >= b.first ? b.second : a.second;
        else v = a.second + (b.second - a.second) * (tt - a.first) / (b.first - a.first);
      }
      break;
    }
    case Type::Expr: v = expr_ ? expr_->eval(ctx) : 0; break;
  }
  if (noise_ > 0 && ctx.rng) {
    std::uniform_real_distribution<double> d(-noise_, noise_);
    v += d(*ctx.rng);
  }
  return Value::number(v);
}

}  // namespace canopen_sim
