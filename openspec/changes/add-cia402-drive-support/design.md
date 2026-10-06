# Design

## Context

Checked against this repository's main @c61e750 (deploy tool 0.23.0), OpenPLC Editor v4.3.2 (37cdb6a) and STruC++ v0.7.0 (the compiler version the editor pins in `binary-versions.json`).

- STruC++ v0.7.0 has a built-in library `plcopen-softmotion` (`libs/sources/plcopen-softmotion/`, "PLCopen SoftMotion (Light)", namespace `strucpp`, GPL-3.0, vendored from the OpenSML and S7RTT projects). Its parts: `AXIS_REF_SM3` (a STRUCT with CODESYS SM3 field names, LREAL technical units, scaling `iRatioTechUnitsNum`/`dwRatioTechUnitsDenom`/`fScalefactor`, and a raw CiA 402 image `Drive : OpenSML_Axis`), the `MC_*` blocks (single active move, BufferMode aborting only), and `SM_Drive_GenericDS402`, the per-axis bridge:
  - inputs `wStatusWord : UINT` (0x6041), `siModesDisplay : SINT` (0x6061), `diActualPosition : DINT` (0x6064), `diActualVelocity : DINT` (0x606C), `iActualTorque : INT` (0x6077), `bOnline : BOOL`;
  - outputs `wControlWord : UINT` (0x6040), `siModes : SINT` (0x6060), `diTargetPosition : DINT` (0x607A), `udiProfileVelocity : UDINT` (0x6081), `diTargetVelocity : DINT` (0x60FF), `iTargetTorque : INT` (0x6071);
  - `VAR_IN_OUT Axis : AXIS_REF_SM3`. Each call copies this scan's inputs into the axis, derives `nAxisState` (power off, standstill, motion, homing, error stop when `bOnline` is FALSE or the statusword fault bit is set) and emits the command words the `MC_*` blocks wrote on the previous scan.
- Editor 4.3.2 uses this library for EtherCAT only: `src/middleware/shared/utils/ethercat/cia402.ts` recognises a CiA 402 ESI device (0x6040 and 0x6041 mandatory, the other objects above optional), and `src/backend/shared/ethercat/generate-softmotion.ts` generates at compile time an `AXIS_REF_SM3` global named after the device, a located global per mapped object, and a `__sm3_bridge` program run first in the task. A CANopen node is not an editor device, so none of that runs for it.
- Our editor project generator (`canopen-editor-project`) already writes `main` with one located variable per mapped PDO entry, in the program's VAR block (located variables in a global variable list do not bind in 4.3.2).
- `test/fixtures/eds/drives/servo-drive.eds` has 0x6040, 0x6041, 0x6060, 0x6061, 0x6064, 0x606C, 0x607A, 0x60FF but not 0x6081, 0x6071, 0x6077 or the homing objects. `test/sim/sim_tests.cpp` has a `VendorDriveSlave` that echoes the controlword, not a CiA 402 state machine.

## Goals / Non-Goals

**Goals**
- `MC_Power`, `MC_MoveAbsolute`, `MC_MoveRelative`, `MC_MoveVelocity`, `MC_Home`, `MC_Halt`, `MC_Stop`, `MC_Reset` and the `MC_Read*` blocks of the stock editor work on a CANopen drive, with the same call form as on an EtherCAT drive (`MC_Power(Axis := drive, ...)`).
- A drive is one setting and one action in the configurator; the generated project needs no hand wiring.
- Tested without hardware.

**Non-Goals**
- Our own motion blocks or a copy of the editor's library.
- Cyclic synchronous modes (CSP 8, CSV 9, CST 10). The library has `OpenSML_SyncPosition`/`OpenSML_SyncVelocity`, but streaming set-points needs SYNC sent from the PLC cycle; that is the separate "SYNC tied to the PLC cycle" change. Until then the docs say the profile modes (1, 3, 6) are the supported ones.
- Multi-axis drives (several 402 profiles in one node at 0x6800 and up), profile torque blocks, buffered or blended moves (library limits), changing homing method or ramps at run time from the program.
- Any change to the plugin's bus behaviour.

