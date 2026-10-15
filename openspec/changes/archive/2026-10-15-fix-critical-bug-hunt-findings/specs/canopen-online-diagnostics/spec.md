## MODIFIED Requirements

### Requirement: DM read and clear operations
The diagnostics channel SHALL offer, on a J1939 network that holds an address, `j1939_dm_read` (send a Request for DM2 to an address and return the answer) and `j1939_dm_clear` (send a Request for DM3 or DM11 to an address or globally and return the ACK, NACK or "sent" for global). `j1939_dm_clear` SHALL be refused with "changes not allowed" unless diagnostics changes are allowed (`allow_changes`), and without `force`; `j1939_dm_read` SHALL also work on a read-only channel. Only one read or clear per destination SHALL be pending on a network at a time, shared with the PLC blocks; another SHALL be answered "busy". Both SHALL be refused on networks of other protocols.

#### Scenario: Clear through the PLC
- **WHEN** a client sends `j1939_dm_clear` for address 0 with `force` and ECU 0 answers ACK
- **THEN** the answer says ACK from 0

#### Scenario: Busy
- **WHEN** a PLC block is waiting for ECU 0's DM2 answer and a client sends `j1939_dm_read` for address 0
- **THEN** the client gets "busy" and the block's read is not disturbed

#### Scenario: Clear on a read-only channel
- **WHEN** diagnostics have `allow_changes` false and a logged-in client sends `j1939_dm_clear` for address 255 with `force`
- **THEN** the client gets "changes not allowed" and no DM11 Request is sent
