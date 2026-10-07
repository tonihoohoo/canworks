# Tasks

## 1. Config and schema

- [ ] 1.1 Parse `role` and `slave` in version 2 networks (node ID or null, EDS, objects, inputs_on_loss, status and EMCY locations), with the misplaced-key and version 1 errors; verify with new cases in `test/fixtures/config/cases-v2.json`.
- [ ] 1.2 Check bindings against the EDS (object exists, access type to direction, `const`/`wo` refused, location area and size) and include slave locations in the cross-network overlap check; verify each error message in config tests.
- [ ] 1.3 Extend `schema/canopen.v2.schema.json` with the slave network and add `config/slave/` (generated EDS, config, short ST program); verify the schema test validates it.

## 2. Slave device in the plugin

- [ ] 2.1 Extract the `SlaveDevice` base from the simulator's `SimDevice` (EDS load, store image with a backend, LSS hooks, SDO indications, `Changed()`, conflict guard) and move `SimDevice` onto it; verify the simulator's sim tests still pass.
- [ ] 2.2 Add `PlcSlave` and `SlaveImage`: input path from RPDO and SDO indications, output path every 1 ms and before SYNC sampling, TPDO events, `inputs_on_loss`; verify with sim tests where the plugin's own master runs against the plugin's slave on a virtual bus (RPDO -> %I, %Q -> event and synchronous TPDO, SDO to a bound object, master remaps a TPDO).
- [ ] 2.3 Run slave networks in their own bus session next to master networks, with start-up logging; verify a sim test with one master and one slave network in one config.
- [ ] 2.4 Status locations (state, comm OK, SYNC count) and EMCY from the program; verify lost master heartbeat, NMT stop and EMCY raise/clear in sim tests.
- [ ] 2.5 State file for 0x1010/0x1011, 0x1020 and LSS store, keyed by network and EDS hash; verify save, PLC restart, load, changed EDS and LSS assignment in sim tests.
- [ ] 2.6 vcan test: plugin master on one socket and plugin slave on another socket of `vcan0` (`test/slave/run.sh`) in CI.

## 3. EDS generator and deploy tool

- [ ] 3.1 `slaveeds.py` with the manufacturer and CiA 401 layouts, default PDO packing, identity hash; verify with unit tests, including lint with `eds_lint: "all"` on every generated file.
- [ ] 3.2 `openplc-canopen-deploy slave-eds` and slave networks in `contract.py`, bundle and `--check`; verify with deploy tool tests.
- [ ] 3.3 Declarations and editor project for slave bindings and status locations; verify with tests on `config/slave`.

## 4. Configurator and diagnostics

- [ ] 4.1 Role switch, slave device page, object list editor with generate and bind, Export EDS; verify with the configurator's server tests.
- [ ] 4.2 Slave status in the diagnostics channel and the online view, local OD reads, master-only ops refused; verify with diag tests against the sim slave.

## 5. Docs, install, release

- [ ] 5.1 `docs/slave.md`, `docs/config.md` slave section, configurator and deploy docs, README feature list and layout.
- [ ] 5.2 State directory in `install-stock.sh` for native and Docker installs; verify with the Docker install test.
- [ ] 5.3 Deploy tool minor version bump.

## 6. Hardware

- [ ] 6.1 On the Pi, run a slave network under a second master on the bench (another controller or a PC master tool) over a real wire: boot, remap, PDO exchange both ways, heartbeat loss, store across a PLC restart.
