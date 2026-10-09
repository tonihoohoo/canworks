## ADDED Requirements

### Requirement: J1939 networks
A J1939 network SHALL have its own section built from the config, and from its DBC for names and comments the config lacks. It SHALL show the adapter and bitrate, the ECU's NAME, address, address range and PLC locations, the DBC file name, every received and sent message with its J1939 settings and PLC locations, and the periodic requests. Its PLC locations SHALL be in the PLC I/O cross-reference. It has no node sheets, boot configuration or object dictionary appendix.

#### Scenario: J1939 example
- **WHEN** a user exports `examples/j1939/canworks.json` to HTML
- **THEN** network `machine` shows ECU address 128 with range 128..135, received PGN 65280 `Pressures` with signal `Pressure` at `%IW210` scale 0.1 bar, sent PGN 65281 `Setpoints` every 100 ms, and no master node ID or node list

#### Scenario: Mixed config
- **WHEN** a version 2 config has a CANopen master network and a J1939 network and both use `%IW` addresses
- **THEN** the document has one section per network and the PLC I/O cross-reference lists both networks' locations sorted together

### Requirement: J1939 signals
Each J1939 message in the document SHALL list its signals with start bit, length, signedness, scale, offset, unit, PLC address, valid-bit PLC address and, in editor-project mode, the PLC variable name.

#### Scenario: Signal row
- **WHEN** the J1939 example is exported
- **THEN** PGN 65280's signal `Temp` shows start bit 16, length 8, signed, unit degC, `%IB204` and valid bit `%IX202.2`

### Requirement: J1939 frame map and bus load
A J1939 network's frame map SHALL list the address claim, the requests and each message with its 29-bit identifier, producer, length, period and load share. Its bus load SHALL use extended-frame bits, count a sent message at its period (on change only: its minimum gap, worst case), a received one at its DBC cycle time or the PLC's request period, a message over 8 bytes as its transport-protocol frames, and state how many received messages have no known rate.

#### Scenario: Received message without a rate
- **WHEN** a J1939 network receives PGN 65282, the DBC gives it no cycle time and the network does not request it
- **THEN** the bus-load total leaves it out and says that 1 received message has no known rate

#### Scenario: Requested message
- **WHEN** the J1939 example requests PGN 65282 every 1000 ms
- **THEN** its 34-byte answer counts once a second as its transport protocol frames

## MODIFIED Requirements

### Requirement: Summary
The document SHALL begin with: a title (from the title option, else "CAN network documentation"), the config file name and its SHA-256, the exporting tool and version, the generation date and time, and per network the name, protocol, interface, bitrate, number of nodes and PDOs (CANopen) or of messages (J1939), and the cyclic and worst-case bus load estimates. It SHALL list every warning the deploy tool's checks and the export give, and SHALL state "no warnings" when there are none.

#### Scenario: Warnings listed
- **WHEN** the config has a startup SDO that writes a PDO communication object
- **THEN** the summary lists the same warning the DBC export gives for it

#### Scenario: Protocol shown
- **WHEN** the config has a CANopen network `field` and a J1939 network `machine`
- **THEN** the summary lists `field` as CANopen with its node and PDO counts and `machine` as J1939 with its message count

### Requirement: Machine-readable content
The document SHALL carry the data it shows as JSON inside the page, in `<script type="application/json" id="canworks-doc">`, with a `doc_schema_version` field (2 for this version) and a `protocol` field on each network, so other tools can read networks, nodes, frames, PDOs, J1939 messages and signals, boot writes and I/O without parsing the HTML.

#### Scenario: Read the JSON
- **WHEN** a script extracts the embedded JSON of the rtd-sensor document
- **THEN** it finds network `vcan0` with `protocol` `canopen` and node 5 with TPDO 1 at COB-ID 0x185 and four mapped objects

#### Scenario: Read a J1939 network
- **WHEN** a script extracts the embedded JSON of the J1939 example's document
- **THEN** it finds network `machine` with `protocol` `j1939`, `doc_schema_version` 2, and message PGN 65280 with four signals
