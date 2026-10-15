## ADDED Requirements

### Requirement: PDO decoding without a configuration
When a node's PDOs are not in a configuration (Commission a device), the trace SHALL decode each PDO frame with that node's PDO layout from the best source available, in this order:
- **bus**: SDO writes in the trace to the node's PDO communication (0x1400-0x15FF, 0x1800-0x19FF) and mapping (0x1600-0x17FF, 0x1A00-0x1BFF) objects, and SDO read answers of them, whoever made them;
- **device**: the node's PDO objects read from the device on the live connection;
- **EDS**: the default COB-IDs and mappings of the node's EDS.

A layout learned from the bus SHALL apply from the frame that completed it, so PDO frames before it decode with the earlier layout. A PDO whose COB-ID is set invalid or whose mapping count is set to 0 SHALL stop decoding from that point. Where the bus gives only part of a PDO (for example only its mapping), the rest SHALL come from the next source. A layout read from the device SHALL apply to frames recorded after the read, and not to opened trace files.

Signals SHALL be named and typed from the node's EDS, or from the built-in standard dictionary when the node has no EDS; an object neither describes SHALL be shown as its index and subindex with its mapped length as an unsigned value. Decoded signals SHALL be available to graphs, triggers and the decoded CSV export like configured PDO signals.

#### Scenario: EDS defaults
- **WHEN** node 32 has an EDS whose TPDO1 maps a UNSIGNED16 Statusword and an INTEGER32 Position actual value at COB-ID 0x180+node ID, and the trace has `0x1A0 37 02 B0 04 00 00`
- **THEN** the row reads `TPDO1 node 32 Statusword=0x0237, Position actual value=1200` with the "assumed" tag

#### Scenario: Mapping set by another master
- **WHEN** at 12.3 s the trace has SDO writes to node 32 that disable TPDO1, map 0x6064:0 alone and enable it again
- **THEN** TPDO1 frames before 12.3 s decode with the earlier layout, frames after it as `Position actual value=…`, and the inspector of a later frame says the layout was set on the bus at 12.3 s

#### Scenario: No EDS
- **WHEN** node 49 has no EDS, is a CiA 401 device by its 0x1000, and the bus set its TPDO1 to map 0x6000:1 (8 bits)
- **THEN** the row shows TPDO1 of node 49 with 0x6000:1 under its CiA 401 name from the standard dictionary and its value

#### Scenario: Nothing known
- **WHEN** node 50 has no EDS, nothing on the bus sets its PDOs and its PDOs were not read
- **THEN** its PDO frames are shown as today, with the node and the bytes

### Requirement: DBC files in a trace
A trace SHALL decode with any number of DBC files the user adds, on every network kind, for live recordings and opened files alike. A DBC message SHALL be decoded as a raw message is (signal names, scale, offset, unit, byte order, multiplexing), in the rows, the inspector's bit grid, graphs, triggers and the decoded CSV export.

On an identifier, decoding SHALL be chosen in this order: the configuration's raw messages and PDOs; the DBC files, in the order listed; PDO layouts without a configuration; the predefined connection set. On identifiers of NMT, SYNC, TIME, EMCY, SDO, heartbeat and LSS the CANopen decoding SHALL stay and the DBC message's decoding SHALL be shown next to it. A DBC message not used because something earlier decodes its identifier SHALL be reported with what decodes it instead.

On a J1939 network, the network's own DBC SHALL keep decoding its PGNs; a trace DBC SHALL decode only identifiers that network does not decode.

#### Scenario: Vendor DBC in Commission a device
- **WHEN** the user adds a DBC whose message `Valve_Status` is 0x1A0 with signal `Position` (bytes 2-5, scale 0.01, unit mm), and the trace has node 32's TPDO1 on 0x1A0
- **THEN** the rows read `Valve_Status Position=12 mm` instead of the inferred layout, and `Position` can be graphed

