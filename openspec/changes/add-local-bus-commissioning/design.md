## Context

The PC tools (`openplc-canopen-config`, `openplc-canopen-diag`) reach the CAN bus only through the plugin's diagnostics channel (canopen-online-diagnostics). `diag.Client` speaks line-delimited JSON over TCP. Everything else is built on its methods (`status`, `emcy`, `sdo_read`, `sdo_write`, `nmt`, `scan`, `lss_*`, `trace_*`): the configurator's online view, scan page, object dictionary browser and watch, device parameters (`parameters.py`, which runs backup, compare, restore and store on the PC over single SDOs), and the trace recorder (`bustrace/recorder.py`, which consumes 24-byte frame records).

So the backend can be swapped below `diag.Client` without touching those consumers. The PC tools install with uv on Windows, macOS and Linux without a system Python (canopen-pc-install). Any new dependency must be a pure Python wheel, or have wheels for all four runners.

The owner's bench adapter is a CANable 2.0 with stock slcan firmware. The plugin drives slcan directly on Linux (canopen-slcan-adapter).

## Goals / Non-Goals

**Goals:**
- With only a USB CAN adapter and the PC tools, a user can scan a bus, read and write objects, send NMT, find devices and set node IDs and bit rates with LSS, back up, compare, restore and store parameters, browse the object dictionary, and record a trace. This works on Windows, macOS and Linux.
- One implementation of each feature: the configurator and CLI keep a single code path, and only the transport differs.
- Safe on a bus where a PLC master already runs: nothing is sent unasked, and changes are opt-in per session.

**Non-Goals:**
- Being an NMT master: booting and configuring nodes, PDO exchange, SYNC, heartbeat production, node guarding. That is the plugin's job.
- Simulated devices on the local adapter (`sim_*`), slave-network status, gateway status.
- Raw frame transmit and bit rate detection: owned by the parallel change for raw frames and bit rate. This change only leaves the hook (Decision 8).
- CAN FD and SDO block transfer.

## Decisions

### 1. A local backend behind the `diag.Client` interface
`localbus.LocalBus` has the same public methods as `diag.Client` (`connect`, `close`, `request(op, **fields)`, `networks`, `several`, `where`, and the convenience methods) and returns the same result dicts. `request` dispatches through an op table, and an op the table lacks answers `{"ok": false, "error": "not available on a local adapter"}`. The configurator's `Connection` pool and `diag.run` pick `LocalBus` or `Client` from the target, and nothing above them changes.

