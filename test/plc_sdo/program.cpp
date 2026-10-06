// program.cpp - a stand-in PLC program for lookup_check: the library's SDO
// blocks with the editor's glue (bridge.py) and nothing else, built as a
// shared object the way the runtime loads a compiled program, so the blocks
// must find the plugin with dlopen(RTLD_NOLOAD) as they do on a device.

#include "c_blocks.h"

// One CO_SDO_READ instance, called once per scan: 0 busy, 1 done, 2 error
// (with *error_id), -1 idle.
extern "C" __attribute__((visibility("default"))) int sdo_program_scan(int execute, unsigned node,
                                                                       unsigned* error_id) {
  static CO_SDO_READ_INST rd;
  rd.NODE = static_cast<uint8_t>(node);
  rd.INDEX = 0x1018;
  rd.SUBINDEX = 1;
  rd.TIMEOUT = 300000000LL;  // T#300ms
  rd.EXECUTE = execute != 0;
  co_sdo_read_call(&rd);
  *error_id = rd.ERROR_ID.get();
  if (rd.ERROR) return 2;
  if (rd.DONE) return 1;
  return rd.BUSY ? 0 : -1;
}
