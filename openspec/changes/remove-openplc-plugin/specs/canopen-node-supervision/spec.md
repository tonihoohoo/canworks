## MODIFIED Requirements

### Requirement: Nodes on PLC stop
The master SHALL support `master.on_plc_stop`: `"preop"` (default) sends ENTER PRE-OPERATIONAL, `"stop"` sends STOP, each to every configured node that is up, before the network closes when the bridge stops or replaces its config; `"keep"` sends no NMT command. Nodes of a PDO link with `"on_plc_stop": "keep"` (canopen-pdo-links) SHALL get no NMT command whatever the master's setting. No output PDO SHALL be sent between the stop request and the NMT command. When the bridge starts again the nodes SHALL be booted and started as usual. What happens when the PLC (the Modbus client) stops is `on_client_loss` (modbus-bridge), not this setting.

#### Scenario: PLC stopped
- **WHEN** nodes 5 and 23 are OPERATIONAL and the bridge's service is stopped with the default `on_plc_stop`
- **THEN** both nodes get ENTER PRE-OPERATIONAL before the network closes, and are OPERATIONAL again after the next start

#### Scenario: Old behaviour
- **WHEN** `on_plc_stop` is `"keep"` and the bridge is stopped
- **THEN** no NMT command is sent

#### Scenario: Kept link
- **WHEN** `on_plc_stop` is `"preop"`, nodes 10 and 20 form a link with `"on_plc_stop": "keep"`, node 5 is in no link, and the bridge is stopped
- **THEN** node 5 gets ENTER PRE-OPERATIONAL, nodes 10 and 20 get no NMT command, and the log says which nodes were left running for which link
