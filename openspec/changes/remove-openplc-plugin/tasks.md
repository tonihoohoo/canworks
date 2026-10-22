## 0. Before starting

- [ ] 0.1 Change 1 (`add-openplc-modbus-target`) is merged and archived; rebase this branch on `main` and re-run `openspec validate remove-openplc-plugin --strict` (the device-install and configurator deltas modify change 1's requirements)
- [ ] 0.2 Inventory: list every file that includes a runtime header, uses `fake_runtime.hpp`, names `axis`, `sync_source`, `scan_watchdog_ms`, `CO402`, `editor-hook`, `install-stock`, `install-runtime` or `canworks-local-runtime` image; attach the list to the PR as the checklist for sections 1-8
- [ ] 0.3 Agree with change 3 (`add-bridge-mailboxes`) on the kept engine services (design decision 1): SDO request queue, EMCY history, frame port with send queue, receive rings and cyclic jobs, J1939 job, message and receiver slots, DM store

## 1. Engine without the plugin

- [ ] 1.1 Delete `plugin.cpp`, `scan_watchdog.*`, `runtime_version.*`, the `canworks_plugin` target, and the C interface tables and their exported functions (`can_plc_api.h`, `canopen_plc_api.h`, `canopen_plc_nmt_api.h`, `j1939_plc_api.*`, the exports and PLC-thread glue in `plc_api.cpp` and the files that fill the tables); keep the services of 0.3 compiling and unit tested
- [ ] 1.2 Delete `network_plc.cpp` and PLC-cycle SYNC; `sync_source`/`sync_cycles` handling leaves `config.cpp`; `"plc_cycle"` refused with the timer SYNC message
- [ ] 1.3 Replace `plugin_runtime_args_t`, the runtime's `IEC_*` types and its log callback with canworks' byte image and log interface; delete the table-addressed image mode in `config.cpp` and `image_io.h`; word locations refused
- [ ] 1.4 Config target rule: a config with neither `bridge` nor `codesys` refused by the bridge with the contract's message
- [ ] 1.5 `CMakeLists.txt` without `OPENPLC_ROOT`; `install-bridge.sh` and `docker/bridge/Dockerfile` without the runtime archive; delete `docker/local-runtime/runtime-sha256`; CI check that no engine source includes a runtime header
- [ ] 1.6 Tests: `fake_host.hpp` over the byte image replaces `fake_runtime.hpp` in `test/unit`, `test/sim`, `test/slave`, `test/j1939_unit`, `test/host/canopen_host.cpp`; delete `test/host/plugin_lifecycle.cpp`, `test/plc_sdo/`, `test/j1939_blocks/`, `test/stock/`, `test/docker/`

## 2. CiA 402

- [ ] 2.1 Engine: node `axis` and its checks, axis parts of `dcf_gen.*` and `network.*`, `sim_drive.*` and its hooks in `sim_engine.cpp` and `sim_file.cpp` (`drive_input`, drive settings); a profile 402 device keeps its values
- [ ] 2.2 Schema v1 and v2 (both copies): drop `axis`, `sync_source`, `sync_cycles`, `scan_watchdog_ms`; fixtures and `cases.json` follow; delete `bad/axis-*.json`
- [ ] 2.3 PC tools: delete `axis.py`, `configurator/cia402map.py`; axis output of `editorproject.py`, `declare.py`; axis rows in `targets.py`; the CODESYS report's axis line; page code in `node.js`, `identity.js`, `sim.js`, `tree.js`, `explain.js`, `app.js`, `style.css`
- [ ] 2.4 Delete `library/canworks/CO402_*.st`, `config/cia402-drive/`, `test/cia402/`, `test/drive/cia402_slave.hpp`, `test/sim_unit/sim_drive_tests.cpp`, `tools/deploy/tests/test_axis.py`, `tools/deploy/tests/data/doc/cia402-drive.json`; axis cases in the other tests; drive EDS fixtures only where unused
- [ ] 2.5 Keep and check: CiA 402 names in `standardod.py`, built-in notes and trace decoding still pass their tests

## 3. Editor side and deploy tool

- [ ] 3.1 Delete `tools/editor-hook/` with its tests and CI wiring
- [ ] 3.2 `canworks-deploy`: delete `--bundle`, `--project` upload, `--runtime`, `--allow-clash`, bundle assembly, clash check, runtime upload and snapshot clearing (`runtime.py`, `project.py`, `cli.py`); `--bridge` takes `HOST[:PORT]`, a remembered name, `link:NAME` and `local`; simulated-parts warning on `--bridge`
- [ ] 3.3 `targets.py`: drop the `openplc` (plugin) column and every plugin-only row (`ui:declarations`, scan watchdog, PLC-cycle SYNC, bit channel locations)
- [ ] 3.4 Configurator: plugin config opens read-only with **Switch to OpenPLC through Modbus** (also dropping `axis`, `sync_source`, `sync_cycles`, `scan_watchdog_ms`); delete the Variable declarations page and the CiA 402 settings; page tests follow

## 4. Library

- [ ] 4.1 Delete the `.cpp` blocks in `library/canworks/` and `library/src/*.inc`; `library/generate.py` and `build.sh` build the ST helpers and change 1's blocks only
- [ ] 4.2 `canworks-deploy library --list` and `--help` texts; library tests for the helpers on STruC++ (results equal the engine's and the tools' packing)

## 5. Device install and Devices

- [ ] 5.1 Delete `scripts/install-stock.sh`, `install-runtime.sh`, `install-runtime.ps1`; `install-bridge.sh`/`.ps1` gain `--with-openplc` and `--pinned-runtime`; remove the Docker-runtime prefix fallback and the plugin coexistence rules; script tests follow
- [ ] 5.2 `device-probe.sh`: drop the plugin object and the runtime container's canworks checks; fake-root tests follow
- [ ] 5.3 `devices/plan.py` and the Devices page: main actions of `device-install`, role question, link and discovery rows for the bridge only, no plugin rows; confirmation texts; tests
- [ ] 5.4 Release assets: drop `install-runtime.*` and `install-stock.sh`; the install lines in docs point to `install-bridge.sh`

## 6. Local runtime

- [ ] 6.1 `localruntime.py`: two containers (pinned upstream runtime image, bridge image of the tools' version in the runtime's network namespace, config volume, forced simulation); `status`, `logs`, `update`, `remove` for both; `--bridge local` and `--runtime local` for the diagnostics client
- [ ] 6.2 Delete `docker/local-runtime/Dockerfile`; keep `runtime-version` and `bootloader-version`
- [ ] 6.3 Configurator's local runtime panel and connect panel follow (start, put the project's config on the local bridge)
- [ ] 6.4 `test/local-runtime/` end-to-end test as `canopen-local-runtime` "Local runtime tested in CI"

