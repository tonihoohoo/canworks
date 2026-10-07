## ADDED Requirements

### Requirement: Four-layer frame explanation
The tools SHALL explain any classic CAN frame against a configuration in four layers: the meaning (one plain sentence naming sender, receiver or target, the object or signals and their values; the raw frame; and a short text on what this message type is for), the identifier, the data bits, and the frame on the wire. The explanation SHALL be built on the PC from the frame and the configuration with its EDS files only, without a runtime or bus. One model SHALL serve the configurator, the command-line client and the network document.

#### Scenario: SDO answer
- **WHEN** node 5 sends `585#4318100178563412` and node 5's EDS names 1018h:01 "Vendor-ID"
- **THEN** the meaning says node 5 answers 1018h:01 Vendor-ID with 305419896 (0x12345678)

#### Scenario: No configuration
- **WHEN** a frame is explained without a configuration
- **THEN** it is explained with the CANopen predefined identifiers, and PDO data is shown as bytes with a note that the mapping is unknown

### Requirement: Identifier layer
The identifier layer SHALL show every identifier bit with its value and weight. For an 11-bit identifier in the CANopen predefined set it SHALL split the bits into the 4-bit function code and the 7-bit node ID, show the arithmetic (for example `0x185 = 3 × 0x80 + 5`), and name the message type and the node with its configured name. It SHALL explain that the identifier is also the priority and that a lower identifier wins arbitration. A 29-bit identifier SHALL be shown with its bits and marked as outside the CANopen predefined set. An identifier changed by the configuration (a PDO COB-ID that is not the default) SHALL be named by its configured use.

#### Scenario: Default TPDO identifier
- **WHEN** frame `185#...` is explained
- **THEN** the identifier layer shows function code 3, node ID 5, TPDO1 of node 5

#### Scenario: Configured COB-ID
- **WHEN** node 5's TPDO2 is configured with COB-ID 0x1A0
- **THEN** a frame with identifier 0x1A0 is explained as TPDO2 of node 5, with a note that this is a configured, not a default, identifier

### Requirement: Every data bit is explained
The data layer SHALL assign every data bit of the frame to exactly one named field, with unused, reserved and padding bits as fields of their own. Each field SHALL have its bit range in CANopen numbering (bit 0 is the least significant bit of byte 0), its value, the working that leads to the value for multi-byte numbers (the bytes in frame order, reversed because CANopen is little-endian, the resulting hex and the value in the data type), and a plain-language explanation. Fields made of single flags SHALL name each bit. Values SHALL be shown in the object's EDS data type, signed and floating point included.

#### Scenario: Little-endian working
- **WHEN** a PDO maps an INTEGER16 object to bits 16-31 and the frame's bytes 2 and 3 are EA 00
- **THEN** the field shows `EA 00 → 0x00EA = 234`

#### Scenario: No unexplained bits
- **WHEN** an SDO expedited answer carries 2 data bytes
- **THEN** bytes 6 and 7 are a padding field explained by the n bits of the command byte

### Requirement: Fields per protocol
The data layer SHALL have fields for:
- NMT: command with its name, target node (0 = all nodes).
- SYNC: the optional counter; a SYNC without data SHALL say the frame's arrival is the message.
- TIME: milliseconds after midnight and days since 1984-01-01, with the date and time.
- EMCY: error code with its class and text, each error register bit by name, manufacturer bytes.
- Heartbeat and boot-up: NMT state with its name and the toggle bit, with node guarding requests and answers explained.
- SDO: the command specifier for the direction (client request or server answer) and, depending on it, the n, e and s bits, the toggle bit, the unused byte count and the last-segment flag, the block transfer bits, the index (little-endian), subindex with the EDS object name, the data in the object's type, the size of a segmented transfer, and abort codes with their text.
- LSS: command specifier with its name and its parameters.
- PDO: each mapped object with its index and subindex, EDS name, data type, PLC address and, in editor-project mode, the PLC variable name; for bit-sized objects or bit-mapped PLC addresses each bit with its own PLC address.
- SocketCAN error frames: each error class flag and the detail bytes (controller state, protocol error type and location, transceiver state, error counters) by name.

#### Scenario: SDO command byte
- **WHEN** frame `605#2B171000E8030000` is explained
- **THEN** byte 0 is split into command specifier 1 (initiate download), n = 2, e = 1, s = 1, the data field is 2 bytes with value 1000, and 1017h:00 is named

#### Scenario: EMCY register bits
- **WHEN** an EMCY carries error register 0x03
- **THEN** bit 0 "generic error" and bit 1 "current" are shown set and the other six bits shown clear with their names

#### Scenario: Digital input bits
- **WHEN** a TPDO maps a UNSIGNED8 digital input object to `%IX100.0` to `%IX100.7` and byte 0 is 0x25
- **THEN** bits 0, 2 and 5 are shown as on with `%IX100.0`, `%IX100.2` and `%IX100.5`

