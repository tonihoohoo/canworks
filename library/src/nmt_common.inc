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
