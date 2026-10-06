# canopen-sdo-variables Specification

## Purpose
Moves node objects between the PLC program and the network over SDO while it runs: reads into input locations and writes from output locations, with optional trigger, status and abort code locations.

## Requirements

### Requirement: SDO variable entries
Each slave entry MAY give an `sdo_variables` list. Each entry SHALL give `index`, `subindex`, `type` (one of the data types allowed for PDO entries), `direction` (`read` or `write`) and `iec_location`, and MAY give `name`, `period_ms` (read entries only, at least 10), `trigger_location` (an `%QX` output bit), `status_location` (an `%IB` input byte), `abort_code_location` (an `%ID` input double word) and `timeout_ms` (10 to 60000, default 1000). A `read` entry's `iec_location` SHALL be an input location and a `write` entry's an output location, each sized for the type by the same rules as PDO entries. All these locations SHALL take part in the configuration's overlap check. An entry that breaks these rules SHALL reject the configuration, naming the node, the entry and the field.

#### Scenario: Read entry accepted
- **WHEN** node 5 has `"sdo_variables": [{"name": "serial", "index": "0x1018", "subindex": 4, "type": "UNSIGNED32", "direction": "read", "iec_location": "%ID200"}]`
- **THEN** the plugin loads the configuration

#### Scenario: Write entry on an input location
- **WHEN** a `write` entry has `iec_location` `%IW200`
- **THEN** the plugin rejects the configuration and names the node, the entry and `iec_location`

#### Scenario: Period on a write entry
- **WHEN** a `write` entry gives `period_ms`
- **THEN** the plugin rejects the configuration and names the field

#### Scenario: Overlap with a PDO entry
- **WHEN** a read entry's `iec_location` overlaps a PDO entry's location
- **THEN** the plugin rejects the configuration and names both

### Requirement: EDS check of SDO variables
At load the plugin SHALL check every SDO variable against the node's EDS: the object SHALL exist, its `DataType` SHALL equal the entry's `type`, a `read` entry's `AccessType` SHALL allow reading (`ro`, `rw`, `rwr`, `rww`, `const`) and a `write` entry's SHALL allow writing over SDO (`wo`, `rw`, `rwr`, `rww`). A failed check SHALL reject the configuration. A `write` entry that targets an object the plugin configures itself (0x1005-0x1007, 0x100C, 0x100D, 0x1014-0x1017, 0x1400-0x1BFF, 0x1F80) SHALL be accepted with a warning naming the node and the object. The deploy tool SHALL run the same checks before upload.

#### Scenario: Write to a const object
- **WHEN** a `write` entry targets 0x1018 subindex 4, which the EDS marks `const`
- **THEN** the configuration is rejected with an error naming the node, the object and the access type

#### Scenario: Write to the heartbeat period
- **WHEN** a `write` entry targets 0x1017 subindex 0
- **THEN** the plugin loads the configuration and logs a warning that the program can override the node's heartbeat setting

### Requirement: When read entries are read
The master SHALL read a `read` entry from the node once after each successful boot of the node, then every `period_ms` while the node stays available when `period_ms` is given, and once on each rising edge of `trigger_location` when it is given. The value SHALL appear in the entry's `iec_location` by the next scan cycle after the transfer ends. The location SHALL read 0 before the first successful read and SHALL keep its last value when a read fails or the node is lost.

#### Scenario: Serial number at boot
- **WHEN** node 5 has a read entry for 0x1018 subindex 4 at `%ID200` and the device's serial number is 0x00001234
- **THEN** after node 5 has booted `%ID200` reads 16#00001234, and no further reads of 0x1018 subindex 4 are sent

#### Scenario: Periodic read
- **WHEN** a read entry has `period_ms` 500
- **THEN** the master reads the object about twice a second while the node is available, and the location follows the device's value

#### Scenario: Read on request
- **WHEN** a read entry has `trigger_location` `%QX20.0` and the program sets `%QX20.0` from FALSE to TRUE
- **THEN** the master reads the object once, and reads it again only after the bit has gone FALSE and TRUE again

#### Scenario: Node lost
- **WHEN** a read entry holds 1234 and its node is lost
- **THEN** the location keeps 1234

### Requirement: When write entries are written
A `write` entry without `trigger_location` SHALL make the PLC the owner of the object: the master SHALL write the location's current value after each successful boot of the node, and again whenever the value differs from the last value written in that boot. A `write` entry with `trigger_location` SHALL be written only on each rising edge of the trigger, with the location's value in the same scan cycle. The master SHALL NOT write any value before the PLC program has completed its first scan cycle since start. Changes SHALL be picked up within 100 ms or by the next SYNC, whichever comes first. When the value changes again while a write is in progress, the master SHALL write the newest value after the current write ends.

#### Scenario: Setpoint owned by the program
- **WHEN** node 23 has a write entry for 0x2020 subindex 1 at `%QW200` without a trigger, and the program sets `%QW200` to 500
- **THEN** the master writes 500 to 0x2020 subindex 1 once, and writes again only when `%QW200` changes

#### Scenario: Node restarts
- **WHEN** node 23 resets and boots again while `%QW200` holds 500
- **THEN** the master writes 500 to 0x2020 subindex 1 again after node 23 has booted

#### Scenario: Write on request
- **WHEN** a write entry has `trigger_location` `%QX20.1` and the program changes the value without touching the trigger
- **THEN** nothing is written until `%QX20.1` goes from FALSE to TRUE, and then the value of that scan cycle is written once

#### Scenario: Value changes during a write
- **WHEN** the program changes an owned value from 1 to 2 to 3 while the write of 1 is still in progress
- **THEN** the master writes 3 after the write of 1 ends, and does not write 2

### Requirement: Transfer status
When `status_location` is given, the plugin SHALL keep it at the state of the entry's latest transfer: 0 none yet, 1 in progress, 2 done, 3 aborted, 4 node not available. When `abort_code_location` is given, the plugin SHALL set it to the CiA 301 abort code of the latest aborted transfer (0x05040000 for a timeout after `timeout_ms`) and to 0 after a successful one. A transfer that is due while the node is not available (not booted, lost, booting, or STOPPED) SHALL NOT be sent: an owned write or a read SHALL wait and be sent once the node is available again, with the status at 4 meanwhile; a triggered transfer SHALL be dropped with the status at 4. An aborted transfer SHALL be logged with the node, the object, the direction and the abort code in hex and words; further aborts of the same entry with the same code SHALL NOT be logged again until a transfer of that entry succeeds. Transfers SHALL NOT change the node's NMT state, status bit or state byte.

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

### Requirement: SDO variables do not disturb the network
The master SHALL run at most one SDO variable transfer per node at a time, SHALL NOT start one while the node is being booted or configured, and SHALL serve triggered transfers and owned writes before periodic reads. The PLC scan path SHALL NOT allocate, log, or wait on CAN traffic for SDO variables.

#### Scenario: Boot takes priority
- **WHEN** node 5 resets while its periodic read is due
- **THEN** the master configures node 5 first and sends the read only after the boot has ended
