// Unit tests: IEC locations, config validation (every rejection scenario in
// the canopen-master-bringup and canopen-pdo-io specs), EDS checks, dcfgen
// generation and caching, and the PDO <-> PLC image binding.

#include <cstdio>
#include <cstring>
#include <chrono>
#include <cstdlib>
#include <fstream>
#include <sstream>
#include <string>
#include <sys/stat.h>
#include <unistd.h>

#include <cerrno>
#include <linux/can/netlink.h>
#include <linux/if_link.h>
#include <linux/netlink.h>
#include <linux/rtnetlink.h>
#include <map>
#include <set>
#include <vector>
#include <net/if.h>

#include <lely/co/dcf.h>
#include <lely/co/dev.h>

#include "cJSON.h"
#include "bus_monitor.h"
#include "can_adapter.h"
#include "check.hpp"
#include "config.h"
#include "dcf_gen.h"
#include "diag.h"
#include "sim_trace.h"

#include <lely/can/msg.h>
#include "eds_check.h"
#include "eds_lint.h"
#include "fake_runtime.hpp"
#include "iec_location.h"
#include "plc_api.h"
#include "log.h"
#include "process_image.h"
#include "runtime_version.h"
#include "sha256.h"
#include "trace_capture.h"

#include <arpa/inet.h>
#include <atomic>
#include <fcntl.h>
#include <mutex>
#include <netinet/in.h>
#include <poll.h>
#include <sys/socket.h>
#include <thread>

using namespace canopen_plugin;

#ifndef PINGPONG_DIR
#error PINGPONG_DIR must point at config/pingpong
#endif
#ifndef FIXTURES_DIR
#error FIXTURES_DIR must point at test/fixtures
#endif

namespace {

std::string read(const std::string& path) {
  std::ifstream in(path);
  std::stringstream ss;
  ss << in.rdbuf();
  return ss.str();
}

void write(const std::string& path, const std::string& data) {
  std::ofstream out(path);
  out << data;
}

std::string tmpdir() {
  char tmpl[] = "/tmp/canopen-test-XXXXXX";
  return mkdtemp(tmpl);
}

bool has_error(const std::vector<std::string>& errors, const std::string& needle) {
  for (const auto& e : errors)
    if (e.find(needle) != std::string::npos) return true;
  return false;
}

std::string join(const std::vector<std::string>& v) {
  std::string s;
  for (const auto& e : v) s += "\n    " + e;
  return s;
}

// A valid ping-pong style config; tests patch it with string replacement.
const char* kValid = R"({
  "schema_version": 1,
  "adapter": { "type": "socketcan", "interface": "vcan0", "bitrate": 125000 },
  "master": { "node_id": 1, "sync_period_us": 10000 },
  "nodes": [
    {
      "node_id": 2,
      "name": "pingpong",
      "eds": "cpp-slave.eds",
      "heartbeat_ms": 500,
      "status_location": "%IX10.0",
      "tx_pdos": [ { "entries": [ { "index": "0x4001", "subindex": 0, "type": "UNSIGNED32", "iec_location": "%ID100" } ] } ],
      "rx_pdos": [ { "entries": [ { "index": "0x4000", "subindex": 0, "type": "UNSIGNED32", "iec_location": "%QD100" } ] } ]
    }
  ]
})";

std::string replace(std::string s, const std::string& from, const std::string& to) {
  size_t pos = s.find(from);
  if (pos == std::string::npos) {
    std::printf("  test setup: \"%s\" not found in config\n", from.c_str());
    ++check::failures();
    return s;
  }
  return s.replace(pos, from.size(), to);
}

bool parse(const std::string& json, Config& cfg, std::vector<std::string>& errors) {
  return parse_config(json, std::string(PINGPONG_DIR) + "/canopen_config.json", ImageLimits(), cfg, errors);
}

void silent(LogLevel, const char*) {}

}  // namespace

// ---------------------------------------------------------------------------
// IEC locations

TEST(iec_parse_valid) {
  IecLocation l;
  std::string why;
  CHECK(parse_iec_location("%IX10.3", l, why));
  CHECK(l.area == IecArea::Input && l.size == IecSize::X && l.index == 10 && l.bit == 3);
  CHECK(parse_iec_location("%QW100", l, why));
  CHECK(l.area == IecArea::Output && l.size == IecSize::W && l.index == 100);
  CHECK(parse_iec_location("%id7", l, why));
  CHECK(l.size == IecSize::D && l.str() == "%ID7");
  CHECK(parse_iec_location("%QL0", l, why) && l.size == IecSize::L);
  CHECK(parse_iec_location("%IB5", l, why) && l.size == IecSize::B);
}

TEST(iec_parse_invalid) {
  IecLocation l;
  std::string why;
  CHECK(!parse_iec_location("IX10.0", l, why));
  CHECK(!parse_iec_location("%MW10", l, why));
  CHECK(!parse_iec_location("%IX10", l, why));
  CHECK(!parse_iec_location("%IX10.8", l, why));
  CHECK(!parse_iec_location("%IZ3", l, why));
  CHECK(!parse_iec_location("%IW", l, why));
  CHECK(!parse_iec_location("%IW10x", l, why));
}

TEST(iec_overlap) {
  IecLocation a, b;
  std::string why;
  parse_iec_location("%IX1.0", a, why);
  parse_iec_location("%IX1.0", b, why);
  CHECK(a.overlaps(b));
  parse_iec_location("%IX1.1", b, why);
  CHECK(!a.overlaps(b));
  parse_iec_location("%IW1", a, why);
  parse_iec_location("%IW1", b, why);
  CHECK(a.overlaps(b));
  parse_iec_location("%ID1", b, why);  // separate table in the OpenPLC image
  CHECK(!a.overlaps(b));
  parse_iec_location("%QW1", b, why);
  CHECK(!a.overlaps(b));
}

TEST(co_type_sizes) {
  CoType t;
  CHECK(parse_co_type("unsigned16", t) && t == CoType::UNSIGNED16);
  CHECK(co_type_fits(CoType::UNSIGNED16, IecSize::W));
  CHECK(co_type_fits(CoType::BOOLEAN, IecSize::X));
  CHECK(co_type_fits(CoType::REAL32, IecSize::D));
  CHECK(co_type_fits(CoType::INTEGER64, IecSize::L));
  CHECK(!co_type_fits(CoType::UNSIGNED32, IecSize::W));
  CHECK(!parse_co_type("VISIBLE_STRING", t));
}

// ---------------------------------------------------------------------------
// Config: valid

TEST(config_valid_loads) {
  Config cfg;
  std::vector<std::string> errors;
  CHECK_MSG(parse(kValid, cfg, errors), join(errors));
  CHECK(cfg.warnings.empty());
  CHECK(cfg.schema_version == 1);
  CHECK(cfg.adapter.type == "socketcan" && cfg.adapter.interface == "vcan0");
  CHECK(cfg.adapter.bitrate == 125000 && cfg.adapter.configure_link && !cfg.adapter.has_restart_ms);
  CHECK(cfg.master.node_id == 1);
  CHECK(cfg.master.sync_period_us == 10000);
  CHECK(cfg.nodes.size() == 1);
  const NodeConfig& n = cfg.nodes[0];
  CHECK(n.node_id == 2 && n.name == "pingpong");
  CHECK(n.eds_path == std::string(PINGPONG_DIR) + "/cpp-slave.eds");
  CHECK(n.heartbeat_ms == 500 && n.heartbeat_timeout_ms == 1500);
  CHECK(n.has_status_location && n.status_location.str() == "%IX10.0");
  CHECK(n.tx_pdos.size() == 1 && n.tx_pdos[0].number == 1 && n.tx_pdos[0].entries.size() == 1);
  CHECK(n.tx_pdos[0].entries[0].index == 0x4001);
  CHECK(n.tpdo_cob_id(n.tx_pdos[0]) == 0x182);
  CHECK(n.rpdo_cob_id(n.rx_pdos[0]) == 0x202);
}

TEST(config_example_file_validates) {
  // config/pingpong/canopen_config.json is the documented example (docs/config.md).
  Config cfg;
  std::vector<std::string> errors;
  CHECK_MSG(load_config(std::string(PINGPONG_DIR) + "/canopen_config.json", ImageLimits(), cfg, errors) &&
                check_eds_files(cfg, errors),
            join(errors));
}

// ---------------------------------------------------------------------------
// Config: canopen-master-bringup rejections

TEST(config_missing_file) {
  Config cfg;
  std::vector<std::string> errors;
  CHECK(!load_config("/nonexistent/canopen_config.json", ImageLimits(), cfg, errors));
  CHECK(has_error(errors, "/nonexistent/canopen_config.json"));
}

TEST(config_malformed_json) {
  Config cfg;
  std::vector<std::string> errors;
  CHECK(!parse("{ \"adapter\": ", cfg, errors));
  CHECK(has_error(errors, "canopen_config.json: not valid JSON"));
}

TEST(config_missing_fields) {
  const char* fields[] = {"\"interface\": \"vcan0\", ", ", \"bitrate\": 125000"};
  for (const char* f : fields) {
    Config cfg;
    std::vector<std::string> errors;
    CHECK(!parse(replace(kValid, f, ""), cfg, errors));
    std::string fs(f);
    size_t q = fs.find('"');
    std::string name = fs.substr(q + 1, fs.find('"', q + 1) - q - 1);
    CHECK_MSG(has_error(errors, "missing required field '" + name + "'"), join(errors));
  }
  Config cfg;
  std::vector<std::string> errors;
  CHECK(!parse(replace(kValid, "\"eds\": \"cpp-slave.eds\",", ""), cfg, errors));
  CHECK_MSG(has_error(errors, "nodes[0]: missing required field 'eds'"), join(errors));
  errors.clear();
  CHECK(!parse(replace(kValid, "\"type\": \"UNSIGNED32\", \"iec_location\": \"%ID100\"", "\"type\": \"UNSIGNED32\""),
               cfg, errors));
  CHECK_MSG(has_error(errors, "missing required field 'iec_location'"), join(errors));
}

TEST(config_invalid_field) {
  Config cfg;
  std::vector<std::string> errors;
  CHECK(!parse(replace(kValid, "\"bitrate\": 125000", "\"bitrate\": 123456"), cfg, errors));
  CHECK_MSG(has_error(errors, "adapter: field 'bitrate' must be a CiA 301 bit rate"), join(errors));
}

TEST(config_duplicate_node_id) {
  std::string two = replace(kValid, "\n  ]\n}", R"(,
    { "node_id": 2, "eds": "cpp-slave.eds",
      "tx_pdos": [ { "entries": [ { "index": "0x4001", "type": "UNSIGNED32", "iec_location": "%ID200" } ] } ] }
  ]
})");
  Config cfg;
  std::vector<std::string> errors;
  CHECK(!parse(two, cfg, errors));
  CHECK_MSG(has_error(errors, "node ID 2 is used by more than one slave"), join(errors));
}

TEST(config_node_id_out_of_range) {
  Config cfg;
  std::vector<std::string> errors;
  CHECK(!parse(replace(kValid, "\"node_id\": 2", "\"node_id\": 128"), cfg, errors));
  CHECK_MSG(has_error(errors, "node ID 128 is out of range"), join(errors));
  errors.clear();
  CHECK(!parse(replace(kValid, "\"node_id\": 2", "\"node_id\": 0"), cfg, errors));
  CHECK_MSG(has_error(errors, "node ID 0 is out of range"), join(errors));
}

TEST(config_node_id_is_master) {
  Config cfg;
  std::vector<std::string> errors;
  CHECK(!parse(replace(kValid, "\"node_id\": 2", "\"node_id\": 1"), cfg, errors));
  CHECK_MSG(has_error(errors, "node ID 1 is the master's node ID"), join(errors));
}

// ---------------------------------------------------------------------------
// Config: canopen-pdo-io rejections

TEST(config_direction_mismatch) {
  Config cfg;
  std::vector<std::string> errors;
  CHECK(!parse(replace(kValid, "%ID100", "%QD50"), cfg, errors));
  CHECK_MSG(has_error(errors, "node 2 (pingpong), object 0x4001:0") && has_error(errors, "%QD50"), join(errors));
  errors.clear();
  CHECK(!parse(replace(kValid, "%QD100", "%ID50"), cfg, errors));
  CHECK_MSG(has_error(errors, "object 0x4000:0") && has_error(errors, "%ID50"), join(errors));
}

TEST(config_size_mismatch) {
  Config cfg;
  std::vector<std::string> errors;
  CHECK(!parse(replace(kValid, "%ID100", "%IW100"), cfg, errors));
  CHECK_MSG(has_error(errors, "node 2 (pingpong), object 0x4001:0: type UNSIGNED32 (32 bit) does not fit location %IW100"),
            join(errors));
}

TEST(config_overlap) {
  Config cfg;
  std::vector<std::string> errors;
  std::string dup = replace(kValid,
                            R"({ "index": "0x4001", "subindex": 0, "type": "UNSIGNED32", "iec_location": "%ID100" })",
                            R"({ "index": "0x4001", "subindex": 0, "type": "UNSIGNED32", "iec_location": "%ID100" },
                               { "index": "0x4000", "subindex": 0, "type": "UNSIGNED32", "iec_location": "%ID100" })");
  CHECK(!parse(dup, cfg, errors));
  CHECK_MSG(has_error(errors, "object 0x4001:0 and node 2 (pingpong) TPDO 1 object 0x4000:0 both map to %ID100"),
            join(errors));
}

TEST(config_status_overlaps_entry) {
  std::string s = replace(kValid, "\"%IX10.0\"", "\"%IX3.1\"");
  s = replace(s, R"("type": "UNSIGNED32", "iec_location": "%ID100" })",
              R"("type": "UNSIGNED32", "iec_location": "%ID100" }, { "index": "0x1001", "type": "BOOLEAN", "iec_location": "%IX3.1" })");
  Config cfg;
  std::vector<std::string> errors;
  CHECK(!parse(s, cfg, errors));
  CHECK_MSG(has_error(errors, "status_location and") && has_error(errors, "%IX3.1"), join(errors));
}

TEST(config_location_outside_image) {
  Config cfg;
  std::vector<std::string> errors;
  CHECK(!parse(replace(kValid, "%ID100", "%ID1024"), cfg, errors));
  CHECK_MSG(has_error(errors, "iec_location %ID1024 lies outside the runtime I/O image"), join(errors));
  CHECK_MSG(has_error(errors, "nodes[0]: tx_pdos[0]: entries[0]"), join(errors));
}

TEST(config_pdo_too_long) {
  std::string s = replace(kValid, R"("type": "UNSIGNED32", "iec_location": "%ID100" })",
                          R"("type": "UNSIGNED32", "iec_location": "%ID100" },
                             { "index": "0x4001", "type": "UNSIGNED64", "iec_location": "%IL1" })");
  Config cfg;
  std::vector<std::string> errors;
  CHECK(!parse(s, cfg, errors));
  CHECK_MSG(has_error(errors, "at most 64"), join(errors));
}

TEST(config_status_must_be_input_bit) {
  Config cfg;
  std::vector<std::string> errors;
  CHECK(!parse(replace(kValid, "\"%IX10.0\"", "\"%QX10.0\""), cfg, errors));
  CHECK_MSG(has_error(errors, "status_location must be an input bit"), join(errors));
}

TEST(config_state_byte) {
  Config cfg;
  std::vector<std::string> errors;
  CHECK_MSG(parse(replace(kValid, "\"status_location\": \"%IX10.0\",",
                          "\"status_location\": \"%IX10.0\", \"state_location\": \"%IB20\","),
                  cfg, errors), join(errors));
  CHECK(cfg.nodes[0].has_state_location && cfg.nodes[0].state_location.str() == "%IB20");
}

TEST(config_state_must_be_input_byte) {
  for (const char* bad : {"%IW20", "%QB20", "%IX20.0"}) {
    Config cfg;
    std::vector<std::string> errors;
    CHECK(!parse(replace(kValid, "\"status_location\": \"%IX10.0\",",
                         std::string("\"state_location\": \"") + bad + "\","),
                 cfg, errors));
    CHECK_MSG(has_error(errors, "state_location must be an input byte"), join(errors));
  }
}

TEST(config_state_overlaps_entry) {
  std::string s = replace(kValid, "\"status_location\": \"%IX10.0\",",
                          "\"status_location\": \"%IX10.0\", \"state_location\": \"%IB20\",");
  s = replace(s, R"("type": "UNSIGNED32", "iec_location": "%ID100" })", R"("type": "UNSIGNED8", "iec_location": "%IB20" })");
  Config cfg;
  std::vector<std::string> errors;
  CHECK(!parse(s, cfg, errors));
  CHECK_MSG(has_error(errors, "state_location and"), join(errors));
}

TEST(config_emcy_fields) {
  Config cfg;
  std::vector<std::string> errors;
  CHECK_MSG(parse(replace(kValid, "\"status_location\": \"%IX10.0\",",
                          "\"status_location\": \"%IX10.0\", \"emcy_code_location\": \"%IW30\", "
                          "\"error_register_location\": \"%IB31\","),
                  cfg, errors), join(errors));
  CHECK(cfg.nodes[0].has_emcy_code_location && cfg.nodes[0].emcy_code_location.str() == "%IW30");
  CHECK(cfg.nodes[0].has_error_register_location && cfg.nodes[0].error_register_location.str() == "%IB31");
  CHECK(cfg.warnings.empty());
}

TEST(config_emcy_fields_wrong_size) {
  for (const char* bad : {"%IB30", "%QW30", "%ID30"}) {
    Config cfg;
    std::vector<std::string> errors;
    CHECK(!parse(replace(kValid, "\"status_location\": \"%IX10.0\",",
                         std::string("\"emcy_code_location\": \"") + bad + "\","),
                 cfg, errors));
    CHECK_MSG(has_error(errors, "emcy_code_location must be an input word"), join(errors));
  }
  for (const char* bad : {"%IW31", "%QB31", "%IX31.0"}) {
    Config cfg;
    std::vector<std::string> errors;
    CHECK(!parse(replace(kValid, "\"status_location\": \"%IX10.0\",",
                         std::string("\"error_register_location\": \"") + bad + "\","),
                 cfg, errors));
    CHECK_MSG(has_error(errors, "error_register_location must be an input byte"), join(errors));
  }
}

TEST(config_emcy_fields_overlap) {
  // The EMCY code word and a PDO entry word.
  std::string s = replace(kValid, "\"status_location\": \"%IX10.0\",",
                          "\"status_location\": \"%IX10.0\", \"emcy_code_location\": \"%IW30\",");
  s = replace(s, R"("type": "UNSIGNED32", "iec_location": "%ID100" })", R"("type": "UNSIGNED16", "iec_location": "%IW30" })");
  Config cfg;
  std::vector<std::string> errors;
  CHECK(!parse(s, cfg, errors));
  CHECK_MSG(has_error(errors, "emcy_code_location and"), join(errors));
  // The error register byte and the state byte.
  s = replace(kValid, "\"status_location\": \"%IX10.0\",",
              "\"state_location\": \"%IB20\", \"error_register_location\": \"%IB20\",");
  errors.clear();
  CHECK(!parse(s, cfg, errors));
  CHECK_MSG(has_error(errors, "state_location and") && has_error(errors, "error_register_location"), join(errors));
}

// ---------------------------------------------------------------------------
// Bus diagnostic fields (canopen-bus-diagnostics)

const char* kBusFields = R"("node_id": 1, "sync_period_us": 10000, "bus_state_location": "%IB100",
    "tx_error_count_location": "%IB101", "rx_error_count_location": "%IB102", "bus_off_count_location": "%IW100")";

TEST(config_bus_fields) {
  Config cfg;
  std::vector<std::string> errors;
  CHECK_MSG(parse(replace(kValid, R"("node_id": 1, "sync_period_us": 10000)", kBusFields), cfg, errors), join(errors));
  const MasterConfig& m = cfg.master;
  CHECK(m.has_bus_state_location && m.bus_state_location.str() == "%IB100");
  CHECK(m.has_tx_error_count_location && m.tx_error_count_location.str() == "%IB101");
  CHECK(m.has_rx_error_count_location && m.rx_error_count_location.str() == "%IB102");
  CHECK(m.has_bus_off_count_location && m.bus_off_count_location.str() == "%IW100");
  CHECK_MSG(cfg.warnings.empty(), join(cfg.warnings));
}

TEST(config_bus_fields_absent) {
  Config cfg;
  std::vector<std::string> errors;
  CHECK(parse(kValid, cfg, errors));
  const MasterConfig& m = cfg.master;
  CHECK(!m.has_bus_state_location && !m.has_tx_error_count_location && !m.has_rx_error_count_location &&
        !m.has_bus_off_count_location);
}

TEST(config_bus_fields_wrong_size) {
  struct Case {
    const char* from;
    const char* to;
    const char* msg;
  } cases[] = {
      {"\"bus_state_location\": \"%IB100\"", "\"bus_state_location\": \"%IW100\"",
       "master: bus_state_location must be an input byte"},
      {"\"tx_error_count_location\": \"%IB101\"", "\"tx_error_count_location\": \"%QB101\"",
       "master: tx_error_count_location must be an input byte"},
      {"\"rx_error_count_location\": \"%IB102\"", "\"rx_error_count_location\": \"%IX102.0\"",
       "master: rx_error_count_location must be an input byte"},
      {"\"bus_off_count_location\": \"%IW100\"", "\"bus_off_count_location\": \"%IB103\"",
       "master: bus_off_count_location must be an input word"},
  };
  for (const auto& c : cases) {
    Config cfg;
    std::vector<std::string> errors;
    std::string s = replace(kValid, R"("node_id": 1, "sync_period_us": 10000)", kBusFields);
    CHECK(!parse(replace(s, c.from, c.to), cfg, errors));
    CHECK_MSG(has_error(errors, c.msg), join(errors));
  }
}

TEST(config_bus_state_overlaps_node_state) {
  std::string s = replace(kValid, R"("node_id": 1, "sync_period_us": 10000)",
                          R"("node_id": 1, "sync_period_us": 10000, "bus_state_location": "%IB20")");
  s = replace(s, "\"status_location\": \"%IX10.0\",", "\"status_location\": \"%IX10.0\", \"state_location\": \"%IB20\",");
  Config cfg;
  std::vector<std::string> errors;
  CHECK(!parse(s, cfg, errors));
  CHECK_MSG(has_error(errors, "master bus_state_location and node 2 (pingpong) state_location both map to %IB20"),
            join(errors));
}

// ---------------------------------------------------------------------------
// EDS checks (canopen-master-bringup: General EDS support)

TEST(eds_missing_file) {
  Config cfg;
  std::vector<std::string> errors;
  CHECK(parse(replace(kValid, "cpp-slave.eds", "missing.eds"), cfg, errors));
  CHECK(!check_eds_files(cfg, errors));
  CHECK_MSG(has_error(errors, "node 2: EDS file") && has_error(errors, "missing.eds"), join(errors));
}

TEST(eds_unparsable_file) {
  std::string dir = tmpdir();
  write(dir + "/broken.eds", "[1000\nParameterName=Device type\n");
  Config cfg;
  std::vector<std::string> errors;
  CHECK(parse(replace(kValid, "cpp-slave.eds", dir + "/broken.eds"), cfg, errors));
  set_log_sink(silent);
  CHECK(!check_eds_files(cfg, errors));
  set_log_sink(nullptr);
  CHECK_MSG(has_error(errors, "node 2: EDS file " + dir + "/broken.eds cannot be parsed"), join(errors));
}

