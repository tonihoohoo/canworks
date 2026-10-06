## ADDED Requirements

### Requirement: Simulation switches in the config
`canopen.json` version 1 SHALL accept an optional boolean `adapter.simulate` (the network is simulated), default false, and an optional boolean `simulate` on each node (the device is simulated), whose default is true on a simulated network and false on a real one. A config without them SHALL behave as before. The schema SHALL describe both, and the plugin and the deploy tool SHALL accept a config with simulated parts whose adapter would otherwise be valid.

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
The simulation file (`simulation.json`, next to `canopen.json`) SHALL carry its own integer `schema_version`, read as 1 when omitted, and the repository SHALL publish a JSON Schema (draft 2020-12) for it. The plugin, the standalone simulator and the PC tools SHALL reject a file whose version is higher than they support, naming both versions, and SHALL reject unknown keys. Checks the schema cannot express (objects that exist in the EDS, value sources on master-written objects, expression syntax and references) SHALL be documented next to it and run by the deploy tool's check as well as at load. Behaviour given for a node that is not simulated SHALL be kept and SHALL NOT be an error, so a node can be switched between real and simulated without editing the file.

#### Scenario: Unknown key
- **WHEN** a simulation file has `"nodes": {"5": {"sources": {...}, "sourcse": {...}}}`
- **THEN** it is rejected with a message naming `sourcse`

#### Scenario: Check without a runtime
- **WHEN** a user runs the deploy tool's check on a project whose simulation file has an expression with an unknown function
- **THEN** the check fails naming the node, the object and the function

#### Scenario: Behaviour for a real node
- **WHEN** the simulation file has sources for node 23 and node 23 is a real device in this config
- **THEN** the config loads, node 23 is not simulated, and the sources apply again when node 23 is switched to simulated
