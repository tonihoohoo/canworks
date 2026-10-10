## ADDED Requirements

### Requirement: PDO links in the document
Each network with links SHALL have a Links table: name, COB-ID, producer node and TPDO, each consumer node and RPDO with its transmission type and deadline, whether the PLC reads the value (and at which addresses), `on_plc_stop`, and whether each consumer watches the producer's heartbeat. The COB-ID map row of a linked TPDO SHALL list the consumers next to the master, and a link SHALL add no row and no bus load. Each consumer's node sheet SHALL show its linked RPDO with the byte grid and table of PDO details, the producer's position for each of its objects, and its heartbeat watch entries. Layout warnings (types that differ at one size) SHALL be shown on the link.

#### Scenario: Link in the COB-ID map
- **WHEN** node 10's TPDO 1 at 0x18A links to node 20 RPDO 2
- **THEN** the 0x18A row has producer node 10, consumers master and node 20, and the bus-load totals equal those without the link

#### Scenario: Consumer node sheet
- **WHEN** node 20 consumes 0x18A on RPDO 2 with a dummy entry at the second position
- **THEN** node 20's sheet shows RPDO 2 fed by node 10 TPDO 1, with 0x6411:1 at bits 0-15 and the dummy at bits 16-31

#### Scenario: Value not used by the PLC
- **WHEN** the producer's entries have no `iec_location`
- **THEN** the Links table says the PLC does not read the link and the PLC I/O cross-reference has no entry for it
