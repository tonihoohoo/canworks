## Context

After `add-j1939-ecu` the plugin is one library with a shared CAN core (`plugin/src/can/`: adapter and link setup, bit rate sweep, bus monitor, trace capture, raw frame send, diagnostics server, process image, IEC locations) and one folder per protocol behind a registration interface. Each network runs one protocol, chosen by `protocol`.

Pieces this change builds on:
- `frame_tx` sends frames from the diagnostics thread on a CAN_RAW socket of its own, or through `SimFrameInjector` on a simulated network.
- `trace_capture` opens a second CAN_RAW socket; the simulated bus has `SimTraceTap`.
- `bus_monitor` keeps bus state, error counters and bus-off count per network.
- The SDO blocks (`canopen-plc-sdo`) show how a C++ block in the editor library finds the loaded plugin (`dlopen` of the SONAME with `RTLD_NOLOAD`) and calls a versioned C table without blocking the scan.
- J1939 packs signals as raw integers at `start_bit`/`length`/`byte_order` and imports DBC files with cantools.

Decisions from the exploration (2026-10-09): raw CAN on every network and on protocol-less networks, config messages and ST blocks together, no CAN FD.

## Goals / Non-Goals

**Goals:**
- A PLC talks to plain CAN devices with no ST code (config-mapped messages) or with full control (function blocks).
- Raw messages work next to CANopen and J1939 on the same bus, and on buses with no protocol.
- Everything works on the simulated bus, so most tests run in the cloud container.
- No CI time growth.

**Non-Goals:**
- CAN FD (no FD adapter on the bench; classic pins stay simple; FD would be separate `CANFD_*` blocks later).
- ISO-TP / UDS, frame forwarding between networks inside the plugin, DBC multiplexing, rolling counters and checksums (later changes).
- Scaling to engineering units in the runtime (values stay raw, as for CANopen and J1939).

## Decisions

### 1. Raw CAN is core, not a protocol

`plugin/src/can/raw/` belongs to the shared core and is built in every build option (CANopen only, J1939 only, both). The protocol registration gets no raw entry; the core runs the raw path for any network whose config has `raw` or whose program opens a receiver or a sender.

`protocol: "none"` is a network with an `adapter`, optional `raw` and nothing else. It still gets the core's services: bus monitor, trace, bit rate detection, diagnostics status and `send_frame`.

*Alternative:* a `raw` protocol module. Rejected: it would make raw frames on a CANopen or J1939 bus impossible, which is the main use (a display next to CANopen nodes).

### 2. One raw I/O path per network

- **Real interface**: a raw thread per network with its own CAN_RAW socket on the interface, using epoll on the socket and a 1 ms timerfd.
  - `CAN_RAW_FILTER` is rebuilt from the configured RX identifiers and the open program receivers (at most 512 filters; above that, no filter and matching in user space).
  - `CAN_RAW_RECV_OWN_MSGS` is on, so a frame we sent comes back when the driver echoes it. That echo is the transmit confirmation for `CAN_SEND` and is not delivered to receivers. Drivers without echo confirm on write; status says which.
  - `SO_TIMESTAMP` gives receive times.
  - The kernel gives every CAN_RAW and CAN_J1939 socket its own copy of each frame, so Lely's socket, the J1939 sockets and trace capture are untouched.
- **Simulated network**: the bus thread that owns the virtual bus calls the raw engine from its loop. Frames come from `SimTraceTap`, frames go out through the injector path. A `none` network with `adapter.simulate` gets a minimal core bus thread for this.
- The thread starts with the network and keeps retrying while the interface is missing or down, like the bus thread. It never runs in the PLC scan.

### 3. Exchange with the PLC

- **Config messages** go through the process image like PDOs: the raw engine writes received values into the input buffer that `cycle_start` copies, and samples outputs from the snapshot `cycle_end` publishes. One frame per message per scan is visible; the receive counter tells the program how many arrived.
- **Function blocks** use lock-free single-producer/single-consumer rings between the scan thread and the raw thread:
  - one ring per receiver (depth 1..256, default 32)
  - one shared TX ring per network (128 frames)
  - a per-job slot for cyclic senders (data and period written by the scan, read by the raw thread)

  The scan thread never waits, allocates or logs, as for the SDO blocks.

