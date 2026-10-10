# Tasks

Finding IDs refer to the table in design.md. Each fix starts with a test that fails on main; a finding whose test cannot be made to fail is dropped with a note in the PR. Each group lands its own tests and docs.

## 1. Crashes from config and requests

- [ ] 1.1 H1: raw locations (status, counter, id, dlc, data, trigger, enable, signals) through the image-limit check; canopen_check test with `%QW5000` on a 1024 image refused; parity corpus file.
- [ ] 1.2 M7: overflow-free byte-address checks in `config.cpp` (`index >= limit || bytes > limit - index`) and `uint64_t` image sizing in `bridge_host.cpp`; test with `%IB4294967295`; parity corpus file.
- [ ] 1.3 L5: `read_concise_dcf` check `size > data.size() - pos`; unit test with a truncated file whose size field is 0xFFFFFFF0.
- [ ] 1.4 H6: expression depth limit 128 and length limit 4096 in `sim_expr.cpp`, bounded `eval_node` and destruction; unit test with 10,000 `(` refused with its position and no crash; same for a `simulation.json` expression and `sim_check_expr`.

## 2. Outputs on the bus

- [ ] 2.1 H4: sim test that fails today: node 5 event-driven RPDO, output held at 1, simulated power cycle → RPDO sent once with 1 after the reboot.
- [ ] 2.2 H4/M1: `SetUp(id, true)` writes the node's bindings before `EnableTpdos` and fires its event-driven TPDOs once; `ApplyOutputsGate(true)` and gateway route re-open do the same; 2.1 passes; timer-SYNC sim test: first synchronous RPDO after recovery carries the current value.
- [ ] 2.3 L14: sim test for a master TPDO feeding a slave RPDO with transmission 0; fix if it is never sent.
- [ ] 2.4 M2: `master.on_plc_stop` (`preop` default, `stop`, `keep`) in schema, contract, plugin and configurator; sim test: PLC stop → each up node gets ENTER PRE-OPERATIONAL before the network closes; `keep` sends nothing.
- [ ] 2.5 M2: `master.scan_watchdog_ms` (default 1000, 0 off, 10..60000); bus thread watches `scan_count` and closes the outputs gate; sim test with a host that stops advancing the scan → RPDOs stop, SYNC keeps going, log line; advance again → outputs re-sent (2.2).
- [ ] 2.6 M4: raw on-change and trigger sends commit only on success and stay pending on failure; J1939 `send_tx` the same; unit tests with a send that fails once.
- [ ] 2.7 M3: refuse a node with no heartbeat consumer time and no guarding unless `heartbeat_ms: 0` is explicit (then a start warning); plugin and configurator check; parity corpus file; update shipped examples that need it.

## 3. PLC function blocks

- [ ] 3.1 H9: stress test with 4 threads calling send, receive-open and cyclic-start on one network; confirm lost or duplicated frames today.
- [ ] 3.2 H9: CAS slot claims, MPSC transmit ring, atomic `gen`; 3.1 passes; the TSan variant runs in the weekly browser workflow.
- [ ] 3.3 L7: receiver reopen publishes `open=false` and bumps the epoch first; `on_frame` re-checks; `bus_info` retries at most 4 times then returns the last copy; unit tests.
- [ ] 3.4 M5: PLC SDO wait capped at the original deadline plus `kAbsentAfter`; a boot error ends waiting transfers with `ERROR_ID` 3; Taken requests time out in `PlcRequests::poll`; sim test with a node that fails its identity check.

## 4. Diagnostics channel

- [ ] 4.1 H5: test: failed login, then a second connection streams 64 KB without a newline during the backoff → closed with "request line too long"; fix the check order and stop reading during the backoff.
- [ ] 4.2 M10: large line limit only for a `put_config` line; scanned-offset line search; test that a 1 MB non-`put_config` line is refused.
- [ ] 4.3 H8: looping replay validated as one repeating sequence and rate-limited at run time (sliding 1 s window ≤ 1000 frames); test: 10-frame replay 1 ms apart with `loop` → refused; a valid loop never exceeds 1000 frames in any second of the trace.
- [ ] 4.4 M6: guard map from the effective COB-IDs incl. 29-bit PDO COB-IDs, slave PDO COB-IDs and the master's SDO server; tests per case.
- [ ] 4.5 M8: `sdo_write` and `nmt` (all but START) to an OPERATIONAL node need `force`; `canworks-diag --force`; configurator online and OD views ask and send `force`; tests in diag, CLI and page tests.
- [ ] 4.6 L1: `scan` needs `force` while any node is OPERATIONAL; login time limit 5 s; `send_frame` log lines rate-limited with a count; prune auth maps after 10 minutes; tests.
- [ ] 4.7 M9: total sweep time ≤ 120 s; `detect_bitrate_stop` op and CLI command; restore always sets the bit rate and retries link up once; tests with the slcan and socketcan fakes.
- [ ] 4.8 docs/diagnostics.md: the new `force` cases, `detect_bitrate_stop`, the limits, and a sentence on `bind`.

## 5. Modbus bridge

