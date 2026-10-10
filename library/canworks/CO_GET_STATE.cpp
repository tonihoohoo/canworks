FUNCTION_BLOCK CO_GET_STATE
VAR_INPUT
  EXECUTE : BOOL;
  NETWORK : USINT;
  NODE : USINT;
END_VAR
VAR_OUTPUT
  BUSY : BOOL;
  DONE : BOOL;
  ERROR : BOOL;
  ERROR_ID : UINT;
  STATE : USINT;
  MASTER_STATE : USINT;
  HELD : USINT;
  BOOT_ERROR : USINT;
  CONFIGURED : BOOL;
  STARTED : BOOL;
END_VAR
VAR
  co_handle : UDINT;
  co_prev : BOOL;
  co_phase : USINT;
END_VAR
// Shared code of the canworks SDO function blocks (spec
// canopen-plc-sdo). library/generate.py copies it into every block's source,
// because the editor grafts each library C++ block into one
// c_blocks_code.cpp and offers no other place for shared code; the include
// guard keeps one copy per program.
//
// The editor binds every pin and local of a block to a #define of its name, so
// nothing here uses a pin or local name (the pins are upper case, the shared
// code is lower case), nor the keyword that closes a variable section. No system header is included after
// those defines: dlopen and dlsym are declared here as glibc does.
#ifndef CO_SDO_COMMON_INCLUDED
#define CO_SDO_COMMON_INCLUDED
extern "C" void* dlopen(const char* file, int mode) noexcept(true);
extern "C" void* dlsym(void* handle, const char* name) noexcept(true);

namespace co_sdo {

// The plugin's C interface, version 1 (plugin/src/canopen/canopen_plc_api.h).
const unsigned api_version = 1;
const unsigned max_data = 1024;
struct request {
  unsigned char network;
  unsigned char node;
  unsigned short index;
  unsigned char subindex;
  unsigned char write;
  unsigned char kind;
  unsigned char size;
  unsigned int timeout_ms;
  const unsigned char* data;
  unsigned int length;
};
struct result {
  unsigned short error_id;
  unsigned int abort_code;
  unsigned int size;
};
struct api_v1 {
  unsigned int size;
  unsigned int (*start)(const request* req, unsigned short* error_id);
  int (*poll)(unsigned int handle, result* res, unsigned char* data, unsigned int cap);
};
enum { kind_int = 0, kind_real = 1, kind_string = 2, kind_bytes = 3 };
enum { err_not_running = 4, err_input = 6, err_too_big = 7 };

// The loaded plugin's table, looked up by its SONAME without loading it
// again (RTLD_NOW | RTLD_NOLOAD). Looked up again on each start until found;
// kept once found, since the runtime unloads plugins only when it exits.
// (The plugin's own tests link the blocks into one process with the master
// and name the entry point with -DCO_SDO_TEST_ENTRY.)
#ifdef CO_SDO_TEST_ENTRY
}  // namespace co_sdo
extern "C" const void* CO_SDO_TEST_ENTRY(unsigned int version);
namespace co_sdo {
#endif
inline const api_v1* api() {
  static const api_v1* table = nullptr;
  if (table) return table;
  typedef const void* (*entry_t)(unsigned int);
#ifdef CO_SDO_TEST_ENTRY
  entry_t entry = CO_SDO_TEST_ENTRY;
#else
  void* lib = dlopen("libcanworks_plugin.so", 0x2 | 0x4);
  if (!lib) return nullptr;
  entry_t entry = reinterpret_cast<entry_t>(dlsym(lib, "canopen_plc_api"));
#endif
  if (!entry) return nullptr;
  const api_v1* t = static_cast<const api_v1*>(entry(api_version));
  if (t && t->size >= sizeof(api_v1)) table = t;
  return table;
}

// TIME (nanoseconds) to the timeout in ms; 0 and negative mean the default.
inline unsigned int timeout_ms(long long ns) {
  if (ns <= 0) return 0;
  long long ms = (ns + 999999) / 1000000;
  return ms > 3600000 ? 3600000u : static_cast<unsigned int>(ms);
}

// One block instance's handshake (PLCopen style). The block keeps `handle`
// and `phase` in its locals and maps the outcome to its pins.
enum { phase_idle = 0, phase_busy = 1, phase_ended = 2 };
struct step {
  bool start;   // a rising edge: clear the outputs and start a transfer
  bool clear;   // the result was shown and EXECUTE is FALSE: clear DONE/ERROR
};
inline step begin(bool execute, bool& prev, unsigned char& phase) {
  step s{false, false};
  bool rising = execute && !prev;
  prev = execute;
  if (phase == phase_ended && !execute) {
    s.clear = true;
    phase = phase_idle;
  }
  if (rising && phase != phase_busy) s.start = true;
  return s;
}

// Starts `req`; returns the handle or 0 with `error` set.
inline unsigned int start(request& req, unsigned short& error) {
  const api_v1* t = api();
  if (!t) {
    error = err_not_running;
    return 0;
  }
  error = 0;
  return t->start(&req, &error);
}

// 0 busy, 1 done, 2 error (`res` filled).
inline int poll(unsigned int handle, result& res, unsigned char* data, unsigned int cap) {
  const api_v1* t = api();
  if (!t) {
    res = result{err_not_running, 0, 0};
    return 2;
  }
  return t->poll(handle, &res, data, cap);
}

inline void put_le(unsigned char* out, unsigned long long v, unsigned n) {
  for (unsigned b = 0; b < n; ++b) out[b] = static_cast<unsigned char>(v >> (8 * b));
}

inline unsigned long long get_le(const unsigned char* in, unsigned n) {
  unsigned long long v = 0;
  for (unsigned b = 0; b < n; ++b) v |= static_cast<unsigned long long>(in[b]) << (8 * b);
  return v;
}

}  // namespace co_sdo
#endif
// Shared code of the canworks NMT function blocks (spec canopen-plc-nmt):
// CO_NMT, CO_NETWORK_START, CO_NETWORK_STOP and CO_GET_STATE.
// library/generate.py copies it into each of them after src/common.inc,
// whose include guard keeps one copy of dlopen, dlsym and the handshake
// (co_sdo::begin) per program. The same pin-name rules apply: nothing here
// uses a pin or local name, nor the keyword that closes a variable section,
// and no system header is included.
#ifndef CO_NMT_COMMON_INCLUDED
#define CO_NMT_COMMON_INCLUDED

