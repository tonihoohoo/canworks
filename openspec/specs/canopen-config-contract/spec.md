# canopen-config-contract Specification

## Purpose
Defines the CANopen JSON configuration as a stable, versioned contract shared by the plugin, the deploy tool, and any future editor GUI.

## Requirements

### Requirement: Versioned configuration format
The configuration file SHALL carry an integer `schema_version`. A file without `schema_version` SHALL be read as version 1. The plugin and the deploy tool SHALL read versions 1 and 2. They SHALL reject a file whose `schema_version` is higher than the highest version they support, naming both versions.

#### Scenario: Version omitted
- **WHEN** a config has no `schema_version` field and is otherwise valid
- **THEN** it is read as version 1 and loads

#### Scenario: Version 2 loads
- **WHEN** a config has `schema_version: 2` and a valid `networks` list
- **THEN** the plugin and the deploy tool load it

#### Scenario: Version from the future
- **WHEN** a config has `schema_version: 3` and the plugin supports versions up to 2
- **THEN** the plugin logs an error naming version 3 and supported version 2, and stays inactive

### Requirement: Published JSON Schema
The repository SHALL publish a JSON Schema (draft 2020-12) for each supported config version. The schema SHALL describe every field the plugin reads, its type, and whether it is required. Any file the plugin accepts SHALL validate against the schema, and the checks the schema cannot express (EDS contents, overlapping locations, node ID uniqueness) SHALL be documented next to it.

#### Scenario: Example configs validate
- **WHEN** the schema is applied to every example config in the repository
- **THEN** each example validates without errors

#### Scenario: Plugin and schema agree
- **WHEN** a test config breaks a rule the schema expresses (wrong type, missing required field, value out of range)
- **THEN** both the schema validation and the plugin reject it

### Requirement: Compatibility rules within a version
Within one `schema_version`, a later release of the plugin SHALL accept every file an earlier release accepted, with the same meaning. New optional fields MAY be added within a version. Removing a field, making an optional field required, or changing a field's meaning SHALL require a new `schema_version`. Unknown fields SHALL be ignored with a warning naming the field, so that a file written for a newer minor release still loads.

#### Scenario: Unknown field
- **WHEN** a version 1 config contains a field the plugin does not know
- **THEN** the plugin logs a warning naming the field and its JSON path, and loads the rest of the config

### Requirement: Pre-contract keys
The plugin and the deploy tool SHALL accept the top-level `interface` and `bitrate` keys used before this contract, reading them as an `adapter` of type `socketcan` with `configure_link` false (as before the contract, the plugin leaves the link alone), and SHALL log a deprecation warning. A config that has both `adapter` and either top-level key SHALL be rejected.

#### Scenario: Old-style config
- **WHEN** a config has top-level `interface: "vcan0"` and `bitrate: 125000` and no `adapter`
- **THEN** it loads as a SocketCAN adapter on `vcan0` at 125 kbit/s and a deprecation warning is logged

#### Scenario: Both styles at once
- **WHEN** a config has an `adapter` object and a top-level `interface`
- **THEN** the config is rejected with an error naming both keys

### Requirement: Simulation switches in the config
`canworks.json` version 1 SHALL accept an optional boolean `adapter.simulate` (the network is simulated), default false, and an optional boolean `simulate` on each node (the device is simulated), whose default is true on a simulated network and false on a real one. A config without them SHALL behave as before. The schema SHALL describe both, and the plugin and the deploy tool SHALL accept a config with simulated parts whose adapter would otherwise be valid.

#### Scenario: Old config
- **WHEN** a config written before this change is loaded
- **THEN** it loads unchanged, runs on its real adapter and simulates nothing

#### Scenario: Simulated network validates
- **WHEN** the example ping-pong config with `adapter.simulate: true` is checked against the schema
- **THEN** it validates

#### Scenario: One simulated node validates
- **WHEN** a config on `can0` with `"simulate": true` on one node is checked against the schema
- **THEN** it validates