- [ ] 5.1 H2: test with a client that pipelines reads and never reads → bridge memory stays bounded and the client is dropped after 10 s over the cap; 8 KB reply cap with POLLIN off while over it.
- [ ] 5.2 H3: `bridge.writers` required in schema, plugin config, `--check-only` and the configurator's bridge panel; the message names `["0.0.0.0/0", "::/0"]`; parity corpus file; examples and docs updated.
- [ ] 5.3 M11: idle timer on complete requests only; 5 s partial-request limit; `max_clients_per_address` (default 4); writer evicts the oldest non-writer when full; tests.
- [ ] 5.4 M12: `stop` clears the output image on entering outputs off; test: loss, then one coil write → other outputs read 0, not their pre-loss values.
- [ ] 5.5 L2: allowlist `add()` failure stops the start; L15: `MemoryMax=256M`, `TasksMax=64` in the unit from `install-bridge.sh`.
- [ ] 5.6 docs/modbus-bridge.md: required `writers`, the limits, stop vs zero.

## 6. Simulator

- [ ] 6.1 H7: sim test: node 5 `simulate: true` taken on the wire, then `clear all`, `power on` and a scenario `clear` → nothing sent with node ID 5; separate `taken` flag.
- [ ] 6.2 M13: extra devices through the listen check and against non-simulated config node IDs; sim test.
- [ ] 6.3 M14: CSV path rules (realpath under the config or simulation folder, regular file, 16 MB, 4096-byte lines), read on load only; tests for `/dev/zero`, a FIFO, `..` and an absolute path.
- [ ] 6.4 M16: `delay()` non-finite delay → 0, history cleared when `t` goes back, cap 10,000; unit test.
- [ ] 6.5 M17: a repeat pass without a wait ends the scenario's step budget for the tick; test: `repeat` of `log` writes at most one line per tick.
- [ ] 6.6 M15: standalone control socket: first line must be `hello`; HTTP method or non-JSON closes; test with an HTTP POST carrying JSON lines → nothing run.
- [ ] 6.7 L13: `cJSON_CreateNull` leak, clamped casts, `CANWORKS_FORCE_SIMULATE` warning for other values; docs/simulator.md.

## 7. Plugin housekeeping

- [ ] 7.1 L3/L4: 60 s limit for `dcfgen` and the lint with kill on timeout, `waitpid` errors as failures, `python -I`, absolute tool paths resolved at start; test with a fake `dcfgen` that sleeps.
- [ ] 7.2 L6: bus thread to SCHED_OTHER on shutdown; non-blocking netlink in `BusMonitor::poll`.
- [ ] 7.3 L8: interface name 1-15 of `[A-Za-z0-9_.:-]` for every network kind; parity corpus file.
- [ ] 7.4 L9: J1939 Request reply rate limit (same PGN and requester ≤ every 50 ms); Cannot Claim delay 0-153 ms; J1939 sim tests.

## 8. PC tools

- [ ] 8.1 M18: editor hook carries version 2 configs; test runs the hook over every shipped example config (v1 and v2), each applied.
- [ ] 8.2 M19: configurator lone-device sweep through the CLI's guard; test: two nodes heard → refused, nothing sent.
- [ ] 8.3 M20: `Connection.call` retries only read-only ops; test: timed-out `nmt` is reported, not re-sent.
- [ ] 8.4 M21: deploy keeps a stopped PLC stopped unless `--start`; unknown plugin state → not started without `--start`; tests with the fake runtime; docs/deploy.md.
- [ ] 8.5 L10: refuse Windows paths with cmd.exe special characters for the editor shim; test.
- [ ] 8.6 L11: local runtime re-pins only after its own create; other changes refused before credentials; password not printed at start; tests; docs/local-runtime.md.
- [ ] 8.7 L12: one-time start code swapped for the cookie; token never in a URL; server test.

## 9. CI, docs and release

- [ ] 9.1 CI time: wall and summed job time of the PR run vs the median of the last 5 green `main` runs with code changes, both at or below, stated in the PR body; pay for new tests with shard rebalancing if needed.
- [ ] 9.2 docs/config.md (`on_plc_stop`, `scan_watchdog_ms`, supervision rule, interface names), README where a listed behaviour changed.
- [ ] 9.3 PC tools minor version bump; golden doc models refreshed if they change.
- [ ] 9.4 Banned-word check on the branch (`--files` and `--range origin/main..HEAD`).

## 10. Hardware (bench)

- [ ] 10.1 NMT RESET NODE to node 23 from the diag channel (stands in for a power cycle): its event-driven outputs are on the bus again after it is back, without a program change.
- [ ] 10.2 PLC stop with the default `on_plc_stop`: node 23 goes PRE-OPERATIONAL (trace); PLC start brings it back to OPERATIONAL.
- [ ] 10.3 Bridge with `writers` set, from the Windows PC: writes from a listed address work, from another address get exception 0x01; a client that never reads is dropped and the bridge's memory stays flat.
- [ ] 10.4 Bench configs: add `writers` to bridge test configs; check the template project for supervision and give it `heartbeat_ms` if needed; clean PLC start afterwards.
