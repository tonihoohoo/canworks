// sim_source.h - value sources (docs/simulator.md, "Value sources").
//
// A Source is parsed from its JSON form; an expression source is compiled
// separately with bind(), once the devices it may name are known. eval()
// gives the value at `t` seconds since the source started.

#ifndef CANOPEN_SIM_SOURCE_H
#define CANOPEN_SIM_SOURCE_H

#include <map>
#include <memory>
#include <random>
#include <string>
#include <vector>

#include "sim_expr.h"
#include "sim_od.h"

typedef struct cJSON cJSON;

namespace canopen_sim {

// CSV files of value sources. A file must resolve (symbolic links followed)
// under one of `roots`, be a regular file of at most 16 MB, with lines of at
// most 4096 bytes. The files of a simulation file are read when it loads;
// once `frozen`, a source only takes rows read then, so no tick reads a file.
struct CsvFiles {
  std::vector<std::string> roots;
  bool frozen = false;
  // Key: resolved path, column and time scale.
  std::map<std::string, std::vector<std::pair<double, double>>> rows;
};

constexpr size_t kCsvMaxBytes = 16u << 20;
constexpr size_t kCsvMaxLine = 4096;

class Source {
 public:
  enum class Type { Constant, Sine, Triangle, Sawtooth, Square, Ramp, Steps, RandomWalk, Counter, Csv, Expr };

  ~Source();
  // Parses one source object; `base_dir` resolves CSV paths. nullptr and
  // `err` on failure. Without `csv` a CSV file must lie under `base_dir`
  // and is read now; with it, see CsvFiles.
  static std::unique_ptr<Source> parse(const cJSON* json, const std::string& base_dir, std::string& err,
                                       CsvFiles* csv = nullptr);

  Type type() const { return type_; }
  // The JSON it was parsed from (for status answers and saving).
  const std::string& json() const { return json_; }
  unsigned tick_ms() const { return tick_ms_; }

  // Expression sources: compile against the devices. Others: true.
  bool bind(const ExprResolver& res, ExprError& err);
  const Expr* expr() const { return expr_.get(); }

  // Restarts the source's own time and state.
  void restart();
  // The value `t` seconds after the source started. For expressions `ctx`
  // carries the device's time, dt and prev; for random sources its rng.
  Value eval(double t, ExprContext& ctx);

 private:
  Source() = default;
  Type type_ = Type::Constant;
  std::string json_;
  unsigned tick_ms_ = 0;
  double noise_ = 0;
  Value constant_;
  double min_ = 0, max_ = 0, period_ = 1, phase_ = 0, duty_ = 0.5;
  double from_ = 0, to_ = 0, duration_ = 1;
  std::string then_ = "hold";
  std::vector<std::pair<double, double>> steps_;  // (value, duration)
  bool repeat_ = true;
  double max_step_ = 0, start_ = 0, step_ = 1;
  bool has_min_ = false, has_max_ = false, has_start_ = false;
  std::vector<std::pair<double, double>> csv_;  // (time, value)
  bool linear_ = true, loop_ = false;
  std::string expr_text_;
  std::unique_ptr<Expr> expr_;
  // State.
  bool started_ = false;
  double state_ = 0;
};

}  // namespace canopen_sim

#endif  // CANOPEN_SIM_SOURCE_H
