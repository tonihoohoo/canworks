## MODIFIED Requirements

### Requirement: SDO variable entries
Each slave entry MAY give an `sdo_variables` list. Each entry SHALL give `index`, `subindex`, `type` (one of the data types allowed for PDO entries), `direction` (`read` or `write`) and `iec_location`, and MAY give `name`, `period_ms` (read entries only, at least 10), `trigger_location` (an `%QX` output bit), `status_location` (an `%IB` input byte), `abort_code_location` (an `%ID` input double word) and `timeout_ms` (10 to 60000, default 1000). A `read` entry's `iec_location` SHALL be an input location and a `write` entry's an output location, each sized for the type by the same rules as PDO entries. All these locations SHALL take part in the configuration's overlap check. An entry that breaks these rules SHALL reject the configuration, naming the node, the entry and the field.

#### Scenario: Read entry accepted
- **WHEN** node 5 has `"sdo_variables": [{"name": "serial", "index": "0x1018", "subindex": 4, "type": "UNSIGNED32", "direction": "read", "iec_location": "%ID200"}]`
- **THEN** the bridge loads the configuration

#### Scenario: Write entry on an input location
- **WHEN** a `write` entry has `iec_location` `%IW200`
- **THEN** the bridge rejects the configuration and names the node, the entry and `iec_location`

#### Scenario: Period on a write entry
- **WHEN** a `write` entry gives `period_ms`
- **THEN** the bridge rejects the configuration and names the field

#### Scenario: Overlap with a PDO entry
- **WHEN** a read entry's `iec_location` overlaps a PDO entry's location
- **THEN** the bridge rejects the configuration and names both

### Requirement: EDS check of SDO variables
At load the bridge SHALL check every SDO variable against the node's EDS: the object SHALL exist, its `DataType` SHALL equal the entry's `type`, a `read` entry's `AccessType` SHALL allow reading (`ro`, `rw`, `rwr`, `rww`, `const`) and a `write` entry's SHALL allow writing over SDO (`wo`, `rw`, `rwr`, `rww`). A failed check SHALL reject the configuration. A `write` entry that targets an object the bridge configures itself (0x1005-0x1007, 0x100C, 0x100D, 0x1014-0x1017, 0x1400-0x1BFF, 0x1F80) SHALL be accepted with a warning naming the node and the object. The deploy tool SHALL run the same checks before upload.

#### Scenario: Write to a const object
- **WHEN** a `write` entry targets 0x1018 subindex 4, which the EDS marks `const`
- **THEN** the configuration is rejected with an error naming the node, the object and the access type

#### Scenario: Write to the heartbeat period
- **WHEN** a `write` entry targets 0x1017 subindex 0
- **THEN** the bridge loads the configuration and logs a warning that the program can override the node's heartbeat setting

### Requirement: Transfer status
When `status_location` is given, the bridge SHALL keep it at the state of the entry's latest transfer: 0 none yet, 1 in progress, 2 done, 3 aborted, 4 node not available. When `abort_code_location` is given, the bridge SHALL set it to the CiA 301 abort code of the latest aborted transfer (0x05040000 for a timeout after `timeout_ms`) and to 0 after a successful one. A transfer that is due while the node is not available (not booted, lost, booting, or STOPPED) SHALL NOT be sent: an owned write or a read SHALL wait and be sent once the node is available again, with the status at 4 meanwhile; a triggered transfer SHALL be dropped with the status at 4. An aborted transfer SHALL be logged with the node, the object, the direction and the abort code in hex and words; further aborts of the same entry with the same code SHALL NOT be logged again until a transfer of that entry succeeds. Transfers SHALL NOT change the node's NMT state, status bit or state byte.

#### Scenario: Device refuses a write
- **WHEN** node 23 aborts a write to 0x2020 subindex 1 with 0x06090030 (value range exceeded)
- **THEN** the status byte reads 3, the abort code reads 16#06090030, the log names node 23, the object and the abort, and node 23 stays OPERATIONAL

#### Scenario: Triggered write while the node is lost
- **WHEN** a write entry's trigger rises while its node is lost
- **THEN** nothing is sent, the status byte reads 4, and nothing is written when the node returns

#### Scenario: No answer
- **WHEN** a read gets no SDO answer within `timeout_ms`
- **THEN** the status byte reads 3 and the abort code reads 16#05040000

#### Scenario: Repeated abort of a periodic read
- **WHEN** a read entry with `period_ms` 100 is aborted with the same code ten times in a row
- **THEN** the log shows that abort once