### Requirement: Simulation file contract
The simulation file (`simulation.json`, next to `canworks.json`) SHALL carry its own integer `schema_version`, read as 1 when omitted, and the repository SHALL publish a JSON Schema (draft 2020-12) for it. The plugin, the standalone simulator and the PC tools SHALL reject a file whose version is higher than they support, naming both versions, and SHALL reject unknown keys. Checks the schema cannot express (objects that exist in the EDS, value sources on master-written objects, expression syntax and references) SHALL be documented next to it and run by the deploy tool's check as well as at load. Behaviour given for a node that is not simulated SHALL be kept and SHALL NOT be an error, so a node can be switched between real and simulated without editing the file.

#### Scenario: Unknown key
- **WHEN** a simulation file has `"nodes": {"5": {"sources": {...}, "sourcse": {...}}}`
- **THEN** it is rejected with a message naming `sourcse`

#### Scenario: Check without a runtime
- **WHEN** a user runs the deploy tool's check on a project whose simulation file has an expression with an unknown function
- **THEN** the check fails naming the node, the object and the function

#### Scenario: Behaviour for a real node
- **WHEN** the simulation file has sources for node 23 and node 23 is a real device in this config
- **THEN** the config loads, node 23 is not simulated, and the sources apply again when node 23 is switched to simulated

### Requirement: Version 2 layout
A version 2 file SHALL have `schema_version: 2`, a `networks` list, and MAY have a top-level `diagnostics` object with the fields version 1 has under `master.diagnostics`. It SHALL NOT have top-level `adapter`, `master`, `nodes`, `interface` or `bitrate`, nor `diagnostics` inside a network's `master`; each is rejected with a message naming where it belongs in version 2.

#### Scenario: Version 1 keys in a version 2 file
- **WHEN** a file has `schema_version: 2` and a top-level `nodes` list
- **THEN** it is rejected with an error saying nodes belong in `networks[].nodes` in version 2

#### Scenario: Diagnostics inside a network
- **WHEN** a version 2 file has `networks[0].master.diagnostics`
- **THEN** it is rejected with an error saying `diagnostics` is a top-level object in version 2

#### Scenario: Empty node lists with diagnostics
- **WHEN** a version 2 file has a top-level `diagnostics` and a network with `"nodes": []`
- **THEN** it loads, that network running as a scan-only network

### Requirement: Version 2 schema shares version 1 definitions
The repository SHALL publish `schema/canworks.v2.schema.json`. Its adapter, master and node definitions SHALL be the version 1 definitions, referenced rather than copied, so an optional field added to version 1 is accepted in version 2 too. Every example config SHALL validate against the schema of its own version.

#### Scenario: Field added to version 1
- **WHEN** a new optional `master` field is added to the version 1 schema
- **THEN** a version 2 file with that field in a network's `master` validates without changing the version 2 schema file

### Requirement: Writers use the lowest version that holds the config
The configurator and every tool that writes a config SHALL write version 1 when the config has one network without a `name` of its own (none, or one equal to the interface name), and version 2 otherwise. Reading a file and saving it unchanged SHALL keep its meaning.

#### Scenario: One network saved
- **WHEN** the configurator saves a config with one network on `can0` and no custom name
- **THEN** the file is version 1 with top-level `adapter`, `master` (holding `diagnostics` if set) and `nodes`

#### Scenario: Second network added
- **WHEN** the user adds a second network and saves
- **THEN** the file is version 2 with both networks and a top-level `diagnostics` if online access is on

#### Scenario: Back to one network
- **WHEN** the user removes the second network of a version 2 config whose remaining network has no custom name, and saves
- **THEN** the file is written as version 1

### Requirement: Slave network role
A version 2 network MAY have `role`, `"master"` (default) or `"slave"`. A slave network SHALL have `adapter` and `slave`, and SHALL NOT have `master` or `nodes`; a master network SHALL NOT have `slave`. Each misplaced key SHALL be rejected with a message naming the role it belongs to. Version 1 files SHALL NOT have `role` or `slave`.

