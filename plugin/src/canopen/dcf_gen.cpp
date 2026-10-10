#include "dcf_gen.h"

#include "eds_check.h"

#include <cerrno>
#include <climits>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fcntl.h>
#include <fstream>
#include <map>
#include <poll.h>
#include <regex>
#include <signal.h>
#include <thread>
#include <set>
#include <spawn.h>
#include <sstream>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <unistd.h>

#include <lely/co/dcf.h>
#include <lely/co/dev.h>

#include "log.h"

extern char** environ;

namespace canopen_plugin {

namespace {

std::string hex(unsigned v, int width = 4) {
  char buf[16];
  std::snprintf(buf, sizeof(buf), "0x%0*X", width, v);
  return buf;
}

// Quotes a string for YAML (double-quoted scalar).
std::string yq(const std::string& s) {
  std::string out = "\"";
  for (char c : s) {
    if (c == '"' || c == '\\') out += '\\';
    out += c;
  }
  return out + "\"";
}

bool read_file(const std::string& path, std::string& out) {
  std::ifstream in(path, std::ios::binary);
  if (!in) return false;
  std::stringstream ss;
  ss << in.rdbuf();
  out = ss.str();
  return true;
}

bool write_file(const std::string& path, const std::string& data) {
  std::ofstream out(path, std::ios::binary | std::ios::trunc);
  if (!out) return false;
  out << data;
  return static_cast<bool>(out);
}

uint64_t fnv1a(uint64_t h, const std::string& data) {
  for (unsigned char c : data) {
    h ^= c;
    h *= 0x100000001b3ULL;
  }
  return h;
}

bool file_exists(const std::string& path) {
  struct stat st;
  return stat(path.c_str(), &st) == 0;
}

bool mkdir_p(const std::string& dir) {
  std::string cur;
  std::stringstream ss(dir);
  std::string part;
  if (!dir.empty() && dir[0] == '/') cur = "/";
  while (std::getline(ss, part, '/')) {
    if (part.empty()) continue;
    cur += part + "/";
    if (mkdir(cur.c_str(), 0755) != 0 && errno != EEXIST) return false;
  }
  return true;
}

// PDO numbers the slave's EDS defines, so unconfigured PDOs can be disabled.
void eds_pdo_numbers(const std::string& eds, std::set<unsigned>& tpdos, std::set<unsigned>& rpdos) {
  co_dev_t* dev = co_dev_create_from_dcf_file(eds.c_str());
  if (!dev) return;
  for (unsigned n = 1; n <= 512; ++n) {
    if (co_dev_find_obj(dev, 0x1800 + n - 1) && co_dev_find_obj(dev, 0x1A00 + n - 1)) tpdos.insert(n);
    if (co_dev_find_obj(dev, 0x1400 + n - 1) && co_dev_find_obj(dev, 0x1600 + n - 1)) rpdos.insert(n);
  }
  co_dev_destroy(dev);
}

// The PDO parameters the config sets explicitly, as writes, inserted after
// the write that switches their PDO off (or before the one that switches it
// on) unless dcfgen already wrote them. Read-only sub-indices are left out:
// the EDS checks made sure their value is the configured one.
void add_explicit_pdo_writes(const NodeConfig& n, std::vector<SdoWrite>& sdos) {
  auto le = [](uint32_t v, unsigned bytes) {
    std::vector<uint8_t> d;
    for (unsigned b = 0; b < bytes; ++b) d.push_back(static_cast<uint8_t>(v >> (8 * b)));
    return d;
  };
  for (int tx = 1; tx >= 0; --tx) {
    for (const auto& p : tx ? n.tx_pdos : n.rx_pdos) {
      uint16_t comm = static_cast<uint16_t>((tx ? 0x1800 : 0x1400) + p.number - 1);
      std::vector<SdoWrite> add;
      auto want = [&](uint8_t sub, uint32_t value, unsigned bytes) {
        if (n.ro_pdo_comm.count({comm, sub})) return;
        for (const auto& w : sdos)
          if (w.index == comm && w.subindex == sub) return;
        SdoWrite w;
        w.index = comm;
        w.subindex = sub;
        w.data = le(value, bytes);
        add.push_back(std::move(w));
      };
      if (p.has_transmission) want(2, p.transmission, 1);
      if (tx && p.has_inhibit_time) want(3, p.inhibit_time_us / 100, 2);
      if (tx && p.has_event_timer) want(5, p.event_timer_ms, 2);
      if (tx && p.has_sync_start) want(6, p.sync_start, 1);
      if (add.empty()) continue;
      // After the COB-ID write with bit 31 set (PDO off); else before the
      // COB-ID write that switches it on; else last.
      auto at = sdos.end();
      for (auto it = sdos.begin(); it != sdos.end(); ++it) {
        if (it->index != comm || it->subindex != 1 || it->data.size() != 4) continue;
        if (it->data[3] & 0x80) {
          at = it + 1;
          break;
        }
        if (at == sdos.end()) at = it;
      }
      sdos.insert(at, add.begin(), add.end());
    }
  }
}

void emit_pdos(std::ostringstream& y, const NodeConfig& n, bool is_tx) {
  const auto& pdos = is_tx ? n.tx_pdos : n.rx_pdos;
  std::set<unsigned> tpdos, rpdos;
  eds_pdo_numbers(n.eds_path, tpdos, rpdos);
  const std::set<unsigned>& present = is_tx ? tpdos : rpdos;
  std::set<unsigned> configured;
  for (const auto& p : pdos) configured.insert(p.number);
  bool any_off = false;
  for (unsigned num : present)
    any_off |= !configured.count(num) && !(is_tx ? n.kept_tpdos : n.kept_rpdos).count(num);
  if (pdos.empty() && !any_off) return;

  y << "  " << (is_tx ? "tpdo" : "rpdo") << ":\n";
  for (const auto& p : pdos) {
    uint32_t cob = is_tx ? n.tpdo_cob_id(p) : n.rpdo_cob_id(p);
    y << "    " << p.number << ":\n";
    y << "      enabled: true\n";
    y << "      cob_id: " << hex(cob, 3) << "\n";
    // Left out: the slave keeps the transmission type its EDS gives.
    if (p.has_transmission) y << "      transmission: " << p.transmission << "\n";
    if (p.has_inhibit_time) y << "      inhibit_time: " << p.inhibit_time_us / 100 << "\n";
    // The RPDO event timer (deadline) is written by the plugin itself: dcfgen
    // 2.4.2 fails on an RPDO event_deadline without event_timer.
    if (is_tx && p.has_event_timer) y << "      event_timer: " << p.event_timer_ms << "\n";
    if (p.has_sync_start) y << "      sync_start: " << p.sync_start << "\n";
    // Without a mapping list dcfgen writes no mapping and the master unpacks
    // the PDO with the EDS default mapping.
    if (p.device_mapping) continue;
    y << "      mapping:\n";
    for (const auto& e : p.entries)
      y << "        - {index: " << hex(e.index) << ", sub_index: " << unsigned(e.subindex) << "}\n";
  }
  // The slave's own PDOs that the JSON does not use are switched off, so the
  // slave's PDO set matches the configuration; those with a read-only COB-ID
  // are left out and stay as the node has them.
  const std::set<unsigned>& kept = is_tx ? n.kept_tpdos : n.kept_rpdos;
  for (unsigned num : present) {
    if (configured.count(num) || kept.count(num)) continue;
    y << "    " << num << ":\n";
    y << "      enabled: false\n";
  }
}

}  // namespace

std::string startup_sdo_key(const Config& cfg) {
  std::string key;
  for (const auto& n : cfg.nodes)
    for (const auto& s : n.sdos) {
      key += std::to_string(n.node_id) + ":" + hex(s.index) + ":" + std::to_string(s.subindex) + "=";
      for (uint8_t b : s.data) key += hex(b, 2);
      key += ";";
    }
  for (const auto& n : cfg.nodes)
    if (n.interpolation_write_us)
      key += std::to_string(n.node_id) + ":60C2=" + std::to_string(n.interpolation_write_us) + ";";
  return key;
}

void resolve_interpolation_periods(Config& cfg, unsigned long long base_tick_us) {
  for (auto& n : cfg.nodes) {
    n.interpolation_write_us = 0;
    if (!n.axis_cyclic) continue;
    bool own = false;
    for (const auto& s : n.sdos) own |= s.index == 0x60C2;
    if (own) {
      log_info("%s: cyclic axis: the startup SDOs write the interpolation time period 0x60C2", n.label().c_str());
      continue;
    }
    uint16_t type;
    if (!eds_sub_type(n, 0x60C2, 1, type) || !eds_sub_type(n, 0x60C2, 2, type)) {
      log_warn("%s: cyclic axis: the EDS (%s) has no 0x60C2 sub 1 and 2; the interpolation time period is not "
               "written", n.label().c_str(), n.eds_path.c_str());
      continue;
    }
    unsigned long long period = n.interpolation_period_us
                                    ? n.interpolation_period_us
                                    : base_tick_us * (cfg.master.sync_cycles ? cfg.master.sync_cycles : 1);
    uint8_t value;
    int8_t exponent;
    if (!period) {
      log_warn("%s: cyclic axis: the runtime does not report its base tick, so the interpolation time period 0x60C2 "
               "is not written; set axis.interpolation_period_us", n.label().c_str());
      continue;
    }
    if (period > 255000 || !interpolation_code(static_cast<unsigned>(period), value, exponent)) {
      log_warn("%s: cyclic axis: the SYNC period of %llu us cannot be written to 0x60C2 (1-255 times 1 ms, 100 us, "
               "10 us or 1 us); set axis.interpolation_period_us or a startup SDO", n.label().c_str(), period);
      continue;
    }
    n.interpolation_write_us = static_cast<unsigned>(period);
    log_info("%s: cyclic axis: interpolation time period %llu us (0x60C2 sub 1 = %u, sub 2 = %d)", n.label().c_str(),
             period, value, exponent);
  }
}

std::string make_dcfgen_yaml(const Config& cfg, const std::string& work_dir) {
  std::ostringstream y;
  y << "# Generated by the OpenPLC CANopen plugin from " << cfg.path << ".\n";
  y << "# Do not edit: it is rewritten whenever the configuration changes.\n";
  y << "options:\n";
  y << "  dcf_path: " << yq(work_dir) << "\n";
  y << "master:\n";
  y << "  node_id: " << cfg.master.node_id << "\n";
  y << "  baudrate: " << cfg.adapter.bitrate / 1000 << "\n";
  y << "  sync_period: " << cfg.master.sync_period_us << "\n";
  y << "  heartbeat_producer: " << cfg.master.heartbeat_ms << "\n";
  const MasterConfig& m = cfg.master;
  // Each option only when the JSON sets it, so an existing configuration
  // generates the same files as before.
  if (m.has_vendor_id) y << "  vendor_id: " << hex(m.vendor_id, 8) << "\n";
  if (m.has_product_code) y << "  product_code: " << hex(m.product_code, 8) << "\n";
  if (m.has_revision_number) y << "  revision_number: " << hex(m.revision_number, 8) << "\n";
  if (m.has_serial_number) y << "  serial_number: " << hex(m.serial_number, 8) << "\n";
  if (m.has_sync_window) y << "  sync_window: " << m.sync_window_us << "\n";
  if (m.has_sync_counter_overflow) y << "  sync_overflow: " << m.sync_counter_overflow << "\n";
  // With time_period_ms the master produces TIME: bit 30 of its 0x1012.
  if (m.time_period_ms)
    y << "  time_cob_id: " << hex((m.has_time_cob_id ? m.time_cob_id : 0x100u) | 0x40000000u, 8) << "\n";
  else if (m.has_time_cob_id)
    y << "  time_cob_id: " << hex(m.time_cob_id, 8) << "\n";
  if (m.has_emcy_inhibit_time) y << "  emcy_inhibit_time: " << m.emcy_inhibit_time_us / 100 << "\n";
  y << "  heartbeat_consumer: " << (m.heartbeat_consumer ? "true" : "false") << "\n";
  if (m.has_heartbeat_multiplier) {
    char mult[32];
    std::snprintf(mult, sizeof(mult), "%.6f", m.heartbeat_multiplier);
    y << "  heartbeat_multiplier: " << mult << "\n";
  }
  if (!m.error_behavior.empty()) {
    y << "  error_behavior:\n";
    for (const auto& eb : m.error_behavior) y << "    " << eb.first << ": " << eb.second << "\n";
  }
  if (m.has_nmt_inhibit_time) y << "  nmt_inhibit_time: " << m.nmt_inhibit_time_us / 100 << "\n";
  if (!m.start) y << "  start: false\n";
  y << "  start_nodes: " << (m.start_nodes ? "true" : "false") << "\n";
  if (m.start_all_nodes) y << "  start_all_nodes: true\n";
  if (m.reset_all_nodes) y << "  reset_all_nodes: true\n";
  if (m.stop_all_nodes) y << "  stop_all_nodes: true\n";
  if (m.has_boot_time) y << "  boot_time: " << m.boot_time_ms << "\n";
  for (const auto& n : cfg.nodes) {
    y << "node_" << n.node_id << ":\n";
    y << "  dcf: " << yq(n.eds_path) << "\n";
    y << "  node_id: " << n.node_id << "\n";
    // Without heartbeat_ms the slave keeps its EDS heartbeat (0x1017), and
    // the master watches it with 3 x that period.
    if (n.has_heartbeat) y << "  heartbeat_producer: " << n.heartbeat_ms << "\n";
    char mult[32];
    std::snprintf(mult, sizeof(mult), "%.6f",
                  n.heartbeat_ms ? (double)n.heartbeat_timeout_ms / n.heartbeat_ms : 3.0);
    y << "  heartbeat_multiplier: " << mult << "\n";
    if (n.guard_time_ms) {
      y << "  guard_time: " << n.guard_time_ms << "\n";
      y << "  life_time_factor: " << n.life_time_factor << "\n";
    }
    y << "  retry_factor: " << (n.has_retry_factor ? n.retry_factor : n.guard_time_ms ? n.life_time_factor : 0)
      << "\n";
    y << "  boot: " << (n.boot ? "true" : "false") << "\n";
    y << "  mandatory: " << (n.mandatory ? "true" : "false") << "\n";
    if (n.has_reset_communication) y << "  reset_communication: " << (n.reset_communication ? "true" : "false") << "\n";
    if (n.has_revision_number) y << "  revision_number: " << hex(n.revision_number, 8) << "\n";
    if (n.has_serial_number) y << "  serial_number: " << hex(n.serial_number, 8) << "\n";
    if (n.has_heartbeat_consumer) y << "  heartbeat_consumer: " << (n.heartbeat_consumer ? "true" : "false") << "\n";
    // time_cob_id is written by the plugin itself: dcfgen 2.4.2 compares it
    // with 0x100 instead of the EDS value.
    if (!n.error_behavior.empty()) {
      y << "  error_behavior:\n";
      for (const auto& eb : n.error_behavior) y << "    " << eb.first << ": " << eb.second << "\n";
    }
    if (n.has_restore_configuration) y << "  restore_configuration: " << n.restore_configuration << "\n";
    if (!n.software_file.empty()) y << "  software_file: " << yq(n.software_path) << "\n";
    if (n.has_software_version) y << "  software_version: " << n.software_version << "\n";
    emit_pdos(y, n, true);
    emit_pdos(y, n, false);
  }
  return y.str();
}

bool read_concise_dcf(const std::string& path, std::vector<SdoWrite>& out, std::string& error) {
  std::string data;
  if (!read_file(path, data)) {
    error = "cannot read " + path;
    return false;
  }
  auto u16 = [&](size_t at) { return uint16_t(uint8_t(data[at]) | uint8_t(data[at + 1]) << 8); };
  auto u32 = [&](size_t at) {
    return uint32_t(uint8_t(data[at])) | uint32_t(uint8_t(data[at + 1])) << 8 |
           uint32_t(uint8_t(data[at + 2])) << 16 | uint32_t(uint8_t(data[at + 3])) << 24;
  };
  if (data.size() < 4) {
    error = path + ": truncated concise DCF";
    return false;
  }
  uint32_t count = u32(0);
  size_t pos = 4;
  out.clear();
  for (uint32_t i = 0; i < count; ++i) {
    // Written as differences: pos <= data.size() holds, so nothing wraps
    // (a size field near 4 GB would wrap pos + size on a 32-bit host).
    if (data.size() - pos < 7) {
      error = path + ": truncated concise DCF";
      return false;
    }
    SdoWrite w;
    w.index = u16(pos);
    w.subindex = uint8_t(data[pos + 2]);
    uint32_t size = u32(pos + 3);
    pos += 7;
    if (size > data.size() - pos) {
      error = path + ": truncated concise DCF";
      return false;
    }
    w.data.assign(data.begin() + pos, data.begin() + pos + size);
    pos += size;
    out.push_back(std::move(w));
  }
  return true;
}

std::string default_dcfgen() {
  const char* env = std::getenv("CANWORKS_DCFGEN");
  if (env && *env) return resolve_program(env);
#ifndef CANWORKS_PREFIX
#define CANWORKS_PREFIX "/opt/canworks"
#endif
  const char* venv = CANWORKS_PREFIX "/venv/bin/dcfgen";
  if (access(venv, X_OK) == 0) return venv;
  return resolve_program("dcfgen");
}

std::string resolve_program(const std::string& program) {
  if (program.empty()) return "";
  if (program.find('/') != std::string::npos) {
    char buf[PATH_MAX];
    if (!realpath(program.c_str(), buf) || access(buf, X_OK) != 0) return "";
    return buf;
  }
  const char* path = std::getenv("PATH");
  std::stringstream ss(path ? path : "/usr/local/bin:/usr/bin:/bin");
  for (std::string dir; std::getline(ss, dir, ':');) {
    if (dir.empty() || dir[0] != '/') continue;  // never the working directory
    std::string cand = dir + "/" + program;
    struct stat st;
    if (stat(cand.c_str(), &st) == 0 && S_ISREG(st.st_mode) && access(cand.c_str(), X_OK) == 0) return cand;
  }
  return "";
}

namespace {
std::chrono::milliseconds g_helper_limit{60000};
}  // namespace

std::chrono::milliseconds helper_time_limit() { return g_helper_limit; }
void set_helper_time_limit(std::chrono::milliseconds limit) { g_helper_limit = limit; }

bool spawn_helper(const std::vector<std::string>& args_in, const posix_spawn_file_actions_t* fa, pid_t& pid,
                  std::string& why) {
  std::vector<std::string> args = args_in;
  std::vector<char*> argv;
  for (auto& a : args) argv.push_back(&a[0]);
  argv.push_back(nullptr);
  posix_spawnattr_t attr;
  posix_spawnattr_init(&attr);
  posix_spawnattr_setflags(&attr, POSIX_SPAWN_SETPGROUP);
  posix_spawnattr_setpgroup(&attr, 0);
  int rc = posix_spawn(&pid, args[0].c_str(), fa, &attr, argv.data(), environ);
  posix_spawnattr_destroy(&attr);
  if (rc != 0) {
    why = std::strerror(rc);
    return false;
  }
  return true;
}

bool wait_helper(pid_t pid, int& status, std::string& why) {
  auto limit = helper_time_limit();
  auto deadline = std::chrono::steady_clock::now() + limit;
  auto pause = std::chrono::milliseconds(1);
#ifdef SYS_pidfd_open
  // Woken the moment the helper exits; the polling below is the fallback
  // for kernels without pidfd_open.
  int pidfd = static_cast<int>(syscall(SYS_pidfd_open, pid, 0));
#else
  int pidfd = -1;
#endif
  while (true) {
    pid_t r = waitpid(pid, &status, WNOHANG);
    if (r == pid) {
      if (pidfd >= 0) close(pidfd);
      return true;
    }
    if (r < 0 && errno != EINTR) {
      why = std::string("waitpid: ") + std::strerror(errno);
      if (pidfd >= 0) close(pidfd);
      kill(-pid, SIGKILL);
      return false;
    }
    auto now = std::chrono::steady_clock::now();
    if (now >= deadline) break;
    if (pidfd >= 0) {
      auto left = std::chrono::duration_cast<std::chrono::milliseconds>(deadline - now).count() + 1;
      pollfd p{pidfd, POLLIN, 0};
      poll(&p, 1, static_cast<int>(std::min<long long>(left, INT_MAX)));
      continue;
    }
    std::this_thread::sleep_for(pause);
    pause = std::min(pause * 2, std::chrono::milliseconds(50));
  }
  if (pidfd >= 0) close(pidfd);
  kill(-pid, SIGKILL);
  while (waitpid(pid, &status, 0) < 0 && errno == EINTR) {
  }
  long long ms = static_cast<long long>(limit.count());
  why = ms % 1000 ? "timed out after " + std::to_string(ms) + " ms"
                  : "timed out after " + std::to_string(ms / 1000) + " s";
  return false;
}

namespace {

bool run_dcfgen(const std::string& dcfgen, const Config& cfg, const std::string& dir,
                const std::string& yaml_path, std::vector<std::string>& errors) {
  std::string log_path = dir + "/dcfgen.log";
  posix_spawn_file_actions_t fa;
  posix_spawn_file_actions_init(&fa);
  posix_spawn_file_actions_addopen(&fa, 1, log_path.c_str(), O_WRONLY | O_CREAT | O_TRUNC, 0644);
  posix_spawn_file_actions_adddup2(&fa, 1, 2);
  posix_spawn_file_actions_addopen(&fa, 0, "/dev/null", O_RDONLY, 0);

  // The plugin's own lint (eds_lint.h) decides which findings stop the load.
  std::vector<std::string> args = {dcfgen, "--remote-pdo", "--no-strict", "-d", dir};
  args.push_back(yaml_path);

  pid_t pid;
  std::string why;
  bool started = !dcfgen.empty() && dcfgen[0] == '/' && spawn_helper(args, &fa, pid, why);
  posix_spawn_file_actions_destroy(&fa);
  if (!started) {
    errors.push_back("cannot run dcfgen (" + (dcfgen.empty() ? std::string("not found") : dcfgen) + ")" +
                     (why.empty() ? "" : ": " + why) + "; is Lely's dcf-tools installed? (see docs/install.md)");
    return false;
  }
  int status = 0;
  if (!wait_helper(pid, status, why)) {
    errors.push_back("dcfgen on " + yaml_path + ": " + why + "; it was stopped (log: " + log_path + ")");
    return false;
  }
  if (!WIFEXITED(status) || WEXITSTATUS(status) != 0) {
    std::string log;
    read_file(log_path, log);
    // dcfgen's last lines name the problem (Python traceback ends with it).
    std::istringstream ls(log);
    std::vector<std::string> lines;
    for (std::string line; std::getline(ls, line);)
      if (!line.empty()) lines.push_back(line);
    std::string tail;
    for (size_t i = lines.size() > 3 ? lines.size() - 3 : 0; i < lines.size(); ++i)
      tail += (tail.empty() ? "" : " | ") + lines[i];
    errors.push_back("dcfgen failed on " + yaml_path + ": " + (tail.empty() ? "no output" : tail) +
                     " (full log: " + log_path + ")");
    return false;
  }
  return true;
}

// The plugin performs the slave configuration downloads itself (so it can
// report which object a slave rejected), so the master must not download the
// concise DCFs referenced from 1F22 on its own. Program files (1F58) stay:
// the master downloads those itself during boot.
bool strip_upload_files(const std::string& master_dcf) {
  std::string text;
  if (!read_file(master_dcf, text)) return false;
  std::istringstream in(text);
  std::ostringstream out;
  bool program_data = false;
  for (std::string line; std::getline(in, line);) {
    if (!line.empty() && line[0] == '[') program_data = line.compare(0, 5, "[1F58") == 0 || line.compare(0, 5, "[1f58") == 0;
    if (line.compare(0, 11, "UploadFile=") == 0 && !program_data) continue;
    out << line << "\n";
  }
  return write_file(master_dcf, out.str());
}

// dcfgen lists an EMCY consumer (1028) only for the configured slaves whose
// EDS has 1014. Every other node ID gets its predefined EMCY COB-ID
// (0x80 + node ID) too, so the master sees, and can report, EMCY messages from
// nodes that are not in the configuration.
bool add_emcy_consumers(const std::string& master_dcf, unsigned master_id) {
  std::string text;
  if (!read_file(master_dcf, text)) return false;
  std::istringstream in(text);
  std::ostringstream out;
  std::map<unsigned, std::string> entries;
  bool in_section = false, done = false;
  auto flush = [&] {
    // A slave whose EDS moves its EMCY onto another node's predefined COB-ID
    // keeps it; that other node ID gets no entry.
    std::set<unsigned long> used;
    for (const auto& e : entries) used.insert(std::strtoul(e.second.c_str(), nullptr, 0) & 0x7FF);
    for (unsigned id = 1; id <= 127; ++id)
      if (id != master_id && !entries.count(id) && !used.count(0x80 + id)) entries[id] = hex(0x80 + id, 8);
    out << "NrOfEntries=" << entries.size() << "\n";
    for (const auto& e : entries) out << e.first << "=" << e.second << "\n";
    done = true;
  };
  for (std::string line; std::getline(in, line);) {
    std::string bare = line;
    if (!bare.empty() && bare.back() == '\r') bare.pop_back();
    if (!bare.empty() && bare[0] == '[') {
      if (in_section) {
        flush();
        out << "\n";
      }
      in_section = bare == "[1028Value]";
      out << line << "\n";
      continue;
    }
    if (in_section) {
      size_t eq = bare.find('=');
      if (eq != std::string::npos && bare.compare(0, eq, "NrOfEntries") != 0)
        entries[static_cast<unsigned>(std::strtoul(bare.substr(0, eq).c_str(), nullptr, 0))] = bare.substr(eq + 1);
      continue;
    }
    out << line << "\n";
  }
  if (in_section) flush();
  // A master DCF with no 1028 at all is left alone (and has no EMCY consumer).
  return done ? write_file(master_dcf, out.str()) : true;
}

// dcfgen's warnings ("path:line: UserWarning: node_5: ...") as log lines
// naming the node the way the plugin does.
void log_dcfgen_warnings(const Config& cfg, const std::string& log_path) {
  std::string log;
  if (!read_file(log_path, log)) return;
  std::istringstream in(log);
  for (std::string line; std::getline(in, line);) {
    size_t at = line.find("Warning: ");
    if (at == std::string::npos) continue;
    std::string msg = line.substr(at + 9);
    // dcf.lint's findings: run_eds_lint has already judged and logged them.
    bool linted = false;
    for (const auto& n : cfg.nodes)
      for (const auto& f : n.lint_findings) linted |= msg == f;
    if (linted) continue;
    bool dropped = false;
    for (const auto& n : cfg.nodes) {
      std::string key = "node_" + std::to_string(n.node_id);
      if (msg.compare(0, key.size(), key) == 0 && (msg.size() == key.size() || !isdigit((unsigned char)msg[key.size()]))) {
        msg = n.label() + msg.substr(key.size());
        // A write to a read-only PDO communication sub-index is dropped from
        // the node's configuration (generate_device_config), so dcfgen's
        // warning about it does not apply.
        unsigned idx = 0, sub = 0;
        size_t w = msg.find("no write access for sub-object 0x");
        dropped = w != std::string::npos && std::sscanf(msg.c_str() + w + 31, "0x%x/%u", &idx, &sub) == 2 &&
                  n.ro_pdo_comm.count({static_cast<uint16_t>(idx), static_cast<uint8_t>(sub)});
        break;
      }
    }
    if (!dropped) log_warn("dcfgen: %s", msg.c_str());
  }
}

// Lely skips a node's configuration download when the master's expected
// configuration date and time (1F26/1F27, sub = node ID) equal the node's
// 0x1020; dcfgen's master DCF has neither, so they are added here, all 0
// (no check). set_config_stamps() fills in the nodes with config_check.
bool add_config_check_objects(const std::string& master_dcf) {
  std::string text;
  if (!read_file(master_dcf, text)) return false;
  if (text.find("[1F26]") != std::string::npos) return true;
  std::istringstream in(text);
  std::ostringstream out;
  bool in_list = false, done = false;
  unsigned count = 0;
  auto add = [&] {
    out << "SupportedObjects=" << count + 2 << "\n" << count + 1 << "=0x1F26\n" << count + 2 << "=0x1F27\n";
    done = true;
  };
  std::string rest;
  for (std::string line; std::getline(in, line);) {
    std::string bare = line;
    if (!bare.empty() && bare.back() == '\r') bare.pop_back();
    if (!bare.empty() && bare[0] == '[') {
      if (in_list) {
        add();
        out << rest << "\n";
        rest.clear();
      }
      in_list = bare == "[OptionalObjects]";
      out << line << "\n";
      continue;
    }
    if (in_list) {
      if (bare.compare(0, 17, "SupportedObjects=") == 0)
        count = static_cast<unsigned>(std::strtoul(bare.c_str() + 17, nullptr, 0));
      else if (!bare.empty())
        rest += line + "\n";
      continue;
    }
    out << line << "\n";
  }
  if (in_list) {
    add();
    out << rest;
  }
  if (!done) return false;
  for (const char* obj : {"1F26]\nParameterName=Expected configuration date", "1F27]\nParameterName=Expected configuration time"})
    out << "\n[" << obj << "\nObjectType=0x08\nDataType=0x0007\nAccessType=rw\nCompactSubObj=127\n";
  return write_file(master_dcf, out.str());
}

// The expected configuration date and time of each node with config_check, as
// [1F26Value]/[1F27Value] in the master DCF. They are in the DCF rather than
// set at run time because the master's NMT reset restores 0x1000-0x1FFF from
// the DCF. Replaced on every start, since they follow the SDO list.
bool set_config_stamps(const std::string& master_dcf,
                       const std::map<unsigned, std::pair<uint32_t, uint32_t>>& stamps) {
  std::string text;
  if (!read_file(master_dcf, text)) return false;
  std::istringstream in(text);
  std::ostringstream out;
  bool skip = false;
  for (std::string line; std::getline(in, line);) {
    std::string bare = line;
    if (!bare.empty() && bare.back() == '\r') bare.pop_back();
    if (!bare.empty() && bare[0] == '[') skip = bare == "[1F26Value]" || bare == "[1F27Value]";
    if (!skip) out << line << "\n";
  }
  std::string body = out.str();
  while (body.size() >= 2 && body[body.size() - 1] == '\n' && body[body.size() - 2] == '\n') body.pop_back();
  for (int half = 0; half < 2; ++half) {
    body += std::string("\n[") + (half ? "1F27" : "1F26") + "Value]\nNrOfEntries=" + std::to_string(stamps.size()) + "\n";
    for (const auto& s : stamps)
      body += std::to_string(s.first) + "=" + hex(half ? s.second.second : s.second.first, 8) + "\n";
  }
  return body == text || write_file(master_dcf, body);
}

// Receive timeouts of node TPDOs (canopen-pdo-io "Receive timeout setting"):
// sub-index 5 (the deadline) of the master RPDO that receives each one, found
// by its COB-ID, as a ParameterValue in the master DCF. dcfgen's own
// event_deadline key fails without an event timer, and a value set at run
// time would be lost at the master's NMT reset. `deadlines` maps COB-ID ->
// milliseconds; `missing` gets the COB-IDs no master RPDO receives.
bool set_rpdo_deadlines(const std::string& master_dcf, const std::map<uint32_t, unsigned>& deadlines,
                        std::vector<uint32_t>& missing) {
  std::string text;
  if (!read_file(master_dcf, text)) return false;
  std::vector<std::string> lines;
  {
    std::istringstream in(text);
    for (std::string line; std::getline(in, line);) lines.push_back(line);
  }
  auto bare = [](std::string l) {
    if (!l.empty() && l.back() == '\r') l.pop_back();
    return l;
  };
  // The COB-ID of every master RPDO: [14xxsub1], ParameterValue over DefaultValue.
  std::map<unsigned, uint32_t> cob_of;  // RPDO communication index -> COB-ID
  std::string section;
  std::map<unsigned, std::pair<bool, uint32_t>> found;  // index -> (from ParameterValue, value)
  for (const auto& raw : lines) {
    std::string l = bare(raw);
    if (!l.empty() && l[0] == '[') {
      section = l;
      continue;
    }
    if (section.size() != 10 || section.compare(5, 5, "sub1]") != 0) continue;
    unsigned idx = static_cast<unsigned>(std::strtoul(section.substr(1, 4).c_str(), nullptr, 16));
    if (idx < 0x1400 || idx > 0x15FF) continue;
    bool param = l.compare(0, 15, "ParameterValue=") == 0;
    if (!param && l.compare(0, 13, "DefaultValue=") != 0) continue;
    uint32_t v = static_cast<uint32_t>(std::strtoul(l.c_str() + (param ? 15 : 13), nullptr, 0));
    auto it = found.find(idx);
    if (it == found.end() || (param && !it->second.first)) found[idx] = {param, v};
  }
  for (const auto& f : found)
    if (!(f.second.second & 0x80000000u)) cob_of[f.first] = f.second.second & 0x7FF;
  std::map<unsigned, unsigned> want;  // index -> ms
  for (const auto& d : deadlines) {
    bool hit = false;
    for (const auto& c : cob_of)
      if (c.second == d.first) want[c.first] = d.second, hit = true;
    if (!hit) missing.push_back(d.first);
  }
  if (want.empty()) return true;
  // Rewrite [14xxsub5]: drop its ParameterValue, add the deadline after it.
  std::ostringstream out;
  for (size_t i = 0; i < lines.size(); ++i) {
    std::string l = bare(lines[i]);
    unsigned idx = 0;
    if (l.size() == 10 && l[0] == '[' && l.compare(5, 5, "sub5]") == 0)
      idx = static_cast<unsigned>(std::strtoul(l.substr(1, 4).c_str(), nullptr, 16));
    auto w = want.find(idx);
    if (w == want.end()) {
      out << lines[i] << "\n";
      continue;
    }
    out << lines[i] << "\n";
    size_t j = i + 1;
    std::vector<std::string> body;
    for (; j < lines.size() && (bare(lines[j]).empty() || bare(lines[j])[0] != '['); ++j)
      if (bare(lines[j]).compare(0, 15, "ParameterValue=") != 0) body.push_back(lines[j]);
    while (!body.empty() && bare(body.back()).empty()) body.pop_back();
    for (const auto& b : body) out << b << "\n";
    out << "ParameterValue=" << w->second << "\n";
    if (j < lines.size()) out << "\n";
    want.erase(w);
    i = j - 1;
  }
  for (const auto& w : want) missing.push_back(cob_of[w.first]);  // a master RPDO without sub-index 5
  return write_file(master_dcf, out.str());
}

}  // namespace

std::pair<uint32_t, uint32_t> config_stamp(const std::vector<SdoWrite>& sdos, unsigned store_subindex) {
  uint64_t h = fnv1a(0xcbf29ce484222325ULL, "config stamp 1");
  for (const auto& w : sdos) {
    std::string item;
    item += static_cast<char>(w.index & 0xFF);
    item += static_cast<char>(w.index >> 8);
    item += static_cast<char>(w.subindex);
    item += static_cast<char>(w.data.size());
    item.append(w.data.begin(), w.data.end());
    h = fnv1a(h, item);
  }
  h = fnv1a(h, "store " + std::to_string(store_subindex));
  uint32_t date = static_cast<uint32_t>(h >> 32), time = static_cast<uint32_t>(h);
  return {date ? date : 1, time ? time : 1};
}

bool generate_device_config(const Config& cfg, const std::string& dcfgen, GeneratedConfig& out,
                            std::vector<std::string>& errors) {
  out = GeneratedConfig();
  out.work_dir = cfg.work_dir.empty() ? cfg.config_dir + "/.canworks" : cfg.work_dir;
  out.master_dcf = out.work_dir + "/master.dcf";
  if (!mkdir_p(out.work_dir)) {
    errors.push_back("cannot create " + out.work_dir + ": " + std::strerror(errno));
    return false;
  }

  // Node EDS paths are the prepared copies run_eds_lint made, where needed.
  std::string yaml = make_dcfgen_yaml(cfg, out.work_dir);
  // Bumped whenever the plugin post-processes dcfgen's output differently, so
  // output cached by an older plugin is regenerated.
  uint64_t h = fnv1a(0xcbf29ce484222325ULL, "post-processing 5: prepared EDS copies, dcfgen --no-strict");
  h = fnv1a(h, yaml);
  h = fnv1a(h, startup_sdo_key(cfg));
  for (const auto& n : cfg.nodes)  // the master DCF gets 1F26/1F27 when any node checks
    if (n.config_check) h = fnv1a(h, "config_check " + std::to_string(n.node_id));
  std::map<uint32_t, unsigned> deadlines;  // and the RPDO deadlines
  for (const auto& n : cfg.nodes)
    for (const auto& p : n.tx_pdos)
      if (p.has_timeout && p.timeout_ms) deadlines[n.tpdo_cob_id(p)] = p.timeout_ms;
  for (const auto& d : deadlines) h = fnv1a(h, "rpdo deadline " + std::to_string(d.first) + "=" + std::to_string(d.second));
  for (const auto& n : cfg.nodes) {
    std::string eds;
    read_file(n.eds_path, eds);
    h = fnv1a(h, n.eds_path);
    h = fnv1a(h, eds);
  }
  char hash[32];
  std::snprintf(hash, sizeof(hash), "%016llx", (unsigned long long)h);

  std::string yaml_path = out.work_dir + "/dcfgen.yml";
  std::string hash_path = out.work_dir + "/inputs.hash";
  std::string old_hash;
  read_file(hash_path, old_hash);
  if (old_hash == hash && file_exists(out.master_dcf)) {
    out.reused = true;
  } else {
    // Clear old output first so a failed run cannot leave stale files behind.
    unlink(hash_path.c_str());
    unlink(out.master_dcf.c_str());
    // dcfgen writes master.bin only when the master has something to check
    // (identity, serial number), so one left from an earlier config would
    // otherwise still be applied.
    unlink((out.work_dir + "/master.bin").c_str());
    for (const auto& n : cfg.nodes) unlink((out.work_dir + "/node_" + std::to_string(n.node_id) + ".bin").c_str());
    if (!write_file(yaml_path, yaml)) {
      errors.push_back("cannot write " + yaml_path);
      return false;
    }
    if (!run_dcfgen(dcfgen, cfg, out.work_dir, yaml_path, errors)) return false;
    if (!strip_upload_files(out.master_dcf)) {
      errors.push_back("dcfgen produced no " + out.master_dcf);
      return false;
    }
    if (!add_emcy_consumers(out.master_dcf, cfg.master.node_id)) {
      errors.push_back("cannot update " + out.master_dcf);
      return false;
    }
    bool any_check = false;
    for (const auto& n : cfg.nodes) any_check |= n.config_check;
    if (any_check && !add_config_check_objects(out.master_dcf)) {
      errors.push_back("cannot add 1F26/1F27 to " + out.master_dcf);
      return false;
    }
    std::vector<uint32_t> missing;
    if (!deadlines.empty() && !set_rpdo_deadlines(out.master_dcf, deadlines, missing)) {
      errors.push_back("cannot write the receive timeouts to " + out.master_dcf);
      return false;
    }
    for (uint32_t cob : missing) {
      char buf[160];
      std::snprintf(buf, sizeof(buf), "dcfgen made no master RPDO with a deadline for COB-ID 0x%03X; its timeout_ms "
                    "cannot be set", cob);
      errors.push_back(buf);
    }
    if (!missing.empty()) return false;
    write_file(hash_path, hash);
  }
  // Also on a reused run, so the warnings show at every start.
  log_dcfgen_warnings(cfg, out.work_dir + "/dcfgen.log");

  for (const auto& n : cfg.nodes) {
    std::string bin = out.work_dir + "/node_" + std::to_string(n.node_id) + ".bin";
    std::vector<SdoWrite> sdos;
    if (file_exists(bin)) {
      std::string why;
      if (!read_concise_dcf(bin, sdos, why)) {
        errors.push_back(why);
        return false;
      }
    }
    // dcfgen switches every configured PDO off and on again through its
    // COB-ID, also when the COB-ID does not change; a node with read-only
    // PDO communication parameters refuses that. The EDS checks made sure
    // the configured values equal the read-only ones, so these writes are
    // dropped.
    for (auto it = sdos.begin(); it != sdos.end();) {
      if (n.ro_pdo_comm.count({it->index, it->subindex}))
        it = sdos.erase(it);
      else
        ++it;
    }
    // dcfgen leaves out a PDO parameter the config sets explicitly when it
    // equals the EDS default, but the node's real value can differ (a device
    // that runs with another transmission type than its EDS gives). Explicit
    // values are written: right after the write that switches the PDO off,
    // where dcfgen puts its own parameter writes.
    add_explicit_pdo_writes(n, sdos);
    // Without heartbeat_consumer the node keeps the 0x1016 entries its EDS
    // gives: dcfgen would clear an entry that watches the master.
    if (!n.has_heartbeat_consumer) {
      uint32_t cleared = uint32_t(cfg.master.node_id) << 16;
      for (auto it = sdos.begin(); it != sdos.end();) {
        uint32_t v = 0;
        for (size_t b = 0; b < it->data.size() && b < 4; ++b) v |= uint32_t(it->data[b]) << (8 * b);
        if (it->index == 0x1016 && it->data.size() == 4 && v == cleared)
          it = sdos.erase(it);
        else
          ++it;
      }
    }
    // The node's TIME COB-ID, unless the EDS already has the value.
    if (n.has_time_cob_id) {
      uint64_t eds_value;
      if (!eds_sub_value(n, 0x1012, 0, eds_value)) {
        log_warn("%s: time_cob_id not written: the EDS (%s) has no object 0x1012", n.label().c_str(),
                 n.eds_path.c_str());
      } else if (eds_value != n.time_cob_id) {
        SdoWrite w;
        w.index = 0x1012;
        w.subindex = 0;
        for (int b = 0; b < 4; ++b) w.data.push_back(static_cast<uint8_t>(n.time_cob_id >> (8 * b)));
        sdos.push_back(std::move(w));
      }
    }
    // RPDO event timers (deadlines), unless the EDS already has the value.
    for (const auto& p : n.rx_pdos) {
      if (!p.has_event_timer) continue;
      uint16_t idx = static_cast<uint16_t>(0x1400 + p.number - 1);
      uint64_t eds_value;
      if (eds_sub_value(n, idx, 5, eds_value) && eds_value == p.event_timer_ms) continue;
      SdoWrite w;
      w.index = idx;
      w.subindex = 5;
      w.data = {static_cast<uint8_t>(p.event_timer_ms & 0xFF), static_cast<uint8_t>(p.event_timer_ms >> 8)};
      sdos.push_back(std::move(w));
    }
    // A cyclic axis's interpolation time period, before the startup SDOs
    // (canopen-cia402-axis "Interpolation time period").
    uint8_t ip_value;
    int8_t ip_exponent;
    if (n.interpolation_write_us && interpolation_code(n.interpolation_write_us, ip_value, ip_exponent)) {
      for (uint8_t sub : {1, 2}) {
        SdoWrite w;
        w.index = 0x60C2;
        w.subindex = sub;
        w.data = {sub == 1 ? ip_value : static_cast<uint8_t>(ip_exponent)};
        sdos.push_back(std::move(w));
      }
    }
    // Startup SDOs go last: after the PDO parameters dcfgen wrote, before the
    // NMT start that follows the configuration downloads (design D7).
    for (const auto& s : n.sdos) {
      SdoWrite w;
      w.index = s.index;
      w.subindex = s.subindex;
      w.data = s.data;
      sdos.push_back(std::move(w));
    }
    // Configuration check: the stamp goes to 0x1020 after everything else,
    // then the optional save (0x1010, "save"), which also keeps 0x1020.
    if (n.config_check) {
      auto stamp = config_stamp(sdos, n.has_store_configuration ? n.store_configuration : 0);
      out.config_stamps[n.node_id] = stamp;
      for (uint8_t sub : {1, 2}) {
        uint32_t v = sub == 1 ? stamp.first : stamp.second;
        SdoWrite w;
        w.index = 0x1020;
        w.subindex = sub;
        for (int b = 0; b < 4; ++b) w.data.push_back(static_cast<uint8_t>(v >> (8 * b)));
        sdos.push_back(std::move(w));
      }
      if (n.has_store_configuration) {
        SdoWrite w;
        w.index = 0x1010;
        w.subindex = static_cast<uint8_t>(n.store_configuration);
        w.data = {'s', 'a', 'v', 'e'};  // 0x65766173
        sdos.push_back(std::move(w));
      }
    }
    out.slave_sdos[n.node_id] = std::move(sdos);
  }
  if (!out.config_stamps.empty() && !set_config_stamps(out.master_dcf, out.config_stamps)) {
    errors.push_back("cannot write the configuration stamps to " + out.master_dcf);
    return false;
  }
  return true;
}

}  // namespace canopen_plugin
