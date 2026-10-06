// check.hpp - a minimal test harness.

#ifndef CHECK_HPP
#define CHECK_HPP

#include <cstdio>
#include <functional>
#include <string>
#include <vector>

namespace check {

inline int& failures() {
  static int n = 0;
  return n;
}

struct Case {
  const char* name;
  std::function<void()> fn;
};

inline std::vector<Case>& cases() {
  static std::vector<Case> c;
  return c;
}

struct Register {
  Register(const char* name, std::function<void()> fn) { cases().push_back({name, fn}); }
};

// No arguments: every case. `<text>`: the cases whose name contains it.
// `--exact <name>`: that one case (ctest runs each case this way).
inline int run_all(int argc, char** argv) {
  bool exact = argc > 2 && std::string(argv[1]) == "--exact";
  const char* filter = exact ? argv[2] : argc > 1 ? argv[1] : nullptr;
  int ran = 0;
  for (auto& c : cases()) {
    if (filter && (exact ? std::string(c.name) != filter : std::string(c.name).find(filter) == std::string::npos)) continue;
    int before = failures();
    std::printf("[ RUN  ] %s\n", c.name);
    std::fflush(stdout);
    c.fn();
    std::printf("[ %s ] %s\n", failures() == before ? " OK " : "FAIL", c.name);
    ++ran;
  }
  std::printf("%d test(s), %d failure(s)\n", ran, failures());
  if (exact && ran == 0) {
    std::printf("no case named %s\n", filter);
    return 1;
  }
  return failures() ? 1 : 0;
}

}  // namespace check

#define TEST(name) \
  static void name(); \
  static check::Register reg_##name(#name, name); \
  static void name()

#define CHECK(cond)                                                          \
  do {                                                                       \
    if (!(cond)) {                                                           \
      ++check::failures();                                                   \
      std::printf("  %s:%d: CHECK failed: %s\n", __FILE__, __LINE__, #cond); \
    }                                                                        \
  } while (0)

#define CHECK_MSG(cond, msg)                                                          \
  do {                                                                                \
    if (!(cond)) {                                                                    \
      ++check::failures();                                                            \
      std::printf("  %s:%d: CHECK failed: %s (%s)\n", __FILE__, __LINE__, #cond,      \
                  std::string(msg).c_str());                                          \
    }                                                                                 \
  } while (0)

#endif  // CHECK_HPP
