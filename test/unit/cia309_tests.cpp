// The CiA 309-3 gateway (canopen-cia309-gateway spec) without a bus: Lely's
// text layer through Cia309Session, with the test playing the bus thread on
// real DiagHubs (it takes the requests and answers them), the hub's event
// queue, and Cia309Server with its plain port and the hand-over from a
// logged-in diagnostics connection.

#include <arpa/inet.h>
#include <netinet/in.h>
#include <poll.h>
#include <sys/socket.h>
#include <unistd.h>

#include <atomic>
#include <chrono>
#include <cstring>
#include <functional>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#include "cJSON.h"
#include "check.hpp"
#include "cia309_dispatch.h"
#include "cia309_server.h"
#include "cia309_text.h"
#include "config.h"
#include "diag.h"
#include "log.h"
#include "secure_channel.h"

using namespace canopen_plugin;
using clock_type = std::chrono::steady_clock;

namespace {

std::vector<std::string> g_log;
std::mutex g_log_mutex;
void capture(LogLevel, const char* msg) {
  std::lock_guard<std::mutex> lock(g_log_mutex);
  g_log.push_back(msg);
}
size_t logged(const std::string& needle) {
  std::lock_guard<std::mutex> lock(g_log_mutex);
  size_t n = 0;
  for (const auto& l : g_log) n += l.find(needle) != std::string::npos;
  return n;
}

const std::string& verifier() {
  static const std::string v = format_scram_verifier(make_scram_verifier("secret", random_bytes(16), 4096));
  return v;
}

std::string replace(std::string s, const std::string& from, const std::string& to) {
  size_t at = s.find(from);
  if (at != std::string::npos) s.replace(at, from.size(), to);
  return s;
}

// Two master networks, io (node 2 with TPDO 1) and drives (node 4), and
// `cia309` as given.
std::string two_networks(const std::string& cia309, bool diagnostics = false) {
  std::string node = R"({ "node_id": %ID%, "name": "n%ID%", "eds": "x.eds",
      "tx_pdos": [ { "entries": [ { "index": "0x6000", "subindex": 1, "type": "UNSIGNED16", "iec_location": "%IW%LOC%" },
                                  { "index": "0x6000", "subindex": 2, "type": "UNSIGNED16", "iec_location": "%IW%LOC2%" } ] } ] })";
  auto make = [&](const char* id, const char* loc, const char* loc2) {
    return replace(replace(replace(replace(node, "%ID%", id), "%ID%", id), "%LOC%", loc), "%LOC2%", loc2);
  };
  std::string diag = diagnostics ? R"("diagnostics": { "token_verifier": ")" + verifier() + R"(", "bind": "127.0.0.1" },)" : "";
  return R"({ "schema_version": 2, )" + diag + R"( "cia309": )" + cia309 + R"(,
    "networks": [
      { "name": "io", "adapter": { "type": "socketcan", "interface": "vcan0", "bitrate": 125000 },
        "master": { "node_id": 1 }, "nodes": [ )" + make("2", "10", "11") + R"( ] },
      { "name": "drives", "adapter": { "type": "socketcan", "interface": "vcan1", "bitrate": 125000 },
        "master": { "node_id": 1 }, "nodes": [ )" + make("4", "12", "13") + R"( ] } ] })";
}

// The networks, their hubs (attached: the test is the bus thread) and a
// session on them.
struct Fixture {
  ConfigSet set;
  std::vector<std::string> errors;
  std::vector<std::unique_ptr<DiagHub>> hubs;
  std::vector<Cia309Net> nets;
  std::unique_ptr<Cia309Session> s;
  clock_type::time_point now = clock_type::now();
  // How the "bus thread" answers; null: it keeps the requests.
  std::function<std::string(const DiagRequest&)> bus;
  std::vector<DiagRequest> seen;  // every request the bus thread took

  explicit Fixture(const std::string& json) {
    bool ok = parse_config_set(json, "/tmp/cia309-test/canworks.json", ImageLimits(), set, errors);
    CHECK_MSG(ok, errors.empty() ? std::string("?") : errors[0]);
    for (auto& cfg : set.networks) {
      hubs.emplace_back(new DiagHub(cfg, "test-1"));
      hubs.back()->attach();
    }
    for (size_t i = 0; i < set.networks.size(); ++i) nets.push_back({&set.networks[i], hubs[i].get()});
    if (!set.networks.empty())
      s.reset(new Cia309Session(set.networks[0].master.cia309, nets, "127.0.0.1", false, "test-1"));
  }
  // Moves requests to the "bus thread" and answers back until nothing moves.
  void pump() {
    for (int round = 0; round < 10; ++round) {
      bool moved = false;
      for (size_t n = 0; n < hubs.size(); ++n) {
        std::vector<DiagRequest> reqs;
        hubs[n]->take(reqs);
        for (auto& r : reqs) {
          seen.push_back(r);
          if (bus) hubs[n]->answer(r.seq, bus(r));
          moved = true;
        }
        std::vector<std::pair<uint64_t, std::string>> answers;
        hubs[n]->take_gateway_answers(answers);
        for (auto& a : answers) {
          s->answer(n, a.first, a.second, now);
          moved = true;
        }
      }
      if (!moved) return;
    }
  }
  // Sends lines and returns the text that came out.
  std::string ask(const std::string& lines) {
    std::string in = lines + "\r\n";
    s->feed(in.data(), in.size(), now);
    pump();
    std::string out = s->output();
    s->output().clear();
    return out;
  }
};

