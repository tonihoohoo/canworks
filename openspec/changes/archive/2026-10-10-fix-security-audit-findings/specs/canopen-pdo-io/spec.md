## ADDED Requirements

### Requirement: Outputs sent again when a node comes up
When a node becomes up again (after a boot, a reboot it reported itself, or recovery from a loss), or when the outputs gate opens again, the master SHALL write the current values of that node's outputs to its PDOs before it enables them, and SHALL send each of the node's event-driven PDOs once, subject to inhibit time. With SYNC, the first synchronous PDO after the node is up SHALL carry the current values. Outputs that did not change SHALL otherwise not be sent again, as before.

#### Scenario: Device reboots while the program holds an output
- **WHEN** node 23's RPDO 1 is event-driven, the program holds `%QX20.0` TRUE, and node 23 resets and comes back
- **THEN** after node 23 is started again the master sends RPDO 1 with `%QX20.0` TRUE once, without the program changing it

#### Scenario: Node recovers on a SYNC network
- **WHEN** node 5 with a synchronous RPDO was lost while the program changed its outputs, and node 5 comes back
- **THEN** the first RPDO after node 5 is up carries the program's current values

### Requirement: Scan watchdog
The master SHALL support `master.scan_watchdog_ms` (10 to 60000, default 1000; 0 turns it off). While the PLC runs and its scan has not finished a cycle for that long, the outputs gate SHALL close: no RPDOs, raw or J1939 transmit messages. SYNC, inputs and node supervision SHALL keep running. The next finished scan SHALL open the gate and the outputs SHALL be sent again as when a node comes up. Closing and opening SHALL be logged.

#### Scenario: Program hangs
- **WHEN** the program's scan stops finishing cycles while the runtime keeps running and `scan_watchdog_ms` is 1000
- **THEN** about 1 s later the master stops sending RPDOs, SYNC keeps going, and the log names the scan watchdog
