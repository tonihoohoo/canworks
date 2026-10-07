# Tasks

## 1. Config and schema

- [x] 1.1 Parse `role` and `slave` in version 2 networks (node ID or null, EDS, objects, inputs_on_loss, status and EMCY locations), with the misplaced-key and version 1 errors; verify with new cases in `test/fixtures/config/cases-v2.json`.
- [x] 1.2 Check bindings against the EDS (object exists, access type to direction, `const`/`wo` refused, location area and size) and include slave locations in the cross-network overlap check; verify each error message in config tests.
- [x] 1.3 Extend `schema/canopen.v2.schema.json` with the slave network and add `config/slave/` (generated EDS, config, short ST program); verify the schema test validates it.

## 2. Slave device in the plugin

- [x] 2.1 Extract the `SlaveDevice` base from the simulator's `SimDevice` (EDS load, store image with a backend, LSS hooks, SDO indications, `Changed()`, conflict guard) and move `SimDevice` onto it; verify the simulator's sim tests still pass. (Done in that order: the base landed in `plugin/src/slave_device.*` first, and once the simulator was on main its `SimDevice` moved onto it, with options for Lely's autostart and LSS bit timing so a simulated device still behaves like a free-standing one; all sim tests pass.)
- [x] 2.2 Add `PlcSlave` and `SlaveImage`: input path from RPDO and SDO indications, output path every 1 ms and before SYNC sampling, TPDO events, `inputs_on_loss`; verify with sim tests where the plugin's own master runs against the plugin's slave on a virtual bus (RPDO -> %I, %Q -> event and synchronous TPDO, SDO to a bound object, master remaps a TPDO).
- [x] 2.3 Run slave networks in their own bus session next to master networks, with start-up logging; verify a sim test with one master and one slave network in one config.
- [x] 2.4 Status locations (state, comm OK, SYNC count) and EMCY from the program; verify lost master heartbeat, NMT stop and EMCY raise/clear in sim tests.
- [x] 2.5 State file for 0x1010/0x1011, 0x1020 and LSS store, keyed by network and EDS hash; verify save, PLC restart, load, changed EDS and LSS assignment in sim tests.
- [ ] 2.6 Shared simulated bus: a master network and a slave network with `adapter.simulate` and the same `interface` run on one virtual bus; verify with a sim test of the plugin's own master booting its own slave there, and the two-masters rejection in config tests. (Waits for the device simulator change, which brings `adapter.simulate`; the sim tests here put both on one in-process virtual bus already.)
- [ ] 2.7 vcan test: master network on `vcan0`, slave network on `vcan1`, the two joined with a `cangw` route, in one config (`test/slave/run.sh`) in CI.

## 3. EDS generator and deploy tool

- [x] 3.1 `slaveeds.py` with the manufacturer and CiA 401 layouts, default PDO packing, identity hash; verify with unit tests, including lint with `eds_lint: "all"` on every generated file.
- [x] 3.2 `openplc-canopen-deploy slave-eds` and slave networks in `contract.py`, bundle and `--check`; verify with deploy tool tests.
- [x] 3.3 Declarations and editor project for slave bindings and status locations; verify with tests on `config/slave`.

## 4. Configurator and diagnostics

- [x] 4.1 Role switch, slave device page, object list editor with generate and bind, Export EDS; verify with the configurator's server tests.
- [ ] 4.2 Slave status in the diagnostics channel and the online view, local OD reads, master-only ops refused; verify with diag tests against the sim slave.

## 5. Docs, install, release

- [x] 5.1 `docs/slave.md`, `docs/config.md` slave section, configurator and deploy docs, README feature list and layout.
- [x] 5.2 State directory in `install-stock.sh` for native and Docker installs; verify with the Docker install test.
- [x] 5.3 Deploy tool minor version bump.

## 6. Gateway

- [x] 6.1 Parse and check the `gateway` section (upper slave network, route ends exist, direction, types, one writer, at least one field network); verify each error in config tests and add `config/gateway/` with a schema-valid example.
- [x] 6.2 Route slots between the bus threads with eventfd wakes; verify with a sim test (upper master, gateway slave + field master, simulated field device on separate simulated buses) that values go up and down within 2 ms and keep flowing while the test program blocks one scan for 100 ms.
- [x] 6.3 Field node status record and operational bit field; verify node loss and recovery in the sim test.
- [x] 6.4 EMCY forwarding with combined 0x1001; verify forward, field reset and the program's own EMCY together.
- [x] 6.5 `on_upper_loss` hold, zero and stop_nodes; verify each in sim tests.
- [x] 6.6 SDO bridge record (read, write with opt-in, abort, busy) on the PLC SDO request path; verify in sim tests including a write refused without `sdo_bridge_write`.
- [x] 6.7 EDS generator input from the gateway section, `slave-eds --gateway`; verify with unit tests and lint.
- [ ] 6.8 Configurator gateway page (routes table picking slave objects and field PDO entries, status, EMCY, loss and bridge options) and gateway status in the diagnostics channel (route counts, last update age); verify with server and diag tests. Document in `docs/gateway.md` and the README.

## 7. Hardware (the current Pi setup, vcan and simulation)

- [ ] 7.1 On the Pi with its current setup (CAN adapter on `can0`, the template project's network and its real node), deploy a config that keeps that network and adds a master network on `vcan0` and a slave network on `vcan1` joined by `cangw`, with a PLC program that loops values through both; check slave boot, remap by the master, PDOs both ways, heartbeat loss (route removed and restored), store across a PLC restart, and that the template's node stays operational throughout.
- [ ] 7.2 Same on the Pi with the master and slave networks simulated on one bus (`adapter.simulate`, shared `interface`), plus a simulated device from the simulator on the master network; check the same points and the PLC scan time against the template project alone.
- [ ] 7.3 Gateway on the Pi: the template's network on `can0` as the field network with its real node, the gateway slave on `vcan1`, and an upper master network on `vcan0` joined by `cangw`; route the real node's values up and a value down, check status and EMCY forwarding (EMCY from the real node or a simulated device) and `on_upper_loss`, and an SDO bridge read of the real node's identity.
- [ ] 7.4 Put the template project back on the Pi and check its node is operational.
