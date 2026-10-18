## MODIFIED Requirements

### Requirement: Schema file names
The JSON Schemas SHALL be published as `schema/canworks.v1.schema.json`, `schema/canworks.v2.schema.json`, `schema/canworks-sim.v1.schema.json` and `schema/canworks-sim.v2.schema.json`, and the `schema_version` values inside config files SHALL keep their meaning.

#### Scenario: Existing example
- **WHEN** `config/pingpong/canopen_config.json` (`schema_version` 1) is checked against `schema/canworks.v1.schema.json`
- **THEN** it validates

#### Scenario: Machine schema
- **WHEN** the repository and the PC tools package are listed
- **THEN** no file named `canworks-sim-machine.v1.schema.json` or `canworks-machine.v1.schema.json` is in either
