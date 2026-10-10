## ADDED Requirements

### Requirement: Every node is supervised or says why not
A configured node whose heartbeat consumer time is 0 (from `heartbeat_ms`, or from the EDS default of 0x1017 when `heartbeat_ms` is absent) and that has no node guarding SHALL make the config refused at load, with a message saying its loss would never be detected. A node with an explicit `"heartbeat_ms": 0` SHALL be accepted and SHALL get a warning at every start. The configurator's check SHALL do the same.

#### Scenario: Device without a heartbeat default
- **WHEN** node 7's EDS has 0x1017 default 0, the config has no `heartbeat_ms` and no guarding for node 7
- **THEN** the config is refused, naming node 7 and `heartbeat_ms`

#### Scenario: Unsupervised on purpose
- **WHEN** node 7 has `"heartbeat_ms": 0`
- **THEN** the config is accepted and each start logs a warning that node 7's loss is not detected

### Requirement: Nodes on PLC stop
The master SHALL support `master.on_plc_stop`: `"preop"` (default) sends ENTER PRE-OPERATIONAL, `"stop"` sends STOP, each to every configured node that is up, before the network closes when the PLC stops or the plugin stops; `"keep"` sends no NMT command. No output PDO SHALL be sent between the stop request and the NMT command. On the next PLC start the nodes SHALL be booted and started as usual.

#### Scenario: PLC stopped
- **WHEN** nodes 5 and 23 are OPERATIONAL and the PLC is stopped with the default `on_plc_stop`
- **THEN** both nodes get ENTER PRE-OPERATIONAL before the network closes, and are OPERATIONAL again after the next PLC start

#### Scenario: Old behaviour
- **WHEN** `on_plc_stop` is `"keep"` and the PLC is stopped
- **THEN** no NMT command is sent
