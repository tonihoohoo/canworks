## ADDED Requirements

### Requirement: PLC inputs while the bridge is lost
For the OpenPLC, truST and Other PLC connections, the generated `canworks_in` SHALL, while `canworks.ok` is FALSE, set every typed input that comes from a node status bit, a node state byte, the master's state or bus state, or a live list to 0. The other typed inputs SHALL follow the connection's `inputs_on_loss`: `"hold"` (default) keeps their last values, `"zero"` sets them to 0. The connection row SHALL offer the choice as "Inputs when the bridge is lost: keep last values / set to 0", and a change SHALL mark the connection's files out of date. When the Node-RED connection's value nodes exist (nodered-blocks), they SHALL follow the same rule.

#### Scenario: Bridge killed under OpenPLC
- **WHEN** the bridge is killed while OpenPLC runs a program with node 23's status bit and an analogue input, with the default `inputs_on_loss`
- **THEN** within the stale time `canworks.ok` is FALSE, node 23's status bit is FALSE, and the analogue input keeps its last value

#### Scenario: Zero on loss
- **WHEN** the same happens with `"inputs_on_loss": "zero"`
- **THEN** the analogue input reads 0 as well

### Requirement: Bus state for the PLC
The `canworks` global variable list of a PLC-link connection SHALL have `bus_ok` (BOOL), which the generated `canworks_in` SHALL set TRUE while `canworks.ok` is TRUE and status block byte 7 bit 1 is clear (modbus-bridge "Bus flag in the status block").

#### Scenario: Cable fault
- **WHEN** the bridge's CAN interface goes down while the PLC runs
- **THEN** `canworks.ok` stays TRUE and `canworks.bus_ok` becomes FALSE, and both are TRUE again after the interface is back
