## Why

Change 1 (`add-openplc-modbus-target`) makes OpenPLC reach canworks through the bridge and the runtime's own Modbus master. After it, the plugin inside the OpenPLC runtime is a second way to run the same engine that nobody should pick: it still ties canworks to the runtime's plugin interface, its I/O image tables, its upload path and its headers, which is exactly what Toni wants gone (research/modbus-only-2026-10-22.md). Toni also decided on 2026-10-22 that CiA 402 support is dropped entirely: no bench drive, not in real use, and cyclic CiA 402 needs the PLC-cycle SYNC that only the plugin had.

This is change 2 of 3. It builds on change 1's design (branch `propose/add-openplc-modbus-target`) and is applied after change 1 merges. Change 3 (`add-bridge-mailboxes`) brings back long SDO, raw CAN, J1939 and EMCY blocks over Modbus. The project is not in real use, so this is a clean cut: no legacy mode, no compatibility reading, no migration code.

## What Changes

- **BREAKING: the OpenPLC runtime plugin is deleted.** `libcanworks_plugin.so`, its entry points, the PLC glue (scan exchange, scan watchdog, PLC-cycle SYNC, `on_plc_stop` at PLC stop), the C interfaces the blocks called (`canopen_plc_api`, `canopen_plc_nmt_api`, `canworks_can_api`, `canworks_j1939_api`) and the runtime version check. Only glue and entry points go: the engine's job and receiver code behind the blocks (SDO request slots, frame send queue, receive rings and cyclic jobs, J1939 job and receiver slots, EMCY queues) stays with its tests, because change 3 builds its bridge mailboxes on it. The engine keeps running every network kind, the diagnostics channel, trace, CiA 309-3, the gateway, LSS, slaves, PDO links and simulated devices, in `canworks-bridge` and the standalone simulator.
- **BREAKING: the engine no longer uses runtime headers.** `plugin_runtime_args_t` and the runtime's `IEC_*` types are replaced by canworks' own byte image, the table-addressed image mode goes, and CMake, `install-bridge.sh`, the bridge image and CI stop downloading the runtime archive and its hash.
- **BREAKING: all CiA 402 support is deleted.** The node `axis` field (schema v1 and v2) and its checks, the axis parts of `dcf_gen` and `network.cpp`, the simulated CiA 402 drive, `axis.py` and the generated axis glue, the configurator's CiA 402 axis setting, **Map CiA 402 objects** and axis declaration lines, the `CO402_*` blocks, `config/cia402-drive/`, `test/cia402/`, the test drive slave, `docs/cia402.md` and spec `canopen-cia402-axis`. CiA 402 object names in the built-in dictionary, built-in notes and trace decoding stay: they describe devices, not drive control.
- **BREAKING: plugin configs are refused.** A config with neither `bridge` nor `codesys` is refused by the bridge, the deploy tool and the configurator's check, naming the configurator's **Switch to OpenPLC through Modbus** (from change 1), which stays the one conversion. `sync_source`, `sync_cycles` and `scan_watchdog_ms` leave the schema with `axis`.
- **Editor side deleted.** `tools/editor-hook/` (upload hook, snapshot route, Docker mode), the deploy tool's bundle assembly and upload through `/api/upload-file`, the cross-plugin address clash check and the editor upload warnings. The editor's own Build and upload carries the program and its Modbus master config; the bridge config goes to the device or the local bridge with `canworks-deploy --bridge`.
- **Device install without the plugin.** `scripts/install-stock.sh`, `install-runtime.sh` and `install-runtime.ps1` are deleted; `install-bridge.sh` (and `.ps1`) gains `--with-openplc`, which installs upstream's runtime at the pinned version first. The device probe, the Devices page and its main actions lose the plugin; link and discovery are installed with the bridge only.
- **Local runtime on the PC = upstream runtime image + bridge image.** `canworks-local-runtime` runs the pinned upstream runtime image unchanged and the released `canworks-bridge` image in the runtime container's network, with every network simulated. The `canworks-local-runtime` image is no longer built or published.
- **Library: only blocks over the bridge and pure ST helpers.** The C++ blocks of `library/canworks/` and their includes are deleted; the ST helpers and change 1's blocks stay. The ST helper requirements move into `plc-library` from the retired block specs.
- **Virtual plant example on plain PDO values.** The drive node becomes a made-up conveyor device with plain set-point and actual-speed values, the example becomes an OpenPLC-through-Modbus project, and the tour follows.
- **CI.** Plugin jobs go (`integration.yml` stock, docker and single-protocol jobs, the plugin build and its ABI checks, the CiA 402 ST tests, plugin images in releases); the browser run and the bad-config parity run against the bridge; `runtime-watch.yml` watches the Modbus master's config model and the editor's remote device format instead of the plugin ABI; CI time goes down.
- **Docs and cleanup.** README and every doc that describes the plugin, the editor hook, the stock install or CiA 402 (`install-stock.md` is deleted, `cia402.md`, `plc-sdo.md`, `plc-nmt.md` are deleted or folded into `plc-library.md`). The bench Linux device gets a one-off cleanup (plugin removed from the managed Docker runtime, bridge installed).

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `canopen-cia402-axis`: retired.
- `can-plc-frames`, `j1939-plc-blocks`, `j1939-plc-diagnostics`, `canopen-plc-sdo`, `canopen-plc-nmt`: retired; their ST helpers move to `plc-library`, the blocks return over Modbus in change 3.
- `canopen-editor-upload`, `canopen-stock-install`, `canopen-docker-install`: retired.
- `plc-library`: library contents, documentation, no plugin interface versions, ST helpers.
- `canopen-master-bringup`: PLC-cycle SYNC removed.
- `canopen-pdo-io`: scan exchange and scan watchdog removed; locations are bridge bytes.
- `canopen-networks`: one engine for every protocol, no PLC scan.
- `canopen-node-supervision`: `on_plc_stop` applies when the bridge stops.
- `canopen-config-contract`: plugin configs refused.
- `canopen-configurator`: CiA 402 pages removed, plugin configs only offer the switch.
- `canopen-editor-project`: no plugin declarations in `main`, library without plugin blocks.
- `canopen-deploy`: no runtime upload; bridge deploy and local bridge.
- `canopen-local-runtime`: stock runtime image + bridge image.
- `canopen-device-simulator`: CiA 402 drive model removed.
- `canopen-virtual-example`: example through Modbus, no axis.
- `modbus-bridge`: builds without runtime sources, runtime install with the bridge, plugin coexistence removed.
- `device-install`: probe and actions without the plugin.
- `canopen-ci`: plugin jobs removed, bridge-based runs, runtime watch of the Modbus formats.