#### Scenario: Slave network with nodes
- **WHEN** a network has `"role": "slave"` and a `nodes` list
- **THEN** the file is rejected with an error saying nodes belong to a master network

#### Scenario: Slave in a version 1 file
- **WHEN** a version 1 file has a top-level `slave`
- **THEN** it is rejected with an error saying slave networks need `schema_version: 2`

### Requirement: Slave object
The `slave` object SHALL have `node_id` (1-127, or null for LSS) and `eds`, and MAY have `objects`, `inputs_on_loss` (`"hold"` default or `"zero"`), `state_location`, `comm_ok_location`, `sync_count_location`, `emcy_code_location` and `error_register_location`. Each `objects` entry SHALL have `index`, `subindex` and `iec_location`, and MAY have `name`. The JSON Schema SHALL describe all of these.

#### Scenario: Example validates
- **WHEN** `config/slave/canopen_config.json` is checked against `schema/canworks.v2.schema.json`
- **THEN** it validates

### Requirement: One role per interface
Two networks on the same real adapter interface SHALL be rejected whatever their roles, so a master and a slave never share one real bus in the plugin. Simulated networks (`adapter.simulate: true`) with the same `interface` name SHALL share one simulated bus, allowed for at most one master network and one slave network. On such a bus, the master network's node with the slave network's node ID SHALL have `simulate: false`, so no simulated device answers in place of the plugin's slave.

#### Scenario: Master and slave on can0
- **WHEN** a master network and a slave network both use `can0`
- **THEN** the file is rejected with an error naming the interface and both networks

#### Scenario: Master and slave on one simulated bus
- **WHEN** a master network and a slave network both have `adapter.simulate: true` and `interface: "bench"`
- **THEN** the file loads and both networks run on one in-process simulated bus named `bench`

#### Scenario: Two masters on one simulated bus
- **WHEN** two master networks are simulated with the same `interface`
- **THEN** the file is rejected with an error naming the interface and both networks

#### Scenario: The slave's node simulated on the master
- **WHEN** a master network and a slave network with node ID 10 share simulated bus `bench`, and the master's node 10 is simulated (its default on a simulated network)
- **THEN** the file is rejected with an error naming node 10, both networks and `"simulate": false`

### Requirement: Configs with a slave network are version 2
Tools that write a config SHALL write version 2 whenever any network is a slave network, even when it is the only network.

#### Scenario: Only a slave
- **WHEN** the configurator saves a config whose one network is a slave
- **THEN** the file has `schema_version: 2` and that network has `"role": "slave"`

### Requirement: Gateway section in the schema
`schema/canworks.v2.schema.json` SHALL describe the top-level `gateway` object (`upper`, `routes`, `status`, `emcy_forward`, `on_upper_loss`, `sdo_bridge`, `sdo_bridge_write`), and a version 1 file SHALL NOT have `gateway`.

#### Scenario: Gateway example validates
- **WHEN** `config/gateway/canopen_config.json` is checked against the version 2 schema
- **THEN** it validates

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

### Requirement: Raw messages in the schema
The version 2 JSON Schema SHALL describe protocol `none`, `adapter.listen_only` and the `raw` object with its `rx`, `tx` and signal entries, so an editor with JSON Schema support completes and checks them. Checks the schema cannot express (unique `tx` identifiers, signals inside the DLC, protocol ownership, location sizes and clashes) SHALL be made by the plugin and by the PC tools with the same messages, from shared test fixtures.

#### Scenario: Schema check of a raw message
- **WHEN** a config's `raw.rx` entry has `id` 0x800 without `extended`
- **THEN** the PC tools and the plugin both reject it naming the path and the 11-bit range

### Requirement: Configs with raw messages are version 2
A version 1 config SHALL NOT have `raw` or `listen_only`. Writers SHALL save version 2 whenever any network has `raw` or protocol `none`.

#### Scenario: Adding a raw message to a version 1 project
- **WHEN** the configurator adds a raw message to a project whose file is version 1
- **THEN** it saves the file as version 2 with one network holding the old content and the raw message
