# canopen-config-contract Specification

## Purpose
Defines the CANopen JSON configuration as a stable, versioned contract shared by the plugin, the deploy tool, and any future editor GUI.

## Requirements

### Requirement: Versioned configuration format
The configuration file SHALL carry an integer `schema_version`. A file without `schema_version` SHALL be read as version 1. The plugin and the deploy tool SHALL reject a file whose `schema_version` is higher than the highest version they support, naming both versions.

#### Scenario: Version omitted
- **WHEN** a config has no `schema_version` field and is otherwise valid
- **THEN** it is read as version 1 and loads

#### Scenario: Version from the future
- **WHEN** a config has `schema_version: 2` and the plugin supports only version 1
- **THEN** the plugin logs an error naming version 2 and supported version 1, and stays inactive

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
