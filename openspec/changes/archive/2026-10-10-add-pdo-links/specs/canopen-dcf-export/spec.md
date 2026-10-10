## MODIFIED Requirements

### Requirement: ParameterValue for every boot write
For every sub-object the plugin writes to the node during its boot-time configuration, the DCF SHALL carry `ParameterValue=` with the value the sub-object holds after the whole configuration download, i.e. the last value written. This covers the writes from PDO communication and mapping settings, linked consumer RPDOs, heartbeat producer and consumer, heartbeat watch entries, node guarding, TIME COB-ID, RPDO deadlines, the configuration-check stamp and startup SDOs. Writes the plugin drops (read-only PDO communication sub-indices whose EDS value already matches, the 0x1016 clear when `heartbeat_consumer` is unset) SHALL get no ParameterValue. `$NODEID` expressions SHALL be resolved: ParameterValue holds the absolute value. A sub-object defined through `CompactSubObj` SHALL get its value in the object's `[<index>Value]` section.

#### Scenario: PDO COB-ID disable and enable
- **WHEN** a TPDO is configured and the plugin writes its COB-ID first with the invalid bit set and later without it
- **THEN** the DCF's `[1800sub1]` ParameterValue is the final, valid COB-ID

#### Scenario: Startup SDO
- **WHEN** node 23 has a startup SDO writing 0x2020 sub 0 = 1
- **THEN** `[2040]` in `node_23.dcf` has `ParameterValue=1` (in the data type's CiA 306 form)

#### Scenario: Dropped read-only write
- **WHEN** a node's EDS has 0x1800 sub 2 read-only with the configured value
- **THEN** `[1800sub2]` has no ParameterValue

#### Scenario: Linked consumer RPDO
- **WHEN** node 20 consumes node 10's TPDO 1 (COB-ID 0x18A) on its RPDO 2 with two mapped objects
- **THEN** `node_20.dcf` has `[1401sub1]` ParameterValue 0x18A, `[1601sub0]` ParameterValue 2 and the two objects in `[1601sub1]` and `[1601sub2]`

#### Scenario: Heartbeat watch entry
- **WHEN** node 20 watches node 10 with 300 ms in 0x1016 sub 2
- **THEN** `[1016sub2]` in `node_20.dcf` has ParameterValue 0x000A012C
