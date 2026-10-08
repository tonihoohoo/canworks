## ADDED Requirements

### Requirement: J1939 network status
For a J1939 network, a status request SHALL return, as of no more than 100 ms before the answer: the claim state, current address and own NAME; the ECUs seen with address, NAME and time since last message; for each `rx` entry its PGN, source filter, sources seen, milliseconds since the last message, timeout state and timeout count; for each `tx` entry its PGN, messages sent and requests answered; and the bus state and error counters as for CANopen networks.

#### Scenario: Timed-out PGN without a location
- **WHEN** PGN 65280 has `timeout_ms` 300 and no `status_location`, and it has stopped arriving
- **THEN** the status answer shows it timed out with a count of at least 1, and `opencan-diag status --network machine` prints a line saying so

#### Scenario: Two senders of one PGN
- **WHEN** ECUs 0 and 3 both send PGN 65280 and the `rx` entry has no source filter
- **THEN** the status answer lists sources 0 and 3 for that entry