TEST(eds_entry_not_defined) {
  Config cfg;
  std::vector<std::string> errors;
  CHECK(parse(replace(kValid, "\"0x4001\"", "\"0x4005\""), cfg, errors));
  CHECK(!check_eds_files(cfg, errors));
  CHECK_MSG(has_error(errors, "node 2, index 0x4005, subindex 0: object is not defined"), join(errors));
}

TEST(eds_entry_not_mappable) {
  // 0x1000 (device type) exists but has PDOMapping=0 in the tutorial EDS.
  Config cfg;
  std::vector<std::string> errors;
  CHECK(parse(replace(kValid, "\"0x4001\"", "\"0x1000\""), cfg, errors));
  CHECK(!check_eds_files(cfg, errors));
  CHECK_MSG(has_error(errors, "node 2, index 0x1000, subindex 0: object is not PDO-mappable"), join(errors));
}

TEST(eds_trimmed_copy) {
  // A trimmed copy of the tutorial EDS without 0x4001: the entry is rejected.
  std::string eds = read(std::string(PINGPONG_DIR) + "/cpp-slave.eds");
  size_t at = eds.find("[4001]");
  CHECK(at != std::string::npos);
  eds = eds.substr(0, at);
  eds = replace(eds, "SupportedObjects=2\n1=0x4000\n2=0x4001", "SupportedObjects=1\n1=0x4000");
  std::string dir = tmpdir();
  write(dir + "/trimmed.eds", eds);
  Config cfg;
  std::vector<std::string> errors;
  CHECK(parse(replace(kValid, "cpp-slave.eds", dir + "/trimmed.eds"), cfg, errors));
  set_log_sink(silent);
  CHECK(!check_eds_files(cfg, errors));
  set_log_sink(nullptr);
  CHECK_MSG(has_error(errors, "node 2, index 0x4001, subindex 0: object is not defined"), join(errors));
}

TEST(eds_wrong_direction_access) {
  // 0x4001 is rwr (slave sends it): mapping it into an RPDO is rejected.
  Config cfg;
  std::vector<std::string> errors;
  std::string s = replace(kValid, "{ \"index\": \"0x4000\"", "{ \"index\": \"0x4001\"");
  CHECK(parse(s, cfg, errors));
  CHECK(!check_eds_files(cfg, errors));
  CHECK_MSG(has_error(errors, "index 0x4001, subindex 0: rx_pdos entry needs an object the slave can receive (AccessType wo, rw or rww), but its AccessType is rwr"), join(errors));
}

TEST(eds_pdo_number_missing) {
  Config cfg;
  std::vector<std::string> errors;
  CHECK(parse(replace(kValid, "\"tx_pdos\": [ {", "\"tx_pdos\": [ { \"number\": 2,"), cfg, errors));
  CHECK(!check_eds_files(cfg, errors));
  CHECK_MSG(has_error(errors, "TPDO 2 does not exist"), join(errors));
}

// ---------------------------------------------------------------------------
// Config contract (canopen-config-contract) and adapter (canopen-master-bringup)

bool has_warning(const Config& cfg, const std::string& needle) {
  for (const auto& w : cfg.warnings)
    if (w.find(needle) != std::string::npos) return true;
  return false;
}

TEST(contract_version_omitted) {
  Config cfg;
  std::vector<std::string> errors;
  CHECK_MSG(parse(replace(kValid, "\"schema_version\": 1,", ""), cfg, errors), join(errors));
  CHECK(cfg.schema_version == 1);
}

TEST(contract_version_from_the_future) {
  Config cfg;
  std::vector<std::string> errors;
  CHECK(!parse(replace(kValid, "\"schema_version\": 1", "\"schema_version\": 3"), cfg, errors));
  CHECK_MSG(has_error(errors, "schema_version 3 is not supported; the highest supported version is 2"), join(errors));
  CHECK(errors.size() == 1);
}

TEST(contract_unknown_field_warns) {
  Config cfg;
  std::vector<std::string> errors;
  std::string s = replace(kValid, "\"name\": \"pingpong\",", "\"name\": \"pingpong\", \"colour\": \"blue\",");
  s = replace(s, "\"sync_period_us\": 10000", "\"sync_period_us\": 10000, \"sync_jitter_us\": 5");
  CHECK_MSG(parse(s, cfg, errors), join(errors));
  CHECK_MSG(has_warning(cfg, "nodes[0]: unknown field 'colour' (nodes[0].colour) ignored"), join(cfg.warnings));
  CHECK_MSG(has_warning(cfg, "master: unknown field 'sync_jitter_us' (master.sync_jitter_us) ignored"),
            join(cfg.warnings));
}

TEST(contract_old_style_keys) {
  Config cfg;
  std::vector<std::string> errors;
  std::string s = replace(kValid, "\"adapter\": { \"type\": \"socketcan\", \"interface\": \"vcan0\", \"bitrate\": 125000 }",
                          "\"interface\": \"vcan0\", \"bitrate\": 125000");
  CHECK_MSG(parse(s, cfg, errors), join(errors));
  CHECK(cfg.adapter.type == "socketcan" && cfg.adapter.interface == "vcan0" && cfg.adapter.bitrate == 125000);
  CHECK(!cfg.adapter.configure_link);  // as before the contract: the link is left alone
  CHECK_MSG(has_warning(cfg, "top-level 'interface' and 'bitrate' are deprecated"), join(cfg.warnings));
}

TEST(contract_both_styles_rejected) {
  Config cfg;
  std::vector<std::string> errors;
  CHECK(!parse(replace(kValid, "\"schema_version\": 1,", "\"schema_version\": 1, \"interface\": \"vcan0\","), cfg,
               errors));
  CHECK_MSG(has_error(errors, "give either 'adapter' or the deprecated top-level 'interface', not both"), join(errors));
}

TEST(adapter_unknown_type) {
  Config cfg;
  std::vector<std::string> errors;
  CHECK(!parse(replace(kValid, "\"type\": \"socketcan\"", "\"type\": \"pcan\""), cfg, errors));
  CHECK_MSG(has_error(errors, "adapter type \"pcan\" is not supported (supported: socketcan, slcan)"), join(errors));
}

TEST(adapter_options) {
  Config cfg;
  std::vector<std::string> errors;
  CHECK_MSG(parse(replace(kValid, "\"bitrate\": 125000 }",
                          "\"bitrate\": 125000, \"configure_link\": false, \"restart_ms\": 100 }"),
                  cfg, errors),
            join(errors));
  CHECK(!cfg.adapter.configure_link && cfg.adapter.has_restart_ms && cfg.adapter.restart_ms == 100);
  errors.clear();
  CHECK(!parse(replace(kValid, "\"bitrate\": 125000 }", "\"bitrate\": 125000, \"configure_link\": 1 }"), cfg, errors));
  CHECK_MSG(has_error(errors, "adapter: field 'configure_link' must be true or false"), join(errors));
  errors.clear();
  CHECK(!parse(replace(kValid, ", \"bitrate\": 125000 }", " }"), cfg, errors));
  CHECK_MSG(has_error(errors, "adapter: missing required field 'bitrate'"), join(errors));
}

// ---------------------------------------------------------------------------
// Startup SDOs

const char* kSdoNode = "\"sdo\": [ { \"index\": \"0x1017\", \"subindex\": 0, \"type\": \"UNSIGNED16\", \"value\": 100 } ],";

std::string with_sdo(const std::string& sdo) {
  return replace(kValid, "\"status_location\": \"%IX10.0\",", std::string("\"status_location\": \"%IX10.0\", ") + sdo);
}

TEST(sdo_parsed_in_order) {
  Config cfg;
  std::vector<std::string> errors;
  CHECK_MSG(parse(with_sdo(R"("sdo": [ { "index": "0x1017", "subindex": 0, "type": "UNSIGNED16", "value": 100 },
                                        { "index": 8192, "type": "INTEGER8", "value": -2 },
                                        { "index": "0x2001", "type": "REAL32", "value": 1.5 },
                                        { "index": "0x2002", "type": "UNSIGNED32", "value": "0xDEADBEEF" },
                                        { "index": "0x2003", "type": "BOOLEAN", "value": true } ],)"),
                  cfg, errors),
            join(errors));
  const auto& s = cfg.nodes[0].sdos;
  CHECK(s.size() == 5);
  CHECK(s[0].index == 0x1017 && s[0].subindex == 0 && s[0].data == std::vector<uint8_t>({100, 0}));
  CHECK(s[1].index == 0x2000 && s[1].data == std::vector<uint8_t>({0xFE}));
  CHECK(s[2].data == std::vector<uint8_t>({0x00, 0x00, 0xC0, 0x3F}));
  CHECK(s[3].data == std::vector<uint8_t>({0xEF, 0xBE, 0xAD, 0xDE}));
  CHECK(s[4].data == std::vector<uint8_t>({1}));
}

TEST(sdo_value_out_of_range) {
  struct Case {
    const char* type;
    const char* value;
    const char* shown;
  } cases[] = {{"UNSIGNED8", "300", "300"},       {"UNSIGNED16", "-1", "-1"},     {"INTEGER8", "128", "128"},
               {"INTEGER8", "-129", "-129"},      {"BOOLEAN", "2", "2"},          {"UNSIGNED32", "\"0x100000000\"", "0x100000000"},
               {"UNSIGNED16", "1.5", "1.5"},      {"REAL32", "\"1\"", "1"}};
  for (const auto& c : cases) {
    Config cfg;
    std::vector<std::string> errors;
    std::string sdo = std::string("\"sdo\": [ { \"index\": \"0x1017\", \"type\": \"") + c.type + "\", \"value\": " + c.value + " } ],";
    CHECK(!parse(with_sdo(sdo), cfg, errors));
    CHECK_MSG(has_error(errors, std::string("nodes[0]: sdo[0]: node 2, index 0x1017, subindex 0: value ") + c.shown),
              std::string(c.type) + " " + c.value + join(errors));
  }
  Config cfg;
  std::vector<std::string> errors;
  CHECK(!parse(with_sdo("\"sdo\": [ { \"index\": \"0x1017\", \"type\": \"UNSIGNED8\", \"value\": 300 } ],"), cfg, errors));
  CHECK_MSG(has_error(errors, "node 2, index 0x1017, subindex 0: value 300 does not fit UNSIGNED8"), join(errors));
  errors.clear();
  CHECK(parse(with_sdo("\"sdo\": [ { \"index\": \"0x1017\", \"type\": \"INTEGER64\", \"value\": \"-0x8000000000000000\" } ],"),
              cfg, errors));
}

TEST(sdo_checked_against_eds) {
  Config cfg;
  std::vector<std::string> errors;
  CHECK(parse(with_sdo("\"sdo\": [ { \"index\": \"0x1000\", \"type\": \"UNSIGNED32\", \"value\": 0 } ],"), cfg, errors));
  CHECK(!check_eds_files(cfg, errors));
  CHECK_MSG(has_error(errors, "node 2, index 0x1000, subindex 0: startup SDO needs a writable object (AccessType wo, "
                              "rw, rwr or rww), but its AccessType is ro"),
            join(errors));
  errors.clear();
  CHECK(parse(with_sdo("\"sdo\": [ { \"index\": \"0x1017\", \"type\": \"UNSIGNED32\", \"value\": 0 } ],"), cfg, errors));
  CHECK(!check_eds_files(cfg, errors));
  CHECK_MSG(has_error(errors, "node 2, index 0x1017, subindex 0: configured type UNSIGNED32 does not match the EDS "
                              "data type UNSIGNED16"),
            join(errors));
  errors.clear();
  CHECK(parse(with_sdo(kSdoNode), cfg, errors));
  CHECK_MSG(check_eds_files(cfg, errors), join(errors));
}

// ---------------------------------------------------------------------------
// EDS data-type and access-type checks (canopen-pdo-io)

std::string eds_variant(const std::string& from, const std::string& to) {
  std::string eds = replace(read(std::string(PINGPONG_DIR) + "/cpp-slave.eds"), from, to);
  std::string dir = tmpdir();
  write(dir + "/variant.eds", eds);
  return dir + "/variant.eds";
}

TEST(eds_type_mismatch) {
  std::string eds = eds_variant("[4001]\nParameterName=UNSIGNED32 sent from slave\nDataType=0x0007",
                                "[4001]\nParameterName=UNSIGNED32 sent from slave\nDataType=0x0006");
  Config cfg;
  std::vector<std::string> errors;
  CHECK(parse(replace(kValid, "cpp-slave.eds", eds), cfg, errors));
  CHECK(!check_eds_files(cfg, errors));
  CHECK_MSG(has_error(errors, "node 2, index 0x4001, subindex 0: configured type UNSIGNED32 does not match the EDS "
                              "data type UNSIGNED16"),
            join(errors));
  // Same size, different type: also rejected.
  errors.clear();
  CHECK(parse(replace(kValid, "\"type\": \"UNSIGNED32\", \"iec_location\": \"%ID100\"",
                      "\"type\": \"INTEGER32\", \"iec_location\": \"%ID100\""),
              cfg, errors));
  CHECK(!check_eds_files(cfg, errors));
  CHECK_MSG(has_error(errors, "configured type INTEGER32 does not match the EDS data type UNSIGNED32"), join(errors));
}

TEST(eds_master_writes_read_only) {
  std::string eds = eds_variant("DataType=0x0007\nAccessType=rww", "DataType=0x0007\nAccessType=ro");
  Config cfg;
  std::vector<std::string> errors;
  CHECK(parse(replace(kValid, "cpp-slave.eds", eds), cfg, errors));
  CHECK(!check_eds_files(cfg, errors));
  CHECK_MSG(has_error(errors, "node 2, index 0x4000, subindex 0: rx_pdos entry needs an object the slave can "
                              "receive (AccessType wo, rw or rww), but its AccessType is ro"),
            join(errors));
}

// ---------------------------------------------------------------------------
// EDS path resolution (canopen-stock-install)

TEST(eds_resolved_next_to_config) {
  Config cfg;
  std::vector<std::string> errors;
  CHECK(parse_config(kValid, std::string(PINGPONG_DIR) + "/canopen_config.json", ImageLimits(), cfg, errors,
                     "/nonexistent/conf"));
  CHECK(cfg.nodes[0].eds_path == std::string(PINGPONG_DIR) + "/cpp-slave.eds");
  CHECK(cfg.nodes[0].eds_candidates.size() == 2);
}

TEST(eds_resolved_in_generated_conf) {
  // Stock route: the runtime copied canopen.json next to the library and
  // extracted the upload's EDS files under core/generated/conf/.
  std::string lib = tmpdir();
  std::string conf = tmpdir();
  mkdir((conf + "/canopen").c_str(), 0755);
  mkdir((conf + "/canopen/eds").c_str(), 0755);
  write(conf + "/canopen/eds/cpp-slave.eds", read(std::string(PINGPONG_DIR) + "/cpp-slave.eds"));
  Config cfg;
  std::vector<std::string> errors;
  CHECK(parse_config(replace(kValid, "\"cpp-slave.eds\"", "\"canopen/eds/cpp-slave.eds\""), lib + "/canopen.json",
                     ImageLimits(), cfg, errors, conf));
  CHECK_MSG(cfg.nodes[0].eds_path == conf + "/canopen/eds/cpp-slave.eds", cfg.nodes[0].eds_path);
  CHECK_MSG(check_eds_files(cfg, errors), join(errors));
}

TEST(eds_resolved_nowhere) {
  std::string lib = tmpdir();
  Config cfg;
  std::vector<std::string> errors;
  CHECK(parse_config(replace(kValid, "\"cpp-slave.eds\"", "\"canopen/eds/cpp-slave.eds\""), lib + "/canopen.json",
                     ImageLimits(), cfg, errors, "/nonexistent/conf"));
  CHECK(!check_eds_files(cfg, errors));
  CHECK_MSG(has_error(errors, "node 2: EDS file " + lib + "/canopen/eds/cpp-slave.eds not found (also looked for "
                              "/nonexistent/conf/canopen/eds/cpp-slave.eds)"),
            join(errors));
}

// ---------------------------------------------------------------------------
// Shared fixtures (test/fixtures/config/cases.json), also run by the deploy
// tool's tests: the plugin's verdict and messages must match.

cJSON* child(cJSON* parent, const std::string& key) {
  if (cJSON_IsArray(parent)) return cJSON_GetArrayItem(parent, std::atoi(key.c_str()));
  return cJSON_GetObjectItemCaseSensitive(parent, key.c_str());
}

void apply_patch(cJSON* root, const cJSON* op) {
  std::string kind = cJSON_GetArrayItem(op, 0)->valuestring;
  std::string path = cJSON_GetArrayItem(op, 1)->valuestring;
  std::vector<std::string> parts;
  std::stringstream ss(path);
  for (std::string p; std::getline(ss, p, '/');) parts.push_back(p);
  cJSON* parent = root;
  for (size_t i = 0; i + 1 < parts.size(); ++i) parent = child(parent, parts[i]);
  const std::string& last = parts.back();
  if (kind == "delete") {
    if (cJSON_IsArray(parent)) cJSON_DeleteItemFromArray(parent, std::atoi(last.c_str()));
    else cJSON_DeleteItemFromObjectCaseSensitive(parent, last.c_str());
    return;
  }
  cJSON* value = cJSON_Duplicate(cJSON_GetArrayItem(op, 2), true);
  if (cJSON_IsArray(parent)) {
    int at = std::atoi(last.c_str());
    if (at < cJSON_GetArraySize(parent)) cJSON_ReplaceItemInArray(parent, at, value);
    else cJSON_AddItemToArray(parent, value);
  } else if (cJSON_GetObjectItemCaseSensitive(parent, last.c_str())) {
    cJSON_ReplaceItemInObjectCaseSensitive(parent, last.c_str(), value);
  } else {
    cJSON_AddItemToObject(parent, last.c_str(), value);
  }
}

std::vector<std::string> strings(const cJSON* obj, const char* key) {
  std::vector<std::string> out;
  const cJSON* arr = cJSON_GetObjectItemCaseSensitive(obj, key);
  const cJSON* s;
  cJSON_ArrayForEach(s, arr) out.push_back(s->valuestring);
  return out;
}

// Runs one fixture file; returns the number of cases.
int run_fixture_file(const std::string& file) {
  std::string fixtures = FIXTURES_DIR;
  cJSON* doc = cJSON_Parse(read(fixtures + "/config/" + file).c_str());
  CHECK_MSG(doc != nullptr, file);
  if (!doc) return 0;
  const cJSON* base = cJSON_GetObjectItemCaseSensitive(doc, "base");
  const cJSON* c;
  int count = 0;
  set_log_sink(silent);
  cJSON_ArrayForEach(c, cJSON_GetObjectItemCaseSensitive(doc, "cases")) {
    std::string name = cJSON_GetObjectItemCaseSensitive(c, "name")->valuestring;
    cJSON* cfg_json = cJSON_Duplicate(base, true);
    const cJSON* op;
    cJSON_ArrayForEach(op, cJSON_GetObjectItemCaseSensitive(c, "patch")) apply_patch(cfg_json, op);
    char* text = cJSON_Print(cfg_json);
    ConfigSet set;
    std::vector<std::string> errors;
    bool ok = parse_config_set(text, fixtures + "/eds/canopen.json", ImageLimits(), set, errors, "/nonexistent");
    std::vector<std::string> warnings = set.warnings;
    for (auto& cfg : set.networks) {
      if (ok) {
        std::string lint_dir = tmpdir();  // the prepared EDS copies
        ok = run_eds_lint(cfg, default_edslint_python(), lint_dir, errors) && check_eds_files(cfg, errors);
      }
      warnings.insert(warnings.end(), cfg.warnings.begin(), cfg.warnings.end());
    }
    std::free(text);
    cJSON_Delete(cfg_json);
    bool want = std::string(cJSON_GetObjectItemCaseSensitive(c, "verdict")->valuestring) == "accept";
    CHECK_MSG(ok == want, name + join(errors));
    if (want) {
      std::string schema = cJSON_GetObjectItemCaseSensitive(c, "schema")->valuestring;
      CHECK_MSG(schema == "valid", name + ": the plugin accepts it, so the schema must too");
    }
    for (const char* key : {"messages", "plugin_messages"})
      for (const auto& m : strings(c, key)) CHECK_MSG(has_error(errors, m), name + ": " + m + join(errors));
    for (const auto& m : strings(c, "warnings")) CHECK_MSG(has_error(warnings, m), name + ": " + m + join(warnings));
    ++count;
  }
  set_log_sink(nullptr);
  cJSON_Delete(doc);
  return count;
}

TEST(shared_fixtures) { CHECK(run_fixture_file("cases.json") > 20); }

TEST(shared_fixtures_v2) { CHECK(run_fixture_file("cases-v2.json") > 15); }

// ---------------------------------------------------------------------------
// SocketCAN link setup on a mocked rtnetlink layer (canopen-master-bringup)

struct MockLink : LinkOps {
  std::map<std::string, LinkInfo> links;
  int fail_set = 0;  // errno returned by set_* (0 = succeed)
  std::vector<std::string> calls;

  int get(const std::string& name, LinkInfo& out) override {
    auto it = links.find(name);
    if (it == links.end()) return -ENODEV;
    out = it->second;
    return 0;
  }
  int set_up(const std::string& name, bool up) override {
    calls.push_back(up ? "up" : "down");
    if (fail_set) return -fail_set;
    links[name].up = up;
    return 0;
  }
  int set_bitrate(const std::string& name, unsigned bitrate, long restart_ms) override {
    calls.push_back("bitrate " + std::to_string(bitrate) + (restart_ms >= 0 ? " restart " + std::to_string(restart_ms) : ""));
    if (fail_set) return -fail_set;
    if (links[name].up) return -EBUSY;
    links[name].bitrate = bitrate;
    return 0;
  }
  int rename(const std::string& name, const std::string& new_name) override {
    calls.push_back("rename " + name + " " + new_name);
    auto it = links.find(name);
    if (it == links.end()) return -ENODEV;
    links[new_name] = it->second;
    links.erase(name);
    return 0;
  }
  int set_txqlen(const std::string&, unsigned len) override {
    calls.push_back("txqlen " + std::to_string(len));
    return fail_set ? -fail_set : 0;
  }
};

std::vector<std::string> g_log;
void capture(LogLevel level, const char* msg) {
  const char* l = level == LogLevel::Warn ? "W: " : level == LogLevel::Error ? "E: " : "I: ";
  std::string m = msg;
  if (m.compare(0, 10, "[CANOPEN] ") == 0) m = m.substr(10);
  g_log.push_back(std::string(l) + m);
}

struct LinkFixture {
  MockLink* link = new MockLink;
  std::unique_ptr<CanAdapter> adapter;
  AdapterConfig cfg;
  LinkFixture(bool configure = true) {
    cfg.interface = "can0";
    cfg.bitrate = 500000;
    cfg.configure_link = configure;
    g_log.clear();
    set_log_sink(capture);
  }
  ~LinkFixture() { set_log_sink(nullptr); }
  AdapterState prepare() {
    if (!adapter) adapter = make_adapter(cfg, std::unique_ptr<LinkOps>(link));
    return adapter->prepare();
  }
  std::string calls() const {
    std::string s;
    for (const auto& c : link->calls) s += (s.empty() ? "" : ", ") + c;
    return s;
  }
};

