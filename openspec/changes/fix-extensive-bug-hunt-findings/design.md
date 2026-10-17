# Design: fix-extensive-bug-hunt-findings

## Context

The findings come from a bug hunt of main 7dba547 on 2026-10-17. Eight reviewers each took one area. Evidence: "ran" findings were reproduced (repro tests against the in-process simulated bus, ASan/UBSan builds against Lely, differential fuzzers between the Python check and the plugin's loader, Playwright against the shipped examples with the real plugin); "read" findings were read and re-checked. Every fix task starts with a test that fails on main, so a finding that turns out not to be real is dropped with a note in the PR.

Full report: research notes `bug-hunt-2026-10-17/` in the project folder (one file per area).

ID prefixes: CR CANopen runtime, JR J1939/plain CAN, CF config/EDS/DCF, PC PC tools, SM simulator, NS network surfaces, KV known vulnerabilities, UI configurator.

| ID | Finding | Where (7dba547) | Evidence |
|---|---|---|---|
| CF-H1 | PDO and TIME COB-IDs on restricted IDs (SYNC, TIME, SDO, heartbeat, LSS, default EMCY) accepted | `contract.py:731-737`, `config.cpp:93,480,3174-3183` | ran |
| CF-H2 | Startup SDO / write SDO variable on 0x1010/0x1011 accepted: NVM written at every boot | `config.cpp:56-71`, `contract.py:865-876` | ran |
| CR-H1 | Routed gateway outputs go to 0 after a field bus session restart | `network.cpp:249-293,962-963,1357-1364` | ran |
| JR-H2 | Program cyclic jobs and queued program frames bypass the outputs gate and watchdog | `can/raw/plc_frames.cpp:481-508`, `raw_io.cpp:192-207` | read |
| JR-H1 | Raw rx status/valid stay TRUE while the link is closed | `raw_io.cpp:316-325,341-346` | ran |
| PC-H2 | Adapter `--force` guard misses nodes another master runs | `localbus/client.py:322-347,372-377` | ran |
| PC-H1 | `replay --loop` has no wait or rate limit across loops | `raw/replay.py:95-170`, `diag.py:2265-2297` | ran |
| SM-S1 | Plain CAN scenario `repeat` without a wait spins the raw I/O thread; `repeat` default count differs | `sim/sim_raw.cpp:~600-663`, `sim_raw.h` | ran |
| CR-M1 | `on_upper_loss: hold` forwards EDS defaults after a gateway reset or slave session restart | `plc_slave.cpp:201-215,390-403` | ran |
| CR-M2 | `stop_all_nodes` master stop forgotten on a session restart | `network.cpp:779`, `run_state.h` | ran |
| CR-M3 | `CO_NETWORK_STOP` undone by a node reset or the gateway's release | `network.cpp:1025-1030,1862-1874`, `network_plc.cpp:430-433` | ran |
| JR-M1 | `on_change` + trigger without period sends nothing until the first edge | `can/raw/engine.cpp:236,243,330,370` | ran |
| JR-M2 | J1939 signal valid bits stay TRUE through a bus outage | `j1939_network.cpp:275-296` | ran |
| JR-M3 | Signed J1939 -1/-2 invalid in the plugin, valid in the PC simulator | `j1939_signal.h:38`, `j1939/sim.py` | ran |
| JR-M4 | No scan watchdog for J1939-only or plain-CAN-only projects | `can/engine.cpp:73-76` | read |
| JR-M5 / PC-M3 | TRC 1.0 replay misparsed; ASC `base dec` and relative timestamps ignored | `raw/replay.py:70-80`, `bustrace/formats.py:165-187` | ran |
| CF-M1 | Version 1 configs: no IEC overlap check on the PC | `contract.py:987,1376-1380` | ran |
| CF-M2 | EDS files Lely refuses pass the PC check (bare `$NODEID`, data types) | `contract.py:~1930`, `edslint.py:160-200` | ran |
| CF-M3 | JSON integers above 2^53 rounded by the plugin | `config.cpp:276-281,880-889,2491-2498` | ran |
| CF-M4 | `error_behavior` string values skip the range check | `contract.py:350-370,548-563` | ran |
| CF-M5 | Empty EDS `DefaultValue`: Python unknown, Lely 0 (heartbeat watch sub-index differs) | `eds.py:57-59`, `links.py:253-258`, `eds_check.cpp:686-690` | ran |
| PC-M1 | PDO test drops an unreadable mapping entry and shifts later ones | `pdotest.py:63-67`, `configurator/params.py` | ran |
| PC-M2 | `restore --hold-preop` on an adapter always ends with NMT START | `parameters.py:639-675` | read |
| PC-M4 | `--into-project` drops DBC files and, with `--force`, deletes device notes | `project.py:36-129` | ran |
| PC-M5 | `gs_usb:N` listing and opening count adapters differently | `localbus/adapter.py:328-368,680-703` | read |
| SM-S2 | SDO abort / refuse-write faults ignored on PDO-mapped objects | `sim/sim_device.cpp:~131-145` | ran |
| SM-S3 | `sim_set` on a powered-off device lost; stale hold swallows next value | `sim/sim_engine.cpp:~721-731,~1817-1835` | ran |
| SM-S4 | Expression spellings: `[0x6000:01]`, `[05/…]` differ between Python and plugin | `simfile.py:~99-110,~223-243`, `sim_engine.cpp:~285` | ran |
| SM-S5 | Stored LSS node ID not checked against IDs on a real bus; guard keeps the old ID | `sim_engine.cpp:~485,~574-577`, `tools/sim/sim_run.cpp:~640-663` | read |
| NS-M1 | Modbus bridge request buffer uncapped, O(n) erase per request | `bridge/modbus_server.cpp:113-128,153` | ran |
| KV-M1 | `zeroconf>=0.130` allows five mDNS parser advisories (fixed in 0.149.16) | `tools/deploy/pyproject.toml` | advisories |
| KV-M2 | Bridge built from upstream `development` without a checksum | `scripts/install-bridge.sh`, `docker/bridge/Dockerfile` | read |
| KV-M3 | Actions pinned by tag, incl. a third-party action in the write-scoped release job | `.github/workflows/*` | read |
| UI-N2 | Raw signal empty/invalid length: every check 500, Problems says none | `raw/contract.py:166` | ran |
| UI-N3 | PDO links and heartbeat_watch don't follow node ID change or removal | `app.js:951,6650` | ran |
| UI-N4 | Network rename doesn't update Modbus bridge live lists | `app.js:918` | ran |

Lows taken up (one line each in tasks.md): CR held keep-alive node marked running, watchdog trip released at session end, gateway hold on command byte/reset/operator paths, FilterStart and unconfigured nodes (document), `outputs_gate.h` comment; JR global Request answer, answer destination, extended-ID ownership, J1939-71 ranges, stcall big-endian; CF heartbeat consumer rounding, auto clash order, trailing newline/`-0`/NaN, sim `random_walk` min>max and `*_ms` max, REAL integer defaults, DBC EMCY COB-ID, `SupportedObjects` cap and CiA 306 scope; PC damaged trace files, dropped frames report, lock folder, `notes skeleton -o`, pcapng without CAN, SDO size mismatch, `--sync-counter` help; SM expression semantics, offline expression check, CSV seek, drive reset on NMT reset, control socket fairness, `.state` LSS ID range; NS unpaired timeout and per-address failures, `manage` rate limit, forwarder caps, workflow permissions; KV `libusb` floor, `requires-python`, SECURITY.md and Dependabot; UI N1, N5-N9, `/api/online/status` 502 flood, A3/A7/C13 leftovers.

Not taken up: cJSON 1.7.18 hardening (comes with the runtime pin, KV-M2), can-j1939 pulling pytest (upstream), base image digest pins and scheduled rebuilds (CI cost), download checksums for Lely (pinned by commit; the archive host gives no stable hash), CODESYS real-tool check (separate thread), CODESYS TIME period 0 (both checks already refuse `time_period_ms` 0).

## Decisions

**Restricted IDs (CF-H1).** One rule on both sides, built on the existing `restricted_can_id` (CiA 301's restricted list: 0x000, 0x001-0x07F, 0x101-0x180, 0x581-0x5FF, 0x601-0x67F, 0x6E0-0x6FF, 0x701-0x77F, 0x780-0x7FF, which covers SDO, heartbeat and LSS), plus the network's SYNC COB-ID (0x80 unless configured), its TIME COB-ID (0x100 unless configured), and each configured node's EMCY identifier (0x80+id, or the node's configured or EDS `emcy_cob_id`). A PDO or TIME COB-ID on any of them is refused with the name of the clashing service ("COB-ID 0x602 is node 2's SDO request"). The existing `restricted_can_id` in both checks is extended rather than duplicated; a parity corpus file per class.

**NVM objects (CF-H2).** `plugin_owned_object` gains 0x1010 and 0x1011 for startup SDOs: refused with "use store_configuration / restore_configuration". A write SDO variable on them is allowed only with a `trigger_location`, so a write happens only when the program asks; a read SDO variable stays allowed. Same rule and message in `contract.py`.

**Gateway values at start (CR-H1, CR-M1).** `Network::Start` runs `ServiceGateway()` once after `SetGateway`/`UpperLoss`, and the supervision tick resyncs routes as the slave side already does. On the slave side, after `OnRestored` and at session start, the dictionary's current values become the baseline (`route_have_ = true`, no `put`); only later changes, which come from the upper master's RPDOs or SDO downloads, are forwarded. While the upper master counts as lost with `hold`, nothing is forwarded.

**Run-long stops (CR-M2, CR-M3, CR lows).** `RunState` gains `master_stopped`. `HandleCommand(STOP)` sets it; `Start` with it set sends NMT STOP to all and keeps the master stopped. `ResetNode` keeps `hold_src == Network` while `prog_stopped`. `UpperLoss(true)` gives a node released during a network stop the network stop's hold instead of START. `HoldSource::Gateway` is treated the same on every path: the command byte, resets, operator and CiA 309-3 NMT are refused for a gateway-held node with the same message CO_NMT already gives (diagnostics with `force` may override, as for running nodes). `HandleBoot` computes `node_op` after checking the hold. The scan watchdog trip moves into `RunState` and is cleared only when `scan_count` moves or at PLC stop. Mode 255 and nodes rebooting during a stop: documented (Lely restarts them), since holding PRE-OPERATIONAL would change mode 255's meaning. `FilterStart`'s expansion: documented.

**Program frames and the gate (JR-H2, JR-M4).** While `!outputs_enabled()`, cyclic jobs stay registered but are not sent, and their due time is pushed forward, so they resume at their period when the gate opens and are not sent as a burst. Frames the program queued with `CAN_SEND` are dropped and their blocks get the existing "not running" error. A J1939 or plain CAN network accepts `scan_watchdog_ms` under its `j1939` or `raw` block, same range and default (1000) as the master's; the engine runs one watchdog per network over the shared gate, so a project of any protocol gets one by default.

**Stale receive bits (JR-H1, JR-M2).** On link loss, every rx status and valid bit goes to 0 and is published at once; while the link is closed the retry loop keeps calling the timeout check and publishing inputs. J1939 `bus_lost` clears signal valid bits as well as status bits.

**On-change baseline (JR-M1).** At start and gate reopen, the first snapshot is recorded as the baseline (`sent_values`) without sending; change detection compares against it, so a change before the first trigger is sent.

**J1939 not-available rule (JR-M3, JR-L4).** Signed signals are never checked for not-available or error. Unsigned signals use the J1939-71 ranges: 8 bits 0xFE error, 0xFF n/a; 16 bits 0xFE00-0xFEFF error, 0xFF00-0xFFFF n/a; 32 bits 0xFE000000-0xFEFFFFFF error, 0xFF000000-0xFFFFFFFF n/a; other lengths keep "all ones" and "all ones minus one". Both the plugin and `j1939/sim.py` follow it; the J1939 page documents it.

**J1939 Requests (JR-L1, JR-L5).** J1939-21: a Request to the global address of a PDU1 PGN is answered to the global address; a destination-specific Request is answered to the requester. Both the plugin and the simulator follow it. A J1939_REQUEST completes only on an answer whose destination is our address or global.

**Number parsing parity (CF-M3, CF-M4, CF lows).** JSON integers whose magnitude is above 2^53 are refused by both sides in every field ("write it as a string: "0x…""). Python parses configs with `parse_constant` refusing NaN/Infinity, uses `fullmatch` for number and location patterns, and drops `strip()`; `"-0"` on unsigned is refused. `parse_numbers` follows `additionalProperties` and `patternProperties`. Parity corpus files for each.

**EDS parity (CF-M2, CF-M5, CF lows).** `edslint.prepare` rewrites a bare `$NODEID` (any case) to `$NODEID+0`. The PC EDS reader refuses the DataTypes and value forms Lely's `co_dev` refuses, with the plugin's message, and reads an empty `DefaultValue` as 0. A plain decimal integer on a REAL type is converted like a decimal. `SupportedObjects` above 0xFFFF is refused in `edslint` and `cia306` before looping. EDS-level parity corpus entries are added to `test/fixtures/config/bad`.

**Heartbeat consumer time (CF low).** `dcf_gen` writes the 0x1016 entry from `heartbeat_timeout_ms` directly instead of a multiplier, and `dcfexport.master_input` mirrors it, so the consumer time equals the configured timeout.

**PC tools on a live bus (PC-H1, PC-H2).** `replay.play` waits one recorded period (at least 1 ms) before each loop and limits the rate over the time since the first loop; `--loop` on a plan shorter than 1 s needs `--rate`. On an adapter, `sdo_write`, non-start NMT, `configure`/`restore` writes and `scan` need `--force` when `other_master()` is set or any node's heartbeat reported OPERATIONAL; the refusal names what was seen. No node-guarding RTR is sent by the PC (it would disturb the other master's guarding).

