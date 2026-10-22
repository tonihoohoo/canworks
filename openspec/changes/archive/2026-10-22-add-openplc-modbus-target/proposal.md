## Why

The canworks plugin lives inside the OpenPLC runtime: it uses the runtime's plugin interface, its I/O image tables and a hook in its upload path. Every runtime release can break it. The next one (v4.3.2) sizes the I/O image from the program and would leave canworks off on ordinary projects, and v4.3 already changed what outputs do on stop. Toni wants canworks to stop depending on runtime internals (research/modbus-only-2026-10-22.md).

The Modbus TCP bridge already runs every network kind with the same engine, the diagnostics channel, trace and CiA 309-3. OpenPLC Runtime v4.3.1 ships its own Modbus master, configured from the OpenPLC Editor's remote devices and carried to the runtime by the editor's normal Build and upload. So OpenPLC can reach canworks through Modbus with nothing of canworks inside the runtime.

This is change 1 of 3: make OpenPLC a Modbus target. Change 2 (`remove-openplc-plugin`) deletes the plugin and all CiA 402 support. Change 3 (`add-bridge-mailboxes`) brings back the remaining function blocks over Modbus.

## What Changes

- **OpenPLC target = bridge config with `bridge.openplc`.** A config with a `bridge` object that holds an `openplc` object targets OpenPLC through Modbus. The bridge then listens on `127.0.0.1:1502`, only `127.0.0.1` may write, words are low word first (the runtime's Modbus master order), and `poll_ms` (default 10) sets the Modbus master's poll period.
- **The configurator writes the editor's remote device.** Saving an OpenPLC project writes `devices/remote/canworks.json` in the editor project: one Modbus TCP device at `127.0.0.1:1502` with one read or write group per PDO (merged up to the Modbus limits), each point named after its canworks value. The editor's own Build and upload carries it as `conf/modbus_master.json`. No other editor file is touched by Save. Saving while the editor has the project open warns that the editor may write its own copy back.
- **Typed, named values in the program.** New editor projects (and **Update declarations**) get a `canworks` global variable list with typed values (BOOL, INT, DINT, REAL…) and two generated programs, `canworks_in` (first in the task) and `canworks_out` (last), that convert between those values and the raw Modbus words. 32-bit values are rebuilt from two words, REAL through a library helper.
- **PLC link header.** Output registers 0-2 carry a "PLC running" word and the 32-bit **map hash** of the bridge's register layout, written by `canworks_out` every scan. The bridge computes the same hash from its config and serves it at input registers 0-1, followed by its status block. The bridge accepts output writes only while the last header matched its hash and said running. A header with running 0 (OpenPLC's stop round writes zeroed outputs) enters outputs off at once with the previous values kept for `on_client_loss: "hold"`. A program built for another map leaves outputs off and is logged. `canworks_in` sets `canworks_ok` while the bridge's status counter moves and the hashes match.
- **`on_client_loss: "preop"`.** Outputs stop and every node of every CANopen master network goes to PRE-OPERATIONAL; the next accepted write after the loss sends NMT start. This replaces "nodes to PRE-OP when the PLC stops" of the plugin.
- **SDO and NMT blocks over Modbus.** The `canworks` library gets ST blocks `CO_SDO_READ`, `CO_SDO_WRITE` (up to 4 bytes, through the bridge's SDO registers), `CO_NMT` and `CO_NODE_LIVE` (control block and live list), and the helpers `CW_WORDS_TO_REAL`/`CW_REAL_TO_WORDS`. They take the generated `canworks` link variable as an in-out, share the bridge's one SDO and one control block between instances, and run on any IEC 61131-3 runtime. The library's other blocks (SDO bytes, string and real, raw CAN, J1939, EMCY, CiA 402) are left out of the library from this change on; change 3 brings the non-CiA 402 ones back.
- **Devices.** For an OpenPLC project the Devices page installs the pinned OpenPLC runtime and the bridge side by side, and **Start this project's bridge** puts the project's bridge config on the device. The runtime gets no canworks plugin.
- **The plugin target leaves the configurator.** New config… and the Project target field offer OpenPLC (through Modbus), Modbus bridge and CODESYS. A plugin config opens with one line and **Switch to OpenPLC through Modbus**, which repacks it as the existing OpenPLC → bridge switch does. The plugin and the deploy tool still accept plugin configs until change 2 removes them.
- **CI and docs.** A new integration test runs the pinned stock runtime image with its Modbus master, the bridge and a simulated node on vcan0. README, `docs/modbus-bridge.md`, `docs/configurator.md`, `docs/plc-library.md`, `docs/devices.md`, `docs/deploy.md` describe the OpenPLC route.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `modbus-bridge`: `openplc` section, PLC link header with map hash, `on_client_loss: "preop"`.
- `modbus-bridge-map`: map hash, OpenPLC remote device file.
- `canopen-config-contract`: config target with `bridge.openplc`.
- `canopen-configurator`: OpenPLC target through Modbus, remote device on save, editor-open warning, plugin config switch.
- `canopen-editor-project`: `canworks` variables and `canworks_in`/`canworks_out` in a new OpenPLC project.
- `plc-library`: ST blocks over the bridge, library contents.
- `device-install`: OpenPLC project installs runtime and bridge.
- `canopen-ci`: OpenPLC Modbus integration test.

## Impact

- Bridge: `plugin/src/can/config.cpp` (`openplc` section), `plugin/src/bridge/bridge_blocks.*` (header, hash, preop), `bridge_host.cpp`; tests in `test/bridge/`.
- PC tools: `modbusmap.py` (hash, remote device), new `tools/deploy/canworks/openplcmodbus.py` (remote device file, `canworks_in`/`canworks_out`), `editorproject.py`, `targets.py`, configurator pages and save path, `devices/plan.py`.
- Library: `library/canworks/` new ST blocks, `library/generate.py` and `build.sh` select the blocks.
- CI: new job in `integration.yml` (path-filtered, replaces nothing yet); browser and tool tests in existing shards.
- Not in scope: deleting the plugin, CiA 402 and the editor hook (change 2); the local simulator runtime on the PC (change 2); mailboxes for long SDO, raw CAN, J1939 and EMCY (change 3).
