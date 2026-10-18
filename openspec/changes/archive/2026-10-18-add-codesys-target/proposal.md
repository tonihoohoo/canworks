# Proposal: add-codesys-target

## Why

A project can target OpenPLC or the Modbus bridge, but CODESYS is only an item in the Export menu. A CODESYS user still works in a page built for OpenPLC:

- Every PDO entry needs an OpenPLC `%I/%Q` location, only because the export names a CODESYS I/O channel after the editor declaration of that location. CODESYS assigns its own addresses, so the user makes up locations that are thrown away.
- The CODESYS settings (network number, CAN interface object, target device, project file) exist only as command-line flags, so the page cannot set them and every run needs them again.
- The page shows about forty settings CODESYS never uses (plugin status locations, SDO variables, CiA 402 axis bridge, scan watchdog, EDS lint, simulated devices, raw CAN, gateway, ...). The export lists them afterwards in its report; the page gives no hint before.

The Modbus bridge has the same gap in a smaller form (Toni, 2026-10-18: "make sure that modbus works in the similar manner"): a bridge project still shows the PLC-cycle SYNC source, the scan watchdogs and the OpenPLC Editor project actions, which the bridge refuses or ignores.

## What Changes

- **Three project targets, one behaviour.** The "Project target" choice offers OpenPLC, Modbus bridge and CODESYS. A top-level `codesys` object makes a config a CODESYS config, the same way `bridge` makes it a bridge config; the two exclude each other.
- **One relevance table** (`canworks/targets.py`) says, per setting, which targets use it and why the others do not. The same table:
  - hides on the page every field, choice option, tree entry, menu item and start-page action the project's target does not use;
  - makes the check warn when a setting the target does not use still has a value, with a Remove action on the problem;
  - gives the CODESYS plan's `not_carried` list (replacing `MASTER_NOTES`/`NODE_NOTES` in `codesys/plan.py`).
- **Variable names without locations.** A PDO entry may have a `name`, the variable name of its value. In a CODESYS config `iec_location` is not needed: every mapped entry becomes a named I/O channel, named by `name` or the name the editor declarations would give it. For OpenPLC and the bridge, `name` also names the entry's declaration and register-map row. The PDO table shows a Variable column for every target and the Location column only where the target uses it.
- **CODESYS settings in the config**: `codesys.project`, `codesys.device`, `codesys.create`, `codesys.variables`, and per master network `codesys.net_id` and `codesys.interface`. The deploy flags (`--codesys-net`, `--codesys-can`, `--codesys-plc`, `--codesys-new`, `--codesys-import PROJECT`) override them, and `--codesys-import` with no project takes `codesys.project`.
- **Switching target** is one undo step, with one dialog listing what the new target does not use. To CODESYS: **Remove them** (default) or **Keep them**; the entries get their current generated names as `name` so channel names do not change. From CODESYS: the existing pack per type (OpenPLC) or Pack for Modbus (bridge) gives every entry a location. OpenPLC to bridge and back keeps today's repack choice and also lists the settings the bridge does not use.
- **CODESYS actions in the header.** A CODESYS project has **Build into CODESYS project…** (runs the existing `--codesys-import` headless on `codesys.project`, shows the report in the log; offered when this PC has CODESYS) and **Download for CODESYS** (today's zip). Export > CODESYS leaves the menu; the DCF, DBC and HTML exports stay for every target.
- **Start page**: "New standalone config" asks for the target. The intro names the three targets.
- **Commission** in a CODESYS project connects through a USB adapter only (no runtime runs the bus); everything else there is unchanged.
- The OpenPLC plugin, `canworks-bridge` and `canworks-deploy --runtime/--bridge` refuse a CODESYS config with a message saying it is for CODESYS.
- Docs: `docs/codesys.md` leads with the target, `docs/configurator.md` and `docs/modbus-bridge.md` describe the target switch and what each target hides, `docs/config.md` documents `codesys` and entry `name`; README and tour updated.

Not in this change: CODESYS J1939 manager or CANopen local device (slave) export, the manager's NMT error behaviour and the devices' identity check ticks from the config (probe only, task 7.2), canworks-sim next to CODESYS Control on Linux.

## Capabilities

### Modified Capabilities
- `canopen-configurator`: Project target with three targets, hiding what the target does not use, switching dialog, Variable column, CODESYS settings and header actions, start page target; Export > CODESYS replaced.
- `canopen-config-contract`: `codesys` object and entry `name` in the schema, CODESYS configs need no locations, targets exclude each other, unused-setting warnings, plugin and bridge refuse CODESYS configs.
- `codesys-export`: plan from the config's `codesys` settings, channels for every mapped entry, names from `name`, `not_carried` from the shared table.
- `canopen-deploy`: CODESYS flags override the config, `--codesys-import` without a project, refusal to upload a CODESYS config.

## Impact

- Code: new `tools/deploy/canworks/targets.py`; `contract.py` (target, checks, warnings), `configurator/declare.py` (entry `name`, entries without locations), `codesys/plan.py`, `cli.py`, `modbusmap.py` (row names), `configurator/server.py` (target table in the model, switch endpoint, build endpoint), `configurator/static/` (`bridge.js` target field moves to a new `target.js`, `app.js`, `tree.js`, `node.js`, `nodes.js`, `index.html`), `plugin/src/can/config.cpp` (refuse `codesys`).
- Schema: `schema/canworks.v2.schema.json` (`codesys`, network `codesys`), `schema/canworks.v1.schema.json` (entry `name`).
- Tests: unit tests for the table, checks, plan and declarations; Playwright tests per target; plugin config test. CI time: a few seconds in the existing shards.
- Version: minor bump of the tools package; plugin patch bump.
- Hardware/PC: one headless build on the Windows PC's CODESYS (config without locations, named channels, 0 build errors). No Pi needed.
