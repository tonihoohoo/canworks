## ADDED Requirements

### Requirement: Bit channels in the documents
The PDO details SHALL list an entry's bit channels under it with bit number, name, location and the device note's bit text, and the PLC I/O cross-reference SHALL list every bit channel location.

#### Scenario: Panel node sheet
- **WHEN** node `panel` maps bits 0 and 3 of 0x6000:1
- **THEN** its PDO details show two bit rows under 0x6000:1 and the cross-reference lists both `%IX` locations