## 7. Virtual plant example

- [ ] 7.1 Config with `bridge.openplc`; the drive node becomes a made-up conveyor device (EDS from a generator in the example, generic profile) with a set-point and an actual speed following it by a simulation expression; timer SYNC on the former PLC-cycle network
- [ ] 7.2 Editor project: remote device file, `canworks` variable list, `canworks_in`/`canworks_out`, `main` on typed variables with `CO_NMT`, `CO_SDO_READ`, `CO_SDO_WRITE`; scenarios marked as tests updated
- [ ] 7.3 CODESYS golden file and `codesys-motion` fixture without `axis`; DBC, DCF and network document goldens follow
- [ ] 7.4 `test/virtual-example/` against the bridge with the pinned runtime's Modbus master

## 8. CI

- [ ] 8.1 `ci.yml`: plugin job becomes the engine job (no runtime sources, no CiA 402 ST step); `.github/actions/build-plugin`, `.github/ci/areas.txt`, `tool-test-times.json` follow the deleted paths
- [ ] 8.2 `integration.yml`: delete the stock, docker and single-protocol jobs; add a J1939 network to change 1's OpenPLC-through-Modbus job config
- [ ] 8.3 `local-runtime.yml` (no image build; end-to-end test), `release-deploy.yml` (no local runtime image), `bridge-image.yml` (no runtime archive), `browser.yml` (configurator against the bridge with the virtual plant)
- [ ] 8.4 `runtime-watch.yml`: newest release plus upstream's Modbus master config model and the editor's remote device format and generator, with a recorded state
- [ ] 8.5 Bad-config parity corpus: word location in a bridge config, config with neither marker
- [ ] 8.6 CI time: wall and summed job time against the median of the last five green `main` runs, both in the PR, neither higher

## 9. Specs and wording

- [ ] 9.1 Scripted pass: every requirement and scenario outside this change's deltas that still names the plugin for canworks gets a MODIFIED block with the same behaviour ("the bridge", or "canworks" where any host is meant); includes `canopen-master-bringup`, `canopen-pdo-io`, `canopen-online-diagnostics`, `canopen-simulated-bus`, `canopen-slcan-adapter`, `canopen-configurator`, `canopen-editor-project` (declaration naming now for the `canworks` variable list), `canopen-device-simulator`, `toolkit-names` and the rest the pass finds
- [ ] 9.2 `test/ci` check: no spec outside `changes/archive` says "plugin" for canworks; `openspec/config.yaml` project context rewritten for the bridge
- [ ] 9.3 `openspec validate --all --strict` with the CI's OpenSpec version

## 10. Docs and release

- [ ] 10.1 Delete `docs/install-stock.md`, `docs/cia402.md`, `docs/plc-sdo.md`, `docs/plc-nmt.md` (what is still true goes into `plc-library.md`, `modbus-bridge.md`, `devices.md`)
- [ ] 10.2 README (features, install, quick start, limits: no long SDO, raw CAN, J1939 or EMCY blocks until change 3, no CiA 402, no PLC-cycle SYNC), `config.md`, `configurator.md`, `deploy.md`, `devices.md`, `development.md`, `diagnostics.md`, `local-runtime.md`, `modbus-bridge.md`, `plc-library.md`, `raw-can.md`, `j1939.md`, `simulator.md`, `standards.md`, `tour.md` (conveyor chapter, screenshots), `codesys.md`, `node-red.md`, `pc-adapter.md`, `network-docs.md`, `remote-access.md`, `wording.md`; tour label test passes
- [ ] 10.3 Banned-word check on the branch (`scripts/check-banned-words.py --files` and `--range`)
- [ ] 10.4 Tools minor version bump with release notes naming what was removed
- [ ] 10.5 Archive the change on the branch before asking for merge

## 11. Hardware (Linux device with the real node)

- [ ] 11.1 One-off bench cleanup (design decision 10): plugin out of the managed Docker runtime (bind, `PYTHONPATH`, `plugins.conf` line), runtime container recreated, plugin files removed; record what was done in project files, not in the repo
- [ ] 11.2 Devices page on the hardware project: **Install the bridge X** next to the pinned runtime, `canworks-bridge@<project>` owns the CAN interface, node OPERATIONAL
- [ ] 11.3 Editor Build and upload of the generated project: values both ways, `canworks_ok` TRUE, `CO_SDO_READ` of 0x1018:1, `CO_NMT` stop and start; then a clean PLC start
- [ ] 11.4 Local runtime on the Mac and on the Windows PC: `start`, virtual plant config with `--bridge local`, editor upload, nodes OPERATIONAL, `update`, `remove --data`
