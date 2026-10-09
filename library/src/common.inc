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

// The plugin's C interface, version 1 (plugin/src/canopen_plc_api.h).
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
