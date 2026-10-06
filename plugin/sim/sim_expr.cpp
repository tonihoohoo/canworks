#include "sim_expr.h"

#include <functional>

#include <cctype>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <limits>
#include <map>

namespace canopen_sim {

namespace {

constexpr double kMaxDelay = 600.0;

enum class Tok { Num, Name, Ref, Op, LParen, RParen, Comma, End };

struct Token {
  Tok kind = Tok::End;
  size_t pos = 0;
  std::string text;  // Name, Op, Ref (inside the brackets)
  double num = 0;
};

struct Fail {
  ExprError err;
};

[[noreturn]] void fail(size_t pos, const std::string& msg) { throw Fail{ExprError{pos, msg}}; }

std::vector<Token> tokenize(const std::string& s) {
  std::vector<Token> out;
  size_t i = 0;
  const size_t n = s.size();
  static const char* const kOps[] = {"**", "<<", ">>", "<=", ">=", "==", "!=", "&&", "||", "+", "-", "*",
                                     "/",  "%",  "<",  ">",  "!",  "~",  "&",  "|",  "^"};
  while (i < n) {
    char c = s[i];
    if (std::isspace(static_cast<unsigned char>(c))) {
      ++i;
      continue;
    }
    Token t;
    t.pos = i;
    if (std::isdigit(static_cast<unsigned char>(c)) || (c == '.' && i + 1 < n && std::isdigit(static_cast<unsigned char>(s[i + 1])))) {
      if (c == '0' && i + 1 < n && (s[i + 1] == 'x' || s[i + 1] == 'X')) {
        size_t j = i + 2;
        while (j < n && std::isxdigit(static_cast<unsigned char>(s[j]))) ++j;
        if (j == i + 2) fail(i, "malformed number '" + s.substr(i, j - i) + "'");
        t.num = static_cast<double>(std::strtoull(s.substr(i + 2, j - i - 2).c_str(), nullptr, 16));
        i = j;
      } else {
        const char* start = s.c_str() + i;
        char* end = nullptr;
        t.num = std::strtod(start, &end);
        i += static_cast<size_t>(end - start);
      }
      if (i < n && (std::isalpha(static_cast<unsigned char>(s[i])) || s[i] == '_'))
        fail(t.pos, "malformed number '" + s.substr(t.pos, i + 1 - t.pos) + "'");
      t.kind = Tok::Num;
    } else if (std::isalpha(static_cast<unsigned char>(c)) || c == '_') {
      size_t j = i;
      while (j < n && (std::isalnum(static_cast<unsigned char>(s[j])) || s[j] == '_')) ++j;
      t.kind = Tok::Name;
      t.text = s.substr(i, j - i);
      i = j;
    } else if (c == '[') {
      size_t j = s.find(']', i);
      if (j == std::string::npos) fail(i, "missing ] after the object reference");
      t.kind = Tok::Ref;
      t.text = s.substr(i + 1, j - i - 1);
      i = j + 1;
    } else if (c == '(') {
      t.kind = Tok::LParen;
      ++i;
    } else if (c == ')') {
      t.kind = Tok::RParen;
      t.text = ")";
      ++i;
    } else if (c == ',') {
      t.kind = Tok::Comma;
      t.text = ",";
      ++i;
    } else {
      bool found = false;
      for (const char* op : kOps) {
        size_t len = std::strlen(op);
        if (s.compare(i, len, op) == 0) {
          t.kind = Tok::Op;
          t.text = op;
          i += len;
          found = true;
          break;
        }
      }
      if (!found) fail(i, std::string("unexpected character '") + c + "'");
    }
    out.push_back(t);
  }
  Token end;
  end.kind = Tok::End;
  end.pos = n;
  out.push_back(end);
  return out;
}

std::string trim(const std::string& s) {
  size_t a = 0, b = s.size();
  while (a < b && std::isspace(static_cast<unsigned char>(s[a]))) ++a;
  while (b > a && std::isspace(static_cast<unsigned char>(s[b - 1]))) --b;
  return s.substr(a, b - a);
}

}  // namespace

bool parse_object_key(const std::string& text, uint16_t& index, uint8_t& subindex) {
  std::string t = trim(text);
  if (t.size() < 3 || t[0] != '0' || (t[1] != 'x' && t[1] != 'X')) return false;
  size_t colon = t.find(':');
  std::string idx = t.substr(2, colon == std::string::npos ? std::string::npos : colon - 2);
  if (idx.empty() || idx.size() > 4) return false;
  for (char c : idx)
    if (!std::isxdigit(static_cast<unsigned char>(c))) return false;
  index = static_cast<uint16_t>(std::strtoul(idx.c_str(), nullptr, 16));
  subindex = 0;
  if (colon == std::string::npos) return true;
  std::string sub = t.substr(colon + 1);
  if (sub.empty()) return false;
  unsigned long v = 0;
  if (sub.size() > 2 && sub[0] == '0' && (sub[1] == 'x' || sub[1] == 'X')) {
    std::string h = sub.substr(2);
    if (h.empty() || h.size() > 2) return false;
    for (char c : h)
      if (!std::isxdigit(static_cast<unsigned char>(c))) return false;
    v = std::strtoul(h.c_str(), nullptr, 16);
  } else {
    if (sub.size() > 3) return false;
    for (char c : sub)
      if (!std::isdigit(static_cast<unsigned char>(c))) return false;
    v = std::strtoul(sub.c_str(), nullptr, 10);
  }
  if (v > 255) return false;
  subindex = static_cast<uint8_t>(v);
  return true;
}

std::string object_key(uint16_t index, uint8_t subindex) {
  char buf[16];
  std::snprintf(buf, sizeof buf, "0x%04X:%u", index, subindex);
  return buf;
}

// ---------------------------------------------------------------------------
// Tree

enum class Fn {
  Abs, Floor, Ceil, Round, Sqrt, Exp, Log, Sin, Cos, Min, Max, Clamp, If, Bit, SetBit, Noise,
  Lag, Delay, RateLimit, Integrate, Hold, Edge
};

class ExprNode {
 public:
  enum class Kind { Num, T, Dt, Prev, Ref, Unary, Binary, Call };
  Kind kind = Kind::Num;
  double num = 0;
  ObjectRef ref;
  std::string op;
  Fn fn = Fn::Abs;
  std::vector<std::unique_ptr<ExprNode>> args;
  // State of stateful functions.
  bool started = false;
  double state = 0;
  double last_cond = 0;
  std::deque<std::pair<double, double>> history;  // delay: (t, x)

