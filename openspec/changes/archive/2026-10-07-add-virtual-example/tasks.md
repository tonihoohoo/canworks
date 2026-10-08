## 1. Simulation file version 2

- [x] 1.1 Add `schema/canopen-sim.v2.schema.json` (top-level `tick_ms`, `networks` keyed by name with the version 1 `nodes`, `extra_devices`, `scenarios`); keep v1; verify both schemas validate their examples in the contract tests.
- [x] 1.2 Plugin: load version 2 in `sim_config.cpp`, apply each section to its network's simulated devices (sources, faults, drive settings, extra devices, autostart scenarios), refuse unknown network names, keep the v1 warning for several networks naming version 2; verify with sim tests on a two-network config (sine on one network only, extra device found by LSS on its own network only, autostart scenario listed per network).
- [x] 1.3 Deploy tool: `simfile.py` checks per section with the network in each message, `deploy` bundle carries the file unchanged; verify with unit tests for unknown network, per-network EDS check and v1 still valid on `config/rtd-sensor`.
- [x] 1.4 Configurator: Simulation view reads and saves the section of the picked network, keeps other sections, offers v1 to v2 conversion for several networks; verify with API and page tests.

## 2. Gateway self-loop

- [x] 2.1 Add a sim test with a gateway whose upper slave network shares a simulated bus with a master network of the same config (field network first): node 20 OPERATIONAL from the stand-in master, routes up and down, field node status, EMCY forwarding, SDO bridge read, upper loss when the stand-in master stops; fix whatever it finds.

## 3. Example project

- [x] 3.1 Write `make_eds.py` for DIO-16 (made-up CiA 401 module: 16 DI, 16 DO, 2 AI, 2 AO, 0x1010/0x1011, 0x1014, 0x1020, LSS, writable mapping); verify the EDS passes the strict lint.
- [x] 3.2 Write the example config (`io`, `motion`, `cell`, `host` on `sim0`-`sim2`, all simulated, diagnostics with a token verifier and changes allowed), the slave description and its generated EDS; verify `openplc-canopen-deploy` check passes with no warnings beyond the expected simulation notice.
- [x] 3.3 Generate the editor project with `--new-project --sdo-blocks --task-interval T#10ms`, add the demo program (temperature scaling and alarm, I/O loopback, drive sequence, SDO blocks, NMT restart, reactions to status, PDO timeout and EMCY, gateway status, the host master's controller role); verify it compiles with STruC++.
- [x] 3.4 Write the version 2 `simulation.json`: waveforms on RTD-8, a formula, an autostart fault timeline, an extra device without node ID, and `test` scenarios that check the program's reactions (alarm, fault output, gateway status, drive sequence end).
- [x] 3.5 Add `examples/virtual-plant/README.md` (what each network shows, file list).

## 4. CI

- [x] 4.1 Add `test/virtual-example/run.sh`: check and exports (HTML, DCF, DBC), STruC++ compile, deploy with `--runtime local` to the image, every configured node OPERATIONAL incl. node 20 on `host`, gateway status, `openplc-canopen-diag sim test --network` per network with JUnit; run it as a step of the amd64 job in `local-runtime.yml` (which builds the image) with `examples/**` in its path filter.

## 5. Docs

- [x] 5.1 Write `docs/tour.md` (install, configurator and checks with a deliberate mistake, exports, editor upload and debugger, online diagnostics and parameters, simulation and faults, LSS, motion, slave and gateway, trace with trigger, frame inspector and export, raw frames, scenario tests, and the "needs hardware" section) with a few screenshots from the configurator against the example.
- [x] 5.2 Update `docs/simulator.md` (version 2 file), `docs/configurator.md` (Simulation view per network), `docs/local-runtime.md` (link to the tour) and README (tour and example first in the docs list, Layout block, simulation file v2).
- [x] 5.3 Bump the deploy tool minor version (next free at apply time).

## 6. Checks by hand (no CAN hardware needed)

- [ ] 6.1 Follow `docs/tour.md` on macOS with Colima: every chapter as written, editor Build and Upload to `localhost:8443`.
- [ ] 6.2 Follow the install and editor chapters on Windows with WSL2.