namespace co_nmt {

// The plugin's NMT interface, version 1 (plugin/src/canopen/canopen_plc_nmt_api.h).
const unsigned api_version = 1;
struct request {
  unsigned char network;
  unsigned char node;
  unsigned char op;
  unsigned char command;
  unsigned int timeout_ms;
};
struct node_state {
  unsigned char state;
  unsigned char master_state;
  unsigned char held;
  unsigned char boot_error;
  unsigned char configured;
  unsigned char started;
};
struct api_v1 {
  unsigned int size;
  unsigned int (*start)(const request* req, unsigned short* error_id);
  int (*poll)(unsigned int handle, unsigned short* error_id);
  unsigned short (*get_state)(unsigned char network, unsigned char node, node_state* out);
};
enum { op_node = 1, op_start = 2, op_stop = 3 };
enum { err_not_running = 4 };

// The loaded plugin's NMT table, found as the SDO blocks find theirs
// (co_sdo::api), through its own entry point canopen_plc_nmt_api. A plugin
// without it (older than these blocks) leaves the table empty: the NMT
// blocks end with ERROR_ID 4 and look again on their next start, while the
// SDO blocks keep working. (The plugin's own tests name the entry point with
// -DCO_NMT_TEST_ENTRY.)
#ifdef CO_NMT_TEST_ENTRY
}  // namespace co_nmt
extern "C" const void* CO_NMT_TEST_ENTRY(unsigned int version);
namespace co_nmt {
#endif
inline const api_v1* api() {
  static const api_v1* table = nullptr;
  if (table) return table;
  typedef const void* (*entry_t)(unsigned int);
#ifdef CO_NMT_TEST_ENTRY
  entry_t entry = CO_NMT_TEST_ENTRY;
#else
  void* lib = dlopen("libcanworks_plugin.so", 0x2 | 0x4);
  if (!lib) return nullptr;
  entry_t entry = reinterpret_cast<entry_t>(dlsym(lib, "canopen_plc_nmt_api"));
#endif
  if (!entry) return nullptr;
  const api_v1* t = static_cast<const api_v1*>(entry(api_version));
  if (t && t->size >= sizeof(api_v1)) table = t;
  return table;
}

// Starts `req`; returns the handle or 0 with `error` set.
inline unsigned int start(const request& req, unsigned short& error) {
  const api_v1* t = api();
  if (!t) {
    error = err_not_running;
    return 0;
  }
  error = 0;
  return t->start(&req, &error);
}

// 0 busy, 1 done, 2 error (`error` set).
inline int poll(unsigned int handle, unsigned short& error) {
  const api_v1* t = api();
  if (!t) {
    error = err_not_running;
    return 2;
  }
  error = 0;
  return t->poll(handle, &error);
}

// The snapshot's values for `node` (0: the master's only); returns an
// ERROR_ID, 0 when `out` is filled.
inline unsigned short get_state(unsigned char network, unsigned char node, node_state& out) {
  out = node_state{};
  const api_v1* t = api();
  if (!t) return err_not_running;
  return t->get_state(network, node, &out);
}

}  // namespace co_nmt
#endif
// CO_GET_STATE: the NMT state the master last saw for NODE and the master's own, in the call that starts it
// Generated by library/generate.py; edit that file or src/nmt_common.inc.

void setup() {
}

void loop() {
  bool prev = co_prev;
  unsigned char phase = co_phase;
  co_sdo::step s = co_sdo::begin(EXECUTE, prev, phase);
  co_prev = prev;
  co_phase = phase;
  if (s.clear) {
    DONE = false;
    ERROR = false;
  }
  if (s.start) {
    co_nmt::node_state st = {};
    unsigned short err = co_nmt::get_state(NETWORK, NODE, st);
    STATE = st.state;
    MASTER_STATE = st.master_state;
    HELD = st.held;
    BOOT_ERROR = st.boot_error;
    CONFIGURED = st.configured != 0;
    STARTED = st.started != 0;
    BUSY = false;
    DONE = err == 0;
    ERROR = err != 0;
    ERROR_ID = err;
    co_phase = co_sdo::phase_ended;
  }
}
END_FUNCTION_BLOCK
