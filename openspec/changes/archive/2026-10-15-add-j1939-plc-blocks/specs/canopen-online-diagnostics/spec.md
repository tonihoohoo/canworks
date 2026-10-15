## MODIFIED Requirements

### Requirement: J1939 network status
For a J1939 network, a status request SHALL return, as of no more than 100 ms before the answer: the claim state, current address and own NAME; the ECUs seen with address, NAME and time since last message; for each `rx` entry its PGN, source filter, sources seen, milliseconds since the last message, timeout state and timeout count; for each `tx` entry its PGN, messages sent and requests answered; the diagnostic messages state: for each source that sent DM1 its lamps, flash, codes (SPN, FMI, OC, CM), codes beyond the stored ones, time since its last DM1 and whether it uses the older SPN format, and, when the network sends its own DM1, its active and previously active codes with counts, the clears carried out and whether DM13 has suspended broadcasts; the program's J1939 blocks: open receivers with their PGN, queued and dropped messages, and the counts of program sends, aborted transfers and requests; and the bus state and error counters as for CANopen networks.

#### Scenario: Timed-out PGN without a location
- **WHEN** PGN 65280 has `timeout_ms` 300 and no `status_location`, and it has stopped arriving
- **THEN** the status answer shows it timed out with a count of at least 1, and `canworks-diag status --network machine` prints a line saying so

#### Scenario: Two senders of one PGN
- **WHEN** ECUs 0 and 3 both send PGN 65280 and the `rx` entry has no source filter
- **THEN** the status answer lists sources 0 and 3 for that entry

#### Scenario: ECU with a fault
- **WHEN** ECU 0 sends DM1 with one code and no `diagnostics.rx` entry watches it
- **THEN** the status answer lists source 0 with its lamps and the code

#### Scenario: Program receiver
- **WHEN** a `J1939_RECEIVE` for PGN 65300 is enabled and has dropped two messages
- **THEN** the status answer lists a receiver for PGN 65300 with 2 dropped
