## ADDED Requirements

### Requirement: Request replies and on-change messages
Answering a Request for a destination-specific message to the requester SHALL NOT count as sending it to the message's own destination: an on-change message whose value changed SHALL still be sent to its configured destination. Requests SHALL NOT be answered before the first PLC scan has written the outputs.

#### Scenario: Request before the change is sent
- **WHEN** an on-change message to 0x20 changes value and ECU 0x30 sends a Request for it before the next send
- **THEN** 0x30 gets the reply and 0x20 also gets the new value

#### Scenario: Request before the first scan
- **WHEN** a Request for a transmitted message arrives after the address is claimed but before the first PLC scan
- **THEN** no reply is sent
