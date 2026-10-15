// j1939_plc_msgs.h - the slots behind version 2 of canworks_j1939_api (spec
// j1939-plc-blocks): the sends and requests the PLC program starts with
// J1939_SEND and J1939_REQUEST, the receivers of J1939_RECEIVE, and the
// ECU snapshot J1939_ECU_INFO and J1939_FIND_ECU read.
//
// As in J1939PlcJobs, the PLC task threads only copy into and out of slots
// that exist from the start, under a mutex held for the copy; the bus thread
// of each J1939 network takes its jobs, runs them in its J1939Engine and
// puts the results back. A receiver's queue is allocated by the bus thread
// when it takes the receiver into use, never on the scan path.

#ifndef CANWORKS_J1939_PLC_MSGS_H
#define CANWORKS_J1939_PLC_MSGS_H

#include <atomic>
#include <chrono>
#include <cstdint>
#include <memory>
#include <mutex>
#include <vector>

#include "j1939_plc_api.h"

namespace canopen_plugin {

class J1939PlcMsgs {
 public:
  using clock = std::chrono::steady_clock;
  static constexpr unsigned kMaxNetworks = 32;
  static constexpr unsigned kReceiverSlots = 64;  // all networks; 16 per network
  static constexpr std::chrono::seconds kKeepResult{10};
  static constexpr std::chrono::seconds kGrace{2};

  enum class Kind : uint8_t { Send, Request };
  // A send or a request as the bus thread takes it.
  struct Job {
    uint32_t handle = 0;
    Kind kind = Kind::Send;
    uint32_t pgn = 0;
    uint8_t destination = 255;
    uint8_t priority = 6;
    uint32_t timeout_ms = 0;
    std::vector<uint8_t> data;
  };
  // An open receiver's filter, for the bus thread.
  struct Filter {
    uint32_t handle = 0;
    uint32_t pgn = 0;
    bool any = false;
    uint8_t source = 255;
    bool all_destinations = false;
  };
  // A receiver's counts, for the status answer.
  struct RxStatus {
    Filter filter;
    uint16_t queued = 0;
    uint32_t dropped = 0;
  };
  struct Ecu {
    uint8_t address = 0;
    uint64_t name = 0;
  };

  static J1939PlcMsgs& instance();

  // Plugin lifecycle, as J1939PlcJobs: open() with one flag per network
  // (true: J1939), close() when the PLC stops (every send, request and
  // receiver ends; their handles answer CANWORKS_J1939_ERR_CANCELLED).
  void open(const std::vector<bool>& j1939_networks);
  void close();
  bool running() const { return running_.load(std::memory_order_acquire); }
  void set_attached(unsigned network, bool attached);
  // The table versions programs asked for that the plugin does not offer
  // (logged once by a bus thread).
  void note_unknown_version(uint32_t v);
  uint32_t take_unknown_version();

  // ---- PLC task threads ----
  uint32_t send_start(uint8_t network, uint32_t pgn, uint8_t destination, uint8_t priority, const uint8_t* data,
                      uint16_t length, uint32_t timeout_ms, uint16_t& error_id);
  uint32_t request_start(uint8_t network, uint32_t pgn, uint8_t destination, uint32_t timeout_ms,
                         uint16_t& error_id);
  int poll(uint32_t handle, Kind kind, canworks_j1939_msg* out, uint16_t& error_id) {
    return poll(handle, kind, out, error_id, clock::now());
  }
  int poll(uint32_t handle, Kind kind, canworks_j1939_msg* out, uint16_t& error_id, clock::time_point now);
  void cancel(uint32_t handle);
  uint32_t rx_open(uint8_t network, uint32_t pgn, uint8_t source, uint8_t flags, uint16_t depth,
                   uint16_t& error_id);
  int rx_read(uint32_t handle, canworks_j1939_msg* msg, canworks_j1939_rx_info* info);
  void rx_close(uint32_t handle);
  int ecu_info(uint8_t network, canworks_j1939_ecu_info& out, uint16_t& error_id);
  int find_ecu(uint8_t network, uint64_t name, uint64_t mask, canworks_j1939_ecu_found& out, uint16_t& error_id);

  // ---- Bus thread of network `network` ----
  // Its queued sends and requests, oldest first, marked as taken.
  void take(unsigned network, std::vector<Job>& out);
  // The end of a taken job: error 0 = done; `answer` for a request.
  void finish(uint32_t handle, uint16_t error_id, const canworks_j1939_msg* answer = nullptr);
  // Takes newly opened receivers into use (allocating their queues) and
  // drops closed ones; true when the set of filters changed since the last
  // call, with `out` the open receivers' filters.
  bool sync_receivers(unsigned network, std::vector<Filter>& out);
  // Queues a received message for every matching receiver of the network.
  // `own`: the network's address (messages to it count as to us).
  void deliver(unsigned network, uint32_t pgn, uint8_t source, uint8_t destination, uint8_t priority,
               const uint8_t* data, size_t length, uint64_t time_us, uint8_t own);
  void set_bus_down(unsigned network, bool down);
  void receiver_status(unsigned network, std::vector<RxStatus>& out);
  // The ECU state J1939_ECU_INFO and J1939_FIND_ECU read.
  void publish_ecu(unsigned network, uint8_t state, uint8_t address, uint64_t name, const std::vector<Ecu>& ecus);

 private:
  enum class State : uint8_t { Free, Queued, Taken, Done };
  struct Slot {
    State state = State::Free;
    uint32_t seq = 0;
    uint64_t order = 0;
    uint8_t network = 0;
    Kind kind = Kind::Send;
    uint32_t pgn = 0;
    uint8_t destination = 255;
    uint8_t priority = 6;
    uint32_t timeout_ms = 0;
    uint16_t length = 0;
    uint16_t error_id = 0;
    clock::time_point started;
    clock::time_point done_at;
    canworks_j1939_msg msg;  // send: the data; request: the answer
  };
  enum class RxState : uint8_t { Free, Opening, Open };
  struct Receiver {
    RxState state = RxState::Free;
    uint32_t seq = 0;
    uint8_t network = 0;
    Filter filter;
    uint16_t depth = 0;
    bool cancelled = false;  // ended by a stop: the next read says so, then the slot is freed
    std::unique_ptr<canworks_j1939_msg[]> queue;
    uint16_t capacity = 0;
    uint16_t head = 0;
    uint16_t count = 0;
    bool overflow = false;
    uint32_t dropped = 0;
  };
  struct EcuView {
    bool valid = false;
    uint8_t state = 3;
    uint8_t address = 254;
    uint64_t name = 0;
    std::vector<Ecu> ecus;
  };

  J1939PlcMsgs();
  Slot* find(uint32_t handle);
  Receiver* find_rx(uint32_t handle);
  uint16_t check_network(uint8_t network) const;

  std::mutex mutex_;
  std::unique_ptr<Slot[]> slots_;
  Receiver receivers_[kReceiverSlots];
  EcuView ecu_[kMaxNetworks];
  uint32_t filter_gen_[kMaxNetworks] = {};
  uint32_t filter_seen_[kMaxNetworks] = {};
  uint32_t next_seq_ = 1;
  uint64_t next_order_ = 1;
  std::atomic<bool> running_{false};
  std::atomic<uint32_t> j1939_{0};
  std::atomic<uint32_t> networks_{0};
  std::atomic<uint32_t> attached_{0};
  std::atomic<uint32_t> bus_down_{0};
  std::atomic<uint32_t> unknown_version_{0};
};

}  // namespace canopen_plugin

#endif  // CANWORKS_J1939_PLC_MSGS_H
