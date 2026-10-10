# Design: fix-security-audit-findings

## Context

The findings come from a code audit of main e17fcae (2026-10-09). Six reviewers each took one area: the diagnostics channel, the CANopen runtime, config with raw CAN and J1939, the Modbus bridge, the PC tools, and the simulator. The top findings were then re-checked against the code. Three were reproduced:
- **Bridge memory:** built and driven over localhost, about 4 GB in 25 s.
- **Expression stack overflow:** the parser was compiled and fed 10,000 `(`.
- **Editor hook v2 refusal:** run against `config/slave`.

The rest come from reading the code. Every fix task starts with a test that fails on main, so findings that turn out not to be real are dropped with a note in the PR instead of being "fixed".

IDs used in tasks.md (line numbers are from e17fcae):

| ID | Finding | Where |
|---|---|---|
| H1 | Raw CAN locations not checked against the I/O image; out-of-bounds read in `image_read_output` | `can/raw/config.cpp:83-104,157-167`, `can/image_io.h:62-85` |
| H2 | Bridge reply queue unbounded; POLLIN stays armed | `bridge/modbus_server.cpp` ~393-439 |
| H3 | Bridge writes open when `writers` is missing, including NMT broadcast | `bridge/modbus_server.h:246-247`, `can/config.cpp:2452-2467` |
| H4 | Event-driven outputs not re-sent after node up or gate re-open | `canopen/network.cpp:309-325,1151-1173` |
| H5 | Diag: input buffer grows unchecked during login backoff | `can/diag.cpp:743-745,776-790` |
| H6 | Sim expression recursion without depth limit; `sim_check_expr` is read-only | `canopen/sim/sim_expr.cpp` ~260-330, `sim_engine.cpp:363` |
| H7 | Sim `power on` / `clear` revive a node marked as taken | `sim_engine.cpp:1065-1069,1239-1243` |
| H8 | Replay loop restarts 1 ms after the end, no whole-loop rate check | `can/diag.cpp:1897-1908,1952-1957` |
| H9 | PLC frame blocks claim slots with check-then-write | `can/raw/plc_frames.cpp` ~115,212-221,373 |
| M1 | First SYNC after recovery carries pre-outage outputs | `network.cpp:855-862,1158` |
| M2 | No safe state on PLC stop or a hung scan | `canopen/bus.cpp` `run_session`, `process_image.h` |
| M3 | Node without heartbeat or guarding never seen as lost | `can/config.cpp:1219-1235`, `dcf_gen.cpp:288-295` |
| M4 | Failed on-change send recorded as sent (raw, J1939) | `raw/engine.cpp:208-212`, `j1939_network.cpp:299-300` |
| M5 | PLC SDO deadline pushed forward forever while a node boots | `network_plc.cpp:121-131`, `plc_api.cpp:93-98` |
| M6 | Owned-ID guard misses 29-bit COB-IDs, slave custom PDOs, the master's SDO server | `can/frame_tx.cpp:54-90` |
| M7 | Byte-address bound check overflows in 32 bits | `can/config.cpp:293,2387`, `bridge_host.cpp:304` |
| M8 | Diag SDO write and NMT need no `force` on a running node | `can/diag.cpp:1134-1165` |
| M9 | Bit rate detection up to ~27 min, no stop, restore can skip the bit rate | `diag.cpp:2041-2054`, `bitrate_sweep.cpp:182-185` |
| M10 | ~11 MB line for any logged-in client, rescanned on every read | `diag.cpp:782-784`, `diag.h:200` |
| M11 | Bridge slowloris: idle timer reset by any byte, no per-address cap | `modbus_server.cpp` ~412,473 |
| M12 | Bridge `stop` mode resumes stale pre-loss outputs | `bridge_host.cpp` ~527-531 |
| M13 | Sim extra devices skip the free node ID check (plugin) | `bus.cpp` ~272-283, `sim_engine.cpp:423-440` |
| M14 | Sim CSV source reads any path, unbounded | `sim/sim_source.cpp` `load_csv` |
| M15 | Standalone sim socket runs JSON lines after an HTTP preamble without `hello` | `tools/sim/control.cpp` `handle_line` |
| M16 | `delay()` history unbounded on NaN or time going back | `sim_expr.cpp` `Fn::Delay` |
| M17 | `repeat` without a wait runs 1000 steps per tick | `sim_engine.cpp:1385` |
| M18 | Editor hook refuses version 2 configs | `tools/editor-hook/canworks_hook/snapshot.py:115-116` |
| M19 | Configurator lone-device sweep skips the CLI's guards | `configurator/server.py:2290-2310` vs `localbus/client.py:949-981` |
| M20 | Configurator re-sends a timed-out request (NMT, SDO write, frames) | `configurator/online.py:166-185` |
| M21 | Deploy starts a PLC that was stopped before the upload | `cli.py:586-592` |
| L1 | Diag `scan` ungated; 4 slots held by idle logins; per-frame log; maps never pruned | `diag.cpp:1103,1613`, `diag.h:195,385-387` |
| L2 | Bridge allowlist `add()` errors ignored | `bridge_host.cpp` ~446-447 |
| L3 | `waitpid` without a time limit; ECHILD counted as success | `dcf_gen.cpp:399`, `eds_lint.cpp:75` |
| L4 | EDS lint `python -m` without `-I` | `eds_lint.cpp:134` |
| L5 | `read_concise_dcf` bound check can wrap on 32-bit | `dcf_gen.cpp:350` |
| L6 | FIFO 49 bus thread spins up to 2 s at shutdown; blocking netlink on it | `bus.cpp:95-96,408-414` |
| L7 | Receiver reopen races `on_frame`; `bus_info` seqlock spins | `plc_frames.cpp:177-186,490` |
| L8 | Interface names over 15 characters truncated on the raw path | `raw_link.cpp:103`, `config.cpp:1579` |
| L9 | J1939 Request replies not rate-limited; no Cannot Claim delay | `j1939_network.cpp` ~260-280 |
| L10 | Windows `.cmd` shim arguments not escaped | `editorproject.py:82-97`, `cli.py:189-192` |
| L11 | Local runtime re-pins a changed cert and sends the password; prints it | `localruntime.py:250-336` |
| L12 | Configurator token in the start URL | `configurator/server.py:2918` |
| L13 | Sim: `cJSON_CreateNull` leak, UB casts, `CANWORKS_FORCE_SIMULATE` only `1` | `sim_engine.cpp`, `sim_raw.cpp` |
| L14 | Master TPDO feeding a slave RPDO with transmission 0 may never be sent (unverified) | `network.cpp` `tpdo_event_` |
| L15 | Bridge unit runs as root with no memory limit | `scripts/install-bridge.sh` ~166-181 |

