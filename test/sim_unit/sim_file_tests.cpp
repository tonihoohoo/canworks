// Unit tests of the simulation file loader and value sources.

#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <string>
#include <vector>

#include <sys/stat.h>
#include <unistd.h>

#include "check.hpp"
#include "cJSON.h"
#include "config.h"
#include "sim_config.h"
#include "sim_file.h"
#include "sim_source.h"

using namespace canopen_sim;

namespace {

bool loads(const std::string& json, std::string& first_error) {
  SimFile f;
  std::vector<std::string> errors;
  bool ok = parse_sim_file(json, "/x/simulation.json", f, errors);
  first_error = errors.empty() ? "" : errors[0];
  return ok;
}

class NoCtx : public ExprContext {
 public:
  double value(const ObjectRef&) override { return 0; }
};

Value eval_source(const std::string& json, double t) {
  cJSON* j = cJSON_Parse(json.c_str());
  std::string err;
  auto s = Source::parse(j, "", err);
  cJSON_Delete(j);
  if (!s) return Value::text("error: " + err);
  NoCtx ctx;
  std::mt19937 rng(1);
  ctx.rng = &rng;
  return s->eval(t, ctx);
}

}  // namespace

TEST(sim_file_examples_load) {
  for (const std::string dir : {std::string(PINGPONG_DIR), std::string(RTD_DIR)}) {
    SimFile f;
    std::vector<std::string> errors;
    CHECK_MSG(load_sim_file(dir + "/simulation.json", f, errors), errors.empty() ? dir : errors[0]);
    CHECK(!f.scenarios.empty());
    canopen_plugin::Config cfg;
    std::vector<std::string> cerr;
    CHECK(canopen_plugin::load_config(dir + "/canopen_config.json", canopen_plugin::ImageLimits(), cfg, cerr));
    CHECK(canopen_plugin::check_sim_file(cfg, f, cerr));
  }
}

TEST(sim_file_errors) {
  std::string e;
  CHECK(loads(R"({"schema_version": 1})", e));
  CHECK(!loads(R"({"schema_version": 3})", e) && e.find("reads up to 2") != std::string::npos);
  CHECK(!loads(R"({"schema_version": 2})", e) && e.find("networks: is required") != std::string::npos);
  CHECK(!loads(R"({"schema_version": 2, "networks": {}, "nodes": {}})", e) &&
        e.find("go in a network's section") != std::string::npos);
  CHECK(!loads(R"({"networks": {"io": {}}})", e) && e.find("\"schema_version\": 2") != std::string::npos);
  CHECK(!loads(R"({"schema_version": 2, "networks": {"io": {"tick_ms": 5}}})", e) &&
        e.find("networks.io") != std::string::npos);
  CHECK(!loads(R"({"schema_version": 2, "networks": {"io": {"nodes": {"300": {}}}}})", e) &&
        e.find("networks.io.nodes.300") != std::string::npos);
  CHECK(!loads(R"({"tick": 5})", e) && e.find("unknown key \"tick\"") != std::string::npos);
  CHECK(!loads(R"({"nodes": {"300": {}}})", e) && e.find("node ID 1-127") != std::string::npos);
  CHECK(!loads(R"({"nodes": {"5": {"sources": {"0x7130:1": {"sine": {"min": 1}}}}}})", e));
  CHECK(!loads(R"({"nodes": {"5": {"faults": [{"power": "sideways"}]}}})", e) && e.find("power must be one of") != std::string::npos);
  CHECK(!loads(R"({"extra_devices": [{"node": 0, "eds": "a.eds"}]})", e) && e.find("needs a \"name\"") != std::string::npos);
  CHECK(!loads(R"({"scenarios": {"s": {"steps": [{"set": {"0x2000": 1}}]}}})", e) && e.find("needs \"node\"") != std::string::npos);
  CHECK(!loads(R"({"scenarios": {"s": {"steps": [{"log": "x", "timeout_ms": 5}]}}})", e));
  CHECK(!loads(R"({"scenarios": {"s": {"steps": [{"expect": {"node": 5, "object": "0x2000"}}]}}})", e));
  // A node entry for a node that is neither in the config nor an extra device.
  canopen_plugin::Config cfg;
  std::vector<std::string> errors;
  CHECK(canopen_plugin::load_config(std::string(PINGPONG_DIR) + "/canopen_config.json", canopen_plugin::ImageLimits(), cfg, errors));
  SimFile f;
  CHECK(parse_sim_file(R"({"nodes": {"9": {}}})", "/x/simulation.json", f, errors));
  CHECK(!canopen_plugin::check_sim_file(cfg, f, errors) && errors.back().find("node 9 is neither in") != std::string::npos);
  // An extra device with the node ID of a config node, simulated or not, or
  // of the master.
  for (auto& n : cfg.nodes) n.simulate = false;
  SimFile x;
  CHECK(parse_sim_file(R"({"extra_devices": [{"node": 2, "eds": "a.eds"}, {"node": 1, "eds": "a.eds"},
                                             {"node": 40, "eds": "a.eds"}]})",
                       "/x/simulation.json", x, errors));
  errors.clear();
  CHECK(!canopen_plugin::check_sim_file(cfg, x, errors) && errors.size() == 2);
  CHECK(errors.size() == 2 && errors[0].find("extra_devices[0]: node ID 2 is a node of the configuration") != std::string::npos &&
        errors[1].find("extra_devices[1]: node ID 1 is the master's node ID") != std::string::npos);
}