  void reset() {
    started = false;
    state = 0;
    last_cond = 0;
    history.clear();
    for (auto& a : args) a->reset();
  }
};

namespace {

int64_t as_int(double v) {
  if (!std::isfinite(v)) return 0;
  if (v >= 9.2e18) return std::numeric_limits<int64_t>::max();
  if (v <= -9.2e18) return std::numeric_limits<int64_t>::min();
  return static_cast<int64_t>(v);
}

struct FnInfo {
  const char* name;
  Fn fn;
  int min_args;
  int max_args;  // -1: any
};

const FnInfo kFns[] = {
    {"abs", Fn::Abs, 1, 1},       {"floor", Fn::Floor, 1, 1},          {"ceil", Fn::Ceil, 1, 1},
    {"round", Fn::Round, 1, 1},   {"sqrt", Fn::Sqrt, 1, 1},            {"exp", Fn::Exp, 1, 1},
    {"log", Fn::Log, 1, 1},       {"sin", Fn::Sin, 1, 1},              {"cos", Fn::Cos, 1, 1},
    {"min", Fn::Min, 1, -1},      {"max", Fn::Max, 1, -1},             {"clamp", Fn::Clamp, 3, 3},
    {"if", Fn::If, 3, 3},         {"bit", Fn::Bit, 2, 2},              {"setbit", Fn::SetBit, 3, 3},
    {"noise", Fn::Noise, 1, 1},   {"lag", Fn::Lag, 2, 2},              {"delay", Fn::Delay, 2, 2},
    {"rate_limit", Fn::RateLimit, 2, 2}, {"integrate", Fn::Integrate, 1, 1}, {"hold", Fn::Hold, 2, 2},
    {"edge", Fn::Edge, 1, 1},
};

const FnInfo* find_fn(const std::string& name) {
  for (const auto& f : kFns)
    if (name == f.name) return &f;
  return nullptr;
}

class Parser {
 public:
  Parser(const std::vector<Token>& toks, const ExprResolver& res, std::vector<Expr::Read>& reads)
      : t_(toks), res_(res), reads_(reads) {}

