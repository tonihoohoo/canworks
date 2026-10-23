## Why

Every program that uses canworks' values reaches them the same way: Modbus TCP registers served by canworks-bridge. Yet the configurator shows OpenPLC as a target of its own, next to "Modbus bridge" and CODESYS, while the other clients (truST, other PLCs, Node-RED, HMIs, scripts) are files scattered in Export ▾. The New config dialog asks "What will run the networks?" and offers OpenPLC, which never runs the networks: canworks-bridge does in both of the first two cards. In the code, the OpenPLC target is only `bridge` plus `bridge.openplc`. Every OpenPLC-only setting describes the program on the other side of the registers (loopback address, writer, PLC link, poll, editor files), not a different engine.

What really differs between clients is how canworks hands them their side. OpenPLC's editor project can be written by canworks and kept in sync on every Save. Every other client gets a file the user imports. That difference belongs to the client, not to the target.

Toni (2026-10-23):
- "why some are exports and some targets when they all use modbus" — the connections model "sounds better";
- "no program choice is ok, but list all supported";
- "codesys as modbus client is not real use case" — "yes remove it and propose".

Mockup: https://claude.ai/artifact/1Ka2keVD13zpbGkh3SWXvD. Explore report: `research/modbus-one-target-2026-10-23.md`.

## What Changes

- **Two targets, by what runs the CAN networks.** **Modbus bridge** (canworks-bridge runs them and serves Modbus TCP registers) and **CODESYS** (a CODESYS PLC runs the CANopen master). OpenPLC is no longer a target. The New config dialog asks only "What runs the CAN networks?". Its Modbus bridge card lists every client the bridge works with: OpenPLC, truST, other PLCs, Node-RED, HMI/SCADA and scripts. The Project page's target field has the same two choices.
- **Connections.** The Modbus bridge page gets a **Connections** list: the programs that read and write the bridge's registers, stored in the config as `bridge.connections`. **Add connection** offers five kinds:
  - **OpenPLC**: an OpenPLC Editor project on the bridge's device. Save keeps its files in sync: the remote device, `canworks_in`/`canworks_out` and the `canworks` list. Adding it while the config is standalone offers New editor project… and Move into project….
  - **truST**: the PLCopen XML folder for truST.
  - **Other PLC**: the PLCopen XML (generic) or the ST PLC link file.
  - **Node-RED**: the Node-RED flow (later also the Node-RED nodes of `add-nodered-blocks`).
  - **HMI, SCADA or script**: the register map as CSV or JSON, or the ST variables.
- **Each connection's own controls.** Each connection has a name, the address it connects from, whether it writes, its files with one Download button, and Remove.
- **Out-of-date warning.** For a file connection canworks remembers the map hash of the last download. When the map changes, the connection says "Out of date" and Problems warns.
- **Several connections at once,** for example an OpenPLC program that writes and an HMI that only reads.
- **Writers follow the connections.** The configurator keeps `bridge.writers` equal to the addresses of the connections that write. A connection from another address than the bridge listens on is a problem with a one-click fix.
- **OpenPLC as a connection (clean cut, nothing is in real use).**
  - `bridge.openplc` is removed. Its PC-side settings (`poll_ms`, `remote_device`, `iec_base`) move into the OpenPLC connection.
  - What the bridge needs becomes explicit bridge settings that adding the connection writes: `plc_link: true`, `listen` 127.0.0.1:1502, `writers` 127.0.0.1, `watchdog_ms` 5 × poll, `word_order` low first, and mailboxes on.
  - canworks-bridge refuses `openplc` with a message pointing to the configurator, and ignores `connections`.
- **Export ▾ is for network files only:** All DCFs, This node's DCF, DBC and Documentation, plus Download for CODESYS on a CODESYS config. The "For the program" group goes away: each of its files is now on its connection.
- **No CODESYS as a Modbus client.** `canworks-deploy --export-plcopen --for codesys`, the CODESYS dialect, `import_canworks_modbus.py` and its options are removed. `--for trust|generic` stay. CODESYS is only the CANopen-master target.
- **Docs.**
  - `docs/configurator.md`: Where things are, Connections, Project target.
  - `docs/modbus-bridge.md`: OpenPLC through Modbus becomes the OpenPLC connection.
  - `docs/plcopen.md`, `docs/node-red.md` and the README.

## Capabilities

### New Capabilities

- `modbus-connections`: the connections of a Modbus bridge config, how each kind is added, downloaded, kept in sync and checked, and how writers follow them.

### Modified Capabilities

- `canopen-configurator`: Project target, Target of a new config, Switching the target, Only what the target uses, Export menu groups, Where things are, Editor project on the Project page, Register map preview and export, OpenPLC project page, Export for another PLC, Reachability warnings; the "CODESYS route explained" requirement is removed.
- `canopen-config-contract`: Config target (two targets), `bridge.connections` in the schema.
- `modbus-bridge`: OpenPLC section removed, PLC link on any bridge config (`plc_link` is the only switch), `connections` ignored by the bridge.
- `plcopen-export`: CODESYS transport removed, export for `trust|generic` only.
- Wording-only updates where `bridge.openplc` is named: `canopen-editor-project`, `modbus-bridge-map`, `modbus-bridge-mailboxes`, `device-install`, `canopen-virtual-example`, `canopen-deploy`, `canopen-ci`.

## Impact

- **PC tools**:
  - `targets.py` (two targets; the OpenPLC-only rows key on the OpenPLC connection);
  - `bridgecheck.py` and `modbusmap.py` (no `openplc`, `connections` checked);
  - `openplcmodbus.py` (reads the OpenPLC connection);
  - `plcopen.py` and `plcopen_targets.py` (no codesys);
  - `cli.py`;
  - the configurator: New config, Project page, Modbus bridge page Connections, Export ▾, Problems;
  - `server.py` routes for connection downloads.
- **Bridge**: `plugin/src/can/config.cpp` drops `openplc` (refused with a pointer), accepts and ignores `connections`; `plc_link` already carries the header logic.
- **Schema**: `bridge.connections`; `bridge.openplc` removed.
- **Examples**: the virtual plant and the bridge examples move to an OpenPLC connection.
- **Tests**: page tests that pick the OpenPLC target or use For the program; the PLCopen CODESYS tests are removed.
- **Order**: after `add-plcopen-export` (#259, merged), before `add-nodered-blocks`. That change's configurator part becomes the Node-RED connection's download.
- **Hardware**: an OpenPLC connection on the Pi bench (Save, upload, values move); desktop checks on Mac and Windows.
