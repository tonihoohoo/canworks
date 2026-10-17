## ADDED Requirements

### Requirement: PDO test needs the whole mapping
The PDO test SHALL leave out, with a note, a PDO whose mapping entries cannot all be read, instead of packing the readable ones.

#### Scenario: One entry times out
- **WHEN** the read of 0x1600 sub 2 times out
- **THEN** RPDO 1 is not offered for the test and the note names the entry

### Requirement: Restore with hold keeps the state
On a USB adapter, a restore with `--hold-preop` SHALL start the node afterwards only if it was OPERATIONAL before.

#### Scenario: Node was pre-operational
- **WHEN** a node is PRE-OPERATIONAL and is restored with the hold
- **THEN** it stays PRE-OPERATIONAL and the result says so