TEST(sim_file_version_2_sections) {
  SimFile f;
  std::vector<std::string> errors;
  CHECK(parse_sim_file(R"({"schema_version": 2, "tick_ms": 20, "networks": {
                             "io": {"nodes": {"5": {}}, "extra_devices": [{"node": 0, "name": "fresh", "eds": "a.eds"}],
                                    "scenarios": {"s": {"autostart": true, "steps": [{"log": "x"}]}}},
                             "drives": {"nodes": {"4": {}}}}})",
                       "/x/simulation.json", f, errors));
  CHECK(f.schema_version == 2 && f.networks.size() == 2 && f.nodes.empty());
  SimFile io;
  CHECK(sim_file_section(f, "io", io));
  CHECK(io.tick_ms == 20 && io.section == "io" && io.nodes.count(5) && !io.nodes.count(4));
  CHECK(io.extra.size() == 1 && io.extra[0].eds_path == "/x/a.eds" && io.scenarios.size() == 1 && io.scenarios[0].autostart);
  SimFile drives;
  CHECK(sim_file_section(f, "drives", drives) && drives.nodes.count(4) && drives.extra.empty());
  SimFile none;
  CHECK(!sim_file_section(f, "other", none) && none.nodes.empty() && none.tick_ms == 20);
  // A node of another network: refused for this section, naming it.
  canopen_plugin::Config cfg;
  CHECK(canopen_plugin::load_config(std::string(PINGPONG_DIR) + "/canopen_config.json", canopen_plugin::ImageLimits(), cfg, errors));
  CHECK(!canopen_plugin::check_sim_file(cfg, drives, errors) &&
        errors.back().find("networks.drives.nodes.4") != std::string::npos);
}

TEST(sim_sources_waveforms) {
  auto num = [](const Value& v) { return v.is_string ? NAN : v.num; };
  CHECK(std::fabs(num(eval_source(R"({"sine": {"min": 0, "max": 10, "period_s": 4}})", 1)) - 10) < 1e-9);
  CHECK(std::fabs(num(eval_source(R"({"triangle": {"min": 0, "max": 10, "period_s": 4}})", 1)) - 5) < 1e-9);
  CHECK(num(eval_source(R"({"square": {"min": 0, "max": 10, "period_s": 4, "duty": 0.25}})", 0.5)) == 10);
  CHECK(num(eval_source(R"({"square": {"min": 0, "max": 10, "period_s": 4, "duty": 0.25}})", 2)) == 0);
  CHECK(num(eval_source(R"({"ramp": {"from": 0, "to": 100, "duration_s": 10}})", 5)) == 50);
  CHECK(num(eval_source(R"({"ramp": {"from": 0, "to": 100, "duration_s": 10}})", 50)) == 100);
  CHECK(num(eval_source(R"({"steps": {"values": [[1, 2], [5, 2]]}})", 3)) == 5);
  CHECK(num(eval_source(R"({"constant": 42})", 3)) == 42);
  Value s = eval_source(R"({"constant": "text"})", 0);
  CHECK(s.is_string && s.str == "text");
}

namespace {

std::string csv_error(const std::string& dir, const std::string& file, CsvFiles* csv = nullptr) {
  cJSON* j = cJSON_CreateObject();
  cJSON* c = cJSON_AddObjectToObject(j, "csv");
  cJSON_AddStringToObject(c, "file", file.c_str());
  std::string err;
  auto s = Source::parse(j, dir, err, csv);
  cJSON_Delete(j);
  return s ? "" : err.empty() ? "?" : err;
}

void write_file(const std::string& path, const std::string& text) {
  FILE* f = std::fopen(path.c_str(), "w");
  if (!f) return;
  std::fwrite(text.data(), 1, text.size(), f);
  std::fclose(f);
}

}  // namespace

