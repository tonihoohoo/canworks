## Context

Research: research/modbus-only-2026-10-22.md (project files), sections "What to delete (change 2)", "CiA 402 removal (change 2)" and "Also take into account".

This change builds on change 1, `add-openplc-modbus-target` (branch `propose/add-openplc-modbus-target`), and is applied after it merges. From change 1 it takes as given: the OpenPLC target is a bridge config with `bridge.openplc` (`openplc_modbus` in `targets.py`); the configurator writes the editor's remote device `devices/remote/canworks.json` and the generated `canworks_in`/`canworks_out` programs; the PLC link header with the map hash; `on_client_loss: "preop"`; the ST blocks `CO_SDO_READ`, `CO_SDO_WRITE`, `CO_NMT`, `CO_NODE_LIVE` and the word helpers; the Devices actions for an OpenPLC project; **Switch to OpenPLC through Modbus** for plugin configs; the integration job with the pinned runtime's Modbus master. Change 1 leaves the plugin, its target, the editor hook, the stock install and CiA 402 in place; this change removes them.

Toni's rules that shape it: not in real use, so breaking changes are clean cuts with no aliases or migration code, only a one-off bench cleanup; CiA 402 dropped entirely (2026-10-22 17:58Z); say "Linux device", not a board name.

## Goals / Non-Goals

Goals: no canworks code inside the OpenPLC runtime and nothing that builds against its sources; no CiA 402 code, config, docs or tests; one engine host (the bridge, plus the standalone simulator); a local runtime on the PC built from upstream's image unchanged; less CI time.

Non-goals: new function blocks (change 3); changes to the CODESYS and Node-RED targets beyond dropping the axis line; a new schema version.

## Decisions

### 1. What is deleted

Plugin and PLC glue (entry points only):
- `plugin/src/can/plugin.cpp`, `scan_watchdog.*`, `runtime_version.*`, the `canworks_plugin` target in `plugin/CMakeLists.txt`.
- The C interfaces the C++ blocks called through the loaded plugin: `can_plc_api.h`, `canopen/canopen_plc_api.h`, `canopen/canopen_plc_nmt_api.h`, `j1939/j1939_plc_api.*`, and the exported functions and PLC-thread glue in `canopen/plc_api.cpp` and the other files that fill those tables (`canopen_plc_api`, `canopen_plc_nmt_api`, `canworks_can_api`, `canworks_j1939_api`).
- `plugin/src/canopen/network_plc.cpp` (PLC-cycle SYNC) and the `on_plc_stop` call from the PLC stop path (the setting stays for the bridge, decision 6).
- The table-addressed image mode in `config.cpp` and `image_io.h` (bit, byte, word, double and long tables of the runtime image).

Kept on purpose, because change 3 (`add-bridge-mailboxes`) builds its mailboxes on them: the engine's job and receiver code behind the blocks, that is the SDO request queue (`PlcRequests` in `canopen/plc_api.*`, whose exported functions alone go), the frame port with its send queue, receive rings and cyclic jobs (`can/raw/plc_frames.*`), the J1939 job, message and receiver slots (`j1939_plc_jobs.h`, `j1939_plc_msgs.*`) the per-network EMCY history (`plc_emcy.*`) and the J1939 DM store (`dm.*`), with their unit tests. They lose their C tables and stay unused by any host until change 3; renaming them away from "plc" is left to change 3, which gives them their new caller.

