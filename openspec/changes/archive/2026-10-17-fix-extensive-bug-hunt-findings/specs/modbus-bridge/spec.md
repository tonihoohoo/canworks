## ADDED Requirements

### Requirement: Request buffer limit
The Modbus server SHALL read from a connection only while less than one frame is waiting, so a client that pipelines requests cannot grow memory or slow other clients.

#### Scenario: Pipelined reads
- **WHEN** one client sends read requests faster than replies drain
- **THEN** the bridge's memory stays flat and other clients keep their reply rate

### Requirement: Bridge builds against the pinned runtime
The bridge install and image SHALL build against the runtime release the project pins, with a checked archive hash.

#### Scenario: Hash mismatch
- **WHEN** the downloaded runtime archive's hash differs
- **THEN** the install stops with a message