  std::unique_ptr<ExprNode> parse() {
    auto e = binary(0);
    const Token& k = peek();
    if (k.kind != Tok::End) fail(k.pos, "unexpected '" + describe(k) + "'");
    return e;
  }

 private:
  const Token& peek() const { return t_[i_]; }
  const Token& next() { return t_[i_++]; }

  static std::string describe(const Token& k) {
    switch (k.kind) {
      case Tok::Num: {
        char b[32];
        std::snprintf(b, sizeof b, "%g", k.num);
        return b;
      }
      case Tok::Ref: return "[" + k.text + "]";
      case Tok::LParen: return "(";
      case Tok::End: return "end";
      default: return k.text;
    }
  }

  // Binary operator levels, lowest first.
  static int level(const std::string& op) {
    static const std::map<std::string, int> lv = {
        {"||", 0}, {"&&", 1}, {"|", 2},  {"^", 3},  {"&", 4},  {"==", 5}, {"!=", 5}, {"<", 6},
        {"<=", 6}, {">", 6},  {">=", 6}, {"<<", 7}, {">>", 7}, {"+", 8},  {"-", 8},  {"*", 9},
        {"/", 9},  {"%", 9}};
    auto it = lv.find(op);
    return it == lv.end() ? -1 : it->second;
  }

  std::unique_ptr<ExprNode> binary(int min_level) {
    auto left = power();
    while (true) {
      const Token& k = peek();
      if (k.kind != Tok::Op) break;
      int lv = level(k.text);
      if (lv < 0 || lv < min_level) break;
      std::string op = next().text;
      auto right = binary(lv + 1);
      auto n = std::unique_ptr<ExprNode>(new ExprNode);
      n->kind = ExprNode::Kind::Binary;
      n->op = op;
      n->args.push_back(std::move(left));
      n->args.push_back(std::move(right));
      left = std::move(n);
    }
    return left;
  }

  std::unique_ptr<ExprNode> power() {
    auto base = unary();
    if (peek().kind == Tok::Op && peek().text == "**") {
      next();
      auto exp = power();
      auto n = std::unique_ptr<ExprNode>(new ExprNode);
      n->kind = ExprNode::Kind::Binary;
      n->op = "**";
      n->args.push_back(std::move(base));
      n->args.push_back(std::move(exp));
      return n;
    }
    return base;
  }

  std::unique_ptr<ExprNode> unary() {
    const Token& k = peek();
    if (k.kind == Tok::Op && (k.text == "-" || k.text == "!" || k.text == "~" || k.text == "+")) {
      std::string op = next().text;
      auto a = unary();
      if (op == "+") return a;
      auto n = std::unique_ptr<ExprNode>(new ExprNode);
      n->kind = ExprNode::Kind::Unary;
      n->op = op;
      n->args.push_back(std::move(a));
      return n;
    }
    return primary();
  }

