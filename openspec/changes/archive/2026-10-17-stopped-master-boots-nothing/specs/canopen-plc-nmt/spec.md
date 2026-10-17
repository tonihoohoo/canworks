## MODIFIED Requirements

### Requirement: A stopped master stays silent in later sessions
While `stop_all_nodes` holds the master STOPPED for the run, the master SHALL send only NMT STOP, its own heartbeat and EMCY, SDO requests and LSS frames, also in later bus sessions. It SHALL NOT reset or start any node, and SHALL NOT send SYNC, TIME or PDOs. It SHALL NOT boot any node: no SDO request of a node boot and no boot retry. SDO requests from the program, the diagnostics channel and the gateway SHALL still be sent. It SHALL report STOPPED, also when a mandatory node comes back.

#### Scenario: Mandatory node back after a link bounce
- **WHEN** the master was stopped by `stop_all_nodes`, the CAN interface goes down and up, and the lost mandatory node boots again
- **THEN** no reset of all nodes, NMT START or SYNC is sent, and the master's state stays STOPPED

#### Scenario: No boot of a stopped node
- **WHEN** the master was stopped by `stop_all_nodes`, the CAN interface goes down and up, and the lost mandatory node sends its boot-up
- **THEN** the node gets NMT STOP, and no SDO request goes to any node for the rest of the run unless the program or an operator sends one