**PDO test, restore, into-project, gs_usb (PC-M1, PC-M2, PC-M4, PC-M5).** A PDO whose mapping sub-indices 1..count cannot all be read is left out of the test with a note. `restore --hold-preop` on a local client starts the node again only if it was OPERATIONAL before, as `configure` does. `--into-project` copies every DBC the config names and each EDS's `.notes.json`, rewritten to base names; with `--force` the old folder is renamed `canworks.bak-<time>` instead of deleted. Adapter listing uses `GsUsb.scan()` itself, prints bus:address, and opening by number uses the same list.

**Trace files (JR-M5, PC-M3, PC lows).** `read_asc` honours `base dec|hex` and `timestamps absolute|relative`. The TRC reader picks the layout from `;$FILEVERSION` and the presence of an Rx/Tx column, refuses unknown versions and lines whose byte count differs from the DLC. All readers turn `ValueError`, `struct.error`, `IndexError` and `TypeError` into `FormatError` with an offset. pcapng without a SocketCAN interface is refused. `canworks-diag trace` reports dropped frames.

**Simulator (SM-S1..S5, SM lows).** The raw scenario runner uses the engine's rule: a pass that ends without waiting stops for this call and `next_in` returns at least one tick; `repeat` without `count` repeats forever in both parsers. SDO rules apply only to SDO access: the device marks SDO processing (a receiver on 0x600+id dispatched before Lely's SSDO) and rules apply while the mark is set; `ApplyFault` refuses a rule on an object the device can only reach by PDO. `sim_set` on a powered-off device is refused ("… is powered off"), as other actions are; the comment is corrected. Python parses subindices as `0x` hex or decimal and refuses a leading-zero device number; the plugin does the same; both spellings go into the shared corpus. Expression semantics follow the C++ implementation (it is what runs), documented in the docs table, and `simfile.Evaluator` is aligned: `hold` takes x on the first tick, `if`/`&&`/`||` evaluate every argument, `lag` uses `1-exp(-dt/tau)`, 64-bit `setbit` is signed, negative shifts give 0. The configurator gets `simfile.check_expression`. A stored LSS ID in `opt_.taken` marks the device taken (and in `sim_run.cpp`); the guard is reinstalled when the node ID changes. NMT reset node calls the drive model's power-on. CSV sources keep their last index. The control socket handles at most 32 lines per poll and stops reading when `kMaxOut` is reached. `.state` LSS IDs outside 1-127 are ignored.

