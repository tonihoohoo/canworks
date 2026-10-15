# Design: fix-critical-bug-hunt-findings

## Context

The findings come from a bug hunt of main 0f7b829 on 2026-10-15. Six reviewers each took one area: the CANopen runtime, J1939 and raw CAN, network-facing code (remote link, diagnostics, CiA 309-3 gateway), the PC tools, the function block library, and the config parser with EDS and the simulator. The config parser, EDS check, DCF generation and the CiA 309-3 text layer were built against Lely with ASan/UBSan and fuzzed. Findings marked "ran" were reproduced; the others were read and re-checked. Every fix task starts with a test that fails on main, so a finding that turns out not to be real is dropped with a note in the PR.

Full report: research notes `critical-bug-hunt-2026-10-15.md` in the project folder.

| ID | Finding | Where (0f7b829) | Evidence |
|---|---|---|---|
| H1 | Number strings: Python decimal, plugin octal for a leading zero | `can/config.cpp:242` (also ~306, ~865, ~2210), `contract.py:233-245`, schema `uint_string` | ran |
| H2 | `cyc_update` input error leaves the job running; block drops its handle | `can/raw/plc_frames.cpp:459-462`, `can_plc_api.h:99`, `library/canworks/CAN_SEND_CYCLIC.cpp:177-188` | ran |
| H3 | Program NMT state and holds live in the per-session `Network` | `canopen/bus.cpp:211`, `network.h:238-242,579-580`, `process_image.cpp:219-226`, `network.cpp:~1791-1797,~1849` | read |
| M1 | `j1939_dm_clear` ignores `allow_changes` | `can/diag.cpp:1295-1324` | read |
| M2 | Master NMT reset restores DCF TPDOs and default values | `network.cpp:219-222,700-703`, Lely `nmt.c` reset path | read + Lely source |
| M3 | Request reply recorded as the on-change send | `j1939_network.cpp:380-388,445-462,588-617` | read |
| M4 | `J1939_RECEIVE` stuck Opening when opened during `sync_receivers` | `j1939_plc_msgs.cpp:341-377` | ran (injected delay) |
| M5 | CiA 309-3 session survives unparseable (HTTP) lines | `cia309_dispatch.cpp:139-178`, `diag.py:2908-2985` | parser ran |
| M6 | CODESYS export: string PDO number drops all channels; string node ID crashes | `codesys/plan.py:206,256-259,316` | ran |
| L1 | Long J1939 send completion taken by the next send | `j1939_network.cpp:914-941,967`, `j1939_socket.cpp:99-131` | read |
| L2 | Raw paged tx: switch value not truncated before page choice | `can/raw/engine.cpp:274-280` | ran |
| L3 | J1939 Request answered before the first scan | `j1939_network.cpp:380-388` | read |
| L4 | Modbus NMT queue unbounded, replays after an outage | `canopen/host_requests.cpp:12-15` | read |
| L5 | Scan watchdog state per session | `network.h:571-573`, `network.cpp:1287-1295` | read |
| L6 | gs_usb listen-only masked away silently; `adapter.listen_only` ignored | `localbus/adapter.py:391-397`, `localbus/core.py:446-487` | read |
| L7 | Link: no cap on unpaired peers, racy pair rate limit, no MemoryMax | `link/device.py:327-348,421-462`, `scripts/install-link.sh:122-135` | read |
| L8 | Discovery: first reply from any source rewrites a remembered link ID | `link/discovery.py:154-177`, `link/pc.py:554-578` | read |
| L9 | Plain CiA 309-3 sessions never time out | `can/cia309_server.cpp` | read |
| L10 | Configurator refuses a one-network v2 save with top-level `cia309` | `configurator/server.py:266-295` | ran |
| L11 | Duplicate JSON keys: Python last wins, cJSON first wins | `contract.py`, cJSON | ran |
| L12 | DM1 code list in a bridge config steps 1 byte, not 4 | `j1939/j1939_config.h:139` | ran |
| L13 | Gateway route + unlocated RPDO entry of the same object sends 0 | `can/config.cpp` ~2880 | read |
| L14 | Gateway "stop_nodes" not re-applied when a session starts with the upper master lost | `network.cpp:895-896` | read |

Not taken up: the packaged ST functions' manifest (already fixed by #120), a Lely EDS reader crash on `SupportedObjects=-1` (the EDS lint rejects such files first).

## Decisions

