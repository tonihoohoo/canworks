# Design

## Context

Checked against this repository's main @3c489fd (deploy tool 0.31.0) and STruC++ 0.7.0, the compiler OpenPLC Editor 4.3.2 pins (`scripts/fetch-strucpp.sh`).

- **SYNC from the PLC cycle** (`canopen-master-bringup`, `docs/config.md` "SYNC from the PLC cycle"): with `"sync_source": "plc_cycle"` the plugin sends SYNC at `cycle_start()`, with the outputs of the previous scan. With transmission type 1 on both sides, inputs reach the PLC one cycle after the SYNC that sampled them and outputs are applied two SYNCs after the scan that wrote them, every time. The SYNC period is the PLC task interval times `sync_cycles`. The plugin knows the runtime's base tick (`plugin_runtime_args_t.base_tick_ns`) at init and measures the SYNC interval (last, min, max) for the diagnostics status.
- **The editor's library** (`libs/sources/plcopen-softmotion/`, GPL-3.0, not vendored here):
  - `AXIS_REF_SM3` has the raw drive image `Drive : OpenSML_Axis` (ControlWord, Modes_of_operation, Target_Position, Target_Velocity, Target_torque, StatusWord, Modes_of_operation_display, actual values), the scaling (`fIncPerUnit`, kept by the bridge) and `fCycleTime : LREAL := 0.01` ("task cycle [s], for OTG"), which nothing sets today.
  - `SM_Drive_GenericDS402` copies all of `Drive` to and from the PDO variables every scan, whatever the mode. For a mode other than 3 and 6 it reports `discrete_motion` (or `standstill` on statusword bit 14).
  - `MC_*` blocks drive modes 1, 3 and 6 only.
  - `OpenSML_SyncPosition` / `OpenSML_SyncVelocity` stream positions in mode 8 through `FB_S7RTT_OTG` (S-curve online trajectory generator, from S7RTT, Apache-2.0). They take `OpenSML_Axis` (not `AXIS_REF_SM3`), their own `lrScale`, `CycleTime` as an input, clear controlword bit 3 to change mode, and go to error unless the drive is already "switched on". No CSV over 0x60FF, no CST.
- **Spike done for this proposal**: an ST function block taking `AXIS_REF_SM3`, compiled with `strucpp --compile-lib <dir> -L <bundled libs>`, builds a `.stlib` whose `dependencies` name `plcopen-softmotion 0.1.0`, and a program using it compiles with `-L` to that `.stlib`. Without `-L` the library build fails on the unknown type. Not yet checked: the editor loading a user library that depends on a bundled one (task 1.1).
- **Simulator** (`plugin/sim/sim_drive.cpp`, `docs/simulator.md`): the drive model already follows 0x607A / 0x60FF at every SYNC in modes 8 and 9 and has a following error window. It has no mode 10, ignores 0x60C2 and keeps running when SYNC stops.
- **Example EDS** `config/cia402-drive/servo402.eds`: 0x6502 = 0x25 (modes 1, 3, 6), no 0x60C2, no 0x6065.

## Goals / Non-Goals

**Goals**
- A program streams position, velocity or torque set-points to a CANopen drive in modes 8, 9, 10, one per PLC cycle, applied on SYNC, with the existing axis (`MC_Power`, `MC_Home`, `MC_Reset`, `MC_Read*` still used on the same axis).
- The config cannot describe a cyclic axis whose PDO timing is wrong.
- A safe start: no jump when a cyclic block takes over, no free-wheeling motor on a mode change.
- Tested end to end without a drive.

**Non-Goals**
- Coordinated multi-axis motion blocks (`MC_GearIn`, cams, path interpolation). The cyclic blocks are what those would be built on; the program can already compute set-points for several axes in one scan.
- Multi-axis drives (profiles at 0x6800 and up), interpolated position mode (7), CiA 402 profile torque mode (4).
- Changing the editor's library or its bridge (state reporting for modes 8-10 stays the bridge's).
- SYNC from the master's timer for cyclic axes (refused, see 3).
- Sub-millisecond cycles beyond what add-plc-cycle-sync already allows.

## Decisions

### 1. Own cyclic blocks on `AXIS_REF_SM3`, in the `openplc_canopen` library
The library's sync blocks are close but unsafe for a CANopen start (mode change with bit 3 cleared) and do not use the axis's scaling or cycle time; wrapping them would keep those faults. The new blocks are plain ST, take `Axis : AXIS_REF_SM3` like the `MC_*` blocks, convert units with `Axis.fIncPerUnit`, and write only `Axis.Drive` fields, so the existing bridge carries their values to the PDOs. For CSP moves they call the library's `FB_S7RTT_OTG` (called, not copied).

