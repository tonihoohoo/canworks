## MODIFIED Requirements

### Requirement: Input PDO timeout detection
A monitored PDO SHALL count as timed out when, while its node is up (master and node OPERATIONAL), no PDO has arrived within `timeout_ms` after the last received one, or within `timeout_ms` after the node came up when none has arrived since. The plugin SHALL check this itself on every bus cycle, so detection SHALL NOT depend on the master's own deadline timer and SHALL work alike on a SocketCAN interface and on the simulated bus, for event-driven and synchronous PDOs. The next received PDO SHALL end the timeout. While its node is not up a PDO SHALL NOT count as timed out. A timeout SHALL NOT change the node's status bit, state byte, outputs or boot state.

#### Scenario: Event-driven PDO stops
- **WHEN** node 23's TPDO 1 has `"timeout_ms": 500`, the node keeps its heartbeat and stops sending TPDO 1
- **THEN** about 500 ms after its last TPDO 1 the PDO counts as timed out and node 23's status bit stays TRUE

#### Scenario: Synchronous PDO stops on the simulated bus
- **WHEN** simulated node 5's TPDO 1 (transmission type 1, `"timeout_ms": 200`) has been received for a while and the simulator's "TPDO stop 1" fault stops it
- **THEN** within about 300 ms TPDO 1 counts as timed out, its timeout bit reads TRUE, the log has one "no PDO" warning, and node 5 stays OPERATIONAL

#### Scenario: PDO never arrives
- **WHEN** node 23 goes OPERATIONAL but never sends its TPDO 1 with `"timeout_ms": 500`
- **THEN** TPDO 1 counts as timed out within about 600 ms of the node being up

#### Scenario: Node lost
- **WHEN** node 23 with a timed-out TPDO 1 loses its heartbeat
- **THEN** TPDO 1 no longer counts as timed out and nothing more is logged for it until the node is up again
