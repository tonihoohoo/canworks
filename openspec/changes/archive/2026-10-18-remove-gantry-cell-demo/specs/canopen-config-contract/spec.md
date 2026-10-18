## MODIFIED Requirements

### Requirement: Simulation file version 2
The repository SHALL publish a JSON Schema (draft 2020-12) for simulation file version 2: `schema_version` 2, an optional top-level `tick_ms`, and `networks`, an object whose keys are network names and whose values each allow `nodes`, `extra_devices` and `scenarios` exactly as in version 1. The plugin and the PC tools SHALL accept versions 1 and 2. A version 2 file SHALL be refused, naming the section, when a section names a network that is not in the config; a section for a network that simulates nothing SHALL be kept without error, as behaviour for a real node is. The checks the schema cannot express SHALL run per section against that network's nodes and EDS files, and their messages SHALL name the network.

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
- **WHEN** a version 2 section has `"machine": "machine.json"`
- **THEN** the check fails naming the section and the unknown key `machine`

#### Scenario: Gateway example validates
- **WHEN** `config/gateway/canopen_config.json` is checked against the version 2 schema
- **THEN** it validates

## REMOVED Requirements

### Requirement: Machine file contract
**Reason**: The machine file existed only for the gantry cell demo, which is removed.
**Migration**: None; the project is not in real use. `schema/canworks-sim-machine.v1.schema.json` is deleted.

### Requirement: Machine file checks
**Reason**: The machine file existed only for the gantry cell demo, which is removed.
**Migration**: None.