// CSV files: under the simulation file's (or the config's) folder, a regular
// file of at most 16 MB with lines of at most 4096 bytes, read on load only.
TEST(sim_csv_path_rules) {
  char tmpl[] = "/tmp/canworks-csv-XXXXXX";
  std::string top = mkdtemp(tmpl);
  std::string dir = top + "/sim";
  mkdir(dir.c_str(), 0755);
  mkdir((dir + "/sub").c_str(), 0755);
  write_file(dir + "/ok.csv", "t,v\n0,1\n1,2\n");
  write_file(dir + "/sub/ok.csv", "0,1\n");
  write_file(top + "/out.csv", "0,1\n");
  write_file(dir + "/long.csv", "0," + std::string(5000, '1') + "\n");
  CHECK(mkfifo((dir + "/fifo.csv").c_str(), 0644) == 0);
  CHECK(symlink("/dev/zero", (dir + "/zero.csv").c_str()) == 0);
  CHECK(symlink(top.c_str(), (dir + "/up").c_str()) == 0);
  {
    FILE* f = std::fopen((dir + "/big.csv").c_str(), "w");
    if (f) {
      CHECK(ftruncate(fileno(f), (16 << 20) + 1) == 0);  // sparse
      std::fclose(f);
    }
  }
  CHECK(csv_error(dir, "ok.csv").empty());
  CHECK(csv_error(dir, "sub/ok.csv").empty());
  CHECK(csv_error(dir, dir + "/ok.csv").empty());
  auto has = [](const std::string& err, const char* part) {
    bool ok = err.find(part) != std::string::npos;
    if (!ok) std::printf("  got: %s\n", err.c_str());
    return ok;
  };
  CHECK(has(csv_error(dir, "../out.csv"), "outside the folders"));
  CHECK(has(csv_error(dir, top + "/out.csv"), "outside the folders"));
  CHECK(has(csv_error(dir, "up/out.csv"), "outside the folders"));
  CHECK(has(csv_error(dir, "/dev/zero"), "outside the folders"));
  CHECK(has(csv_error(dir, "zero.csv"), "outside the folders"));
  CHECK(has(csv_error(dir, "fifo.csv"), "not a regular file"));  // and no wait for a writer
  CHECK(has(csv_error(dir, "big.csv"), "larger than 16 MB"));
  CHECK(has(csv_error(dir, "long.csv"), "line 1 is longer than 4096 bytes"));
  CHECK(has(csv_error("", "ok.csv"), "cannot read"));

  // A simulation file reads its CSV files on load, from under its own folder
  // or the config's; afterwards they come from memory only.
  std::string sim = R"({"nodes": {"2": {"sources": {"0x4001": {"csv": {"file": "FILE"}}}}},
                        "scenarios": {"s": {"steps": [{"node": 2, "source": {"0x4001": {"csv": {"file": "sub/ok.csv"}}}}]}}})";
  auto with = [&](const std::string& file) {
    std::string t = sim;
    t.replace(t.find("FILE"), 4, file);
    return t;
  };
  SimFile f;
  std::vector<std::string> errors;
  CHECK(parse_sim_file(with("ok.csv"), dir + "/simulation.json", f, errors));
  CHECK(f.csv && f.csv->frozen && f.csv->rows.size() == 2);
  remove((dir + "/ok.csv").c_str());
  remove((dir + "/sub/ok.csv").c_str());
  CHECK(csv_error(dir, "ok.csv", f.csv.get()).empty());     // read on load
  CHECK(csv_error(dir, "sub/ok.csv", f.csv.get()).empty());  // the scenario step's, too
  CHECK(has(csv_error(dir, "other.csv", f.csv.get()), "read only when it loads"));
  errors.clear();
  CHECK(!parse_sim_file(with("../out.csv"), dir + "/simulation.json", f, errors) && !errors.empty() &&
        has(errors[0], "outside the folders"));
  errors.clear();
  write_file(dir + "/sub/ok.csv", "0,1\n");
  CHECK_MSG(parse_sim_file(with("../out.csv"), dir + "/simulation.json", f, errors, top), errors.empty() ? "" : errors[0]);
  std::string rm = "rm -rf '" + top + "'";
  CHECK(std::system(rm.c_str()) == 0);
}