std::string ok(cJSON* res) { return diag_ok("", res); }

cJSON* obj(std::initializer_list<std::pair<const char*, const char*>> strings) {
  cJSON* o = cJSON_CreateObject();
  for (const auto& kv : strings) cJSON_AddStringToObject(o, kv.first, kv.second);
  return o;
}

bool has(const std::string& text, const std::string& needle) { return text.find(needle) != std::string::npos; }

}  // namespace

TEST(cia309_text_layer) {
  std::vector<int> srvs;
  std::string text;
  Cia309Text t([&](const co_gw_req&) { srvs.push_back(1); }, [&](const std::string& l) { text += l + "\n"; });
  CHECK(t.ok());
  uint32_t seq = 0;
  CHECK(t.line("[1] 1 2 r 0x1018 1 u32", seq) && srvs.size() == 1);
  CHECK(!t.line("[7] 1 2 r 0x1018", seq) && seq == 7 && srvs.size() == 1);  // no type: syntax error
  CHECK(t.line("", seq) && t.line("# a comment", seq) && srvs.size() == 1);
  CHECK(t.line("[2] info version", seq) && srvs.size() == 2);
  CHECK(t.confirm(7, 0x11, 101) && has(text, "[7] ERROR: 101"));
  CHECK(t.confirm(3, 0x11, 0) && has(text, "[3] OK"));
  const uint8_t four[4] = {1, 2, 3, 4};
  CHECK(Cia309Text::value_fits(0x0007, four, 4) && !Cia309Text::value_fits(0x0007, four, 2) &&
        Cia309Text::value_fits(0x0009, four, 3));
}

TEST(cia309_sdo_upload_and_download) {
  set_log_sink(capture);
  Fixture f(two_networks("{}"));
  f.bus = [](const DiagRequest& r) {
    cJSON* res = cJSON_CreateObject();
    if (r.index == 0x2100) {
      cJSON_AddBoolToObject(res, "success", false);
      cJSON_AddNumberToObject(res, "abort_code", 0x06020000);
      cJSON_AddStringToObject(res, "error", "Object does not exist");
    } else if (r.index == 0x1008) {
      cJSON_AddBoolToObject(res, "success", true);
      cJSON_AddStringToObject(res, "data", "70 69 6E 67");
    } else if (r.index == 0x1001) {
      cJSON_AddBoolToObject(res, "success", false);
      cJSON_AddStringToObject(res, "error", "timeout");
    } else {
      cJSON_AddBoolToObject(res, "success", true);
      cJSON_AddStringToObject(res, "data", "A2 01 00 00");
    }
    return ok(res);
  };
  std::string a = f.ask("[1] 1 2 r 0x1018 1 u32");
  std::printf("    %s", a.c_str());
  CHECK_MSG(has(a, "[1] 0x000001a2") || has(a, "[1] 0x000001a2"), a);
  CHECK(f.seen.size() == 1 && f.seen[0].op == "sdo_read" && f.seen[0].from_cia309 && f.seen[0].node == 2 &&
        f.seen[0].index == 0x1018 && f.seen[0].subindex == 1 && f.seen[0].timeout_ms == 1000);
  // The object is not there: its abort code.
  a = f.ask("[2] 1 2 r 0x2100 0 u8");
  CHECK_MSG(has(a, "[2] ERROR: 06020000"), a);
  // A visible string; the wrong type for the data's length.
  a = f.ask("[3] 1 2 r 0x1008 0 vs");
  CHECK_MSG(has(a, "[3] \"ping\""), a);
  a = f.ask("[4] 1 2 r 0x1018 1 u16");
  CHECK_MSG(has(a, "[4] ERROR: 06070010"), a);
  // No answer from the node: 103.
  a = f.ask("[5] 1 2 r 0x1001 0 u8");
  CHECK_MSG(has(a, "[5] ERROR: 103"), a);
  // The SDO timeout of the session.
  a = f.ask("[6] 1 set sdo_timeout 200");
  CHECK(has(a, "[6] OK"));
  f.ask("[7] 1 2 r 0x1018 1 u32");
  CHECK(f.seen.back().timeout_ms == 200);
  // Read-only: a download is refused before the bus, logged with the client.
  size_t before = f.seen.size();
  a = f.ask("[8] 1 2 w 0x2000 1 u8 3");
  CHECK_MSG(has(a, "[8] ERROR: 102"), a);
  CHECK(f.seen.size() == before);
  CHECK(logged("cia309 127.0.0.1: [8] 1 2 w 0x2000 1 u8 3 refused: changes not allowed") == 1);
  // The master's own node ID and node 0.
  CHECK(has(f.ask("[9] 1 1 r 0x1000 0 u32"), "[9] ERROR: 107"));
  CHECK(has(f.ask("[10] 1 0 r 0x1000 0 u32"), "[10] ERROR: 107"));
  // A line Lely cannot parse sends nothing.
  before = f.seen.size();
  CHECK(has(f.ask("[11] 1 2 r 0x1018"), "[11] ERROR: 101"));
  CHECK(f.seen.size() == before);
  set_log_sink(nullptr);
}

