## ADDED Requirements

### Requirement: Scan watchdog trip lasts until the scan moves
A tripped scan watchdog SHALL keep the outputs gate closed until the PLC scan finishes a cycle again or the PLC stops, also when a bus session ends.

#### Scenario: Interface down while the scan is hung
- **WHEN** the scan watchdog tripped and one network's interface goes down
- **THEN** the gate stays closed for every other network

### Requirement: Program frames obey the outputs gate
While the outputs gate is closed, program cyclic jobs SHALL NOT send and SHALL resume at their period when it opens, and frames queued by `CAN_SEND` SHALL be dropped with the not-running error.

#### Scenario: Hung scan with a cyclic heartbeat
- **WHEN** a `CAN_SEND_CYCLIC` job sends a frame every 100 ms and the scan watchdog trips
- **THEN** the frame stops on the bus until the scan runs again

### Requirement: Scan watchdog for every protocol
A J1939 or plain CAN network SHALL accept `scan_watchdog_ms` (0 off, 10-60000, default 1000) under its `j1939` or `raw` block, so a project without a CANopen master also closes the outputs gate on a hung scan.

#### Scenario: J1939-only project
- **WHEN** a project has one J1939 network and the scan hangs for 1 s
- **THEN** periodic J1939 transmit messages stop
