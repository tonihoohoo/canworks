#include "eds_lint.h"

#include <cerrno>
#include <cstdlib>
#include <cstring>
#include <fcntl.h>
#include <fstream>
#include <spawn.h>
#include <sstream>
#include <sys/stat.h>
#include <sys/wait.h>
#include <unistd.h>

#include "cJSON.h"

extern char** environ;

namespace canopen_plugin {

namespace {

bool read_file(const std::string& path, std::string& out) {
  std::ifstream f(path, std::ios::binary);
  if (!f) return false;
  std::ostringstream ss;
  ss << f.rdbuf();
  out = ss.str();
  return true;
}

bool make_dir(const std::string& dir) {
  std::string partial;
  std::stringstream ss(dir);
  if (!dir.empty() && dir[0] == '/') partial = "/";
  for (std::string part; std::getline(ss, part, '/');) {
    if (part.empty()) continue;
    partial += part + "/";
    if (mkdir(partial.c_str(), 0755) != 0 && errno != EEXIST) return false;
  }
  return true;
}

std::string last_lines(const std::string& text, size_t count) {
  std::istringstream ls(text);
  std::vector<std::string> lines;
  for (std::string line; std::getline(ls, line);)
    if (!line.empty()) lines.push_back(line);
  std::string tail;
  for (size_t i = lines.size() > count ? lines.size() - count : 0; i < lines.size(); ++i)
    tail += (tail.empty() ? "" : " | ") + lines[i];
  return tail;
}

// Runs args with stdout to out_path and stderr to err_path. Returns the exit
// status (0-255), or -1 with `why` set when it could not run or was killed.
int run(const std::vector<std::string>& args_in, const std::string& out_path, const std::string& err_path,
        std::string& why) {
  posix_spawn_file_actions_t fa;
  posix_spawn_file_actions_init(&fa);
  posix_spawn_file_actions_addopen(&fa, 0, "/dev/null", O_RDONLY, 0);
  posix_spawn_file_actions_addopen(&fa, 1, out_path.c_str(), O_WRONLY | O_CREAT | O_TRUNC, 0644);
  posix_spawn_file_actions_addopen(&fa, 2, err_path.c_str(), O_WRONLY | O_CREAT | O_TRUNC, 0644);
  std::vector<std::string> args = args_in;
  std::vector<char*> argv;
  for (auto& a : args) argv.push_back(&a[0]);
  argv.push_back(nullptr);
  pid_t pid;
  int rc = posix_spawnp(&pid, args[0].c_str(), &fa, nullptr, argv.data(), environ);
  posix_spawn_file_actions_destroy(&fa);
  if (rc != 0) {
    why = std::strerror(rc);
    return -1;
  }
  int status = 0;
  while (waitpid(pid, &status, 0) < 0 && errno == EINTR) {
  }
  if (!WIFEXITED(status)) {
    why = "killed by signal " + std::to_string(WTERMSIG(status));
    return -1;
  }
  return WEXITSTATUS(status);
}

std::string json_string(const cJSON* obj, const char* key) {
  const cJSON* item = cJSON_GetObjectItemCaseSensitive(obj, key);
  return cJSON_IsString(item) ? item->valuestring : "";
}

}  // namespace

std::string default_edslint_python() {
  const char* env = std::getenv("CANOPEN_EDSLINT");
  if (env && *env) return env;
#ifndef CANOPEN_PREFIX
#define CANOPEN_PREFIX "/opt/openplc-canopen"
#endif
  const char* venv = CANOPEN_PREFIX "/venv/bin/python";
  if (access(venv, X_OK) == 0) return venv;
  return "python3";
}

bool run_eds_lint(Config& cfg, const std::string& python, const std::string& work_dir,
                  std::vector<std::string>& errors) {
  size_t before = errors.size();
  std::string dir = work_dir + "/eds";
  if (!make_dir(dir)) {
    errors.push_back("cannot create " + dir + ": " + std::strerror(errno));
    return false;
  }
  for (auto& n : cfg.nodes) {
    struct stat st;
    if (stat(n.eds_path.c_str(), &st) != 0 || !S_ISREG(st.st_mode)) continue;  // check_eds_files says so
    std::string base = dir + "/node_" + std::to_string(n.node_id);
    std::string copy = base + ".eds", out_path = base + ".lint.json", err_path = base + ".lint.log";
    unlink(copy.c_str());  // a copy from an earlier load must not outlive its corrections
    std::vector<std::string> args = {python, "-m", "openplc_canopen_deploy.edslint", "--json",
                                     "--node-id", std::to_string(n.node_id), "--mode", cfg.master.eds_lint,
                                     "--label", n.label(), "--name", n.eds, "--out", copy, n.eds_path};
    std::string why;
    int rc = run(args, out_path, err_path, why);
    std::string out, err;
    read_file(out_path, out);
    read_file(err_path, err);
    cJSON* doc = rc == 0 ? cJSON_Parse(out.c_str()) : nullptr;
    if (!doc || !cJSON_IsObject(doc)) {
      if (why.empty()) why = rc == 0 ? "no result" : "exit status " + std::to_string(rc);
      std::string tail = last_lines(err, 2);
      errors.push_back("cannot run the EDS lint (" + python + " -m openplc_canopen_deploy.edslint): " + why +
                       (tail.empty() ? "" : ": " + tail) +
                       "; the deploy tool must be installed in the plugin's venv (rerun scripts/install-stock.sh)");
      cJSON_Delete(doc);
      return false;
    }
    const cJSON* notes = cJSON_GetObjectItemCaseSensitive(doc, "notes");
    const cJSON* note;
    cJSON_ArrayForEach(note, notes) if (cJSON_IsString(note)) cfg.notes.push_back(note->valuestring);
    std::string warning = json_string(doc, "warning"), error = json_string(doc, "error");
    if (!warning.empty()) cfg.warnings.push_back(n.label() + ": " + warning);
    if (!error.empty()) errors.push_back(error);
    const cJSON* finding;
    n.lint_findings.clear();
    cJSON_ArrayForEach(finding, cJSON_GetObjectItemCaseSensitive(doc, "findings")) {
      std::string message = json_string(finding, "message");
      if (!message.empty()) n.lint_findings.push_back(message);
    }
    std::string prepared = json_string(doc, "prepared");
    if (!prepared.empty()) n.eds_path = prepared;
    cJSON_Delete(doc);
  }
  return errors.size() == before;
}

}  // namespace canopen_plugin
