## ADDED Requirements

### Requirement: Signal valid bits on bus loss
When the bus is lost, every received signal's valid bit SHALL go FALSE along with the message status bits.

#### Scenario: Interface down
- **WHEN** a received PGN has signals with `valid_location` and the interface goes down
- **THEN** the valid bits are FALSE

### Requirement: Not-available values
Signed signals SHALL NOT be checked for not-available or error values. Unsigned 8, 16 and 32-bit signals SHALL use the J1939-71 ranges for error and not available; other lengths use all ones and all ones minus one. The plugin and the PC simulator SHALL follow the same rule.

#### Scenario: Signed -1
- **WHEN** a signed 16-bit signal reads 0xFFFF
- **THEN** the plugin and the simulator both treat it as -1, valid

#### Scenario: Unsigned error range
- **WHEN** an unsigned 16-bit signal reads 0xFE50
- **THEN** it is treated as an error value

### Requirement: Request answers
A Request to the global address for a PDU1 PGN SHALL be answered to the global address, and a destination-specific Request to the requester, in the plugin and the PC simulator. A `J1939_REQUEST` SHALL complete only on an answer addressed to the PLC's address or global.

#### Scenario: Global request
- **WHEN** another ECU sends a global Request for an on-change PDU1 PGN the PLC sends
- **THEN** the answer goes to the global address