The diagnostics port binding to `0.0.0.0` by default is kept on purpose. It is TLS with SCRAM, and remote access from the PC is its use. The docs get a sentence on `bind`.

## Goals / Non-Goals

**Goals:**
- Fix every finding above, each with a test that fails before the fix.
- Make the safe choice the default where a finding comes from a default: bridge writers, PLC stop, scan watchdog, a stopped PLC after deploy.
- Keep PR CI wall time and summed job time at or below the baseline.

**Non-Goals:**
- A new authentication scheme for Modbus TCP. The protocol has none; allowlists and network placement stay the tools.
- Moving the diagnostics default bind to loopback.
- Compatibility layers for the config changes. The project is not in real use, so these are clean cuts.

## Decisions

### 1. Raw locations through the common bound check (H1, M7)
The raw parser calls the same image-limit check as `Parser::get_location`, for every location kind: status, counter, id, dlc, data, trigger, enable and signals. The check is written as `index >= limit || bytes > limit - index`, so it cannot wrap. The bridge host sizes its image in `uint64_t` and refuses anything over the configured limit. The parity corpus (`test/fixtures/config/bad`) gets files for both cases, so the configurator refuses them too.

### 2. Outputs when a node comes up and when the gate opens (H4, M1)
`SetUp(id, true)` writes that node's output bindings from the latest snapshot into the master's mapped objects before `EnableTpdos`. After enabling, it calls `TpdoEvent` once for each of the node's event-driven TPDOs. `ApplyOutputsGate(true)` and gateway route re-open do the same for every up node. `last_out_` stays as the change filter in between.
*Alternative:* clear `last_out_` for a down node, so the next scan counts as changed. Rejected: with PLC-cycle SYNC off and a quiet program there is no next change to wait for.
*Test:* sim test. Node 5 with an event-driven RPDO, output held at 1, simulated power cycle: after the reboot the RPDO goes out once with 1. With timer SYNC, the first synchronous RPDO after recovery carries the current value.
L14 is checked with a sim test in the same group and fixed if real.