TEST(link_down_no_bitrate) {
  LinkFixture f;
  f.link->links["can0"] = LinkInfo{false, "can", 0};
  CHECK(f.prepare() == AdapterState::Ready);
  CHECK_MSG(f.calls() == "bitrate 500000, up", f.calls());
  CHECK(f.link->links["can0"].up && f.link->links["can0"].bitrate == 500000);
  CHECK_MSG(has_error(g_log, "I: set CAN interface can0 to 500000 bit/s and brought it up"), join(g_log));
}

TEST(link_up_at_configured_rate) {
  LinkFixture f;
  f.link->links["can0"] = LinkInfo{true, "can", 500000};
  CHECK(f.prepare() == AdapterState::Ready);
  CHECK_MSG(f.calls().empty(), f.calls());
}

TEST(link_up_at_other_rate) {
  LinkFixture f;
  f.link->links["can0"] = LinkInfo{true, "can", 250000};
  CHECK(f.prepare() == AdapterState::Ready);
  CHECK_MSG(f.calls() == "down, bitrate 500000, up", f.calls());
  CHECK_MSG(has_error(g_log, "W: CAN interface can0 runs at 250000 bit/s but the config says 500000 bit/s; taking it down"),
            join(g_log));
}

TEST(link_restart_ms) {
  LinkFixture f;
  f.cfg.restart_ms = 100;
  f.cfg.has_restart_ms = true;
  f.link->links["can0"] = LinkInfo{false, "can", 0};
  CHECK(f.prepare() == AdapterState::Ready);
  CHECK_MSG(f.calls() == "bitrate 500000 restart 100, up", f.calls());
}

TEST(link_left_to_the_system) {
  LinkFixture f(false);
  f.link->links["can0"] = LinkInfo{true, "can", 250000};
  CHECK(f.prepare() == AdapterState::Ready);
  CHECK(f.prepare() == AdapterState::Ready);
  CHECK_MSG(f.calls().empty(), f.calls());
  CHECK_MSG(g_log.size() == 1 && has_error(g_log, "W: CAN interface can0 runs at 250000 bit/s but the config says "
                                                  "500000 bit/s; configure_link is false"),
            join(g_log));
  f.link->links["can0"].up = false;
  CHECK(f.prepare() == AdapterState::Down);
  CHECK(f.calls().empty());
}

TEST(link_vcan_only_brought_up) {
  LinkFixture f;
  f.cfg.interface = "vcan0";
  f.link->links["vcan0"] = LinkInfo{false, "vcan", 0};
  CHECK(f.prepare() == AdapterState::Ready);
  CHECK_MSG(f.calls() == "up", f.calls());
  CHECK(f.prepare() == AdapterState::Ready);
  CHECK_MSG(f.calls() == "up", f.calls());
}

TEST(link_missing) {
  LinkFixture f;
  CHECK(f.prepare() == AdapterState::Missing);
  CHECK(f.adapter->problem() == "CAN interface can0 is missing");
}

TEST(link_not_permitted) {
  LinkFixture f;
  f.link->links["can0"] = LinkInfo{false, "can", 0};
  f.link->fail_set = EPERM;
  CHECK(f.prepare() == AdapterState::NotPermitted);
  CHECK_MSG(f.adapter->problem().find("cannot configure CAN interface can0: permission denied") == 0 &&
                f.adapter->problem().find("CAP_NET_ADMIN") != std::string::npos,
            f.adapter->problem());
  // Retried on the next attempt, and succeeds once permitted.
  f.link->fail_set = 0;
  CHECK(f.prepare() == AdapterState::Ready);
}

// ---------------------------------------------------------------------------
// slcan backend on mocked serial and rtnetlink layers (canopen-slcan-adapter)

struct MockSerial : SerialOps {
  MockLink* link;
  std::set<std::string> devices;  // serial devices that exist
  int attach_err = 0;
  std::string kind = "can";  // what the created link reports ("" = pre-6.0 slcan)
  int open_fds = 0;
  std::vector<std::string> calls;
  explicit MockSerial(MockLink* l) : link(l) {}

  int open(const std::string& path, unsigned baudrate, int& fd) override {
    calls.push_back("open " + path + (baudrate ? " " + std::to_string(baudrate) : ""));
    if (!devices.count(path)) return -ENOENT;
    fd = 42;
    ++open_fds;
    return 0;
  }
  int attach(int, std::string& ifname) override {
    if (attach_err) return -attach_err;
    LinkInfo li;
    li.kind = kind;
    link->links["slcan0"] = li;
    ifname = "slcan0";
    return 0;
  }
  void close(int) override {
    calls.push_back("close");
    --open_fds;
    // Closing the tty removes the interface, whatever it is called by now.
    link->links.erase("slcan0");
    link->links.erase("can0");
  }
};

struct SlcanFixture : LinkFixture {
  MockSerial* serial = new MockSerial(link);
  SlcanFixture() {
    cfg.type = "slcan";
    cfg.device = "/dev/ttyACM0";
    serial->devices.insert("/dev/ttyACM0");
  }
  AdapterState prepare() {
    if (!adapter) adapter = make_adapter(cfg, std::unique_ptr<LinkOps>(link), std::unique_ptr<SerialOps>(serial));
    return adapter->prepare();
  }
};

TEST(slcan_creates_the_interface) {
  SlcanFixture f;
  CHECK_MSG(f.prepare() == AdapterState::Ready, f.adapter->problem());
  CHECK_MSG(f.calls() == "rename slcan0 can0, bitrate 500000, txqlen 1000, up", f.calls());
  CHECK(f.link->links.count("can0") && f.link->links["can0"].up && !f.link->links.count("slcan0"));
  CHECK_MSG(has_error(g_log, "I: attached the slcan driver to /dev/ttyACM0 as CAN interface can0"), join(g_log));
  CHECK_MSG(has_error(g_log, "I: set CAN interface can0 (slcan on /dev/ttyACM0) to 500000 bit/s, txqueuelen 1000"),
            join(g_log));
  // Already set up: the next attempt changes nothing.
  CHECK(f.prepare() == AdapterState::Ready);
  CHECK(f.serial->open_fds == 1 && f.link->calls.size() == 4);
}

TEST(slcan_serial_speed) {
  SlcanFixture f;
  f.cfg.serial_baudrate = 115200;
  CHECK(f.prepare() == AdapterState::Ready);
  CHECK_MSG(f.serial->calls[0] == "open /dev/ttyACM0 115200", f.serial->calls[0]);
}

TEST(slcan_device_missing) {
  SlcanFixture f;
  f.serial->devices.clear();
  CHECK(f.prepare() == AdapterState::Missing);
  CHECK_MSG(f.adapter->problem() == "serial device /dev/ttyACM0 is missing", f.adapter->problem());
  f.serial->devices.insert("/dev/ttyACM0");
  CHECK(f.prepare() == AdapterState::Ready);
}

TEST(slcan_name_taken) {
  SlcanFixture f;
  f.link->links["can0"] = LinkInfo{true, "can", 500000};  // made by an slcand service
  CHECK(f.prepare() == AdapterState::Failed);
  CHECK_MSG(f.adapter->problem().find("CAN interface can0 already exists and was not created by the plugin; stop "
                                      "the program that created it (such as an slcand service)") == 0,
            f.adapter->problem());
  CHECK(f.serial->calls.empty() && f.link->calls.empty());  // neither the device nor can0 touched
  f.link->links.erase("can0");                              // service stopped
  CHECK(f.prepare() == AdapterState::Ready);
}

TEST(slcan_unplug_and_replug) {
  SlcanFixture f;
  CHECK(f.prepare() == AdapterState::Ready);
  // Unplugged: the kernel removes the interface and the device node.
  f.link->links.erase("can0");
  f.serial->devices.clear();
  CHECK(f.prepare() == AdapterState::Missing);
  CHECK(f.serial->open_fds == 0);
  CHECK_MSG(has_error(g_log, "W: CAN interface can0 (slcan on /dev/ttyACM0) is gone; reopening"), join(g_log));
  f.serial->devices.insert("/dev/ttyACM0");
  f.link->calls.clear();
  CHECK(f.prepare() == AdapterState::Ready);
  CHECK_MSG(f.calls() == "rename slcan0 can0, bitrate 500000, txqlen 1000, up", f.calls());
  CHECK(f.serial->open_fds == 1);
}

TEST(slcan_old_kernel) {
  SlcanFixture f;
  f.serial->kind = "";  // before Linux 6.0 slcan is not a CAN device
  CHECK(f.prepare() == AdapterState::Failed);
  CHECK_MSG(f.adapter->problem().find("does not take a bit rate over netlink (needs Linux 6.0 or newer); create "
                                      "can0 with slcand and use adapter type socketcan with configure_link false") !=
                std::string::npos,
            f.adapter->problem());
  CHECK(f.serial->open_fds == 0);
}

TEST(slcan_not_permitted) {
  SlcanFixture f;
  f.serial->attach_err = EPERM;
  CHECK(f.prepare() == AdapterState::NotPermitted);
  CHECK_MSG(f.adapter->problem() ==
                "cannot attach the slcan driver to /dev/ttyACM0: permission denied (needs CAP_NET_ADMIN; run the "
                "runtime as root)",
            f.adapter->problem());
  CHECK(f.serial->open_fds == 0);
}

TEST(slcan_release_removes_the_interface) {
  SlcanFixture f;
  CHECK(f.prepare() == AdapterState::Ready);
  f.link->calls.clear();
  f.adapter->release();
  CHECK_MSG(f.calls() == "down", f.calls());
  CHECK(f.serial->open_fds == 0 && !f.link->links.count("can0"));
  CHECK_MSG(has_error(g_log, "I: released /dev/ttyACM0; CAN interface can0 removed"), join(g_log));
  f.adapter->release();  // idempotent
  CHECK(f.serial->open_fds == 0);
}

TEST(netlink_reads_loopback) {
  // The real rtnetlink layer: "lo" exists everywhere, is up and is not CAN.
  auto ops = make_netlink_ops();
  LinkInfo li;
  CHECK(ops->get("lo", li) == 0);
  CHECK(li.up && li.kind.empty() && li.bitrate == 0);
  CHECK(ops->get("nosuchcan9", li) == -ENODEV);
  CHECK(ops->set_up("nosuchcan9", true) == -ENODEV);
}

// ---------------------------------------------------------------------------
// Bus diagnostics: netlink parsing and the monitor (canopen-bus-diagnostics)

namespace {

// Builds an RTM_NEWLINK reply the way the kernel lays out a CAN link.
struct NlMsg {
  alignas(nlmsghdr) char buf[1024] = {};
  nlmsghdr* nh() { return reinterpret_cast<nlmsghdr*>(buf); }
  NlMsg(bool up) {
    nh()->nlmsg_len = NLMSG_LENGTH(sizeof(ifinfomsg));
    nh()->nlmsg_type = RTM_NEWLINK;
    static_cast<ifinfomsg*>(NLMSG_DATA(nh()))->ifi_flags = up ? IFF_UP : 0;
  }
  rtattr* add(uint16_t type, const void* data, size_t len) {
    size_t at = NLMSG_ALIGN(nh()->nlmsg_len);
    rtattr* rta = reinterpret_cast<rtattr*>(buf + at);
    rta->rta_type = type;
    rta->rta_len = RTA_LENGTH(len);
    if (len) std::memcpy(RTA_DATA(rta), data, len);
    nh()->nlmsg_len = at + RTA_ALIGN(rta->rta_len);
    return rta;
  }
  void end(rtattr* nest) { nest->rta_len = static_cast<unsigned short>(buf + nh()->nlmsg_len - reinterpret_cast<char*>(nest)); }
};

}  // namespace

TEST(netlink_parses_can_diagnostics) {
  NlMsg m(true);
  rtattr* li = m.add(IFLA_LINKINFO, nullptr, 0);
  m.add(IFLA_INFO_KIND, "can", 4);
  rtattr* data = m.add(IFLA_INFO_DATA, nullptr, 0);
  uint32_t state = CAN_STATE_ERROR_PASSIVE;
  m.add(IFLA_CAN_STATE, &state, sizeof(state));
  can_berr_counter bc{130, 7};
  m.add(IFLA_CAN_BERR_COUNTER, &bc, sizeof(bc));
  m.end(data);
  can_device_stats st{};
  st.bus_off = 3;
  m.add(IFLA_INFO_XSTATS, &st, sizeof(st));
  m.end(li);
  LinkInfo out;
  CHECK(parse_newlink(m.buf, sizeof(m.buf), out));
  CHECK(out.up && out.kind == "can");
  CHECK(out.has_can_state && out.can_state == CAN_STATE_ERROR_PASSIVE);
  CHECK(out.has_berr && out.tx_errors == 130 && out.rx_errors == 7);
  CHECK(out.has_stats && out.bus_off == 3);
}

TEST(netlink_parses_can_without_counters) {
  NlMsg m(true);
  rtattr* li = m.add(IFLA_LINKINFO, nullptr, 0);
  m.add(IFLA_INFO_KIND, "can", 4);
  rtattr* data = m.add(IFLA_INFO_DATA, nullptr, 0);
  uint32_t state = CAN_STATE_ERROR_ACTIVE;
  m.add(IFLA_CAN_STATE, &state, sizeof(state));
  m.end(data);
  m.end(li);
  LinkInfo out;
  CHECK(parse_newlink(m.buf, sizeof(m.buf), out));
  CHECK(out.has_can_state && out.can_state == CAN_STATE_ERROR_ACTIVE);
  CHECK(!out.has_berr && !out.has_stats);
}

TEST(netlink_parses_vcan) {
  NlMsg m(true);
  rtattr* li = m.add(IFLA_LINKINFO, nullptr, 0);
  m.add(IFLA_INFO_KIND, "vcan", 5);
  uint64_t junk[8] = {1, 2, 3, 4, 5, 6, 7, 8};  // another kind's xstats: ignored
  m.add(IFLA_INFO_XSTATS, junk, sizeof(junk));
  m.end(li);
  LinkInfo out;
  CHECK(parse_newlink(m.buf, sizeof(m.buf), out));
  CHECK(out.up && out.kind == "vcan" && !out.has_can_state && !out.has_berr && !out.has_stats);
}

namespace {

struct MonitorFixture {
  MockLink* link = new MockLink;
  Config cfg;
  ProcessImage img;
  std::unique_ptr<BusMonitor> mon;
  BusMonitor::clock::time_point t = BusMonitor::clock::time_point() + std::chrono::hours(1);
  fake_runtime::Image* fake = new fake_runtime::Image;
  plugin_runtime_args_t rt;

  MonitorFixture(const std::string& iface = "can0", bool counters = true) {
    std::vector<std::string> errors;
    std::string s = replace(kValid, R"("node_id": 1, "sync_period_us": 10000)", kBusFields);
    s = replace(s, "\"vcan0\"", "\"" + iface + "\"");
    if (!counters) {
      s = replace(s, R"("tx_error_count_location": "%IB101", )", "");
      s = replace(s, R"("rx_error_count_location": "%IB102", )", "");
    }
    if (!parse(s, cfg, errors)) std::printf("  fixture: %s\n", join(errors).c_str());
    img.build(cfg);
    mon.reset(new BusMonitor(cfg, img, std::unique_ptr<LinkOps>(link)));
    mon->reset();
    fake_runtime::attach(*fake, rt);
    g_log.clear();
    set_log_sink(capture);
    LinkInfo li;
    li.up = true;
    li.kind = iface.compare(0, 4, "vcan") == 0 ? "vcan" : "can";
    if (li.kind == "can") {
      li.bitrate = 500000;
      li.has_can_state = true;
      li.has_berr = counters;
      li.has_stats = true;
    }
    link->links[iface] = li;
  }
  ~MonitorFixture() {
    set_log_sink(nullptr);
    delete fake;
  }
  LinkInfo& li() { return link->links.begin()->second; }
  bool tick(int ms = 100) {
    t += std::chrono::milliseconds(ms);
    bool changed = mon->poll(t);
    img.commit_inputs();
    img.copy_to_plc(rt);
    return changed;
  }
  unsigned state() const { return fake->byte_in[100]; }
  unsigned tx() const { return fake->byte_in[101]; }
  unsigned rx() const { return fake->byte_in[102]; }
  unsigned bus_offs() const { return fake->int_in[100]; }
};

}  // namespace

TEST(bus_monitor_states_and_counters) {
  MonitorFixture f;
  CHECK(f.tick());
  CHECK_MSG(f.state() == 1, std::to_string(f.state()));
  CHECK_MSG(g_log.empty(), join(g_log));  // coming up healthy is not news
  CHECK(!f.tick());

  f.li().can_state = CAN_STATE_ERROR_WARNING;
  f.li().tx_errors = 100;
  CHECK(f.tick());
  CHECK(f.state() == 2 && f.tx() == 100 && f.rx() == 0);

  // Cable pulled: TX errors stop at 128, error-passive.
  f.li().can_state = CAN_STATE_ERROR_PASSIVE;
  f.li().tx_errors = 128;
  f.li().rx_errors = 3;
  f.tick();
  CHECK(f.state() == 3 && f.tx() == 128 && f.rx() == 3);
  CHECK_MSG(has_error(g_log, "W: CAN interface can0 is error-passive"), join(g_log));

  f.li().can_state = CAN_STATE_BUS_OFF;
  f.li().tx_errors = 300;  // clamped
  f.li().bus_off = 1;
  f.tick();
  CHECK(f.state() == 4 && f.tx() == 255 && f.bus_offs() == 1);
  CHECK_MSG(has_error(g_log, "E: CAN interface can0 is bus-off; it stays bus-off until it is restarted (set "
                             "adapter.restart_ms"),
            join(g_log));

  f.li().can_state = CAN_STATE_ERROR_ACTIVE;
  f.li().tx_errors = 0;
  f.li().rx_errors = 0;
  f.tick();
  CHECK(f.state() == 1 && f.tx() == 0 && f.bus_offs() == 1);
  CHECK_MSG(has_error(g_log, "I: CAN interface can0 is error-active again"), join(g_log));

  // Stopped controller and a down link read "no bus".
  f.li().can_state = CAN_STATE_STOPPED;
  f.tick();
  CHECK(f.state() == 0);
  f.li().can_state = CAN_STATE_ERROR_ACTIVE;
  f.tick();
  f.li().up = false;
  f.tick();
  CHECK(f.state() == 0);
}

TEST(bus_monitor_restart_ms_hint) {
  MonitorFixture f;
  f.cfg.adapter.has_restart_ms = true;
  f.cfg.adapter.restart_ms = 100;
  f.tick();
  f.li().can_state = CAN_STATE_BUS_OFF;
  f.li().bus_off = 1;
  f.tick();
  CHECK_MSG(has_error(g_log, "E: CAN interface can0 is bus-off; the kernel restarts it after 100 ms"), join(g_log));
}

TEST(bus_monitor_short_bus_off_counted) {
  MonitorFixture f;
  f.li().bus_off = 7;  // before the PLC started
  f.tick();
  CHECK(f.bus_offs() == 0);
  f.li().bus_off = 9;  // two bus-offs the kernel recovered from between ticks
  f.tick();
  CHECK(f.state() == 1 && f.bus_offs() == 2);
  CHECK_MSG(has_error(g_log, "E: CAN interface can0 went bus-off 2 times and recovered"), join(g_log));
  // Wraps at 65535.
  f.li().bus_off = 9 + 65535;
  f.tick();
  CHECK(f.bus_offs() == 1);
  // A re-created link restarts its own count; nothing is lost or invented.
  f.li().bus_off = 0;
  f.tick();
  CHECK(f.bus_offs() == 1);
  f.li().bus_off = 1;
  f.tick();
  CHECK(f.bus_offs() == 2);
}

TEST(bus_monitor_reset_at_plc_start) {
  MonitorFixture f;
  f.tick();
  f.li().bus_off = 2;
  f.tick();
  CHECK(f.bus_offs() == 2);
  f.mon->reset();
  f.tick();
  CHECK(f.bus_offs() == 0);
  f.li().bus_off = 3;
  f.tick();
  CHECK(f.bus_offs() == 1);
}

TEST(bus_monitor_flapping_throttled) {
  MonitorFixture f;
  f.tick();
  g_log.clear();
  // 10 changes within one second: 5 logged, then one summary.
  for (int i = 0; i < 10; ++i) {
    f.li().can_state = i % 2 ? CAN_STATE_ERROR_ACTIVE : CAN_STATE_ERROR_PASSIVE;
    f.tick(50);
  }
  CHECK_MSG(g_log.size() == 5, join(g_log));
  f.tick(600);  // the window has passed
  CHECK_MSG(g_log.size() == 6 && has_error(g_log, "W: CAN interface can0: bus state changed 10 times in one second, "
                                                  "now error-active"),
            join(g_log));
  f.tick(1000);
  CHECK_MSG(g_log.size() == 6, join(g_log));
}

TEST(bus_monitor_no_counters) {
  MonitorFixture f("can0", false);
  f.li().has_berr = false;
  f.tick();
  CHECK_MSG(g_log.empty(), join(g_log));  // counters not mapped: nothing to say

  MonitorFixture g;
  g.li().has_berr = false;
  g.tick();
  g.tick();
  CHECK(g.tx() == 0 && g.rx() == 0 && g.state() == 1);
  CHECK_MSG(g_log.size() == 1 && has_error(g_log, "W: CAN interface can0 does not report error counters"),
            join(g_log));
}

TEST(bus_monitor_slcan_note) {
  MonitorFixture f;
  f.cfg.adapter.type = "slcan";
  f.li().has_can_state = false;  // slcan firmware sends no error state
  f.li().has_berr = false;
  f.tick();
  f.tick();
  CHECK(f.state() == 1);
  int n = 0;
  for (const auto& l : g_log) n += l.find("W: slcan adapter on can0 does not report the CAN error state") == 0;
  CHECK_MSG(n == 1, join(g_log));
  f.mon->reset();  // next PLC start: said again
  f.tick();
  CHECK_MSG(has_error(g_log, "candleLight firmware"), join(g_log));
}

TEST(bus_monitor_vcan_and_no_bus) {
  MonitorFixture f("vcan0");
  f.tick();
  CHECK(f.state() == 1 && f.tx() == 0 && f.bus_offs() == 0);
  CHECK_MSG(g_log.empty(), join(g_log));
  CHECK(f.mon->no_bus());
  f.img.commit_inputs();
  f.img.copy_to_plc(f.rt);
  CHECK(f.state() == 0);
  CHECK(!f.mon->no_bus());
  // A failed read keeps the last value (the session's own check ends it).
  f.tick();
  CHECK(f.state() == 1);
  f.link->links.clear();
  CHECK(!f.tick());
  CHECK(f.state() == 1);
}

// ---------------------------------------------------------------------------
// dcfgen

