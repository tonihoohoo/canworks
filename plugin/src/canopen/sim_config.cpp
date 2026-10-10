#include "sim_config.h"

#include <chrono>
#include <cstring>
#include <linux/can.h>
#include <linux/can/raw.h>
#include <net/if.h>
#include <poll.h>
#include <sys/ioctl.h>
#include <sys/socket.h>
#include <unistd.h>

namespace canopen_plugin {

std::vector<canopen_sim::DeviceSpec> sim_device_specs(const Config& cfg, bool only_flagged,
                                                      const std::set<unsigned>& only) {
  std::vector<canopen_sim::DeviceSpec> out;
  for (const auto& n : cfg.nodes) {
    if (only_flagged && !n.simulate) continue;
    if (!only.empty() && !only.count(n.node_id)) continue;
    canopen_sim::DeviceSpec d;
    d.node = n.node_id;
    d.name = n.name;
    d.eds_path = n.eds_path;
    if (n.has_revision_number && n.revision_number) d.identity[3] = n.revision_number;
    if (n.has_serial_number) d.identity[4] = n.serial_number;
    d.lss = n.lss_assign;
    for (const auto& p : n.rx_pdos) {
      if (p.device_mapping) continue;
      for (const auto& e : p.entries)
        d.master_written[canopen_sim::ObjKey{e.index, e.subindex}] = "RPDO " + std::to_string(p.number);
    }
    // A link consumer's objects are written by the producer's TPDO.
    for (const auto& l : cfg.links)
      for (const auto& c : l.consumers) {
        if (c.node != n.node_id || c.device_mapping) continue;
        for (const auto& e : c.entries)
          if (e.index >= 0x0008)
            d.master_written[canopen_sim::ObjKey{e.index, e.subindex}] =
                l.label() + " (RPDO " + std::to_string(c.rpdo) + ", from node " + std::to_string(l.producer) +
                " TPDO " + std::to_string(l.tpdo) + ")";
      }
    for (const auto& s : n.sdos) d.master_written[canopen_sim::ObjKey{s.index, s.subindex}] = "startup SDO";
    for (const auto& v : n.sdo_variables)
      if (!v.is_read()) d.master_written[canopen_sim::ObjKey{v.index, v.subindex}] = v.label();
    out.push_back(std::move(d));
  }
  return out;
}

bool check_sim_file(const Config& cfg, const canopen_sim::SimFile& file, std::vector<std::string>& errors) {
  bool ok = true;
  for (const auto& kv : file.nodes) {
    bool known = false;
    for (const auto& n : cfg.nodes) known = known || n.node_id == kv.first;
    for (const auto& x : file.extra) known = known || x.node == kv.first;
    if (!known) {
      std::string at = file.section.empty() ? "" : "networks." + file.section + ".";
      errors.push_back(file.path + ": " + at + "nodes." + std::to_string(kv.first) + ": node " +
                       std::to_string(kv.first) + " is neither in " +
                       (file.section.empty() ? cfg.path : "network \"" + file.section + "\" of " + cfg.path) +
                       " nor an extra device" + (file.section.empty() ? "" : " of that section"));
      ok = false;
    }
  }
  // An extra device never has the node ID of a config node, simulated or
  // not (a real one would then have a twin on the bus), nor the master's.
  for (size_t i = 0; i < file.extra.size(); ++i) {
    unsigned id = file.extra[i].node;
    if (!id) continue;
    std::string at = file.path + ": " + (file.section.empty() ? "" : "networks." + file.section + ".") +
                     "extra_devices[" + std::to_string(i) + "]: node ID " + std::to_string(id);
    bool node = false;
    for (const auto& n : cfg.nodes) node = node || n.node_id == id;
    if (node) {
      errors.push_back(at + " is a node of the configuration; give its behaviour under nodes.\"" + std::to_string(id) +
                       "\"");
      ok = false;
    } else if (!cfg.is_slave() && cfg.master.node_id == id) {
      errors.push_back(at + " is the master's node ID");
      ok = false;
    }
  }
  return ok;
}

bool check_sim_sources(const Config& cfg, const canopen_sim::SimFile& file, std::vector<std::string>& errors) {
  bool ok = true;
  std::string at = file.section.empty() ? "" : "networks." + file.section + ".";
  for (const auto& d : sim_device_specs(cfg, false)) {
    auto it = file.nodes.find(d.node);
    if (it == file.nodes.end()) continue;
    for (const auto& s : it->second.sources) {
      auto mw = d.master_written.find(s.first);
      if (mw == d.master_written.end()) continue;
      errors.push_back(file.path + ": " + at + "nodes." + std::to_string(d.node) + ".sources." + s.first.str() +
                       ": node " + std::to_string(d.node) + ": " + canopen_sim::writer_text(s.first, mw->second) +
                       "; use an override to make the device ignore it");
      ok = false;
    }
  }
  return ok;
}

std::string sim_network_name(const Config& cfg) {
  return cfg.network.empty() ? cfg.adapter.interface : cfg.network;
}

bool check_sim_sections(const ConfigSet& set, const canopen_sim::SimFile& file, std::vector<std::string>& errors) {
  bool ok = true;
  std::string names;
  for (const auto& n : set.networks) names += (names.empty() ? "" : ", ") + sim_network_name(n);
  for (const auto& sec : file.networks) {
    bool known = false;
    for (const auto& n : set.networks) known = known || sim_network_name(n) == sec.network;
    if (!known) {
      errors.push_back(file.path + ": networks." + sec.network + ": there is no network \"" + sec.network + "\" in " +
                       set.path + " (networks: " + names + ")");
      ok = false;
    }
  }
  return ok;
}

std::string sim_summary(const Config& cfg, const canopen_sim::SimFile& file, const std::string& slave_network) {
  std::string nodes;
  unsigned count = 0;
  for (const auto& n : cfg.nodes) {
    if (!n.simulate) continue;
    ++count;
    nodes += (nodes.empty() ? "" : ", ") + std::to_string(n.node_id);
  }
  std::string s;
  if (cfg.adapter.simulate) {
    s = std::string("the CAN network is SIMULATED (") +
        (cfg.adapter.simulation_forced ? "forced by the runtime" : "adapter.simulate") + "): no CAN interface is used";
    s += count ? "; simulated nodes: " + nodes : "; no node is simulated";
    if (!slave_network.empty()) s += "; slave network \"" + slave_network + "\" shares the simulated bus";
  } else if (count) {
    s = "SIMULATED devices run on " + cfg.adapter.interface + " for node" + (count > 1 ? "s " : " ") + nodes;
  }
  if (!s.empty() && !file.extra.empty()) s += ", plus " + std::to_string(file.extra.size()) + " extra device(s)";
  if (!s.empty() && (count || file.extra.size() || slave_network.empty()))
    s += "; outputs to simulated devices go nowhere";
  return s;
}

bool listen_node_ids(const std::string& iface, unsigned ms, std::set<unsigned>& seen, std::string& err) {
  int fd = socket(PF_CAN, SOCK_RAW, CAN_RAW);
  if (fd < 0) {
    err = std::string("cannot open a CAN socket: ") + std::strerror(errno);
    return false;
  }
  struct ifreq ifr;
  std::memset(&ifr, 0, sizeof ifr);
  std::strncpy(ifr.ifr_name, iface.c_str(), IFNAMSIZ - 1);
  if (ioctl(fd, SIOCGIFINDEX, &ifr) < 0) {
    err = "no CAN interface " + iface;
    close(fd);
    return false;
  }
  struct sockaddr_can addr;
  std::memset(&addr, 0, sizeof addr);
  addr.can_family = AF_CAN;
  addr.can_ifindex = ifr.ifr_ifindex;
  if (bind(fd, reinterpret_cast<struct sockaddr*>(&addr), sizeof addr) < 0) {
    err = "cannot listen on " + iface + ": " + std::strerror(errno);
    close(fd);
    return false;
  }
  auto end = std::chrono::steady_clock::now() + std::chrono::milliseconds(ms);
  while (true) {
    auto left = std::chrono::duration_cast<std::chrono::milliseconds>(end - std::chrono::steady_clock::now()).count();
    if (left <= 0) break;
    struct pollfd p = {fd, POLLIN, 0};
    if (poll(&p, 1, static_cast<int>(left)) <= 0) continue;
    struct can_frame f;
    if (read(fd, &f, sizeof f) != static_cast<ssize_t>(sizeof f)) continue;
    if (f.can_id & (CAN_EFF_FLAG | CAN_ERR_FLAG | CAN_RTR_FLAG)) continue;
    unsigned id = f.can_id & CAN_SFF_MASK;
    unsigned fn = id & 0x780, node = id & 0x7F;
    if (!node) continue;
    if (fn == 0x700 || (fn == 0x080 && f.can_dlc == 8) || fn == 0x580) seen.insert(node);
  }
  close(fd);
  return true;
}

}  // namespace canopen_plugin
