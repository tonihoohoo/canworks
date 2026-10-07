## Why

The bus trace is read-only by design, and the master sends only what the config tells it to. On the first bench session with an unknown device two things are missing that every commissioning tool has:

- **Sending a frame by hand.** Poke a device with a single raw frame (an SDO request to an unconfigured node, an NMT command, a vendor's test frame), send a frame cyclically to keep a device awake or check a filter, and watch the answer in the trace. Today this needs `cansend` in a shell on the PLC, which is not there in the managed Docker install and bypasses every guard.
- **Finding an unknown bus's bit rate.** A device out of its box, or a machine nobody documented, runs at one of the CiA 301 bit rates and says nothing about which. Today the user changes `adapter.bitrate`, uploads, and checks whether nodes boot, once per rate.

Both are small on the plugin side: it already owns the CAN interface, its link settings and a second raw socket for the trace.

## What Changes

- **Send raw frames** (diagnostics channel op `send_frame`, `send_frame_stop`): one frame, or a cyclic job (period 10-60000 ms, optional count) that ends on `send_frame_stop`, on disconnect, after its count or after 10 minutes. Standard or extended identifier, data or remote frame. Guarded:
  - needs `allow_changes`;
  - refused without `force` when the identifier is one the configured network uses (its COB-ID map: NMT, SYNC, TIME, EMCY, PDOs, SDO channels and heartbeats of configured nodes, LSS) or while any node of the network (or the plugin's own slave) is OPERATIONAL;
  - rate-limited (single frames at most 50 per second per client, at most 8 cyclic jobs per network);
  - every send logged with the client's address; sent frames show in a trace as Tx.
- **Detect the bit rate** (ops `detect_bitrate`, `detect_bitrate_status`): the plugin pauses CANopen on that network, sets the interface listen-only and listens at each CiA 301 rate (1000, 800, 500, 250, 125, 50, 20, 10 kbit/s, or a chosen subset) for a set time, counting valid frames, error frames and distinct identifiers, then restores the configured rate and resumes CANopen (nodes boot again as after an adapter loss). The result names the rate where frames arrived without errors, says when the bus was silent or the result is ambiguous, and whether it differs from `adapter.bitrate`. Never transmits: listen-only, no acknowledge, no error frames. Needs `allow_changes`; refused without `force` while a node is OPERATIONAL; refused on vcan, simulated networks and links the plugin does not configure (`configure_link: false`).
- **`openplc-canopen-diag`**: `send ID [DATA]` (`--ext`, `--rtr --dlc N`, `--period-ms`, `--count`, `--duration`, `--force`), `send-stop`, `detect-bitrate` (`--rates`, `--per-rate-ms`, `--rounds`, `--force`).
- **Configurator**: a **Send** panel in the Trace view (single or cyclic, list of running jobs with Stop, "send again" from a selected trace row, a confirmation naming why `force` is needed), and **Detect bit rate** on the Scan the bus page with per-rate progress and a "Use N kbit/s" button that sets the network's bit rate on the page (unsaved).
- **PC-direct too**: the four ops are defined on the diagnostics protocol, so the same CLI commands and configurator panels work against the runtime now and against the USB-adapter backend of `add-local-bus-commissioning` once it lands. That change leaves hooks for exactly this (one adapter-open function with a listen-only flag, one transmit path, one op table); this change fills them: `send_frame`/`detect_bitrate` in its op table and listen-only per adapter type. If this change is applied first, those tasks wait for it.

## Capabilities

### New Capabilities
None.

### Modified Capabilities
- `canopen-online-diagnostics`: raw frame transmit and bit rate detection ops, their guards and the CLI commands.
- `canopen-configurator`: Send panel in the Trace view, Detect bit rate on the Scan page.

## Impact

- Plugin: `diag.cpp` (ops, guards, rate limit), new `frame_tx.{h,cpp}` (raw send socket and cyclic jobs in the diagnostics thread; on a simulated network the virtual bus), `bus.cpp` (pause a session for a bit-rate sweep between sessions), `can_adapter.{h,cpp}` (`LinkOps::set_listen_only`, sweep helper), a COB-ID map of the running network for the guard.
- PC tools: `openplc-canopen-diag` commands; configurator endpoints and UI in the Trace and Scan pages; once `add-local-bus-commissioning` is in, its `localbus` op table and `adapter.open(..., listen_only)`.
- No config, schema or PLC-side change; no change for users who leave `allow_changes` off. Protocol stays version 1: an older plugin answers `unknown op`, which the tools report as "the runtime's plugin is too old for this".
- Tests: unit tests for the guard, rate limit, sweep decision and link sequence (mocked `LinkOps`); vcan CI test for send/cyclic/stop and the vcan refusal of detection; configurator page tests.
- Docs: `docs/diagnostics.md`, `docs/trace.md`, `docs/configurator.md`, README (PC tools and Online features). Deploy tool minor version bump.