TEST(cia309_download_with_changes_and_force) {
  Fixture f(two_networks(R"({ "allow_changes": true })"));
  f.bus = [](const DiagRequest& r) {
    cJSON* res = cJSON_CreateObject();
    cJSON_AddBoolToObject(res, "success", true);
    return ok(res);
  };
  CHECK(has(f.ask("[1] 1 2 w 0x2000 1 u8 3"), "[1] OK"));
  CHECK(f.seen.size() == 1 && f.seen[0].op == "sdo_write" && f.seen[0].data == std::vector<uint8_t>{3} &&
        !f.seen[0].force);
  CHECK(has(f.ask("[2] 1 2 w 0x2000 1 u32 0x01020304"), "[2] OK"));
  CHECK(f.seen[1].data == (std::vector<uint8_t>{4, 3, 2, 1}));
  Fixture g(two_networks(R"({ "allow_changes": true, "allow_force": true })"));
  g.bus = f.bus;
  g.ask("[1] 1 2 w 0x2000 1 u8 3");
  CHECK(g.seen.size() == 1 && g.seen[0].force);
}

TEST(cia309_network_numbering) {
  Fixture f(two_networks("{}"));
  f.bus = [](const DiagRequest&) {
    cJSON* res = cJSON_CreateObject();
    cJSON_AddBoolToObject(res, "success", true);
    cJSON_AddStringToObject(res, "data", "00 00 00 00");
    return ok(res);
  };
  // Network 2 is drives (the second network of the file).
  f.ask("[3] 2 4 r 0x1000 0 u32");
  CHECK(f.seen.size() == 1 && f.seen[0].node == 4);
  CHECK(f.hubs[1].get() && f.seen.size() == 1);
  // Several networks and no default: 104; set network makes one.
  CHECK(has(f.ask("[1] 4 r 0x1000 0 u32"), "[1] ERROR: 104"));
  CHECK(has(f.ask("[1] set network 2"), "[1] OK"));
  f.ask("[2] 4 r 0x1000 0 u32");
  CHECK(f.seen.size() == 2);
  // A network that does not exist.
  CHECK(has(f.ask("[3] 9 4 r 0x1000 0 u32"), "[3] ERROR: 106"));
  CHECK(has(f.ask("[4] set network 9"), "[4] ERROR: 106"));
  // The default node.
  CHECK(has(f.ask("[5] r 0x1000 0 u32"), "ERROR: 105"));
  CHECK(has(f.ask("[6] 2 set node 4"), "[6] OK"));
  f.ask("[7] r 0x1000 0 u32");
  CHECK(f.seen.size() == 3 && f.seen.back().node == 4);

  // Explicit numbers: only the listed ones exist.
  Fixture g(two_networks(R"({ "nets": { "10": "drives" } })"));
  CHECK(has(g.ask("[1] 1 4 r 0x1000 0 u32"), "[1] ERROR: 106"));
  g.bus = f.bus;
  g.ask("[2] 10 4 r 0x1000 0 u32");
  CHECK(g.seen.size() == 1 && g.seen[0].node == 4);
  // One network: it is the default.
  Fixture h(two_networks(R"({ "default_net": 2 })"));
  h.bus = f.bus;
  h.ask("[1] 4 r 0x1000 0 u32");
  CHECK(h.seen.size() == 1);
}

