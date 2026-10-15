/* j1939_plc_api.h - the C interface the PLC program's J1939 blocks in
 * library/canworks use through the loaded plugin: version 1 for the trouble
 * code blocks (J1939_DM_READ, J1939_DM_CLEAR: read DM1/DM2, send DM3/DM11;
 * spec j1939-plc-diagnostics), version 2 adds the message blocks
 * (J1939_SEND, J1939_RECEIVE, J1939_REQUEST, J1939_ECU_INFO,
 * J1939_FIND_ECU; spec j1939-plc-blocks). The plugin offers both versions.
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

#define CANWORKS_J1939_API_VERSION 2u

/* ERROR_ID values (0 = no error); spec j1939-plc-diagnostics "Error IDs of
 * the trouble code blocks". */
enum {
  CANWORKS_J1939_ERR_NOT_RUNNING = 1, /* no plugin, no API version, or network not running */
  CANWORKS_J1939_ERR_NETWORK = 2,     /* no such network */
  CANWORKS_J1939_ERR_INPUT = 3,       /* an input out of range (source above 253, destination 254, ...) */
  CANWORKS_J1939_ERR_PROTOCOL = 4,    /* the network sends that PGN itself */
  CANWORKS_J1939_ERR_PENDING = 5,     /* another DM2 read or clear for that address is pending */
  CANWORKS_J1939_ERR_TIMEOUT = 6,     /* no answer within the timeout */
  CANWORKS_J1939_ERR_BUS = 7,         /* bus-off or interface down */
  CANWORKS_J1939_ERR_CANCELLED = 8,   /* PLC stop, network restart or stale handle */
  CANWORKS_J1939_ERR_FULL = 9,        /* no free message job or receiver */
  CANWORKS_J1939_ERR_NOT_J1939 = 10,  /* the network is not a J1939 network */
  CANWORKS_J1939_ERR_NO_ADDRESS = 11, /* the network holds no address (claiming, cannot claim) */
  CANWORKS_J1939_ERR_NACK = 12,       /* the destination answered NACK */
  CANWORKS_J1939_ERR_NO_DM1 = 13,     /* no DM1 received from that source */
  CANWORKS_J1939_ERR_ABORTED = 14     /* the transport protocol session was aborted */
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

/* ---- Version 2: the message blocks ---- */

/* Bytes of the longest message (the kernel's transport protocol). */
#define CANWORKS_J1939_MAX_LENGTH 1785u
/* Sends and requests in progress or waiting, all networks together. */
#define CANWORKS_J1939_MSG_SLOTS 32u
/* Program receivers per network, and messages each queues. */
#define CANWORKS_J1939_RECEIVERS 16u
#define CANWORKS_J1939_DEPTH_DEFAULT 4u
#define CANWORKS_J1939_DEPTH_MAX 32u
/* Receiver flags. */
#define CANWORKS_J1939_RX_ANY 0x01u              /* every PGN */
#define CANWORKS_J1939_RX_ALL_DESTINATIONS 0x02u /* also messages between other ECUs */

typedef struct {
  uint32_t pgn;     /* PDU1: the destination byte is 0 */
  uint8_t source;
  uint8_t destination;
  uint8_t priority;
  uint8_t ack_code; /* requests: 1 NACK, 2 access denied, 3 cannot respond (error 12) */
  uint16_t length;
  uint64_t time_us; /* received messages: UTC microseconds */
  uint8_t data[CANWORKS_J1939_MAX_LENGTH];
} canworks_j1939_msg;

typedef struct {
  uint16_t queued;  /* messages still waiting after this read */
  uint8_t overflow; /* messages were dropped since the receiver opened */
  uint8_t bus_down; /* the network has no bus (the receiver stays open) */
  uint32_t dropped;
} canworks_j1939_rx_info;

typedef struct {
  uint8_t state;    /* 0 claiming, 1 claimed, 2 cannot claim, 3 no bus */
  uint8_t address;  /* 254 while none is held */
  uint16_t ecu_count;
  uint64_t name;
} canworks_j1939_ecu_info;

typedef struct {
  uint8_t found;
  uint8_t address;
  uint16_t count;
  uint64_t name;
} canworks_j1939_ecu_found;

typedef struct {
  /* Version 1, unchanged. */
  uint32_t size; /* sizeof(canworks_j1939_api_v2) */
  uint32_t (*dm_read_start)(uint8_t network, uint8_t source, uint8_t previous, uint32_t timeout_ms,
                            uint16_t* error_id);
  int (*dm_read_poll)(uint32_t handle, canworks_j1939_dm* out, uint16_t* error_id);
  uint32_t (*dm_clear_start)(uint8_t network, uint8_t destination, uint8_t previous_only, uint32_t timeout_ms,
                             uint16_t* error_id);
  int (*dm_clear_poll)(uint32_t handle, uint16_t* error_id);
  void (*cancel)(uint32_t handle);
  /* Queues a message from the network's address (destination 255 global;
   * ignored for a PDU2 PGN); its handle (> 0), or 0 with *error_id set.
   * timeout_ms 0 = 1000 up to 8 bytes, 10000 above. */
  uint32_t (*send_start)(uint8_t network, uint32_t pgn, uint8_t destination, uint8_t priority, const uint8_t* data,
                         uint16_t length, uint32_t timeout_ms, uint16_t* error_id);
  /* 0 while waiting; 1 sent, 2 error (*error_id). The handle is invalid after
   * a 1 or 2. */
  int (*send_poll)(uint32_t handle, uint16_t* error_id);
  /* Sends a Request for `pgn` to `destination` (255 global); its handle, or 0
   * with *error_id set. timeout_ms 0 = 1000. */
  uint32_t (*request_start)(uint8_t network, uint32_t pgn, uint8_t destination, uint32_t timeout_ms,
                            uint16_t* error_id);
  /* 0 while waiting; 1 answered (*out filled; global: sent, length 0), 2
   * error (*error_id; 12 with out->ack_code). */
  int (*request_poll)(uint32_t handle, canworks_j1939_msg* out, uint16_t* error_id);
  /* Forgets a send or a request. */
  void (*msg_cancel)(uint32_t handle);
  /* Opens a receiver for `pgn` (any with CANWORKS_J1939_RX_ANY) from
   * `source` (255 any); its handle, or 0 with *error_id set. depth 0 =
   * CANWORKS_J1939_DEPTH_DEFAULT. */
  uint32_t (*rx_open)(uint8_t network, uint32_t pgn, uint8_t source, uint8_t flags, uint16_t depth,
                      uint16_t* error_id);
  /* 1 with the oldest message taken into *msg, 0 when none waits, -error_id
   * when the receiver is gone (cancelled). *info is filled either way. */
  int (*rx_read)(uint32_t handle, canworks_j1939_msg* msg, canworks_j1939_rx_info* info);
  void (*rx_close)(uint32_t handle);
  /* 0 with *out filled, or 2 with *error_id. */
  int (*ecu_info)(uint8_t network, canworks_j1939_ecu_info* out, uint16_t* error_id);
  /* 0 with *out filled (found 0 when no ECU matches), or 2 with *error_id.
   * An ECU matches when (its NAME AND mask) = (name AND mask). */
  int (*find_ecu)(uint8_t network, uint64_t name, uint64_t mask, canworks_j1939_ecu_found* out,
                  uint16_t* error_id);
} canworks_j1939_api_v2;

/* The table for `version`, or NULL when this plugin does not offer it. */
const void* canworks_j1939_api(uint32_t version);
/* The same inside the plugin's code (the plugin exports it as the above). */
const void* canworks_j1939_api_table(uint32_t version);

#ifdef __cplusplus
}
#endif

#endif /* CANWORKS_J1939_PLC_API_H */
