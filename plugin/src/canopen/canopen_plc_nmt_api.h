/* canopen_plc_nmt_api.h - the C interface the PLC program's NMT function
 * blocks (library/canworks: CO_NMT, CO_NETWORK_START, CO_NETWORK_STOP,
 * CO_GET_STATE) use to command nodes and the master through the loaded
 * plugin. See the spec canopen-plc-nmt.
 *
 * The blocks find the plugin as the SDO blocks do (canopen_plc_api.h), with
 * dlopen("libcanworks_plugin.so", RTLD_NOW | RTLD_NOLOAD), and call
 * canopen_plc_nmt_api(CANOPEN_PLC_NMT_API_VERSION), which returns the
 * function table for that version or NULL. This entry point and its version
 * are separate from the SDO table's, which they leave unchanged. Every
 * function is called on the PLC scan thread: none waits on CAN traffic,
 * allocates or logs, and get_state takes no lock.
 *
 * The library carries a copy of these declarations (library/src/nmt_common.inc);
 * the simulation tests (sim_plc_nmt_blocks) run the real blocks against this
 * table. Change the layout only together with a new version number. */

#ifndef CANOPEN_PLC_NMT_API_H
#define CANOPEN_PLC_NMT_API_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define CANOPEN_PLC_NMT_API_VERSION 1u

/* Requests in progress or waiting at a time (separate from the SDO slots). */
#define CANOPEN_PLC_NMT_SLOTS 16u

/* Request kinds (canopen_plc_nmt_request.op). */
enum {
  CANOPEN_PLC_NMT_NODE = 1,  /* CO_NMT: command a node, or every node with node 0 */
  CANOPEN_PLC_NMT_START = 2, /* CO_NETWORK_START: the master goes OPERATIONAL */
  CANOPEN_PLC_NMT_STOP = 3   /* CO_NETWORK_STOP: the master goes PRE-OPERATIONAL */
};

/* CiA 301 command specifiers (op 1), the codes of nmt_command_location. */
enum {
  CANOPEN_PLC_NMT_CS_START = 1,
  CANOPEN_PLC_NMT_CS_STOP = 2,
  CANOPEN_PLC_NMT_CS_PREOP = 128,
  CANOPEN_PLC_NMT_CS_RESET_NODE = 129,
  CANOPEN_PLC_NMT_CS_RESET_COMM = 130
};

/* op 3: what the nodes get (0: master.on_plc_stop's choice, 2 STOP, 128
 * ENTER PRE-OPERATIONAL, 255 nothing). */
#define CANOPEN_PLC_NMT_NODES_DEFAULT 0u
#define CANOPEN_PLC_NMT_NODES_NONE 255u

/* ERROR_ID values: the SDO family's numbers (canopen_plc_api.h), plus 9.
 * 2 a CO_NETWORK_START timeout; 4 not running; 5 slots full; 6 bad input;
 * 8 cancelled by a PLC stop or a CANopen restart. */
enum { CANOPEN_PLC_ERR_REFUSED = 9 }; /* a state the program does not own */

typedef struct {
  uint8_t network;     /* as canopen_plc_request */
  uint8_t node;        /* op 1: 0 every node, 1..127 */
  uint8_t op;          /* CANOPEN_PLC_NMT_NODE... */
  uint8_t command;     /* op 1: a CiA 301 command specifier; op 3: 0, 2, 128 or 255 */
  uint32_t timeout_ms; /* op 2: 0 = no limit */
} canopen_plc_nmt_request;

/* What the master last saw (CO_GET_STATE). */
typedef struct {
  uint8_t state;        /* the node state byte's codes: 5, 127, 4, 0 no contact */
  uint8_t master_state; /* the master state byte's codes */
  uint8_t held;         /* 0, or 2 / 128: the hold the master keeps applying */
  uint8_t boot_error;   /* the boot error byte's code */
  uint8_t configured;   /* 1: the configuration lists the node */
  uint8_t started;      /* 1: the master may run (start, or CO_NETWORK_START, and no stop since) */
} canopen_plc_nmt_state;

typedef struct {
  uint32_t size; /* sizeof(canopen_plc_nmt_api_v1) */
  /* Starts a request and returns its handle (> 0), or 0 with *error_id set. */
  uint32_t (*start)(const canopen_plc_nmt_request* req, uint16_t* error_id);
  /* 0 while the request runs; 1 done, 2 error with *error_id set. The handle
   * is invalid after a 1 or 2. */
  int (*poll)(uint32_t handle, uint16_t* error_id);
  /* Fills *out for `node` (0: the master's fields only); returns an ERROR_ID
   * (0 = filled). */
  uint16_t (*get_state)(uint8_t network, uint8_t node, canopen_plc_nmt_state* out);
} canopen_plc_nmt_api_v1;

/* The table for `version`, or NULL when this plugin does not offer it. */
const void* canopen_plc_nmt_api(uint32_t version);

#ifdef __cplusplus
}
#endif

#endif /* CANOPEN_PLC_NMT_API_H */
