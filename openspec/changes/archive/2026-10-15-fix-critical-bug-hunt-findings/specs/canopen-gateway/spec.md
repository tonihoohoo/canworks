## ADDED Requirements

### Requirement: Upper master loss at network start
When a gateway network's bus session starts while the upper master is lost, the configured upper-loss behaviour SHALL apply at once, as it does when the loss is first seen.

#### Scenario: Link drop while the upper master is gone
- **WHEN** the upper master is lost with `stop_nodes` behaviour and the lower network's interface goes down and comes back
- **THEN** the lower nodes are held as `stop_nodes` says once they are configured

### Requirement: Routed object not also an unlocated RPDO entry
A config SHALL be refused when a gateway route's object is also mapped in an RPDO entry of the same node that has no `iec_location`, naming the route and the entry.

#### Scenario: Object in a TPDO and an RPDO
- **WHEN** object 0x6000:1 of node 5 is in a TPDO and in an RPDO entry without `iec_location`, and a route names 0x6000:1
- **THEN** the config is refused naming the route and the RPDO entry