### Requirement: SDO segments in context
When a frame is explained from a trace, an SDO segment, block segment or segment answer SHALL be explained with the transfer it belongs to: object, direction, segment number, toggle bit expected and received, and bytes so far. Without a trace, a segment SHALL be explained on its own with a note that the transfer is unknown.

#### Scenario: Segment in a trace
- **WHEN** the third segment of an upload of 1008h:00 from node 5 is explained from a trace
- **THEN** it is shown as segment 3 of the upload of 1008h:00 with its toggle bit and the bytes it adds

### Requirement: Frame on the wire
The wire layer SHALL rebuild the frame as a correct CAN controller sends it, for base and extended, data and remote frames: start of frame, identifier, SRR and IDE where they apply, RTR, reserved bits, DLC, data, the 15-bit CRC (polynomial 0x4599) over the unstuffed bits from start of frame to the end of the data, stuff bits inserted after every five equal bits from start of frame to the end of the CRC sequence, CRC delimiter, ACK slot as a received frame has it (dominant), ACK delimiter, seven end-of-frame bits and three intermission bits. Every wire bit SHALL say which field and which bit of the other layers it carries, or that it is a stuff bit and why. The layer SHALL show the bus level of each bit (0 dominant, 1 recessive), the frame's length in bits, the number of stuff bits, the CRC, the time on the bus at the network's bit rate and the share of the frame that is data. It SHALL say that the layer is a reconstruction and not measured. Error frames SHALL have no wire layer.

#### Scenario: CRC check value
- **WHEN** the CRC function is fed the bytes of the ASCII string "123456789"
- **THEN** it returns 0x059E

#### Scenario: Stuff bits
- **WHEN** frame `185#2500EA00` is explained at 500 kbit/s
- **THEN** the wire layer has 76 frame bits plus 3 stuff bits, and the time on the bus is 158 µs

#### Scenario: Remote frame
- **WHEN** a remote request `705#R` is explained
- **THEN** the RTR bit is recessive, there is no data field, and the meaning is a node guarding request to node 5

### Requirement: Bit rate for timing
Bit times SHALL come from the network's configured bit rate, or from a trace file's metadata, or from a bit rate given by the user. When none is known, 500 kbit/s SHALL be used and marked as assumed.

#### Scenario: Assumed bit rate
- **WHEN** a frame is explained from a candump file without bit rate and without a configuration
- **THEN** the times are computed at 500 kbit/s and marked as assumed

### Requirement: Frame builder
The tools SHALL build frames for explanation from: an SDO read or write (expedited or segmented, request and answer) of an object picked from a node's dictionary with a value typed in the object's data type, a PDO of the configuration with values per signal (PLC variable names in editor-project mode), an NMT command with target, a heartbeat or boot-up of a node, and an EMCY with code and register. They SHALL also generate example frames from the configuration: each node's boot-up, heartbeat, an SDO read of 1018h:01 and its answer, and each configured PDO. Built frames SHALL never be sent to a bus.

#### Scenario: Build an SDO write
- **WHEN** the user builds a write of 1017h:00 = 1000 to node 5
- **THEN** the frames `605#2B171000E8030000` and the matching answer `585#6017100000000000` are produced and explained

#### Scenario: Out-of-range value
- **WHEN** the user types 300 for a UNSIGNED8 signal
- **THEN** no frame is built and the field says the value is out of range 0 to 255

### Requirement: Explain in the command-line client
`openplc-canopen-diag explain` SHALL explain one or more frames given in candump syntax (`ID#DATA`, `ID#R` for remote frames, 8 hex digits for extended identifiers) or one frame of a trace file (`--trace FILE --index N`, with SDO context from the trace). Options SHALL select the configuration (`--config`), the network (`--network`), the bit rate (`--bitrate`) and the output (`--format text`, the default, or `json`). Text output SHALL show the meaning, the identifier split, a byte-by-bit grid with each field marked and a legend, the field list with values and working, and the wire summary with the wire bits and stuff bits marked. JSON output SHALL be the explanation model. The command SHALL need no runtime.

#### Scenario: Explain a heartbeat
- **WHEN** a user runs `openplc-canopen-diag explain 705#05`
- **THEN** it prints that node 5 is operational, the identifier as function code 14 and node 5, the state and toggle bit fields, and the wire summary

#### Scenario: Bad frame syntax
- **WHEN** a user runs `openplc-canopen-diag explain 185#2500E`
- **THEN** the command exits with an error saying the data needs whole bytes

#### Scenario: Frame longer than classic CAN
- **WHEN** a frame with 12 data bytes is given
- **THEN** the command says only classic CAN frames up to 8 bytes are supported
