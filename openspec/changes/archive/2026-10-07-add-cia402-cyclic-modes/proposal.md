# Proposal

## Why

A CiA 402 axis today runs profile position (1), profile velocity (3) and homing (6) only: the drive plans each move itself and the PLC sends a target now and then (`docs/cia402.md`, "What works"). Coordinated or multi-axis motion, a PLC-side trajectory, electronic gearing or a torque loop in the program need the cyclic synchronous modes, CSP (8), CSV (9) and CST (10), where the program sends a new set-point every cycle and the drive applies it on SYNC. The missing piece for that was SYNC sent from the PLC cycle, which shipped in add-plc-cycle-sync (`"sync_source": "plc_cycle"`). What is left is the axis side: config and checks that make the PDO timing right, program blocks that stream set-points safely, the drive's interpolation period, and a way to test it without a drive.

The editor's built-in motion library does not cover this. Its `MC_*` blocks use the profile modes only. It has `OpenSML_SyncPosition` and `OpenSML_SyncVelocity`, which stream positions in mode 8 through its S-curve generator `FB_S7RTT_OTG`, but they work on the raw drive image with their own scale, need the cycle time typed in, switch modes by dropping "enable operation" (the motor is free for a moment), go to error unless the drive is already switched on, and offer no CSV over 0x60FF and no CST.

## What Changes

- Config: an axis can be marked `"cyclic": true` (axis object, additive in schema versions 1 and 2). For such an axis the deploy tool, configurator and project generator require SYNC from the PLC cycle with `sync_cycles` 1, 0x6060 mapped, at least one set-point object (0x607A, 0x60FF or 0x6071) mapped, and the drive's RPDOs that carry the controlword, mode and set-points synchronous (transmission type 0-240 after EDS defaults). They warn when the drive's input PDO with the actual position or velocity is not synchronous, when the EDS has no 0x60C2, and when 0x6502 does not list a mode the axis maps a set-point for.
- Plugin: for a cyclic axis it writes the interpolation time period 0x60C2 (sub 1 value, sub 2 exponent) during node configuration from the SYNC period (the PLC base tick), unless the config sets `interpolation_period_us` or a startup SDO writes 0x60C2. It warns once when the measured SYNC interval differs from it by more than 10 %. It refuses a cyclic axis on a network without PLC-cycle SYNC, as the deploy tool does.
- Program blocks in the repository's own `openplc_canopen` editor library, working on the library's `AXIS_REF_SM3` next to `MC_Power`, `MC_Home` and `MC_Reset`: `CO402_CyclicPosition`, `CO402_CyclicVelocity`, `CO402_CyclicTorque` (stream a set-point every cycle in mode 8, 9 or 10, with a bumpless start from the actual value and an optional step limit) and `CO402_CyclicMoveAbsolute` (point-to-point move in CSP through the editor library's S-curve generator). Axis scaling is the axis's own.
- Project generator and configurator: the generated axis lines also set `<axis>.fCycleTime` from the project's task interval; "Map CiA 402 objects" on a cyclic axis lays the objects out for cyclic use and sets transmission type 1 on those PDOs (shown, not hidden); a "Cyclic synchronous" switch on the axis.
- Device simulator: the drive model also runs CST (mode 10), reads 0x60C2, and faults with EMCY 0x8700 when SYNC stops while it runs a cyclic mode in "operation enabled", as real drives' interpolation watchdogs do.
- Example and tests: a CSP variant of `config/cia402-drive/` (the made-up EDS lists modes 8-10 and has 0x60C2), ST tests of the blocks against the ST drive model, and an end-to-end simulated run through the real master with SYNC from the PLC cycle.
- Docs: `docs/cia402.md` gets a cyclic synchronous section (timing, following error, what stops the drive), `docs/config.md` the new fields, README its CiA 402 line.

## Capabilities

### New Capabilities
None.

### Modified Capabilities
- `canopen-cia402-axis`: cyclic axes: the `cyclic` and `interpolation_period_us` fields, their checks, the plugin's 0x60C2 write, the cyclic program blocks, the example and its tests.
- `canopen-device-simulator`: the drive model adds CST, 0x60C2 and the SYNC watchdog.
- `canopen-configurator`: the "Cyclic synchronous" switch and the cyclic layout of "Map CiA 402 objects".
- `canopen-editor-project`: the generated axis lines set the axis cycle time.

## Impact

- `schema/canopen.v1.schema.json`, `schema/canopen.v2.schema.json`, `docs/config.md`; plugin `config.cpp` (fields, checks), node configuration (0x60C2 write), SYNC statistics (interval warning).
- Deploy tool: `axis.py` checks and generated lines, `editorproject.py`, configurator page, the `openplc_canopen` library (ST blocks next to the SDO blocks, built with `library/build.sh`), version bump.
- `plugin/sim/sim_drive.cpp` (CST, 0x60C2, SYNC watchdog), `docs/simulator.md`.
- `config/cia402-drive/` (EDS 0x6502 and 0x60C2, CSP config and demo), `test/cia402/` (drive model modes 8-10, block tests), a new `sim_tests` case.
- Depends on the editor's built-in library (`AXIS_REF_SM3`, `FB_S7RTT_Plan`) in OpenPLC Editor 4.3.2 / STruC++ 0.7.0; the library dependency of `openplc_canopen.stlib` is checked first (task 1.1).
- No real CiA 402 drive is available: verification is the simulator and ST tests; the hardware task stays open.
