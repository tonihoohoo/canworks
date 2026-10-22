## ADDED Requirements

### Requirement: Time since a node was last heard
The status answer SHALL give, for each configured node, the milliseconds since any frame was last received from it (heartbeat, boot-up, emergency, a TPDO or an SDO answer), or none when nothing has been received since the session started. `canworks-diag status` SHALL print it per node.

#### Scenario: Node with a heartbeat
- **WHEN** node 23 sends a heartbeat every 100 ms
- **THEN** the status answer gives node 23 a last-heard time under 200 ms

#### Scenario: Node switched off
- **WHEN** node 23 is switched off and 5 s pass
- **THEN** the status answer gives node 23 a last-heard time of at least 5000 ms
