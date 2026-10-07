# canopen-cia402-axis Specification

## Purpose
CiA 402 drives on the bus used by the PLC program as PLCopen axes of the stock editor's built-in motion library: the `axis` node field, its checks, the generated axis glue, and the CiA 402 example.

## Requirements

### Requirement: Axis node in the config
A node in `canopen_config.json` MAY have an `axis` object, meaning the node is a CiA 402 drive used by the PLC program as one PLCopen axis of the stock editor's PLCopen SoftMotion library, named after the node. The object SHALL accept `scale_numerator` (DINT range, default 1), `scale_denominator` (1 to 4294967295, default 1) and `scale_factor` (finite, non-zero, default 1.0), the axis's three scaling fields. The field SHALL be part of `schema_version` 1 and its JSON Schema.

#### Scenario: Minimal axis
- **WHEN** node `drive` has `"axis": {}`
- **THEN** the config is valid, the axis is named `drive` and its scaling is 1, 1 and 1.0

#### Scenario: Bad scaling
- **WHEN** `scale_denominator` is 0 or `scale_factor` is 0
- **THEN** the config is refused naming the field and its JSON path

### Requirement: Plugin and the axis field
The plugin SHALL accept a node's `axis` object without an unknown-field warning. For an axis without `cyclic` it SHALL NOT change anything it does on the bus because of it. For a cyclic axis it SHALL write the interpolation time period (see "Interpolation time period") and SHALL refuse the config when the axis's network does not send SYNC from the PLC cycle with `sync_cycles` 1.

#### Scenario: Bus unchanged
- **WHEN** the same config is loaded once with and once without an `axis` object that has no `cyclic`
- **THEN** the plugin boots, maps and supervises the node the same way both times and logs no warning about `axis`

#### Scenario: Cyclic axis without PLC-cycle SYNC
- **WHEN** an axis has `"cyclic": true` and its network's master has `sync_period_us` 10000 and no `sync_source`
- **THEN** the plugin refuses the config, naming the node and saying a cyclic axis needs `"sync_source": "plc_cycle"`

### Requirement: Standard objects of an axis
For an axis node, the standard objects SHALL be found from its mapped PDO entries (sub-index 0): outputs 0x6040, 0x6060, 0x607A, 0x6081, 0x60FF, 0x6071 in RPDOs; inputs 0x6041, 0x6061, 0x6064, 0x606C, 0x6077 in TPDOs. The config SHALL be refused, naming node and object, when 0x6040 or 0x6041 is not mapped with a location, or a standard object is mapped in the wrong direction or twice. The others SHALL be optional.

#### Scenario: Velocity-only drive
- **WHEN** the axis node maps 0x6040, 0x6060 and 0x60FF in RPDO 1 and 0x6041, 0x6061 and 0x606C in TPDO 1, all with locations
- **THEN** the config is valid and the axis uses those six objects

#### Scenario: No statusword
- **WHEN** the axis node maps 0x6040 but not 0x6041
- **THEN** the config is refused saying the axis needs the statusword 0x6041 in a TPDO

### Requirement: Types of the standard objects
The config SHALL be refused, naming the node and object, when a mapped standard object's entry has another type than the bridge pin needs: UNSIGNED16 (UINT) for 0x6040 and 0x6041, INTEGER8 (SINT) for 0x6060 and 0x6061, INTEGER32 (DINT) for 0x607A, 0x6064, 0x606C and 0x60FF, UNSIGNED32 (UDINT) for 0x6081, INTEGER16 (INT) for 0x6071 and 0x6077.

#### Scenario: Wrong type
- **WHEN** 0x6040 is mapped with type INTEGER32 at `%QD100`
- **THEN** the config is refused saying 0x6040 needs type UNSIGNED16 (UINT)

### Requirement: Axis needs the node status bit
An axis node SHALL have a `status_location`. The config SHALL be refused without it, saying the axis uses the status bit to put the axis into error stop when the drive is lost.

#### Scenario: Missing status bit
- **WHEN** node `drive` has `axis` but no `status_location`
- **THEN** the config is refused naming node `drive` and `status_location`

### Requirement: Axis warnings
Checking a config with an axis node SHALL warn, without refusing it, when the node's EDS device type (0x1000) does not name device profile 402 in its low 16 bits, and when a target object (0x607A, 0x6081 or 0x60FF) is mapped without 0x6060.

#### Scenario: Not a 402 device
- **WHEN** the axis node's EDS has device type 0x00000191
- **THEN** the check warns that the device does not report profile 402 and the config is still valid

