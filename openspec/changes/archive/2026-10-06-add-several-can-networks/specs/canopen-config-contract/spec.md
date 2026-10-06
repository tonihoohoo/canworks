# Spec Delta

## MODIFIED Requirements

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

## ADDED Requirements

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
The repository SHALL publish `schema/canopen.v2.schema.json`. Its adapter, master and node definitions SHALL be the version 1 definitions, referenced rather than copied, so an optional field added to version 1 is accepted in version 2 too. Every example config SHALL validate against the schema of its own version.

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
