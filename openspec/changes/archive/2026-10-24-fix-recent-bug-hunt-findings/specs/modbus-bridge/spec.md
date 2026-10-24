## ADDED Requirements

### Requirement: Clean stop with several networks
A bridge with any number of CANopen, J1939 and CAN networks SHALL stop on SIGTERM with exit code 0 after every network has run its `on_plc_stop` action, and SHALL remove its run marker. An accepted config upload SHALL be applied on the restart that follows it. A network whose interface drops while the bridge runs SHALL NOT end the process.

#### Scenario: Stop with three CANopen networks
- **WHEN** a bridge runs a config with three CANopen master networks and receives SIGTERM
- **THEN** each network sends its `on_plc_stop` NMT command, the bridge exits 0, and the next start reports the last stop as clean

#### Scenario: Upload with two networks
- **WHEN** a client uploads a new config to a bridge running two CANopen networks
- **THEN** the bridge restarts on the new config, reports the upload, and leaves no staged upload behind

#### Scenario: One interface drops
- **WHEN** the interface of the first of two networks goes down and a client then writes an output of the second
- **THEN** the bridge keeps running, the first network reports its bus lost, and the write is applied

### Requirement: Device identification with the map hash
In addition to the functions the bridge supports, it SHALL answer Modbus function 43 with MEI type 14 (Read Device Identification) for every config: object 0 "canworks", object 1 "canworks-bridge", object 2 the bridge version, and the private object 0x80 the config's map hash as 8 upper-case hex digits. Other MEI types SHALL get exception 0x01.

#### Scenario: Read the map hash
- **WHEN** a client sends function 43/14 with read code 1 to a bridge whose map hash is 0x1234ABCD, with or without `plc_link`
- **THEN** the answer holds "canworks", "canworks-bridge", the version, and object 0x80 "1234ABCD"
