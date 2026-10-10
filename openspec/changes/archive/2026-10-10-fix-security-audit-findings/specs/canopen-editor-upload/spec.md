## MODIFIED Requirements

### Requirement: CANopen config in the editor project
An editor project SHALL be able to carry its config as `canworks/canworks.json` at the project root, with every EDS file it names next to it or in a subfolder of `canworks/`. The file SHALL follow the same contract as the deploy tool's input, `schema_version` 1 or 2 (several networks, slave, gateway, J1939 and raw messages included), with `eds` paths relative to `canworks/`.

#### Scenario: Project layout
- **WHEN** a project folder contains `canworks/canworks.json` naming `eds: "rtd8.eds"` and `canworks/rtd8.eds` exists
- **THEN** the project carries a complete CANopen config

#### Scenario: Version 2 config
- **WHEN** a project's `canworks/canworks.json` is a version 2 config with two networks and a slave network, and it is sent with the editor's "Build and upload"
- **THEN** the runtime enables the plugin with that config and both networks run