The `hello` answer is synthesized: `protocol` 1, `version` (the tools' version), `allow_changes` (the session switch), `local: true`, `adapter` and `bitrate`, and one network named after `--network` (or empty) with `role: "local"` and `master_node_id: null`.

*Alternative:* a small local TCP server that speaks the protocol, so even `diag.Client` stays unchanged. Rejected: it adds a port and a token for no gain, and the in-process backend is easier to test.

### 2. Own small CANopen client on python-can, not the `canopen` package
python-can (pure Python) gives the adapter layer for all three operating systems: `slcan` over pyserial, `socketcan` on Linux, and pass-through to `gs_usb`, `pcan`, `kvaser`, `ixxat`, `vector`. On top of it, `localbus` implements the client subset the operations need:
- **SDO client**: expedited and segmented upload and download on the default channel (0x600+n / 0x580+n), with toggle check, abort codes, timeout and abort on timeout. That covers the 4096-byte limit of the protocol.
- **NMT**: commands to one node, never broadcast.
- **LSS master** (CiA 305): switch state global and selective, fastscan with optional vendor and product, configure node ID and bit timing, store (only when asked), inquire.
- **Listener**: heartbeat, boot-up and EMCY frames, NMT, SYNC and other masters' SDO requests (for Decision 4), and the trace ring.

The results must match the plugin's channel field for field (scan rows, LSS `note`s, abort texts), and those come from our own code on both sides. The subset is a few hundred lines, and keeping python-can the only CANopen-related dependency keeps the uv install small.

*Alternative:* depend on the `canopen` package (MIT, pure Python, has SDO, NMT and LSS). Not chosen as the default because its node and object-dictionary model and its own threading would be wrapped to reproduce our result shapes. If its LSS fastscan and SDO behave well in the CI parity test (Decision 9), switching later is a local change inside `localbus`.

### 3. Adapters and opening
`--adapter TYPE:CHANNEL` maps to `can.Bus(interface=TYPE, channel=CHANNEL, bitrate=...)`. Extra `--adapter-option KEY=VALUE` options are passed through (for example `serial_baudrate` for slcan, or `device_id` for some interfaces).

| Type | OS | Status |
|---|---|---|
| `slcan` | Windows (COMn, built-in USB serial driver), macOS (`/dev/tty.usbmodem*`), Linux (`/dev/ttyACM*`) | supported, tested |
| `socketcan` | Linux (`can0`, `vcan0`; gs_usb and PEAK through the kernel) | supported, tested |
| `gs_usb`, `pcan`, `kvaser`, `ixxat`, `vector`, ... | as python-can supports them | passed through, documented untested |

`openplc-canopen-diag adapters` (and the configurator's port list) shows serial ports from pyserial's port list, marking known CANable and slcan USB IDs, together with python-can's `detect_available_configs` for the installed interfaces.

The bit rate comes from `--bitrate`, or from the selected network's `adapter.bitrate` when `--config` is given. With neither, the command exits and says so: a wrong bit rate disturbs a running bus, so there is no default. The SocketCAN bit rate is set only when the link is down and the user may configure it, as the plugin does; otherwise the link's own rate is used and reported.

An adapter is opened by one process at a time. The configurator keeps it open while its online view or a trace uses it, and closes it after the same idle time as a runtime connection. A second opener gets "adapter in use (another tool has it open)" instead of the OS error.

### 4. The PC is a guest on the bus
- Nothing is sent on connect. The backend listens for 1 s before its first transmit, which is also where Decision 8's bit rate check will hook in.
- The PC never sends SYNC, heartbeat, TIME or broadcast NMT, and never starts nodes on its own.
- **Other master detection**: an NMT command frame (COB-ID 0), SYNC (0x080) or an SDO request (0x600+n) not sent by this tool marks `other_master: true` in status, with what was seen and when. While it is set, LSS operations answer "another master is active on this bus" unless the request has `force: true` (CLI `--force`), because LSS switches every device's state. SDO and NMT stay allowed. An SDO to a node that just had a foreign SDO request waits 200 ms for that transfer to end before sending, to avoid answering someone else's segment.
- Node state in `status` comes from what the bus shows: the last heartbeat or boot-up per node ID, with age. Nodes not heard from show as unknown. With `--config`, configured nodes are listed by name even when silent.

### 5. Changes are opt-in per session, store is never automatic
The session switch `allow_changes` (CLI `--allow-changes`, a configurator checkbox that starts off and is never saved) gates exactly the ops the plugin gates: `sdo_write`, `nmt` and the `lss_` ops except `lss_find_status`. Without it they answer `changes not allowed` (on a local adapter: "start with --allow-changes"). `store` keeps its own confirmation, and `lss_set_id` and `lss_set_bitrate` store only with `store: true`. Nothing in the backend writes 0x1010 or sends LSS store on its own.

### 6. Operations and their differences from the plugin

| op | On a local adapter |
|---|---|
| `status` | `local: true`, adapter, bit rate, bus state when the adapter reports it (else `null`), `other_master`, nodes seen (id, NMT state, last heard, last EMCY), configured nodes from `--config`. No boot results, holds, SDO variables or SYNC counters. |
| `emcy` | the last 16 EMCYs of any node ID heard since connect |
| `sdo_read`, `sdo_write` | as the plugin: any node 1-127, up to 4096 bytes, timeout 10-10000 ms |
| `nmt` | any node 1-127, sent once. No hold: nothing restarts the node, so `--hold-preop` in restore works by sending `preop` before and `start` after |
| `scan`, `scan_status` | the plugin's algorithm: 8 probes at a time of 0x1018:1, 100 ms each, then identity, device type and name, compared with `--config` when given |
| `lss_*` | as the plugin, plus `force` (Decision 4). There is no configured node to protect, so `lss_set_id` refuses only IDs it has heard heartbeats from, unless forced |
| `trace_*` | same record format, ring of 65536, filters and error frames. Time stamps come from the adapter when it gives hardware time, otherwise from the PC clock. Tx flag on frames this tool sent |
| `sim_*`, slave ops | `not available on a local adapter` |

### 7. Configurator
The online access target becomes a choice: runtime host, local simulator runtime, or USB adapter. The adapter settings (type, channel, bit rate, last used) are kept in the configurator's settings on this PC per project folder, like the runtime host, and never in the project. The allow-changes checkbox is per connection and not kept. Pages that only make sense with a master hide their runtime-only fields. The status banner says "USB adapter slcan:COM5, 250 kbit/s, read-only" and shows the other-master warning.

A **Commission a device** entry on the start page opens the online view on an adapter without any config: scan, OD browser (EDS from the scan match or picked by the user), LSS, parameters and trace. "Add to configuration" from a scan row is offered only when a config is open.

### 8. Hook for raw frames and bit rate detection
These hooks exist so the parallel change can plug in without restructuring this one:
- `localbus.adapter.open(spec, bitrate, listen_only=False)`: the single place an adapter is opened. This change always passes `False`, and the raw-frames change implements listen-only per adapter.
- `LocalBus._transmit(msg)`: the single transmit path, which records Tx in the trace ring and the other-master bookkeeping.
- The op table in `LocalBus`: `send_frame` and `detect_bitrate` are added there, and in the plugin, by that change.
- The 1 s listen-before-transmit in Decision 4 is where a bit rate sanity check goes.

### 9. Testing
- **Unit tests on python-can's `virtual` bus** with an in-test fake device (SDO server with a small dictionary, heartbeat, EMCY, LSS slave with fastscan), covering each op, segmented SDO, aborts and timeouts, scan, LSS find, set ID and store-only-when-asked, other-master detection, allow-changes gating and trace records. They run in CI and on the four PC tools runners (Windows, macOS, Linux x86_64 and ARM64).
- **Linux CI on `vcan0`**: `openplc-canopen-sim` runs the rtd-sensor and ping-pong devices, and `test/lss/lss_slave` an unconfigured LSS device. `openplc-canopen-diag --adapter socketcan:vcan0` then runs status, scan, sdo-read and sdo-write, backup and compare, lss-find and lss-set-id, and a trace with pcapng export. A parity step runs the same read-only commands through the plugin's diagnostics channel on the same bus and compares the JSON results field by field (except fields documented as runtime-only).
- **Bench**: Decision 10.

### 10. Hardware checks
Following the project rule, these run when the Pi is reachable through Remote Control and stay open otherwise:
- On the Pi (Linux, the PC tools installed with uv), with the PLC stopped and the CANable through python-can `slcan` (not the plugin): scan finds the bench node, sdo-read of 0x1018, backup and compare, trace, and LSS inquire.
- On the Pi with the PLC running: the other-master warning appears and LSS is refused without `--force`.
- On a Mac or Windows PC with the CANable plugged in, which needs the owner to move the adapter: the configurator's USB adapter target, scan, OD browser and backup.

## Risks / Trade-offs

- **SDO collision with a running master**: two clients on the default SDO channel to one node can corrupt each other's segmented transfer. Mitigated by the foreign-SDO wait and the other-master warning; documented as "use read-only and short reads while a PLC runs".
- **Adapter quirks**: adapters differ in what python-can can read from them (error counters, bus state, hardware time stamps). `status` reports `null` for what an adapter does not give, and the apply step records per tested adapter what it gives.
- **Dependency weight**: python-can brings a few small dependencies of its own. The apply step checks that each has a wheel or pure Python build on all four runners, and the PC tools job checks a fresh uv install on each OS.
- **Windows serial ports**: CANable stock firmware enumerates as a CDC device. Windows 10 and 11 bind the built-in driver, with no install needed. Older Windows are not supported.
- **Two tools on one adapter**: refused with a clear message rather than shared. Sharing needs a local broker, which is left out.

## Open Questions

- Should the configurator offer the adapter target while its project config has a different bit rate than the one typed? Proposed default: allow it, and show both rates in the banner.
- Whether to add `gs_usb` on Windows and macOS (libusb, Zadig on Windows) to the tested set later, if a candleLight-firmware adapter is on the bench.
