// program.cpp - a stand-in PLC program for lookup_check: the library's SDO
// blocks with the editor's glue (bridge.py) and nothing else, built as a
// shared object the way the runtime loads a compiled program, so the blocks
// must find the plugin with dlopen(RTLD_NOLOAD) as they do on a device.

#include "c_blocks.h"

// One CO_SDO_READ instance, called once per scan: 0 busy, 1 done, 2 error
// (with *error_id), -1 idle.
extern "C" __attribute__((visibility("default"))) int sdo_program_scan(int execute, unsigned node,
                                                                       unsigned timeout_ms, unsigned* error_id) {
  static CO_SDO_READ_INST rd;
  rd.NODE = static_cast<uint8_t>(node);
  rd.INDEX = 0x1018;
  rd.SUBINDEX = 1;
  rd.TIMEOUT = static_cast<long long>(timeout_ms) * 1000000LL;
  rd.EXECUTE = execute != 0;
  co_sdo_read_call(&rd);
  *error_id = rd.ERROR_ID.get();
  if (rd.ERROR) return 2;
  if (rd.DONE) return 1;
  return rd.BUSY ? 0 : -1;
}

// One CO_GET_STATE instance for node `node`, called once per scan: 1 done
// (the master's state in *master_state), 2 error (with *error_id), -1 idle.
// It reaches the plugin through its own entry point, canopen_plc_nmt_api.
extern "C" __attribute__((visibility("default"))) int nmt_program_scan(int execute, unsigned node,
                                                                       unsigned* master_state, unsigned* error_id) {
  static CO_GET_STATE_INST gs;
  gs.NODE = static_cast<uint8_t>(node);
  gs.EXECUTE = execute != 0;
  co_get_state_call(&gs);
  *error_id = gs.ERROR_ID.get();
  *master_state = gs.MASTER_STATE.get();
  if (gs.ERROR) return 2;
  if (gs.DONE) return 1;
  return -1;
}
