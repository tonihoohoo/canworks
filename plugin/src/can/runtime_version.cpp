#include "runtime_version.h"

#include <fstream>

namespace canopen_plugin {

namespace {

std::string trim(const std::string& s) {
  const char* ws = " \t\r\n";
  size_t b = s.find_first_not_of(ws);
  if (b == std::string::npos) return "";
  return s.substr(b, s.find_last_not_of(ws) - b + 1);
}

}  // namespace

std::string runtime_version_problem(const std::string& stamp_path, const char* running) {
  if (!running) return "";  // native install
  std::string now = trim(running);
  if (now.empty()) return "";
  std::ifstream in(stamp_path);
  std::string built;
  if (!in || !std::getline(in, built) || trim(built).empty())
    return "no build stamp at " + stamp_path + " for runtime " + now +
           "; re-run scripts/install-stock.sh to rebuild the CANopen plugin";
  built = trim(built);
  if (built != now)
    return "the CANopen plugin was built for runtime " + built + " but the runtime is " + now +
           "; re-run scripts/install-stock.sh to rebuild it";
  return "";
}

}  // namespace canopen_plugin
