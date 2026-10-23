## RENAMED Requirements

- FROM: `### Requirement: Values match the plugin's downloads`
- TO: `### Requirement: Values match the bridge's downloads`

## MODIFIED Requirements

### Requirement: DCF body is the node's EDS
The DCF SHALL contain every section and key of the EDS copy the bridge uses (the prepared copy from the EDS lint step), in the same order and with the same values, so that removing the added lines gives back that copy, except that REAL32 and REAL64 DefaultValue, ParameterValue, LowLimit and HighLimit SHALL be written as decimal numbers that read back to exactly the same value. The export SHALL only add or change the lines this capability names: `ParameterValue` keys, the `[DeviceComissioning]` section, `[FileInfo]` keys, leading `;` comment lines and the decimal form of REAL values.

#### Scenario: Unwritten objects untouched
- **WHEN** a node's EDS defines 0x6000 and the config writes nothing there
- **THEN** the DCF's 0x6000 sections are identical to the EDS's, with no ParameterValue

#### Scenario: REAL limit
- **WHEN** a node's prepared EDS has `HighLimit=0x42C80000` on a REAL32 object
- **THEN** the DCF has `HighLimit=100.0` on that object

### Requirement: ParameterValue for every boot write
For every sub-object the bridge writes to the node during its boot-time configuration, the DCF SHALL carry `ParameterValue=` with the value the sub-object holds after the whole configuration download, i.e. the last value written. This covers the writes from PDO communication and mapping settings, linked consumer RPDOs, heartbeat producer and consumer, heartbeat watch entries, node guarding, TIME COB-ID, RPDO deadlines, the configuration-check stamp and startup SDOs. Writes the bridge drops (read-only PDO communication sub-indices whose EDS value already matches, the 0x1016 clear when `heartbeat_consumer` is unset) SHALL get no ParameterValue. `$NODEID` expressions SHALL be resolved: ParameterValue holds the absolute value. A sub-object defined through `CompactSubObj` SHALL get its value in the object's `[<index>Value]` section.

#### Scenario: PDO COB-ID disable and enable
- **WHEN** a TPDO is configured and the bridge writes its COB-ID first with the invalid bit set and later without it
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

### Requirement: Boot commands are not parameter values
Writes that are commands rather than settings (0x1010 store and 0x1011 restore) SHALL NOT be written as ParameterValue. The DCF SHALL list each such step the bridge performs for the node in a leading `;` comment, in boot order.

#### Scenario: Store after configuration check
- **WHEN** a node has the configuration check with store enabled
- **THEN** the DCF has a ParameterValue on 0x1020 sub 1 and sub 2, none on 0x1010, and a comment line saying the bridge writes "save" to 0x1010 sub 1 after the configuration

### Requirement: Values match the bridge's downloads
For every node, the set of sub-objects carrying ParameterValue and their values SHALL equal the final per-sub-object result of the configuration download the bridge performs for the same config (`canopen_check --dump-writes`), excluding the boot commands named above.

#### Scenario: Fixture parity
- **WHEN** CI exports every fixture config and runs `canopen_check --dump-writes` on it
- **THEN** for each node the two lists match
