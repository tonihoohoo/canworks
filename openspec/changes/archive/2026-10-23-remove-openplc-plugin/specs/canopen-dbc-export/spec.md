## MODIFIED Requirements

### Requirement: A message per configured PDO
Every PDO in the config's `tx_pdos` and `rx_pdos` SHALL become one message with the PDO's COB-ID as the bridge resolves it (explicit `cob_id`, `"auto"`, or the CiA 301 default for PDOs 1-4), named `<node>_TPDO<n>` or `<node>_RPDO<n>`. A TPDO SHALL be sent by its node and received by `Master`; an RPDO SHALL be sent by `Master` and received by its node. The message length SHALL be the mapped bits rounded up to whole bytes.

#### Scenario: Auto COB-ID
- **WHEN** node 2 has TPDO 5 with `"cob_id": "auto"` and the bridge resolves it to 0x57F
- **THEN** the DBC message `<node>_TPDO5` has COB-ID 0x57F

#### Scenario: RPDO direction
- **WHEN** node 2 has RPDO 1
- **THEN** message `<node>_RPDO1` at 0x202 has sender `Master` and its signals have node 2 as receiver

### Requirement: Warnings that affect the file
When the deploy tool's checks warn that a startup SDO overrides PDO settings the bridge writes, the export SHALL still write the DBC from the PDO settings in the config and SHALL report the warning with it, stating that the DBC may not match the bus for that PDO.

#### Scenario: Startup SDO rewrites a COB-ID
- **WHEN** a startup SDO writes 0x1800 sub 1 of a configured TPDO
- **THEN** the DBC is written and the export reports that warning naming the PDO

### Requirement: EMCY identifier from the EDS
The DBC export SHALL use a node's EMCY COB-ID as the bridge listens on it, including the EDS default.

#### Scenario: Moved EMCY in the EDS
- **WHEN** the EDS sets 0x1014 to 0x0C2 for node 2
- **THEN** the DBC's EMCY message for node 2 uses 0x0C2
