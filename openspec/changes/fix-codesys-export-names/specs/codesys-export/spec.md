## ADDED Requirements

### Requirement: Unique object names
Every CANbus, CANopen Manager and node object the script adds SHALL get a name that no other object in the project uses, adding `_2`, `_3`, ... to the base name when it is taken anywhere in the device tree, because CODESYS refuses a name used elsewhere in the tree.

#### Scenario: Three networks
- **WHEN** a config with networks `io`, `motion` and `host` is built into a new project with one PLC
- **THEN** all three networks are added, their managers are named `CANopen_Manager`, `CANopen_Manager_2` and `CANopen_Manager_3`, and the report has no error

#### Scenario: Node name taken in another network
- **WHEN** two networks each have a node named `drive`
- **THEN** the second becomes `drive_2` and the report says it kept that name

## MODIFIED Requirements

### Requirement: Plan settings per node
The plan SHALL hold, per node, its node ID, a name that is a valid IEC 61131-3 identifier, its DCF path, its CODESYS device settings (node ID, optional or mandatory, do not initialize, restore before configuring, SDO timeout, and the heartbeat producer time when the node has `heartbeat_ms`) and its PDO channels with PDO mapping object, index, sub-index and variable name. The heartbeat producer time SHALL be planned even when it equals the EDS default. A channel SHALL be planned for every mapped PDO entry, with or without an IEC location. Variable names SHALL be the names the editor declarations give the same entries, using the entry's `name` when it has one.

#### Scenario: Variable names match the editor
- **WHEN** node `dio` maps 0x6000 sub 1 to `%IB8` and the editor declarations name that location `dio_Read_input_8_bit_1`
- **THEN** the plan's channel for input 0x6000 sub 1 of `dio` has that variable name

#### Scenario: Entry without a location
- **WHEN** a CODESYS config's node `dio` maps 0x6000 sub 1 with `name` `door_open` and no `iec_location`
- **THEN** the plan has a channel for input 0x6000 sub 1 of `dio` named `dio_door_open`

#### Scenario: Heartbeat equal to the EDS default
- **WHEN** node `conveyor` has `heartbeat_ms` 50 and its EDS default for 0x1017 is 50
- **THEN** the plan's device settings for `conveyor` set the heartbeat producer to 50 ms, and the CODESYS device shows 50 ms after the build