TEST(dcfgen_generates_and_caches) {
  std::string dir = tmpdir();
  write(dir + "/cpp-slave.eds", read(std::string(PINGPONG_DIR) + "/cpp-slave.eds"));
  Config cfg;
  std::vector<std::string> errors;
  CHECK(parse_config(kValid, dir + "/canopen_config.json", ImageLimits(), cfg, errors));
  GeneratedConfig gen;
  CHECK_MSG(generate_device_config(cfg, default_dcfgen(), gen, errors), join(errors));
  CHECK(!gen.reused);
  CHECK(gen.work_dir == dir + "/.canopen");
  struct stat st;
  CHECK(stat((dir + "/.canopen/master.dcf").c_str(), &st) == 0);
  CHECK(stat((dir + "/.canopen/node_2.bin").c_str(), &st) == 0);
  CHECK(gen.slave_sdos.count(2) == 1);
  // Heartbeat producer 500 ms is written to 0x1017 of the slave.
  bool hb = false, tpdo_map = false, rpdo_map = false;
  for (const auto& w : gen.slave_sdos[2]) {
    if (w.index == 0x1017 && w.data.size() == 2 && w.data[0] == (500 & 0xFF) && w.data[1] == (500 >> 8)) hb = true;
    if (w.index == 0x1A00 && w.subindex == 1 && w.data.size() == 4 && w.data[3] == 0x40 && w.data[2] == 0x01)
      tpdo_map = true;
    if (w.index == 0x1600 && w.subindex == 1 && w.data.size() == 4 && w.data[3] == 0x40 && w.data[2] == 0x00)
      rpdo_map = true;
  }
  CHECK(hb && tpdo_map && rpdo_map);
  std::string dcf = read(gen.master_dcf);
  CHECK(dcf.find("UploadFile=") == std::string::npos);
  CHECK(dcf.find("[1016]") != std::string::npos);
  // An EMCY consumer for every node ID but the master's own: the slave's
  // (dcfgen's, from its EDS) and the predefined COB-ID for every other one.
  size_t at = dcf.find("[1028Value]");
  CHECK(at != std::string::npos);
  if (at != std::string::npos) {
    std::string sect = dcf.substr(at, dcf.find("\n[", at + 1) - at);
    CHECK_MSG(sect.find("NrOfEntries=126\n") != std::string::npos, sect);
    CHECK(sect.find("\n1=") == std::string::npos);
    CHECK(sect.find("\n9=0x00000089\n") != std::string::npos);
    CHECK(sect.find("\n127=0x000000FF\n") != std::string::npos);
  }

  // Unchanged inputs: dcfgen is skipped.
  GeneratedConfig again;
  CHECK_MSG(generate_device_config(cfg, "/bin/false", again, errors), join(errors));
  CHECK(again.reused);
  CHECK(again.slave_sdos[2].size() == gen.slave_sdos[2].size());

  // A changed config runs dcfgen again (and /bin/false makes that fail).
  cfg.nodes[0].heartbeat_ms = 200;
  // dcfgen writes master.bin only for a config with master-side checks
  // (such as serial_number); one from an earlier config must not survive.
  write(dir + "/.canopen/master.bin", "stale");
  GeneratedConfig changed;
  errors.clear();
  CHECK(!generate_device_config(cfg, "/bin/false", changed, errors));
  CHECK_MSG(has_error(errors, "dcfgen failed"), join(errors));
  CHECK(stat((dir + "/.canopen/master.dcf").c_str(), &st) != 0);  // stale output removed
  CHECK(stat((dir + "/.canopen/master.bin").c_str(), &st) != 0);
}

// The EDS lint (openplc_canopen_deploy.edslint): a prepared copy only when a
// correction applies, the verdict under eds_lint, and an error naming the
// install when the module cannot run.
TEST(eds_lint_prepared_copy_and_verdict) {
  set_log_sink(silent);
  std::string fixtures = FIXTURES_DIR, work = tmpdir();
  auto config = [&](const std::string& eds, const std::string& master_extra) {
    Config cfg;
    std::vector<std::string> errors;
    std::string json = replace(replace(kValid, "\"cpp-slave.eds\"", "\"" + eds + "\""),
                               "\"sync_period_us\": 10000", "\"sync_period_us\": 10000" + master_extra);
    CHECK_MSG(parse_config(json, fixtures + "/eds/canopen_config.json", ImageLimits(), cfg, errors), join(errors));
    return cfg;
  };
  std::vector<std::string> errors;

  Config plain = config("cpp-slave.eds", "");
  std::string original = plain.nodes[0].eds_path;
  CHECK_MSG(run_eds_lint(plain, default_edslint_python(), work, errors), join(errors));
  CHECK(plain.nodes[0].eds_path == original);  // nothing to correct: the original file
  CHECK(plain.warnings.empty() && plain.notes.empty());

  Config octets = config("lint/octet-string.eds", "");
  CHECK_MSG(run_eds_lint(octets, default_edslint_python(), work, errors), join(errors));
  CHECK(octets.nodes[0].eds_path == work + "/eds/node_2.eds");
  CHECK_MSG(octets.notes.size() == 1 && octets.notes[0].find("0x2051 DefaultValue was \"----\"") != std::string::npos,
            join(octets.notes));
  CHECK_MSG(check_eds_files(octets, errors), join(errors));  // Lely reads the prepared copy

  Config limits = config("lint/signed-hex.eds", "");
  CHECK_MSG(run_eds_lint(limits, default_edslint_python(), work, errors), join(errors));
  CHECK_MSG(has_warning(limits, "node 2 (pingpong): EDS lint/signed-hex.eds: 2 lint findings accepted"),
            join(limits.warnings));
  CHECK(limits.nodes[0].eds_path != work + "/eds/node_2.eds");
  struct stat st;
  CHECK(stat((work + "/eds/node_2.eds").c_str(), &st) != 0);  // the earlier copy is gone

  Config strict = config("lint/signed-hex.eds", ", \"eds_lint\": \"all\"");
  CHECK(!run_eds_lint(strict, default_edslint_python(), work, errors));
  CHECK_MSG(has_error(errors, "fails dcfgen's lint (eds_lint \"all\"): 0x6061: HighLimit overflow in [6061]"),
            join(errors));

  errors.clear();
  Config missing = config("cpp-slave.eds", "");
  CHECK(!run_eds_lint(missing, "/nonexistent/python", work, errors));
  CHECK_MSG(has_error(errors, "cannot run the EDS lint (/nonexistent/python -m openplc_canopen_deploy.edslint)") &&
                has_error(errors, "rerun scripts/install-stock.sh"),
            join(errors));
  errors.clear();
  CHECK(!run_eds_lint(missing, "/bin/false", work, errors));
  CHECK_MSG(has_error(errors, "exit status 1"), join(errors));
  set_log_sink(nullptr);
}

// Lely's EDS parser reads OCTET_STRING values as hex digits and refuses one
// that does not start with one ("----", seen in a servo drive's EDS); the prepared copy
// clears it. Fails here when a Lely update changes that rule.
TEST(lely_octet_string_rule) {
  set_log_sink(silent);
  std::string fixtures = FIXTURES_DIR, work = tmpdir();
  co_dev_t* dev = co_dev_create_from_dcf_file((fixtures + "/eds/lint/octet-string.eds").c_str());
  CHECK(dev == nullptr);
  co_dev_destroy(dev);
  Config cfg;
  std::vector<std::string> errors;
  std::string json = replace(kValid, "\"cpp-slave.eds\"", "\"lint/octet-string.eds\"");
  CHECK(parse_config(json, fixtures + "/eds/canopen_config.json", ImageLimits(), cfg, errors));
  CHECK_MSG(run_eds_lint(cfg, default_edslint_python(), work, errors), join(errors));
  dev = co_dev_create_from_dcf_file(cfg.nodes[0].eds_path.c_str());
  CHECK(dev != nullptr);
  co_dev_destroy(dev);
  set_log_sink(nullptr);
}

// Some vendor EDS files write PDO COB-IDs as "0x200+$NODEID", which dcfgen
// rejects even with --no-strict; the lint's prepared copy corrects them.
TEST(dcfgen_accepts_nodeid_suffix_eds) {
  std::string dir = tmpdir();
  std::string eds = read(std::string(PINGPONG_DIR) + "/cpp-slave.eds");
  for (const char* v : {"0x180", "0x200", "0x280", "0x300", "0x380", "0x400", "0x480", "0x500"}) {
    std::string from = std::string("DefaultValue=$NODEID+") + v, to = std::string("DefaultValue=") + v + "+$NODEID";
    for (size_t p; (p = eds.find(from)) != std::string::npos;) eds.replace(p, from.size(), to);
  }
  CHECK(eds.find("+$NODEID") != std::string::npos);
  write(dir + "/cpp-slave.eds", eds);
  Config cfg;
  std::vector<std::string> errors;
  CHECK(parse_config(kValid, dir + "/canopen_config.json", ImageLimits(), cfg, errors));
  CHECK_MSG(run_eds_lint(cfg, default_edslint_python(), dir + "/.canopen", errors), join(errors));
  CHECK_MSG(cfg.notes.size() == 1 && cfg.notes[0].find("\"<number>+$NODEID\" rewritten") != std::string::npos,
            join(cfg.notes));
  GeneratedConfig gen;
  CHECK_MSG(generate_device_config(cfg, default_dcfgen(), gen, errors), join(errors));
  CHECK(read(dir + "/cpp-slave.eds") == eds);  // the original is left alone
  struct stat st;
  CHECK(stat((dir + "/.canopen/eds/node_2.eds").c_str(), &st) == 0);
  // The slave's TPDO 1 gets the configured COB-ID 0x182.
  bool cob = false;
  for (const auto& w : gen.slave_sdos[2])
    if (w.index == 0x1800 && w.subindex == 1 && w.data.size() == 4 && w.data[0] == 0x82 && w.data[1] == 0x01) cob = true;
  CHECK(cob);
}

TEST(dcfgen_yaml_disables_unused_pdos) {
  Config cfg;
  std::vector<std::string> errors;
  std::string s = replace(kValid, ",\n      \"rx_pdos\": [ { \"entries\": [ { \"index\": \"0x4000\", \"subindex\": 0, \"type\": \"UNSIGNED32\", \"iec_location\": \"%QD100\" } ] } ]", "");
  CHECK_MSG(parse(s, cfg, errors), join(errors));
  std::string yaml = make_dcfgen_yaml(cfg, "/tmp/x");
  CHECK_MSG(yaml.find("  rpdo:\n    1:\n      enabled: false\n") != std::string::npos, yaml);
  CHECK(yaml.find("cob_id: 0x182") != std::string::npos);
}

// A device-mapped PDO gives dcfgen no mapping list (the node keeps its EDS
// mapping); an unused PDO with a read-only COB-ID is left out instead of
// switched off; the read-only COB-ID writes dcfgen still makes are dropped.
TEST(dcfgen_device_pdo_mapping) {
  set_log_sink(silent);
  std::string fixtures = FIXTURES_DIR;
  std::string json = R"({
  "adapter": { "type": "socketcan", "interface": "vcan0", "bitrate": 125000 },
  "master": { "node_id": 1, "sync_period_us": 100000 },
  "nodes": [ { "node_id": 4, "name": "io", "eds": "fixed-io.eds",
    "tx_pdos": [ { "entries": [ { "index": "0x6000", "subindex": 2, "type": "UNSIGNED8", "iec_location": "%IB40" } ] } ],
    "rx_pdos": [ { "entries": [ { "index": "0x6200", "subindex": 1, "type": "UNSIGNED8", "iec_location": "%QB40" } ] } ] } ]
})";
  Config cfg;
  std::vector<std::string> errors;
  CHECK_MSG(parse_config(json, fixtures + "/eds/canopen.json", ImageLimits(), cfg, errors, "/nonexistent") &&
                check_eds_files(cfg, errors),
            join(errors));
  const NodeConfig& n = cfg.nodes[0];
  CHECK(n.tx_pdos[0].device_mapping && n.rx_pdos[0].device_mapping);
  CHECK(n.kept_tpdos.count(2) == 1 && n.kept_tpdos.count(1) == 0 && n.kept_rpdos.empty());
  CHECK(n.ro_pdo_comm.count({0x1800, 1}) && n.ro_pdo_comm.count({0x1400, 2}));
  bool noted = false;
  for (const auto& m : cfg.notes) noted |= m == "node 4 (io): TPDO 2 is not configured, but fixed-io.eds fixes its COB-ID; it stays enabled as the node has it";
  CHECK_MSG(noted, join(cfg.notes));
  std::string yaml = make_dcfgen_yaml(cfg, "/tmp/x");
  CHECK_MSG(yaml.find("mapping:") == std::string::npos, yaml);
  CHECK_MSG(yaml.find("enabled: false") == std::string::npos, yaml);
  CHECK_MSG(yaml.find("  tpdo:\n    1:\n      enabled: true\n      cob_id: 0x184\n  rpdo:") != std::string::npos, yaml);

  // dcfgen's output: nothing left to download but no PDO or COB-ID write.
  std::string dir = tmpdir();
  write(dir + "/fixed-io.eds", read(fixtures + "/eds/fixed-io.eds"));
  write(dir + "/canopen.json", json);
  Config cfg2;
  GeneratedConfig gen;
  errors.clear();
  CHECK_MSG(load_config(dir + "/canopen.json", ImageLimits(), cfg2, errors) && check_eds_files(cfg2, errors) &&
                generate_device_config(cfg2, default_dcfgen(), gen, errors),
            join(errors));
  for (const auto& w : gen.slave_sdos[4])
    CHECK_MSG(w.index < 0x1400 || w.index > 0x1BFF, "write to " + std::to_string(w.index));
  set_log_sink(nullptr);
}

// A writable count (sub 0) with read-only entries is still a fixed mapping:
// dcfgen's entry writes would be refused.
TEST(eds_fixed_entries_writable_count) {
  set_log_sink(silent);
  std::string dir = tmpdir();
  std::string eds = read(std::string(FIXTURES_DIR) + "/eds/fixed-io.eds");
  eds = replace(eds, "[1A00sub0]\nParameterName=Number of mapped application objects in PDO\nDataType=0x0005\nAccessType=ro",
                "[1A00sub0]\nParameterName=Number of mapped application objects in PDO\nDataType=0x0005\nAccessType=rw");
  write(dir + "/fixed-io.eds", eds);
  std::string json = R"({
  "adapter": { "type": "socketcan", "interface": "vcan0", "bitrate": 125000 },
  "master": { "node_id": 1, "sync_period_us": 100000 },
  "nodes": [ { "node_id": 4, "eds": "fixed-io.eds",
    "tx_pdos": [ { "entries": [ { "index": "0x6000", "subindex": 1, "type": "UNSIGNED8", "iec_location": "%IB40" } ] } ] } ]
})";
  Config cfg;
  std::vector<std::string> errors;
  CHECK_MSG(parse_config(json, dir + "/canopen.json", ImageLimits(), cfg, errors, "/nonexistent") &&
                check_eds_files(cfg, errors),
            join(errors));
  CHECK(cfg.nodes[0].tx_pdos[0].device_mapping);
  json = replace(json, "\"tx_pdos\": [ { \"entries\"", "\"tx_pdos\": [ { \"mapping\": \"config\", \"entries\"");
  Config forced;
  errors.clear();
  CHECK(parse_config(json, dir + "/canopen.json", ImageLimits(), forced, errors, "/nonexistent"));
  CHECK(!check_eds_files(forced, errors));
  CHECK_MSG(has_error(errors, "fixes the mapping (0x1A00 subindex 1 is ro)"), join(errors));
  set_log_sink(nullptr);
}

// "device" on a writable PDO: no mapping list, the PDO keeps its COB-ID writes.
TEST(dcfgen_device_mapping_chosen) {
  Config cfg;
  std::vector<std::string> errors;
  std::string s = replace(kValid, "\"tx_pdos\": [ { \"entries\"", "\"tx_pdos\": [ { \"mapping\": \"device\", \"entries\"");
  CHECK_MSG(parse(s, cfg, errors) && check_eds_files(cfg, errors), join(errors));
  CHECK(cfg.nodes[0].tx_pdos[0].device_mapping && !cfg.nodes[0].rx_pdos[0].device_mapping);
  std::string yaml = make_dcfgen_yaml(cfg, "/tmp/x");
  size_t tpdo = yaml.find("  tpdo:"), rpdo = yaml.find("  rpdo:");
  CHECK_MSG(tpdo != std::string::npos && rpdo != std::string::npos, yaml);
  CHECK_MSG(yaml.find("mapping:", tpdo) > rpdo, yaml);  // TPDO 1 has none, RPDO 1 has one
  CHECK_MSG(yaml.find("mapping:", rpdo) != std::string::npos, yaml);
}

// Fields left out of the config keep the slave's EDS defaults: dcfgen only
// gets (and the slave only receives) what the config sets.
TEST(dcfgen_yaml_keeps_eds_defaults) {
  Config cfg;
  std::vector<std::string> errors;
  std::string s = replace(kValid, "      \"heartbeat_ms\": 500,\n", "");
  CHECK_MSG(parse(s, cfg, errors), join(errors));
  std::string yaml = make_dcfgen_yaml(cfg, "/tmp/x");
  CHECK_MSG(yaml.find("transmission:") == std::string::npos, yaml);
  CHECK_MSG(yaml.find("  heartbeat_producer:", yaml.find("node_2:")) == std::string::npos, yaml);

  s = replace(replace(kValid, "\"heartbeat_ms\": 500", "\"heartbeat_ms\": 0"), "\"rx_pdos\": [ { \"entries\"",
              "\"rx_pdos\": [ { \"transmission\": 255, \"entries\"");
  Config set;
  CHECK_MSG(parse(s, set, errors), join(errors));
  yaml = make_dcfgen_yaml(set, "/tmp/x");
  CHECK_MSG(yaml.find("      transmission: 255\n") != std::string::npos, yaml);
  CHECK_MSG(yaml.find("  heartbeat_producer: 0\n", yaml.find("node_2:")) != std::string::npos, yaml);
}

// A slave whose RPDO transmission type is fixed (the device refuses the
// write) boots when the config leaves the transmission type out.
TEST(dcfgen_unset_transmission_not_written) {
  std::string dir = tmpdir();
  std::string eds = read(std::string(PINGPONG_DIR) + "/cpp-slave.eds");
  eds = replace(eds, "[1400sub2]\nParameterName=Transmission type\nDataType=0x0005\nAccessType=rw\nDefaultValue=0x01",
                "[1400sub2]\nParameterName=Transmission type\nDataType=0x0005\nAccessType=rw\nDefaultValue=0xFF");
  write(dir + "/cpp-slave.eds", eds);
  auto writes_1400_2 = [&](const std::string& json) {
    Config cfg;
    std::vector<std::string> errors;
    CHECK(parse_config(json, dir + "/canopen_config.json", ImageLimits(), cfg, errors));
    GeneratedConfig gen;
    CHECK_MSG(generate_device_config(cfg, default_dcfgen(), gen, errors), join(errors));
    for (const auto& w : gen.slave_sdos[2])
      if (w.index == 0x1400 && w.subindex == 2) return true;
    return false;
  };
  CHECK(!writes_1400_2(kValid));
  CHECK(writes_1400_2(replace(kValid, "\"rx_pdos\": [ { \"entries\"", "\"rx_pdos\": [ { \"transmission\": 1, \"entries\"")));
}

// PDO communication fields reach dcfgen in its units; the RPDO event timer
// is left to the plugin (dcfgen 2.4.2 fails on an RPDO event_deadline).
TEST(dcfgen_yaml_pdo_timing) {
  Config cfg;
  std::vector<std::string> errors;
  std::string s = replace(kValid, "\"tx_pdos\": [ { \"entries\"",
                          "\"tx_pdos\": [ { \"transmission\": 2, \"inhibit_time_us\": 10000, \"event_timer_ms\": 0, "
                          "\"sync_start\": 3, \"entries\"");
  s = replace(s, "\"rx_pdos\": [ { \"entries\"", "\"rx_pdos\": [ { \"event_timer_ms\": 500, \"entries\"");
  CHECK_MSG(parse(s, cfg, errors), join(errors));
  std::string yaml = make_dcfgen_yaml(cfg, "/tmp/x");
  size_t tpdo = yaml.find("  tpdo:"), rpdo = yaml.find("  rpdo:");
  CHECK_MSG(yaml.find("      inhibit_time: 100\n", tpdo) < rpdo, yaml);
  CHECK_MSG(yaml.find("      event_timer: 0\n", tpdo) < rpdo, yaml);
  CHECK_MSG(yaml.find("      sync_start: 3\n", tpdo) < rpdo, yaml);
  CHECK_MSG(yaml.find("event_timer", rpdo) == std::string::npos, yaml);
  CHECK_MSG(yaml.find("event_deadline") == std::string::npos, yaml);

  Config bare;
  CHECK_MSG(parse(kValid, bare, errors), join(errors));
  yaml = make_dcfgen_yaml(bare, "/tmp/x");
  for (const char* key : {"inhibit_time", "event_timer", "sync_start"})
    CHECK_MSG(yaml.find(key) == std::string::npos, yaml);
}

// config_check: the stamp goes to 0x1020 after every other download, then the
// optional save; the master DCF gets 1F26/1F27 with the expected values.
TEST(dcfgen_config_check) {
  std::string last_dir;
  auto generate = [&last_dir](const std::string& json, GeneratedConfig& gen, bool again = false) {
    std::string dir = again ? last_dir : tmpdir();
    last_dir = dir;
    write(dir + "/cpp-slave.eds", read(std::string(FIXTURES_DIR) + "/eds/config-check.eds"));
    Config cfg;
    std::vector<std::string> errors;
    CHECK_MSG(parse_config(json, dir + "/canopen_config.json", ImageLimits(), cfg, errors), join(errors));
    CHECK_MSG(check_eds_files(cfg, errors), join(errors));
    CHECK_MSG(generate_device_config(cfg, default_dcfgen(), gen, errors), join(errors));
  };
  std::string checked = replace(kValid, "\"name\": \"pingpong\",",
                                "\"name\": \"pingpong\", \"config_check\": true, \"store_configuration\": 1,");
  GeneratedConfig gen;
  generate(checked, gen);
  const auto& w = gen.slave_sdos[2];
  CHECK(gen.config_stamps.count(2) == 1);
  auto stamp = gen.config_stamps[2];
  CHECK(stamp.first != 0 && stamp.second != 0);
  CHECK(w.size() > 3);
  if (w.size() > 3) {
    auto u32 = [](const SdoWrite& x) {
      return uint32_t(x.data[0]) | uint32_t(x.data[1]) << 8 | uint32_t(x.data[2]) << 16 | uint32_t(x.data[3]) << 24;
    };
    const SdoWrite& date = w[w.size() - 3];
    const SdoWrite& time = w[w.size() - 2];
    const SdoWrite& save = w.back();
    CHECK(date.index == 0x1020 && date.subindex == 1 && date.data.size() == 4 && u32(date) == stamp.first);
    CHECK(time.index == 0x1020 && time.subindex == 2 && time.data.size() == 4 && u32(time) == stamp.second);
    CHECK(save.index == 0x1010 && save.subindex == 1 && save.data.size() == 4 && u32(save) == 0x65766173u);
    // The stamp covers what comes before it.
    std::vector<SdoWrite> before(w.begin(), w.end() - 3);
    CHECK(config_stamp(before, 1) == stamp);
  }
  std::string dcf = read(gen.master_dcf);
  CHECK(dcf.find("\n[1F26]\n") != std::string::npos && dcf.find("\n[1F27]\n") != std::string::npos);
  CHECK(dcf.find("=0x1F26\n") != std::string::npos && dcf.find("=0x1F27\n") != std::string::npos);
  CHECK(dcf.find("CompactSubObj=127") != std::string::npos);
  auto entry = [](uint32_t v) {
    char buf[32];
    std::snprintf(buf, sizeof(buf), "\n2=0x%08X\n", v);
    return std::string("NrOfEntries=1") + buf;
  };
  CHECK(dcf.find("[1F26Value]\n" + entry(stamp.first)) != std::string::npos);
  CHECK(dcf.find("[1F27Value]\n" + entry(stamp.second)) != std::string::npos);

  // Same configuration, same stamp; another download, another stamp.
  GeneratedConfig same, changed, no_save, unchecked;
  generate(checked, same);
  CHECK(same.config_stamps[2] == stamp);
  GeneratedConfig again;
  generate(checked, again, true);  // reuses dcfgen's output; the values are replaced, not added again
  CHECK(again.reused && again.config_stamps[2] == stamp && read(again.master_dcf) == read(same.master_dcf));
  generate(replace(checked, "\"heartbeat_ms\": 500", "\"heartbeat_ms\": 200"), changed);
  CHECK(changed.config_stamps[2] != stamp);
  CHECK(read(changed.master_dcf).find("[1F26Value]\n" + entry(changed.config_stamps[2].first)) != std::string::npos);
  generate(replace(checked, " \"store_configuration\": 1,", ""), no_save);
  CHECK(no_save.config_stamps[2] != stamp);
  CHECK(!no_save.slave_sdos[2].empty() && no_save.slave_sdos[2].back().index == 0x1020);
  for (const auto& x : no_save.slave_sdos[2]) CHECK(x.index != 0x1010);

  // Without config_check: no stamp, no 0x1020 or 0x1010 writes, no 1F26.
  generate(kValid, unchecked);
  CHECK(unchecked.config_stamps.empty());
  for (const auto& x : unchecked.slave_sdos[2]) CHECK(x.index != 0x1020 && x.index != 0x1010);
  CHECK(read(unchecked.master_dcf).find("[1F26") == std::string::npos);

  // Neither half is ever 0.
  for (unsigned sub = 0; sub < 2000; ++sub) {
    auto s = config_stamp({}, sub);
    CHECK(s.first != 0 && s.second != 0);
  }
}