### 4. `canworks_can_api(1)`

A new exported C function in the core, separate from `canopen_plc_api`, so a J1939-only build still has it. Its table (version 1):
- `rx_open(network, id, mask, flags, depth) → handle | 0 + error`, `rx_read(handle, frame*) → 0 none / 1 frame / <0 error`, `rx_close(handle)`
- `tx_send(network, frame*, timeout_ms) → handle | 0 + error`, `tx_poll(handle) → 0 busy / 1 done / 2 error`
- `cyc_start(network, frame*, period_us) → handle`, `cyc_update(handle, frame*, period_us)`, `cyc_stop(handle) → count`
- `bus_info(network, info*)`

Handles carry a generation, so a handle from before a PLC restart is refused with "cancelled". The header lives at `plugin/src/can/can_plc_api.h`; the library carries a copy and a test checks they agree (as `test/plc_sdo` does).

### 5. Block behaviour

- `CAN_SEND` follows the PLCopen handshake of the SDO blocks: edge of `EXECUTE` queues, `BUSY` until confirmed or `TIMEOUT` (`T#0s` = 100 ms), then `DONE` or `ERROR`.
- `CAN_SEND_CYCLIC`: `ENABLE` starts a job. `ID` and `EXTENDED` are fixed while enabled; `DATA`, `DLC` and `PERIOD` are taken on every call and used from the next send. `PERIOD` must be 1 ms to 60 s.
- `CAN_RECEIVE`: `ENABLE` opens a receiver with `ID`/`MASK`/`EXTENDED` (fixed while enabled). Each call takes at most one frame; `NEW` is TRUE when it did, and the frame outputs keep the last frame otherwise. Calling the instance in a `WHILE rx.NEW DO` loop drains the queue in one scan. `OVERFLOW` latches when the queue dropped frames; `DROPPED` counts them.
- `CAN_BUS_INFO` reads the bus monitor values plus frame counters kept by the raw path (for a `none` network the bus monitor runs too).

Pins are fixed in the `can-plc-frames` spec. `DATA` is `ARRAY[0..7] OF BYTE`.

### 6. Error IDs

| ID | Meaning |
|---|---|
| 1 | not running: plugin missing, API version not offered, or the network is not running |
| 2 | no such network |
| 3 | invalid input (identifier out of range, DLC > 8, period out of range, depth out of range) |
| 4 | the identifier belongs to the network's protocol and the network does not allow program overrides |
| 5 | resources full (receivers, cyclic jobs or TX ring) |
| 6 | not confirmed on the bus within `TIMEOUT` |
| 7 | bus-off or interface down |
| 8 | cancelled (PLC stop, network restart, stale handle) |
| 9 | the network is listen-only |

### 7. Guards

- The program is trusted like the PDO mapping, so `allow_changes` (a diagnostics setting) does not apply to blocks.
- Protocol ownership: a program send whose identifier the network's protocol uses fails with error 4 unless `raw.program_override_protocol` is true. A config `tx` message on such an identifier is a config error unless it has `override_protocol: true`. Ownership:
  - CANopen: `cob_id_use()` (NMT, SYNC, TIME, LSS, EMCY, PDO, SDO, heartbeat COB-IDs of the configured nodes and the master or own slave)
  - J1939: any 29-bit identifier whose source address byte is the ECU's address or in its address range
  - none: nothing
- The diagnostics `send_frame` guard map also names raw `tx` messages ("raw message Lamps"), so an engineer cannot collide with the program by accident.

### 8. Config shape

```json
{ "schema_version": 2, "networks": [
  { "name": "cab", "protocol": "none",
    "adapter": { "type": "socketcan", "interface": "can1", "bitrate": 250000 },
    "raw": {
      "dbc": "cab.dbc",
      "program_override_protocol": false,
      "rx": [ { "name": "Joystick", "id": 291, "dlc": 8, "timeout_ms": 300,
                "status_location": "%IX300.0", "counter_location": "%IW302",
                "signals": [ { "name": "X", "start_bit": 0, "length": 12, "signed": true,
                               "scale": 0.1, "unit": "%", "iec_location": "%IW304" } ] },
              { "name": "AnyBattery", "id": 1536, "mask": 2032,
                "id_location": "%ID308", "data_location": "%IL312" } ],
      "tx": [ { "name": "Lamps", "id": 1281, "dlc": 2, "period_ms": 100,
                "on_change": true, "min_gap_ms": 10, "enable_location": "%QX300.0",
                "signals": [ { "name": "Red", "start_bit": 0, "length": 1, "iec_location": "%QX300.1" } ] },
              { "name": "Wake", "id": 1282, "extended": false, "rtr": true, "dlc": 0,
                "trigger_location": "%QX300.2" } ] } } ] }
```