#### Scenario: Configuration wins
- **WHEN** a project configures node 32's TPDO1 on 0x1A0 and the user adds a DBC that also has a message on 0x1A0
- **THEN** the rows keep the configured TPDO1 and the DBC message is reported as not used because the configuration's TPDO1 of node 32 decodes 0x1A0

#### Scenario: Heartbeat in a DBC
- **WHEN** the DBC has a message on 0x720
- **THEN** the row still reads `Heartbeat node 32 OPERATIONAL`, the inspector also shows the DBC's decoding, and its signals are offered to graphs

#### Scenario: Trace command with a DBC
- **WHEN** the user runs `canworks-diag convert in.log -o out.csv --dbc machine.dbc`
- **THEN** the CSV's decoded column uses the DBC's messages

## MODIFIED Requirements

### Requirement: CANopen decoding
Every frame SHALL be decoded using the configuration and its EDS files: NMT commands with target node, SYNC, TIME, EMCY with error code text, error register and node name, heartbeat and boot-up with the NMT state, SDO requests and responses with the object index, subindex and EDS object name, expedited values as the EDS data type, abort codes with their text and segmented transfers shown as one completed transfer, LSS requests, and PDOs as signals named as in the DBC export (PLC variable names in editor-project mode) with values as the EDS data type. Without a configuration, PDOs SHALL decode as "PDO decoding without a configuration" says, and frames that match a DBC file added to the trace as "DBC files in a trace" says. Frames that match nothing SHALL be shown raw.

#### Scenario: SDO upload decoded
- **WHEN** the trace holds an SDO upload of 0x1018 subindex 4 from node 23 answered with 0x12345678
- **THEN** the request and response are shown as an SDO read of "Identity object / Serial number" of node 23 with value 0x12345678

#### Scenario: PDO signal decoded
- **WHEN** node 23's TPDO1 maps a UNSIGNED16 status word to the PLC variable `valve_status` in an editor project
- **THEN** the TPDO frame is shown with `valve_status` and its value

#### Scenario: EMCY decoded
- **WHEN** node 23 sends EMCY code 0x5010
- **THEN** the frame is shown as an emergency from node 23 with the code's text and the error register bits

#### Scenario: Unknown frame
- **WHEN** a frame with extended identifier 0x18FF0017 arrives
- **THEN** it is shown with its identifier and data and no decoding

### Requirement: Raw message decoding
A trace of a network with raw messages SHALL show each frame that matches a raw message with the message's name and its signal values (raw and, when the signal has scale, offset or unit, the scaled value with the unit). For a multiplexed message only the signals active in that frame SHALL be decoded, the row SHALL name the switch values, and a switch value with no page SHALL be shown as an unknown page; graph series of a multiplexed signal SHALL take points only from frames where it is active. For a forced message on an identifier the protocol uses, the raw decoding SHALL be shown next to the protocol's. The frame inspector SHALL mark the bits of the signals active in the frame in its bit grid. Messages of DBC files added to the trace SHALL decode the same way (see "DBC files in a trace"). Other frames SHALL be shown as before.

#### Scenario: Joystick frame
- **WHEN** a trace of a plain network has a frame `0x123 FF 0F 00 00 00 00 00 00` and the config has `Joystick` with signal `X` (start 0, length 12, signed, scale 0.1, unit %)
- **THEN** the row reads `Joystick X=-1 (-0.1 %)` and the inspector marks bits 0 to 11 as `X`

#### Scenario: Multiplexed frame
- **WHEN** the config's `Status` has switch `Page` (byte 0), `Temp` on page 1 and `Press` (unit kPa) on page 2 at bytes 1-2, and the trace has `Status` with bytes `02 90 01`
- **THEN** the row reads `Status [Page=2] Press=400 kPa`, the inspector marks `Page` and `Press` only, and a graph of `Temp` gets no point from this frame

#### Scenario: Unknown page
- **WHEN** the trace has `Status` with `Page` 7 and no signal is on page 7
- **THEN** the row reads `Status [Page=7 unknown]`
