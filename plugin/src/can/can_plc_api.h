/* can_plc_api.h - the C interface the PLC program's CAN frame function blocks
 * (CAN_SEND, CAN_SEND_CYCLIC, CAN_RECEIVE, CAN_BUS_INFO in library/canworks)
 * use to send and receive raw frames through the loaded plugin. See the spec
 * can-plc-frames.
 *
 * The blocks find the plugin the runtime has loaded with
 * dlopen("libcanworks_plugin.so", RTLD_NOW | RTLD_NOLOAD) and call
 * canworks_can_api(CANWORKS_CAN_API_VERSION), which returns the function
 * table for that version or NULL. Every function is called on the PLC scan
 * thread: none waits on CAN traffic, allocates or logs.
 *
 * The library carries a copy of these declarations
 * (library/src/can_common.inc); test/can_raw checks that the two agree.
 * Change the layout only together with a new version number. */

#ifndef CANWORKS_CAN_PLC_API_H
#define CANWORKS_CAN_PLC_API_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define CANWORKS_CAN_API_VERSION 1u

/* Frame flags. */
#define CANWORKS_CAN_EXTENDED 0x01u
#define CANWORKS_CAN_RTR 0x02u

/* ERROR_ID values (0 = no error); spec can-plc-frames "Error IDs of the frame
 * blocks". */
enum {
  CANWORKS_CAN_ERR_NOT_RUNNING = 1, /* no plugin, no API version, or network not running */
  CANWORKS_CAN_ERR_NETWORK = 2,     /* no such network */
  CANWORKS_CAN_ERR_INPUT = 3,       /* identifier, DLC, period or depth out of range */
  CANWORKS_CAN_ERR_PROTOCOL = 4,    /* identifier used by the network's protocol */
  CANWORKS_CAN_ERR_FULL = 5,        /* no free receiver, cyclic job or queue space */
  CANWORKS_CAN_ERR_TIMEOUT = 6,     /* not confirmed on the bus in time */
  CANWORKS_CAN_ERR_BUS = 7,         /* bus-off or interface down */
  CANWORKS_CAN_ERR_CANCELLED = 8,   /* PLC stop, network restart or stale handle */
  CANWORKS_CAN_ERR_LISTEN_ONLY = 9  /* the network is listen-only */
};

/* Limits per network. */
#define CANWORKS_CAN_RECEIVERS 32u
#define CANWORKS_CAN_CYCLIC_JOBS 16u
#define CANWORKS_CAN_TX_QUEUE 128u
#define CANWORKS_CAN_DEPTH_DEFAULT 32u
#define CANWORKS_CAN_DEPTH_MAX 256u

typedef struct {
  uint32_t id;      /* identifier without flags */
  uint8_t flags;    /* CANWORKS_CAN_EXTENDED | CANWORKS_CAN_RTR */
  uint8_t dlc;      /* 0..8 */
  uint8_t data[8];
  uint64_t time_us; /* received frames: UTC microseconds (kernel receive time) */
} canworks_can_frame;

typedef struct {
  uint16_t queued;  /* frames still waiting after this read */
  uint8_t overflow; /* frames were dropped since the receiver opened */
  uint8_t bus_down; /* the bus is off or the interface down (receiver stays open) */
  uint32_t dropped;
} canworks_can_rx_info;

typedef struct {
  uint8_t state;       /* 0 active, 1 warning, 2 passive, 3 bus-off, 4 down or missing */
  uint16_t tx_errors;
  uint16_t rx_errors;
  uint32_t bus_off_count;
  uint8_t bus_load;    /* percent over the last second */
  uint32_t rx_count;
  uint32_t tx_count;
  uint32_t error_frames;
} canworks_can_bus_info;

typedef struct {
  uint32_t size; /* sizeof(canworks_can_api_v1) */
  /* Opens a receiver; its handle (> 0), or 0 with *error_id set. depth 0 =
   * CANWORKS_CAN_DEPTH_DEFAULT. */
  uint32_t (*rx_open)(uint8_t network, uint32_t id, uint32_t mask, uint8_t flags, uint16_t depth,
                      uint16_t* error_id);
  /* 1 with the oldest frame taken into *frame, 0 when none waits, -error_id
   * when the receiver is gone (cancelled). *info is filled either way. */
  int (*rx_read)(uint32_t handle, canworks_can_frame* frame, canworks_can_rx_info* info);
  void (*rx_close)(uint32_t handle);
  /* Queues one frame; its handle, or 0 with *error_id set. timeout_ms 0 = 100. */
  uint32_t (*tx_send)(uint8_t network, const canworks_can_frame* frame, uint32_t timeout_ms, uint16_t* error_id);
  /* 0 while waiting for confirmation; 1 confirmed, 2 error (*error_id). The
   * handle is invalid after a 1 or 2. */
  int (*tx_poll)(uint32_t handle, uint16_t* error_id);
  /* Starts a cyclic job; its handle, or 0 with *error_id set. */
  uint32_t (*cyc_start)(uint8_t network, const canworks_can_frame* frame, uint32_t period_us, uint16_t* error_id);
  /* New data, DLC and period from the next send; *count = frames sent. 0 ok
   * (*error_id 7 while the bus is off or down: the job stays), 2 error
   * (*error_id; the job has ended). */
  int (*cyc_update)(uint32_t handle, const canworks_can_frame* frame, uint32_t period_us, uint32_t* count,
                    uint16_t* error_id);
  void (*cyc_stop)(uint32_t handle);
  /* 0 with *info filled, or 2 with *error_id. */
  int (*bus_info)(uint8_t network, canworks_can_bus_info* info, uint16_t* error_id);
} canworks_can_api_v1;

/* The table for `version`, or NULL when this plugin does not offer it. */
const void* canworks_can_api(uint32_t version);
/* The same inside the plugin's code (the plugin exports it as the above). */
const void* canworks_can_api_table(uint32_t version);

#ifdef __cplusplus
}
#endif

#endif /* CANWORKS_CAN_PLC_API_H */
