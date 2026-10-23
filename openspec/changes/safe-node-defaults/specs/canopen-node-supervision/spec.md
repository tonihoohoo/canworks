## ADDED Requirements

### Requirement: Nodes not protected against a bridge stop
A node SHALL count as protected against a lost master when `heartbeat_consumer` is true, or its EDS default 0x1016 has an entry with the master's node ID and a time above 0 that the config does not clear, or one of its RPDOs has an `event_timer_ms` above 0 (given or from the EDS). For every node with output entries (RPDO entries with an `iec_location`, or the consumer RPDO of a PDO link) that is not protected, the bridge SHALL log one warning at load naming the node and saying that it keeps its last outputs when the bridge stops without a clean stop (crash, power loss), and how to make it react (`heartbeat_consumer`, or an RPDO `event_timer_ms`). `canworks-deploy --check` SHALL print the same warning. The warning SHALL NOT refuse the config, and the bridge SHALL NOT change what an unset field writes to the node.

#### Scenario: Valve node with nothing set
- **WHEN** node 23 has RPDO entries, no `heartbeat_consumer`, an EDS 0x1016 with no entry for the master and no RPDO event timer
- **THEN** the bridge starts, its log has one warning naming node 23 and `heartbeat_consumer`, and `canworks-deploy --check` prints the same warning and exits 0

#### Scenario: Protected node
- **WHEN** node 23 has `"heartbeat_consumer": true`
- **THEN** there is no such warning for node 23

#### Scenario: Input-only node
- **WHEN** node 5 has only TPDO entries
- **THEN** there is no such warning for node 5

#### Scenario: Crash with a protected node
- **WHEN** node 23 has `"heartbeat_consumer": true`, the master heartbeat is 100 ms with multiplier 3, and the bridge is killed with SIGKILL
- **THEN** about 300 ms later node 23 acts per its 0x1029 error behaviour (for example enters pre-operational) and stops applying its RPDO values
