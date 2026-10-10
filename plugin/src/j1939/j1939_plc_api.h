/* j1939_plc_api.h - the C interface the PLC program's J1939 trouble code
 * blocks (J1939_DM_READ, J1939_DM_CLEAR in library/canworks) use to read
 * DM1/DM2 and send DM3/DM11 through the loaded plugin. See the spec
 * j1939-plc-diagnostics.
 *
 * The blocks find the plugin the runtime has loaded with
 * dlopen("libcanworks_plugin.so", RTLD_NOW | RTLD_NOLOAD) and call
 * canworks_j1939_api(CANWORKS_J1939_API_VERSION), which returns the function
 * table for that version or NULL (also when the plugin is built without
 * J1939). Every function is called on a PLC task thread, possibly from
 * several tasks at once (a handle stays with the block instance that got
 * it): none waits on CAN traffic, allocates or logs.
 *
 * The library carries a copy of these declarations
 * (library/src/j1939_common.inc); test/j1939_unit checks that the two agree.
 * Change the layout only together with a new version number. */

#ifndef CANWORKS_J1939_PLC_API_H
#define CANWORKS_J1939_PLC_API_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define CANWORKS_J1939_API_VERSION 1u

/* ERROR_ID values (0 = no error); spec j1939-plc-diagnostics "Error IDs of
 * the trouble code blocks". */
enum {
  CANWORKS_J1939_ERR_NOT_RUNNING = 1, /* no plugin, no API version, or network not running */
  CANWORKS_J1939_ERR_NETWORK = 2,     /* no such network */
  CANWORKS_J1939_ERR_INPUT = 3,       /* source above 253, destination 254 */
  CANWORKS_J1939_ERR_PENDING = 5,     /* another DM2 read or clear for that address is pending */
  CANWORKS_J1939_ERR_TIMEOUT = 6,     /* no answer within the timeout */
  CANWORKS_J1939_ERR_BUS = 7,         /* bus-off or interface down */
  CANWORKS_J1939_ERR_CANCELLED = 8,   /* PLC stop, network restart or stale handle */
  CANWORKS_J1939_ERR_NOT_J1939 = 10,  /* the network is not a J1939 network */
  CANWORKS_J1939_ERR_NO_ADDRESS = 11, /* the network holds no address (claiming, cannot claim) */
  CANWORKS_J1939_ERR_NACK = 12,       /* the destination answered NACK */
  CANWORKS_J1939_ERR_NO_DM1 = 13      /* no DM1 received from that source */
};

/* Codes a read returns; COUNT may be higher. */
#define CANWORKS_J1939_DM_CODES 32u
/* Jobs (reads and clears) in progress or waiting, all networks together. */
#define CANWORKS_J1939_SLOTS 64u

typedef struct {
  uint8_t lamps;    /* byte 1 of the message */
  uint8_t flash;    /* byte 2 */
  uint16_t count;   /* codes in the message */
  uint32_t age_ms;  /* DM1: milliseconds since it arrived; DM2: 0 */
  uint32_t dtcs[CANWORKS_J1939_DM_CODES]; /* SPN + FMI*2^19 + OC*2^24 + CM*2^31; unused 0 */
} canworks_j1939_dm;

typedef struct {
  uint32_t size; /* sizeof(canworks_j1939_api_v1) */
  /* Starts a read of `source`'s latest DM1 (previous 0) or a Request for
   * DM2 (previous 1); its handle (> 0), or 0 with *error_id set.
   * timeout_ms 0 = 1000. */
  uint32_t (*dm_read_start)(uint8_t network, uint8_t source, uint8_t previous, uint32_t timeout_ms,
                            uint16_t* error_id);
  /* 0 while waiting; 1 done with *out filled, 2 error (*error_id). The
   * handle is invalid after a 1 or 2. */
  int (*dm_read_poll)(uint32_t handle, canworks_j1939_dm* out, uint16_t* error_id);
  /* Starts a Request for DM3 (previous_only 1) or DM11 (0) to `destination`
   * (255 global); its handle, or 0 with *error_id set. */
  uint32_t (*dm_clear_start)(uint8_t network, uint8_t destination, uint8_t previous_only, uint32_t timeout_ms,
                             uint16_t* error_id);
  /* 0 while waiting; 1 acknowledged (global: sent), 2 error (*error_id). */
  int (*dm_clear_poll)(uint32_t handle, uint16_t* error_id);
  /* Forgets a job; its handle answers CANWORKS_J1939_ERR_CANCELLED. */
  void (*cancel)(uint32_t handle);
} canworks_j1939_api_v1;

/* The table for `version`, or NULL when this plugin does not offer it. */
const void* canworks_j1939_api(uint32_t version);
/* The same inside the plugin's code (the plugin exports it as the above). */
const void* canworks_j1939_api_table(uint32_t version);

#ifdef __cplusplus
}
#endif

#endif /* CANWORKS_J1939_PLC_API_H */