## Decisions

### 1. Reuse the editor's built-in library, generate only the glue
The bridge and `MC_*` blocks are already in every 4.3.2 install, take plain PDO values, and match CODESYS SM3 names, which is what a user porting a program expects. A second library would mean two `MC_Power`s with different semantics and would need installing in each editor. Vendoring the library is ruled out by its licence (GPL-3.0 into an Apache-2.0 repository) and would fork it.

Alternative kept as fallback: our own `.stlib` (`CO402_Power`, `CO402_MoveVelocity`, ... over the same located variables), written from the CiA 402 standard, only if the first task shows the built-in library cannot be used from a project without an EtherCAT device.

### 2. Config: `axis` object on the node
```json
{ "name": "drive", "node_id": 4, "eds": "servo402.eds", "status_location": "%IX10.0",
  "axis": { "scale_numerator": 1, "scale_denominator": 1, "scale_factor": 1.0 },
  "rx_pdos": [...], "tx_pdos": [...] }
```
The axis is named after the node (the editor's rule: device name = axis name), so the program says `MC_Power(Axis := drive)`. All three scaling fields are optional with the library's defaults (1, 1, 1.0); `scale_numerator` is a DINT, `scale_denominator` a positive DWORD, `scale_factor` a non-zero finite number. The node name is already a valid IEC identifier, and the name `drive` does not clash with the generated `drive_*` variables.

Which object goes to which bridge pin is found from the node's PDO entries (index:subindex 0x6040:0 etc.), not from extra config, so mapping stays in one place. The plugin only learns that `axis` is a known field (no "unknown field" warning).

### 3. Checks
Run by the deploy tool's contract checks, so the configurator, `deploy` and the project generator refuse the same things:
- error: 0x6040:0 not mapped in an RPDO with a location, or 0x6041:0 not in a TPDO with a location;
- error: a standard object mapped in the wrong direction, twice, or to a location whose IEC type differs from the pin's (UINT for 0x6040/0x6041, SINT for 0x6060/0x6061, DINT for 0x607A/0x6064/0x606C/0x60FF, UDINT for 0x6081, INT for 0x6071/0x6077); the configurator's type suggestion already picks these from the EDS data types, so this mainly catches hand-edited files;
- error: no `status_location` (the bridge's `bOnline` needs it; without it a lost drive would look like a drive in standstill);
- error: bad scaling values;
- warning: EDS device type (0x1000) low word is not 402;
- warning: a target object mapped without its mode (0x607A or 0x6081 without 0x6060, 0x60FF without 0x6060), since the library sets the mode itself.

### 4. Generated code in `main`
Per axis node, after that node's other declarations in the VAR block:
```
drive : AXIS_REF_SM3; (* CiA 402 axis, node drive *)
drive_bridge : SM_Drive_GenericDS402; (* drive bridge for axis drive *)
```
and at the top of the body, before the existing comment:
```
(* CiA 402 axes from canopen/canopen.json: keep these lines first *)
drive.iRatioTechUnitsNum := DINT#1;
drive.dwRatioTechUnitsDenom := DWORD#1;
drive.fScalefactor := LREAL#1.0;
drive_bridge(Axis := drive, wStatusWord := drive_Statusword, siModesDisplay := drive_Modes_of_operation_display,
    diActualPosition := drive_Position_actual_value, diActualVelocity := drive_Velocity_actual_value,
    bOnline := drive_ok, wControlWord => drive_Controlword, siModes => drive_Modes_of_operation,
    diTargetPosition => drive_Target_position, diTargetVelocity => drive_Target_velocity);
```
Only pins whose object is mapped are bound; unbound inputs stay at the library's defaults. The located variable names are the ones the generator already uses. Same shape as the editor's EtherCAT bridge: the bridge runs first, so `MC_*` calls after it see this scan's feedback, and their commands go out on the next scan (one scan of command latency, as on EtherCAT).

Lines in the body are the user's to keep: the generator writes `main` once and never touches an existing project (`Never overwrite`), so regenerating after a config change means a new project or editing these lines by hand. The configurator's "Located variable declarations" copy text gets the same lines so a user with an existing project can paste them.

### 5. Example and docs
`config/cia402-drive/`: `make_eds.py` writing `servo402.eds` (a made-up drive: 0x1000 = 0x00020192, the objects above plus 0x6083/0x6084 ramps and 0x6098/0x6099/0x609A homing, writable PDO mapping, heartbeat), `canopen_config.json` (one axis node, startup SDOs for ramps and homing method), `drive_demo.st` (power on, home, absolute move, velocity, halt, fault reset with `MC_*`), `README.md`. `docs/cia402.md` covers the PDO layout, transmission types (the EDS's own values; with SYNC on, a SYNC period short enough for the program's cycle), scaling, the one-scan latency, supported modes, and how to set homing and ramps (startup SDOs now; run-time SDO later).

### 6. Tests
- **ST tests with STruC++**: CI downloads the STruC++ v0.7.0 release (the editor's pin) into the runner cache; the version is one variable next to the editor version the docs name. `test/cia402/drive_model.st` is an ST model of a CiA 402 drive (power state machine from the controlword, statusword bits, mode display following the mode, set-point acknowledge and target reached in profile position, velocity following in profile velocity, homing done, a fault input). `TEST` blocks run the generated `main` for the example config against the model: power on reaches `Status`, a move reaches `Done`, velocity reaches the target, fault and `MC_Reset`, `bOnline` FALSE gives error stop. The generator's Python tests check the text; these check that it compiles and does what it says with the real library.
- **Simulated bus**: `test/drive/drive_slave.cpp`, a Lely slave from `servo402.eds` with the same CiA 402 behaviour in C++, and a `cia402` mode in `test/host/canopen_host` that runs the scan logic. First choice: the STruC++-compiled `main` linked into the host, so the real ST runs against the real plugin on vcan; fallback if the generated C++ cannot be hosted outside the runtime: a C++ scan that performs the same handshake, which still proves PDO direction, types and timing.
- **Hardware**: no drive on the bench; the hardware task stays open in the PR, as with earlier changes.

## Risks / Trade-offs

- **The built-in library is used outside its intended path.** If the 4.3.2 editor only links `plcopen-softmotion` when the project has an EtherCAT axis, `MC_Power` does not resolve in a CANopen project. First task checks this on the editor; fallback is decision 1's own library.
- **Upstream changes the library.** It is version 0.1.0 and its plan document calls the SM3 layer "design". Pinning the STruC++ version in tests and naming the editor version in the docs keeps us honest; a signature change shows up as a failing ST test when the pin moves.
- **Library limits leak through.** Single active move, profile modes only, units scaling as the library does it, error IDs from its `SMC_ERROR` subset. The docs list them instead of hiding them.
- **One scan of command latency** plus PDO timing (SYNC period or event). Fine for profile modes, where the drive runs the profile; not for CSP.
- **Editing generated lines.** A user who changes the PDO mapping must update the bridge call by hand in an existing project; the configurator's copy text helps.

## Related changes in other threads

- **SYNC tied to the PLC cycle**: needed before CSP/CSV can be offered; the bridge's one-scan pipeline then lines up with SYNC.
- **SDO from the program (CiA 405 style)**: lets the program set homing method, ramps or read drive errors (0x603F) at run time; until then those are startup SDOs. If that change ships a C++ FB library, a later `MC_ReadParameter`/`MC_WriteParameter` could sit on it.
- **Several CAN networks**: axis names stay node names, which that change must keep unique across networks.
- **EDS device simulator**: once it exists, `drive_slave` could become its CiA 402 personality so users can try an axis without a drive.

## Open Questions

- Does the 4.3.2 editor make `plcopen-softmotion` available to every project (task 1.1)?
- Should a later change let the configurator's online view show the axis state (decoded `nAxisState`) next to the statusword decoding it already has?
