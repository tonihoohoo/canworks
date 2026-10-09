// raw_devices.cpp - see raw_devices.h.

#include "raw_devices.h"

#include <unistd.h>

#include <algorithm>
#include <cmath>
#include <cstring>
#include <fstream>
#include <limits>
#include <sstream>

#include "cJSON.h"
#include "sim_raw.h"

namespace canworks_raw {

namespace {

// Plain CAN devices have no object dictionary.
class NoObjects : public canopen_sim::ExprResolver {
 public:
  int self() const override { return 0; }
  int device(const std::string&) const override { return -1; }
  bool has_object(int, uint16_t, uint8_t) const override { return false; }
};

class NoObjectsContext : public canopen_sim::ExprContext {
 public:
  double value(const canopen_sim::ObjectRef&) override { return std::nan(""); }
};

canopen_sim::RawFrame to_sim(const canworks_can_frame& f) {
  canopen_sim::RawFrame r;
  r.id = f.id;
  r.extended = (f.flags & CANWORKS_CAN_EXTENDED) != 0;
  r.rtr = (f.flags & CANWORKS_CAN_RTR) != 0;
  r.dlc = f.dlc > 8 ? 8 : f.dlc;
  std::memcpy(r.data, f.data, 8);
  return r;
}

canworks_can_frame from_sim(const canopen_sim::RawFrame& r) {
  canworks_can_frame f{};
  f.id = r.id;
  f.flags = static_cast<uint8_t>((r.extended ? CANWORKS_CAN_EXTENDED : 0) | (r.rtr ? CANWORKS_CAN_RTR : 0));
  f.dlc = r.dlc > 8 ? 8 : r.dlc;
  std::memcpy(f.data, r.data, 8);
  return f;
}

}  // namespace

RawSimDevices::RawSimDevices() : rng_(1) {}
RawSimDevices::~RawSimDevices() = default;

bool RawSimDevices::load(const std::string& path, const std::string& network, bool several,
                         std::vector<std::string>& errors) {
  std::ifstream in(path);
  if (!in) {
    errors.push_back(path + ": cannot read the file");
    return false;
  }
  std::stringstream ss;
  ss << in.rdbuf();
  size_t slash = path.rfind('/');
  std::string dir = slash == std::string::npos ? "." : path.substr(0, slash);
  return load_text(ss.str(), path, dir.empty() ? "/" : dir, network, several, errors);
}

bool RawSimDevices::load_text(const std::string& json, const std::string& path, const std::string& dir,
                              const std::string& network, bool several, std::vector<std::string>& errors) {
  devices_.clear();
  cJSON* root = cJSON_Parse(json.c_str());
  if (!root) {
    errors.push_back(path + ": not valid JSON");
    return false;
  }
  std::unique_ptr<cJSON, void (*)(cJSON*)> guard(root, cJSON_Delete);
  const cJSON* list = cJSON_GetObjectItemCaseSensitive(root, "raw_devices");
  if (!list) return true;
  std::vector<canopen_sim::RawDeviceSpec> specs;
  std::vector<std::string> errs;
  bool ok = canopen_sim::parse_raw_devices(list, specs, errs);
  NoObjects resolver;
  for (size_t i = 0; i < specs.size(); ++i) {
    if (specs[i].network.empty() && several) {
      errs.push_back("raw_devices[" + std::to_string(i) + "]: \"network\" is required when the configuration has "
                     "several networks");
      ok = false;
      continue;
    }
    if (!specs[i].network.empty() && specs[i].network != network) continue;
    std::unique_ptr<canopen_sim::RawDevice> d(new canopen_sim::RawDevice(specs[i]));
    if (!d->bind(dir, resolver, errs)) ok = false;
    devices_.push_back(std::move(d));
  }
  for (const auto& e : errs) errors.push_back(path + ": " + e);
  if (!ok) devices_.clear();
  return ok;
}

std::vector<std::string> RawSimDevices::names() const {
  std::vector<std::string> n;
  for (const auto& d : devices_) n.push_back(d->name());
  return n;
}

void RawSimDevices::start(uint64_t now_ms) {
  for (auto& d : devices_) d->power_on(now_ms);
}

void RawSimDevices::on_frame(const canworks_can_frame& f, uint64_t now_ms) {
  if (devices_.empty()) return;
  canopen_sim::RawFrame r = to_sim(f);
  for (auto& d : devices_) d->on_frame(r, now_ms);
}

void RawSimDevices::due(uint64_t now_ms, std::vector<canworks_can_frame>& out) {
  NoObjectsContext ctx;
  ctx.rng = &rng_;
  std::vector<canopen_sim::RawFrame> frames;
  for (auto& d : devices_) d->due(now_ms, frames, ctx);
  for (const auto& r : frames) out.push_back(from_sim(r));
}

uint64_t RawSimDevices::next_in(uint64_t now_ms) const {
  uint64_t next = std::numeric_limits<uint64_t>::max();
  for (const auto& d : devices_) next = std::min(next, d->next_in(now_ms));
  return next;
}

std::string find_simulation_file(const std::string& config_dir, const std::string& fallback_dir) {
  std::vector<std::string> c = {config_dir + "/simulation.json", config_dir + "/canworks/simulation.json"};
  if (!fallback_dir.empty()) {
    c.push_back(fallback_dir + "/canworks/simulation.json");
    c.push_back(fallback_dir + "/simulation.json");
  }
  for (const auto& p : c)
    if (access(p.c_str(), R_OK) == 0) return p;
  return "";
}

}  // namespace canworks_raw
