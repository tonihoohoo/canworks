## Why

Many devices on machine buses speak neither CANopen nor J1939: joysticks, displays, sensors, battery packs and drives with their own frame layouts, usually described by a DBC file or a data sheet. Today a canworks PLC cannot talk to them:
- the PLC program cannot send or receive an arbitrary CAN frame
- the config cannot map a plain CAN message to `%I`/`%Q`
- every network must run CANopen (or, with `add-j1939-ecu`, J1939)

Raw frames exist only as a service tool (`send_frame` on the diagnostics channel), gated by `allow_changes` and meant for an engineer, not for the program.

The exploration of 2026-10-09 (project notes `research/raw-can-2026-10-09.md`) settled the scope with Toni:
- raw CAN works on **every** network (next to CANopen or J1939 on the same bus) and on networks with **no protocol** at all
- config-mapped messages and the ST function blocks come in **one** change
- **no CAN FD**

Raw CAN is not a third protocol module. It is part of the shared CAN core that `add-j1939-ecu` creates, so every build of the plugin has it.

## What Changes

- **Config** (schema version 2):
  - `protocol` gains `"none"`: a plain CAN network with an `adapter` and raw messages only.
  - Every network (CANopen, J1939 or none) MAY have a `raw` object:
    - received messages (`rx`): identifier (11 or 29 bit, optional mask), expected DLC, timeout, signals (start bit, length, byte order, signed) to `%I`, the whole frame to `%IL`, DLC, receive counter, received identifier and a status bit
    - sent messages (`tx`): identifier, DLC, period, on change with a minimum gap, on a trigger bit, an enable bit, signals and the whole frame from `%Q`, remote frames
    - `dbc`: the DBC file the messages came from (for tools)
  - `adapter.listen_only`: the PLC watches a bus without acknowledging or sending (networks with protocol `none` only).
  - A sent message whose identifier the network's protocol uses (a CANopen COB-ID, a J1939 frame from the PLC's own address) is a config error unless the message says `override_protocol`.
- **Runtime plugin** (shared core, `plugin/src/can/raw/`): one raw I/O path per network that has raw messages or open program receivers. On a real interface it uses its own CAN_RAW socket with kernel filters and transmit confirmation; on a simulated network it uses the simulated bus. Received values reach the PLC and sent values leave it through the process image snapshots, like PDOs. Signal packing is shared with J1939 (`plugin/src/can/signals.*`).
- **PLC function blocks** in the existing `canworks` editor library, through a new C entry point `canworks_can_api(1)`:
  - `CAN_SEND`: one frame, `DONE` when it is confirmed on the bus
  - `CAN_SEND_CYCLIC`: a frame sent by the plugin at a fixed period, independent of the scan
  - `CAN_RECEIVE`: a receiver with identifier and mask and a queue, read one frame per call
  - `CAN_BUS_INFO`: bus state, error counters, bus load and frame counts
  - ST functions for bit and byte packing (`CAN_GET_BITS`, `CAN_SET_BITS`, 16- and 32-bit integer helpers in either byte order) and J1939 identifier helpers
- **Diagnostics channel**: status of raw messages, program receivers and cyclic jobs; raw `tx` identifiers join the `send_frame` guard map; a `replay` operation and `canworks-diag replay FILE` play a recorded trace onto a network or a PC adapter.
- **PC tools**:
  - DBC import into raw messages (cantools, shared with J1939), DBC export of raw messages
  - located variable declarations for raw signals
  - clash and protocol-ownership checks
  - `canworks-deploy --new-project --blocks` (replaces `--sdo-blocks`, breaking)
- **Configurator**: "Plain CAN" on Add network, listen-only setting, a CAN messages page on every network (receive/send tables, signal rows, bit layout, suggested PLC addresses, Import DBC), raw messages in the online view, "Copy as ST call" for a message.
- **Bus trace**: frames matching a raw message are shown with its name and signal values, in the trace rows and the frame inspector.
- **Simulator**: a simulation file section for plain CAN devices (periodic frames with value sources, replies to received frames), on the simulated bus and the standalone simulator.
- **CI**: raw tests run on the simulated bus inside existing jobs plus one vcan check in an existing vcan group; no new job; wall time and summed job time stay within the baseline.

## Capabilities

### New Capabilities
- `can-raw-messages`: the `raw` config object, plain CAN networks, listen-only, and the runtime behaviour of config-mapped messages.
- `can-plc-frames`: the `CAN_*` function blocks and ST helpers, and the `canworks_can_api` interface.

### Modified Capabilities
- `canopen-networks`: the network list admits networks with protocol `none`.
- `canopen-config-contract`: `raw` in the version 2 schema; configs with raw messages are version 2.
- `canopen-plc-sdo`: the library carries the `CAN_*` blocks too.
- `canopen-editor-project`: `--blocks` replaces `--sdo-blocks`; declarations for raw signals.
- `canopen-configurator`: plain CAN networks, CAN messages page, DBC import, online view, Copy as ST call.
- `canopen-bus-trace`: raw message decoding.
- `canopen-device-simulator`: plain CAN devices in the simulation file.
- `canopen-online-diagnostics`: raw status, guard map, replay.
- `canopen-dbc-export`: raw messages in the exported DBC.

## Impact

- **Order**: applies after `add-j1939-ecu` has merged (it creates `plugin/src/can/`, the protocol field, the protocol registration, the DBC import and the CI area classifier). This change rebases onto it at apply time.
- **Plugin**: new `plugin/src/can/raw/` and `plugin/src/can/can_plc_api.h`; signal packing moves from `plugin/src/j1939/` to `plugin/src/can/signals.*`; `cob_id_use()` learns raw messages. No new third-party dependency.
- **Library**: `library/generate.py` writes the `CAN_*` C++ blocks; ST helpers are plain ST POUs in the library project.
- **PC tools**: `canworks/raw/` (contract checks, DBC import/export, declarations, trace decode, sim devices); minor version bump.
- **Breaking** (allowed, the project is not in use): `--sdo-blocks` becomes `--blocks`.
- **Not in this change**: CAN FD, ISO-TP, frame forwarding between networks in the plugin, DBC multiplexed signals, rolling counters and checksums.
- **Hardware**: the bench Pi adapter as the PLC with a plain CAN network next to the CANopen node, and the PC adapter playing a plain CAN device.
- **Docs**: `docs/raw-can.md`, README feature list and layout, `docs/configurator.md`, `examples/raw-can/` (simulated joystick and lamp panel, made-up identifiers).
