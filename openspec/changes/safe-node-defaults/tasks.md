## 0. Order

- [x] 0.1 Apply only after `modbus-connections` (connections, the generator for each connection) and `bridge-failure-hardening` (status byte 7 bit 0, the "When the bridge fails" docs section) are merged and archived (coordinator says when). Rebase on main and re-validate.
- [x] 0.2 At rebase, fold "Bus flag in the status block" into the archived Status block requirement's byte 7 line (MODIFIED), instead of a separate requirement.
- [x] 0.3 `faster-mailboxes`, `add-nodered-blocks` and `mailboxes-on-demand` edit the same configurator page and generator: rebase over whichever of them has landed. When `add-nodered-blocks` has merged, the Node-RED value nodes follow "PLC inputs while the bridge is lost" (task 3.4); otherwise leave that out and say so in the PR.

## 1. Bridge

- [x] 1.1 Protection check per node with output entries (heartbeat_consumer, EDS 0x1016 entry for the master, RPDO event timer from config or EDS; PDO-link consumers count) and one load warning each
- [x] 1.2 Status block byte 7 bit 1 from each network's bus state (interface down or missing, bus-off); diagnostics status names the networks
- [x] 1.3 C++ tests: warning present and absent cases; bit 1 with a simulated network (always clear) and with the bus-state source forced down in a unit test

## 2. PC tools

- [x] 2.1 `bridgecheck.py`: the same protection warning for `--check` (shared rule, parity test against the bridge's log on the fixtures)
- [x] 2.2 Configurator: Add node sets `config_check` (writable 0x1020); first output entry sets `heartbeat_consumer` (and `master.heartbeat_ms` 100 when 0) in the same undo step, never again after the user turned it off; new socketcan adapter gets `restart_ms` 100
- [x] 2.3 Problems: unprotected node with Watch the master heartbeat; adapter without `restart_ms` with Restart after bus-off (100 ms); both one undo step
- [x] 2.4 Page tests for 2.2 and 2.3, including undo and loaded files left unchanged
- [x] 2.5 Version bump (minor)

## 3. PLC side

- [x] 3.1 Schema and checks: `inputs_on_loss` (`hold` | `zero`) on OpenPLC, truST and Other PLC connections; connection row choice; out of date on change
- [x] 3.2 Generated `canworks_in` (OpenPLC, ST PLC link, PLCopen export): status, state and live-list inputs to 0 while `canworks.ok` is FALSE; other inputs per `inputs_on_loss`; `canworks.bus_ok`
- [x] 3.3 STruC++ compile tests (`test/plc_modbus`): zeroing on a frozen status counter, hold and zero, `bus_ok` from byte 7
- [x] 3.4 Node-RED value nodes follow the same rule (only when `add-nodered-blocks` has merged)

## 4. Examples and docs

- [x] 4.1 `examples/modbus-bridge`, `examples/openplc-modbus`, virtual plant: `heartbeat_consumer`, `config_check`, `restart_ms` where the EDS allow, no new warning
- [x] 4.2 `docs/modbus-bridge.md` "When the bridge fails": what each node does on a clean stop, a crash and a restart, with and without the settings, and to check 0x1029 (`error_behavior`); `docs/config.md` links from `heartbeat_consumer`, `event_timer_ms`, `config_check`, `restart_ms`; `docs/plc-library.md`: `canworks.bus_ok`, gate outputs on `canworks.ok`; `docs/configurator.md`: the new defaults and Problems
- [x] 4.3 README only if a user-visible line there changes; run `tools/deploy/tests/test_readme.py`
- [ ] 4.4 State CI wall time and summed job time against the baseline in the PR

## 5. Hardware (Linux device with node 23; needs the coordinator's OK on the Pi and Toni's typed go)

- [ ] 5.1 Without `heartbeat_consumer`: `kill -9` the bridge; node 23 stays OPERATIONAL with its last outputs (records today's behaviour)
- [ ] 5.2 With `heartbeat_consumer` true: `kill -9` the bridge; node 23 reacts per its 0x1029 within the heartbeat timeout; after the restart it is operational again
- [ ] 5.3 With `config_check` true: restart the bridge with node 23 running; the log says configuration unchanged and node 23 is not reset
- [ ] 5.4 Take the CAN interface down and up: status byte 7 bit 1 and `canworks.bus_ok` follow (slcan reports no bus-off, so bus-off itself stays with the vcan/C++ tests)
- [ ] 5.5 Clean PLC start afterwards
