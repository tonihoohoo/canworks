## ADDED Requirements

### Requirement: PDO identifiers stay off service identifiers
The PC tools and the plugin SHALL refuse a PDO COB-ID, or the master's TIME COB-ID, that is a CiA 301 restricted CAN-ID, the network's SYNC or TIME COB-ID, or a configured node's EMCY identifier, with a message naming the clashing service. Both SHALL give the same verdict.

#### Scenario: RPDO on a node's SDO channel
- **WHEN** an RPDO of node 2 has COB-ID 0x602
- **THEN** the configurator and the plugin refuse it with "COB-ID 0x602 is node 2's SDO request"

#### Scenario: TPDO on SYNC
- **WHEN** a TPDO has COB-ID 0x80 and SYNC uses its default
- **THEN** both refuse it naming SYNC

#### Scenario: TPDO on a node's EMCY
- **WHEN** node 2's EMCY is not moved and a TPDO uses 0x82
- **THEN** both refuse it naming node 2's EMCY

### Requirement: Store and restore are never startup writes
A startup SDO to 0x1010 or 0x1011 SHALL be refused by the PC tools and the plugin with a pointer to `store_configuration` and `restore_configuration`. A write SDO variable on 0x1010 or 0x1011 SHALL be accepted only with a `trigger_location`.

#### Scenario: Save in the startup list
- **WHEN** a node's `sdo` list writes 0x65766173 to 0x1010 sub 1
- **THEN** both refuse the config and name `store_configuration`

#### Scenario: Triggered write variable
- **WHEN** a write SDO variable on 0x1010 sub 1 has a `trigger_location`
- **THEN** the config is accepted and the write happens only on the trigger

### Requirement: 64-bit values as JSON numbers
A JSON integer whose magnitude is above 2^53 SHALL be refused in every config field by the PC tools and the plugin, with a message to write it as a string.

#### Scenario: Large UNSIGNED64 startup value
- **WHEN** a startup SDO value is the JSON number 9007199254740993
- **THEN** both refuse it and ask for a string

### Requirement: Same number syntax on both sides
The PC tools SHALL refuse every number or location string the plugin refuses, including strings with leading or trailing whitespace or a newline, `"-0"` on unsigned types, and the JSON constants NaN and Infinity. String values in maps such as `error_behavior` SHALL be range-checked like JSON numbers.

#### Scenario: Trailing newline
- **WHEN** `node_id` is `"3\n"`
- **THEN** the configurator refuses it as the plugin does

#### Scenario: error_behavior as a string
- **WHEN** `error_behavior` is `{"1": "0x100"}`
- **THEN** both refuse it as out of range

### Requirement: Location overlaps in version 1 configs
The PC check SHALL refuse two uses of one IEC location in a version 1 config as it does in version 2 and as the plugin does.

#### Scenario: State and boot error on one byte
- **WHEN** a node's `state_location` and `boot_error_location` are both `%IB400`
- **THEN** the configurator reports the overlap before saving

### Requirement: Automatic COB-IDs are checked where they land
A PDO with `cob_id: "auto"` SHALL be checked for clashes at its resolved COB-ID, not at a default one.

#### Scenario: Auto TPDO 6 next to an explicit 0x682
- **WHEN** node 2 TPDO 6 is `auto` and node 3 TPDO 1 uses 0x682
- **THEN** both accept the config and the auto PDO gets a free COB-ID

### Requirement: Heartbeat consumer time is the configured timeout
The master's heartbeat consumer entry for a node SHALL equal the node's `heartbeat_timeout_ms`, never less, in the plugin and the DCF export.

#### Scenario: Timeout 10 ms on a 3 ms heartbeat
- **WHEN** `heartbeat_ms` is 3 and `heartbeat_timeout_ms` is 10
- **THEN** the master's 0x1016 entry for the node is 10 ms
