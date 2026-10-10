// Unit tests of the simulator engine's parts that need no bus: expressions,
// value sources, the simulation file loader and scenarios on a fake clock.

#include <cmath>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <map>
#include <sstream>
#include <string>

#include "check.hpp"
#include "cJSON.h"
#include "sim_expr.h"
#include "sim_od.h"

#include <lely/co/type.h>

using namespace canopen_sim;

namespace {

std::string read_file(const std::string& path) {
  std::ifstream in(path);
  std::stringstream ss;
  ss << in.rdbuf();
  return ss.str();
}

// Devices: 0 = own, 1 = node 7, 2 = "spare". Objects at index 0x6999 do not exist.
class CorpusResolver : public ExprResolver {
 public:
  int self() const override { return 0; }
  int device(const std::string& name) const override {
    if (name == "7") return 1;
    if (name == "spare") return 2;
    return -1;
  }
  bool has_object(int, uint16_t index, uint8_t) const override { return index != 0x6999; }
};

class CorpusContext : public ExprContext {
 public:
  std::map<std::string, double> objects;
  double value(const ObjectRef& r) override {
    std::string dev = r.device == 0 ? "" : r.device == 1 ? "7/" : "spare/";
    char key[32];
    if (r.subindex == 0 && objects.count(dev + object_key(r.index, 0).substr(0, 6)))
      return objects[dev + object_key(r.index, 0).substr(0, 6)];
    std::snprintf(key, sizeof key, "%s", object_key(r.index, r.subindex).c_str());
    auto it = objects.find(dev + key);
    return it == objects.end() ? 0 : it->second;
  }
};

}  // namespace

TEST(expr_corpus) {
  std::string text = read_file(std::string(FIXTURES_DIR) + "/sim/expressions.json");
  cJSON* root = cJSON_Parse(text.c_str());
  CHECK(root != nullptr);
  if (!root) return;
  CorpusResolver res;
  CorpusContext base;
  const cJSON* ctx = cJSON_GetObjectItem(root, "context");
  base.t = cJSON_GetObjectItem(ctx, "t")->valuedouble;
  base.dt = cJSON_GetObjectItem(ctx, "dt")->valuedouble;
  base.prev = cJSON_GetObjectItem(ctx, "prev")->valuedouble;
  const cJSON* objs = cJSON_GetObjectItem(ctx, "objects");
  for (const cJSON* o = objs->child; o; o = o->next) {
    std::string k = o->string;
    // "spare/0x2000" -> "spare/0x2000" (subindex 0 key form used by value())
    base.objects[k] = o->valuedouble;
  }
  int n = 0;
  for (const cJSON* c = cJSON_GetObjectItem(root, "cases")->child; c; c = c->next, ++n) {
    std::string expr = cJSON_GetObjectItem(c, "expr")->valuestring;
    bool ok = cJSON_IsTrue(cJSON_GetObjectItem(c, "ok"));
    ExprError err;
    auto e = Expr::compile(expr, res, err);
    if (ok) {
      CHECK_MSG(e != nullptr, ("should compile: " + expr + " (" + err.message + ")").c_str());
      const cJSON* v = cJSON_GetObjectItem(c, "value");
      if (e && v) {
        CorpusContext cc = base;
        double got = e->eval(cc);
        CHECK_MSG(std::fabs(got - v->valuedouble) < 1e-9,
                  (expr + " = " + std::to_string(got) + ", want " + std::to_string(v->valuedouble)).c_str());
      }
    } else {
      CHECK_MSG(e == nullptr, ("should fail: " + expr).c_str());
      if (!e) {
        size_t pos = static_cast<size_t>(cJSON_GetObjectItem(c, "position")->valueint);
        std::string msg = cJSON_GetObjectItem(c, "message")->valuestring;
        CHECK_MSG(err.position == pos, (expr + ": position " + std::to_string(err.position) + ", want " +
                                        std::to_string(pos) + " (" + err.message + ")").c_str());
        CHECK_MSG(err.message.find(msg) != std::string::npos,
                  (expr + ": message '" + err.message + "' lacks '" + msg + "'").c_str());
      }
    }
  }
  CHECK(n > 40);
  cJSON_Delete(root);
}

// Values the control protocol refuses for set and override (sim_od.h).
TEST(value_misfit_by_type) {
  CHECK(value_misfit(CO_DEFTYPE_INTEGER16, Value::number(-32768)).empty());
  CHECK(value_misfit(CO_DEFTYPE_INTEGER16, Value::number(32767.4)).empty());  // rounds to 32767
  CHECK(value_misfit(CO_DEFTYPE_INTEGER16, Value::text("abc")) == "give a number");
  CHECK_MSG(value_misfit(CO_DEFTYPE_INTEGER16, Value::number(40000)) == "40000 is outside its range -32768 to 32767",
            value_misfit(CO_DEFTYPE_INTEGER16, Value::number(40000)));
  CHECK(!value_misfit(CO_DEFTYPE_UNSIGNED32, Value::number(-1)).empty());
  CHECK(!value_misfit(CO_DEFTYPE_UNSIGNED8, Value::number(NAN)).empty());
  CHECK(value_misfit(CO_DEFTYPE_BOOLEAN, Value::number(1)).empty());
  CHECK(!value_misfit(CO_DEFTYPE_BOOLEAN, Value::number(2)).empty());
  CHECK(value_misfit(CO_DEFTYPE_REAL32, Value::number(1.5)).empty());
  CHECK(value_misfit(CO_DEFTYPE_VISIBLE_STRING, Value::text("abc")).empty());
  CHECK(value_misfit(CO_DEFTYPE_VISIBLE_STRING, Value::number(1)) == "give text");
  CHECK(!value_misfit(CO_DEFTYPE_DOMAIN, Value::text("abc")).empty());
  CHECK(type_name(CO_DEFTYPE_INTEGER16) == "INTEGER16");
}

