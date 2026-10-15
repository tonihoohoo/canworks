## MODIFIED Requirements

### Requirement: PDO decoding without a configuration
When a node's PDOs are not in a configuration (Commission a device), the trace SHALL decode each PDO frame with that node's PDO layout from the best source available, in this order:
- **bus**: SDO writes in the trace to the node's PDO communication (0x1400-0x15FF, 0x1800-0x19FF) and mapping (0x1600-0x17FF, 0x1A00-0x1BFF) objects that the node confirmed, whoever made them;
- **device**: the node's PDO objects read from the device on the live connection, and SDO read answers of them in the trace, whoever asked;
- **EDS**: the default COB-IDs and mappings of the node's EDS.

A layout learned from the bus SHALL apply from the frame that completed it, so PDO frames before it decode with the earlier layout. A PDO whose COB-ID is set invalid or whose mapping count is set to 0 SHALL stop decoding from that point. Where the bus gives only part of a PDO (for example only its mapping), the rest SHALL come from the next source. A layout read from the device on the live connection SHALL apply to frames recorded after the read, and not to opened trace files; one read in the trace SHALL apply from the answer that completed it, like a layout learned from the bus.

Signals SHALL be named and typed from the node's EDS, or from the built-in CiA 301/401/402 object names when the node has no EDS; an object neither describes SHALL be shown as its index and subindex with its mapped length as an unsigned value. Decoded signals SHALL be available to graphs, triggers and the decoded CSV export like configured PDO signals.

#### Scenario: EDS defaults
- **WHEN** node 32 has an EDS whose TPDO1 maps a UNSIGNED16 Statusword and an INTEGER32 Position actual value at COB-ID 0x180+node ID, and the trace has `0x1A0 37 02 B0 04 00 00`
- **THEN** the row reads `TPDO1 node 32 Statusword=567, Position actual value=1200` with the "assumed" tag

#### Scenario: Mapping set by another master
- **WHEN** at 12.3 s the trace has SDO writes to node 32 that disable TPDO1, map 0x6064:0 alone and enable it again
- **THEN** TPDO1 frames before 12.3 s decode with the earlier layout, frames after it as `Position actual value=…`, and the inspector of a later frame says the layout was set on the bus at 12.3 s

#### Scenario: Mapping read in the trace
- **WHEN** the trace has SDO reads of node 5's TPDO1 COB-ID and mapping (a PDO test, or another tool's Read all) and then TPDO1 frames
- **THEN** the frames decode with the layout read, and the inspector says the layout was read from the device

#### Scenario: No EDS
- **WHEN** node 49 has no EDS, is a CiA 401 device by its 0x1000, and the bus set its TPDO1 to map 0x6000:1 (8 bits)
- **THEN** the row shows TPDO1 of node 49 with 0x6000:1 under its built-in CiA 401 name and its value

#### Scenario: Nothing known
- **WHEN** node 50 has no EDS, nothing on the bus sets its PDOs and its PDOs were not read
- **THEN** its PDO frames are shown as today, with the node and the bytes