CiA 402:
- Node `axis` in both schema copies, its checks in `config.cpp`, the axis parts of `dcf_gen.*` and `network.*`, `plugin/src/canopen/sim/sim_drive.*` and its hooks in `sim_engine.cpp` and `sim_file.cpp` (`drive_input` fault, drive settings).
- `tools/deploy/canworks/axis.py`, `configurator/cia402map.py`, the axis output of `editorproject.py` and `declare.py`, the axis page parts of `node.js`, `identity.js`, `sim.js`, `tree.js`, `explain.js`, `app.js`, `style.css`.
- `library/canworks/CO402_*.st`, `config/cia402-drive/`, `test/cia402/`, `test/drive/cia402_slave.hpp`, `test/sim_unit/sim_drive_tests.cpp`, the axis cases in `test/sim/sim_tests.cpp` and `test/unit/unit_tests.cpp`, `test/fixtures/config/bad/axis-*.json` and their `cases.json` entries, `tools/deploy/tests/test_axis.py` and the axis parts of the other tool tests, `tools/deploy/tests/data/doc/cia402-drive.json`, `docs/cia402.md`, spec `canopen-cia402-axis`.
- Kept: the CiA 402 object names in `standardod.py`, the built-in notes of CiA 402 objects, trace decoding of those objects, and the drive EDS fixtures in `test/fixtures/eds/drives/` where a non-axis test uses them (checked at apply; unused ones go). A simulated device with profile 402 behaves like any profile without a default (objects keep their values).

Editor and runtime side:
- `tools/editor-hook/` (hook, snapshot route, Docker mode, its tests and CI).
- In the deploy tool: `--bundle`, `--project` upload, bundle assembly (`conf/canworks.json`, `conf/canworks/eds/`), the cross-plugin address clash check, the upload through `/api/login`, `/api/upload-file`, `compilation-status`, `/api/start-plc`, snapshot clearing, `--runtime NAME` uploads, `--allow-clash`, and the warnings about the editor's upload button.
- `scripts/install-stock.sh`, `scripts/install-runtime.sh`, `scripts/install-runtime.ps1`, `docker/local-runtime/Dockerfile`, `sitecustomize` and the `PYTHONPATH` entry.
- `test/stock/`, `test/docker/`, `test/plc_sdo/`, `test/j1939_blocks/`, `test/host/plugin_lifecycle.cpp`, the plugin parts of `test/local-runtime/`.

Library:
- Every `.cpp` block in `library/canworks/` and `library/src/*.inc`. Kept: the pure ST helpers (`CAN_GET_*`, `CAN_SET_*`, `CAN_J1939_*`, `J1939_GET_BITS`, `J1939_SET_BITS`, `J1939_DTC_*`, `J1939_NAME_*`) and change 1's `library/modbus/` blocks.

### 2. The engine's own image interface

The engine takes a canworks byte image instead of `plugin_runtime_args_t`: an input byte area, an output byte area and the lock the host holds while it copies, the interface `byte_image.h` already gives the bridge. Locations are bridge bytes (`%IB`/`%QB` offsets with bit numbers), as "Bridge configs are byte-addressed" already requires. `log.h` takes a canworks log callback instead of the runtime's. The test hosts (`test/common/fake_runtime.hpp`, `test/host/canopen_host.cpp` and the tests using them) move to a `fake_host.hpp` over that interface with the same cases.

The top-level `CMakeLists.txt` drops `OPENPLC_ROOT` and the runtime header check. `install-bridge.sh`, `docker/bridge/Dockerfile` and CI stop downloading the runtime archive, so `docker/local-runtime/runtime-sha256` goes; `runtime-version` and `bootloader-version` stay in `docker/local-runtime/` as the pins of the runtime installed on devices, in the local runtime and in the integration job.

Alternative: keep a thin adapter to the runtime types for a possible later plugin. Rejected: it keeps the license and ABI tie the change is for, and a plugin can be rebuilt from history.

### 3. Plugin configs are refused

The contract's target rule loses its fourth case: a config SHALL have a `bridge` or a `codesys` object. The bridge (`--check-only` included), the deploy tool and the configurator's check refuse one with neither, with "This config is for the removed OpenPLC plugin; open it in the configurator and use Switch to OpenPLC through Modbus." The configurator keeps change 1's switch as the one conversion, so a leftover config is one click from working. `targets.py` loses the `openplc` (plugin) column; `openplc_modbus` stays the OpenPLC target.