### 3. PLC stop, plugin stop and a hung scan (M2)
- **`master.on_plc_stop`**, one of `"preop"` (default), `"stop"` or `"keep"`. On `stop_loop`, before the session ends, the master sends the outputs once more with the gate closed (no change), then an NMT command to each configured node that is up, then closes. `"keep"` is today's behaviour.
  - Pre-operational is the default because it stops PDOs on the device side, so the device's own communication-loss setting (for example 0x6007 in CiA 402, or 0x1029) applies, while SDO access stays available for a restart.
  - Slave networks and J1939 are not affected; they have no NMT master role.
- **`master.scan_watchdog_ms`** (default 1000, 0 off, 10..60000). The bus thread watches `scan_count`. When it has not advanced for that long while the PLC runs, the outputs gate closes (the same gate the bridge watchdog uses: RPDOs and raw/J1939 transmit stop, SYNC keeps going), with a log line. It opens again on the next advance, and decision 2 re-sends the outputs then.
- The bridge has no scan; its own watchdog stays as it is.

### 4. Unsupervised nodes (M3)
At config load, a node whose effective heartbeat consumer time is 0 and that has no guarding is refused with "node N has no heartbeat or guarding: its loss would never be detected; set heartbeat_ms, or heartbeat_ms: 0 to accept that". The effective time comes from `heartbeat_ms`, or from the EDS 0x1017 default when that key is absent. An explicit `"heartbeat_ms": 0` is accepted with a warning at start. The configurator's check does the same (parity corpus).

### 5. Sends that fail (M4)
- **Raw:** `sent_values` and `change_pending` are committed only when the write succeeded. A failed on-change or trigger send stays pending and is tried again on the next 1 ms tick, still subject to `min_gap_ms`. Periodic sends are not bunched up.
- **J1939:** the same applies to `st.data` and `sent_once`.

### 6. PLC SDO wait for a booting node (M5)
The deadline is pushed forward while the node boots, as today, but never past the original deadline plus `kAbsentAfter`. A boot that ends in an error (the boot error byte is set) ends waiting transfers with `ERROR_ID` 3 at once. `PlcRequests::poll` also times out Taken requests whose network side never answered, as a backstop.

### 7. PLC frame blocks across tasks (H9, L7)
- **Slots:** receivers, cyclic jobs and transmit slots are claimed with `compare_exchange_strong` on the slot state.
- **Transmit queue:** becomes multi-producer, a bounded MPSC ring with a per-cell sequence number (Vyukov style). It stays lock-free on the scan side.
- **Generation counters:** `gen` fields become atomics.
- **Receiver reopen:** `rx_open` publishes `open=false` and bumps the epoch before it rewrites the filter. `on_frame` re-checks `open` and the epoch after matching.
- **`bus_info`:** retries the seqlock at most 4 times, then returns the last good copy.

*Test:* a stress test with 4 threads calling send, receive-open and cyclic-start on one network under TSan.

### 8. Diagnostics channel (H5, H8, M6, M8, M9, M10, L1)
- **Input buffer (H5, M10):**
  - `process_input` checks `c.in.size()` against the current limit before the backoff return. During the backoff the server also stops polling that client's socket for reading.
  - The large limit applies only after a line has started with `{"op":"put_config"` (checked on the first 64 bytes).
  - Line scanning remembers the scanned offset.
