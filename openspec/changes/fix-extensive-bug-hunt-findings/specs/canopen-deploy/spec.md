## ADDED Requirements

### Requirement: Into-project keeps the config's files
`--into-project` SHALL copy every DBC file the config names and each EDS's notes file, and with `--force` SHALL keep the old `canworks/` folder as a dated backup instead of deleting it.

#### Scenario: J1939 config
- **WHEN** a J1939 config naming `machine.dbc` is moved into a project
- **THEN** the project's `canworks/` folder has `machine.dbc`

#### Scenario: Refresh with force
- **WHEN** the project's own config is moved again with `--force`
- **THEN** the old folder is kept as `canworks.bak-<time>`