### Requirement: Axis in the PLC program
In a program generated from the config, each axis SHALL be a variable of the library's axis type named after the node, updated once per scan, before the user's code, from the node's mapped inputs and status bit, with the commands the user's `MC_*` calls wrote sent on the next scan. With the node lost (status bit FALSE) or the drive reporting a fault, the axis SHALL be in error stop.

#### Scenario: Power on
- **WHEN** the program calls `MC_Power(Axis := drive, Enable := TRUE)` every scan and the drive follows the CiA 402 power state machine
- **THEN** the drive receives Shutdown, Switch on and Enable operation in turn and `MC_Power.Status` becomes TRUE once the statusword reports operation enabled

### Requirement: Supported motion blocks
An axis SHALL work with the library's `MC_Power`, `MC_MoveAbsolute`, `MC_MoveRelative`, `MC_MoveVelocity`, `MC_Home`, `MC_Halt`, `MC_Stop`, `MC_Reset`, `MC_ReadStatus`, `MC_ReadActualPosition`, `MC_ReadActualVelocity` and `MC_ReadAxisError` in profile position, profile velocity and homing mode.

#### Scenario: Velocity
- **WHEN** the axis is powered and the program executes `MC_MoveVelocity` with velocity 1000 and scaling 1, 1, 1.0
- **THEN** the drive receives modes of operation 3 and target velocity 1000

#### Scenario: Drive lost
- **WHEN** the drive stops sending heartbeats while powered
- **THEN** the axis state becomes error stop

#### Scenario: Fault reset
- **WHEN** the drive reports a fault and the program executes `MC_Reset`
- **THEN** the drive receives the fault reset bit and, once the fault clears, the axis leaves error stop

### Requirement: CiA 402 example
The repository SHALL include a CiA 402 example with a self-written drive EDS that describes no real product, a config with one axis node, a demo program using `MC_Power`, `MC_Home`, `MC_MoveAbsolute`, `MC_MoveVelocity`, `MC_Halt` and `MC_Reset`, and documentation of the supported modes, scaling, timing and the library's limits. The example's generated program SHALL be compiled and run in CI against a simulated CiA 402 drive.

#### Scenario: Example in CI
- **WHEN** CI runs
- **THEN** the example's generated program compiles with the compiler version the supported editor uses and its tests against the simulated drive pass

### Requirement: Cyclic axis in the config
An axis object MAY have `cyclic` (boolean, default false), meaning the program drives the axis in cyclic synchronous position (8), velocity (9) or torque (10) mode, and `interpolation_period_us` (100 to 255000), the interpolation time period to write to the drive instead of the SYNC period. Both SHALL be part of the axis object in the JSON Schema of every schema version that has `axis`.

#### Scenario: Minimal cyclic axis
- **WHEN** node `drive` has `"axis": {"cyclic": true}` and its checks pass
- **THEN** the config is valid and the interpolation period is the SYNC period

### Requirement: Cyclic axis checks
Checking a config SHALL refuse a cyclic axis, naming node and reason, when: its network's master does not have `"sync_source": "plc_cycle"`; `sync_cycles` is not 1; 0x6060 is not mapped; none of 0x607A, 0x60FF and 0x6071 is mapped; or an RPDO carrying 0x6040, 0x6060, 0x607A, 0x60FF or 0x6071 has an effective transmission type (the config's, else the EDS's) above 240. It SHALL warn, without refusing, when a TPDO carrying 0x6064 or 0x606C is not synchronous, when the EDS has no 0x60C2, when the EDS has no 0x6065, and when the EDS's 0x6502 does not list the mode a mapped set-point object needs (8 for 0x607A, 9 for 0x60FF, 10 for 0x6071). An `interpolation_period_us` that 0x60C2 cannot represent (value 1-255 with exponent -3 to -6) SHALL be refused.

#### Scenario: Event-driven set-point PDO
- **WHEN** a cyclic axis maps 0x607A in RPDO 1, which has transmission type 255 in the EDS and none in the config
- **THEN** the config is refused saying RPDO 1 must be synchronous (transmission type 0-240) for a cyclic axis

#### Scenario: More than one cycle per SYNC
- **WHEN** a cyclic axis's network has `"sync_source": "plc_cycle"` and `"sync_cycles": 2`
- **THEN** the config is refused saying a cyclic axis needs one SYNC every PLC cycle

#### Scenario: Mode not listed
- **WHEN** a cyclic axis maps 0x6071 and the EDS's 0x6502 has bit 9 (mode 10) clear
- **THEN** the check warns that the drive does not list cyclic synchronous torque and the config is still valid