// The RPDO event timer goes out as an SDO after dcfgen's downloads and before
// the startup SDOs, and not at all when the EDS already has the value.
TEST(dcfgen_rpdo_event_timer_sdo) {
  std::string dir = tmpdir();
  write(dir + "/cpp-slave.eds", read(std::string(FIXTURES_DIR) + "/eds/pdo-comm.eds"));
  auto sdos = [&](const std::string& json) {
    Config cfg;
    std::vector<std::string> errors;
    CHECK_MSG(parse_config(json, dir + "/canopen_config.json", ImageLimits(), cfg, errors), join(errors));
    GeneratedConfig gen;
    CHECK_MSG(generate_device_config(cfg, default_dcfgen(), gen, errors), join(errors));
    return gen.slave_sdos[2];
  };
  std::string json = replace(with_sdo(kSdoNode), "\"rx_pdos\": [ { \"entries\"",
                             "\"rx_pdos\": [ { \"event_timer_ms\": 500, \"entries\"");
  auto w = sdos(json);
  size_t at = w.size();
  for (size_t i = 0; i < w.size(); ++i)
    if (w[i].index == 0x1400 && w[i].subindex == 5) at = i;
  CHECK(at + 2 == w.size());  // then the startup SDO
  if (at < w.size()) CHECK(w[at].data == std::vector<uint8_t>({0xF4, 0x01}));
  CHECK(w.back().index == 0x1017);
  w = sdos(replace(json, "\"event_timer_ms\": 500", "\"event_timer_ms\": 0"));  // the EDS value
  for (const auto& x : w) CHECK(!(x.index == 0x1400 && x.subindex == 5));
}

// ---------------------------------------------------------------------------
// dcfgen options (master and node)

// A configuration without the new fields gives the same YAML as before them.
TEST(dcfgen_yaml_unchanged_without_options) {
  Config cfg;
  std::vector<std::string> errors;
  CHECK_MSG(parse(kValid, cfg, errors), join(errors));
  std::string yaml = make_dcfgen_yaml(cfg, "/tmp/x");
  std::string master = yaml.substr(yaml.find("master:\n"), yaml.find("node_2:\n") - yaml.find("master:\n"));
  CHECK_MSG(master ==
                "master:\n  node_id: 1\n  baudrate: 125\n  sync_period: 10000\n  heartbeat_producer: 0\n"
                "  heartbeat_consumer: true\n  start_nodes: true\n",
            master);
  std::string node = yaml.substr(yaml.find("node_2:\n"));
  node = node.substr(node.find("  node_id:"), node.find("  tpdo:") - node.find("  node_id:"));
  CHECK_MSG(node ==
                "  node_id: 2\n  heartbeat_producer: 500\n  heartbeat_multiplier: 3.000000\n  retry_factor: 0\n"
                "  boot: true\n  mandatory: false\n",
            node);
}

const char* kAllMasterOptions =
    "\"sync_period_us\": 10000, \"heartbeat_ms\": 100, \"vendor_id\": \"0x360\", \"product_code\": 7, "
    "\"revision_number\": 2, \"serial_number\": \"0x1234\", \"sync_window_us\": 5000, "
    "\"sync_counter_overflow\": 10, \"time_cob_id\": \"0x40000100\", \"emcy_inhibit_time_us\": 1000, "
    "\"heartbeat_consumer\": false, \"heartbeat_multiplier\": 2.5, \"error_behavior\": {\"1\": 1}, "
    "\"nmt_inhibit_time_us\": 200, \"start_nodes\": false, \"start_all_nodes\": true, \"reset_all_nodes\": true, "
    "\"stop_all_nodes\": true, \"boot_time_ms\": 5000, \"state_location\": \"%IB20\"";

const char* kAllNodeOptions =
    "\"name\": \"pingpong\", \"mandatory\": true, \"boot\": false, \"reset_communication\": false, "
    "\"revision_number\": 0, \"serial_number\": \"0x5678\", \"heartbeat_consumer\": true, \"retry_factor\": 4, "
    "\"time_cob_id\": \"0x100\", \"error_behavior\": {\"1\": 2}, \"restore_configuration\": 1, "
    "\"boot_error_location\": \"%IB21\",";

TEST(dcfgen_options_parsed) {
  Config cfg;
  std::vector<std::string> errors;
  std::string s = replace(kValid, "\"sync_period_us\": 10000", kAllMasterOptions);
  s = replace(s, "\"name\": \"pingpong\",", kAllNodeOptions);
  CHECK_MSG(parse(s, cfg, errors), join(errors));
  const MasterConfig& m = cfg.master;
  CHECK(m.has_vendor_id && m.vendor_id == 0x360 && m.product_code == 7 && m.revision_number == 2);
  CHECK(m.serial_number == 0x1234 && m.sync_window_us == 5000 && m.sync_counter_overflow == 10);
  CHECK(m.time_cob_id == 0x40000100 && m.emcy_inhibit_time_us == 1000 && !m.heartbeat_consumer);
  CHECK(m.has_heartbeat_multiplier && m.heartbeat_multiplier == 2.5);
  CHECK(m.error_behavior.size() == 1 && m.error_behavior[0] == std::make_pair(1u, 1u));
  CHECK(m.nmt_inhibit_time_us == 200 && m.start && !m.start_nodes && m.start_all_nodes);
  CHECK(m.reset_all_nodes && m.stop_all_nodes && m.has_boot_time && m.boot_time_ms == 5000);
  CHECK(m.has_state_location && m.state_location.str() == "%IB20");
  const NodeConfig& n = cfg.nodes[0];
  CHECK(n.mandatory && !n.boot && n.has_reset_communication && !n.reset_communication);
  CHECK(n.has_revision_number && n.revision_number == 0 && n.serial_number == 0x5678);
  CHECK(n.has_heartbeat_consumer && n.heartbeat_consumer && n.retry_factor == 4 && n.time_cob_id == 0x100);
  CHECK(n.error_behavior.size() == 1 && n.error_behavior[0] == std::make_pair(1u, 2u));
  CHECK(n.has_restore_configuration && n.restore_configuration == 1);
  CHECK(n.has_boot_error_location && n.boot_error_location.str() == "%IB21");
  CHECK(cfg.warnings.empty());

  std::string yaml = make_dcfgen_yaml(cfg, "/tmp/x");
  for (const char* line :
       {"  vendor_id: 0x00000360\n", "  product_code: 0x00000007\n", "  serial_number: 0x00001234\n",
        "  sync_window: 5000\n", "  sync_overflow: 10\n", "  time_cob_id: 0x40000100\n", "  emcy_inhibit_time: 10\n",
        "  heartbeat_consumer: false\n", "  heartbeat_multiplier: 2.500000\n", "  error_behavior:\n    1: 1\n",
        "  nmt_inhibit_time: 2\n", "  start_nodes: false\n", "  start_all_nodes: true\n", "  reset_all_nodes: true\n",
        "  stop_all_nodes: true\n", "  boot_time: 5000\n"})
    CHECK_MSG(yaml.find(line) < yaml.find("node_2:"), line + std::string(" in\n") + yaml);
  for (const char* line :
       {"  boot: false\n", "  mandatory: true\n", "  reset_communication: false\n", "  revision_number: 0x00000000\n",
        "  serial_number: 0x00005678\n", "  heartbeat_consumer: true\n", "  retry_factor: 4\n",
        "  error_behavior:\n    1: 2\n", "  restore_configuration: 1\n"})
    CHECK_MSG(yaml.find(line, yaml.find("node_2:")) != std::string::npos, line + std::string(" in\n") + yaml);
}

TEST(boot_sdo_timeout_parsed) {
  Config cfg;
  std::vector<std::string> errors;
  CHECK_MSG(parse(kValid, cfg, errors), join(errors));
  CHECK(cfg.master.sdo_timeout_ms == 1000);
  std::string yaml = make_dcfgen_yaml(cfg, "/tmp/x");
  Config with;
  CHECK_MSG(parse(replace(kValid, "\"sync_period_us\": 10000", "\"sync_period_us\": 10000, \"sdo_timeout_ms\": 3000"),
                  with, errors),
            join(errors));
  CHECK(with.master.sdo_timeout_ms == 3000);
  CHECK_MSG(make_dcfgen_yaml(with, "/tmp/x") == yaml, "the master DCF does not carry the timeout");
  for (const char* bad : {"5", "60001"}) {
    Config c;
    errors.clear();
    CHECK(!parse(replace(kValid, "\"sync_period_us\": 10000",
                         std::string("\"sync_period_us\": 10000, \"sdo_timeout_ms\": ") + bad),
                 c, errors));
    CHECK_MSG(join(errors).find(std::string("field 'sdo_timeout_ms' must be 10-60000: ") + bad) != std::string::npos,
              join(errors));
  }
}

TEST(time_producer_parsed) {
  Config cfg;
  std::vector<std::string> errors;
  CHECK_MSG(parse(kValid, cfg, errors), join(errors));
  CHECK(cfg.master.time_period_ms == 0);
  CHECK(make_dcfgen_yaml(cfg, "/tmp/x").find("time_cob_id") == std::string::npos);
  CHECK(!has_warning(cfg, "consume"));

  Config with;
  CHECK_MSG(parse(replace(kValid, "\"sync_period_us\": 10000", "\"sync_period_us\": 10000, \"time_period_ms\": 1000"),
                  with, errors),
            join(errors));
  CHECK(with.master.time_period_ms == 1000);
  CHECK(with.master.time_producer_cob_id() == 0x100);
  std::string yaml = make_dcfgen_yaml(with, "/tmp/x");
  CHECK_MSG(yaml.find("  time_cob_id: 0x40000100\n") != std::string::npos, yaml);
  CHECK_MSG(has_warning(with, "master: the master produces TIME, but no configured node is set to consume it"),
            join(with.warnings));

  Config own;
  CHECK_MSG(parse(replace(kValid, "\"sync_period_us\": 10000",
                          "\"sync_period_us\": 10000, \"time_period_ms\": 5000, \"time_cob_id\": \"0x180\""),
                  own, errors),
            join(errors));
  CHECK(own.master.time_producer_cob_id() == 0x180);
  CHECK(make_dcfgen_yaml(own, "/tmp/x").find("  time_cob_id: 0x40000180\n") != std::string::npos);

  // Without time_period_ms a time_cob_id goes to dcfgen as given.
  Config plain;
  CHECK_MSG(parse(replace(kValid, "\"sync_period_us\": 10000", "\"sync_period_us\": 10000, \"time_cob_id\": \"0x180\""),
                  plain, errors),
            join(errors));
  CHECK(make_dcfgen_yaml(plain, "/tmp/x").find("  time_cob_id: 0x00000180\n") != std::string::npos);

  for (const char* bad : {"10", "3600001"}) {
    Config c;
    errors.clear();
    CHECK(!parse(replace(kValid, "\"sync_period_us\": 10000",
                         std::string("\"sync_period_us\": 10000, \"time_period_ms\": ") + bad),
                 c, errors));
    CHECK_MSG(join(errors).find(std::string("field 'time_period_ms' must be 100-3600000: ") + bad) != std::string::npos,
              join(errors));
  }
}

TEST(dcfgen_options_start_false_warns) {
  Config cfg;
  std::vector<std::string> errors;
  CHECK_MSG(parse(replace(kValid, "\"sync_period_us\": 10000", "\"sync_period_us\": 10000, \"start\": false"), cfg,
                  errors),
            join(errors));
  CHECK_MSG(has_warning(cfg, "master: 'start' is false: the master stays PRE-OPERATIONAL"), join(cfg.warnings));
  CHECK(make_dcfgen_yaml(cfg, "/tmp/x").find("  start: false\n") != std::string::npos);
}

TEST(dcfgen_options_rejected) {
  struct Case {
    const char* from;
    const char* to;
    const char* error;
  };
  const Case cases[] = {
      {"\"sync_period_us\": 10000", "\"sync_period_us\": 10000, \"nmt_inhibit_time_us\": 150",
       "master: field 'nmt_inhibit_time_us' must be a multiple of 100: 150"},
      {"\"sync_period_us\": 10000", "\"sync_period_us\": 10000, \"emcy_inhibit_time_us\": 50",
       "master: field 'emcy_inhibit_time_us' must be a multiple of 100: 50"},
      {"\"sync_period_us\": 10000", "\"sync_period_us\": 10000, \"sync_counter_overflow\": 1",
       "field 'sync_counter_overflow' must be 0 (no counter) or 2-240"},
      {"\"sync_period_us\": 10000", "\"sync_period_us\": 10000, \"sync_counter_overflow\": 241",
       "field 'sync_counter_overflow' is out of range (max 240)"},
      {"\"sync_period_us\": 10000", "\"sync_period_us\": 10000, \"heartbeat_multiplier\": 0.5",
       "field 'heartbeat_multiplier' must be between 1 and 100"},
      {"\"sync_period_us\": 10000", "\"sync_period_us\": 10000, \"error_behavior\": {\"0\": 1}",
       "master: error_behavior: sub-index \"0\" must be 1-254"},
      {"\"sync_period_us\": 10000", "\"sync_period_us\": 10000, \"state_location\": \"%IW20\"",
       "state_location must be an input byte (%IB...), not %IW20"},
      {"\"name\": \"pingpong\",", "\"name\": \"pingpong\", \"heartbeat_consumer\": true,",
       "nodes[0]: 'heartbeat_consumer' needs a master heartbeat"},
      {"\"name\": \"pingpong\",", "\"name\": \"pingpong\", \"software_version\": 2,",
       "node 2 (pingpong): 'software_version' needs 'software_file'"},
      {"\"name\": \"pingpong\",", "\"name\": \"pingpong\", \"software_file\": \"fw/node2.bin\",",
       "node 2 (pingpong): software_file \"fw/node2.bin\" not found"},
      {"\"name\": \"pingpong\",", "\"name\": \"pingpong\", \"state_location\": \"%IB20\", \"boot_error_location\": \"%IB20\",",
       "node 2 (pingpong) state_location and node 2 (pingpong) boot_error_location both map to %IB20"},
      {"\"sync_period_us\": 10000", "\"sync_period_us\": 10000, \"state_location\": \"%IB20\", \"bus_state_location\": \"%IB20\"",
       "master bus_state_location and master state_location both map to %IB20"},
  };
  for (const auto& c : cases) {
    Config cfg;
    std::vector<std::string> errors;
    CHECK_MSG(!parse(replace(kValid, c.from, c.to), cfg, errors), c.to);
    CHECK_MSG(has_error(errors, c.error), c.error + join(errors));
  }
}

TEST(dcfgen_options_sdo_override_warns) {
  Config cfg;
  std::vector<std::string> errors;
  std::string s = replace(with_sdo("\"sdo\": [ { \"index\": \"0x1029\", \"subindex\": 1, \"type\": \"UNSIGNED8\", "
                                   "\"value\": 0 } ],"),
                          "\"name\": \"pingpong\",", "\"name\": \"pingpong\", \"error_behavior\": {\"1\": 1},");
  CHECK_MSG(parse(s, cfg, errors), join(errors));
  CHECK_MSG(has_warning(cfg, "startup SDO to 0x1029 subindex 1 runs last and overrides error_behavior"),
            join(cfg.warnings));
}

// Through dcfgen: node settings left out write nothing to the node (the
// EDS's 0x1016 entry watching the master stays); set ones land in the node's
// concise DCF and the master's DCF.
TEST(dcfgen_options_full_run) {
  std::string dir = tmpdir();
  write(dir + "/cpp-slave.eds", read(std::string(FIXTURES_DIR) + "/eds/node-options.eds"));
  auto run = [&](const std::string& json, GeneratedConfig& gen) {
    Config cfg;
    std::vector<std::string> errors;
    CHECK_MSG(parse_config(json, dir + "/canopen_config.json", ImageLimits(), cfg, errors), join(errors));
    CHECK_MSG(generate_device_config(cfg, default_dcfgen(), gen, errors), join(errors));
  };
  auto writes = [](const GeneratedConfig& gen, uint16_t index) {
    for (const auto& w : gen.slave_sdos.at(2))
      if (w.index == index) return true;
    return false;
  };
  GeneratedConfig plain;
  run(kValid, plain);
  for (int idx : {0x1011, 0x1012, 0x1016, 0x1029}) CHECK_MSG(!writes(plain, uint16_t(idx)), std::to_string(idx));
  std::string dcf = read(plain.master_dcf);
  CHECK(dcf.find("[1F8AValue]\nNrOfEntries=0\n") != std::string::npos);

  std::string s = replace(kValid, "\"sync_period_us\": 10000",
                          "\"sync_period_us\": 10000, \"heartbeat_ms\": 100, \"sync_window_us\": 5000, "
                          "\"sync_counter_overflow\": 10, \"nmt_inhibit_time_us\": 200, \"stop_all_nodes\": true, "
                          "\"boot_time_ms\": 5000");
  s = replace(s, "\"name\": \"pingpong\",",
              "\"name\": \"pingpong\", \"mandatory\": true, \"heartbeat_consumer\": true, \"time_cob_id\": \"0x100\", "
              "\"error_behavior\": {\"1\": 2}, \"restore_configuration\": 1, \"serial_number\": \"0x5678\",");
  GeneratedConfig set;
  run(s, set);
  bool hb = false, time = false, eb = false;
  for (const auto& w : set.slave_sdos.at(2)) {
    if (w.index == 0x1016 && w.subindex == 1 && w.data == std::vector<uint8_t>({0x2C, 0x01, 0x01, 0x00})) hb = true;
    if (w.index == 0x1012 && w.data == std::vector<uint8_t>({0x00, 0x01, 0x00, 0x00})) time = true;
    if (w.index == 0x1029 && w.subindex == 1 && w.data == std::vector<uint8_t>({0x02})) eb = true;
  }
  CHECK(hb && time && eb);  // 0x1016: master 1, 3 x 100 ms
  CHECK(make_dcfgen_yaml(Config(), "/tmp/x").find("time_cob_id") == std::string::npos);
  dcf = read(set.master_dcf);
  CHECK_MSG(dcf.find("[1007]\nParameterName=Synchronous window length\nDataType=0x0007\nAccessType=rw\n"
                     "DefaultValue=5000") != std::string::npos, dcf);
  CHECK(dcf.find("DefaultValue=10\n", dcf.find("[1019]")) < dcf.find("[1028]"));
  CHECK(dcf.find("DefaultValue=2\n", dcf.find("[102A]")) != std::string::npos);
  CHECK(dcf.find("DefaultValue=5000\n", dcf.find("[1F89]")) != std::string::npos);
  // 0x1F80: master, stop all nodes (0x40); 0x1F81: listed, boot, mandatory, restore.
  CHECK_MSG(dcf.find("DefaultValue=0x00000041", dcf.find("[1F80]")) < dcf.find("[1F81]"), dcf.substr(dcf.find("[1F80]"), 400));
  CHECK_MSG(dcf.find("2=0x0000008D", dcf.find("[1F81Value]")) != std::string::npos, dcf.substr(dcf.find("[1F81Value]"), 100));
  CHECK(dcf.find("2=0x01", dcf.find("[1F8AValue]")) != std::string::npos);
  // The expected serial number goes to the master's own startup (master.bin).
  std::string bin = read(set.work_dir + "/master.bin");
  CHECK(bin.find(std::string("\x88\x1F\x02\x04\x00\x00\x00\x78\x56\x00\x00", 11)) != std::string::npos);
}

// The master downloads program files (0x1F58) itself; configuration files
// (0x1F22) stay stripped because the plugin downloads those.
TEST(dcfgen_keeps_program_upload_file) {
  std::string dir = tmpdir();
  write(dir + "/cpp-slave.eds", read(std::string(FIXTURES_DIR) + "/eds/node-options.eds"));
  mkdir((dir + "/fw").c_str(), 0755);
  write(dir + "/fw/node2.bin", "firmware");
  Config cfg;
  std::vector<std::string> errors;
  std::string s = replace(kValid, "\"name\": \"pingpong\",",
                          "\"name\": \"pingpong\", \"software_file\": \"fw/node2.bin\", \"software_version\": 2,");
  CHECK_MSG(parse_config(s, dir + "/canopen_config.json", ImageLimits(), cfg, errors), join(errors));
  CHECK(cfg.nodes[0].software_path == dir + "/fw/node2.bin");
  GeneratedConfig gen;
  CHECK_MSG(generate_device_config(cfg, default_dcfgen(), gen, errors), join(errors));
  std::string dcf = read(gen.master_dcf);
  size_t at = dcf.find("UploadFile=");
  CHECK_MSG(at != std::string::npos && dcf.rfind("[1F58sub2]", at) != std::string::npos, dcf);
  CHECK(dcf.find("UploadFile=" + dir + "/fw/node2.bin") != std::string::npos);
  CHECK(dcf.find("UploadFile=", at + 1) == std::string::npos);  // no 1F22 line
  CHECK(dcf.find("[1F22]") != std::string::npos);
}

