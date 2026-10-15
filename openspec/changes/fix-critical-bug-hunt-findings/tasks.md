# Tasks

Finding IDs refer to the table in design.md. Each fix starts with a test that fails on main; a finding whose test cannot be made to fail is dropped with a note in the PR. Each group lands its own tests and docs.

## 1. Config numbers

- [x] 1.1 H1: parity corpus file with node_id `"012"` and COB-IDs `"0200"`/`"0300"`; today the Python check passes and the plugin reads octal.
- [x] 1.2 H1: schema `uint_string` to `^(0|[1-9][0-9]*|0[xX][0-9a-fA-F]+)$`; `contract._uint` and `contract.sdo_value` refuse a leading zero with "leading zero: write 12 or 0x0C"; plugin `get_uint`, `j_uint64`, `emcy_cob_id` and `error_behavior` keys parse base 10 or 16 explicitly and refuse the same strings; 1.1 refused on both sides with the same message.
- [x] 1.3 L11: duplicate keys refused by the PC tools (`object_pairs_hook`) and by the plugin (sibling-key scan after cJSON parse); parity corpus file.
- [x] 1.4 L13: a gateway route whose object is also an RPDO entry without `iec_location` is refused; parity corpus file.
- [x] 1.5 docs/config.md: number format sentence; check shipped examples and test fixtures for leading zeros.

## 2. CANopen runtime

- [x] 2.1 H3: sim test that restarts the bus session (test hook that throws in the session loop or toggles a fake interface down/up) after `CO_NETWORK_STOP` with `NODE_COMMAND := 2`; today the nodes are started again and RPDOs go out.
- [x] 2.2 H3: per-network `RunState` owned by the runtime for the PLC run (program start/stop, node command, holds, seen reset counters); `Network` uses it; 2.1 passes; tests for a held node, a `master.start: false` network started by the program, and no spurious RESET NODE after a session restart; PLC stop clears it.
- [x] 2.3 L14: gateway re-evaluates the upper master in `Start`; sim test with the upper master missing across a session restart.
- [x] 2.4 L5: scan watchdog state in `RunState`; test with a hung scan across a session restart keeps the gate closed.
- [x] 2.5 M2: sim test with a mandatory node lost and `reset_all_nodes`: no master TPDO with default values before the node is up again; fix in the reset branch (TPDOs off, `MapSyncRpdos`); also with the outputs gate closed and after `CO_NETWORK_STOP`.
- [x] 2.6 L4: Modbus control-block NMT refused while the network is down, queue cap 16; bridge test.

## 3. PLC function blocks

- [x] 3.1 H2: test through the block glue: running job, `PERIOD := T#0s`, then `ENABLE` FALSE → no frame due; DLC 9 then re-enable → one job.
- [x] 3.2 H2: `cyc_update` ends the job on an input error; `generate.py` CAN_SEND_CYCLIC body calls `cyc_stop` before dropping a handle; regenerate the block and `canworks.stlib`; 3.1 passes.
- [x] 3.3 M4: test with an injected delay hook in `sync_receivers` (test build only); generation captured in the first locked section; no stuck receiver over 20000 trials.
- [x] 3.4 L1: vcan test: long send times out, a second long send must not take the first one's completion; match by `SOF_TIMESTAMPING_OPT_ID`; rebind fails in-flight sends with `ERROR_ID` 14.

## 4. J1939 and raw CAN

- [x] 4.1 M3: test: on-change PDU1 message to 0x20, value changes, a Request from 0x30 arrives first → 0x20 still gets the new value; fix.
- [x] 4.2 L3: no Request answer before the first scan; test.
- [x] 4.3 L2: raw paged tx truncates the switch value to its length; harness test with value 17 on a 4-bit switch sends page 1 with its signals.
- [x] 4.4 L12: bridge DM1 code list in 4-byte steps; bridge config test with `dtcs` 3.

## 5. Diagnostics and gateways

- [x] 5.1 M1: diag test: `j1939_dm_clear` with `force` on a read-only server → "changes not allowed"; fix; docs/diagnostics.md.
- [x] 5.2 M5: gateway test: first line `POST / HTTP/1.1` then a valid `[1] 1 5 w 0x2000 0 u8 1` → closed after one `ERROR: 101`, nothing sent; same through `canworks-diag gateway --listen`; a later typo still answers `ERROR: 101` and keeps the session.
- [x] 5.3 L9: `cia309.idle_timeout_s` (default 300, 0 off) in schema, contract, plugin and configurator; test with a short timeout.
- [x] 5.4 Gateway docs page: first-line rule and idle timeout.

## 6. PC tools

- [x] 6.1 M6: CODESYS export test with `"number": "1"` and `"node_id": "0x02"`; numbers through `contract._uint`; build errors reported, never an empty channel map.
- [x] 6.2 L10: configurator save test of a one-network v2 config with top-level `cia309`; `lowest_version` moves it under `master`.
- [x] 6.3 L6: adapter without listen-only support refuses a listen-only open with a message; `adapter.listen_only: true` connects without the probe; tests with the gs_usb fake.
- [x] 6.4 L7: link service caps (8 unpaired, 2 per address), attempt counted before login, `MemoryMax=128M` in the unit; tests.
- [x] 6.5 L8: discovery takes replies only from the queried address; a changed ID on a paired runtime is reported and needs `--repair`; tests.
- [x] 6.6 README and docs for user-visible changes (number format, listen-only, gateway idle timeout, link repair).

## 7. Hardware

- [ ] 7.1 On the Pi with node 23: run `CO_NETWORK_STOP` with `NODE_COMMAND := 2`, take the CAN interface down and up, confirm node 23 stays STOPPED and no RPDO is sent; then `CO_NETWORK_START` brings it back. Clean PLC start afterwards.
- [ ] 7.2 On the Pi: `CAN_SEND_CYCLIC` with `PERIOD` set to 0 while running, confirm the frame stops on the bus and `ENABLE` FALSE/TRUE starts one job.

## 8. CI time

- [ ] 8.1 Compare the PR's CI wall and summed job time with the main baseline and state both in the PR body.
