// outputs_gate.h - whether the host lets the networks send outputs.
//
// The OpenPLC plugin never closes the gate: outputs stop there because the
// whole network stops with the PLC. The Modbus bridge closes it for "outputs
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

inline bool outputs_enabled() { return outputs_gate().load(std::memory_order_acquire); }
inline void set_outputs_enabled(bool on) { outputs_gate().store(on, std::memory_order_release); }

}  // namespace canopen_plugin

#endif  // CANWORKS_OUTPUTS_GATE_H
