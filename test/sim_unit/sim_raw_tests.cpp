// Unit tests of the simulation file's plain CAN devices (sim_raw.h): parsing,
// periodic frames with signal sources, replies and the faults.

#include <cmath>
#include <string>
#include <vector>

#include "can/signals.h"
#include "check.hpp"
#include "cJSON.h"
#include "sim_raw.h"

using namespace canopen_sim;

namespace {

class NoDevices : public ExprResolver {
 public:
  int self() const override { return -1; }
  int device(const std::string&) const override { return -1; }
  bool has_object(int, uint16_t, uint8_t) const override { return false; }
};

class NoValues : public ExprContext {
 public:
  double value(const ObjectRef&) override { return 0; }
};

std::vector<RawDeviceSpec> parse(const char* text, std::vector<std::string>& errors) {
  std::vector<RawDeviceSpec> out;
  cJSON* j = cJSON_Parse(text);
  parse_raw_devices(j, out, errors);
  cJSON_Delete(j);
  return out;
}

bool has_error(const std::vector<std::string>& errors, const std::string& part) {
  for (const auto& e : errors)
    if (e.find(part) != std::string::npos) return true;
  return false;
}

const char* kJoystick = R"([{"name": "joystick", "send": [{"name": "Joystick", "id": 384, "dlc": 4, "period_ms": 100,
  "signals": [{"name": "X", "start_bit": 0, "length": 16, "signed": true,
               "source": {"sine": {"min": -1000, "max": 1000, "period_s": 4}}},
              {"name": "B", "start_bit": 16, "length": 8, "source": {"constant": 7}}]}],
  "replies": [{"on": {"id": 2016, "data": [2, 1, 12]}, "send": {"id": 2024, "data": [4, 65, 12, 26, 248]}}]}])";

}  // namespace

TEST(sim_raw_parse_and_send) {
  std::vector<std::string> errors;
  auto specs = parse(kJoystick, errors);
  CHECK(errors.empty());
  CHECK(specs.size() == 1 && specs[0].sends.size() == 1 && specs[0].replies.size() == 1);
  RawDevice dev(specs[0]);
  NoDevices res;
  CHECK(dev.bind("", res, errors));
  NoValues ctx;
  std::vector<RawFrame> out;
  dev.due(0, out, ctx);
  CHECK(out.empty());  // not powered
  dev.power_on(1000);
  dev.due(1000, out, ctx);
  CHECK(out.size() == 1 && out[0].id == 384 && out[0].dlc == 4 && out[0].data[2] == 7);
  // A quarter period later the sine is at its top.
  out.clear();
  for (uint64_t t = 1100; t <= 2000; t += 100) dev.due(t, out, ctx);
  CHECK(out.size() == 10);
  int64_t x = canworks_can::sign_extend(canworks_can::unpack_signal(out.back().data, 4, 0, 16, false), 16);
  CHECK(x == 1000);
  CHECK(dev.next_in(2000) == 100);
}

TEST(sim_raw_reply_and_faults) {
  std::vector<std::string> errors;
  auto specs = parse(kJoystick, errors);
  RawDevice dev(specs[0]);
  NoDevices res;
  NoValues ctx;
  dev.bind("", res, errors);
  dev.power_on(0);
  std::vector<RawFrame> out;
  dev.due(0, out, ctx);
  out.clear();
  RawFrame req;
  req.id = 2016;
  req.dlc = 8;
  req.data[0] = 2, req.data[1] = 1, req.data[2] = 12;
  dev.on_frame(req, 10);
  req.data[2] = 13;  // other data: no reply
  dev.on_frame(req, 10);
  dev.due(10, out, ctx);
  CHECK(out.size() == 1 && out[0].id == 2024 && out[0].dlc == 5 && out[0].data[4] == 248);
  // Wrong DLC fault.
  dev.set_dlc_fault(2);
  out.clear();
  dev.due(100, out, ctx);
  CHECK(out.size() == 1 && out[0].dlc == 2);
  // Stopped: nothing sent, no replies.
  dev.power_off();
  out.clear();
  dev.on_frame(req, 200);
  dev.due(200, out, ctx);
  CHECK(out.empty());
}

TEST(sim_raw_rejections) {
  std::vector<std::string> errors;
  parse(R"([{"name": "a", "send": [{"id": 2048, "dlc": 2, "period_ms": 10}]},
            {"name": "a", "send": [{"id": 1, "dlc": 1, "period_ms": 10,
              "signals": [{"start_bit": 4, "length": 8, "source": {"constant": 1}}]}]},
            {"name": "c", "bogus": 1, "send": [{"id": 1, "data": [1, 2], "dlc": 1, "period_ms": 0}]},
            {"name": "d"}])",
        errors);
  CHECK(has_error(errors, "raw_devices[0].send[0]: \"id\" must be an integer 0-2047"));
  CHECK(has_error(errors, "raw_devices[1]: another plain CAN device is also called \"a\""));
  CHECK(has_error(errors, "raw_devices[1].send[0].signals[0]: does not fit the frame's 1 bytes"));
  CHECK(has_error(errors, "raw_devices[2]: unknown key \"bogus\""));
  CHECK(has_error(errors, "raw_devices[2].send[0]: \"dlc\" is shorter than \"data\""));
  CHECK(has_error(errors, "raw_devices[2].send[0]: \"period_ms\" must be an integer 1-60000"));
  CHECK(has_error(errors, "raw_devices[3]: has neither \"send\" nor \"replies\""));
}

