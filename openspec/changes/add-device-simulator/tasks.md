## 1. Simulator engine core

- [ ] 1.1 Add `plugin/sim/` with the `canopen_sim` static library and CMake target linked into the plugin and a new `openplc-canopen-sim` executable target; verify both build in CI's plugin job.
- [ ] 1.2 Implement `SimDevice` on Lely `BasicSlave`: build from EDS or DCF (DCF `ParameterValue` as starting values), refuse files that fail the plugin's lint; verify with sim tests that a device from `config/rtd-sensor/rtd8.eds` boots under the plugin's master and one from a DCF answers its `ParameterValue`.
- [ ] 1.3 Add the frame-filter channel wrapper (drop, delay) and power off/on with reload from the file; verify with a sim test that the master reports the node lost and boots it again after power on.
- [ ] 1.4 Implement the store image (0x1010 save, 0x1011 load, 0x1020 kept, LSS store), keyed by node ID and file hash, in memory or in a state directory; verify store/power-cycle, not-stored, and config-check-skip scenarios in sim tests.
- [ ] 1.5 Write `docs/simulator.md` with the device model (what an EDS-driven device does and does not do) and link it from the README.

## 2. Value sources and expressions

- [ ] 2.1 Implement constant, sine, triangle, square, sawtooth, ramp, step sequence, random walk, noise, counter and CSV series sources with type conversion and clamping; verify each with unit tests on a fake clock.
- [ ] 2.2 Implement the expression parser and evaluator (operators, functions, object references across devices, stateful functions, load-time checks with positions, cycle detection, non-finite handling); verify with unit tests and a shared corpus `test/fixtures/sim/expressions.json` of valid and invalid expressions.
- [ ] 2.3 Apply the writer precedence (override, scenario set, source, model, profile default) and signal TPDO events after writes; verify with a sim test that an event-driven TPDO goes out on a source change within its inhibit time.
- [ ] 2.4 Refuse sources on master-written objects; verify the RPDO scenario in unit tests. Document sources and expressions in `docs/simulator.md`.

## 3. Profile defaults and CiA 402 model

- [ ] 3.1 Add the CiA 401 loopback and CiA 404 slow movement defaults and the switch to turn them off; verify the loopback and "no default" scenarios in sim tests with fixture EDS files.
- [ ] 3.2 Implement the CiA 402 state machine, profile position, profile velocity, homing (17, 18, 33, 34, 35, 37), cyclic synchronous position and velocity, following error with EMCY 0x8611, software and switch limits; verify enable, move and following-error scenarios in sim tests with `test/fixtures/eds/drives/servo-drive.eds`.
- [ ] 3.3 Document the defaults and the drive model with its settings in `docs/simulator.md`.

## 4. Fault injection

- [ ] 4.1 Implement EMCY once/periodic/reset, heartbeat stop/resume, self reset and NMT state change, TPDO stop/resume; verify each in sim tests against the plugin's master (status bit, EMCY history, state byte).
- [ ] 4.2 Implement SDO abort rules (read/write/both, count or until removed), answer delay and refuse-while-OPERATIONAL; verify the abort-rule scenario and that a delay beyond `sdo_timeout_ms` fails the boot with the timeout abort.
- [ ] 4.3 Implement identity and device type overrides and "forget node ID" (LSS waiting); verify the wrong-product scenario and an LSS boot assignment of a forgotten node in sim tests. Document faults in `docs/simulator.md`.

## 5. Simulation file and scenarios

- [ ] 5.1 Write `schema/canopen-sim.v1.schema.json` and the loader (version check, unknown keys, nodes, extra devices, paths relative to the file); verify with schema tests on example files and loader unit tests including the unknown-key and unknown-node errors.
- [ ] 5.2 Implement scenarios (set, override, source, fault, clear, wait, expect now/within/for, log, repeat, autostart, several at once) with results naming step, condition and value seen; verify with unit tests on a fake clock and one sim test that runs the PLC-alarm style scenario against a stand-in program in `canopen_host`.
- [ ] 5.3 Add `config/pingpong/simulation.json` and `config/rtd-sensor/simulation.json` examples; verify they pass the schema and the loader in CI. Document the file in `docs/simulator.md`.

## 6. Standalone simulator

