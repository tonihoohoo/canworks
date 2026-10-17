# Tasks

Finding IDs refer to the table in design.md. Each fix starts with a test that fails on main; a finding whose test cannot be made to fail is dropped with a note in the PR. Each group lands its own tests and docs. The bug hunt's repro tests (research notes, `canopen-runtime-repro.diff`) seed group 2.

## 1. Config contract and EDS

- [x] 1.1 CF-H1: parity corpus files (RPDO 0x602, TPDO 0x80, 0x100, 0x582, 0x702, 0x7E4, 0x82 with node 2's EMCY unmoved, TIME COB-ID on a TPDO); both checks refuse with the service named; docs/config.md.
- [x] 1.2 CF-H2: corpus files for a startup SDO on 0x1010 and 0x1011 and an untriggered write SDO variable on them; both refuse with the store/restore pointer; a triggered write variable loads; docs/config.md.
- [x] 1.3 CF-M1: v1 overlap check in `contract.py` (state/boot error on one byte, a TPDO entry twice, two RPDO entries on one location); corpus files.
- [x] 1.4 CF-M3: JSON integers above 2^53 refused on both sides; corpus files for an UNSIGNED64 SDO value and a J1939 `source_name`.
- [x] 1.5 CF-M4 and lows: `parse_numbers` follows `additionalProperties`/`patternProperties`; `fullmatch`, no `strip`, `"-0"` and NaN/Infinity refused; corpus files.
- [x] 1.6 CF low: clash check after `resolve_auto_cob_ids` in the plugin; test with node 2 TPDO 6 `auto` and node 3 TPDO 1 on 0x682.
- [x] 1.7 CF-M2, CF-M5 and lows: bare `$NODEID` rewrite, Lely-refused DataTypes refused on the PC, empty `DefaultValue` as 0, integer REAL defaults, `SupportedObjects` cap; EDS-level corpus entries checked against `canopen_check`.
- [x] 1.8 CF low: master heartbeat consumer time from `heartbeat_timeout_ms` in `dcf_gen` and `dcfexport.master_input`; test with heartbeat 3 / timeout 10.
- [x] 1.9 CF low: `simfile` refuses `random_walk` min > max and `*_ms` above 2147483647; corpus files.

## 2. CANopen runtime and gateway

- [x] 2.1 CR-H1: `bughunt_gateway_field_restart_keeps_route` test; `ServiceGateway()` at the end of `Start`, periodic route resync on the supervision tick.
- [x] 2.2 CR-M1: `bughunt_gateway_hold_on_upper_reset_node` test plus a slave session restart case; baseline after `OnRestored` and at session start, forward only upper writes.
- [x] 2.3 CR-M2: `bughunt_stop_all_nodes_forgotten_on_restart` test; `RunState::master_stopped`, applied in `Start`.
- [x] 2.4 CR-M3: `bughunt_reset_during_network_stop` and `bughunt_gateway_release_during_network_stop` tests; network hold kept through `ResetNode`, `UpperLoss(true)` gives the network stop's hold.
- [x] 2.5 CR lows: gateway hold refused on the command byte, reset, operator and CiA 309-3 paths (force overrides in diagnostics); `HandleBoot` `node_op` after the hold check; tests.
- [x] 2.6 CR low: scan watchdog trip in `RunState`, cleared only when the scan moves or at PLC stop; test with a hung scan and one interface going down.
- [x] 2.7 CR lows: document mode 255 and `FilterStart` with unconfigured nodes in docs/plc-nmt (or the NMT page); fix the `outputs_gate.h` comment.

## 3. Plain CAN, J1939 and blocks

- [x] 3.1 JR-H2: test with a cyclic job and a queued `CAN_SEND` while the gate closes; cyclic jobs pause and resume at their period, queued frames dropped with the not-running error; spec text in docs/config.md.
- [x] 3.2 JR-M4: `scan_watchdog_ms` under `j1939` and `raw` in schema, contract, plugin and configurator; test with a J1939-only and a plain-CAN-only project.
- [x] 3.3 JR-H1: raw I/O test with a link that hangs up and fails to reopen; status and valid bits FALSE, timeouts run while retrying.
- [x] 3.4 JR-M2: J1939 `bus_lost` clears signal valid bits; test.
- [x] 3.5 JR-M1: on-change baseline at start and gate reopen; test with a trigger and no period, also paged `pages: all`.
- [x] 3.6 JR-M3, JR-L4: not-available rule (signed exempt, J1939-71 ranges) in `j1939_signal.h` and `j1939/sim.py`; shared test vectors; J1939 docs page.
- [x] 3.7 JR-L1, JR-L5: global Request of a PDU1 PGN answered to global in plugin and simulator; `J1939_REQUEST` answer destination check; tests.
- [x] 3.8 JR-L3: extended-ID ownership check on CANopen networks; test with a 29-bit TPDO COB-ID.
- [x] 3.9 JR-L2: `stcall.py` refuses big-endian signals; test.

## 4. PC tools

- [x] 4.1 PC-H1: replay loop test with a counting sender (one frame, ten frames); wait between loops, rate across loops, `--loop` under 1 s needs `--rate`.
- [x] 4.2 PC-H2: virtual bus test with SYNC from another master and a slow heartbeat; `sdo-write`, `nmt stop`, restore/configure writes and scan refused without `--force`, message names what was seen.
- [x] 4.3 PC-M1: PDO test layout with a mapping read that times out; the PDO is left out with a note (CLI and configurator).
- [x] 4.4 PC-M2: `restore --hold-preop` on a local client keeps a PRE-OPERATIONAL node there; test with the fake client.
- [x] 4.5 PC-M4: `--into-project` copies DBC and `.notes.json` files; `--force` keeps `canworks.bak-<time>`; tests on a copy of gantry-cell and the j1939 example.
- [x] 4.6 PC-M5: gs_usb listing from `GsUsb.scan()` with bus:address; test with the gs_usb fake and two device IDs.
- [x] 4.7 JR-M5, PC-M3 and lows: ASC `base`/`timestamps`, TRC 1.0/1.1 layouts and DLC check, readers raise `FormatError` (fuzz corpus from the hunt as tests), pcapng without CAN refused, dropped frames reported; docs/trace.md.
- [x] 4.8 PC lows: per-user adapter lock folder and `OSError` → `AdapterError`; `notes skeleton -o` refuses an existing file; SDO upload size mismatch aborts 0x06070010; `--sync-counter` help text.

## 5. Simulator

- [x] 5.1 SM-S1: raw runner one pass per tick and `next_in` at least one tick; `repeat` without `count` forever in both parsers; regression test like `sim_scenario_repeat_one_pass_per_tick`; docs/simulation.md.
- [x] 5.2 SM-S2: `zz_sdo_abort_pdo_mapped` test; rules apply to SDO access only; PDO traffic unaffected.
- [x] 5.3 SM-S3: `zz_set_while_powered_off` test; refused with "powered off", no hold left; comment fixed.
- [x] 5.4 SM-S4 and SM-L1: one grammar and the C++ semantics in `simfile`; shared corpus cases for spellings and first-tick values; docs table.
- [x] 5.5 SM-L2: `simfile.check_expression`; unmocked configurator test.
- [x] 5.6 SM-S5: stored LSS ID checked against taken IDs in the engine and `sim_run.cpp`; guard follows a new LSS ID; tests.
- [x] 5.7 SM lows: drive power-on on RESET NODE, CSV last index, control socket 32 lines per poll and `kMaxOut` in the loop, `.state` LSS ID range; tests.

## 6. Network surfaces

- [x] 6.1 NS-M1: Modbus server test with a pipelining client; read only while less than one frame waits, compact once per round; memory flat and throughput kept.
- [x] 6.2 NS lows: link unpaired 30 s timeout and close after a finished pair stream, failures per address, `manage` pairing delay; forwarder caps (4); tests.

## 7. Supply chain and repo

- [x] 7.1 KV-M1, KV lows: `zeroconf>=0.149.16`, `libusb>=1.0.30` on Windows, `requires-python >=3.10` in `pyproject.toml`; README and install docs.
- [x] 7.2 KV-M2: `install-bridge.sh` defaults to the pinned runtime release with a sha256 check; CI `build-plugin` uses the same pin; bridge image build checked in CI.
- [x] 7.3 KV-M3, NS-L4: top-level `permissions: contents: read` in every workflow; actions pinned by SHA with the tag in a comment; `.github/dependabot.yml` for github-actions, monthly.
- [x] 7.4 SECURITY.md (reporting and supported versions); README link.

## 8. Configurator and exports

- [x] 8.1 UI-N2: page test that clears a raw signal length; field problem, no 500; same for raw tx signals.
- [x] 8.2 UI-N3: page tests for a node ID change and a node removal with PDO links, heartbeat watches and gateway routes.
- [x] 8.3 UI-N4: page test for a network rename and removal with a Modbus bridge live list.
- [x] 8.4 UI lows: N1 null guard, N5 default rows, N6 problem wording, N7 missing HOME, N8 Plain CAN trace and Frame lab, N9 disabled reason and target sizes, online status without 502, A3/A7/C13 leftovers; checks added to the existing page tests.
- [x] 8.5 Exports: DBC EMCY COB-ID from the EDS, DCF export CiA 306 check on written lines only; tests. CODESYS TIME period 0 dropped: both checks already refuse `time_period_ms` 0 (100-3600000), so it cannot be reached.
- [x] 8.6 README for user-visible changes (refused configs, watchdog for J1939/plain CAN, J1939 not-available rule, replay `--loop`, `--into-project` backup, Python 3.10).

## 9. Hardware

- [x] 9.1 On the Pi with node 23 as mandatory with `stop_all_nodes`: power node 23 off so the master stops, take the CAN interface down and up, confirm the master and node 23 stay STOPPED and no output PDO is sent. Clean PLC start afterwards.
- [x] 9.2 From a PC USB adapter on the Pi's running bus: `sdo-write` and `nmt stop` to node 23 without `--force` are refused naming the other master.

## 10. CI time

- [x] 10.1 Compare the PR's CI wall and summed job time with the main baseline and state both in the PR body.

Hardware results (2026-10-17, Windows PC over SSH, simulated mandatory node 10 in place of a power cycle): 9.1 first failed (the master started again after the slcan0 bounce) and passed after stopped-master-stays-silent (#140). 9.2 was refused both times, and after #140 the refusal names the other master.