// "auto" COB-IDs: CiA 301 defaults for PDOs 1-4, else a free COB-ID outside
// every configured node's predefined set, logged as a note.
TEST(config_auto_cob_id) {
  Config cfg;
  std::vector<std::string> errors;
  std::string s = replace(kValid, "\"tx_pdos\": [ { \"entries\"", "\"tx_pdos\": [ { \"cob_id\": \"auto\", \"entries\"");
  s = replace(s, "\"rx_pdos\": [ { \"entries\"",
              "\"rx_pdos\": [ { \"number\": 5, \"cob_id\": \"auto\", \"entries\"");
  s = replace(s, "\"%QD100\" } ] } ]",
              "\"%QD100\" } ] }, { \"number\": 6, \"cob_id\": \"auto\", \"entries\": [ { \"index\": \"0x4000\", "
              "\"type\": \"UNSIGNED32\", \"iec_location\": \"%QD104\" } ] } ]");
  CHECK_MSG(parse(s, cfg, errors), join(errors));
  const NodeConfig& n = cfg.nodes[0];
  CHECK(n.tpdo_cob_id(n.tx_pdos[0]) == 0x182);
  uint32_t a = n.rpdo_cob_id(n.rx_pdos[0]), b = n.rpdo_cob_id(n.rx_pdos[1]);
  CHECK_MSG(a == 0x57F && b == 0x57E, std::to_string(a) + " " + std::to_string(b));
  CHECK(cfg.notes.size() == 2);
  CHECK_MSG(!cfg.notes.empty() && cfg.notes[0].find("node 2 (pingpong) RPDO 5: automatic COB-ID 0x57F") != std::string::npos,
            join(cfg.notes));
  // A number above 4 without a COB-ID still needs one.
  Config none;
  std::vector<std::string> e2;
  CHECK(!parse(replace(s, "\"number\": 5, \"cob_id\": \"auto\", ", "\"number\": 5, "), none, e2));
  CHECK_MSG(has_error(e2, "RPDO 5 has no default COB-ID; set 'cob_id' (or \"auto\")"), join(e2));
}

TEST(dcfgen_missing_program) {
  std::string dir = tmpdir();
  write(dir + "/cpp-slave.eds", read(std::string(PINGPONG_DIR) + "/cpp-slave.eds"));
  Config cfg;
  std::vector<std::string> errors;
  CHECK(parse_config(kValid, dir + "/canopen_config.json", ImageLimits(), cfg, errors));
  GeneratedConfig gen;
  CHECK(!generate_device_config(cfg, "/nonexistent/dcfgen", gen, errors));
  CHECK_MSG(has_error(errors, "cannot run dcfgen"), join(errors));
}

TEST(dcfgen_startup_sdo_after_pdo_parameters) {
  std::string dir = tmpdir();
  write(dir + "/cpp-slave.eds", read(std::string(PINGPONG_DIR) + "/cpp-slave.eds"));
  Config cfg;
  std::vector<std::string> errors;
  CHECK(parse_config(replace(with_sdo(kSdoNode), "\"value\": 100", "\"value\": 250"), dir + "/canopen_config.json",
                     ImageLimits(), cfg, errors));
  GeneratedConfig gen;
  CHECK_MSG(generate_device_config(cfg, default_dcfgen(), gen, errors), join(errors));
  const auto& w = gen.slave_sdos[2];
  CHECK(!w.empty());
  if (w.empty()) return;
  // The startup SDO is the last download, after every PDO parameter.
  CHECK(w.back().index == 0x1017 && w.back().subindex == 0 && w.back().data == std::vector<uint8_t>({250, 0}));
  size_t last_pdo = 0;
  for (size_t i = 0; i < w.size(); ++i)
    if (w[i].index >= 0x1400 && w[i].index <= 0x1BFF) last_pdo = i;
  CHECK(last_pdo < w.size() - 1);
  // The startup SDOs are part of the input hash: a changed value reruns dcfgen.
  cfg.nodes[0].sdos[0].data = {100, 0};
  GeneratedConfig again;
  errors.clear();
  CHECK(!generate_device_config(cfg, "/bin/false", again, errors));
}

// ---------------------------------------------------------------------------
// Binding table and triple buffers (canopen-pdo-io)

TEST(triple_buffer_latest_wins) {
  TripleBuffer tb;
  tb.resize(2);
  bool fresh = true;
  const uint64_t* p = tb.latest(&fresh);
  CHECK(!fresh && p[0] == 0);
  tb.back()[0] = 1;
  tb.publish();
  tb.back()[0] = 2;
  tb.publish();
  p = tb.latest(&fresh);
  CHECK(fresh && p[0] == 2);
  p = tb.latest(&fresh);
  CHECK(!fresh && p[0] == 2);
  // The back buffer starts from the published data.
  tb.back()[1] = 7;
  tb.publish();
  p = tb.latest();
  CHECK(p[0] == 2 && p[1] == 7);
}

namespace {

const char* kAllSizes = R"({
  "adapter": { "type": "socketcan", "interface": "vcan0", "bitrate": 250000 },
  "master": { "node_id": 1, "sync_period_us": 10000 },
  "nodes": [ {
    "node_id": 5, "eds": "x.eds", "status_location": "%IX0.7", "state_location": "%IB9",
    "emcy_code_location": "%IW9", "error_register_location": "%IB10",
    "tx_pdos": [
      { "entries": [ { "index": "0x6000", "type": "BOOLEAN", "iec_location": "%IX1.2" },
                     { "index": "0x6001", "type": "UNSIGNED8", "iec_location": "%IB3" },
                     { "index": "0x6002", "type": "INTEGER16", "iec_location": "%IW4" },
                     { "index": "0x6003", "type": "UNSIGNED32", "iec_location": "%ID5" } ] },
      { "entries": [ { "index": "0x6004", "type": "UNSIGNED64", "iec_location": "%IL6" } ] } ],
    "rx_pdos": [
      { "entries": [ { "index": "0x7000", "type": "BOOLEAN", "iec_location": "%QX1.2" },
                     { "index": "0x7001", "type": "INTEGER8", "iec_location": "%QB3" },
                     { "index": "0x7002", "type": "UNSIGNED16", "iec_location": "%QW4" },
                     { "index": "0x7003", "type": "REAL32", "iec_location": "%QD5" } ] },
      { "entries": [ { "index": "0x7004", "type": "INTEGER64", "iec_location": "%QL6" } ] } ]
  } ]
})";

}  // namespace

TEST(binding_every_size_both_directions) {
  Config cfg;
  std::vector<std::string> errors;
  CHECK_MSG(parse_config(kAllSizes, "/tmp/c.json", ImageLimits(), cfg, errors), join(errors));
  ProcessImage img;
  img.build(cfg);
  CHECK(img.inputs().size() == 5 && img.outputs().size() == 5);

  static fake_runtime::Image fake;
  plugin_runtime_args_t rt;
  fake_runtime::attach(fake, rt);

  // Inputs: bus side sets values, cycle_start copies them to %I*.
  img.set_input(0, 1);
  img.set_input(1, 0xAB);
  img.set_input(2, 0xFFFE);  // INTEGER16 -2
  img.set_input(3, 0xDEADBEEF);
  img.set_input(4, 0x0123456789ABCDEFULL);
  img.set_node_status(5, true);
  img.set_node_state(5, 5);
  img.set_node_emcy(5, 0x4210, 0x09);
  img.copy_to_plc(rt);
  CHECK(fake.bool_in[1][2] == 0);  // not committed yet: still the old snapshot
  img.commit_inputs();
  img.copy_to_plc(rt);
  CHECK(fake.bool_in[1][2] == 1);
  CHECK(fake.byte_in[3] == 0xAB);
  CHECK(fake.int_in[4] == 0xFFFE);
  CHECK(fake.dint_in[5] == 0xDEADBEEF);
  CHECK(fake.lint_in[6] == 0x0123456789ABCDEFULL);
  CHECK(fake.bool_in[0][7] == 1);  // status bit
  CHECK(fake.byte_in[9] == 5);      // state byte: OPERATIONAL
  CHECK(fake.int_in[9] == 0x4210);  // EMCY code
  CHECK(fake.byte_in[10] == 0x09);  // error register
  CHECK(fake.journal_writes == 18);

  // Outputs: cycle_end reads %Q* into a snapshot the bus side picks up.
  fake.bool_out[1][2] = 1;
  fake.byte_out[3] = 0x80;
  fake.int_out[4] = 0x1234;
  fake.dint_out[5] = 0x3F800000;  // 1.0f
  fake.lint_out[6] = 0xFFFFFFFFFFFFFFFFULL;
  img.copy_from_plc(rt);
  CHECK(fake.locks == 1 && fake.unlocks == 1);
  const uint64_t* out = img.latest_outputs();
  CHECK(out[0] == 1 && out[1] == 0x80 && out[2] == 0x1234 && out[3] == 0x3F800000 &&
        out[4] == 0xFFFFFFFFFFFFFFFFULL);

  // Node status off: status bit goes FALSE, inputs keep their last value.
  img.set_node_status(5, false);
  img.set_node_state(5, 0);
  img.commit_inputs();
  img.copy_to_plc(rt);
  CHECK(fake.bool_in[0][7] == 0);
  CHECK(fake.byte_in[9] == 0);
  CHECK(fake.int_in[9] == 0x4210);  // the last EMCY is kept while the node is down
  CHECK(fake.dint_in[5] == 0xDEADBEEF);
}

TEST(binding_null_output_reads_zero) {
  Config cfg;
  std::vector<std::string> errors;
  CHECK(parse_config(kAllSizes, "/tmp/c.json", ImageLimits(), cfg, errors));
  ProcessImage img;
  img.build(cfg);
  static fake_runtime::Image fake;
  plugin_runtime_args_t rt;
  fake_runtime::attach(fake, rt);
  fake.int_out[4] = 99;
  fake.p_int_out[4] = nullptr;  // the program does not declare %QW4
  img.copy_from_plc(rt);
  CHECK(img.latest_outputs()[2] == 0);
}

// ---------------------------------------------------------------------------
// SDO variables and NMT command bytes (canopen-sdo-variables,
// canopen-node-supervision)

const char* kSdoVars = R"("sdo_variables": [
        { "name": "vendor", "index": "0x1018", "subindex": 1, "type": "UNSIGNED32", "direction": "read",
          "iec_location": "%ID200", "period_ms": 500, "trigger_location": "%QX20.0",
          "status_location": "%IB200", "abort_code_location": "%ID201", "timeout_ms": 250 },
        { "index": "0x4000", "type": "UNSIGNED32", "direction": "write", "iec_location": "%QD200" }
      ],
      "nmt_command_location": "%QB30",
      "status_location": "%IX10.0",)";

TEST(config_sdo_variables) {
  Config cfg;
  std::vector<std::string> errors;
  CHECK_MSG(parse(replace(kValid, "\"status_location\": \"%IX10.0\",", kSdoVars), cfg, errors), join(errors));
  if (cfg.nodes.empty()) return;
  const NodeConfig& n = cfg.nodes[0];
  CHECK(n.has_nmt_command_location && n.nmt_command_location.str() == "%QB30");
  CHECK(n.sdo_variables.size() == 2);
  if (n.sdo_variables.size() != 2) return;
  const SdoVariable& r = n.sdo_variables[0];
  CHECK(r.is_read() && r.index == 0x1018 && r.subindex == 1 && r.type == CoType::UNSIGNED32);
  CHECK(r.location.str() == "%ID200" && r.period_ms == 500 && r.timeout_ms == 250);
  CHECK(r.has_trigger && r.trigger_location.str() == "%QX20.0");
  CHECK(r.has_status && r.status_location.str() == "%IB200");
  CHECK(r.has_abort_code && r.abort_code_location.str() == "%ID201");
  CHECK(r.label() == "SDO variable 0x1018:1 (vendor)");
  const SdoVariable& w = n.sdo_variables[1];
  CHECK(!w.is_read() && w.timeout_ms == 1000 && !w.has_trigger && !w.has_status && w.period_ms == 0);
  CHECK_MSG(cfg.warnings.empty(), join(cfg.warnings));
  CHECK_MSG(check_eds_files(cfg, errors), join(errors));
}

TEST(config_sdo_variable_rejections) {
  struct Case {
    const char* entry;
    const char* message;
  } cases[] = {
      {R"({ "index": "0x4000", "type": "UNSIGNED32", "direction": "write", "iec_location": "%ID200" })",
       "a write entry needs an output location (%Q...), not %ID200"},
      {R"({ "index": "0x4001", "type": "UNSIGNED32", "direction": "read", "iec_location": "%QD200" })",
       "a read entry needs an input location (%I...), not %QD200"},
      {R"({ "index": "0x4001", "type": "UNSIGNED32", "direction": "read", "iec_location": "%IW200" })",
       "type UNSIGNED32 (32 bit) does not fit location %IW200 (16 bit)"},
      {R"({ "index": "0x4000", "type": "UNSIGNED32", "direction": "write", "iec_location": "%QD200", "period_ms": 100 })",
       "field 'period_ms' is only for read entries"},
      {R"({ "index": "0x4001", "type": "UNSIGNED32", "direction": "read", "iec_location": "%ID200", "period_ms": 5 })",
       "field 'period_ms' must be 10 or more"},
      {R"({ "index": "0x4001", "type": "UNSIGNED32", "direction": "read", "iec_location": "%ID200", "timeout_ms": 70000 })",
       "field 'timeout_ms' must be 10-60000"},
      {R"({ "index": "0x4001", "type": "UNSIGNED32", "direction": "sideways", "iec_location": "%ID200" })",
       "field 'direction' must be \"read\" or \"write\""},
      {R"({ "index": "0x4001", "type": "UNSIGNED32", "direction": "read", "iec_location": "%ID200", "trigger_location": "%IX20.0" })",
       "trigger_location must be an output bit (%QX...)"},
      {R"({ "index": "0x4001", "type": "UNSIGNED32", "direction": "read", "iec_location": "%ID200", "status_location": "%IW20" })",
       "status_location must be an input byte (%IB...)"},
      {R"({ "index": "0x4001", "type": "UNSIGNED32", "direction": "read", "iec_location": "%ID200", "abort_code_location": "%IW20" })",
       "abort_code_location must be an input double word (%ID...)"},
      {R"({ "index": "0x4001", "type": "UNSIGNED32", "direction": "read", "iec_location": "%ID100" })",
       "SDO variable 0x4001:0 and"},
      {R"({ "index": "0x4001", "type": "UNSIGNED32", "direction": "read" })", "missing required field 'iec_location'"},
  };
  for (const auto& c : cases) {
    Config cfg;
    std::vector<std::string> errors;
    std::string field = std::string("\"sdo_variables\": [") + c.entry + "], \"status_location\": \"%IX10.0\",";
    CHECK_MSG(!parse(replace(kValid, "\"status_location\": \"%IX10.0\",", field), cfg, errors), c.message);
    CHECK_MSG(has_error(errors, c.message), std::string(c.message) + join(errors));
    CHECK_MSG(has_error(errors, "nodes[0]: sdo_variables[0]") || has_error(errors, "both map to"), join(errors));
  }
}

TEST(config_nmt_command_location) {
  for (const char* bad : {"%IB30", "%QW30", "%QX30.0"}) {
    Config cfg;
    std::vector<std::string> errors;
    CHECK(!parse(replace(kValid, "\"status_location\": \"%IX10.0\",",
                         std::string("\"nmt_command_location\": \"") + bad + "\", \"status_location\": \"%IX10.0\","),
                 cfg, errors));
    CHECK_MSG(has_error(errors, "node 2 (pingpong): nmt_command_location must be an output byte (%QB...)"),
              join(errors));
  }
  // Overlaps a write entry's byte.
  Config cfg;
  std::vector<std::string> errors;
  CHECK(!parse(replace(kValid, "\"status_location\": \"%IX10.0\",",
                       R"("nmt_command_location": "%QB30", "sdo_variables": [ { "index": "0x1017", "type": "UNSIGNED8",
                          "direction": "write", "iec_location": "%QB30" } ],)"),
               cfg, errors));
  CHECK_MSG(has_error(errors, "nmt_command_location and node 2 (pingpong) SDO variable 0x1017:0 both map to %QB30"),
            join(errors));
}

TEST(config_sdo_variable_plugin_owned_write_warns) {
  Config cfg;
  std::vector<std::string> errors;
  CHECK_MSG(parse(replace(kValid, "\"status_location\": \"%IX10.0\",",
                          R"("sdo_variables": [
                               { "index": "0x1017", "type": "UNSIGNED16", "direction": "write", "iec_location": "%QW200" },
                               { "index": "0x1017", "type": "UNSIGNED16", "direction": "read", "iec_location": "%IW200" },
                               { "index": "0x2000", "type": "UNSIGNED16", "direction": "write", "iec_location": "%QW201" } ],)"),
                  cfg, errors),
            join(errors));
  CHECK_MSG(cfg.warnings.size() == 1, join(cfg.warnings));
  CHECK_MSG(has_warning(cfg, "node 2 (pingpong): SDO variable 0x1017:0 writes an object the plugin configures "
                             "itself; the program can override the node's heartbeat setting"),
            join(cfg.warnings));
}

TEST(eds_sdo_variables_checked) {
  Config cfg;
  std::vector<std::string> errors;
  CHECK(parse(replace(kValid, "\"status_location\": \"%IX10.0\",",
                      R"("sdo_variables": [
                           { "index": "0x1018", "subindex": 1, "type": "UNSIGNED32", "direction": "write", "iec_location": "%QD200" },
                           { "index": "0x1018", "subindex": 1, "type": "UNSIGNED16", "direction": "read", "iec_location": "%IW200" },
                           { "index": "0x2100", "type": "UNSIGNED8", "direction": "read", "iec_location": "%IB200" } ],)"),
              cfg, errors));
  CHECK(!check_eds_files(cfg, errors));
  CHECK_MSG(has_error(errors, "node 2, index 0x1018, subindex 1: SDO variable to write needs a writable object "
                              "(AccessType wo, rw, rwr or rww), but its AccessType is ro"),
            join(errors));
  CHECK_MSG(has_error(errors, "node 2, index 0x1018, subindex 1: configured type UNSIGNED16 does not match the EDS "
                              "data type UNSIGNED32"),
            join(errors));
  CHECK_MSG(has_error(errors, "node 2, index 0x2100, subindex 0: object is not defined in cpp-slave.eds"),
            join(errors));
}

TEST(binding_sdo_variables_and_nmt) {
  Config cfg;
  std::vector<std::string> errors;
  CHECK_MSG(parse(replace(kValid, "\"status_location\": \"%IX10.0\",", kSdoVars), cfg, errors), join(errors));
  ProcessImage img;
  img.build(cfg);
  CHECK(img.sdo_vars().size() == 2 && img.has_nmt_command(2));
  static fake_runtime::Image fake;
  plugin_runtime_args_t rt;
  fake_runtime::attach(fake, rt);

  // Nothing published yet: the scan count reads 0.
  CHECK(img.scan_count(img.latest_outputs()) == 0);

  // Inputs: value, status and abort code of the read entry.
  img.set_sdo_value(0, 0x360);
  img.set_sdo_status(0, 3);
  img.set_sdo_abort(0, 0x05040000);
  img.commit_inputs();
  img.copy_to_plc(rt);
  CHECK(fake.dint_in[200] == 0x360 && fake.byte_in[200] == 3 && fake.dint_in[201] == 0x05040000);

  // Outputs: the write entry's value; a one-scan trigger pulse counts once.
  fake.dint_out[200] = 1234;
  fake.bool_out[20][0] = 1;
  fake.byte_out[30] = 2;
  img.copy_from_plc(rt);
  fake.bool_out[20][0] = 0;
  img.copy_from_plc(rt);
  const uint64_t* snap = img.latest_outputs();
  CHECK(img.scan_count(snap) == 2);
  CHECK(img.sdo_out_value(snap, 1) == 1234);
  CHECK(img.sdo_trigger_count(snap, 0) == 1);
  uint8_t level = 0, code = 0;
  uint64_t resets = 0;
  CHECK(img.nmt_command(snap, 2, level, resets, code) && level == 2 && resets == 0);

  // 0 -> 129 -> 0 within two scans: one reset request, code 129. Holding 130
  // counts once.
  fake.byte_out[30] = 129;
  img.copy_from_plc(rt);
  fake.byte_out[30] = 0;
  img.copy_from_plc(rt);
  snap = img.latest_outputs();
  CHECK(img.nmt_command(snap, 2, level, resets, code) && level == 0 && resets == 1 && code == 129);
  fake.byte_out[30] = 130;
  for (int i = 0; i < 3; ++i) img.copy_from_plc(rt);
  snap = img.latest_outputs();
  CHECK(img.nmt_command(snap, 2, level, resets, code) && level == 130 && resets == 2 && code == 130);
  // Held TRUE: no new edge.
  fake.bool_out[20][0] = 1;
  for (int i = 0; i < 3; ++i) img.copy_from_plc(rt);
  CHECK(img.sdo_trigger_count(img.latest_outputs(), 0) == 2);
}


// ---------------------------------------------------------------------------
// Diagnostics channel: token hash, config, the TCP server
// (canopen-online-diagnostics)

