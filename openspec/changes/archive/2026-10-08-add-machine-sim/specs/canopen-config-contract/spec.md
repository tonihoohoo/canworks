## MODIFIED Requirements

### Requirement: Simulation file version 2
The repository SHALL publish a JSON Schema (draft 2020-12) for simulation file version 2: `schema_version` 2, an optional top-level `tick_ms`, and `networks`, an object whose keys are network names and whose values each allow `nodes`, `extra_devices` and `scenarios` exactly as in version 1, and an optional `machine`, the path of a machine file relative to the simulation file. The plugin and the PC tools SHALL accept versions 1 and 2. A version 2 file SHALL be refused, naming the section, when a section names a network that is not in the config; a section for a network that simulates nothing SHALL be kept without error, as behaviour for a real node is. The checks the schema cannot express SHALL run per section against that network's nodes and EDS files, and their messages SHALL name the network.

#### Scenario: Unknown network
- **WHEN** a version 2 simulation file has a section `drivez` and the config's networks are `io` and `drives`
- **THEN** the check fails naming `drivez` and the config's network names

#### Scenario: Check names the network
- **WHEN** the `motion` section has a source on an object node 4's EDS does not have
- **THEN** the check fails naming network `motion`, node 4 and the object

#### Scenario: Version 1 still valid
- **WHEN** the single-network `config/rtd-sensor` example with its version 1 `simulation.json` is checked
- **THEN** it passes as before

#### Scenario: Machine file missing
- **WHEN** the `motion` section names `machine.json` and there is no such file next to the simulation file
- **THEN** the check fails naming network `motion` and the missing file

## ADDED Requirements

### Requirement: Machine file contract
The repository SHALL publish a JSON Schema (draft 2020-12) for the machine file, `schema_version` 1:
- `name` and `kind` (`gantry_xyz` in this version), units `mm`, and an optional step `tick_ms`;
- `joints` keyed by name, each with `node`, `travel`, `counts_per_mm`, optional offset and direction, `home_flag`, `limits`, `hard_stops` and `load`;
- `tool`, `parts`, `conveyors`, `sensors` and `fixtures`;
- `visual` for the configurator only.

Every I/O binding SHALL be written as `node`, `object` and `bit`, as in scenario conditions. The deploy tool SHALL carry the machine file into the upload with the simulation file.

#### Scenario: Bundle
- **WHEN** a project with a machine file is deployed
- **THEN** the upload contains `machine.json` next to `simulation.json` and the runtime loads it

### Requirement: Machine file checks
Beyond the schema, the PC tools and the plugin SHALL check that:
- each joint's node is a simulated node of the network with an `axis`;
- each bound object exists in that node's EDS with a data type the bit fits;
- outputs are objects the master writes and inputs are objects it does not write;
- no input bit is bound twice;
- travel, limits and hard stops are in order;
- every part kind used is defined.

A file that fails a check SHALL be refused with the network, the element and the reason.

#### Scenario: Joint on a node without an axis
- **WHEN** joint `x` names node 10, the I/O module
- **THEN** the check fails naming joint `x`, node 10 and that it has no `axis`

#### Scenario: Input written by the master
- **WHEN** the pick sensor's output is bound to 0x6200:1 bit 3 of node 10, an object in an RPDO
- **THEN** the check fails naming the sensor and that the master writes that object
