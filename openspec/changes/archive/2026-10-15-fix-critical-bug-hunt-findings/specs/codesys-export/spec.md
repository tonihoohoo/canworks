## ADDED Requirements

### Requirement: Numbers written as strings in the export
The CODESYS export SHALL read every number of the config (PDO numbers, node IDs, COB-IDs, indexes) as the config contract does, so a number written as a string gives the same project as the plain number. A failure while naming I/O channels SHALL end the export with an error naming the node and PDO, never with an empty channel list.

#### Scenario: PDO number and node ID as strings
- **WHEN** a config has `"number": "1"` on a TPDO and `"node_id": "0x02"`
- **THEN** the export gives the same CODESYS project and channel names as with `1` and `2`