TEST(sha256_vectors) {
  CHECK(sha256_hex("") == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
  CHECK(sha256_hex("abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
  CHECK(sha256_hex("abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq") ==
        "248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1");
  CHECK(sha256_hex(std::string(1000000, 'a')) == "cdc76e5c9914fb9281a1c7e284d73e67f1809a48a497200e046d39ccc7112cd0");
  CHECK(equal_constant_time("abc", "abc") && !equal_constant_time("abc", "abd") && !equal_constant_time("ab", "abc"));
}

TEST(config_diagnostics_defaults_and_fields) {
  Config cfg;
  std::vector<std::string> errors;
  std::string h = sha256_hex("secret");
  CHECK(parse(replace(kValid, "\"sync_period_us\": 10000", "\"sync_period_us\": 10000, \"diagnostics\": { \"token_sha256\": \"" + h + "\" }"),
              cfg, errors));
  CHECK(cfg.master.has_diagnostics && cfg.master.diag_token_sha256 == h);
  CHECK(cfg.master.diag_port == 7531 && cfg.master.diag_bind == "0.0.0.0" && !cfg.master.diag_allow_changes);
  Config cfg2;
  CHECK(parse(replace(kValid, "\"sync_period_us\": 10000",
                      "\"sync_period_us\": 10000, \"diagnostics\": { \"token_sha256\": \"" + sha256_hex("x").substr(0, 0) +
                          "9F86D081884C7D659A2FEAA0C55AD015A3BF4F1B2B0B822CD15D6C15B0F00A08\", \"port\": 9000, \"bind\": "
                          "\"127.0.0.1\", \"allow_changes\": true }"),
              cfg2, errors));
  CHECK(cfg2.master.diag_token_sha256 == "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08");
  CHECK(cfg2.master.diag_port == 9000 && cfg2.master.diag_bind == "127.0.0.1" && cfg2.master.diag_allow_changes);
  Config cfg3;
  CHECK(!parse(replace(kValid, "\"sync_period_us\": 10000", "\"sync_period_us\": 10000, \"diagnostics\": true"), cfg3,
               errors));
  CHECK(has_error(errors, "master: field 'diagnostics' must be an object"));
}

TEST(config_file_fingerprint) {
  std::string dir = tmpdir();
  std::string path = dir + "/canopen.json";
  std::ofstream(path) << kValid;
  std::ofstream(dir + "/cpp-slave.eds") << read(std::string(PINGPONG_DIR) + "/cpp-slave.eds");
  Config cfg;
  std::vector<std::string> errors;
  CHECK(load_config(path, ImageLimits(), cfg, errors));
  CHECK(cfg.file_sha256 == sha256_hex(kValid));
}

namespace {

// A blocking test client for the diagnostics server.
struct DiagClient {
  int fd = -1;
  std::string buf;
  explicit DiagClient(unsigned port, int rcvbuf = 0) {
    fd = socket(AF_INET, SOCK_STREAM, 0);
    if (rcvbuf) setsockopt(fd, SOL_SOCKET, SO_RCVBUF, &rcvbuf, sizeof rcvbuf);
    sockaddr_in a{};
    a.sin_family = AF_INET;
    a.sin_port = htons(static_cast<uint16_t>(port));
    inet_pton(AF_INET, "127.0.0.1", &a.sin_addr);
    if (connect(fd, reinterpret_cast<sockaddr*>(&a), sizeof a) != 0) {
      close(fd);
      fd = -1;
    }
  }
  ~DiagClient() {
    if (fd >= 0) close(fd);
  }
  bool send_line(const std::string& line) {
    std::string l = line + "\n";
    return ::send(fd, l.data(), l.size(), MSG_NOSIGNAL) == static_cast<ssize_t>(l.size());
  }
  // The next line, "" on timeout, "<closed>" when the server closed.
  std::string line(int timeout_ms = 3000) {
    auto end = std::chrono::steady_clock::now() + std::chrono::milliseconds(timeout_ms);
    for (;;) {
      size_t nl = buf.find('\n');
      if (nl != std::string::npos) {
        std::string l = buf.substr(0, nl);
        buf.erase(0, nl + 1);
        return l;
      }
      int left = static_cast<int>(
          std::chrono::duration_cast<std::chrono::milliseconds>(end - std::chrono::steady_clock::now()).count());
      if (left <= 0) return "";
      pollfd p{fd, POLLIN, 0};
      if (poll(&p, 1, left) <= 0) return "";
      char tmp[4096];
      ssize_t n = recv(fd, tmp, sizeof tmp, 0);
      if (n <= 0) return "<closed>";
      buf.append(tmp, static_cast<size_t>(n));
    }
  }
  std::string ask(const std::string& req) {
    send_line(req);
    return line();
  }
};

std::vector<std::string> g_diag_log;
std::mutex g_diag_log_mutex;
void diag_capture(LogLevel, const char* msg) {
  std::lock_guard<std::mutex> lock(g_diag_log_mutex);
  g_diag_log.push_back(msg);
}
size_t diag_log_count(const std::string& needle) {
  std::lock_guard<std::mutex> lock(g_diag_log_mutex);
  size_t n = 0;
  for (const auto& l : g_diag_log) n += l.find(needle) != std::string::npos;
  return n;
}

Config diag_config(bool allow_changes) {
  Config cfg;
  std::vector<std::string> errors;
  parse(kValid, cfg, errors);
  cfg.file_sha256 = sha256_hex("config");
  cfg.master.has_diagnostics = true;
  cfg.master.diag_token_sha256 = sha256_hex("secret");
  cfg.master.diag_port = 0;  // any free port
  cfg.master.diag_bind = "127.0.0.1";
  cfg.master.diag_allow_changes = allow_changes;
  return cfg;
}

bool wait_port(DiagServer& s) {
  for (int i = 0; i < 200 && !s.port(); ++i) std::this_thread::sleep_for(std::chrono::milliseconds(5));
  return s.port() != 0;
}

}  // namespace

TEST(diag_server_token_and_offline_answers) {
  {
    std::lock_guard<std::mutex> lock(g_diag_log_mutex);
    g_diag_log.clear();
  }
  set_log_sink(diag_capture);
  Config cfg = diag_config(false);
  DiagHub hub(cfg, "test-1");
  DiagServer server(hub);
  server.start();
  CHECK(wait_port(server));
  CHECK(diag_log_count("diagnostics listen on 127.0.0.1:") == 1 && diag_log_count("read-only") == 1);

  // Wrong token: closed without an answer, logged once per minute.
  {
    DiagClient c(server.port());
    c.send_line(R"({"op":"hello","token":"guess"})");
    CHECK(c.line() == "<closed>");
  }
  {
    DiagClient c(server.port());
    c.send_line(R"({"op":"status"})");  // no hello first
    CHECK(c.line() == "<closed>");
  }
  CHECK(diag_log_count("diagnostics: connection from 127.0.0.1 refused: wrong token") == 1);

  DiagClient c(server.port());
  std::string hello = c.ask(R"({"op":"hello","token":"secret","id":1})");
  CHECK_MSG(hello.find("\"ok\":true") != std::string::npos && hello.find("\"protocol\":1") != std::string::npos &&
                hello.find("\"allow_changes\":false") != std::string::npos && hello.find("\"id\":1") != std::string::npos,
            hello);
  // No bus session: status says so, the rest is refused.
  std::string st = c.ask(R"({"op":"status","id":"a"})");
  CHECK_MSG(st.find("\"session\":false") != std::string::npos && st.find("\"node_id\":2") != std::string::npos &&
                st.find("\"id\":\"a\"") != std::string::npos,
            st);
  CHECK(c.ask(R"({"op":"sdo_read","node":2,"index":"0x1000","subindex":0})").find("no bus") != std::string::npos);
  CHECK(c.ask(R"({"op":"scan"})").find("no bus") != std::string::npos);
  // Changes are refused in read-only mode, whatever the bus.
  CHECK(c.ask(R"({"op":"sdo_write","node":2,"index":"0x2000","subindex":1,"data":"01"})").find("changes not allowed") !=
        std::string::npos);
  CHECK(c.ask(R"({"op":"nmt","node":2,"command":"stop"})").find("changes not allowed") != std::string::npos);
  // So is every LSS request, even one that stores nothing.
  CHECK(c.ask(R"({"op":"lss_find"})").find("changes not allowed") != std::string::npos);
  CHECK(c.ask(R"({"op":"lss_inquire","vendor_id":1,"product_code":2,"revision_number":3,"serial_number":4})")
            .find("changes not allowed") != std::string::npos);
  CHECK(c.ask(R"({"op":"lss_set_id","vendor_id":1,"product_code":2,"revision_number":3,"serial_number":4,"node":40})")
            .find("changes not allowed") != std::string::npos);
  CHECK(c.ask(R"({"op":"lss_set_bitrate","vendor_id":1,"product_code":2,"revision_number":3,"serial_number":4,)"
              R"("bitrate_kbit":250,"store":true})")
            .find("changes not allowed") != std::string::npos);
  CHECK(c.ask(R"({"op":"lss_set_bitrate","vendor_id":1,"product_code":2,"revision_number":3,"serial_number":4,)"
              R"("bitrate_kbit":100})")
            .find("field 'bitrate_kbit' must be 10, 20, 50, 125, 250, 500, 800 or 1000") != std::string::npos);
  CHECK(c.ask(R"({"op":"lss_set_id","vendor_id":1,"product_code":2,"revision_number":3,"serial_number":4,"node":1})")
            .find("is the master itself") != std::string::npos);
  // Bad requests get an error and the connection stays usable.
  CHECK(c.ask("not json").find("not a JSON object") != std::string::npos);
  CHECK(c.ask(R"({"op":"frobnicate"})").find("unknown op 'frobnicate'") != std::string::npos);
  CHECK(c.ask(R"({"op":"sdo_read","node":1,"index":4096,"subindex":0})").find("is the master itself") !=
        std::string::npos);
  CHECK(c.ask(R"({"op":"sdo_read","node":2,"index":4096,"subindex":0,"timeout_ms":5})").find("timeout_ms") !=
        std::string::npos);
  CHECK(c.ask(R"({"op":"emcy","node":9})").find("not in the configuration") != std::string::npos);
  CHECK(c.ask(R"({"op":"status"})").find("\"ok\":true") != std::string::npos);
  // An over-long line ends the connection.
  c.send_line(std::string(DiagServer::kMaxLine + 10, 'x'));
  CHECK(c.line().find("request line too long") != std::string::npos);
  CHECK(c.line() == "<closed>");
  server.stop();
  set_log_sink(nullptr);
}

TEST(config_simulate_switches) {
  Config cfg;
  std::vector<std::string> errors;
  // Old configs are unchanged: nothing simulated.
  CHECK(parse(kValid, cfg, errors));
  CHECK(!cfg.adapter.simulate && !cfg.nodes[0].simulate && !simulates_anything(cfg));
  // A simulated network simulates every node by default; the adapter is still checked.
  std::string sim = replace(kValid, "\"bitrate\": 125000 }", "\"bitrate\": 125000, \"simulate\": true }");
  CHECK(parse(sim, cfg, errors));
  CHECK(cfg.adapter.simulate && cfg.nodes[0].simulate && simulates_anything(cfg));
  CHECK(parse(replace(sim, "\"name\": \"pingpong\",", "\"name\": \"pingpong\", \"simulate\": false,"), cfg, errors));
  CHECK(cfg.adapter.simulate && !cfg.nodes[0].simulate);
  errors.clear();
  CHECK(!parse(replace(sim, "\"bitrate\": 125000", "\"bitrate\": 123"), cfg, errors));
  // One simulated node on a real network.
  errors.clear();
  CHECK(parse(replace(kValid, "\"name\": \"pingpong\",", "\"name\": \"pingpong\", \"simulate\": true,"), cfg, errors));
  CHECK(!cfg.adapter.simulate && cfg.nodes[0].simulate && simulates_anything(cfg));
  errors.clear();
  CHECK(!parse(replace(kValid, "\"name\": \"pingpong\",", "\"name\": \"pingpong\", \"simulate\": 1,"), cfg, errors));
}

TEST(config_force_simulate) {
  // Only exactly "1" forces.
  CHECK(force_simulate_from_env("1"));
  CHECK(!force_simulate_from_env(nullptr) && !force_simulate_from_env("") && !force_simulate_from_env("0") &&
        !force_simulate_from_env("true") && !force_simulate_from_env("1 "));
  Config cfg;
  std::vector<std::string> errors;
  ImageLimits forced;
  forced.force_simulate = true;
  const std::string path = std::string(PINGPONG_DIR) + "/canopen_config.json";
  // A real-adapter config runs simulated, every node with it; the file's adapter is kept.
  CHECK(parse_config(kValid, path, forced, cfg, errors));
  CHECK(cfg.adapter.simulate && cfg.adapter.simulation_forced && cfg.nodes[0].simulate);
  CHECK(cfg.adapter.interface == "vcan0");
  // A node switched off stays absent, as on any simulated network.
  CHECK(parse_config(replace(kValid, "\"name\": \"pingpong\",", "\"name\": \"pingpong\", \"simulate\": false,"), path,
                     forced, cfg, errors));
  CHECK(cfg.adapter.simulate && !cfg.nodes[0].simulate);
  // Without the flag nothing changes.
  CHECK(parse(kValid, cfg, errors));
  CHECK(!cfg.adapter.simulate && !cfg.adapter.simulation_forced);
}

TEST(sim_trace_tap) {
  auto tap = std::make_shared<SimTraceTap>();
  auto src = make_sim_trace_source(tap);
  can_msg m = CAN_MSG_INIT;
  m.id = 0x702;
  m.len = 1;
  m.data[0] = 5;
  tap->push(m);  // no trace: not kept
  CHECK(src->open("simulated", {}, false) == 0 && src->fd() >= 0);
  tap->push(m);
  m.id = 0x182;
  m.len = 4;
  tap->push(m);
  std::vector<TraceRecord> got;
  uint64_t drops = 0;
  CHECK(src->drain(got, drops));
  CHECK(got.size() == 2 && got[0].id == 0x702 && got[0].dlc == 1 && got[0].data[0] == 5 && got[1].id == 0x182);
  CHECK(drops == 0 && got[0].time_us > 0);
  src->close();
  tap->push(m);
  got.clear();
  CHECK(src->open("simulated", {}, false) == 0);
  CHECK(src->drain(got, drops) && got.empty());
  src->close();
}

TEST(diag_server_sim_ops) {
  set_log_sink(diag_capture);
  // Nothing simulated: every sim_ request says so.
  {
    Config cfg = diag_config(true);
    DiagHub hub(cfg, "test-1");
    DiagServer server(hub);
    server.start();
    CHECK(wait_port(server));
    DiagClient c(server.port());
    c.ask(R"({"op":"hello","token":"secret"})");
    CHECK(c.ask(R"({"op":"sim_status"})").find("nothing simulated") != std::string::npos);
    CHECK(c.ask(R"({"op":"sim_set","node":2,"values":{"0x2000":1}})").find("nothing simulated") != std::string::npos);
    std::string st = c.ask(R"({"op":"status"})");
    CHECK_MSG(st.find("\"simulated_network\":false") != std::string::npos && st.find("\"simulated\":false") != std::string::npos, st);
    server.stop();
  }
  // A simulated network, read-only: reads go to the bus thread (no bus here),
  // changes are refused at once.
  {
    Config cfg = diag_config(false);
    cfg.adapter.simulate = true;
    for (auto& n : cfg.nodes) n.simulate = true;
    DiagHub hub(cfg, "test-1");
    DiagServer server(hub);
    server.start();
    CHECK(wait_port(server));
    DiagClient c(server.port());
    c.ask(R"({"op":"hello","token":"secret"})");
    CHECK(c.ask(R"({"op":"sim_status"})").find("no bus") != std::string::npos);
    CHECK(c.ask(R"({"op":"sim_get","items":[{"node":2,"object":"0x1000"}]})").find("no bus") != std::string::npos);
    CHECK(c.ask(R"({"op":"sim_check_expr","node":2,"expr":"1"})").find("no bus") != std::string::npos);
    for (const char* op : {"sim_set", "sim_override", "sim_release", "sim_source", "sim_fault", "sim_clear",
                           "sim_scenario_start", "sim_scenario_stop"})
      CHECK_MSG(c.ask(std::string(R"({"op":")") + op + R"(","node":2})").find("changes not allowed") != std::string::npos, op);
    std::string st = c.ask(R"({"op":"status"})");
    CHECK_MSG(st.find("\"simulated_network\":true") != std::string::npos &&
                  st.find("\"interface\":\"simulated\"") != std::string::npos && st.find("\"simulated\":true") != std::string::npos,
              st);
    server.stop();
  }
  set_log_sink(nullptr);
}

TEST(diag_server_client_limit_and_stalled_client) {
  set_log_sink(diag_capture);
  Config cfg = diag_config(true);
  DiagHub hub(cfg, "test");
  DiagServer server(hub);
  server.start();
  CHECK(wait_port(server));
  std::vector<std::unique_ptr<DiagClient>> clients;
  for (unsigned i = 0; i < DiagServer::kMaxClients; ++i) {
    clients.emplace_back(new DiagClient(server.port()));
    CHECK(clients.back()->ask(R"({"op":"hello","token":"secret"})").find("\"allow_changes\":true") !=
          std::string::npos);
  }
  {
    DiagClient fifth(server.port());
    CHECK(fifth.line().find("too many clients") != std::string::npos);
    CHECK(fifth.line() == "<closed>");
  }
  for (auto& c : clients) CHECK(c->ask(R"({"op":"status"})").find("\"ok\":true") != std::string::npos);
  // Changes allowed, still no bus.
  CHECK(clients[0]->ask(R"({"op":"nmt","node":2,"command":"stop"})").find("no bus") != std::string::npos);
  CHECK(clients[0]->ask(R"({"op":"nmt","node":9,"command":"stop"})").find("not in the configuration") !=
        std::string::npos);
  clients.clear();

  // A client that sends many requests and never reads: closed once the
  // server's send buffer is full; others keep working.
  DiagClient stalled(server.port(), 4096);
  stalled.send_line(R"({"op":"hello","token":"secret"})");
  std::string many;
  for (int i = 0; i < 40000; ++i) many += "{\"op\":\"status\"}\n";
  for (size_t off = 0; off < many.size();) {
    pollfd p{stalled.fd, POLLOUT, 0};
    if (poll(&p, 1, 2000) <= 0) break;
    ssize_t n = ::send(stalled.fd, many.data() + off, many.size() - off, MSG_NOSIGNAL | MSG_DONTWAIT);
    if (n <= 0) break;
    off += static_cast<size_t>(n);
  }
  bool closed = false;
  for (int i = 0; i < 400 && !closed; ++i) {
    std::this_thread::sleep_for(std::chrono::milliseconds(10));
    closed = diag_log_count("does not read its answers") > 0;
  }
  CHECK(closed);
  DiagClient other(server.port());
  CHECK(other.ask(R"({"op":"hello","token":"secret"})").find("\"ok\":true") != std::string::npos);
  server.stop();
  set_log_sink(nullptr);
}

TEST(diag_server_port_in_use) {
  {
    std::lock_guard<std::mutex> lock(g_diag_log_mutex);
    g_diag_log.clear();
  }
  set_log_sink(diag_capture);
  int blocker = socket(AF_INET, SOCK_STREAM, 0);
  sockaddr_in a{};
  a.sin_family = AF_INET;
  inet_pton(AF_INET, "127.0.0.1", &a.sin_addr);
  CHECK(bind(blocker, reinterpret_cast<sockaddr*>(&a), sizeof a) == 0 && listen(blocker, 1) == 0);
  socklen_t len = sizeof a;
  getsockname(blocker, reinterpret_cast<sockaddr*>(&a), &len);
  Config cfg = diag_config(false);
  cfg.master.diag_port = ntohs(a.sin_port);
  DiagHub hub(cfg, "test");
  DiagServer server(hub);
  server.start();
  std::this_thread::sleep_for(std::chrono::milliseconds(200));
  CHECK(server.port() == 0);
  CHECK(diag_log_count("diagnostics: cannot listen on 127.0.0.1:" + std::to_string(cfg.master.diag_port)) == 1);
  close(blocker);
  server.stop();
  set_log_sink(nullptr);
}


// ---------------------------------------------------------------------------
// Trace capture (canopen-online-diagnostics: frame capture, trace operations)

namespace {

TraceRecord rec(uint32_t id, uint64_t t, bool tx = false) {
  TraceRecord r;
  r.id = id;
  r.time_us = t;
  r.dlc = 2;
  r.data[0] = static_cast<uint8_t>(id);
  r.data[1] = static_cast<uint8_t>(t);
  if (tx) r.flags = kTraceTx;
  return r;
}

// Frames written into a pipe by the test; "present" models the interface.
struct FakeTraceSource : TraceSource {
  int p[2] = {-1, -1};
  std::atomic<bool>* present;
  std::atomic<int>* opens;
  std::vector<TraceFilter>* last_filters;
  FakeTraceSource(std::atomic<bool>* pr, std::atomic<int>* op, std::vector<TraceFilter>* lf)
      : present(pr), opens(op), last_filters(lf) {}
  ~FakeTraceSource() override { close(); }
  int open(const std::string&, const std::vector<TraceFilter>& f, bool) override {
    if (!*present) return -ENODEV;
    if (pipe2(p, O_NONBLOCK | O_CLOEXEC) != 0) return -errno;
    ++*opens;
    *last_filters = f;
    return 0;
  }
  int set_filters(const std::vector<TraceFilter>& f, bool) override {
    *last_filters = f;
    return 0;
  }
  int fd() const override { return p[0]; }
  bool drain(std::vector<TraceRecord>& out, uint64_t& drops) override {
    TraceRecord r;
    while (::read(p[0], &r, sizeof r) == static_cast<ssize_t>(sizeof r)) out.push_back(r);
    drops = 3;
    return present->load();
  }
  void close() override {
    for (int& fd : p) {
      if (fd >= 0) ::close(fd);
      fd = -1;
    }
  }
  void put(const TraceRecord& r) {
    ssize_t n = ::write(p[1], &r, sizeof r);
    (void)n;
  }
};

std::vector<TraceRecord> decode_frames(const std::string& line) {
  std::string key = "\"frames\":\"";
  size_t a = line.find(key);
  std::vector<TraceRecord> out;
  if (a == std::string::npos) return out;
  a += key.size();
  std::string b64 = line.substr(a, line.find('"', a) - a);
  static const std::string t = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
  std::vector<uint8_t> bytes;
  uint32_t acc = 0;
  int bits = 0;
  for (char ch : b64) {
    if (ch == '=') break;
    acc = (acc << 6) | static_cast<uint32_t>(t.find(ch));
    bits += 6;
    if (bits >= 8) {
      bits -= 8;
      bytes.push_back(static_cast<uint8_t>(acc >> bits));
    }
  }
  out.resize(bytes.size() / sizeof(TraceRecord));
  std::memcpy(out.data(), bytes.data(), out.size() * sizeof(TraceRecord));
  return out;
}

double json_number(const std::string& line, const std::string& key) {
  size_t a = line.find("\"" + key + "\":");
  if (a == std::string::npos) return -1;
  return std::strtod(line.c_str() + a + key.size() + 3, nullptr);
}

}  // namespace

TEST(trace_ring_wrap_cursor_and_filters) {
  TraceRing ring(4);
  CHECK(ring.last_seq() == 0 && ring.oldest_seq() == 1);
  for (uint32_t i = 1; i <= 6; ++i) ring.push(rec(0x180 + i, i));
  CHECK(ring.last_seq() == 6 && ring.oldest_seq() == 3);
  auto f = ring.fetch(0, 100, {}, false);
  CHECK(f.lost == 2 && f.records.size() == 4 && f.records[0].time_us == 3 && f.next == 6);
  f = ring.fetch(4, 1, {}, false);
  CHECK(f.lost == 0 && f.records.size() == 1 && f.records[0].time_us == 5 && f.next == 5);
  f = ring.fetch(6, 10, {}, false);
  CHECK(f.records.empty() && f.next == 6);
  // Filter 0x184/0x7FF: one frame; the cursor still moves past the others.
  f = ring.fetch(2, 10, {{0x184, 0x7FF}}, false);
  CHECK(f.records.size() == 1 && f.records[0].id == 0x184 && f.next == 6);
  // Error frames only when asked; gap records always.
  TraceRecord err = rec(kCanErr | 0x40, 7);
  TraceRecord gap;
  gap.flags = kTraceGap;
  ring.push(err);
  ring.push(gap);
  CHECK(ring.fetch(6, 10, {{0x180, 0x780}}, false).records.size() == 1);
  CHECK(ring.fetch(6, 10, {}, true).records.size() == 2);
  ring.clear();
  CHECK(ring.fetch(0, 10, {}, true).records.empty() && ring.last_seq() == 8 && ring.oldest_seq() == 9);
  // Filters on the identifier bits, standard and extended alike.
  CHECK((TraceFilter{0x180, 0x780}.match(0x1FF) && !TraceFilter{0x180, 0x780}.match(0x200)));
  CHECK((TraceFilter{0x18FF0000, 0x1FFF0000}.match(kCanEff | 0x18FF0017)));
  // Base64 of the 24-byte records.
  std::vector<TraceRecord> one{rec(0x123, 0x0102030405060708)};
  CHECK(trace_base64(one).size() == 32);
  CHECK(trace_base64({}).empty());
}

TEST(diag_server_trace_ops) {
  set_log_sink(diag_capture);
  Config cfg = diag_config(false);
  DiagHub hub(cfg, "test");
  DiagServer server(hub);
  std::atomic<bool> present{true};
  std::atomic<int> opens{0};
  std::vector<TraceFilter> kernel_filters;
  auto* src = new FakeTraceSource(&present, &opens, &kernel_filters);
  server.set_trace_source(std::unique_ptr<TraceSource>(src));
  server.set_trace_ring(8);
  server.set_trace_idle(std::chrono::milliseconds(1000));
  server.start();
  CHECK(wait_port(server));
  DiagClient c(server.port());
  CHECK(c.ask(R"({"op":"hello","token":"secret"})").find("\"ok\":true") != std::string::npos);
  // No session: refused; fetch without a trace too.
  CHECK(c.ask(R"({"op":"trace_start"})").find("no bus") != std::string::npos);
  CHECK(c.ask(R"({"op":"trace_fetch","after":0})").find("no trace running") != std::string::npos);
  CHECK(opens == 0);

  hub.attach();
  // Read-only diagnostics still trace.
  std::string st = c.ask(R"({"op":"trace_start","id":7})");
  CHECK_MSG(st.find("\"ok\":true") != std::string::npos && json_number(st, "next") == 0 &&
                json_number(st, "buffer_frames") == 8 && json_number(st, "record_size") == 24,
            st);
  CHECK(opens == 1 && kernel_filters.empty());
  src->put(rec(0x080, 1, true));
  src->put(rec(0x197, 2));
  src->put(rec(0x717, 3));
  std::this_thread::sleep_for(std::chrono::milliseconds(50));
  std::string f = c.ask(R"({"op":"trace_fetch","after":0,"max":2})");
  auto frames = decode_frames(f);
  CHECK_MSG(frames.size() == 2 && frames[0].id == 0x080 && (frames[0].flags & kTraceTx) && frames[1].id == 0x197 &&
                !(frames[1].flags & kTraceTx) && json_number(f, "next") == 2 && f.find("\"more\":true") != std::string::npos &&
                f.find("\"session\":true") != std::string::npos && json_number(f, "kernel_drops") == 3,
            f);
  frames = decode_frames(c.ask(R"({"op":"trace_fetch","after":2})"));
  CHECK(frames.size() == 1 && frames[0].id == 0x717 && frames[0].data[0] == 0x17);
  // A slow client: the ring of 8 wrapped.
  for (uint32_t i = 0; i < 12; ++i) src->put(rec(0x180, 10 + i));
  std::this_thread::sleep_for(std::chrono::milliseconds(50));
  f = c.ask(R"({"op":"trace_fetch","after":3})");
  CHECK_MSG(json_number(f, "lost") == 4 && decode_frames(f).size() == 8 && json_number(f, "next") == 15, f);
  CHECK(c.ask(R"({"op":"trace_fetch","after":0,"max":4001})").find("'max'") != std::string::npos);

  // A second client with a filter: kernel filter stays "all" while the first
  // takes everything; its own fetches are filtered.
  DiagClient c2(server.port());
  CHECK(c2.ask(R"({"op":"hello","token":"secret"})").find("\"ok\":true") != std::string::npos);
  CHECK(c2.ask(R"({"op":"trace_start","filters":[{"id":"0x180","mask":"0x780"}]})").find("\"ok\":true") !=
        std::string::npos);
  CHECK(kernel_filters.empty() && opens == 1);
  src->put(rec(0x197, 30));
  src->put(rec(0x297, 31));
  std::this_thread::sleep_for(std::chrono::milliseconds(50));
  frames = decode_frames(c2.ask(R"({"op":"trace_fetch","after":15})"));
  CHECK(frames.size() == 1 && frames[0].id == 0x197);
  // The first stops: the kernel filter becomes the second's.
  CHECK(c.ask(R"({"op":"trace_stop"})").find("\"ok\":true") != std::string::npos);
  std::this_thread::sleep_for(std::chrono::milliseconds(50));
  CHECK(kernel_filters.size() == 1 && kernel_filters[0].id == 0x180 && kernel_filters[0].mask == 0x780);
  CHECK(c2.ask(R"({"op":"trace_start","filters":[{"id":1,"mask":"zz"}]})").find("'mask'") != std::string::npos);

  // Interface lost and back: no session meanwhile, then a gap record and new frames.
  present = false;
  src->put(rec(0x197, 40));
  std::this_thread::sleep_for(std::chrono::milliseconds(100));
  f = c2.ask(R"({"op":"trace_fetch","after":17})");
  CHECK_MSG(f.find("\"session\":false") != std::string::npos, f);
  uint64_t next = static_cast<uint64_t>(json_number(f, "next"));
  present = true;
  for (int i = 0; i < 100 && opens < 2; ++i) std::this_thread::sleep_for(std::chrono::milliseconds(20));
  CHECK(opens == 2);
  src->put(rec(0x1A0, 41));
  std::this_thread::sleep_for(std::chrono::milliseconds(50));
  f = c2.ask(R"({"op":"trace_fetch","after":)" + std::to_string(next) + "}");
  frames = decode_frames(f);
  CHECK_MSG(frames.size() == 2 && (frames[0].flags & kTraceGap) && frames[1].id == 0x1A0 &&
                f.find("\"session\":true") != std::string::npos,
            f);

  // No fetch for longer than the idle time: the trace ends and the capture closes.
  std::this_thread::sleep_for(std::chrono::milliseconds(2500));
  CHECK(c2.ask(R"({"op":"trace_fetch","after":0})").find("no trace running") != std::string::npos);
  CHECK(src->fd() < 0);
  CHECK(diag_log_count("trace of 127.0.0.1 ended: no fetch") >= 1);
  server.stop();
  set_log_sink(nullptr);
}

// ---------------------------------------------------------------------------
// Runtime version guard (managed Docker install)

TEST(runtime_version_guard) {
  std::string dir = tmpdir();
  std::string stamp = dir + "/runtime-version";
  // Native install: no RUNTIME_VERSION, no check, even without a stamp.
  CHECK(runtime_version_problem(stamp, nullptr).empty());
  // Docker without a stamp.
  std::string e = runtime_version_problem(stamp, "v4.2.4");
  CHECK(e.find("no build stamp") != std::string::npos);
  { std::ofstream(stamp) << "v4.2.4\nghcr.io/autonomy-logic/openplc-runtime:v4.2.4\n"; }
  CHECK(runtime_version_problem(stamp, "v4.2.4").empty());
  CHECK(runtime_version_problem(stamp, " v4.2.4\n").empty());
  e = runtime_version_problem(stamp, "v4.2.5");
  CHECK(e.find("built for runtime v4.2.4 but the runtime is v4.2.5") != std::string::npos);
  CHECK(e.find("install-stock.sh") != std::string::npos);
  unlink(stamp.c_str());
  rmdir(dir.c_str());
}

// The request slots behind the PLC program's SDO blocks (add-plc-sdo-blocks 2.6).
TEST(plc_requests_slots_and_handles) {
  using canopen_plugin::PlcRequests;
  PlcRequests& q = PlcRequests::instance();
  canopen_plc_request r{};
  r.node = 5;
  r.index = 0x1018;
  r.subindex = 1;
  uint16_t err = 0;
  q.close();
  CHECK(q.start(r, err) == 0);
  CHECK(err == CANOPEN_PLC_ERR_NOT_RUNNING);
  q.open();
  // Input checks.
  canopen_plc_request bad = r;
  bad.node = 0;
  CHECK(q.start(bad, err) == 0 && err == CANOPEN_PLC_ERR_INPUT);
  bad = r;
  bad.network = 1;
  CHECK(q.start(bad, err) == 0 && err == CANOPEN_PLC_ERR_INPUT);
  uint8_t payload[8] = {1, 2, 3, 4, 5, 6, 7, 8};
  bad = r;
  bad.write = 1;
  bad.kind = CANOPEN_PLC_REAL;
  bad.data = payload;
  bad.length = 8;
  bad.size = 2;
  CHECK(q.start(bad, err) == 0 && err == CANOPEN_PLC_ERR_INPUT);
  bad.kind = CANOPEN_PLC_BYTES;
  bad.length = CANOPEN_PLC_MAX_DATA + 1;
  CHECK(q.start(bad, err) == 0 && err == CANOPEN_PLC_ERR_INPUT);
  // A request runs and its result is collected once.
  uint32_t h = q.start(r, err);
  CHECK(h != 0 && err == 0);
  canopen_plc_result res{};
  CHECK(q.poll(h, &res, nullptr, 0) == 0);
  std::vector<PlcRequests::Job> jobs;
  q.take(0, jobs);
  CHECK(jobs.size() == 1 && jobs[0].handle == h && jobs[0].req.timeout_ms == PlcRequests::kDefaultTimeoutMs);
  uint8_t reply[4] = {0x78, 0x56, 0x34, 0x12};
  q.finish(h, 0, 0, reply, sizeof reply);
  uint8_t got[8] = {};
  CHECK(q.poll(h, &res, got, sizeof got) == 1);
  CHECK(res.error_id == 0 && res.size == 4 && got[0] == 0x78 && got[3] == 0x12);
  CHECK(q.poll(h, &res, nullptr, 0) == 2 && res.error_id == CANOPEN_PLC_ERR_CANCELLED);
  // A reused slot gets a new handle; the old one stays stale.
  uint32_t h2 = q.start(r, err);
  CHECK(h2 != 0 && h2 != h && (h2 & (CANOPEN_PLC_SLOTS - 1)) == (h & (CANOPEN_PLC_SLOTS - 1)));
  CHECK(q.poll(h, &res, nullptr, 0) == 2);
  // An abort keeps its code; the reply data is not copied.
  jobs.clear();
  q.take(0, jobs);
  q.finish(h2, CANOPEN_PLC_ERR_ABORT, 0x06020000u, nullptr, 0);
  CHECK(q.poll(h2, &res, got, sizeof got) == 2 && res.error_id == CANOPEN_PLC_ERR_ABORT && res.abort_code == 0x06020000u);
  // 64 slots, then BUSY; oldest first when taken.
  std::vector<uint32_t> handles;
  for (unsigned i = 0; i < CANOPEN_PLC_SLOTS; ++i) {
    handles.push_back(q.start(r, err));
    CHECK(handles.back() != 0);
  }
  CHECK(q.start(r, err) == 0 && err == CANOPEN_PLC_ERR_BUSY);
  jobs.clear();
  q.take(0, jobs);
  CHECK(jobs.size() == CANOPEN_PLC_SLOTS);
  bool ordered = true;
  for (unsigned i = 0; i < jobs.size(); ++i) ordered = ordered && jobs[i].handle == handles[i];
  CHECK(ordered);
  // A finished result nobody collects is dropped after 10 s.
  q.finish(handles[0], 0, 0, reply, 1);
  q.expire(PlcRequests::clock::now() + PlcRequests::kKeepResult);
  CHECK(q.poll(handles[0], &res, nullptr, 0) == 2 && res.error_id == CANOPEN_PLC_ERR_CANCELLED);
  // Taken requests of a network that went away end as cancelled.
  q.cancel_taken(0);
  CHECK(q.poll(handles[1], &res, nullptr, 0) == 2 && res.error_id == CANOPEN_PLC_ERR_CANCELLED);
  // A queued request no network takes times out.
  canopen_plc_request quick = r;
  quick.timeout_ms = 1;
  uint32_t h3 = q.start(quick, err);
  usleep(5000);
  CHECK(q.poll(h3, &res, nullptr, 0) == 2 && res.error_id == CANOPEN_PLC_ERR_TIMEOUT && res.abort_code == 0x05040000u);
  // Stopping the PLC drops everything.
  uint32_t h4 = q.start(r, err);
  q.close();
  CHECK(q.poll(h4, &res, nullptr, 0) == 2 && res.error_id == CANOPEN_PLC_ERR_CANCELLED);
  // Only API version 1 is offered; another is noted once.
  CHECK(canopen_plugin::plc_api_table(1) != nullptr);
  CHECK(canopen_plugin::plc_api_table(7) == nullptr);
  CHECK(q.take_unknown_version() == 7);
  CHECK(q.take_unknown_version() == 0);
}

// Several networks: a request names its network; each network takes and
// cancels only its own (add-several-can-networks, SDO blocks on every network).
TEST(plc_requests_per_network) {
  using canopen_plugin::PlcRequests;
  PlcRequests& q = PlcRequests::instance();
  canopen_plc_request r{};
  r.node = 2;
  r.index = 0x1018;
  r.subindex = 1;
  uint16_t err = 0;
  q.open(2);
  canopen_plc_request second = r;
  second.network = 1;
  canopen_plc_request third = r;
  third.network = 2;
  CHECK(q.start(third, err) == 0 && err == CANOPEN_PLC_ERR_INPUT);
  uint32_t h0 = q.start(r, err);
  uint32_t h1 = q.start(second, err);
  CHECK(h0 && h1);
  std::vector<PlcRequests::Job> jobs;
  q.take(1, jobs);
  CHECK(jobs.size() == 1 && jobs[0].handle == h1 && jobs[0].req.network == 1);
  // The second network going away cancels only its own transfer.
  q.cancel_taken(0);
  canopen_plc_result res{};
  CHECK(q.poll(h1, &res, nullptr, 0) == 0);
  q.cancel_taken(1);
  CHECK(q.poll(h1, &res, nullptr, 0) == 2 && res.error_id == CANOPEN_PLC_ERR_CANCELLED);
  jobs.clear();
  q.take(0, jobs);
  CHECK(jobs.size() == 1 && jobs[0].handle == h0);
  q.finish(h0, 0, 0, nullptr, 0);
  CHECK(q.poll(h0, &res, nullptr, 0) == 1);
  // One network again: network 1 is refused.
  q.open(1);
  CHECK(q.start(second, err) == 0 && err == CANOPEN_PLC_ERR_INPUT);
  q.close();
}

int main(int argc, char** argv) { return check::run_all(argc, argv); }

// ---------------------------------------------------------------------------
// Several networks (canopen-networks spec)

namespace {

std::string two_networks_json(const std::string& diagnostics = "") {
  std::string d = diagnostics.empty() ? "" : "\"diagnostics\": " + diagnostics + ",";
  return R"({ "schema_version": 2, )" + d + R"( "networks": [
    { "name": "io", "adapter": { "type": "socketcan", "interface": "vcan0", "bitrate": 125000 },
      "master": { "node_id": 1, "sync_period_us": 10000 },
      "nodes": [ { "node_id": 2, "name": "pingpong", "eds": "cpp-slave.eds", "heartbeat_ms": 500,
        "tx_pdos": [ { "entries": [ { "index": "0x4001", "subindex": 0, "type": "UNSIGNED32", "iec_location": "%ID100" } ] } ],
        "rx_pdos": [ { "entries": [ { "index": "0x4000", "subindex": 0, "type": "UNSIGNED32", "iec_location": "%QD100" } ] } ] } ] },
    { "adapter": { "type": "socketcan", "interface": "vcan1", "bitrate": 500000 },
      "master": { "node_id": 3, "sync_period_us": 10000 },
      "nodes": [ { "node_id": 2, "name": "pingpong", "eds": "cpp-slave.eds", "heartbeat_ms": 500,
        "tx_pdos": [ { "entries": [ { "index": "0x4001", "subindex": 0, "type": "UNSIGNED32", "iec_location": "%ID101" } ] } ],
        "rx_pdos": [ { "entries": [ { "index": "0x4000", "subindex": 0, "type": "UNSIGNED32", "iec_location": "%QD101" } ] } ] } ] }
  ] })";
}

}  // namespace

TEST(config_v2_networks) {
  std::string path = std::string(PINGPONG_DIR) + "/canopen_config.json";
  std::string h = sha256_hex("secret");
  std::string json = two_networks_json("{ \"token_sha256\": \"" + h + "\", \"port\": 9000 }");
  ConfigSet set;
  std::vector<std::string> errors;
  CHECK_MSG(parse_config_set(json, path, ImageLimits(), set, errors), join(errors));
  CHECK(set.schema_version == 2 && set.networks.size() == 2 && set.several());
  if (set.networks.size() != 2) return;
  const Config& io = set.networks[0];
  const Config& drives = set.networks[1];
  CHECK(io.network == "io" && io.network_index == 0 && io.log_prefix == "io");
  // Without a name, the network is named after its interface.
  CHECK(drives.network == "vcan1" && drives.network_index == 1 && drives.log_prefix == "vcan1");
  CHECK(io.work_dir == std::string(PINGPONG_DIR) + "/.canopen/io");
  CHECK(drives.work_dir == std::string(PINGPONG_DIR) + "/.canopen/vcan1");
  CHECK(io.master.node_id == 1 && drives.master.node_id == 3 && drives.adapter.bitrate == 500000);
  // The one diagnostics object reaches every network's master.
  for (const auto& cfg : set.networks)
    CHECK(cfg.master.has_diagnostics && cfg.master.diag_token_sha256 == h && cfg.master.diag_port == 9000);
  CHECK(io.file_sha256 == sha256_hex(json) && set.file_sha256 == io.file_sha256);

  // The one-network form refuses a file with two.
  Config one;
  errors.clear();
  CHECK(!parse_config(json, path, ImageLimits(), one, errors));
  CHECK_MSG(has_error(errors, "holds 2 networks; this tool takes a file with one"), join(errors));

  // A version 1 file: one unnamed network, no log prefix, .canopen as before.
  errors.clear();
  ConfigSet v1;
  CHECK(parse_config_set(kValid, path, ImageLimits(), v1, errors));
  CHECK(v1.networks.size() == 1 && v1.networks[0].network.empty() && v1.networks[0].log_prefix.empty());
  CHECK(v1.networks[0].work_dir == std::string(PINGPONG_DIR) + "/.canopen");
}

TEST(dcfgen_work_dir_per_network) {
  // Each network generates into .canopen/<name>/ with its own reuse stamp:
  // a change to one network regenerates only that network.
  std::string dir = tmpdir();
  write(dir + "/cpp-slave.eds", read(std::string(PINGPONG_DIR) + "/cpp-slave.eds"));
  auto generate = [&](const std::string& json, bool& io_reused, bool& drives_reused) {
    ConfigSet set;
    std::vector<std::string> errors;
    CHECK_MSG(parse_config_set(json, dir + "/canopen_config.json", ImageLimits(), set, errors), join(errors));
    if (set.networks.size() != 2) return;
    GeneratedConfig io, drives;
    CHECK_MSG(generate_device_config(set.networks[0], default_dcfgen(), io, errors), join(errors));
    CHECK_MSG(generate_device_config(set.networks[1], default_dcfgen(), drives, errors), join(errors));
    CHECK(io.work_dir == dir + "/.canopen/io" && drives.work_dir == dir + "/.canopen/vcan1");
    io_reused = io.reused;
    drives_reused = drives.reused;
  };
  std::string json = two_networks_json();
  bool a = true, b = true;
  generate(json, a, b);
  CHECK(!a && !b);
  struct stat st;
  CHECK(stat((dir + "/.canopen/io/master.dcf").c_str(), &st) == 0);
  CHECK(stat((dir + "/.canopen/vcan1/master.dcf").c_str(), &st) == 0);
  CHECK(stat((dir + "/.canopen/master.dcf").c_str(), &st) != 0);
  std::string changed = json;
  size_t at = changed.find("\"node_id\": 3, \"sync_period_us\": 10000");
  CHECK(at != std::string::npos);
  if (at == std::string::npos) return;
  changed.replace(at, std::strlen("\"node_id\": 3"), "\"node_id\": 4");
  generate(changed, a, b);
  CHECK(a && !b);
}

TEST(config_v2_single_network_has_no_prefix) {
  std::string json = R"({ "schema_version": 2, "networks": [
    { "name": "plant", "adapter": { "type": "socketcan", "interface": "vcan0", "bitrate": 125000 },
      "master": { "node_id": 1 },
      "nodes": [ { "node_id": 2, "eds": "cpp-slave.eds" } ] } ] })";
  ConfigSet set;
  std::vector<std::string> errors;
  CHECK_MSG(parse_config_set(json, std::string(PINGPONG_DIR) + "/c.json", ImageLimits(), set, errors), join(errors));
  CHECK(set.networks.size() == 1 && set.networks[0].network == "plant" && set.networks[0].log_prefix.empty());
  CHECK(set.networks[0].work_dir == std::string(PINGPONG_DIR) + "/.canopen/plant");
  Config cfg;
  CHECK(parse_config(json, std::string(PINGPONG_DIR) + "/c.json", ImageLimits(), cfg, errors));
}

