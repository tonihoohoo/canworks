## ADDED Requirements

### Requirement: Node-to-node heartbeat watch
A node MAY give `heartbeat_watch`, a list of `{ "node": <id>, "timeout_ms": <ms> }`. For each entry the plugin SHALL write one heartbeat consumer entry (0x1016, CiA 301) into that node's configuration download, after dcfgen's own writes: the entry that already names the watched node, else the first unused entry that is not the one watching the master. `timeout_ms` SHALL default to the watched node's heartbeat timeout as the master uses it (`heartbeat_timeout_ms`, else three times its effective heartbeat period). The plugin SHALL reject the configuration, naming the node, the entry and the reason, when the watched node is not a configured node of the same network, is the node itself or the master, has no heartbeat (node guarding, or an effective 0x1017 of 0), when `timeout_ms` is not above the watched node's heartbeat period, or when the node's EDS has no 0x1016 or too few writable entries. The master's own supervision of either node SHALL NOT change.

#### Scenario: Consumer watches its producer
- **WHEN** node 20 has `"heartbeat_watch": [{ "node": 10 }]`, node 10 has `heartbeat_ms` 100 and no `heartbeat_timeout_ms`
- **THEN** node 20's download writes a 0x1016 entry with node ID 10 and 300 ms

#### Scenario: Next to the master's entry
- **WHEN** node 20 also has `"heartbeat_consumer": true` and dcfgen puts the master's entry in 0x1016 sub 1
- **THEN** the watch of node 10 goes to the next unused sub-index, and sub 1 still watches the master

#### Scenario: Watched node without heartbeat
- **WHEN** node 20 watches node 10 and node 10 uses node guarding
- **THEN** the configuration is rejected naming node 20, `heartbeat_watch` and that node 10 sends no heartbeat

#### Scenario: Not enough entries
- **WHEN** node 20's EDS 0x1016 has one entry, `heartbeat_consumer` is true and node 20 watches node 10
- **THEN** the configuration is rejected naming node 20, its EDS and that 0x1016 has room for 1 entry where 2 are needed

#### Scenario: Startup SDO overrides the watch
- **WHEN** node 20 has a `heartbeat_watch` and a startup SDO writing 0x1016
- **THEN** the plugin warns that the startup SDO runs last and overrides `heartbeat_watch`

## MODIFIED Requirements

### Requirement: Nodes on PLC stop
The master SHALL support `master.on_plc_stop`: `"preop"` (default) sends ENTER PRE-OPERATIONAL, `"stop"` sends STOP, each to every configured node that is up, before the network closes when the PLC stops or the plugin stops; `"keep"` sends no NMT command. Nodes of a PDO link with `"on_plc_stop": "keep"` (canopen-pdo-links) SHALL get no NMT command whatever the master's setting. No output PDO SHALL be sent between the stop request and the NMT command. On the next PLC start the nodes SHALL be booted and started as usual.

#### Scenario: PLC stopped
- **WHEN** nodes 5 and 23 are OPERATIONAL and the PLC is stopped with the default `on_plc_stop`
- **THEN** both nodes get ENTER PRE-OPERATIONAL before the network closes, and are OPERATIONAL again after the next PLC start

#### Scenario: Old behaviour
- **WHEN** `on_plc_stop` is `"keep"` and the PLC is stopped
- **THEN** no NMT command is sent

#### Scenario: Kept link
- **WHEN** `on_plc_stop` is `"preop"`, nodes 10 and 20 form a link with `"on_plc_stop": "keep"`, node 5 is in no link, and the PLC is stopped
- **THEN** node 5 gets ENTER PRE-OPERATIONAL, nodes 10 and 20 get no NMT command, and the log says which nodes were left running for which link