- **Replay (H8):**
  - Validation treats a looping replay as one repeating sequence: the gap between the last and first frame counts.
  - `service_replays` keeps a sliding one-second window and never sends more than 1000 frames in it.
- **Owned identifiers (M6):** the guard map is built from the effective COB-IDs the network uses, extended ones included. That covers PDO COB-IDs with bit 29 set, a slave network's configured PDO COB-IDs, and the master's own SDO server channel.
- **Changes to a running network (M8):**
  - `sdo_write` to a node that is OPERATIONAL, and `nmt` STOP, ENTER PRE-OPERATIONAL, RESET NODE and RESET COMMUNICATION to a node that is OPERATIONAL, need `force` (START never needs it).
  - The configurator's online view and object dictionary view ask "node N is running; send anyway?" and then send `force`.
  - `canworks-diag` takes `--force`.
- **Scan (L1):** while any node is OPERATIONAL, the scan needs `force`. It stays available without `allow_changes`, because it only reads.
- **Bit rate detection (M9):**
  - total time is capped at 120 s (`listen_ms` × rates × rounds);
  - `detect_bitrate_stop` ends a sweep after the current rate;
  - the restore always calls `set_bitrate` and retries the link up once, logging if either fails.
- **Housekeeping (L1):**
  - login time limit 5 s;
  - per-frame `send_frame` log lines at most 1 per second per client, plus a count;
  - `auth_failed_` and `auth_logged_` entries older than 10 minutes are pruned.

### 9. Modbus bridge (H2, H3, M11, M12, L2, L15)
- **Writers (H3):** `bridge.writers` is required. `["0.0.0.0/0", "::/0"]` is the explicit way to allow every host. The loader, `--check-only` and the configurator say so. The control block's node 0 (broadcast) stays, since only writers can reach it now.
- **Reply queue (H2):** a client's pending replies are capped at 8 KB. While over the cap, the server stops reading from that client. A client still over the cap after 10 s is dropped.
- **Connections (M11):**
  - The idle timer resets only on a complete request.
  - A partial request older than 5 s drops the client.
  - `max_clients_per_address` (default 4).
  - When all slots are full and a writer address connects, the oldest connection from a non-writer is closed to make room.
- **Stop mode (M12):** with `on_client_loss: "stop"`, entering outputs off clears the output image (nothing is sent). The next write starts from zeros, not from pre-loss values. The docs state this difference from `"zero"`, which sends the zeros once.
- **Allowlist (L2):** an `add()` failure is a start failure.
- **Unit (L15):** `MemoryMax=256M` and `TasksMax=64` in the systemd unit. It keeps root, because CAP_NET_ADMIN is needed to set the bit rate.

### 10. Simulator (H6, H7, M13-M17, L13)
- **Expressions (H6):**
  - The parser counts depth and refuses over 128 levels with the position.
  - Expressions longer than 4096 characters are refused.
  - `eval_node` and the tree destructor are iterative or bounded by the same depth.
- **Taken node IDs (H7, M13):**
  - A device gets `taken` (separate from `conflict`) when its node ID is found in use on the wire at session start, or when the runtime guard sees a foreign frame.
  - `power on`, `clear` and scenario steps leave a `taken` device off and answer "node N is taken by a real device".
  - Extra devices go through the same listen check as config nodes, and are also checked against the config's non-simulated node IDs.
- **CSV sources (M14):** files must resolve (realpath) under the config folder or the simulation file's folder and be regular files under 16 MB, with lines under 4096 bytes. They are read on load, never on the bus thread during a tick.
- **`delay()` (M16):** a non-finite delay counts as 0. The history is cleared when `t` goes backwards and capped at 10,000 entries.
- **`repeat` (M17):** a pass of a repeat body that did not wait ends the tick's step budget for that scenario.
- **Standalone control socket (M15):** the first line must be a JSON `hello`, with or without a token. Anything else closes the connection. A line starting with an HTTP method closes it at once.
- **Small fixes (L13):** the null leak, the casts are clamped, and `CANWORKS_FORCE_SIMULATE` set to anything but `1` or empty logs a warning that it is ignored.

