# Tasks

Each group lands its own tests. Byte fixtures shared by the plugin and the PC tools keep the DM codec the same on both sides.

## 1. DM codec

- [x] 1.1 Fixture files under `test/fixtures/j1939-dm/`: DM1/DM2 payloads (no code, one code, five codes by BAM, CM set, lamps and flash combinations), DM3/DM11 requests with ACK/NACK, DM13 stop/start/hold, DM22, Component and Software ID, each with its expected decode and `UDINT` codes.
- [x] 1.2 `plugin/src/j1939/dm.*`: parse and build DM1/DM2, code ↔ `UDINT` (design Decision 2), DM13 field decode; unit tests against 1.1.
- [x] 1.3 `canworks/j1939/dm.py`: the same codec, lamp and FMI texts (own words); tests against 1.1.

## 2. Config and schema

- [x] 2.1 `j1939_config.*`: parse `diagnostics` (rx, dtcs, lamps/clear locations, accept_clear, dm13) with the checks and messages of "Diagnostics config"; location size, direction and clash checks; unit tests for every rejection scenario.
- [x] 2.2 `canworks.v2.schema.json` and the Python J1939 contract: the same object and messages; parity fixtures run in plugin and PC tools tests.

## 3. Plugin runtime

- [x] 3.1 Per-source DM1 store (64 codes kept, rest counted, CM count and one log line per source); `diagnostics.rx` mapping into `J1939Image` with timeout; vcan tests for "Receive DM1 into the PLC" scenarios incl. the five-code BAM.
- [x] 3.2 Own DM1: active set from the `%Q` snapshot, lamp OR, occurrence counts, previously active list, 1 s period plus rate-limited change sends, nothing before claim; vcan tests for "Send own DM1" and "Previously active codes".
- [x] 3.3 Requests and clears: DM1/DM2 answers through the reply gate, DM3/DM11 to us (ACK) and global (no ACK), `clear_location`, `accept_clear` false (NACK), DM22 NACK, unchanged NACK rule without own DM1; vcan tests for "DM requests and clears".
- [x] 3.4 DM13: suspend periodic `tx` and DM1, resume on start or 6 s after the last stop/hold, `dm13` false ignores; vcan tests for both DM13 scenarios.
- [x] 3.5 Status `dm` part and operations `j1939_dm_read` / `j1939_dm_clear` (force, busy, protocol refusal) sharing one pending-job table with the blocks; diag tests for the new scenarios of `canopen-online-diagnostics`.

## 4. PLC blocks

- [x] 4.1 `canworks_j1939_api(1)` table and export (`plugin/src/j1939/j1939_plc_api.*`, `can/plugin.cpp`); C test that the library's copy of the declarations (`library/src/j1939_common.inc`) matches the plugin header.
- [x] 4.2 `J1939_DM_READ.cpp`, `J1939_DM_CLEAR.cpp` with the handshake and error IDs 1-13; `J1939_DTC_SPLIT.st`, `J1939_DTC_MAKE.st`; library build includes them; block tests on vcan (read DM1, read DM2, clear ACK, NACK → 12, CANopen network → 10, unseen source → 13, PLC stop → 8, two tasks at once).

## 5. PC tools

- [x] 5.1 `canworks-diag dm list | read | clear` through the plugin and on a local adapter (claim 249 with own NAME, release at exit, `--force` for clear); tests with the simulator on vcan and a fake diag server.
- [x] 5.2 DBC import: DM PGNs listed as problems, `SPN` attributes read for naming; tests with a DBC defining 65226.
- [x] 5.3 Configurator J1939 page: Diagnostics section (watched ECUs, own codes with FMI picker, settings, free-location suggestion, PGN 65226 hint); browser test adding an own code and saving with no problems.
- [x] 5.4 Online view Faults panel with DM2 read and confirmed clear; browser test against the simulator.
- [x] 5.5 Located variable declarations for every diagnostics location; test for the "Watched engine" scenario.

## 6. Trace and simulator

- [x] 6.1 `bustrace/j1939.py`: DM1/DM2/DM3/DM11/DM13/DM22, ACK/NACK naming the DM, Component/Software ID, SPN names from the DBC; frame inspector explains a code's four bytes; trace tests for both scenarios.
- [x] 6.2 `canworks-j1939-sim`: scenario `dtcs` with `from_s`/`to_s`, DM1 sending, DM2 answers, DM3/DM11 with ACK, `--refuse-clear`, decoded print of received DMs; tests for both simulator scenarios.

## 7. Docs, examples, release

- [x] 7.1 `docs/j1939.md`: "Diagnostic messages" section (config, PLC value layout, blocks, clears, DM13, tools); remove the DM line from "Limits"; `docs/diagnostics.md` `dm` commands.
- [x] 7.2 README: J1939 feature bullet and limits line updated.
- [x] 7.3 `examples/j1939`: one watched ECU and two own codes (proprietary SPNs), a simulator scenario raising a code; example validates in CI.
- [x] 7.4 PC tools minor version bump.
- [x] 7.5 CI: new tests run in the existing j1939-area jobs; compare wall time and summed job time against the baseline in the PR.

## 8. Hardware (bench, when the Pi is reachable)

- [x] 8.1 PC adapter runs `canworks-j1939-sim` with a `dtcs` scenario beside the PLC on the Pi: the program sees lamps, count and codes come and go; `canworks-diag dm list` shows them through the PLC.
- [x] 8.2 The program clears the simulator with `J1939_DM_CLEAR` (DM3 and DM11) and reads DM2 with `J1939_DM_READ`; the PLC's own DM1 shows in `canworks-diag dm list` run PC-direct on the adapter.

Bench run 2026-10-10 (Pi PLC on its gs_usb bus at 500 kbit/s, simulator on a PC slcan adapter): 8.1 and 8.2 passed. The `%I` mapping followed the simulator's codes (1, 5, then 4 codes; the first code value checked), `J1939_DM_READ` read DM1 and DM2 every 5 s without error, and `J1939_DM_CLEAR` with DM11 was acknowledged each minute. The bench program's DM3 clear fell in the same scan as its own DM2 read to the same address and correctly got ERROR_ID 5, so DM3 was checked through the plugin with `canworks-diag dm clear --previous` (ACK). `dm list`, `dm read` and `dm clear` (refused without `--force`, ACK with it) worked through the PLC, and `dm list` on the PC adapter showed the PLC's own DM1.
