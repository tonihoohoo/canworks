/* canopen_plc_api.h - the C interface the PLC program's CANopen function
 * blocks (library/canworks) use to run SDO transfers and read emergency
 * messages through the loaded plugin. See the spec canopen-plc-sdo.
 *
 * The blocks find the plugin the runtime has loaded with
 * dlopen("libcanworks_plugin.so", RTLD_NOW | RTLD_NOLOAD) (the plugin's SONAME)
 * and call canopen_plc_api(version), which returns the function table for
 * that version or NULL. Version 2 begins with the fields of version 1; the
 * SDO blocks ask for version 1 (so they run on an older plugin too),
 * CO_RECV_EMCY for version 2. Every function is called on the PLC scan
 * thread: they never wait on CAN traffic, allocate or log.
 *
 * The library carries a copy of these declarations (library/src/common.inc);
 * test/plc_sdo/layout_check.cpp checks that the two agree. Change the layout
 * only together with a new version number. */

#ifndef CANOPEN_PLC_API_H
#define CANOPEN_PLC_API_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* The newest version this header describes. */
#define CANOPEN_PLC_API_VERSION 2u

/* Kinds of data, as the block families name them. */
enum {
  CANOPEN_PLC_INT = 0,    /* CO_SDO_READ / CO_SDO_WRITE: up to 8 bytes, little-endian */
  CANOPEN_PLC_REAL = 1,   /* _REAL: a write carries an 8-byte double */
  CANOPEN_PLC_STRING = 2, /* _STRING */
  CANOPEN_PLC_BYTES = 3   /* _BYTES */
};

/* ERROR_ID values (0 = no error). */
enum {
  CANOPEN_PLC_ERR_ABORT = 1,       /* abort_code holds the CiA 301 code */
  CANOPEN_PLC_ERR_TIMEOUT = 2,     /* abort_code 0x05040000 */
  CANOPEN_PLC_ERR_UNAVAILABLE = 3, /* the node is lost, not booted or STOPPED */
  CANOPEN_PLC_ERR_NOT_RUNNING = 4, /* no CANopen, or no matching API version */
  CANOPEN_PLC_ERR_BUSY = 5,        /* too many transfers in progress */
  CANOPEN_PLC_ERR_INPUT = 6,       /* an input is invalid */
  CANOPEN_PLC_ERR_TOO_BIG = 7,     /* the reply does not fit the block's output */
  CANOPEN_PLC_ERR_CANCELLED = 8    /* PLC stopped, CANopen restarted, or result expired */
};

/* Largest write and largest reply a transfer carries. */
#define CANOPEN_PLC_MAX_DATA 1024u
/* Transfers in progress or waiting at a time. */
#define CANOPEN_PLC_SLOTS 64u

typedef struct {
  uint8_t network;   /* 0.. : the config's networks in order (0 for a version 1 config) */
  uint8_t node;      /* 1..127 */
  uint16_t index;
  uint8_t subindex;
  uint8_t write;     /* 0 read, 1 write */
  uint8_t kind;      /* CANOPEN_PLC_INT... */
  uint8_t size;      /* INT/REAL writes: bytes to send, 0 = from the node's EDS */
  uint32_t timeout_ms;   /* 0 = 1000 */
  const uint8_t* data;   /* write payload: 8 bytes for INT (LWORD) and REAL (double) */
  uint32_t length;       /* bytes in data */
} canopen_plc_request;

typedef struct {
  uint16_t error_id;
  uint32_t abort_code;
  uint32_t size;  /* bytes the device sent (a read); may exceed what was copied */
} canopen_plc_result;

typedef struct {
  uint32_t size; /* sizeof(canopen_plc_api_v1) */
  /* Starts a transfer and returns its handle (> 0), or 0 with *error_id set. */
  uint32_t (*start)(const canopen_plc_request* req, uint16_t* error_id);
  /* 0 while the transfer runs; 1 done, 2 error, with *res filled and the
   * reply (reads) copied into data up to cap bytes. The handle is invalid
   * after a 1 or 2. */
  int (*poll)(uint32_t handle, canopen_plc_result* res, uint8_t* data, uint32_t cap);
} canopen_plc_api_v1;

/* Emergency messages kept per CANopen master network (CO_RECV_EMCY). */
#define CANOPEN_PLC_EMCY_QUEUE 64u

/* One emergency message of a configured node. */
typedef struct {
  uint64_t time_us;      /* receive time, UTC microseconds since 1970 */
  uint32_t seq;          /* sequence number in the network's queue */
  uint16_t error_code;
  uint8_t node;
  uint8_t error_register;
  uint8_t msef[5];       /* manufacturer-specific bytes */
  uint8_t reserved[3];
} canopen_plc_emcy;

/* A reader's position, kept by the block instance. */
typedef struct {
  uint32_t session;  /* the CANopen session it reads from */
  uint32_t next;     /* the next sequence number it wants */
} canopen_plc_emcy_cursor;

typedef struct {
  uint16_t queued;   /* matching messages still waiting for this reader */
  uint16_t reserved;
  uint32_t lost;     /* messages overwritten before this reader got to them, in this call */
} canopen_plc_emcy_info;

typedef struct {
  uint32_t size; /* sizeof(canopen_plc_api_v2) */
  uint32_t (*start)(const canopen_plc_request* req, uint16_t* error_id);
  int (*poll)(uint32_t handle, canopen_plc_result* res, uint8_t* data, uint32_t cap);
  /* Places *cursor at the oldest message still kept, or with skip_old at the
   * next one to arrive. 0, or -ERROR_ID (CANOPEN_PLC_ERR_NOT_RUNNING,
   * CANOPEN_PLC_ERR_INPUT for a network that is not a CANopen master network
   * or a node above 127). node 0: every node. */
  int (*emcy_begin)(uint8_t network, uint8_t node, uint8_t skip_old, canopen_plc_emcy_cursor* cursor);
  /* Copies the oldest message at or after *cursor that matches node into
   * *entry and moves the cursor past it: 1; none: 0; -ERROR_ID on an error
   * (CANOPEN_PLC_ERR_CANCELLED once when the CANopen session restarted: the
   * cursor then stands at the new session's oldest message). *info is filled
   * on 0 and 1. */
  int (*emcy_read)(uint8_t network, uint8_t node, canopen_plc_emcy_cursor* cursor, canopen_plc_emcy* entry,
                   canopen_plc_emcy_info* info);
} canopen_plc_api_v2;

/* The table for `version`, or NULL when this plugin does not offer it. */
const void* canopen_plc_api(uint32_t version);

#ifdef __cplusplus
}
#endif

#endif /* CANOPEN_PLC_API_H */