**Network surfaces (NS-M1, NS lows).** The Modbus server reads only while `rx` holds less than one frame and compacts once per round. The link closes an unpaired connection after 30 s or after its first finished `pair` stream, counts failed pairings per address as well as globally, and applies the pairing delay to `manage` logins. The PC forwarders cap concurrent local connections at 4.

**Supply chain (KV-M1..M3, KV lows).** `zeroconf>=0.149.16`, `libusb>=1.0.30; sys_platform == 'win32'`, `requires-python = ">=3.10"` (CI already uses 3.12; clean cut). `install-bridge.sh` defaults `RUNTIME_REF` to the release in `docker/local-runtime/runtime-version` and checks the archive's sha256 stored next to it; CI's `build-plugin` action uses the same pin. Every workflow gets a top-level `permissions: contents: read` (jobs that need more ask for it); all actions are pinned by full SHA with the tag in a comment; `.github/dependabot.yml` covers `github-actions` only, monthly, so pins stay current without pip update PRs adding CI runs. A short SECURITY.md says how to report issues and which versions get fixes.

**Configurator (UI).** `raw/contract.py` skips the location-size message when `length` is invalid (`o.uint` already reported it). `followNodeId` also updates `links[].from.node`, `links[].to[].node` and every `heartbeat_watch`. `removeNode` lists the links, routes and watches that name the node and offers to remove them, as `removeNetwork` does. `renameNetwork` and network removal update `bridge.live_lists[].network`. The rest are small: null guard in `tree.js:299`; `choice()` maps a default's literal value to the default row; links and heartbeat-watch problems lose the repeated prefix and raw paths; a missing HOME falls back to the current folder; Plain CAN networks get the J1939-style trace and Frame lab branch; the "Add live list" button gets a disabled reason; two small targets reach 24 px; `/api/online/status` returns 200 with `{"reachable": false}` instead of 502 while the runtime does not answer. Leftovers of A3/A7/C13: "Network network" wording, the master-ID message names the node, and NMT/Read/Write disable after a connection loss.

**Exports.** `dbcexport` uses the EDS 0x1014 default as the plugin does; `dcfexport` runs `cia306.check` only on the lines it wrote.

## Risks

- Restricted-ID refusal may refuse configs some vendor EDS files suggest (PDOs on 0x6E0-0x6FF are allowed by some stacks). The list follows CiA 301; nothing is in real use, and the message names the clash so a user can move the PDO.
- Changing the J1939 not-available rule changes what the PLC reads at the edges of signed signals. Documented as a clean cut.
- `requires-python >= 3.10` drops 3.8/3.9 users; the release wheel and the Python-free installer bundle their own interpreter.
- CI time: the new tests are unit and sim tests in existing jobs; the browser checks extend existing page tests. Wall and summed time are compared with main in the PR.
