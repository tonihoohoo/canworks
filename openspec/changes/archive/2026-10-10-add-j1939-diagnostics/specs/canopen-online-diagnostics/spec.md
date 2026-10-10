## MODIFIED Requirements

### Requirement: J1939 network status
For a J1939 network, a status request SHALL return, as of no more than 100 ms before the answer: the claim state, current address and own NAME; the ECUs seen with address, NAME and time since last message; for each `rx` entry its PGN, source filter, sources seen, milliseconds since the last message, timeout state and timeout count; for each `tx` entry its PGN, messages sent and requests answered; the diagnostic messages state: for each source that sent DM1 its lamps, flash, codes (SPN, FMI, OC, CM), codes beyond the stored ones, time since its last DM1 and whether it uses the older SPN format, and, when the network sends its own DM1, its active and previously active codes with counts, the clears carried out and whether DM13 has suspended broadcasts; and the bus state and error counters as for CANopen networks.

#### Scenario: Timed-out PGN without a location
- **WHEN** PGN 65280 has `timeout_ms` 300 and no `status_location`, and it has stopped arriving
- **THEN** the status answer shows it timed out with a count of at least 1, and `canworks-diag status --network machine` prints a line saying so

#### Scenario: Two senders of one PGN
- **WHEN** ECUs 0 and 3 both send PGN 65280 and the `rx` entry has no source filter
- **THEN** the status answer lists sources 0 and 3 for that entry

#### Scenario: ECU with a fault
- **WHEN** ECU 0 sends DM1 with one code and no `diagnostics.rx` entry watches it
- **THEN** the status answer lists source 0 with its lamps and the code

## ADDED Requirements

### Requirement: DM read and clear operations
The diagnostics channel SHALL offer, on a J1939 network that holds an address, `j1939_dm_read` (send a Request for DM2 to an address and return the answer) and `j1939_dm_clear` (send a Request for DM3 or DM11 to an address or globally and return the ACK, NACK or "sent" for global). `j1939_dm_clear` SHALL be refused without `force`. Only one read or clear per destination SHALL be pending on a network at a time, shared with the PLC blocks; another SHALL be answered "busy". Both SHALL be refused on networks of other protocols.

#### Scenario: Clear through the PLC
- **WHEN** a client sends `j1939_dm_clear` for address 0 with `force` and ECU 0 answers ACK
- **THEN** the answer says ACK from 0

#### Scenario: Busy
- **WHEN** a PLC block is waiting for ECU 0's DM2 answer and a client sends `j1939_dm_read` for address 0
- **THEN** the client gets "busy" and the block's read is not disturbed