TEST(log_prefix_per_thread) {
  {
    std::lock_guard<std::mutex> lock(g_diag_log_mutex);
    g_diag_log.clear();
  }
  set_log_sink(diag_capture);
  {
    ScopedLogPrefix p("drives: ");
    log_info("node 10 (valve) lost");
    std::thread([] { log_info("other thread"); }).join();
  }
  log_info("after");
  set_log_sink(nullptr);
  CHECK(diag_log_count("[CANOPEN] drives: node 10 (valve) lost") == 1);
  CHECK(diag_log_count("[CANOPEN] other thread") == 1);
  CHECK(diag_log_count("[CANOPEN] after") == 1);
}

TEST(diag_server_two_networks) {
  set_log_sink(diag_capture);
  ConfigSet set;
  std::vector<std::string> errors;
  CHECK(parse_config_set(two_networks_json("{ \"token_sha256\": \"" + sha256_hex("secret") +
                                           "\", \"port\": 1024, \"bind\": \"127.0.0.1\" }"),
                         std::string(PINGPONG_DIR) + "/c.json", ImageLimits(), set, errors));
  if (set.networks.size() != 2) return;
  for (auto& cfg : set.networks) cfg.master.diag_port = 0;  // any free port
  DiagHub io(set.networks[0], "test"), drives(set.networks[1], "test");
  DiagServer server(std::vector<DiagHub*>{&io, &drives});
  std::atomic<bool> present{true};
  std::atomic<int> opens0{0}, opens1{0};
  std::vector<TraceFilter> f0, f1;
  server.set_trace_source(std::unique_ptr<TraceSource>(new FakeTraceSource(&present, &opens0, &f0)), 0);
  server.set_trace_source(std::unique_ptr<TraceSource>(new FakeTraceSource(&present, &opens1, &f1)), 1);
  server.start();
  CHECK(wait_port(server));
  DiagClient c(server.port());
  std::string hello = c.ask(R"({"op":"hello","token":"secret"})");
  CHECK_MSG(hello.find(R"("protocol":1)") != std::string::npos &&
                hello.find(R"("networks":[{"name":"io","interface":"vcan0","bitrate":125000,"master_node_id":1},)"
                           R"({"name":"vcan1","interface":"vcan1","bitrate":500000,"master_node_id":3}])") !=
                    std::string::npos,
            hello);
  std::string st = c.ask(R"({"op":"status"})");
  CHECK_MSG(st.find("network required (io, vcan1)") != std::string::npos, st);
  st = c.ask(R"({"op":"status","network":"bus9"})");
  CHECK_MSG(st.find("unknown network 'bus9' (io, vcan1)") != std::string::npos, st);
  st = c.ask(R"({"op":"status","network":"vcan1"})");
  CHECK_MSG(st.find(R"("network":"vcan1")") != std::string::npos && st.find(R"("session":false)") != std::string::npos &&
                st.find(R"("node_id":3)") != std::string::npos,
            st);
  // The master check uses the picked network's master node ID.
  CHECK(c.ask(R"({"op":"sdo_read","network":"vcan1","node":3,"index":4096,"subindex":0})").find("is the master itself") !=
        std::string::npos);
  CHECK(c.ask(R"({"op":"sdo_read","network":"io","node":3,"index":4096,"subindex":0})").find("no bus") !=
        std::string::npos);
  // One network has a session, the other not.
  drives.attach();
  st = c.ask(R"({"op":"trace_start","network":"io"})");
  CHECK_MSG(st.find("no bus") != std::string::npos, st);
  st = c.ask(R"({"op":"trace_start","network":"vcan1"})");
  CHECK_MSG(st.find(R"("interface":"vcan1")") != std::string::npos && st.find(R"("network":"vcan1")") != std::string::npos,
            st);
  CHECK(opens0 == 0 && opens1 == 1);
  CHECK(c.ask(R"({"op":"trace_fetch","network":"io","after":0})").find("no trace running") != std::string::npos);
  CHECK(c.ask(R"({"op":"trace_fetch","network":"vcan1","after":0})").find(R"("ok":true)") != std::string::npos);
  CHECK(c.ask(R"({"op":"trace_stop","network":"vcan1"})").find(R"("ok":true)") != std::string::npos);
  drives.detach();
  server.stop();
  set_log_sink(nullptr);
}