TEST(cia309_nmt_and_guards) {
  set_log_sink(capture);
  Fixture ro(two_networks("{}"));
  CHECK(has(ro.ask("[1] 1 2 stop"), "[1] ERROR: 102") && ro.seen.empty());
  Fixture f(two_networks(R"({ "allow_changes": true })"));
  f.bus = [](const DiagRequest& r) {
    if (r.command == "stop" && r.node == 2 && !r.force)
      return diag_error("", "node 2 (n2) is OPERATIONAL; an NMT command takes it out of the program's control; force "
                            "needed");
    return ok(cJSON_CreateObject());
  };
  std::string a = f.ask("[5] 1 2 stop");
  CHECK_MSG(has(a, "[5] ERROR: 102"), a);
  CHECK(logged("force is not allowed on the CiA 309-3 gateway") >= 1);
  CHECK(has(f.ask("[6] 1 2 start"), "[6] OK"));
  CHECK(f.seen.back().op == "nmt" && f.seen.back().command == "start");
  CHECK(has(f.ask("[7] 1 2 preop"), "[7] OK") && f.seen.back().command == "preop");
  CHECK(has(f.ask("[8] 1 2 reset node"), "[8] OK") && f.seen.back().command == "reset");
  CHECK(has(f.ask("[9] 1 2 reset comm"), "[9] OK") && f.seen.back().command == "reset-comm");
  // Node 0: every configured node, as one request.
  CHECK(has(f.ask("[10] 1 0 start"), "[10] OK") && f.seen.back().node == 0);
  // A node that is not configured: nothing sent.
  size_t before = f.seen.size();
  CHECK(has(f.ask("[11] 1 9 stop"), "[11] ERROR: 107") && f.seen.size() == before);
  set_log_sink(nullptr);
}

TEST(cia309_services_not_served) {
  Fixture f(two_networks(R"({ "allow_changes": true })"));
  for (const char* line : {"[1] 1 set heartbeat 100", "[1] 1 init 0", "[1] 1 set id 5", "[1] 1 2 enable heartbeat 100",
                           "[1] 1 2 disable guarding", "[1] 1 w p 1 1 5", "[1] 1 lss_activate_bitrate 100",
                           "[1] 1 lss_switch_glob 1"}) {
    std::string a = f.ask(line);
    CHECK_MSG(has(a, "[1] ERROR: 100"), std::string(line) + " -> " + a);
  }
  CHECK(f.seen.empty());
  // Answered on the gateway thread.
  std::string v = f.ask("[2] info version");
  CHECK_MSG(has(v, "[2] ") && has(v, "2.1"), v);
  CHECK(has(f.ask("[3] set command_timeout 2000"), "[3] OK"));
  CHECK(f.seen.empty());
}

TEST(cia309_pdo_read) {
  Fixture f(two_networks("{}"));
  f.bus = [](const DiagRequest& r) {
    if (r.pdo != 1) return diag_error("", "PDO not configured: node 2 has no TPDO 2 the master maps");
    cJSON* res = cJSON_CreateObject();
    cJSON* list = cJSON_AddArrayToObject(res, "values");
    cJSON_AddItemToArray(list, obj({{"raw", "513"}}));
    cJSON_AddItemToArray(list, obj({{"raw", "7"}}));
    return ok(res);
  };
  // Node 2's TPDO 1 is gateway RPDO (2 - 1) * 4 + 1 = 5. A single number
  // before "r p" is a node ID to Lely, so the network is the default one, or
  // "<net> 0" in front.
  CHECK(has(f.ask("[5] 1 r p 5"), "[5] ERROR: 104"));
  std::string a = f.ask("[6] 1 0 r p 5");
  std::printf("    %s", a.c_str());
  CHECK_MSG(has(a, "[6] 1 pdo 2 0x201 0x7"), a);
  CHECK(f.seen.size() == 1 && f.seen[0].op == "pdo_read" && f.seen[0].node == 2 && f.seen[0].pdo == 1);
  CHECK(has(f.ask("[1] set network 1"), "[1] OK"));
  CHECK(has(f.ask("[7] r p 6"), "[7] ERROR: 102"));
  // Node 3 is not configured: refused here.
  size_t before = f.seen.size();
  CHECK(has(f.ask("[8] r p 9"), "[8] ERROR: 102") && f.seen.size() == before);
}

TEST(cia309_pipelining_limit_and_command_timeout) {
  Fixture f(two_networks("{}"));
  std::string lines;
  for (int i = 1; i <= 10; ++i) lines += "[" + std::to_string(i) + "] 1 2 r 0x1000 0 u32\r\n";
  lines.erase(lines.size() - 2);
  std::string a = f.ask(lines);  // the bus thread keeps them
  CHECK_MSG(has(a, "[9] ERROR: 102") && has(a, "[10] ERROR: 102") && !has(a, "[1] "), a);
  // One at a time on the bus thread, in order.
  CHECK(f.seen.size() == 1 && f.s->outstanding() == 8);
  f.hubs[0]->answer(f.seen[0].seq, diag_error("", "timeout (the node is booting)"));
  f.pump();
  a = f.s->output();
  f.s->output().clear();
  CHECK_MSG(has(a, "[1] ERROR: 103"), a);
  CHECK(f.seen.size() == 2);
  // No answer within the command timeout: 103, and the next one goes.
  f.s->poll(f.now + std::chrono::seconds(6));
  f.pump();
  a = f.s->output();
  f.s->output().clear();
  CHECK_MSG(has(a, "[2] ERROR: 103"), a);
  CHECK(f.seen.size() == 3);
  // The late answer is dropped.
  CHECK(!f.s->answer(0, f.seen[1].seq, ok(cJSON_CreateObject()), f.now));
}