Requirements of other specs that only call the engine "the plugin" are reworded at apply as MODIFIED blocks with the same behaviour (design decision 9).

## Impact

- Deleted code: about 4,100 lines of plugin glue and CiA 402 engine code in `plugin/src/`, about 6,900 lines of C++ library blocks, `tools/editor-hook/`, `scripts/install-stock.sh`, `install-runtime.sh/.ps1`, `docker/local-runtime/Dockerfile`, `tools/deploy/canworks/axis.py`, `configurator/cia402map.py`, the bundle and runtime upload parts of `runtime.py`, `project.py`, `cli.py`.
- Changed: engine host interface (`config.cpp`, `engine.*`, `image_io.h`, `process_image.*`, protocol runtimes, `bridge_host.*`), `CMakeLists.txt`, `install-bridge.sh/.ps1`, `docker/bridge/Dockerfile`, `localruntime.py`, `devices/` (probe, plan), `targets.py`, configurator pages, schema v1/v2 (both copies), library build, virtual-plant example, codesys fixtures.
- Tests and CI: `test/stock`, `test/docker`, `test/plc_sdo`, `test/j1939_blocks`, `test/cia402`, `test/drive`, `test/host/plugin_lifecycle.cpp`, the axis fixtures and test files go; the engine tests move from `fake_runtime.hpp` to a byte-image host; `integration.yml`, `local-runtime.yml`, `release-deploy.yml`, `runtime-watch.yml`, `ci.yml`, `browser.yml`, `.github/ci/areas.txt`.
- Docs: README, `config.md`, `configurator.md`, `deploy.md`, `devices.md`, `development.md`, `diagnostics.md`, `local-runtime.md`, `modbus-bridge.md`, `plc-library.md`, `raw-can.md`, `j1939.md`, `simulator.md`, `standards.md`, `tour.md`, `codesys.md`, `node-red.md`, `pc-adapter.md`, `network-docs.md`, `remote-access.md`, `wording.md`; `install-stock.md`, `cia402.md`, `plc-sdo.md`, `plc-nmt.md` deleted.
- Moot after this change: the runtime 4.3.2 program-sized image fix, the plugin side of "outputs zeroed on PLC stop", the editor hook work and the runtime freeze for anything but the integration test and the local runtime.
- Not in scope: mailboxes and the remaining blocks (change 3), CODESYS and Node-RED targets (unchanged apart from the axis line in the CODESYS report).
