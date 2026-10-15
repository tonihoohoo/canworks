FUNCTION_BLOCK J1939_REQUEST
VAR_INPUT
  EXECUTE : BOOL;
  NETWORK : USINT;
  PGN : UDINT;
  DESTINATION : USINT;
  TIMEOUT : TIME;
END_VAR
VAR_IN_OUT
  DATA : ARRAY[0..1784] OF BYTE;
END_VAR
VAR_OUTPUT
  BUSY : BOOL;
  DONE : BOOL;
  ERROR : BOOL;
  ERROR_ID : UINT;
  SOURCE : USINT;
  LENGTH : UINT;
  ACK_CODE : USINT;
END_VAR
VAR
  jd_handle : UDINT;
  jd_prev : BOOL;
  jd_phase : USINT;
END_VAR
// Shared code of the canworks J1939 blocks: the trouble code blocks (spec
// j1939-plc-diagnostics, interface version 1) and the message blocks (spec
// j1939-plc-blocks, version 2). library/generate.py copies it into every
// J1939_* C++ block's source for the same reason as common.inc: the editor
// grafts each C++ block into one c_blocks_code.cpp. The same rules apply:
// nothing here uses a pin or local name (pins are upper case, this code lower
// case), and no system header is included after the pin defines.
#ifndef J1939_DM_COMMON_INCLUDED
#define J1939_DM_COMMON_INCLUDED
extern "C" void* dlopen(const char* file, int mode) noexcept(true);
extern "C" void* dlsym(void* handle, const char* name) noexcept(true);

