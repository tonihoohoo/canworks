## ADDED Requirements

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
- **WHEN** `config/slave/canopen_config.json` is checked against `schema/canopen.v2.schema.json`
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
`schema/canopen.v2.schema.json` SHALL describe the top-level `gateway` object (`upper`, `routes`, `status`, `emcy_forward`, `on_upper_loss`, `sdo_bridge`, `sdo_bridge_write`), and a version 1 file SHALL NOT have `gateway`.

#### Scenario: Gateway example validates
- **WHEN** `config/gateway/canopen_config.json` is checked against the version 2 schema
- **THEN** it validates
