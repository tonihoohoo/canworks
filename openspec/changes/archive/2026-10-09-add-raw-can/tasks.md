## 0. Order

- [x] 0.1 Apply after `add-j1939-ecu` has merged; rebase this branch on that `main` and adjust paths if its core layout differs from design Decision 1. Rewrite the `canopen-networks` delta against the merged "Network list" text.

## 1. Config and schema

- [x] 1.1 Extend `schema/canworks.v2.schema.json` (and the packaged copy) with protocol `none`, `adapter.listen_only` and `raw`; add `examples/raw-can/canworks.json`, `examples/raw-can/cab.dbc` and `examples/raw-can/cab.sim.json` with made-up identifiers; verify they and every existing example validate.
- [x] 1.2 Plugin config: parse `raw` on every network and protocol `none` (`plugin/src/can/raw/config.*`), every check in `can-raw-messages` (ranges, masks, DLC and signal fit, unique TX identifiers, timing needed, listen-only rules, misplaced keys), protocol ownership through the protocol registration (CANopen `cob_id_use()`, J1939 source address), raw locations in the clash check; verify with C++ unit tests, one per rejection message.
- [x] 1.3 PC contract: the same checks in Python from shared fixtures (`test/fixtures/config/cases-raw.json`); writers save version 2 for raw or `none`; verify with the shared fixture tests.

## 2. Runtime raw path

- [x] 2.1 Move signal packing to `plugin/src/can/signals.*` with the fill rule parameter; J1939 and raw use it; replace the J1939 packing tests with one shared fixture test (cantools vectors) so the test count does not grow.
- [x] 2.2 Raw thread for real interfaces: CAN_RAW socket, filter rebuild, own-message echo for confirmation, timestamps, 1 ms timer, retry on missing/down/bus-off; verify on vcan (filter rebuild, echo confirmation) in the existing vcan group with the most headroom.
- [x] 2.3 Simulated bus: raw engine driven from the bus thread through the tap and injector; minimal core bus thread for a simulated `none` network; verify with simulated-bus tests (RX into the process image, TX timing).
- [x] 2.4 Config RX: matching with masks, locations through the process image, counter, id/dlc/data locations, timeout and status bit, short frames; config TX: period, on change with min gap, trigger edge, enable bit, fill, remote frames, start and stop with the PLC; verify with simulated-bus tests for every scenario in `can-raw-messages`.
- [x] 2.5 Listen-only: ctrlmode on SocketCAN, silent mode on slcan (reuse the sweep's code), log where it cannot be set, refuse every send; verify with unit tests of the refusal paths.
- [x] 2.6 Log line per network with raw message counts; plain network log line; verify in the config tests' log assertions.

## 3. PLC block interface and library

- [x] 3.1 `plugin/src/can/can_plc_api.h` and `canworks_can_api(1)`: receivers (rings, depth, drop count), TX ring with confirmation and timeout, cyclic jobs, bus info, generation handles, cancel on PLC stop and network restart, limits; verify with C++ tests that call the table from a test "scan" thread on the simulated bus.
- [x] 3.2 `library/generate.py`: the four `CAN_*` C++ blocks with a shared `library/src/can_common.inc`; header-agreement check like `test/plc_sdo`; verify with the generator `--check` and a compile of the generated blocks against the header.
- [x] 3.3 ST helper functions in the library project (`CAN_GET_BITS`, `CAN_SET_BITS`, byte helpers, J1939 identifier helpers); verify they compile in the existing library build step and, with strucpp's test runner if it has one, against the shared packing fixtures; otherwise through a tiny C++ harness on the generated code.
- [x] 3.4 Rename `--sdo-blocks` to `--blocks` in `canworks-deploy` and its docs; verify with the existing editor project tests updated.

## 4. Diagnostics

- [x] 4.1 Raw status fields and the plain network status; raw send identifiers in the `send_frame` guard map; verify with simulated-bus diag tests and a client test against a recorded answer.
- [x] 4.2 `replay` / `replay_stop` ops with guards and limits, `canworks-diag replay` (channel and `--adapter`, `.asc`/`.trc`/trace input, `--rate`, `--loop`); verify with a simulated-bus replay test and a python-can virtual bus test for `--adapter`.

## 5. PC tools

- [x] 5.1 `canworks/raw/`: DBC import (reusing the J1939 cantools import), DBC export of raw messages with round-trip test, declarations with scale/unit comments; verify with tests on the example DBC.
- [x] 5.2 Trace decode of raw messages (config or DBC), frame inspector field marks, `explain`; verify with decoder tests on a recorded simulated-bus trace.
- [x] 5.3 Simulator `raw_devices` (send with value sources, replies, scenario stop, wrong DLC) on the simulated bus and in the standalone simulator; verify with simulator tests.

## 6. Configurator

- [x] 6.1 Plain CAN on Add network, Listen only switch, CAN messages page (tables, signal rows, bit grid, Suggest addresses, override switch), Import DBC dialog; verify with page tests (build the example network from its DBC and save with no problems).
- [x] 6.2 Raw rows in the online view, Copy as ST call for raw messages; verify with page tests against a stub status answer.

## 7. CI

- [x] 7.1 Area classifier: raw paths count as `shared`; no new job; state wall time and summed job time against the baseline (median of the last 5 green `main` push runs with code changes) in the PR and pay for any increase in the same PR.

## 8. Docs

- [x] 8.1 `docs/raw-can.md` (plain networks, raw messages, listen-only, blocks with examples, what `DONE` means per adapter, replay, simulator), README feature list and layout, `docs/configurator.md` CAN messages section; bump the PC tools minor version.
- [x] 8.2 Run the banned-word check on the branch.

## 9. Hardware (bench PLC; skip and leave open when it is not reachable)

- [x] 9.1 Pi adapter as the PLC on the CANopen bench network with one raw send and one raw receive message next to the CANopen node; the PC adapter plays a plain CAN device with `canworks-sim`; check values both ways, the node still boots and runs, and the timeout bit when the PC device stops.
  - 2026-10-09: passed with `cansend` on the Pi host playing the plain CAN device (the PC adapter is on another computer).
- [x] 9.2 Program blocks on the bench: `CAN_SEND` confirmation, `CAN_SEND_CYCLIC` at 10 ms with a 50 ms scan (period checked in a PC trace), `CAN_RECEIVE` draining a burst, `CAN_BUS_INFO` after unplugging the other adapter (error passive or bus-off).
  - 2026-10-09 retest after fix-raw-can-hw-findings: passed (cyclic period 10.00 ms average).
  - 2026-10-09 unplug (other device's cable pulled): the bus went error passive (not bus-off, as expected without acknowledgement) and every block recovered by itself after the replug. Found and fixed: `CAN_SEND` ended with `ERROR_ID` 5 on a full kernel queue, and `TX_ERRORS`/`ERROR_FRAMES` stayed 0 on an adapter without driver counters. Bus-off itself is not tried.
  - 2026-10-09 unplug retest after those fixes: `CAN_SEND` ends with 6, error frames counted, recovery as before; `TX_ERRORS` stayed 0 because gs_usb sets the counters without CAN_ERR_CNT (fixed after the run).
- [ ] 9.3 Listen-only plain network on the Pi: the PC adapter sends, the PLC receives, and a PC trace shows no acknowledgement or frame from the Pi when the PC adapter is the only other device. Put the bench's usual project back afterwards.
  - 2026-10-09: listen-only mode set, frames received, nothing sent, program sends refused. The "no acknowledgement" part needs a bus where the PC adapter is the only other device.
