# Design

## Context

- The plugin owns each network's CAN interface: `CanAdapter::prepare()` sets the bit rate over rtnetlink and brings the link up (socketcan with `configure_link`, and slcan, which the plugin creates itself). `Bus::thread_main` runs `prepare()` then `run_session()` in a loop; a session ends on supervision or adapter loss and the loop starts a new one.
- The diagnostics server runs in its own thread. Trace capture already opens a second `CAN_RAW` socket there (`trace_capture.cpp`); Lely's socket keeps `CAN_RAW_LOOPBACK` on, so frames sent from another socket on the host reach the master as if they came from the bus, and the trace marks them Tx.
- A simulated network has no interface: the master runs on Lely's in-process `VirtualCanController`, and `SimTraceTap` feeds the trace.
- `allow_changes`, the client limit and per-network routing are already in place; `nmt`, `sdo_write` and the `lss_` ops show the "changes not allowed" pattern.
- A parallel plan, "PC-direct commissioning", adds a backend on the PC that serves the same diagnostics ops from a USB adapter without a runtime. This change stays on the plugin and the existing clients.

## Goals / Non-Goals

**Goals:**
- Send one or a few hand-made frames, or a slow cyclic frame, from the configurator or CLI, with guards that make it hard to disturb a running machine by accident.
- Find the bit rate of an unknown bus without transmitting anything on it.
- Same op names and fields for the plugin and a later PC-direct backend.

**Non-Goals:**
- A frame generator for load tests (sequences, ramps, high rates). The rate limit is deliberate.
- CAN FD, bit timing other than the CiA 301 rates, sample point search.
- Replaying a trace file onto the bus. Possible follow-up, built on `send_frame`.
- Automatic bit-rate detection at PLC start (`adapter.bitrate: "auto"`). A follow-up once detection has been used on real buses.

## Decisions

