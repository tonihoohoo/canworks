## MODIFIED Requirements

### Requirement: Plan settings per node
The plan SHALL hold, per node, its node ID, a name that is a valid IEC 61131-3 identifier, its DCF path, its CODESYS device settings (node ID, optional or mandatory, do not initialize, restore before configuring, SDO timeout) and its PDO channels with PDO mapping object, index, sub-index and variable name. A channel SHALL be planned for every mapped PDO entry, with or without an IEC location. Variable names SHALL be the names the editor declarations give the same entries, using the entry's `name` when it has one.

#### Scenario: Variable names match the editor
- **WHEN** node `dio` maps 0x6000 sub 1 to `%IB8` and the editor declarations name that location `dio_Read_input_8_bit_1`
- **THEN** the plan's channel for input 0x6000 sub 1 of `dio` has that variable name

#### Scenario: Entry without a location
- **WHEN** a CODESYS config's node `dio` maps 0x6000 sub 1 with `name` `door_open` and no `iec_location`
- **THEN** the plan has a channel for input 0x6000 sub 1 of `dio` named `dio_door_open`

### Requirement: CODESYS network number
A network's CODESYS network number SHALL come from the user's override for that network when given, else the network's `codesys.net_id`, else the interface's trailing number, else 0 with a `not_carried` note.

#### Scenario: Number from the interface
- **WHEN** network `field` runs on `can1`, has no `codesys.net_id` and no override is given
- **THEN** the plan gives `field` network number 1

#### Scenario: Number from the config
- **WHEN** network `field` runs on `can1` and has `codesys.net_id` 0
- **THEN** the plan gives `field` network number 0

#### Scenario: Override
- **WHEN** the user gives `field=2` for a network with `codesys.net_id` 0
- **THEN** the plan gives `field` network number 2

### Requirement: Settings that do not carry over
Every set config value that the relevance table of `canopen-config-contract` marks as not used by CODESYS SHALL be in the plan's `not_carried` list with where it is set and the table's reason, the same text the check's warning gives.

#### Scenario: Plugin-only status location
- **WHEN** node `rtd` has `emcy_code_location` `%IW20`
- **THEN** `not_carried` lists `emcy_code_location` for `field/rtd` with the reason the check gives for it