// Values outside a 64-bit signal's range are clamped to it, without the
// out-of-range double to integer cast (undefined) that gave 0 or 2^63.
TEST(sim_raw_signal_clamped) {
  std::vector<std::string> errors;
  auto specs = parse(R"([{"name": "big", "send": [{"id": 1, "dlc": 8, "period_ms": 10, "signals": [
      {"start_bit": 0, "length": 64, "source": {"constant": 1e30}}]}]},
    {"name": "neg", "send": [{"id": 2, "dlc": 8, "period_ms": 10, "signals": [
      {"start_bit": 0, "length": 64, "signed": true, "source": {"constant": -1e30}}]}]},
    {"name": "pos", "send": [{"id": 3, "dlc": 8, "period_ms": 10, "signals": [
      {"start_bit": 0, "length": 64, "signed": true, "source": {"constant": 1e30}}]}]},
    {"name": "byte", "send": [{"id": 4, "dlc": 1, "period_ms": 10, "signals": [
      {"start_bit": 0, "length": 8, "source": {"constant": 1e30}}]}]}])",
                     errors);
  CHECK_MSG(errors.empty(), errors.empty() ? "" : errors[0]);
  if (specs.size() != 4) return;
  const uint64_t want[] = {UINT64_MAX, static_cast<uint64_t>(INT64_MIN), static_cast<uint64_t>(INT64_MAX), 0xFF};
  for (size_t i = 0; i < 4; ++i) {
    RawDevice dev(specs[i]);
    NoDevices res;
    NoValues ctx;
    CHECK(dev.bind("", res, errors));
    dev.power_on(0);
    std::vector<RawFrame> out;
    dev.due(0, out, ctx);
    CHECK(out.size() == 1);
    if (out.size() != 1) continue;
    uint64_t got = canworks_can::unpack_signal(out[0].data, out[0].dlc, 0, i == 3 ? 8 : 64, false);
    CHECK_MSG(got == want[i], specs[i].name + ": " + std::to_string(got));
  }
}

// A multiplexed send: every page each period ("all", the default) or the next
// page each period ("rotate"); the simulator sets the switch.
TEST(sim_raw_multiplexed_pages) {
  std::vector<std::string> errors;
  auto specs = parse(R"([{"name": "status", "send": [
      {"name": "All", "id": 768, "dlc": 4, "period_ms": 100, "signals": [
        {"name": "Page", "start_bit": 0, "length": 8, "multiplexer": true},
        {"name": "Temp", "start_bit": 8, "length": 8, "mux": {"values": [1]}, "source": {"constant": 21}},
        {"name": "Press", "start_bit": 8, "length": 16, "mux": {"values": [2]}, "source": {"constant": 1000}},
        {"name": "Count", "start_bit": 24, "length": 8, "source": {"constant": 5}}]},
      {"name": "Rotate", "id": 769, "dlc": 2, "period_ms": 100, "pages": "rotate", "signals": [
        {"name": "Page", "start_bit": 0, "length": 8, "multiplexer": true},
        {"name": "A", "start_bit": 8, "length": 8, "mux": {"values": [[3, 4]]}, "source": {"constant": 9}}]}]}])",
                     errors);
  CHECK_MSG(errors.empty(), errors.empty() ? "" : errors[0]);
  if (specs.size() != 1) return;
  RawDevice dev(specs[0]);
  NoDevices res;
  NoValues ctx;
  CHECK(dev.bind("", res, errors));
  dev.power_on(0);
  std::vector<RawFrame> out;
  dev.due(0, out, ctx);
  CHECK(out.size() == 3);
  if (out.size() != 3) return;
  CHECK(out[0].id == 0x300 && out[0].data[0] == 1 && out[0].data[1] == 21 && out[0].data[3] == 5);
  CHECK(out[1].id == 0x300 && out[1].data[0] == 2 && out[1].data[1] == 0xE8 && out[1].data[2] == 0x03);
  CHECK(out[2].id == 0x301 && out[2].data[0] == 3 && out[2].data[1] == 9);
  out.clear();
  dev.due(100, out, ctx);
  CHECK(out.size() == 3 && out[2].data[0] == 4);
  out.clear();
  dev.due(200, out, ctx);
  CHECK(out.size() == 3 && out[2].data[0] == 3);
}

TEST(sim_raw_multiplexed_rejections) {
  std::vector<std::string> errors;
  parse(R"([{"name": "a", "send": [
      {"id": 1, "dlc": 2, "period_ms": 10, "pages": "rotate", "signals": [
        {"start_bit": 0, "length": 8, "source": {"constant": 1}}]},
      {"id": 2, "dlc": 2, "period_ms": 10, "pages": "program", "signals": [
        {"name": "P", "start_bit": 0, "length": 8, "multiplexer": true},
        {"name": "X", "start_bit": 8, "length": 8, "mux": {"values": [1]}, "source": {"constant": 1}}]},
      {"id": 3, "dlc": 2, "period_ms": 10, "signals": [
        {"name": "X", "start_bit": 8, "length": 8, "mux": {"values": [1]}}]},
      {"id": 4, "dlc": 2, "period_ms": 10, "signals": [
        {"name": "X", "start_bit": 8, "length": 8, "mux": {"values": [1]}, "source": {"constant": 1}}]}]}])",
        errors);
  CHECK(has_error(errors, "raw_devices[0].send[0]: \"pages\": only for a send with a switch (multiplexer: true)"));
  CHECK(has_error(errors, "raw_devices[0].send[1]: \"pages\" must be \"all\" or \"rotate\""));
  CHECK(has_error(errors, "raw_devices[0].send[2].signals[0]: needs a \"source\" (only a switch, multiplexer: true, has none)"));
  CHECK(has_error(errors, "raw_devices[0].send[3].signals[0].mux: the message has no switch (multiplexer: true)"));
}
