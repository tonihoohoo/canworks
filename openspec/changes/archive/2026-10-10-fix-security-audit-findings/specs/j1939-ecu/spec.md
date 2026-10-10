## ADDED Requirements

### Requirement: Request replies are rate-limited
The network SHALL answer Requests for the same PGN from the same requester at most once every 50 ms; Requests in between SHALL be ignored. Before sending Cannot Claim in answer to a Request for Address Claimed, the network SHALL wait a pseudo-random 0 to 153 ms.

#### Scenario: Request flood
- **WHEN** ECU 3 requests PGN 65281 every 5 ms
- **THEN** the network answers at most every 50 ms

### Requirement: Failed sends stay pending
An on-change send of a TX PGN that the interface refuses SHALL NOT count as sent: the PGN SHALL be sent with its current values once the interface takes frames again.

#### Scenario: Interface busy on a change
- **WHEN** the program changes a TX PGN's signal while the interface's transmit queue is full
- **THEN** the PGN with the new value goes out once the queue has room