### Requirement: Interpolation time period
For a cyclic axis whose EDS has 0x60C2 and whose config has no startup SDO to 0x60C2, the plugin SHALL write 0x60C2 sub 1 and sub 2 during node configuration, before the node is started, with `interpolation_period_us` or, without it, the PLC base tick times `sync_cycles`, using the largest exponent from -3 to -6 that represents the period exactly with a value of 1-255. It SHALL log the period once per node. After 100 SYNCs it SHALL compare the measured mean SYNC interval with the written period and log one warning, naming the node and both values, when they differ by more than 10 %.

#### Scenario: Ten millisecond cycle
- **WHEN** a cyclic axis is configured with a 10 ms base tick and `sync_cycles` 1
- **THEN** the master writes 0x60C2 sub 1 = 10 and sub 2 = -3 before starting the node

#### Scenario: Startup SDO wins
- **WHEN** the node's startup SDOs write 0x60C2 sub 1
- **THEN** the plugin does not write 0x60C2 itself

#### Scenario: Wrong tick
- **WHEN** the program has tasks of 10 ms and 15 ms, so the base tick is 5 ms and frames come every 7.5 ms on average
- **THEN** after 100 SYNCs the plugin warns once that node `drive` has interpolation period 5000 us and the measured SYNC interval is about 7500 us

### Requirement: Cyclic synchronous program blocks
The repository's editor library SHALL provide `CO402_CyclicPosition` (mode 8, target 0x607A), `CO402_CyclicVelocity` (mode 9, target 0x60FF), `CO402_CyclicTorque` (mode 10, target 0x6071) and `CO402_CyclicMoveAbsolute` (mode 8, a point-to-point move whose set-points come from the editor library's S-curve generator), each taking `Axis : AXIS_REF_SM3` and values in the axis's units, usable on the same axis as the library's `MC_Power`, `MC_Home`, `MC_Reset` and `MC_Read*` blocks. On start each block SHALL set the target to the actual value (position) or zero (velocity, torque), then select its mode while keeping "enable operation" set, and follow its input only once 0x6061 shows the mode; it SHALL report `InSync`, `Busy`, `Error` and `ErrorID` (drive not enabled, mode not reached within `ModeTimeout`, step limit exceeded, axis in error stop). A set-point step above the configured limit times `Axis.fCycleTime` SHALL set `Error` and hold the last set-point. With `Enable` FALSE the block SHALL stop writing the set-point after holding the position (CSP) or sending zero velocity or torque (CSV, CST) for one scan.

#### Scenario: Bumpless start
- **WHEN** the axis is powered at actual position 5000 increments in profile position mode and the program enables `CO402_CyclicPosition` with `Position` 5000.0 and scaling 1
- **THEN** the drive receives target position 5000 and modes of operation 8 with controlword bit 3 still set, and `InSync` becomes TRUE once 0x6061 shows 8

#### Scenario: Step limit
- **WHEN** `CO402_CyclicPosition` is in sync with `MaxVelocity` 1000.0, `fCycleTime` 0.01 and the program jumps `Position` by 50.0 in one scan
- **THEN** the block sets `Error` with the step limit error ID and the drive keeps the last target position

#### Scenario: Move in CSP
- **WHEN** the program executes `CO402_CyclicMoveAbsolute` with position 10000.0, velocity 2000.0, acceleration 10000.0 and jerk 100000.0 from position 0
- **THEN** the target position sent each SYNC rises to 10000 without a step above 2000 times the cycle time, and `Done` becomes TRUE when the drive's actual position is there

### Requirement: Axis cycle time
For a cyclic axis the program SHALL set the axis's `fCycleTime` to the PLC task interval in seconds before the blocks run. The project generator and the configurator's axis lines SHALL write that line from the task interval.

#### Scenario: Generated line
- **WHEN** a project is generated with task interval T#10ms from a config whose node `drive` is a cyclic axis
- **THEN** the generated axis lines include `drive.fCycleTime := LREAL#0.01;` before the bridge call

### Requirement: Cyclic synchronous example
The CiA 402 example SHALL include a cyclic variant: a config with one cyclic axis, SYNC from the PLC cycle, synchronous drive PDOs and a following error window set by startup SDO, and a demo program that powers and homes the drive, makes a CSP move with `CO402_CyclicMoveAbsolute`, runs `CO402_CyclicVelocity` and `CO402_CyclicTorque` briefly, and halts. The example's made-up EDS SHALL list modes 1, 3, 6, 8, 9 and 10 in 0x6502 and have 0x60C2 and 0x6065. CI SHALL compile the demo with the compiler version the supported editor uses and run it through the master against the simulated drive with SYNC from the PLC cycle.

#### Scenario: Cyclic example in CI
- **WHEN** CI runs
- **THEN** the cyclic demo runs against the simulated drive, the drive receives 0x60C2, ends each motion step without a fault, no set-point step exceeds the drive model's maximum velocity per period, and stopping the PLC faults the drive by its SYNC watchdog
