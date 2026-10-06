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