TEST(expr_stateful) {
  CorpusResolver res;
  CorpusContext c;
  ExprError err;
  auto lag = Expr::compile("lag(100, 1)", res, err);
  auto integ = Expr::compile("integrate(2)", res, err);
  auto rl = Expr::compile("rate_limit(if(t > 0.5, 10, 0), 5)", res, err);
  auto del = Expr::compile("delay(t, 0.5)", res, err);
  auto edge = Expr::compile("edge(t > 0.3)", res, err);
  auto hold = Expr::compile("hold(t, edge(t > 0.3))", res, err);
  CHECK(lag && integ && rl && del && edge && hold);
  c.dt = 0.01;
  double l = 0, i = 0, r = 0, d = 0, h = 0;
  int edges = 0;
  for (int k = 0; k <= 200; ++k) {
    c.t = k * 0.01;
    l = lag->eval(c);
    i = integ->eval(c);
    r = rl->eval(c);
    d = del->eval(c);
    edges += edge->eval(c) != 0;
    h = hold->eval(c);
  }
  CHECK(std::fabs(l - 100) < 1e-9);  // starts at its input
  CHECK(std::fabs(i - 2 * 0.01 * 201) < 1e-9);
  CHECK(std::fabs(r - 7.55) < 0.2);  // 1.5 s at 5/s after t = 0.5
  CHECK(std::fabs(d - 1.5) < 0.011);
  CHECK(edges == 1);
  CHECK(std::fabs(h - 0.31) < 0.011);
  // lag towards a step: 63 % after one time constant
  auto lag2 = Expr::compile("lag(if(t > 0, 100, 0), 1)", res, err);
  c.t = 0;
  lag2->eval(c);
  for (int k = 1; k <= 100; ++k) {
    c.t = k * 0.01;
    l = lag2->eval(c);
  }
  CHECK(std::fabs(l - 63.2) < 0.5);
}

TEST(expr_reads_and_reset) {
  CorpusResolver res;
  ExprError err;
  auto e = Expr::compile("[0x6200:1] + lag([7/0x6401:1], 2) + integrate([spare/0x2000])", res, err);
  CHECK(e != nullptr);
  CHECK(e->reads().size() == 3);
  CHECK(!e->reads()[0].delayed && e->reads()[1].delayed && e->reads()[2].delayed);
  CHECK(e->reads()[1].ref.device == 1 && e->reads()[1].ref.index == 0x6401 && e->reads()[1].ref.subindex == 1);
}

// Nesting and length limits: refused with the position, never a crash.
TEST(expr_limits) {
  CorpusResolver res;
  ExprError err;
  CHECK(!Expr::compile(std::string(10000, '('), res, err) && err.position == 4096 &&
        err.message.find("4096") != std::string::npos);
  err = ExprError();
  CHECK(!Expr::compile(std::string(2000, '(') + "1" + std::string(2000, ')'), res, err) && err.position == 128 &&
        err.message.find("128 levels") != std::string::npos);
  std::string pow;
  for (int i = 0; i < 1000; ++i) pow += "2**";
  CHECK(!Expr::compile(pow + "1", res, err) && err.position == 129 * 3 - 2);
  CHECK(!Expr::compile(std::string(2000, '!') + "1", res, err) && err.position == 128);
  // At the limit: compiles, evaluates and frees.
  std::string sum = "1";
  for (int i = 0; i < 127; ++i) sum += "+1";
  auto e = Expr::compile(sum, res, err);
  CHECK(e != nullptr);
  CorpusContext c;
  if (e) CHECK(e->eval(c) == 128);
  CHECK(!Expr::compile(sum + "+1", res, err) && err.position == sum.size());
}

// delay(): a non-finite delay counts as 0, time going back clears the
// history, and the history never holds more than 10,000 samples.
TEST(expr_delay_bounded) {
  CorpusResolver res;
  CorpusContext c;
  ExprError err;
  auto nan = Expr::compile("delay(t, 0 / 0)", res, err);
  auto inf = Expr::compile("delay(t, -log(0))", res, err);
  auto big = Expr::compile("delay(t, 600)", res, err);
  auto half = Expr::compile("delay(t, 0.5)", res, err);
  CHECK(nan && inf && big && half);
  if (!nan || !inf || !big || !half) return;
  double last = 0;
  bool now = true;
  for (int k = 0; k < 50000; ++k) {
    c.t = k * 0.001;
    now = now && nan->eval(c) == c.t && inf->eval(c) == c.t;
    last = big->eval(c);
    half->eval(c);
  }
  CHECK(now);
  // 600 s at 1 ms would be 600,000 samples: the oldest kept is 9,999 back.
  CHECK_MSG(std::fabs(last - (c.t - 9.999)) < 1e-6, std::to_string(last));
  // Time goes back: the old run's samples are gone.
  c.t = 0;
  CHECK_MSG(half->eval(c) == 0, std::to_string(half->eval(c)));
}

int main(int argc, char** argv) { return check::run_all(argc, argv); }