namespace j1939_dm {

// The plugin's C interface, version 1 (plugin/src/j1939/j1939_plc_api.h).
const unsigned api_version = 1;
const unsigned max_codes = 32;
struct dm {
  unsigned char lamps;
  unsigned char flash;
  unsigned short count;
  unsigned int age_ms;
  unsigned int dtcs[max_codes];
};
struct api_v1 {
  unsigned int size;
  unsigned int (*dm_read_start)(unsigned char network, unsigned char source, unsigned char previous,
                                unsigned int timeout_ms, unsigned short* error_id);
  int (*dm_read_poll)(unsigned int handle, dm* out, unsigned short* error_id);
  unsigned int (*dm_clear_start)(unsigned char network, unsigned char destination, unsigned char previous_only,
                                 unsigned int timeout_ms, unsigned short* error_id);
  int (*dm_clear_poll)(unsigned int handle, unsigned short* error_id);
  void (*cancel)(unsigned int handle);
};
enum { err_not_running = 1, err_input = 3, err_bus = 7, err_cancelled = 8 };

// Version 2: the message blocks. The table starts with version 1's.
const unsigned api_version_msgs = 2;
const unsigned max_length = 1785;
const unsigned rx_any = 0x01;
const unsigned rx_all_destinations = 0x02;
struct msg {
  unsigned int pgn;
  unsigned char source;
  unsigned char destination;
  unsigned char priority;
  unsigned char ack_code;
  unsigned short length;
  unsigned long long time_us;
  unsigned char data[max_length];
};
struct rx_info {
  unsigned short queued;
  unsigned char overflow;
  unsigned char bus_down;
  unsigned int dropped;
};
struct ecu_info {
  unsigned char state;
  unsigned char address;
  unsigned short ecu_count;
  unsigned long long name;
};
struct ecu_found {
  unsigned char found;
  unsigned char address;
  unsigned short count;
  unsigned long long name;
};
struct api_v2 {
  unsigned int size;
  unsigned int (*dm_read_start)(unsigned char network, unsigned char source, unsigned char previous,
                                unsigned int timeout_ms, unsigned short* error_id);
  int (*dm_read_poll)(unsigned int handle, dm* out, unsigned short* error_id);
  unsigned int (*dm_clear_start)(unsigned char network, unsigned char destination, unsigned char previous_only,
                                 unsigned int timeout_ms, unsigned short* error_id);
  int (*dm_clear_poll)(unsigned int handle, unsigned short* error_id);
  void (*cancel)(unsigned int handle);
  unsigned int (*send_start)(unsigned char network, unsigned int pgn, unsigned char destination,
                             unsigned char priority, const unsigned char* data, unsigned short length,
                             unsigned int timeout_ms, unsigned short* error_id);
  int (*send_poll)(unsigned int handle, unsigned short* error_id);
  unsigned int (*request_start)(unsigned char network, unsigned int pgn, unsigned char destination,
                                unsigned int timeout_ms, unsigned short* error_id);
  int (*request_poll)(unsigned int handle, msg* out, unsigned short* error_id);
  void (*msg_cancel)(unsigned int handle);
  unsigned int (*rx_open)(unsigned char network, unsigned int pgn, unsigned char source, unsigned char flags,
                          unsigned short depth, unsigned short* error_id);
  int (*rx_read)(unsigned int handle, msg* m, rx_info* info);
  void (*rx_close)(unsigned int handle);
  int (*ecu_info)(unsigned char network, ecu_info* out, unsigned short* error_id);
  int (*find_ecu)(unsigned char network, unsigned long long name, unsigned long long mask, ecu_found* out,
                  unsigned short* error_id);
};

// The loaded plugin's table, as co_sdo::api() finds it. (The plugin's tests
// link the blocks into one process with the plugin code and name the entry
// point with -DJ1939_DM_TEST_ENTRY.)
#ifdef J1939_DM_TEST_ENTRY
}  // namespace j1939_dm
extern "C" const void* J1939_DM_TEST_ENTRY(unsigned int version);
namespace j1939_dm {
#endif
inline const api_v1* api() {
  static const api_v1* table = nullptr;
  if (table) return table;
  typedef const void* (*entry_t)(unsigned int);
#ifdef J1939_DM_TEST_ENTRY
  entry_t entry = J1939_DM_TEST_ENTRY;
#else
  void* lib = dlopen("libcanworks_plugin.so", 0x2 | 0x4);
  if (!lib) return nullptr;
  entry_t entry = reinterpret_cast<entry_t>(dlsym(lib, "canworks_j1939_api"));
#endif
  if (!entry) return nullptr;
  const api_v1* t = static_cast<const api_v1*>(entry(api_version));
  if (t && t->size >= sizeof(api_v1)) table = t;
  return table;
}

// The version 2 table, the same way; nullptr from a plugin that lacks it.
inline const api_v2* api2() {
  static const api_v2* table = nullptr;
  if (table) return table;
  typedef const void* (*entry_t)(unsigned int);
#ifdef J1939_DM_TEST_ENTRY
  entry_t entry = J1939_DM_TEST_ENTRY;
#else
  void* lib = dlopen("libcanworks_plugin.so", 0x2 | 0x4);
  if (!lib) return nullptr;
  entry_t entry = reinterpret_cast<entry_t>(dlsym(lib, "canworks_j1939_api"));
#endif
  if (!entry) return nullptr;
  const api_v2* t = static_cast<const api_v2*>(entry(api_version_msgs));
  if (t && t->size >= sizeof(api_v2)) table = t;
  return table;
}

// Errors a receiver or a lookup recovers from by itself (tried again while
// ENABLE stays TRUE).
inline bool retry(unsigned short error_id) {
  return error_id == err_not_running || error_id == err_bus || error_id == err_cancelled || error_id == 9;
}

// TIME (nanoseconds) to milliseconds; 0 and negative give 0 (the plugin's
// default, 1 s).
inline unsigned int time_ms(long long ns) {
  if (ns <= 0) return 0;
  long long ms = (ns + 999999) / 1000000;
  return ms > 3600000 ? 3600000u : static_cast<unsigned int>(ms);
}

// PLCopen handshake of one block instance, as co_sdo::begin.
enum { phase_idle = 0, phase_busy = 1, phase_ended = 2 };
struct step {
  bool start;
  bool clear;
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

}  // namespace j1939_dm
#endif
// J1939_REQUEST: sends a Request for a PGN; DONE with one ECU's answer (global: once sent), ERROR_ID 12 on its NACK
// Generated by library/generate.py; edit that file or src/j1939_common.inc.

void setup() {
}

void loop() {
  bool prev = jd_prev;
  unsigned char phase = jd_phase;
  j1939_dm::step s = j1939_dm::begin(EXECUTE, prev, phase);
  jd_prev = prev;
  jd_phase = phase;
  if (s.clear) {
    DONE = false;
    ERROR = false;
  }
  const j1939_dm::api_v2* t = j1939_dm::api2();
  if (s.start) {
    DONE = false;
    ERROR = false;
    ERROR_ID = 0;
    ACK_CODE = 0;
    unsigned short err = 0;
    unsigned int handle = 0;
    if (!t) {
      err = j1939_dm::err_not_running;
    } else {
      handle = t->request_start(NETWORK, PGN, DESTINATION, j1939_dm::time_ms(TIMEOUT), &err);
    }
    if (handle) {
      jd_handle = handle;
      BUSY = true;
      jd_phase = j1939_dm::phase_busy;
    } else {
      BUSY = false;
      ERROR = true;
      ERROR_ID = err;
      jd_phase = j1939_dm::phase_ended;
    }
  }
  if (jd_phase == j1939_dm::phase_busy) {
    j1939_dm::msg m;
    m.length = 0;
    m.ack_code = 0;
    unsigned short err = j1939_dm::err_not_running;
    int st = t ? t->request_poll(jd_handle, &m, &err) : 2;
    if (st != 0) {
      BUSY = false;
      jd_handle = 0;
      jd_phase = j1939_dm::phase_ended;
      ACK_CODE = m.ack_code;
      if (st == 1) {
        SOURCE = m.source;
        LENGTH = m.length;
        for (unsigned i = 0; i < m.length && i < j1939_dm::max_length; ++i) DATA[i] = m.data[i];
        DONE = true;
      } else {
        ERROR = true;
        ERROR_ID = err;
      }
    }
  }
}
END_FUNCTION_BLOCK
