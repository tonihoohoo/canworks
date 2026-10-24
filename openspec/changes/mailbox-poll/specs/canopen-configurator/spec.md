## MODIFIED Requirements

### Requirement: OpenPLC project page
A bridge config's OpenPLC connection SHALL have **Settings** on its row, opening the poll period (`poll_ms`, placeholder 10), the mailbox poll (with mailboxes only), the remote device name and the first editor location, with facts from the saved config: the remote device and port, the poll with requests per poll ("6 Modbus requests every 10 ms, 2 more every 50 ms" with mailboxes) and the warning above 40, the writer-loss time, the map hash and the first editor `%IW`/`%QW`.

The mailbox poll SHALL offer the multiples of `poll_ms` among 10, 20, 50, 100 and 200 ms, show the default as its placeholder and save nothing when left at it. Its hint SHALL give the round trip of a mailbox block (2 to 3 mailbox polls plus the bus) and the frames per second the receive mailbox keeps up with (frames per batch × 1000 / (2 × mailbox poll)), and say that a faster mailbox poll costs more PLC CPU. A change SHALL mark the connection Out of date and be one undo step.

#### Scenario: Requests per poll
- **WHEN** a config with an OpenPLC connection has 30 nodes with two TPDOs and two RPDOs each, none contiguous
- **THEN** the OpenPLC connection's settings show the request count above 40 with the warning, and Problems lists it

#### Scenario: Mailbox poll hint
- **WHEN** a config with the default mailboxes (one receive block) and an OpenPLC connection with `poll_ms` 10 opens the connection's Settings
- **THEN** the mailbox poll shows placeholder 50 and the hint says mailbox blocks answer in about 100-150 ms plus the bus and the receive mailbox keeps up with about 90 frames per second

#### Scenario: No mailboxes
- **WHEN** the config has no `bridge.mailboxes`
- **THEN** the Settings show no mailbox poll and the requests line names only the requests every poll