  std::unique_ptr<ExprNode> primary() {
    const Token& k = next();
    auto n = std::unique_ptr<ExprNode>(new ExprNode);
    switch (k.kind) {
      case Tok::Num:
        n->kind = ExprNode::Kind::Num;
        n->num = k.num;
        return n;
      case Tok::Ref: return reference(k);
      case Tok::LParen: {
        auto e = binary(0);
        const Token& c = peek();
        if (c.kind != Tok::RParen) fail(c.pos, c.kind == Tok::End ? "missing )" : "missing ) before '" + describe(c) + "'");
        next();
        return e;
      }
      case Tok::Name: {
        if (peek().kind == Tok::LParen) return call(k);
        if (k.text == "t") {
          n->kind = ExprNode::Kind::T;
        } else if (k.text == "dt") {
          n->kind = ExprNode::Kind::Dt;
        } else if (k.text == "prev") {
          n->kind = ExprNode::Kind::Prev;
        } else if (k.text == "pi") {
          n->num = 3.14159265358979323846;
        } else if (k.text == "true") {
          n->num = 1;
        } else if (k.text == "false") {
          n->num = 0;
        } else {
          fail(k.pos, find_fn(k.text) ? k.text + " is a function: write " + k.text + "(...)" : "unknown name " + k.text);
        }
        return n;
      }
      case Tok::End: fail(k.pos, "unexpected end of expression");
      default: fail(k.pos, "unexpected '" + describe(k) + "'");
    }
  }

  std::unique_ptr<ExprNode> reference(const Token& k) {
    std::string body = trim(k.text);
    std::string dev, obj = body;
    size_t slash = body.find('/');
    if (slash != std::string::npos) {
      dev = trim(body.substr(0, slash));
      obj = trim(body.substr(slash + 1));
    }
    uint16_t idx = 0;
    uint8_t sub = 0;
    if (!parse_object_key(obj, idx, sub)) fail(k.pos, "malformed object '" + obj + "' (want [0xIIII:S] or [NODE/0xIIII:S])");
    int d = res_.self();
    if (!dev.empty()) {
      d = res_.device(dev);
      if (d < 0) fail(k.pos, "unknown device " + dev + " (not a simulated device)");
    }
    if (!res_.has_object(d, idx, sub))
      fail(k.pos, "object " + object_key(idx, sub) + (dev.empty() ? "" : " of device " + dev) + " does not exist");
    auto n = std::unique_ptr<ExprNode>(new ExprNode);
    n->kind = ExprNode::Kind::Ref;
    n->ref.device = d;
    n->ref.index = idx;
    n->ref.subindex = sub;
    reads_.push_back(Expr::Read{n->ref, delayed_ > 0});
    return n;
  }

  std::unique_ptr<ExprNode> call(const Token& name) {
    const FnInfo* f = find_fn(name.text);
    if (!f) fail(name.pos, "unknown function " + name.text);
    next();  // (
    auto n = std::unique_ptr<ExprNode>(new ExprNode);
    n->kind = ExprNode::Kind::Call;
    n->fn = f->fn;
    bool delays = f->fn == Fn::Lag || f->fn == Fn::Delay || f->fn == Fn::Integrate;
    if (peek().kind != Tok::RParen) {
      while (true) {
        bool first = n->args.empty();
        if (delays && first) ++delayed_;
        n->args.push_back(binary(0));
        if (delays && first) --delayed_;
        const Token& k = peek();
        if (k.kind == Tok::Comma) {
          next();
          continue;
        }
        if (k.kind == Tok::RParen) break;
        fail(k.pos, k.kind == Tok::End ? "missing )" : "expected , or ) but found '" + describe(k) + "'");
      }
    }
    next();  // )
    int got = static_cast<int>(n->args.size());
    if (got < f->min_args || (f->max_args >= 0 && got > f->max_args)) {
      char b[96];
      if (f->max_args < 0)
        std::snprintf(b, sizeof b, "%s takes at least %d argument%s, not %d", f->name, f->min_args, f->min_args == 1 ? "" : "s", got);
      else
        std::snprintf(b, sizeof b, "%s takes %d argument%s, not %d", f->name, f->min_args, f->min_args == 1 ? "" : "s", got);
      fail(name.pos, b);
    }
    if (f->fn == Fn::Delay && n->args[1]->kind == ExprNode::Kind::Num && n->args[1]->num > kMaxDelay)
      fail(name.pos, "delay is at most 600 s");
    return n;
  }

