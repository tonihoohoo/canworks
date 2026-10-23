## ADDED Requirements

### Requirement: Mailbox use in the status
With mailboxes, the bridge's status answer SHALL have `bridge.mailboxes` with `operations` (mailbox operations started since the bridge started, including those a restart ends with ERROR_ID 8) and `receivers_opened` (receivers opened since the bridge started). Without mailboxes it SHALL have no `mailboxes` object.

#### Scenario: Used mailboxes
- **WHEN** a program has opened one CAN receiver and run 12 SDO reads through the mailboxes
- **THEN** the status has `operations` 13 and `receivers_opened` 1

### Requirement: Mailbox use in diag
`canworks-deploy diag` SHALL print the mailbox use as one line, "no mailboxes" without them. While both counts are 0 it SHALL add that nothing has used the mailboxes and that turning them off saves Modbus requests.

#### Scenario: Unused mailboxes
- **WHEN** a bridge with the default mailboxes has served for an hour an OpenPLC program that declares no mailbox block
- **THEN** `diag` prints "mailboxes: 0 operations, 0 receivers opened since start: nothing has used the mailboxes; turning them off saves Modbus requests"

#### Scenario: Used
- **WHEN** the status has `operations` 13 and `receivers_opened` 1
- **THEN** `diag` prints "mailboxes: 13 operations, 1 receiver opened since start"
