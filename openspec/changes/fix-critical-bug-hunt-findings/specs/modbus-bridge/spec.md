## ADDED Requirements

### Requirement: NMT commands while a network is down
An NMT command from the bridge's control block SHALL be refused while the target network's bus session is down, and the control block SHALL report it as refused. At most 16 NMT commands SHALL wait per network.

#### Scenario: Command during an outage
- **WHEN** the CAN interface is down and a Modbus client writes a STOP command for node 5
- **THEN** the command is refused, and nothing is sent to node 5 when the interface comes back
