## 0. Order

- [ ] 0.1 Apply after `rename-to-canworks` has merged; rebase this branch on the renamed `main` (paths below use the new names).

## 1. Config and schema

- [ ] 1.1 Extend `schema/canopen.v2.schema.json` (and the packaged copy) with `protocol` and the `j1939` object; add `examples/j1939/canopen.json` and `examples/j1939/machine.dbc` with proprietary PGNs only; verify both validate and existing examples still do.
- [ ] 1.2 Plugin config: parse `protocol` and `j1939` into a `J1939Config` (new `plugin/src/j1939/config.*`), every check from `j1939-config` and design Decision 10, J1939 locations in the cross-network clash check; verify with C++ unit tests, one per rejection message.
- [ ] 1.3 PC tools contract: the same checks in Python with shared fixtures (`test/fixtures/config/cases-j1939.json`) used by both C++ and Python tests; writers pick version 2 for J1939.

## 2. Runtime J1939 engine

- [ ] 2.1 Kernel socket wrapper (`plugin/src/j1939/socket.*`): RX socket with `SO_J1939_FILTER`, ECU socket bound to NAME/address, priority, `recvmsg` control data; map `EPROTONOSUPPORT` to the module message; verify with unit tests of the error mapping.
- [ ] 2.2 Address claim state machine (design Decision 2), with state and address locations; verify on vcan against `canworks-j1939-sim --contend` (free, lost with range, lost without range, request for claim).
- [ ] 2.3 Signal pack/unpack (little and big byte order, signed, 1..64 bits, not-available/error), unused bits 1; verify with C++ unit tests against cantools-encoded vectors stored as fixtures.
- [ ] 2.4 RX path into the process image, source filters (address, NAME with mask), timeouts and status bits; TX path from the output snapshot (period, on change, min gap, TP over 8 bytes); request answers and NACK; periodic requests; verify on vcan with the simulator (values both ways, 1785-byte TP, request round trip, timeout bit).
- [ ] 2.5 Bus loss and recovery (interface down, slcan unplug, bus-off) with re-claim; verify the vcan down/up case in CI.
- [ ] 2.6 Network dispatch in `canopen_plugin.cpp`/`network.*`: protocol per network, log lines; move the shared files touched here to `plugin/src/can/`.

## 3. Install

- [ ] 3.1 `install-stock.sh`: `modules-load.d` entry and `modprobe can-j1939` in native and Docker mode, with a message when the module is missing; verify in the Docker-mode stub test and the integration workflow.

## 4. Diagnostics

- [ ] 4.1 J1939 network status in the diag protocol (protocol version unchanged, new fields only) and `canworks-diag status` output; verify with a vcan test and a client test against a recorded answer.

## 5. PC tools

- [ ] 5.1 Add `can-j1939` and `cantools` dependencies; `canworks/j1939/dbcimport.py`; verify with tests on a DBC with 29-bit and 11-bit messages.
- [ ] 5.2 Deploy checks and clash check for J1939; declarations with scale/unit comments; J1939 DBC export (cantools strict round trip); verify with tests.
- [ ] 5.3 `canworks-j1939-sim` (claim, send, receive log, requests, contend, slcan and SocketCAN); verify on vcan in CI and with a python-can virtual bus in the tools tests.

## 6. Configurator

- [ ] 6.1 Protocol choice on Add network; J1939 network page (identity, Import DBC with picker, rx/tx/request tables, suggested locations); verify with page tests (build a network from the example DBC and save with no problems).
- [ ] 6.2 J1939 online view; verify with a page test against a stub status answer.

## 7. Trace

- [ ] 7.1 J1939 decoder (ID split, DBC names, claims with NAME, requests, ACK, TP sessions), frame inspector split, CLI `explain`; verify with decoder tests on a recorded vcan trace fixture.

## 8. CI

- [ ] 8.1 Area classifier in `ci_changes.py` with its path rules file and tests; gate J1939 and CANopen-only steps; put the J1939 vcan step in the vcan group with the most headroom (`modprobe can-j1939` there); state wall time against the median of the last 5 green `main` runs in the PR.

## 9. Docs

- [ ] 9.1 `docs/j1939.md` (config, DBC import, raw values and scaling in ST, simulator, module), README feature list and layout, `docs/configurator.md` J1939 section; bump the PC tools minor version.
- [ ] 9.2 Run the banned-word check on the branch.

## 10. Hardware (bench PLC; skip and leave open when it is not reachable)

- [ ] 10.1 Pi with its adapter as the PLC at 250 kbit/s on a segment without the CANopen node; a second adapter on the PC runs `canworks-j1939-sim` with the example DBC; check address claim, RX values into the PLC, TX values seen by the simulator, request round trip, and the timeout bit when the simulator stops.
- [ ] 10.2 Contention on the bench: the simulator contends for the PLC's address; the PLC moves within its range; with the range removed it reports "cannot claim" and goes silent.
- [ ] 10.3 Unplug and replug the Pi's adapter; the network re-claims and resumes. Put the bench's usual project back afterwards.
