// mailbox_engine.h - the mailboxes' backend on the engine (mailboxes.h): the
// SDO request queue, the frame ports, the J1939 message and trouble code
// slots and the EMCY history, through the same internal tables the PLC
// blocks of the plugin used, so every limit, guard and ERROR_ID is theirs.

#ifndef CANWORKS_BRIDGE_MAILBOX_ENGINE_H
#define CANWORKS_BRIDGE_MAILBOX_ENGINE_H

#include <cstdint>
#include <memory>
#include <vector>

#include "mailboxes.h"

namespace canworks_bridge {

class EngineMailboxBackend : public MailboxBackend {
 public:
  explicit EngineMailboxBackend(unsigned networks);
  ~EngineMailboxBackend() override;

  std::unique_ptr<MbJob> start(const MbCall& call, MbAnswer& now) override;
  uint32_t rx_open(const RxSpec& spec, uint8_t& error) override;
  int rx_read(uint32_t handle, RxRecord& rec, uint8_t& error) override;
  void rx_close(uint32_t handle) override;
  uint32_t cyc_start(uint8_t network, const CyclicFrame& f, uint8_t& error) override;
  bool cyc_update(uint32_t handle, const CyclicFrame* f, uint32_t& count, uint8_t& error) override;
  void cyc_stop(uint32_t handle) override;
  bool net_info(unsigned network, NetInfo& out) override;
  bool has_network(unsigned network) const override { return network < networks_; }

 private:
  struct Rx;
  struct Cyclic;
  unsigned networks_;
  // Mailbox handles: index + 1 into these.
  std::vector<std::unique_ptr<Rx>> rx_;
  std::vector<std::unique_ptr<Cyclic>> cyc_;
};

}  // namespace canworks_bridge

#endif