- [ ] 6.1 Implement `openplc-canopen-sim` run mode (config, `--sim`, `--eds/--node`, `--iface`, `--setup-vcan`, start lines and event lines, clean stop on SIGINT/SIGTERM); verify with `test/simulator/run.sh` on vcan0 where the real plugin in `canopen_host` boots every simulated node.
- [ ] 6.2 Implement the real-bus checks (`--real-bus`, 1 s listen, refuse taken node IDs); verify with `test/simulator/run.sh` using vcan1 marked as "real" by a test-only override and a second simulator holding node 23.
- [ ] 6.3 Implement the control listener (7532, loopback without token, token on other addresses) and the C++ subcommands; verify `set`/`get`/`override`/`release`/`fault` in `test/simulator/run.sh`.
- [ ] 6.4 Implement `test` mode with `--junit`, `--timeout`, exit codes; verify a passing and a failing scenario in `test/simulator/run.sh` and validate the JUnit file's structure.
- [ ] 6.5 Document the command in `docs/simulator.md`, including the vcan setup and the real-bus caution.

## 7. Simulated bus in the plugin

- [ ] 7.1 Add `adapter.simulate` to `config.cpp` and `schema/canopen.v1.schema.json`; verify with unit tests (old config unchanged, simulated config validates, adapter still checked).
- [ ] 7.2 Run `Network` on a virtual controller with one `SimDevice` per configured node and the extra devices, loading `conf/canopen/simulation.json`; no link or serial access; verify with a `canopen_host` test without any CAN interface that the ping-pong program runs and its status bit is TRUE.
- [ ] 7.3 Log the simulated-bus warning at each start, add `simulated` to status, report error-active bus state; verify in plugin lifecycle tests.
- [ ] 7.4 Add the `sim_` diag ops with token/`allow_changes` rules and `not simulated` on a real bus; verify in diag tests.
- [ ] 7.5 Add the virtual-bus trace source; verify a `trace_start`/`trace_fetch` test on a simulated config sees SYNC, PDO, heartbeat and SDO frames and reports `interface: simulated`.
- [ ] 7.6 Add the 32-device CPU budget test; verify it stays under 5 % of one core on the CI runner.
- [ ] 7.7 Document `adapter.simulate` in `docs/config.md` and the `sim_` ops in `docs/diagnostics.md`.

## 8. PC tools

- [ ] 8.1 Add `simclient.py` and `openplc-canopen-diag sim` subcommands (`--runtime` and `--sim`); verify against `fake_diag.py` extended with `sim_` ops.
- [ ] 8.2 Add the Python simulation-file checks (schema, objects in EDS, master-written objects, expression grammar) and run the shared expression corpus against them; verify in deploy tool tests.
- [ ] 8.3 Bundle `simulation.json` with its EDS/DCF/CSV files in deploy, `--into-project` and `--new-project`; add the simulated-config warning and `--simulated`; verify in deploy tool tests.
- [ ] 8.4 Add `openplc-canopen-sim test --runtime` support in the Python client used by the native command's remote mode (or a `openplc-canopen-diag sim test` alias); verify a remote test run against the fake diag server.
- [ ] 8.5 Add the configurator **Simulate devices** switch and banner; verify with page tests.
- [ ] 8.6 Add the configurator Simulation view (live values, sliders and switches, overrides, source editor with expression checking, faults, extra devices, save to `simulation.json`, read-only without **Allow changes**); verify with page tests against the fake server.
- [ ] 8.7 Add the scenario list, step editor and live run state; verify with page tests.
- [ ] 8.8 Document the switch and the view in `docs/configurator.md` and the bundle changes in `docs/deploy.md`; bump the deploy tool version.

## 9. Install

- [ ] 9.1 Build and install `openplc-canopen-sim` from `scripts/install-stock.sh` (native link in `/usr/local/bin`, Docker inside the container) and remove it on uninstall; verify in `test/stock/run.sh` and `test/docker/run.sh` (`openplc-canopen-sim --version` equals the plugin version).
- [ ] 9.2 Document it in `docs/install-stock.md`.

## 10. Integration

- [ ] 10.1 Add the simulator unit tests, sim tests and `test/simulator/run.sh` to CI; verify `ci-ok` is green on the PR.
- [ ] 10.2 Update the README (feature list, layout, development build lines); verify the banned-word check passes.
- [ ] 10.3 Hardware: on the bench runtime (Docker install), switch the editor template project to **Simulate devices**, upload it with the editor's Build and upload, and confirm boot, online view, Simulation view, a scenario and trace from the PC; record the CPU load of the plugin.
- [ ] 10.4 Hardware: run `openplc-canopen-sim --real-bus` for one extra node on the bench bus next to the real device, confirm the plugin boots both, and confirm the simulator refuses the real device's node ID.
