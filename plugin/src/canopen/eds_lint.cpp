#include "eds_lint.h"

#include <cerrno>
#include <climits>
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
#include "dcf_gen.h"

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

// Runs args (args[0] an absolute path) with stdout to out_path and stderr to
// err_path, under the helper time limit (dcf_gen.h). Returns the exit status
// (0-255), or -1 with `why` set when it could not run, timed out or was killed.
int run(const std::vector<std::string>& args, const std::string& out_path, const std::string& err_path,
        std::string& why) {
  posix_spawn_file_actions_t fa;
  posix_spawn_file_actions_init(&fa);
  posix_spawn_file_actions_addopen(&fa, 0, "/dev/null", O_RDONLY, 0);
  posix_spawn_file_actions_addopen(&fa, 1, out_path.c_str(), O_WRONLY | O_CREAT | O_TRUNC, 0644);
  posix_spawn_file_actions_addopen(&fa, 2, err_path.c_str(), O_WRONLY | O_CREAT | O_TRUNC, 0644);
  pid_t pid;
  bool started = !args[0].empty() && args[0][0] == '/' && spawn_helper(args, &fa, pid, why);
  posix_spawn_file_actions_destroy(&fa);
  if (!started) {
    if (why.empty()) why = "not found";
    return -1;
  }
  int status = 0;
  if (!wait_helper(pid, status, why)) return -1;
  if (!WIFEXITED(status)) {
    why = "killed by signal " + std::to_string(WTERMSIG(status));
    return -1;
  }
  return WEXITSTATUS(status);
}

// Python runs isolated (-I: no PYTHONPATH, user site or working directory on
// its path). A development or test interpreter named by $CANWORKS_EDSLINT
// finds the module through the absolute forms of $PYTHONPATH's entries,
// which the plugin puts on the path itself; the installed venv has it in its
// site-packages.
std::vector<std::string> module_path() {
  std::vector<std::string> out;
  const char* lint = std::getenv("CANWORKS_EDSLINT");
  const char* pp = std::getenv("PYTHONPATH");
  if (!lint || !*lint || !pp) return out;
  std::stringstream ss(pp);
  for (std::string dir; std::getline(ss, dir, ':');) {
    if (dir.empty()) continue;
    char buf[PATH_MAX];
    if (realpath(dir.c_str(), buf)) out.push_back(buf);
  }
  return out;
}

std::string json_string(const cJSON* obj, const char* key) {
  const cJSON* item = cJSON_GetObjectItemCaseSensitive(obj, key);
  return cJSON_IsString(item) ? item->valuestring : "";
}

}  // namespace

std::string default_edslint_python() {
  const char* env = std::getenv("CANWORKS_EDSLINT");
  if (env && *env) return resolve_program(env);
#ifndef CANWORKS_PREFIX
#define CANWORKS_PREFIX "/opt/canworks"
#endif
  const char* venv = CANWORKS_PREFIX "/venv/bin/python";
  if (access(venv, X_OK) == 0) return venv;
  return resolve_program("python3");
}

bool run_eds_lint(Config& cfg, const std::string& python, const std::string& work_dir,
                  std::vector<std::string>& errors) {
  size_t before = errors.size();
  const std::string exe = !python.empty() && python[0] == '/' ? python : resolve_program(python);
  // -I: isolated; with extra module directories the module runs through a
  // bootstrap that puts them first on its path.
  std::vector<std::string> head = {exe, "-I"};
  std::vector<std::string> extra = module_path();
  if (extra.empty()) {
    head.insert(head.end(), {"-m", "canworks.edslint"});
  } else {
    std::string joined;
    for (const auto& d : extra) joined += (joined.empty() ? "" : ":") + d;
    head.insert(head.end(), {"-c",
                             "import runpy, sys; sys.path[:0] = sys.argv.pop(1).split(':'); "
                             "runpy.run_module('canworks.edslint', run_name='__main__', alter_sys=True)",
                             joined});
  }
  std::string dir = work_dir + "/eds";
  if (!make_dir(dir)) {
    errors.push_back("cannot create " + dir + ": " + std::strerror(errno));
    return false;
  }
  // One EDS to lint: the nodes' of a master network, or the slave's own.
  struct Item {
    std::string* eds_path;
    std::vector<std::string>* findings;
    const std::string* eds;
    std::string label, base, mode;
    unsigned node_id;
  };
  std::vector<Item> items;
  if (cfg.is_slave()) {
    SlaveConfig& s = cfg.slave;
    // An LSS slave has no node ID yet; its EDS is linted as node 1.
    items.push_back({&s.eds_path, &s.lint_findings, &s.eds, s.label(), dir + "/slave", s.eds_lint,
                     s.lss ? 1u : s.node_id});
  }
  for (auto& n : cfg.nodes)
    items.push_back({&n.eds_path, &n.lint_findings, &n.eds, n.label(), dir + "/node_" + std::to_string(n.node_id),
                     cfg.master.eds_lint, n.node_id});
  for (auto& it : items) {
    struct stat st;
    if (stat(it.eds_path->c_str(), &st) != 0 || !S_ISREG(st.st_mode)) continue;  // check_eds_files says so
    const std::string& base = it.base;
    std::string copy = base + ".eds", out_path = base + ".lint.json", err_path = base + ".lint.log";
    unlink(copy.c_str());  // a copy from an earlier load must not outlive its corrections
    std::vector<std::string> args = head;
    args.insert(args.end(), {"--json",
                                     "--node-id", std::to_string(it.node_id), "--mode", it.mode,
                                     "--label", it.label, "--name", *it.eds, "--out", copy, *it.eds_path});
    std::string why;
    int rc = run(args, out_path, err_path, why);
    std::string out, err;
    read_file(out_path, out);
    read_file(err_path, err);
    cJSON* doc = rc == 0 ? cJSON_Parse(out.c_str()) : nullptr;
    if (!doc || !cJSON_IsObject(doc)) {
      if (why.empty()) why = rc == 0 ? "no result" : "exit status " + std::to_string(rc);
      std::string tail = last_lines(err, 2);
      errors.push_back("cannot run the EDS lint (" + python + " -I -m canworks.edslint): " + why +
                       (tail.empty() ? "" : ": " + tail) +
                       ((access(python.c_str(), X_OK) != 0 && errno == EACCES) ||
                                (why + err).find("Permission denied") != std::string::npos
                            ? "; this user may not run it: run as root (sudo), as the service does"
                            : "; the deploy tool must be installed in the plugin's venv (rerun scripts/install-stock.sh, "
                              "or scripts/install-bridge.sh for canworks-bridge)"));
      cJSON_Delete(doc);
      return false;
    }
    const cJSON* notes = cJSON_GetObjectItemCaseSensitive(doc, "notes");
    const cJSON* note;
    cJSON_ArrayForEach(note, notes) if (cJSON_IsString(note)) cfg.notes.push_back(note->valuestring);
    std::string warning = json_string(doc, "warning"), error = json_string(doc, "error");
    if (!warning.empty()) cfg.warnings.push_back(it.label + ": " + warning);
    if (!error.empty()) errors.push_back(error);
    const cJSON* finding;
    it.findings->clear();
    cJSON_ArrayForEach(finding, cJSON_GetObjectItemCaseSensitive(doc, "findings")) {
      std::string message = json_string(finding, "message");
      if (!message.empty()) it.findings->push_back(message);
    }
    std::string prepared = json_string(doc, "prepared");
    if (!prepared.empty()) *it.eds_path = prepared;
    cJSON_Delete(doc);
  }
  return errors.size() == before;
}

}  // namespace canopen_plugin