**Number strings: refuse leading zeros everywhere (H1).** Octal is never what a user means in a CANopen config, and silently reading decimal in C++ would still leave two parsers to keep in step. The schema pattern becomes `^(0|[1-9][0-9]*|0[xX][0-9a-fA-F]+)$`; `contract._uint` and the plugin's `get_uint`, `j_uint64`, `emcy_cob_id` and `error_behavior` parsing refuse the same strings with the same message ("leading zero: write 12 or 0x0C"). The plugin parses with base 10 or base 16 explicitly. `contract.sdo_value`, which today accepts octal on purpose, follows the same rule. Clean cut, no migration (nothing is in real use). A parity corpus file covers it.

**Duplicate keys (L11).** The PC tools load configs with an `object_pairs_hook` that refuses a repeated key. The plugin gets the same rule through a small scan of the parsed cJSON tree (sibling keys per object) right after parsing, so a file sent by diag `put_config` or copied by hand is refused the same way.

**Per-run program state (H3, L5, L14).** A new `RunState` per network, owned by `MasterRuntime` for the PLC run, holds `prog_start`, `prog_stopped`, the node command for stopped nodes, per-node `hold`/`hold_src`, per-node `nmt_resets` seen, and the scan watchdog's last count and time. `Network` reads and writes it instead of its own members. A new session therefore starts the master only if `MayRun()` says so, re-sends held nodes their held command after configuring them (the existing "node boots while stopped" path), and does not see old reset counters as new. The gateway re-evaluates upper loss in `Start` from the current upper state instead of waiting for a change. PLC stop clears `RunState`, as the spec already requires for holds.

**Master reset (M2).** In the NMT reset branch of `HandleCommand`, repeat what `Start` does: every master TPDO invalid, `MapSyncRpdos` again. Outputs then come back only through `SetUp` → `ResendOutputs`, which already respects the outputs gate and program stop.

**Cyclic job error (H2).** Follow the header: an input error in `cyc_update` ends the job (generation bumped, slot freed) before returning 2. The generated block also calls `cyc_stop` whenever it drops a non-zero handle, so a future plugin bug of the same kind still cannot leave an orphan job.

**Receiver race (M4).** `sync_receivers` reads `filter_gen_` in the first locked section and stores that value as seen at the end, so an open in between bumps the generation past it and is picked up on the next tick.

**Long send matching (L1).** Use `SOF_TIMESTAMPING_OPT_ID`: each long send records the kernel's per-socket counter, and completions are matched by `ee_data`. A send that times out on the PLC side keeps its entry until its completion arrives or the socket closes, then the entry is dropped silently. A rebind marks in-flight sends failed (`ERROR_ID` 14) at once instead of letting them time out.

**Request replies (M3, L3).** A reply whose destination differs from the message's own destination does not update `sent_once`, `data` or `last_sent`. Requests before `scan_count > 0` get no answer (a NACK for PDU1 would tell the requester "not supported", which is wrong).

**`j1939_dm_clear` (M1).** Refused with "changes not allowed" unless `allow_changes`, checked before `force`. `j1939_dm_read` stays open.

**CiA 309-3 first line (M5, L9).** The session's first line must parse as a CiA 309-3 command (comments and blank lines excepted). Otherwise the server writes one `ERROR: 101` and closes. A later unparseable line keeps today's `ERROR: 101` answer, since a real client may send a typo. The PC forwarder (`canworks-diag gateway --listen`) applies the same check before it forwards anything. Plain sessions close after `idle_timeout_s` (default 300, 0 off) without a line. No per-run secret on the PC forwarder: standard CiA 309-3 clients cannot send one, and the first-line check is what stops browser requests.

**Modbus NMT while down (L4).** `HostRequests::nmt` refuses while the network's session is down, and the control block reports it like any refused command. The queue gets a cap of 16.

**CODESYS strings (M6).** `plan.py` uses `contract._uint` for every number it reads from the config, as the other exports do. A failure while building channels is reported as an error, never swallowed into an empty map.

**Local bus listen-only (L6).** If the adapter cannot do listen-only, opening in listen-only fails with a message naming the adapter; `Opened.listen_only` is only True when the device really is. A network with `adapter.listen_only: true` connects without the 0x7E5 probe and stays listen-only.

**Link (L7, L8).** At most 8 unpaired connections and 2 per remote address; a pairing attempt counts against the rate limit before the SCRAM exchange starts; the unit gets `MemoryMax=128M`. Discovery accepts a reply only from the address it queried (or, for broadcast, records the source), and a reply whose ID differs from a paired entry's is shown as "changed identity" and needs `--repair`.