Fields removed from both schema copies: node `axis`, master `sync_source`, `sync_cycles`, and `scan_watchdog_ms` (master, J1939, raw). They become unknown fields, ignored with a warning as the contract says for unknown fields; `"sync_source": "plc_cycle"` in a config can no longer start SYNC, so the bridge refuses it with the same message the bridge gives today. The rule "removing a field needs a new `schema_version`" is broken once on purpose: the project is not in use, and a v3 would force a rewrite of every example and fixture for no reader.

### 4. Deploy tool after the plugin

`canworks-deploy` keeps its checks, the exports (DCF, DBC, Modbus map, network document, slave EDS, CODESYS, Node-RED), `--new-project` and `--into-project` (now writing change 1's remote device and generated programs), `library`, notes, and `--bridge HOST[:PORT]` (upload with `put_config` over the diagnostics channel). The simulated-parts warning moves to the bridge deploy. `--bridge local` targets the local bridge (decision 7). There is no deploy to an OpenPLC runtime any more: the editor's Build and upload sends the program and `conf/modbus_master.json`, and the runtime needs nothing else from canworks.

### 5. Device install

`install-bridge.sh` is the one install script on a Linux device. It gains `--with-openplc` (and `-WithOpenplc` in `install-bridge.ps1`): when no OpenPLC runtime is found, run upstream's installer with the pinned runtime and bootloader versions, wait until the runtime answers, then install the bridge; a failed upstream install stops before the bridge. It also takes `--pinned-runtime` (**Switch runtime to vP** on a managed Docker runtime, nothing else changed in the runtime). `--with-link` and discovery stay as the bridge already has them. The stock install's same-version skip (install stamp) was plugin-only and is not carried over: a bridge re-run rebuilds as it does today.

Devices: the probe drops the plugin object; the main actions become **Install OpenPLC Runtime and the bridge X**, **Install the bridge X**, **Install and start this project's bridge**, **Update A → X**, **Start this project's bridge**, **Switch runtime to vP** (managed Docker runtime off the pin, OpenPLC project) or Up to date. With no config open the role question stays: **OpenPLC PLC with canworks** installs the runtime and the bridge, **Modbus bridge** the bridge only. **Rebuild for runtime vN** and the plugin rows go. A device that still has an old plugin is not detected; the bench device is cleaned by hand (decision 10).

### 6. `on_plc_stop` on the bridge

The setting stays for bridge networks, with its meaning when the bridge stops or its network closes (service stop, config replaced). For an OpenPLC project, PLC stop is change 1's `on_client_loss` (with `"preop"`); the configurator keeps hiding `on_plc_stop` there.

### 7. Local runtime: upstream image + bridge image

`canworks-local-runtime start` runs two containers:
- `canworks-local-runtime`: the upstream runtime image at the pin (`runtime-version`), unchanged, publishing 8443 (runtime) and 7531 (bridge diagnostics) on `127.0.0.1`, the data volume and the real-time options as today;
- `canworks-local-bridge`: `ghcr.io/tonihoohoo/canworks-bridge:<tools version>` with `--network container:canworks-local-runtime`, so the runtime's Modbus master reaches it at `127.0.0.1:1502`, `CANWORKS_FORCE_SIMULATE=1`, and the volume `canworks-local-bridge-config` as `/etc/canworks-bridge`.

The bridge starts with an empty config and waits; `canworks-deploy --bridge local --config …` and the configurator put the project's config on it through the diagnostics channel, and the editor uploads the program to `localhost:8443` as to any runtime. `update` pulls both images for the tools' version, `remove --data` removes both containers and volumes. The `canworks-local-runtime` image is no longer built or published; older tags stay on the registry untouched.

Alternative: one image with the bridge added to upstream's. Rejected: it is again a modified runtime image to build per release and architecture, which is the coupling this change removes.

### 8. Virtual plant example

The example becomes an OpenPLC-through-Modbus project: its config gets `bridge.openplc`, the editor project gets change 1's remote device and `canworks_in`/`canworks_out`, and `main` uses the typed `canworks` variables. The drive node becomes a made-up conveyor device (own EDS written by a generator in the example, generic profile) with a speed set-point and an actual speed that a simulation expression makes follow the set-point. The network that used PLC-cycle SYNC uses timer SYNC. The SDO and NMT parts of the program use change 1's blocks. The tour's drive chapter becomes a conveyor chapter on plain PDO values; the CODESYS golden file and the `codesys-motion` fixture are rewritten without `axis` (the network-number override test keeps its two networks).

### 9. Specs

Retired whole (`retire_capabilities`): `canopen-cia402-axis`, `can-plc-frames`, `j1939-plc-blocks`, `j1939-plc-diagnostics`, `canopen-plc-sdo`, `canopen-plc-nmt`, `canopen-editor-upload`, `canopen-stock-install`, `canopen-docker-install`. Their ST helper requirements move to `plc-library`; the device probe script moves to `device-install`; the runtime install moves to `modbus-bridge`.

Behaviour changes have their own delta blocks in this change. Many other requirements (`canopen-master-bringup`, `canopen-pdo-io`, `canopen-online-diagnostics`, `canopen-simulated-bus`, `canopen-slcan-adapter`, `canopen-configurator`, `toolkit-names` and others) call the engine "the plugin" with behaviour that stays. At apply, a scripted pass lists every remaining requirement and scenario that names the plugin, and each gets a MODIFIED block with the same behaviour and "the bridge" (or "canworks" where the text is about any host); a test in `test/ci` fails when a spec outside `changes/archive` still says "plugin" for canworks. `openspec/config.yaml`'s project context is rewritten for the bridge.

### 10. Bench cleanup on the Linux device

One-off, by hand during the hardware tasks, no code: remove the plugin from the managed Docker runtime (the `/opt/canworks` bind, the `PYTHONPATH` entry and the `plugins.conf` line in the bootloader's runtime spec), recreate the runtime container, delete the plugin files under `/opt/canworks`, install the bridge with the hardware project's config, and check a clean PLC start.

### 11. CI

- `ci.yml`: the plugin job becomes the engine job (build without runtime sources, unit, virtual-bus and simulator tests, bridge tests, change 1's OpenPLC Modbus tests); the CiA 402 ST test step and the STruC++ cache key text change (STruC++ stays for the library and change 1's tests).
- `integration.yml`: the stock, docker and single-protocol jobs go; change 1's OpenPLC-through-Modbus job stays and covers the single-protocol builds' purpose with a J1939 network added to its config.
- `local-runtime.yml`: no image build; an end-to-end test of `canworks-local-runtime` with the pinned upstream image and the bridge image built in the job.
- `release-deploy.yml`: the local runtime image jobs go; the bridge image stays.
- `runtime-watch.yml`: watches upstream's `modbus_master` config model, the editor's `devices/remote` format and its Modbus master generator, besides the newest release.
- `browser.yml`: the configurator against the bridge running the virtual plant.
- `.github/ci/areas.txt`, `tool-test-times.json` and the `build-plugin` action follow the deleted paths. The PR states wall and summed job time against the median of the last five green `main` runs.

## Risks / Trade-offs

- Lost until change 3: long SDO, raw CAN, J1939 and EMCY blocks in the program. Accepted by Toni; change 3 brings them back over Modbus.
- Lost for good: cyclic CiA 402 and PLC-cycle SYNC. Accepted (no drive, not in use).
- Large deletion in one PR: reviewed by area in the commit order of the tasks; the test suite and change 1's integration job are the safety net.
- Wording pass over many specs: mechanical but long; guarded by the spec wording test.
- The local runtime's two containers share one network namespace; engines that cannot do `--network container:` (none known among Docker and Podman) would fail at start with a clear message.

## Migration Plan

None in code. Leftover plugin configs open in the configurator with the switch. The bench Linux device is cleaned by hand (decision 10). Old `canworks-local-runtime` images and containers on a PC: `canworks-local-runtime update` recreates the container from the upstream image on the same data volume.

## Open Questions

None. CiA 402 dropped and the three-change split decided by Toni on 2026-10-22.