- Identifiers are numbers (the configurator shows hex). `extended` defaults to false.
- `rx` matching: `(frame_id & mask) == (id & mask)`, `mask` defaulting to all ones. Overlapping entries all receive the frame.
- `rx` frames shorter than the signals need are not applied; they are counted as short frames in status.
- `tx` needs at least one of `period_ms`, `on_change`, `trigger_location`. Bits no signal covers are sent as the message's `fill` byte (default 0x00). `enable_location` FALSE stops periodic and on-change sends.
- Sending starts when the PLC runs and stops when it stops.

Writers use version 2 whenever `raw` or protocol `none` is present.

### 9. Listen-only

`adapter.listen_only: true` is only valid with protocol `none` and no `tx` entries. The plugin sets the controller to listen-only (SocketCAN ctrlmode, slcan silent mode as the bit rate sweep does). With `configure_link: false`, or on vcan and simulated buses, the plugin cannot set the mode; it logs that and only refuses its own sends (blocks get error 9, `send_frame` is refused).

### 10. Signal packing shared with J1939

`plugin/src/j1939/` signal code moves to `plugin/src/can/signals.*` with one fill rule parameter (J1939: unused bits 1; raw: the `fill` byte). The C++ and Python packers keep one shared fixture of cantools-encoded vectors, so this change replaces the J1939 packing tests instead of adding a second set.

### 11. PC side

- `canworks/raw/`: contract checks (same fixtures as C++), declarations (`<network>_<message>_<signal>` with several networks, scale/unit comments), DBC import (reuses J1939's cantools import; 11-bit and 29-bit messages without J1939 attributes become raw messages), DBC export of raw messages, trace decode, sim devices.
- `replay`: the PC client reads `.asc`, `.trc` or a canworks trace and sends the frames with their original spacing (or `--rate`), either onto a PC adapter directly (local bus) or to the plugin through a new diagnostics op `replay` that takes frames in batches of up to 500 with relative times. It has the `send_frame` guards (allow_changes, force on protocol identifiers or OPERATIONAL nodes), ends on disconnect or `replay_stop`, and is limited to one replay per network and 1000 frames per second.

### 12. CI

- Raw C++ tests run on the simulated bus in the existing plugin test job: config checks, RX/TX timing, receivers, cyclic jobs, guards, block API.
- One vcan check (kernel filter rebuild and echo confirmation) joins the vcan group with the most headroom.
- ST helpers compile in the existing library build step.
- The area classifier from `add-j1939-ecu` treats `plugin/src/can/raw/**`, `tools/deploy/canworks/raw/**` and `test/can_raw/**` as `shared`.
- The PR states wall time and summed job time against the baseline (median of the last 5 green `main` runs with code changes) and pays for any increase in the same PR.

## Risks / Trade-offs

- [A program flooding the bus with `CAN_SEND_CYCLIC` at 1 ms on many jobs] → 16 jobs per network, bus load visible in `CAN_BUS_INFO` and status; no rate limit beyond that, because the program owns the bus like it owns PDOs.
- [Adapters that do not echo sent frames give weaker `DONE`] → status names the confirmation mode; docs say what `DONE` means then.
- [Raw RX on a CANopen bus adds a second socket's copy of every frame] → kernel filters keep it to configured identifiers; measured on the Pi in the hardware task.
- [The J1939 change might land with a different core layout than planned] → this change is rebased and its paths adjusted at apply time; the specs name behaviour, not paths.

## Migration Plan

Additive except `--sdo-blocks` → `--blocks` (clean cut, the project is not in use). Existing configs are unchanged. The bench needs a redeploy of the PC tools and plugin for the hardware tasks only.

## Open Questions

None open; defaults chosen: receiver depth 32, TX ring 128, 32 receivers and 16 cyclic jobs per network, `CAN_SEND` timeout 100 ms.
