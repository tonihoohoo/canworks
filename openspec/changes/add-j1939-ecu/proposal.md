## Why

Mobile machines, engines, gensets and agricultural and construction equipment talk SAE J1939, not CANopen. A PLC on such a machine has two jobs:
- **read** what other ECUs broadcast (engine speed, temperatures, hydraulic pressures)
- **act as an ECU itself** (claim an address, send its own messages, answer requests)

Today the toolkit can do neither. Most of what J1939 needs already exists and is protocol-neutral: adapter setup (SocketCAN, slcan), bit rate detection, raw frames, the bus trace and frame inspector, the diagnostics channel, the PLC I/O binding, the deploy tool, the configurator and several networks per PLC.

The exploration of 2026-10-08 (project notes `research/j1939-2026-10-08.md`) settled the main choices:
- slice 1 covers **both** roles
- the runtime uses the **Linux kernel J1939 stack** (`CAN_J1939` sockets, mainline since 5.4, shipped as a module in the Raspberry Pi kernels), chosen because it is production-proven
- the PC tools use **can-j1939** (MIT)
- there is no real J1939 device on the bench, so hardware tests use a second adapter running a simulated ECU

This change assumes `rename-to-opencan-plc` has landed and uses its command names.

## What Changes

- **Config**: a version 2 network gets `protocol`, `"canopen"` (default, all existing files unchanged) or `"j1939"`. A J1939 network has an `adapter` and a `j1939` object:
  - the ECU identity (NAME fields, preferred address, optional address range)
  - received messages (`rx`): PGN, source filter, timeout, signals with bit position, length, byte order and an `iec_location`
  - sent messages (`tx`): PGN, priority, destination, period or on-change, signals from `%Q`
  - periodic requests
  - PLC locations for claim state and current address

  Signal layouts come from the user's DBC. The SAE J1939 Digital Annex is licensed and is not shipped. The JSON Schema describes it all.
- **Runtime plugin** (same library, one bus thread per network as today): a J1939 network opens kernel `CAN_J1939` sockets on its interface. It:
  - claims its address and handles contention and loss
  - receives configured PGNs (multi-packet included, the kernel reassembles them) into `%I`
  - sends configured PGNs from `%Q` (more than 8 bytes goes through the kernel's transport protocol)
  - answers Request (PGN 59904) for the PGNs it sends and for its address claim
  - sends configured periodic requests
  - supervises received PGNs with timeouts and per-message status bits

  A missing `can-j1939` kernel module stops only that network, with a log line naming the module.
- **Install**: `install-stock.sh` (native and managed Docker) loads `can-j1939` on the host and makes it load at boot.
- **Diagnostics channel**: status for J1939 networks (claim state, own address, NAMEs seen on the bus, per-PGN age, timeouts and counters). The trace, raw-frame send and bit rate detection work on J1939 networks unchanged.
- **PC tools**:
  - DBC import with J1939 PGN handling (cantools)
  - deploy checks (clash check includes J1939 locations; PGN, address and NAME checks)
  - located variable declarations for J1939 signals (scale, offset and unit as comments; values reach the PLC raw)
  - J1939 DBC export of a network
- **Configurator**: protocol choice per network. A J1939 network page has an ECU identity form, "Import DBC…" with a message picker (receive/send), a signal table with suggested PLC addresses, timeouts and periods prefilled from the DBC, and an online view.
- **Bus trace**: J1939 decoding:
  - 29-bit identifier split (priority, PGN, source, destination)
  - names from the imported DBC
  - transport protocol sessions shown as one message
  - address claims with decoded NAME
  - requests

  The frame inspector shows the J1939 identifier split.
- **J1939 ECU simulator**: `opencan-j1939-sim` (can-j1939) plays an ECU from a DBC on a SocketCAN interface or a USB adapter. It claims an address, sends its messages with changing values and answers requests. It is used in CI on vcan and for the hardware tests.
- **CI**: the change classifier learns protocol areas (CANopen, J1939, shared). CANopen-only pull requests skip J1939 tests and the reverse. J1939 vcan tests join the existing vcan groups (no new job). Wall time must not exceed the median of the last 5 green `main` runs.

## Capabilities

### New Capabilities
- `j1939-config`: the `protocol` field and the `j1939` network object, with checks and schema.
- `j1939-ecu`: runtime behaviour of a J1939 network: address claim, receive, send, requests, transport, supervision, PLC status, module errors.
- `j1939-pc-tools`: DBC import, deploy checks, declarations, DBC export, configurator J1939 pages.
- `j1939-trace`: J1939 decoding in the bus trace and frame inspector.
- `j1939-simulator`: the PC-side J1939 ECU simulator.

### Modified Capabilities
- `canopen-networks`: the network list admits J1939 networks (no `master`/`nodes`).
- `canopen-ci`: the full suite is selected by protocol area.
- `canopen-stock-install`, `canopen-docker-install`: the J1939 kernel module is loaded.
- `canopen-online-diagnostics`: status of J1939 networks.

## Impact

- **Plugin**: new `plugin/src/j1939/` (config, ECU, socket wrapper). Shared adapter, trace, diag and process-image files move to `plugin/src/can/` when first touched. `config.cpp` dispatches on `protocol`. No new third-party C/C++ dependency (kernel UAPI headers only).
- **PC tools**: new `j1939/` package (dbc import, decode, sim), configurator static pages, `bustrace/decode.py` dispatch. New runtime dependencies: `can-j1939` (pulls numpy) and `cantools`. Both MIT.
- **Schema**: `schema/canopen.v2.schema.json` gains the optional `protocol` and `j1939` (additive within version 2).
- **Not supported in this change**:
  - J1939 on the in-process simulated bus (`adapter.simulate: true` is rejected on a J1939 network; use vcan)
  - the local sim runtime on Docker Desktop (until its kernel is checked for `can-j1939`)
  - J1939 and CANopen on one physical bus
  - DM1/DM2/DM3/DM11, PLC function blocks, J1939-FD and ISOBUS (a later `add-j1939-diagnostics` change)
- **Hardware**: Pi with its adapter as the PLC, a second adapter on the engineering PC running `opencan-j1939-sim` at 250 kbit/s, with the CANopen bench device off this segment.
- **Docs**: `docs/j1939.md`, README feature list, `examples/j1939/` with made-up proprietary PGNs only.