TEST(cia309_line_limit) {
  Fixture f(two_networks("{}"));
  std::string big(Cia309Session::kMaxLine + 10, 'x');
  CHECK(!f.s->feed(big.data(), big.size(), f.now));
}

TEST(cia309_notifications) {
  Fixture f(two_networks("{}"));
  DiagEvent e;
  e.kind = DiagEvent::Emcy;
  e.node = 2;
  e.code = 0x5030;
  e.er = 0x01;
  e.msef = {1, 2, 3, 4, 5};
  f.s->event(0, e);
  DiagEvent b;
  b.kind = DiagEvent::Bootup;
  b.node = 4;
  f.s->event(1, b);
  DiagEvent h;
  h.kind = DiagEvent::HeartbeatLost;
  h.node = 7;
  f.s->event(0, h);
  DiagEvent st;
  st.kind = DiagEvent::State;
  st.node = 2;
  st.state = 4;
  f.s->event(0, st);
  std::string out = f.s->output();
  f.s->output().clear();
  std::printf("%s", out.c_str());
  CHECK_MSG(has(out, "1 2 EMCY 5030 01 1 2 3 4 5\r\n"), out);
  CHECK_MSG(has(out, "2 4 BOOT_UP\r\n"), out);
  CHECK_MSG(has(out, "1 7 ERROR 203"), out);
  CHECK_MSG(has(out, "1 2 ERRORx STOP"), out);
  // Boot-up indication off for network 2.
  CHECK(has(f.ask("[1] 2 boot_up_indication Disable"), "[1] OK"));
  f.s->event(1, b);
  CHECK(f.s->output().empty());
  // A reader that falls behind loses the oldest, and is told.
  for (int i = 0; i < 1100; ++i) f.s->event(0, e);
  f.s->lost(5);
  CHECK(f.s->notifications_waiting() == Cia309Session::kMaxNotifications);
  std::string all;
  for (int i = 0; i < 20 && (f.s->notifications_waiting() || all.empty()); ++i) {
    all += f.s->output();
    f.s->output().clear();
  }
  CHECK_MSG(has(all, "# 81 notifications lost"), all.substr(0, 200));
}

