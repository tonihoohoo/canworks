## ADDED Requirements

### Requirement: Plain CAN networks in the configurator
Add network SHALL offer "Plain CAN" next to the other protocols. A plain CAN network page SHALL show the adapter settings, a "Listen only" switch, and the CAN messages page; it SHALL show no master, node or J1939 settings. Turning on "Listen only" while the network has send messages SHALL be refused with a message naming them.

#### Scenario: New plain network
- **WHEN** the user adds a Plain CAN network on `can1` at 250 kbit/s and saves
- **THEN** the file has a version 2 network with `"protocol": "none"` and that adapter, and Check reports no problems

### Requirement: CAN messages page
Every network SHALL have a CAN messages page with a receive table and a send table. A row SHALL edit one message (name, identifier in hex, extended, remote, mask for receive, DLC, timing for send, timeout and status locations for receive) and SHALL open its signal rows (name, start bit, length, byte order, signed, scale, offset, unit, PLC location). The page SHALL draw the selected message's 8 bytes as a bit grid with each signal's bits marked, as the frame inspector does. "Suggest addresses" SHALL fill free PLC locations of the right size. A send message on an identifier the network's protocol uses SHALL be marked with the use and an "Override protocol" switch.

#### Scenario: Overlapping signals
- **WHEN** the user gives two signals of one message overlapping bits
- **THEN** both rows are marked with a problem naming the other signal, and the bit grid shows the overlap

#### Scenario: Send on a PDO identifier
- **WHEN** the user adds a send message 0x205 on a network where 0x205 is RPDO1 of node 5
- **THEN** the row says "RPDO1 of node 5" and Check reports a problem until "Override protocol" is on

### Requirement: Import a DBC into CAN messages
The CAN messages page SHALL have "Import DBC…", which reads a DBC file, lists its messages with identifier, DLC, sender and signal count, and adds the chosen messages as receive or send messages (send preselected for messages whose sender is a node the user marks as "this PLC"). Imported messages SHALL keep the DBC's names, layouts, scale, offset, unit and limits; a cycle time from the DBC SHALL become `period_ms` for send and three times the cycle as `timeout_ms` for receive. Messages with multiplexed signals SHALL be listed with a note that multiplexed signals are not imported. The file name SHALL be stored in `raw.dbc`.

#### Scenario: Import two messages
- **WHEN** the user imports a DBC with messages `Joystick` (cycle 100 ms) and `Lamps`, choosing receive for `Joystick` and send for `Lamps`, then clicks Suggest addresses and saves
- **THEN** the file has `Joystick` in `raw.rx` with `timeout_ms` 300 and `Lamps` in `raw.tx`, every signal has a location, and Check reports no problems

### Requirement: Raw messages in the online view
The online view SHALL list each raw message of the network with its last data, age, counter, timeout state and short-frame count (receive) or sent count and last error (send), and the numbers of program receivers and cyclic jobs with their drops.

#### Scenario: Message timed out
- **WHEN** a receive message with `timeout_ms` 300 has not arrived for a second
- **THEN** its row shows timed out and the age in milliseconds

### Requirement: Copy a raw message as ST
"Copy as ST call" on a raw message SHALL copy ST that receives it with `CAN_RECEIVE` and unpacks each signal with `CAN_GET_BITS` (receive), or packs each signal with `CAN_SET_BITS` and sends it with `CAN_SEND` or `CAN_SEND_CYCLIC` at its period (send), with the network's number set.

#### Scenario: Copy a receive message
- **WHEN** the user copies receive message `Joystick` on the second network
- **THEN** the clipboard holds a `CAN_RECEIVE` call with `NETWORK := 1` and `ID := 16#123`, and one `CAN_GET_BITS` line per signal with its layout