### 11. PC tools (M18-M21, L10-L12)
- **Editor hook (M18):** validates with `contract.check_config` and walks `contract.all_nodes()` / `eds_users()` like `bundle.rewrite`, so version 1 and 2 are both carried. A test runs the hook over every shipped example config.
- **Configurator lone-device sweep (M19):** the server builds the sweep through the same guard function as `localbus/client.py` `_lone_fields` (allow-changes on, no other master, at most one node heard). The browser confirmation stays as an extra step.
- **Retries (M20):** `Connection.call` retries after a timeout only for operations in the read-only set (`status`, `sdo_read`, `scan`, trace reads, `sim_status`, ...). Any other timeout is reported as "no answer; the request may have been carried out", without resending.
- **Deploy and a stopped PLC (M21):** `canworks-deploy` reads `/api/status` before uploading:
  - stopped before: stays stopped after the build, the tool says so, and `--start` overrides;
  - running before, or no program: started as today; `--no-start` is kept;
  - plugin state unknown from the build log: not started, unless `--start` is given.
- **Windows paths (L10):** on Windows, a project or editor path with `& | ^ % < > "` is refused with a message, rather than escaping for cmd.exe.
- **Local runtime (L11):**
  - The fingerprint is re-pinned only by `start` right after it created or recreated the container itself.
  - Any other change refuses before sending credentials and names `canworks-sim-runtime start`.
  - The start text no longer prints the password; `status --show-password` stays.
- **Start code (L12):** the start URL carries a one-time code that the server swaps for the session cookie and then forgets. The token itself never appears in a URL.

### 12. Plugin housekeeping (L3-L6, L8, L9)
- **Child processes (L3, L4):**
  - `dcfgen` and the lint run under a 60 s limit (`WNOHANG` loop), are killed on timeout, and a `waitpid` error counts as failure.
  - Python runs with `-I`.
  - The `dcfgen` and `python3` paths are resolved once at start to absolute paths.
- **32-bit bound check (L5):** `size > data.size() - pos`.
- **Bus thread at shutdown (L6):** drops to SCHED_OTHER when shutdown starts. `BusMonitor::poll` uses a non-blocking netlink socket with replies read on the next poll.
- **Interface names (L8):** 1-15 characters of `[A-Za-z0-9_.:-]`, checked at load for every network kind.
- **J1939 (L9):**
  - a reply to a Request for the same PGN and requester at most every 50 ms;
  - Cannot Claim waits a pseudo-random 0-153 ms (seeded from the NAME), as J1939-81 asks.

## Risks / Trade-offs

- **`on_plc_stop: "preop"` changes what devices see on every PLC stop.** On the bench, node 23 goes to PRE-OPERATIONAL on stop and is started again on the next PLC start, as today after a reboot. A user who wants the old behaviour sets `"keep"`.
- **Refusing unsupervised nodes can break existing configs.** The bench template project needs `heartbeat_ms` if its node's EDS has no heartbeat default. This is listed as a bench task.
- **Requiring `force` for SDO writes and NMT on running nodes adds a confirmation to the online view.** That is the point: the PLC is driving the node.
- **The scan watchdog needs a sensible default.** 1000 ms is far above any normal scan; a program with a deliberately long scan sets a larger value or 0.
- **CI time.** The new tests are unit and sim tests in existing jobs. A TSan build for the frame-block stress test would cost time, so it runs in the weekly browser workflow, not in PR CI. The PR states wall and summed time against the baseline.

## Migration Plan

There are no users, so this is a clean cut. Bench tasks:
- add `writers` to bridge configs used for HW tests;
- check the template project for supervision;
- a clean PLC start afterwards.
