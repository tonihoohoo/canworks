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
The plugin SHALL accept a node's `axis` object without an unknown-field warning and SHALL NOT change anything it does on the bus because of it.

#### Scenario: Bus unchanged
- **WHEN** the same config is loaded once with and once without the `axis` object
- **THEN** the plugin boots, maps and supervises the node the same way both times and logs no warning about `axis`

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
