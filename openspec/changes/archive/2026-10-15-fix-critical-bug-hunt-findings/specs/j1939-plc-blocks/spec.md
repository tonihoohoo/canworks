## ADDED Requirements

### Requirement: Receivers opened at any time
A `J1939_RECEIVE` opened at any moment, also while the bus thread is updating the network's receivers, SHALL get its queue and receive matching messages within a few bus-thread ticks.

#### Scenario: Two tasks open receivers
- **WHEN** two PLC tasks each open a `J1939_RECEIVE` on the same network in the same millisecond
- **THEN** both receivers become active and each gets its matching messages

### Requirement: Long sends get their own result
A long `J1939_SEND` SHALL end with the result of its own transport session. A late result of a send that already ended (for example by its `TIMEOUT`) SHALL NOT be given to any other send. When the network changes its address and its sockets are reopened, sends in progress SHALL end with `ERROR_ID` 14 at once.

#### Scenario: Timed-out send followed by another
- **WHEN** a 200-byte send to 0x10 ends with `ERROR_ID` 6, and a 200-byte send to 0x20 starts before 0x10's session finishes
- **THEN** the second send ends with the result of its own session to 0x20
