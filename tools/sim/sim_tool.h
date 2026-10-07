// sim_tool.h - openplc-canopen-sim, the standalone simulator
// (docs/simulator.md, "openplc-canopen-sim"): its modes and shared helpers.

#ifndef OPENPLC_CANOPEN_SIM_TOOL_H
#define OPENPLC_CANOPEN_SIM_TOOL_H

#include <string>
#include <vector>

#ifndef CANOPEN_PLUGIN_VERSION
#define CANOPEN_PLUGIN_VERSION "unknown"
#endif

namespace sim_tool {

// Exit codes of every mode.
constexpr int kExitOk = 0;
constexpr int kExitFailed = 1;  // an error answer, a failed scenario
constexpr int kExitUsage = 2;   // usage or start-up error

// Command-line words after the program name (and after the subcommand).
class Args {
 public:
  explicit Args(std::vector<std::string> words) : words_(std::move(words)) {}
  bool done() const { return i_ >= words_.size(); }
  const std::string& peek() const { return words_[i_]; }
  std::string next() { return words_[i_++]; }
  // `--name VALUE` or `--name=VALUE` at the current word. Consumes it and
  // sets `value`; false (nothing consumed) when the word is another option.
  // A missing value sets `missing`.
  bool option(const char* name, std::string& value, bool& missing);
  // `--name` at the current word.
  bool flag(const char* name);

 private:
  std::vector<std::string> words_;
  size_t i_ = 0;
};

// Run mode: openplc-canopen-sim [CONFIG] [options].
int run_main(Args& args);
// Test mode: openplc-canopen-sim test ...
int test_main(Args& args);
// Control subcommands (status, get, set, ...): `cmd` is the subcommand.
int command_main(const std::string& cmd, Args& args);
bool is_command(const std::string& word);

void print_usage(bool full);

}  // namespace sim_tool

#endif  // OPENPLC_CANOPEN_SIM_TOOL_H