They go into the repository's existing editor library `openplc_canopen.stlib` (the SDO blocks, spec `canopen-plc-sdo`), built by `library/build.sh` with `-L` to the bundled libraries, so it gains a dependency on `plcopen-softmotion`. Every 4.3.2 project has that library, so nothing new to install. Prefix `CO402_` keeps them clear of names the editor's library may add later (`SMC_*`, `MC_*`).

Fallback if task 1.1 shows the editor will not load a user library depending on a bundled one: the project generator writes the four blocks as POUs into the project (`pous/function-blocks/`), and the configurator offers them as a file to import. Same source, same tests.

Blocks (inputs in the axis's units, as `MC_*`):

| Block | Mode | Inputs | Writes |
|---|---|---|---|
| `CO402_CyclicPosition` | 8 | `Enable`, `Position`, `MaxVelocity` (0 = no step limit) | 0x607A |
| `CO402_CyclicVelocity` | 9 | `Enable`, `Velocity`, `MaxAcceleration` (0 = no limit) | 0x60FF |
| `CO402_CyclicTorque` | 10 | `Enable`, `Torque` (per mille of rated torque, 0x6076), `MaxTorqueStep` (0 = no limit) | 0x6071 |
| `CO402_CyclicMoveAbsolute` | 8 | `Execute`, `Position`, `Velocity`, `Acceleration`, `Jerk` | 0x607A through `FB_S7RTT_OTG` |

Outputs: `InSync` (drive reports the mode, operation enabled, set-points are being applied), `Busy`, `Done` (move block), `Error`, `ErrorID` (`1` drive not enabled, `2` mode refused (0x6061 did not follow within `ModeTimeout`, default T#500ms), `3` step limit exceeded, `4` axis error stop).

Start sequence, the same for all four: on a rising `Enable`/`Execute` with the axis powered (`MC_Power.Status`), set the target to the actual value (0x607A := 0x6064, 0x60FF := 0, 0x6071 := 0), then write 0x6060; keep "enable operation" set; hold the target at the actual value until 0x6061 shows the mode; then follow the input. A drive accepts a mode change while operation is enabled; nothing clears bit 3. A set-point step larger than the limit times `Axis.fCycleTime` sets `Error` and holds the last set-point (no clamping that would hide a bug in the program's trajectory). With `Enable` FALSE the block holds the last set-point (CSP), sends velocity 0 (CSV) or torque 0 (CST) for one scan, and stops writing: the next block (`MC_Halt`, `MC_MoveVelocity`, ...) takes over, following the library's rule that only the active block is called.

Alternative considered: the names other SoftMotion products use (`SMC_FollowPosition`, ...), for porting. Rejected for the clash risk with a future editor library; the docs map the names.

### 2. Config: `cyclic` on the axis
```json
"axis": { "cyclic": true, "interpolation_period_us": 10000 }
```
`cyclic` (default false) says the axis is used in modes 8-10, so the checks know. `interpolation_period_us` (optional, 100-255000) overrides what the plugin writes to 0x60C2. Additive in schema 1 (and 2 through its `$ref`).

### 3. Checks
In the deploy tool's `axis.py` (so deploy, configurator and generator agree) and, for the bus-relevant ones, in the plugin's config parser:
- error: the axis's network has no `"sync_source": "plc_cycle"`, or `sync_cycles` is not 1. With the master's timer, scan and SYNC drift against each other and a set-point is applied twice or skipped; with `sync_cycles` > 1 the program writes set-points the drive never sees. Both make CSP rough or unsafe.
- error: 0x6060 not mapped; none of 0x607A, 0x60FF, 0x6071 mapped.
- error: an RPDO that carries 0x6040, 0x6060 or a set-point object has an effective transmission type above 240 (after EDS defaults). The drive must apply them on SYNC.
- warning: a TPDO with 0x6064 or 0x606C is not synchronous (the program then mixes feedback from different instants).
- warning: the EDS has no 0x60C2 (the drive's period must be set some other way) or 0x6502 does not list the mode a mapped set-point needs (8 for 0x607A, 9 for 0x60FF, 10 for 0x6071).
- warning: no 0x6065 following error window in the EDS (the drive's default may fault on the fixed pipeline delay, see 6).

### 4. Plugin writes 0x60C2
During node configuration, after the startup SDOs dcfgen produces and before NMT start, for a cyclic axis whose EDS has 0x60C2 and no startup SDO for it: write sub 1 (UNSIGNED8 value) and sub 2 (INTEGER8 exponent) for `interpolation_period_us` or, without it, the base tick times `sync_cycles`. The exponent is the largest of -3, -4, -5, -6 that represents the period exactly in 1-255 (10 ms: 10 / -3; 2.5 ms: 25 / -4); a period that cannot be represented is refused at load with the reason. It is logged once per node. The base tick is the SYNC period only when frames come at a fixed rate (one task, or all intervals multiples of the fastest); after 100 SYNCs the plugin compares the measured mean interval and warns once when it differs by more than 10 %, naming the node and both values.

Alternative: the deploy tool computes the period from the editor project's task interval and writes a startup SDO. Rejected as the only source because the configurator edits configs without a project and the plugin sees the real tick; the generator still uses the task interval for `fCycleTime` (5), and the plugin's warning catches a mismatch.

### 5. `fCycleTime` in the generated lines
The generated axis lines (project generator, configurator declarations panel) add `drive.fCycleTime := LREAL#0.010;` for a cyclic axis, from `--task-interval` / the project's task interval. The blocks use it for step limits and the S-curve generator. The docs say to change it with the task interval.

### 6. Timing the user must know
With PLC-cycle SYNC and transmission type 1 the loop is fixed: a set-point written in scan k is applied at SYNC k+2; the position feedback the program sees in scan k was sampled at SYNC k-1. So the program sees a constant following distance of about three cycles times the velocity (30 mm at 1 m/s and 10 ms). The drive's own following error window (0x6065) must allow it; the docs give the formula and the example sets it with a startup SDO. When the PLC stops, SYNC stops and a real drive faults on its interpolation watchdog; `MC_Reset` and a new start are needed after a PLC restart.

### 7. Simulator
`sim_drive.cpp`: mode 10 (torque set-point 0x6071 to acceleration with `drive.torque_accel` counts/s² per ‰, default 10000, limited by `max_velocity`); 0x60C2 read at enable for the watchdog period; in modes 8-10 with operation enabled, once a SYNC has been seen in that mode, no SYNC for 3 interpolation periods faults the drive with EMCY 0x8700 (CiA 402 "sync controller" class); a `sync_watchdog: false` drive setting switches it off. The model already follows set-points at each SYNC. It also counts set-point steps above `max_velocity` per period (`sim_status`), which the end-to-end test asserts is zero.

### 8. Tests
- ST tests (`test/cia402/`, STruC++ 0.7.0): the drive model learns modes 8, 9, 10 (follow on each call, which is one SYNC); tests for each block's start (no jump from a non-zero actual position, mode reached with bit 3 kept), step limit error, `Enable` FALSE hand-over to `MC_Halt`, `CO402_CyclicMoveAbsolute` reaching the target without exceeding velocity, acceleration, error stop.
- End to end (`sim_tests --exact sim_cia402_cyclic`): the CSP demo compiled by STruC++ runs as the PLC program through the real master with `"sync_source": "plc_cycle"` against the in-plugin simulated drive on the virtual bus: power, home, a CSP move, a CSV run, a CST step, set-point steps within limits, 0x60C2 written, SYNC stopped (PLC stop) faults the drive and `MC_Reset` recovers.
- Deploy tool unit tests for the checks and generated lines; configurator page tests; plugin config tests.

## Risks / Trade-offs

- **Editor loading a library with a dependency** is unproven (task 1.1); fallback in 1.
- **Frame jitter**: SYNC follows the runtime's frames; scan overruns or mixed task intervals give uneven periods, which CSP turns into speed ripple. add-plc-cycle-sync measured SYNC within limits under load with SCHED_FIFO; the docs keep the "one task, or multiples" rule and the plugin's warning flags a wrong tick.
- **No real drive**: drive behaviour on a mode change while enabled, on 0x60C2 and on missing SYNC differs between vendors. The simulator models the CiA 402 text; the hardware task stays open until a drive is available.
- **Bridge state**: modes 8-10 report `discrete_motion` through `MC_ReadStatus`; `InSync` is the block-level truth. Documented.

## Open Questions

- Whether a second, faster PLC task only for motion is worth supporting (frames would no longer be regular). Not in this change.