TEST(cia309_lss) {
  Fixture ro(two_networks("{}"));
  for (const char* line : {"[1] 1 lss_switch_glob 0", "[1] 1 lss_switch_sel 1 2 3 4", "[1] 1 _lss_fastscan 0 0 0 0 0 0 0 0"})
    CHECK(has(ro.ask(line), "[1] ERROR: 102"));
  CHECK(ro.seen.empty());
  Fixture f(two_networks(R"({ "allow_changes": true })"));
  int polls = 0;
  f.bus = [&polls](const DiagRequest& r) {
    cJSON* res = cJSON_CreateObject();
    if (r.op == "lss_find") {
      cJSON_AddBoolToObject(res, "running", true);
    } else if (r.op == "lss_find_status") {
      bool done = ++polls >= 2;
      cJSON_AddBoolToObject(res, "running", !done);
      if (done) {
        cJSON_AddBoolToObject(res, "found", true);
        cJSON* d = cJSON_AddObjectToObject(res, "device");
        cJSON_AddNumberToObject(d, "vendor_id", 0x360);
        cJSON_AddNumberToObject(d, "product_code", 0);
        cJSON_AddNumberToObject(d, "revision_number", 0);
        cJSON_AddNumberToObject(d, "serial_number", 0x42);
        cJSON_AddNumberToObject(d, "node_id", 255);
      }
    } else if (r.op == "lss_inquire") {
      cJSON_AddNumberToObject(res, "node_id", 40);
    }
    return ok(res);
  };
  // Nothing selected yet.
  CHECK(has(f.ask("[1] 1 lss_set_node 40"), "[1] ERROR: 102"));
  // The search, polled until it ends; the found device is selected.
  std::string a = f.ask("[2] 1 _lss_fastscan 0 0 0 0 0 0 0 0");
  CHECK(a.empty() && f.seen.size() == 1 && f.seen[0].op == "lss_find" && !f.seen[0].lss_known);
  for (int i = 0; i < 5 && a.empty(); ++i) {
    f.now += std::chrono::milliseconds(250);
    f.s->poll(f.now);
    f.pump();
    a = f.s->output();
  }
  f.s->output().clear();
  CHECK_MSG(has(a, "[2] 0x00000360 0x00000000 0x00000000 0x00000042"), a);
  // Set node 40, without store.
  CHECK(has(f.ask("[3] 1 lss_set_node 40"), "[3] OK"));
  const DiagRequest& r = f.seen.back();
  CHECK(r.op == "lss_set_id" && r.node == 40 && !r.store && r.lss[0] == 0x360 && r.lss[3] == 0x42);
  CHECK(has(f.ask("[4] 1 lss_set_node 1"), "[4] ERROR: 102"));  // the master's
  CHECK(has(f.ask("[5] 1 lss_store"), "[5] OK") && f.seen.back().op == "lss_store");
  CHECK(has(f.ask("[6] 1 lss_get_node"), "[6] 40") && f.seen.back().op == "lss_inquire");
  CHECK(has(f.ask("[7] 1 lss_inquire_addr 0x5D"), "[7] 0x00000042"));
  CHECK(has(f.ask("[8] 1 lss_conf_bitrate 0 3"), "[8] OK") && f.seen.back().bitrate_kbit == 250 &&
        !f.seen.back().store);
  CHECK(has(f.ask("[9] 1 lss_conf_bitrate 0 5"), "[9] ERROR: 102"));
  // switch_sel then switch_glob 0: the selection goes.
  CHECK(has(f.ask("[10] 1 lss_switch_sel 1 2 3 4"), "[10] OK"));
  CHECK(has(f.ask("[11] 1 lss_switch_glob 0"), "[11] OK"));
  CHECK(has(f.ask("[12] 1 lss_store"), "[12] ERROR: 102"));
  // Only vendor ID and product code can be fixed.
  CHECK(has(f.ask("[14] 1 _lss_fastscan 0 0 0 0 0 0 5 0xFF"), "[14] ERROR: 102"));
}

TEST(cia309_hub_answers_and_events) {
  ConfigSet set;
  std::vector<std::string> errors;
  CHECK(parse_config_set(two_networks("{}"), "/tmp/x/canworks.json", ImageLimits(), set, errors));
  DiagHub hub(set.networks[0], "v");
  hub.attach();
  // A gateway request's answer goes to the gateway, a diagnostics one's not.
  DiagRequest g;
  g.op = "status";
  g.from_cia309 = true;
  uint64_t gs = hub.submit(g);
  DiagRequest d;
  d.op = "status";
  uint64_t ds = hub.submit(d);
  std::vector<DiagRequest> taken;
  hub.take(taken);
  hub.answer(gs, "g\n");
  hub.answer(ds, "d\n");
  std::vector<std::pair<uint64_t, std::string>> ga, da;
  hub.take_gateway_answers(ga);
  hub.take_answers(da);
  CHECK(ga.size() == 1 && ga[0].first == gs && da.size() == 1 && da[0].first == ds);
  // Detached: offline answers keep their way too.
  uint64_t gs2 = hub.submit(g);
  hub.detach();
  ga.clear();
  hub.take_gateway_answers(ga);
  CHECK(ga.size() == 1 && ga[0].first == gs2);
  // Events only while on; a full queue drops its oldest.
  DiagEvent e;
  hub.push_event(e);
  std::vector<DiagEvent> ev;
  CHECK(hub.take_events(ev) == 0 && ev.empty());
  hub.set_events(true);
  for (size_t i = 0; i < DiagHub::kMaxEvents + 10; ++i) {
    e.node = static_cast<uint8_t>(i % 100);
    hub.push_event(e);
  }
  CHECK(hub.take_events(ev) == 10 && ev.size() == DiagHub::kMaxEvents && ev.front().node == 10);
  hub.set_events(false);
  hub.push_event(e);
  ev.clear();
  CHECK(hub.take_events(ev) == 0 && ev.empty());
}

