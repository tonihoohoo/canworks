## ADDED Requirements

### Requirement: PLC inputs while the bridge is lost
For the OpenPLC, truST and Other PLC connections, the generated `canworks_in` SHALL, while `canworks.ok` is FALSE, set every typed input of a status, state or timeout location (a `*_location` field other than an entry's or signal's `iec_location`: node status bits and state bytes, the master's state and bus state, PDO timeout bits, raw and J1939 message status) to 0. The other typed inputs SHALL follow the connection's `inputs_on_loss`: `"hold"` (default) keeps their last values, `"zero"` sets them to 0. The connection row SHALL offer the choice as "Inputs when the bridge is lost: keep last values / set to 0", and a change SHALL mark the connection's files out of date. The Node-RED package's canworks in node SHALL follow the same rule when its connection to the bridge is lost: it sends 0 or false for those values, for every live-list `.operational` value and for `bridge.bus_ok`, and keeps the other values. A download made before a change of `inputs_on_loss` SHALL show as out of date (`stale` in the connection) until the next download.

#### Scenario: Bridge killed under OpenPLC
- **WHEN** the bridge is killed while OpenPLC runs a program with node 23's status bit and an analogue input, with the default `inputs_on_loss`
- **THEN** within the stale time `canworks.ok` is FALSE, node 23's status bit is FALSE, and the analogue input keeps its last value

#### Scenario: Zero on loss
- **WHEN** the same happens with `"inputs_on_loss": "zero"`
- **THEN** the analogue input reads 0 as well

### Requirement: Bus state for the PLC
The `canworks` global variable list of a PLC-link connection SHALL have `bus_ok` (BOOL), which the generated `canworks_in` SHALL set TRUE while `canworks.ok` is TRUE and status block byte 7 bit 1 is clear (modbus-bridge "Status block").

#### Scenario: Cable fault
- **WHEN** the bridge's CAN interface goes down while the PLC runs
- **THEN** `canworks.ok` stays TRUE and `canworks.bus_ok` becomes FALSE, and both are TRUE again after the interface is back
