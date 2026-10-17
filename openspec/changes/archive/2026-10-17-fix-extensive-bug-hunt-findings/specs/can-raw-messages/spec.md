## ADDED Requirements

### Requirement: Receive timeouts while the link is down
When the CAN interface is gone, every received message's status bit and every signal valid bit SHALL go FALSE, and timeouts SHALL keep running while the link is retried.

#### Scenario: Adapter unplugged
- **WHEN** a received message has `timeout_ms: 100` and the adapter is unplugged
- **THEN** its status and valid bits are FALSE within the timeout

### Requirement: On-change messages before the first trigger
An `on_change` message with a `trigger_location` SHALL be sent when its outputs change, also before the first trigger edge after a PLC start or gate reopen.

#### Scenario: Change after start
- **WHEN** the PLC starts and the program changes an output of such a message
- **THEN** the message is sent
