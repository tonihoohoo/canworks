## MODIFIED Requirements

### Requirement: Machine file contract
The repository SHALL publish a JSON Schema (draft 2020-12) for the machine file, `schema_version` 1:
- `name` and `kind` (`gantry_xyz` in this version), units `mm`, and an optional step `tick_ms`;
- `joints` keyed by name, each with `node`, `travel`, `counts_per_mm`, optional offset and direction, `home_flag`, `limits`, `hard_stops`, `load` and `brake`;
- `tool`, `parts`, `conveyors`, `sensors` and `fixtures`;
- optional `panel` with `buttons` (`name`, `label`, `key`, `kind` `momentary`, `switch` or `latching`, `input`) and `lamps` (`name`, `label`, `output`);
- optional `safety` with `relay` (`inputs` naming latching buttons and scanners, `reset` naming a button, `stop_delay_ms`, `joints`, `conveyors`, `feedback`) and `scanners` (`name`, `at`, `warning` and `protective` boxes, `warning_output`);
- `visual` for the configurator only.

Every I/O binding SHALL be written as `node`, `object` and `bit`, as in scenario conditions. The deploy tool SHALL carry the machine file into the upload with the simulation file.

#### Scenario: Bundle
- **WHEN** a project with a machine file is deployed
- **THEN** the upload contains `machine.json` next to `simulation.json` and the runtime loads it

#### Scenario: Panel in the schema
- **WHEN** an editor with JSON Schema support opens a machine file and adds a button with kind `toggle`
- **THEN** the schema marks the kind and offers `momentary`, `switch` and `latching`

### Requirement: Machine file checks
Beyond the schema, the PC tools and the plugin SHALL check that:
- each joint's node is a simulated node of the network with an `axis`;
- each bound object exists in that node's EDS with a data type the bit fits;
- outputs are objects the master writes and inputs are objects it does not write;
- no input bit is bound twice, counting panel buttons, the relay feedback and scanner warning outputs;
- travel, limits and hard stops are in order;
- every part kind used is defined;
- panel button and lamp names are unique, and no two buttons have the same key, and no button uses Tab or Escape;
- the relay's inputs name latching buttons or scanners, its reset names a momentary button, and its joints and conveyors exist;
- each scanner's protective field lies inside its warning field.

A file that fails a check SHALL be refused with the network, the element and the reason.

#### Scenario: Joint on a node without an axis
- **WHEN** joint `x` names node 10, the I/O module
- **THEN** the check fails naming joint `x`, node 10 and that it has no `axis`

#### Scenario: Input written by the master
- **WHEN** the pick sensor's output is bound to 0x6200:1 bit 3 of node 10, an object in an RPDO
- **THEN** the check fails naming the sensor and that the master writes that object

#### Scenario: Same key twice
- **WHEN** buttons `gripper` and `gate` both use key G
- **THEN** the check fails naming both buttons and the key

#### Scenario: Momentary emergency stop
- **WHEN** the relay's inputs name a button of kind `momentary`
- **THEN** the check fails naming the button and that an emergency stop must be latching