namespace {

// A blocking line client on a plain TCP port.
struct LineClient {
  int fd = -1;
  std::string buf;
  explicit LineClient(unsigned port) {
    fd = socket(AF_INET, SOCK_STREAM, 0);
    sockaddr_in a{};
    a.sin_family = AF_INET;
    a.sin_port = htons(static_cast<uint16_t>(port));
    inet_pton(AF_INET, "127.0.0.1", &a.sin_addr);
    if (connect(fd, reinterpret_cast<sockaddr*>(&a), sizeof a) != 0) {
      close(fd);
      fd = -1;
    }
  }
  ~LineClient() {
    if (fd >= 0) close(fd);
  }
  void send_line(const std::string& l) {
    std::string s = l + "\r\n";
    ssize_t r = ::send(fd, s.data(), s.size(), MSG_NOSIGNAL);
    (void)r;
  }
  std::string line(int ms = 3000) {
    auto end = clock_type::now() + std::chrono::milliseconds(ms);
    for (;;) {
      size_t nl = buf.find('\n');
      if (nl != std::string::npos) {
        std::string l = buf.substr(0, nl);
        buf.erase(0, nl + 1);
        if (!l.empty() && l.back() == '\r') l.pop_back();
        return l;
      }
      int left = static_cast<int>(std::chrono::duration_cast<std::chrono::milliseconds>(end - clock_type::now()).count());
      if (left <= 0) return "";
      pollfd p{fd, POLLIN, 0};
      if (poll(&p, 1, left) <= 0) return "";
      char tmp[4096];
      ssize_t n = recv(fd, tmp, sizeof tmp, 0);
      if (n <= 0) return "<closed>";
      buf.append(tmp, static_cast<size_t>(n));
    }
  }
};

// The TLS client of the diagnostics channel, with the SCRAM login.
struct TlsClient {
  LineClient raw;
  std::unique_ptr<TlsConn> tls;
  std::string plain;
  bool failed = false;
  explicit TlsClient(unsigned port) : raw(port) {
    std::string why;
    tls = TlsConn::client(why);
    tls->start(why);
    flush();
  }
  void flush() {
    std::string& w = tls->wire();
    if (!w.empty()) {
      ssize_t r = ::send(raw.fd, w.data(), w.size(), MSG_NOSIGNAL);
      (void)r;
    }
    w.clear();
  }
  void pump(int ms) {
    pollfd p{raw.fd, POLLIN, 0};
    if (poll(&p, 1, ms) <= 0) return;
    char tmp[4096];
    ssize_t n = recv(raw.fd, tmp, sizeof tmp, 0);
    std::string why;
    if (n <= 0 || !tls->feed(tmp, static_cast<size_t>(n), plain, why)) failed = true;
    flush();
  }
  void write(const std::string& l) {
    std::string why;
    tls->write(l + "\n", why);
    flush();
  }
  std::string line(int ms = 3000) {
    auto end = clock_type::now() + std::chrono::milliseconds(ms);
    for (;;) {
      size_t nl = plain.find('\n');
      if (nl != std::string::npos) {
        std::string l = plain.substr(0, nl);
        plain.erase(0, nl + 1);
        if (!l.empty() && l.back() == '\r') l.pop_back();
        return l;
      }
      if (failed) return "<closed>";
      if (clock_type::now() >= end) return "";
      pump(50);
    }
  }
  bool login() {
    auto end = clock_type::now() + std::chrono::seconds(3);
    while (!tls->established() && !failed && clock_type::now() < end) pump(50);
    if (!tls->established()) return false;
    std::string cnonce = b64_encode(random_bytes(18));
    write(R"({"op":"hello","mech":"SCRAM-SHA-256-PLUS","nonce":")" + cnonce + "\"}");
    cJSON* a = cJSON_Parse(line().c_str());
    const cJSON* r = cJSON_GetObjectItemCaseSensitive(a, "result");
    if (!r) {
      cJSON_Delete(a);
      return false;
    }
    std::string snonce = cJSON_GetObjectItemCaseSensitive(r, "nonce")->valuestring;
    std::string salt_b64 = cJSON_GetObjectItemCaseSensitive(r, "salt")->valuestring;
    unsigned iter = static_cast<unsigned>(cJSON_GetObjectItemCaseSensitive(r, "iterations")->valuedouble);
    cJSON_Delete(a);
    Bytes salt, proof, sig;
    b64_decode(salt_b64, salt);
    std::string auth = scram_auth_message(cnonce, snonce, salt_b64, iter, tls->peer_cert_hash());
    scram_client("secret", salt, iter, auth, proof, sig);
    write(R"({"op":"login","proof":")" + b64_encode(proof) + "\"}");
    return line().find("\"cia309\":true") != std::string::npos;
  }
};

// The bus thread of the server tests: answers every SDO read with 0x1A2.
struct BusThread {
  std::vector<DiagHub*> hubs;
  std::atomic<bool> stop{false};
  std::thread t;
  explicit BusThread(std::vector<DiagHub*> h) : hubs(std::move(h)) {
    t = std::thread([this] {
      while (!stop) {
        for (DiagHub* hub : hubs) {
          std::vector<DiagRequest> reqs;
          hub->take(reqs);
          for (auto& r : reqs) {
            cJSON* res = cJSON_CreateObject();
            if (r.op == "sdo_read") {
              cJSON_AddBoolToObject(res, "success", true);
              cJSON_AddStringToObject(res, "data", "A2 01 00 00");
            }
            hub->answer(r.seq, diag_ok(r.id, res));
          }
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(2));
      }
    });
  }
  ~BusThread() {
    stop = true;
    t.join();
  }
};

}  // namespace

