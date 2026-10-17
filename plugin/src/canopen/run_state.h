// run_state.h - what a CANopen master network keeps for the whole PLC run,
// across its bus sessions (canopen-plc-nmt "Program NMT state lasts across
// bus restarts").
//
// Bus starts a new session (a new Network) after an interface loss or a
// session error. The runtime keeps one RunState per master network for the
// PLC run and every session's Network works on it, so a new session goes on
// from what the program and the operators asked for instead of starting the
// network and every node again. A PLC stop ends it (the next run starts
// from a new one).

#ifndef CANOPEN_RUN_STATE_H
#define CANOPEN_RUN_STATE_H

#include <chrono>
#include <cstdint>
#include <map>
#include <vector>

#include "outputs_gate.h"

namespace canopen_plugin {

// NMT state the program (nmt_command_location, CO_NMT, CO_NETWORK_STOP),
// an operator (manual NMT command on the diagnostics channel or the Modbus
// control block) or the gateway holds a node in. One hold per node: the
// command that acted last decides (canopen-plc-nmt "One hold per node").
enum class Hold : uint8_t { None, Stopped, Preop };
enum class HoldSource : uint8_t { Byte, Block, Operator, Gateway, Network };

struct RunState {
  bool prog_start = false;    // CO_NETWORK_START ran in this PLC run
  bool prog_stopped = false;  // CO_NETWORK_STOP ran since
  // The hold CO_NETWORK_STOP's node command gives (None: the nodes keep
  // their state), for a node reset or released by the gateway meanwhile.
  Hold prog_stop_hold = Hold::None;
  // A lost mandatory node with stop_all_nodes stopped the master and every
  // node: it stays so until the PLC restarts.
  bool master_stopped = false;
  struct Node {
    // The program's NMT command byte: the level last acted on and the reset
    // requests handled (ProcessImage counts them for the run).
    uint8_t nmt_level = 0;
    uint64_t nmt_resets = 0;
    Hold hold = Hold::None;
    // Who set the hold: the command byte, CO_NMT, a diagnostics client (or
    // the Modbus control block), the gateway's on_upper_loss "stop_nodes", or
    // CO_NETWORK_STOP's node command (released by CO_NETWORK_START).
    HoldSource hold_src = HoldSource::Byte;
  };
  std::map<unsigned, Node> nodes;  // node ID ->
  // Per SDO variable (ProcessImage::sdo_vars()): trigger edges handled.
  std::vector<uint64_t> trig_seen;
  // Scan watchdog: the scan count last seen and when it last moved.
  uint64_t scan_seen = 0;
  std::chrono::steady_clock::time_point scan_moved{};
  // The watchdog tripped (it holds the outputs gate, outputs_gate.h, until
  // the scan moves again or the run ends, whatever the bus sessions do).
  bool scan_hung = false;
  // A gateway's field network: the upper master was OK once in this run, so
  // a session that starts while it is not has lost it.
  bool upper_seen = false;

  // The PLC run ends: a tripped scan watchdog no longer holds the gate.
  void end_run() {
    if (scan_hung) set_scan_hung(false);
    scan_hung = false;
  }
};

}  // namespace canopen_plugin

#endif  // CANOPEN_RUN_STATE_H