### D1. Raw sends from the diagnostics thread on their own socket
`send_frame` opens one `CAN_RAW` socket per network (on first use, closed when no client has a job) in the diagnostics thread and writes there. Cyclic jobs are driven by that thread's poll loop with a monotonic deadline per job. The bus thread and the PLC scan are not involved. Because of loopback the master receives the frame like any bus frame; that is the intended behaviour (sending a boot-up message makes the master boot that node), and the reason for the guard in D3. On a simulated network the frame goes into the virtual bus through the same tap the trace uses.
Alternative: hand the frame to Lely's `io::CanChannel` in the bus thread. Rejected: needs the master's mutex and an executor round trip for a frame the master does not own, and would not show as Tx in the trace (the trace socket would still see it, but timing would be the bus thread's).

### D2. Cyclic jobs are leased to the client
A cyclic job belongs to the client that started it and stops when that client disconnects, sends `send_frame_stop` (one job or all), or after `count` frames or 10 minutes. The answer carries a `job` number. Period 10-60000 ms; at most 8 jobs per network across clients; single frames at most 50 per second per client (a token bucket; over the limit answers `rate limit`). A write that fails with `ENOBUFS` (transmit queue full, typically no other device acknowledges) ends a cyclic job; the reason is logged, kept with the ended job for 60 s, and returned by `send_frame_stop` or listed in `status` under `send_jobs`.

### D3. Guard: `allow_changes`, then `force` for two cases
Without `allow_changes`: `changes not allowed`, as for every op that acts on the bus. With it, `force: true` is needed when
1. the identifier is in the running network's COB-ID map: NMT (0x000), SYNC, TIME, EMCY of configured nodes, every PDO the config sets up (both directions), the SDO request and response COB-IDs of configured nodes, their heartbeats (0x700+n) and the master's own, LSS (0x7E4/0x7E5); on a slave network the slave's own COB-IDs; or
2. any configured node is OPERATIONAL (on a slave network: the slave is OPERATIONAL).
The refusal names the case (`0x205 is RPDO1 of node 5; force needed`, `node 5 is OPERATIONAL; force needed`). Identifiers free on the configured network (an SDO request to an unconfigured node ID, a vendor's private ID) go without `force` while nothing is OPERATIONAL, which is the bench case. The map is built once per session from the generated configuration, the same data the network documentation's frame list shows.
Alternative: refuse IDs in the map outright. Rejected: spoofing a TPDO into the PLC is a legitimate test, it just must not happen by mistake.

### D4. Bit-rate sweep runs between sessions, in the bus thread
`detect_bitrate` asks the network's `Bus` to sweep. The bus thread ends the current session the same way the supervision tick does (nodes report not operational, outputs stop, inputs hold, the PLC keeps scanning), then, still in the bus thread:
1. for each rate (default order 1000, 800, 500, 250, 125, 50, 20, 10; or the request's subset), repeated `rounds` times: link down, set bit rate and `CAN_CTRLMODE_LISTENONLY` over rtnetlink, link up, listen on a raw socket with error frames enabled for `per_rate_ms` (100-10000, default 1000), count valid frames, error frames and distinct identifiers (first 16 kept);
2. link down, configured bit rate without listen-only, link up;
3. back to the normal loop: `prepare()` then a new session; nodes boot as after an adapter loss.
`detect_bitrate` answers at once with progress; `detect_bitrate_status` returns progress and, at the end, the per-rate table and the verdict. Both are served by the diagnostics hub without a session (a sweep has none), like the trace ops. A sweep stops early after a round that gives a clear verdict. One sweep per network at a time; scans, LSS and SDO requests on that network answer `no bus` while it runs, as between sessions. Other networks are untouched.
Alternative: a separate process or a second interface. Rejected: the bit rate is a property of the one controller the master uses.

### D5. Verdict
A rate is a *match* when it saw at least one valid frame and its error frames are no more than 1 % of its valid frames (slcan adapters without error reporting give 0 errors everywhere, so the valid-frame count decides). Exactly one match: `detected`. More than one (very rare; a device switching rates during the sweep): `ambiguous` with the list. None with frames anywhere: `ambiguous` with the rate that had the most valid frames. No frames at all: `silent`, with the hint that a device sends its boot-up message when powered or reset, so power-cycle one during the sweep (or use `rounds`). The answer also says `matches_config` when the detected rate equals `adapter.bitrate`.
A listen-only controller does not acknowledge; on a bus where the only other device is the one transmitting, that device sees acknowledge errors and repeats its frame, which the sweep still counts as received. That device may go error-passive until the master is back and acknowledges again; documented.

### D6. Where detection is refused
- vcan (no bit rate) and simulated networks: `no bit rate on a virtual bus`.
- `socketcan` with `configure_link: false`: `the link is configured by the system (configure_link false)`; the plugin must not change a link it was told to leave alone.
- A driver without listen-only (`EOPNOTSUPP` from rtnetlink): the sweep stops before listening, restores the link and answers `the adapter's driver has no listen-only mode`. slcan on Linux 6.1+ opens the channel with `L` when listen-only is set; to be confirmed on the bench (task 6.2). candleLight/gs_usb, mcp251x and mcp251xfd support it.
- No interface (adapter unplugged): `no bus`.

### D7. Protocol and clients
New ops in protocol version 1; a client that gets `unknown op 'send_frame'` reports that the runtime's plugin is older than the tool. Fields:
- `send_frame`: `id`, `ext` (default false), `rtr` (default false), `dlc` (with `rtr`), `data` (hex bytes, 0-8), `period_ms` (0 or absent: one frame), `count`, `force`. Result: `sent` (single) or `job`.
- `send_frame_stop`: `job` (absent: all of this client's jobs). Result: `stopped` with each job's `sent` count and `reason`.
- `detect_bitrate`: `rates` (list of kbit/s), `per_rate_ms`, `rounds` (1-20, default 1), `force`. Result: as `detect_bitrate_status`.
- `detect_bitrate_status`: `running`, `rate_kbit` (current), `done`, `total`, and when finished `results` (per rate `bitrate_kbit`, `frames`, `error_frames`, `ids`), `verdict` (`detected`, `ambiguous`, `silent`, `failed`), `bitrate_kbit`, `matches_config`, `error`.
- `status` gains `send_jobs` (this network's cyclic jobs: id, period, sent, client) and `bitrate_sweep` (running or not).
The PC-direct backend will serve the same ops; its plan decides how (python-can with listen-only on SocketCAN, `L` on slcan).

### D8. Configurator
- Trace view, **Send** panel (folded by default; disabled with the reason when online access has no `allow_changes`): identifier (hex), Extended, Remote with DLC, data bytes, Single or Cyclic with period and count, **Send** / **Stop**, running jobs with their counts and a Stop each, the last 20 frames sent. A trace row's context menu has **Send this frame** which fills the panel. A refusal that needs `force` opens a confirmation that quotes the reason; confirming resends with `force`. The panel works without a running trace; when one runs the sent frames show as Tx.
- Scan the bus page, **Detect bit rate**: a warning that CANopen on that network stops for the sweep and nodes boot again after it, then progress per rate and the result table. On `detected` with a rate different from the tab's `adapter.bitrate`, a **Use N kbit/s** button sets the field on the page (unsaved; saving and uploading is the user's step, as for any change). The button is not shown for `silent` or `ambiguous`.

## Risks / Trade-offs

- [A forced frame can confuse a running machine] → `allow_changes` off by default, `force` only after a confirmation naming the reason, every send logged with the client's address, the rate limit.
- [A sweep stops CANopen on that network for up to 8 x per_rate_ms x rounds] → refused without `force` while anything is OPERATIONAL, progress shown, configurator warns first; other networks keep running.
- [Listen-only support differs by driver] → explicit refusal and the link restored; bench check on slcan.
- [A bus with traffic only on demand looks silent] → `silent` verdict with the power-cycle hint, `rounds` to sweep longer.
- [Restoring the link after a sweep fails (adapter unplugged mid-sweep)] → the normal loop's `prepare()` handles it as any adapter loss.

## Migration Plan

None: new ops only, no config change. Older clients do not know the ops; older plugins answer `unknown op`.

## Open Questions

- Should `adapter.bitrate: "auto"` (sweep at every PLC start until found) follow? Left out until detection has been used on real buses.