TEST(cia309_server_plain_port_and_limit) {
  set_log_sink(capture);
  Fixture f(two_networks(R"({ "max_clients": 2 })"));
  std::vector<Cia309Net> nets = f.nets;
  Cia309Server server(f.set.networks[0].master.cia309, nets, "test-1");
  server.listen_any_port();
  server.start();
  for (int i = 0; i < 200 && !server.port(); ++i) std::this_thread::sleep_for(std::chrono::milliseconds(5));
  CHECK(server.port() != 0);
  CHECK(logged("CiA 309-3 gateway listens on 127.0.0.1:") == 1 && logged("read-only; networks 1 = io, 2 = drives") == 1);
  BusThread bus({f.hubs[0].get(), f.hubs[1].get()});
  LineClient a(server.port()), b(server.port());
  a.send_line("[1] 1 2 r 0x1018 1 u32");
  std::string got = a.line();
  CHECK_MSG(got == "[1] 0x000001a2", got);
  b.send_line("[1] 2 4 r 0x1018 1 u32");
  CHECK(b.line() == "[1] 0x000001a2");
  // A third: one ERROR: 102 line, closed.
  LineClient c(server.port());
  std::string l = c.line();
  CHECK_MSG(l.find("ERROR: 102") == 0, l);
  CHECK(c.line() == "<closed>");
  CHECK(server.sessions() == 2);
  cJSON* st = server.status();
  CHECK(cJSON_GetArraySize(cJSON_GetObjectItemCaseSensitive(st, "sessions")) == 2);
  cJSON_Delete(st);
  server.stop();
  set_log_sink(nullptr);
}

TEST(cia309_server_hand_over_from_diagnostics) {
  Fixture f(two_networks(R"({ "max_clients": 1 })", true));
  for (auto& cfg : f.set.networks) cfg.master.diag_port = 0;  // any free port
  Cia309Server gw(f.set.networks[0].master.cia309, f.nets, "test-1");
  gw.listen_any_port();
  DiagServer diag({f.hubs[0].get(), f.hubs[1].get()});
  diag.set_cia309(gw.hooks());
  gw.start();
  diag.start();
  for (int i = 0; i < 200 && !diag.port(); ++i) std::this_thread::sleep_for(std::chrono::milliseconds(5));
  BusThread bus({f.hubs[0].get(), f.hubs[1].get()});
  // Four diagnostics clients: the limit.
  std::vector<std::unique_ptr<TlsClient>> clients;
  for (int i = 0; i < 4; ++i) {
    clients.emplace_back(new TlsClient(diag.port()));
    CHECK(clients.back()->login());
  }
  // One switches: the JSON answer, then CiA 309-3 lines in the same TLS session.
  TlsClient& t = *clients[0];
  t.write(R"({"op":"cia309","id":5})");
  std::string a = t.line();
  CHECK_MSG(a.find("\"ok\":true") != std::string::npos && a.find("\"CiA 309-3\"") != std::string::npos &&
                a.find("\"name\":\"drives\"") != std::string::npos,
            a);
  t.write("[1] 1 2 r 0x1018 1 u32");
  a = t.line();
  CHECK_MSG(a == "[1] 0x000001a2", a);
  CHECK(gw.sessions() == 1);
  // Its diagnostics slot is free again.
  TlsClient fifth(diag.port());
  CHECK(fifth.login());
  // The gateway full: the op is refused and the connection stays a diagnostics one.
  TlsClient& u = *clients[1];
  u.write(R"({"op":"cia309"})");
  a = u.line();
  CHECK_MSG(a.find("too many gateway clients") != std::string::npos, a);
  u.write(R"({"op":"status","network":"io"})");
  CHECK(u.line().find("\"ok\":true") != std::string::npos);
  diag.stop();
  gw.stop();
}

TEST(cia309_op_without_gateway) {
  Fixture f(two_networks("{}", true));
  for (auto& cfg : f.set.networks) {
    cfg.master.diag_port = 0;
    cfg.master.cia309.enabled = false;
  }
  DiagServer diag({f.hubs[0].get(), f.hubs[1].get()});
  diag.start();
  for (int i = 0; i < 200 && !diag.port(); ++i) std::this_thread::sleep_for(std::chrono::milliseconds(5));
  TlsClient c(diag.port());
  CHECK(!c.login());  // the login answer says cia309: false
  c.write(R"({"op":"cia309"})");
  CHECK(c.line().find("cia309 gateway not configured") != std::string::npos);
  diag.stop();
}

int main(int argc, char** argv) { return check::run_all(argc, argv); }
