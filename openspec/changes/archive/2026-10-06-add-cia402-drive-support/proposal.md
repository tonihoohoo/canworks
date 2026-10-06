# Proposal

## Why

A user who maps a CiA 402 drive today writes the drive state machine by hand in ST: Shutdown, Switch on, Enable operation and fault reset over the controlword and statusword, the mode byte, and the profile position and velocity handshakes (new set-point, set-point acknowledge, target reached). The OD browser already decodes 0x6040/0x6041 and 0x6060/0x6061, but nothing helps the PLC program. CODESYS SoftMotion and TwinCAT NC give an axis object with PLCopen Motion blocks.

OpenPLC Editor 4.3.2 already ships those blocks. Its compiler (STruC++ v0.7.0, the version the editor pins) has a built-in library "PLCopen SoftMotion (Light)" with `AXIS_REF_SM3`, `MC_Power`, `MC_MoveAbsolute`, `MC_MoveRelative`, `MC_MoveVelocity`, `MC_Home`, `MC_Halt`, `MC_Stop`, `MC_Reset`, `MC_ReadStatus`, `MC_ReadActualPosition`, `MC_ReadActualVelocity` and `MC_ReadAxisError`, plus a generic CiA 402 drive bridge `SM_Drive_GenericDS402` that copies the drive's PDO values into the axis each scan. The library itself is fieldbus independent; the editor only wires it automatically for EtherCAT drives (it generates the axis, the located PDO variables and the bridge call at compile time). A CANopen drive mapped through this plugin gets none of that.

So the missing piece is the CANopen glue, not a new motion library: mark a node as a CiA 402 axis, map its standard objects to PDOs, and generate the axis and the bridge call in the editor project, so `MC_Power(Axis := drive, Enable := TRUE)` works on a CANopen drive exactly as it does on an EtherCAT one. Writing our own `CO402_*` library instead would duplicate the editor's blocks under other names, and copying the editor's library into this repository is not possible (it is GPL-3.0, this repository is Apache-2.0).

## What Changes

- A node in the config can carry an optional `axis` object: the node is a CiA 402 drive used as one PLCopen axis named after the node, with optional scaling (`scale_numerator`, `scale_denominator`, `scale_factor`, the three `AXIS_REF_SM3` scaling fields). Additive within `schema_version` 1; the plugin accepts the field and does nothing different on the bus.
- Axis checks in the deploy tool (also run by the configurator and the project generator): the controlword 0x6040 must be mapped in an RPDO and the statusword 0x6041 in a TPDO, every mapped standard object must have the IEC type the bridge needs, no standard object may be mapped twice, and the node needs a status bit (`status_location`) so a lost drive puts the axis into error stop. An EDS whose device type 0x1000 is not profile 402 gives a warning, not an error.
- Configurator: a "CiA 402 axis" setting per node with the scaling fields, and a "Map CiA 402 objects" action that adds the standard objects the EDS can map (0x6040, 0x6060, 0x607A, 0x6081, 0x60FF, 0x6071 out; 0x6041, 0x6061, 0x6064, 0x606C, 0x6077 in) to free PDO entries and suggests their locations. PDO communication settings keep the EDS's own values.
- Editor project from a config: for each axis node, `main` also declares the axis (`AXIS_REF_SM3`) and its bridge instance, and the body starts with generated lines that set the scaling and call the bridge with the node's located PDO variables and status bit. The user writes `MC_*` calls after them.
- Example: `config/cia402-drive/` with a self-written CiA 402 drive EDS, a config with one axis node, and a demo program (power on, home, move absolute, move velocity, halt, fault reset), plus `docs/cia402.md`.
- Tests: the generated `main` compiled and run with STruC++'s own ST test runner against an ST model of a CiA 402 drive (pinned STruC++ v0.7.0, downloaded in CI, never committed), and a simulated end-to-end run against a Lely slave that implements the CiA 402 power state machine and profile position/velocity on vcan.
- No plugin bus code. Cyclic synchronous modes (CSP/CSV) are out of scope here; they need SYNC tied to the PLC cycle (separate change).

## Capabilities

### New Capabilities
- `canopen-cia402-axis`: a CANopen node used as a PLCopen axis: the `axis` config field, its checks, what the generated glue does, and the example.

### Modified Capabilities
- `canopen-editor-project`: `main` declares the axis and its bridge and its body calls the bridge for each axis node.
- `canopen-configurator`: CiA 402 axis setting and the "Map CiA 402 objects" action.

## Impact

- `schema/canopen.v1.schema.json`, `docs/config.md`, plugin config parser (accept `axis`, no warning).
- Deploy tool: `contract.py` checks, `editorproject.py` generation, configurator page (`app.js` and the node settings), version bump.
- New `config/cia402-drive/`, `docs/cia402.md`, new drive EDS fixture in `test/fixtures/eds/drives/make_drives.py`, new test slave and ST tests, CI step that fetches STruC++ v0.7.0.
- Depends on the stock editor's built-in PLCopen SoftMotion library (4.3.2 and later); related changes in other threads: SYNC tied to the PLC cycle (needed for CSP/CSV), SDO from the program (homing and ramp parameters at run time), several CAN networks, the EDS device simulator.
