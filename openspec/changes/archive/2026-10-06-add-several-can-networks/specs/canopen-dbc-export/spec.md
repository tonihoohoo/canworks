# Spec Delta

## MODIFIED Requirements

### Requirement: One DBC file for the configured network
The export SHALL produce one DBC file per network of the config, describing that network's nodes and frames only. It SHALL be built on the engineering PC from the config and the nodes' EDS files alone, with no PLC, runtime or CAN bus. Only a config that passes the deploy tool's existing checks (schema, EDS checks, EDS lint under the config's `eds_lint` setting) SHALL be exported; otherwise the export SHALL stop with those checks' messages and write nothing. The file SHALL be ASCII text with CRLF line endings and SHALL load in cantools with strict checking (no overlapping signals, every signal inside its message). With one network the export SHALL write the one file to the given path; with several it SHALL write `<stem>_<network>.dbc` per network next to the given path, or only the given path for `--network NAME`.

#### Scenario: Example config
- **WHEN** `config/rtd-sensor/canopen_config.json` is exported
- **THEN** the DBC has messages `rtd_TPDO1` (COB-ID 0x185, 8 bytes) and `rtd_TPDO2` (0x285, 4 bytes) plus node 5's heartbeat and EMCY, NMT and SYNC, and cantools loads it with `strict=True`

#### Scenario: Config with an error
- **WHEN** a TPDO number does not exist in the node's EDS
- **THEN** the export stops with the same message the deploy tool's checks give, and no DBC is written

#### Scenario: Two networks
- **WHEN** a config has networks `io` and `drives` and the user exports to `plant.dbc`
- **THEN** `plant_io.dbc` and `plant_drives.dbc` are written, each with only its own network's nodes, NMT and SYNC

#### Scenario: One network of two
- **WHEN** the user exports with `--network drives` to `drives.dbc`
- **THEN** only `drives.dbc` is written, with `drives`' nodes
