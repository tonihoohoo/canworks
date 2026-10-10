// outputs_gate.h - whether the host lets the networks send outputs.
//
// The OpenPLC plugin closes it while the scan watchdog of a CANopen master
// (master.scan_watchdog_ms) sees the PLC scan hung; otherwise outputs stop
// there because the whole network stops with the PLC. The Modbus bridge closes it for "outputs
// off" (watchdog or idle command, modbus-bridge spec): the CANopen master
// stops SYNC and its RPDOs, J1939 stops its transmit messages and the raw
// path its transmit messages, while inputs, supervision, the diagnostics
// channel and J1939 address claim keep running.

#ifndef CANWORKS_OUTPUTS_GATE_H
#define CANWORKS_OUTPUTS_GATE_H

#include <atomic>

namespace canopen_plugin {

inline std::atomic<bool>& outputs_gate() {
  static std::atomic<bool> open{true};
  return open;
}

// CANopen master networks whose scan watchdog (master.scan_watchdog_ms)
// sees the PLC scan hung; any closes the gate too, for every network.
inline std::atomic<int>& scan_hung_count() {
  static std::atomic<int> n{0};
  return n;
}

inline bool outputs_enabled() {
  return outputs_gate().load(std::memory_order_acquire) && scan_hung_count().load(std::memory_order_acquire) == 0;
}
inline void set_outputs_enabled(bool on) { outputs_gate().store(on, std::memory_order_release); }
// A network's scan watchdog trips (true) or clears again (false); calls pair up.
inline void set_scan_hung(bool hung) { scan_hung_count().fetch_add(hung ? 1 : -1, std::memory_order_acq_rel); }

}  // namespace canopen_plugin

#endif  // CANWORKS_OUTPUTS_GATE_H
