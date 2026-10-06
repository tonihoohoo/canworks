## ADDED Requirements

### Requirement: CiA 402 axis setting
The node settings SHALL offer a "CiA 402 axis" switch with the three scaling fields, writing the node's `axis` object, and SHALL show the axis checks' errors and warnings with the node. The switch SHALL be offered for every node and SHALL say when the EDS does not report device profile 402. Turning it on SHALL require a status bit and SHALL suggest one when the node has none.

#### Scenario: Turn on
- **WHEN** the user turns on "CiA 402 axis" for node `drive`, which has a status bit, and saves
- **THEN** the saved config has `"axis": {}` on node `drive` (scaling left at the defaults is not written)

#### Scenario: Error shown
- **WHEN** the axis node does not map 0x6041
- **THEN** the node shows the error and the config is not saved

### Requirement: Map CiA 402 objects
For an axis node the configurator SHALL offer "Map CiA 402 objects", which adds each standard axis object that the EDS has as PDO-mappable and that is not yet mapped to a free entry of an RPDO (outputs) or TPDO (inputs) the device lets the master map, with suggested locations of the bridge's IEC types, and leaves PDO communication settings at the EDS's values. Objects that do not fit SHALL be listed by name and nothing already mapped SHALL change.

#### Scenario: Servo drive
- **WHEN** the user runs "Map CiA 402 objects" on an axis node whose EDS has all eleven standard objects, writable mapping and four RPDOs and TPDOs, with nothing mapped
- **THEN** all eleven objects are mapped with locations of the right IEC types and the axis check passes

#### Scenario: Does not fit
- **WHEN** the EDS has no 0x6077 object
- **THEN** the action maps the others and says 0x6077 is not in the EDS

### Requirement: Map CiA 402 objects on a fixed-mapping device
For a device whose PDO mapping the master cannot change, "Map CiA 402 objects" SHALL only give suggested locations to the standard objects already in the device's mapping and SHALL list the missing ones.

#### Scenario: Fixed mapping
- **WHEN** the device's fixed RPDO 1 holds 0x6040 and 0x60FF and the action runs
- **THEN** both get locations and the other standard outputs are listed as not in the device's mapping

### Requirement: Axis lines in the declarations
For an axis node the located variable declarations SHALL also offer the axis and bridge declarations and the bridge call lines the project generator writes, ready to copy into an existing project.

#### Scenario: Copy axis lines
- **WHEN** node `drive` is an axis
- **THEN** the declarations panel shows the `drive : AXIS_REF_SM3;` and `drive_bridge` declarations and the call of `drive_bridge` with the node's mapped objects