  const std::vector<Token>& t_;
  const ExprResolver& res_;
  std::vector<Expr::Read>& reads_;
  size_t i_ = 0;
  int delayed_ = 0;
};

double eval_node(ExprNode& n, ExprContext& c);

double call(ExprNode& n, ExprContext& c) {
  std::vector<double> a;
  a.reserve(n.args.size());
  for (auto& x : n.args) a.push_back(eval_node(*x, c));
  switch (n.fn) {
    case Fn::Abs: return std::fabs(a[0]);
    case Fn::Floor: return std::floor(a[0]);
    case Fn::Ceil: return std::ceil(a[0]);
    case Fn::Round: return std::round(a[0]);
    case Fn::Sqrt: return std::sqrt(a[0]);
    case Fn::Exp: return std::exp(a[0]);
    case Fn::Log: return std::log(a[0]);
    case Fn::Sin: return std::sin(a[0]);
    case Fn::Cos: return std::cos(a[0]);
    case Fn::Min: {
      double v = a[0];
      for (double x : a) v = x < v ? x : v;
      return v;
    }
    case Fn::Max: {
      double v = a[0];
      for (double x : a) v = x > v ? x : v;
      return v;
    }
    case Fn::Clamp: return a[0] < a[1] ? a[1] : (a[0] > a[2] ? a[2] : a[0]);
    case Fn::If: return a[0] != 0 ? a[1] : a[2];
    case Fn::Bit: {
      int64_t b = as_int(a[1]);
      if (b < 0 || b > 63) return 0;
      return static_cast<double>((static_cast<uint64_t>(as_int(a[0])) >> b) & 1u);
    }
    case Fn::SetBit: {
      int64_t b = as_int(a[1]);
      if (b < 0 || b > 63) return a[0];
      uint64_t v = static_cast<uint64_t>(as_int(a[0]));
      uint64_t m = uint64_t(1) << b;
      v = a[2] != 0 ? (v | m) : (v & ~m);
      return static_cast<double>(static_cast<int64_t>(v));
    }
    case Fn::Noise: {
      if (!c.rng || !(a[0] > 0)) return 0;
      std::uniform_real_distribution<double> d(-a[0], a[0]);
      return d(*c.rng);
    }
    case Fn::Lag: {
      if (!n.started || !std::isfinite(n.state)) {
        n.started = true;
        n.state = a[0];
      } else if (a[1] <= 0) {
        n.state = a[0];
      } else {
        n.state += (a[0] - n.state) * (1.0 - std::exp(-c.dt / a[1]));
      }
      return n.state;
    }
    case Fn::Delay: {
      double d = a[1] < 0 ? 0 : (a[1] > kMaxDelay ? kMaxDelay : a[1]);
      n.history.emplace_back(c.t, a[0]);
      double target = c.t - d;
      // Drop samples no longer needed: keep the newest one at or before target.
      while (n.history.size() >= 2 && n.history[1].first <= target) n.history.pop_front();
      return n.history.front().first <= target ? n.history.front().second : n.history.front().second;
    }
    case Fn::RateLimit: {
      if (!n.started) {
        n.started = true;
        n.state = a[0];
      } else {
        double step = std::fabs(a[1]) * c.dt;
        double diff = a[0] - n.state;
        n.state += diff > step ? step : (diff < -step ? -step : diff);
      }
      return n.state;
    }
    case Fn::Integrate: {
      if (!n.started) {
        n.started = true;
        n.state = 0;
      }
      n.state += a[0] * c.dt;
      return n.state;
    }
    case Fn::Hold: {
      if (!n.started) {
        n.started = true;
        n.state = a[0];
      } else if (a[1] != 0 && n.last_cond == 0) {
        n.state = a[0];
      }
      n.last_cond = a[1];
      return n.state;
    }
    case Fn::Edge: {
      double r = (a[0] != 0 && n.last_cond == 0) ? 1 : 0;
      n.last_cond = a[0];
      return r;
    }
  }
  return 0;
}

double eval_node(ExprNode& n, ExprContext& c) {
  switch (n.kind) {
    case ExprNode::Kind::Num: return n.num;
    case ExprNode::Kind::T: return c.t;
    case ExprNode::Kind::Dt: return c.dt;
    case ExprNode::Kind::Prev: return c.prev;
    case ExprNode::Kind::Ref: return c.value(n.ref);
    case ExprNode::Kind::Unary: {
      double v = eval_node(*n.args[0], c);
      if (n.op == "-") return -v;
      if (n.op == "!") return v == 0 ? 1 : 0;
      return static_cast<double>(~as_int(v));
    }
    case ExprNode::Kind::Binary: {
      double x = eval_node(*n.args[0], c);
      double y = eval_node(*n.args[1], c);
      const std::string& o = n.op;
      if (o == "+") return x + y;
      if (o == "-") return x - y;
      if (o == "*") return x * y;
      if (o == "/") return y == 0 ? std::numeric_limits<double>::quiet_NaN() : x / y;
      if (o == "%") return y == 0 ? std::numeric_limits<double>::quiet_NaN() : std::fmod(x, y);
      if (o == "**") return std::pow(x, y);
      if (o == "==") return x == y ? 1 : 0;
      if (o == "!=") return x != y ? 1 : 0;
      if (o == "<") return x < y ? 1 : 0;
      if (o == "<=") return x <= y ? 1 : 0;
      if (o == ">") return x > y ? 1 : 0;
      if (o == ">=") return x >= y ? 1 : 0;
      if (o == "&&") return (x != 0 && y != 0) ? 1 : 0;
      if (o == "||") return (x != 0 || y != 0) ? 1 : 0;
      int64_t a = as_int(x), b = as_int(y);
      if (o == "&") return static_cast<double>(a & b);
      if (o == "|") return static_cast<double>(a | b);
      if (o == "^") return static_cast<double>(a ^ b);
      if (o == "<<") return (b < 0 || b > 63) ? 0 : static_cast<double>(static_cast<int64_t>(static_cast<uint64_t>(a) << b));
      if (o == ">>") return (b < 0 || b > 63) ? 0 : static_cast<double>(a >> b);
      return 0;
    }
    case ExprNode::Kind::Call: return call(n, c);
  }
  return 0;
}

}  // namespace

Expr::Expr() = default;
Expr::~Expr() = default;
Expr::Expr(Expr&&) noexcept = default;
Expr& Expr::operator=(Expr&&) noexcept = default;

std::unique_ptr<Expr> Expr::compile(const std::string& text, const ExprResolver& resolver, ExprError& err) {
  std::unique_ptr<Expr> e(new Expr);
  e->text_ = text;
  try {
    if (trim(text).empty()) fail(0, "empty expression");
    std::vector<Token> toks = tokenize(text);
    Parser p(toks, resolver, e->reads_);
    e->root_ = p.parse();
    std::function<bool(const ExprNode&)> plain = [&](const ExprNode& n) {
      if (n.kind == ExprNode::Kind::Dt || n.kind == ExprNode::Kind::Prev) return false;
      if (n.kind == ExprNode::Kind::Call && n.fn >= Fn::Noise) return false;
      for (const auto& a : n.args)
        if (!plain(*a)) return false;
      return true;
    };
    e->stateless_ = plain(*e->root_);
  } catch (const Fail& f) {
    err = f.err;
    return nullptr;
  }
  return e;
}

double Expr::eval(ExprContext& ctx) { return eval_node(*root_, ctx); }

void Expr::reset() {
  if (root_) root_->reset();
}

}  // namespace canopen_sim
