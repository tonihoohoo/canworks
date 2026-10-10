// sim_expr.h - the simulator's expression language (docs/simulator.md,
// "Expressions").
//
// An expression is compiled once into a tree; names, functions and object
// references are resolved then, so evaluating never fails to find anything.
// Stateful functions (lag, delay, rate_limit, integrate, hold, edge) keep
// their state in their own node of the tree, so each call site has its own.
// Evaluation allocates only in delay(), whose history grows with the delay
// (at most 10,000 samples). Texts over 4096 characters and nesting over 128
// levels are refused, which bounds the recursion of parsing, evaluating and
// freeing a tree.

#ifndef CANOPEN_SIM_EXPR_H
#define CANOPEN_SIM_EXPR_H

#include <cstdint>
#include <deque>
#include <functional>
#include <memory>
#include <random>
#include <string>
#include <vector>

namespace canopen_sim {

// An object reference: a device (by its index in the engine's table) and an
// object.
struct ObjectRef {
  int device = -1;
  uint16_t index = 0;
  uint8_t subindex = 0;
  bool operator<(const ObjectRef& o) const {
    if (device != o.device) return device < o.device;
    if (index != o.index) return index < o.index;
    return subindex < o.subindex;
  }
  bool operator==(const ObjectRef& o) const {
    return device == o.device && index == o.index && subindex == o.subindex;
  }
};

// What compiling needs to know about the devices.
class ExprResolver {
 public:
  virtual ~ExprResolver() = default;
  // The device the expression belongs to.
  virtual int self() const = 0;
  // A device named in a reference ("7" or "spare"); -1 when there is none.
  virtual int device(const std::string& name) const = 0;
  virtual bool has_object(int device, uint16_t index, uint8_t subindex) const = 0;
};

// What evaluating needs.
class ExprContext {
 public:
  virtual ~ExprContext() = default;
  virtual double value(const ObjectRef& ref) = 0;
  double t = 0;     // seconds since the device's power-on
  double dt = 0;    // seconds since the last tick
  double prev = 0;  // the object's own value before this tick
  std::mt19937* rng = nullptr;
};

struct ExprError {
  size_t position = 0;
  std::string message;
};

class ExprNode;

class Expr {
 public:
  ~Expr();
  Expr(Expr&&) noexcept;
  Expr& operator=(Expr&&) noexcept;

  // Compiles `text`; on failure returns nullptr and fills `err`.
  static std::unique_ptr<Expr> compile(const std::string& text, const ExprResolver& resolver, ExprError& err);

  // Evaluates; the result may be NaN or infinite (the caller keeps the old
  // value then).
  double eval(ExprContext& ctx);
  // Forgets the state of the stateful functions (at power-on).
  void reset();

  const std::string& text() const { return text_; }
  // No stateful function, dt or prev: evaluating it again in the same tick
  // gives the same result for the same inputs.
  bool stateless() const { return stateless_; }
  // Every object the expression reads, and whether the read goes through a
  // lag, delay or integrate (which breaks a reference cycle).
  struct Read {
    ObjectRef ref;
    bool delayed = false;
  };
  const std::vector<Read>& reads() const { return reads_; }

 private:
  Expr();
  std::string text_;
  std::unique_ptr<ExprNode> root_;
  std::vector<Read> reads_;
  bool stateless_ = false;
};

// Parses "0x6200:1", "0x6200" (subindex 0); false when malformed.
bool parse_object_key(const std::string& text, uint16_t& index, uint8_t& subindex);
std::string object_key(uint16_t index, uint8_t subindex);

}  // namespace canopen_sim

#endif  // CANOPEN_SIM_EXPR_H
