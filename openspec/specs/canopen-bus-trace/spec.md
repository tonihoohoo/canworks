# canopen-bus-trace Specification

## Purpose
Records the CAN traffic of the runtime's CANopen interface through the plugin's diagnostics channel, decodes it as CANopen, and lets the engineering PC save, open, export, graph and trigger on traces.

## Requirements

### Requirement: Record a trace on the PC
The configurator SHALL record a trace in its own server process, so the trace survives a page reload or switching views. It SHALL record through the open connection:
- the runtime's diagnostics channel;
- or a USB adapter through the local bus backend.

**Stopping and continuing.** It SHALL stop recording only when:
- the user stops it;
- a single-mode trigger ends it;
- the connection ends;
- the configurator exits.

When the connection ends, the frames recorded so far SHALL be kept and a marker with the reason SHALL be added. A recording continued on the same network SHALL append to the same trace after a gap marker holding the gap's length, keeping the trigger and its hits.

**Limits.** It SHALL keep at least 2 million frames. Past the limit the oldest frames SHALL be dropped and the user told. Frames lost on the PLC side SHALL be shown as gaps with their count.

**Saved files.** Saved traces SHALL record whether they came from a runtime or an adapter.

#### Scenario: Reload during recording
- **WHEN** a trace is recording and the user reloads the configurator page
- **THEN** the trace view shows the frames recorded so far and recording continues

#### Scenario: Lost frames shown
- **WHEN** the plugin reports 120 lost frames during a fetch
- **THEN** the trace shows a gap marker with 120 lost frames at that time and the statistics count them

#### Scenario: Connection ends
- **WHEN** a runtime stops answering during a recording
- **THEN** the recording stops, its frames are kept, and a marker says the connection ended and why

#### Scenario: Continue on the same network
- **WHEN** a recording of network io stopped because the connection ended 20 s ago and the user continues it on io
- **THEN** new frames are appended after a gap marker of about 20 s, and the trigger's earlier hits are kept

#### Scenario: Source in the saved file
- **WHEN** a trace recorded through an adapter is saved as pcapng and opened again
- **THEN** its metadata names the adapter as the source with the interface and bit rate

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

### Requirement: Save and open traces
A trace SHALL be saved as pcapng with SocketCAN link type, per-frame direction and the trace's metadata (configuration SHA-256, interface, bit rate, start time, trigger, markers). The configurator and the command-line client SHALL open pcapng files they saved, SocketCAN pcapng files from Wireshark or tcpdump, candump log files and Vector ASC files, and decode them with the current configuration.

#### Scenario: Round trip
- **WHEN** a trace with markers is saved and opened again
- **THEN** the same frames, times, directions and markers are shown

#### Scenario: candump from the Pi
- **WHEN** the user opens a file recorded with `candump -l can0` on the Pi without the PLC running
- **THEN** its frames are shown decoded with the current configuration

### Requirement: Export formats
A trace, or the selected time range of it, SHALL be exportable as candump log, Vector ASC, Vector BLF, PEAK TRC version 2.1, pcapng and CSV, each keeping frame time, identifier and format, RTR, data and direction (where the format has one), and error frames where the format has them. The CSV SHALL include the decoded name and value of each frame. A signals CSV SHALL hold the chosen graph series, one column each, against time. Exported files SHALL be readable frame for frame by python-can (candump log, ASC, BLF, TRC) and by Wireshark (pcapng).

#### Scenario: Export for Vector tools
- **WHEN** the user exports a trace as BLF and as ASC
- **THEN** both files hold the same frames with the same times and directions, readable by python-can

#### Scenario: Export for Wireshark
- **WHEN** the user exports pcapng and opens it in Wireshark with Decode As CAN next level dissector CANopen
- **THEN** Wireshark shows the NMT, SYNC, SDO, EMCY and PDO frames as CANopen

#### Scenario: Range export
- **WHEN** the user selects 2 seconds around a marker and exports CSV
- **THEN** the file holds only the frames of those 2 seconds, with decoded names and values

### Requirement: Graphs
The configurator SHALL plot chosen series against time on a shared time axis: decoded PDO signals, SDO variable values, node NMT states, bus state and error counters, frame rate and estimated bus load. It SHALL offer zoom, pan, a value cursor across all lanes, two measurement cursors showing the time and value difference, and jumping from a point to its frame in the trace and back. Graphs SHALL stay responsive with a 2 million frame trace and update while recording.

#### Scenario: Plot a valve signal
- **WHEN** the user adds node 23's valve output signal and the bus load to the graph during recording
- **THEN** both series update live on the same time axis

#### Scenario: Measure a delay
- **WHEN** the user places one measurement cursor on a SYNC and the other on the following TPDO of node 23
- **THEN** the graph shows the time between them

### Requirement: Triggers
The user SHALL be able to set a trigger made of one condition or two conditions combined (both within a time window, or one after the other). A condition is a frame match (identifier or identifier/mask, optional data mask and value, optional direction), a CANopen event (EMCY from any or a given node, optionally a given code; a node's NMT state change or boot-up; heartbeat lost; SDO abort; boot error), a decoded signal condition (greater, less, equal, not equal, crossing up or down, rising or falling edge), or a bus condition (error-warning, error-passive, bus-off, error frame). A trigger MAY fire only on its Nth match. In normal mode each hit SHALL add a marker and recording SHALL continue; in single mode recording SHALL stop when the post-trigger time after the hit has passed. Pre-trigger time (limited to what was recorded) and post-trigger time (0 to 600 s) SHALL be settable, and a hit MAY auto-save the window around it in a chosen format to a chosen folder, never inside the project's canopen folder.

#### Scenario: Single shot on EMCY
- **WHEN** the trigger is "EMCY from node 23", single mode, pre-trigger 5 s, post-trigger 2 s, and node 23 sends an EMCY
- **THEN** recording stops 2 s after the EMCY, a marker is placed on it, and the trace keeps at least the 5 s before it

#### Scenario: Normal mode with auto-save
- **WHEN** the trigger is "signal valve_status bit 3 rising", normal mode, auto-save as BLF, and the bit rises twice
- **THEN** recording continues, two markers are placed and two BLF files with the window around each hit are written

#### Scenario: Count
- **WHEN** the trigger is "SDO abort" with count 3
- **THEN** it fires on the third SDO abort only

### Requirement: Trace statistics
The trace SHALL show frames per second, estimated bus load in percent of the configured bit rate, lost and dropped frames, and error frame count.

It SHALL keep a per-identifier table, one row per identifier, extended flag and direction. Each row SHALL hold:
- the frame count;
- the decoded name;
- the last data;
- the bytes of the last data that changed since the identifier's previous frame, and when each byte last changed;
- the bytes that never changed in the trace;
- the minimum, average and maximum cycle time;
- the time of the last frame;
- whether the identifier is silent.

An identifier is silent when it has not been seen for more than three of its average cycles, and at least one second. Identifiers with fewer than three frames are never silent.

The table SHALL be updated as frames arrive, and SHALL answer only the rows changed since a given point, so that asking four times a second costs only the changed rows.

A reference SHALL be settable at the current moment of a recording, or at a frame of the trace. Each row SHALL then say which bytes differ from the reference and whether the identifier appeared after it.

#### Scenario: PDO cycle time
- **WHEN** node 23 sends TPDO1 every 10 ms for 10 s
- **THEN** the per-identifier table shows TPDO1 of node 23 with about 1000 frames and an average cycle time of about 10 ms

#### Scenario: Changed bytes
- **WHEN** node 5's TPDO1 arrives as `25 00 EA 00` and then as `25 00 EB 00`
- **THEN** its row marks byte 2 as changed and bytes 0, 1 and 3 as unchanged

#### Scenario: Reference compare
- **WHEN** a reference is set while node 5's TPDO1 holds `25 00 EA 00` and later frames hold `25 04 EA 00`
- **THEN** the row says byte 1 differs from the reference, also after further frames with the same data

#### Scenario: Incremental answer
- **WHEN** the table was read at generation 100 and only node 5's TPDO1 arrived since
- **THEN** the answer for changes since generation 100 holds only that row

### Requirement: A trace records one network
A trace SHALL record one network, picked in the trace view or by `--network NAME` on the trace command, and SHALL decode its frames with that network's nodes from the config. Saved traces SHALL record the network name with the interface and bit rate.

#### Scenario: Decode with the right nodes
- **WHEN** node 2 is an I/O module on `io` and a drive on `drives`, and the user traces `drives`
- **THEN** node 2's PDOs are decoded with the drive's mapping

#### Scenario: Trace command without a network
- **WHEN** the user runs the trace command without `--network` against two networks
- **THEN** it exits with status 1 naming `io` and `drives`

### Requirement: Frame inspector on traces
Any frame of a recorded or opened trace SHALL be explainable with the `canopen-frame-explain` model, using the configuration the trace is decoded with, the trace's bit rate and the SDO context of the trace at that frame. Explaining a frame SHALL work on traces of any size by explaining one frame at a time on the PC.

#### Scenario: Explain a recorded PDO
- **WHEN** a trace holds node 5's TPDO1 and the user explains it
- **THEN** the explanation shows each mapped signal's bits with their PLC addresses and the wire layer at the network's bit rate

### Requirement: SDO conversations
The trace SHALL list SDO conversations: each transfer from its initiate request to its final answer or abort, per node and SDO channel, with object and name, direction, size, value or abort text, number of frames and the time of each step. Segmented and block transfers SHALL be one conversation. A conversation SHALL be shown as a sequence diagram between master and node, each arrow opening its frame's explanation.

#### Scenario: Segmented upload
- **WHEN** the trace holds an 18-byte segmented upload of 1008h:00 from node 5
- **THEN** one conversation lists the initiate request and answer and three segment requests and answers, with the toggle bits and the read string

#### Scenario: Aborted write
- **WHEN** a write to a read-only object is answered with abort 0x06010002
- **THEN** the conversation ends in the abort with the text "attempt to write a read only object"

### Requirement: SYNC cycle view
For a trace with SYNC, the trace SHALL show one SYNC cycle at a time as a timeline: the SYNC, then every frame up to the next SYNC with its time after the SYNC, grouped as synchronous PDOs, other PDOs, SDO and other frames; next to each PDO its configured transmission type and, for synchronous PDOs, whether it came inside the configured SYNC window. The user SHALL be able to step through cycles and jump to the slowest cycle.

#### Scenario: Late TPDO
- **WHEN** the SYNC window is 2 ms and node 5's synchronous TPDO1 comes 2.6 ms after a SYNC
- **THEN** that cycle's timeline marks the TPDO as outside the SYNC window

### Requirement: Boot story
For each boot of a node found in a trace (a boot-up message, or an NMT reset command to it), the trace SHALL show the steps until the node's first PDO after the NMT start (or, when it sends none, its first heartbeat in Operational): boot-up, each SDO the master reads and writes with its object name and value, the NMT start, the first heartbeat in Operational and the first PDOs, with their times. The master's writes before the NMT start SHALL be compared with the writes the configuration makes at boot (the same list as the network document's boot configuration), and missing, extra, different and refused writes SHALL be marked.

#### Scenario: Refused write in a boot
- **WHEN** the device refuses the write of 1400h:02 during a boot in the trace
- **THEN** the boot story marks that step as refused with the abort text and shows that the node did not get to Operational

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

### Requirement: Decoding with gateway-routed entries
The decoding of a network's frames SHALL use the configured PDOs and EDS files of every node whenever the config passes the configurator's check, including PDO entries without a PLC location because a gateway route feeds them. A note about decoding without the config's PDOs SHALL appear only when the config itself has a problem, and SHALL name it in the user's terms, without file paths.

#### Scenario: Virtual-plant io
- **WHEN** a trace of the virtual-plant example's network io is shown
- **THEN** node 5's TPDO 1 is decoded with its mapped objects, the Graph offers its PDO signals, and no decoding note is shown

### Requirement: Identifier filters in hex
The trace's identifier filters SHALL read identifiers in hex, as the trace shows them, with or without `0x`, and the cyclic send jobs SHALL show their identifiers in hex.

#### Scenario: Hex range
- **WHEN** the user filters identifiers from 180 to 1FF
- **THEN** the trace shows the frames with identifiers 0x180 to 0x1FF

### Requirement: Views follow the picked network
On a network switch, the following SHALL drop what belonged to the previous network:
- the trace graph;
- the Frame lab result;
- the Simulation view's picked node;
- the shown transmit list, which changes to the picked network's list.

Cyclic send jobs started on the previous network SHALL keep running and SHALL stay listed in the status bar with that network's name.

A J1939 network SHALL show only J1939 kinds, sequences, trigger conditions and frame examples, and a CANopen network only CANopen ones.

#### Scenario: Simulation node after a switch
- **WHEN** node 5 is picked in the Simulation view on network io and the user switches to motion
- **THEN** the view shows motion's node 4 or no node, never node 5

#### Scenario: Transmit list after a switch
- **WHEN** a cyclic row runs on io and the user switches the picker to motion
- **THEN** the transmit list shows motion's rows, and the status bar still lists the io job with "io" in its label

### Requirement: PDO decoding without a configuration
When a node's PDOs are not in a configuration (Commission a device), the trace SHALL decode each PDO frame with that node's PDO layout from the best source available, in this order:
- **bus**: SDO writes in the trace to the node's PDO communication (0x1400-0x15FF, 0x1800-0x19FF) and mapping (0x1600-0x17FF, 0x1A00-0x1BFF) objects, and SDO read answers of them, whoever made them;
- **device**: the node's PDO objects read from the device on the live connection;
- **EDS**: the default COB-IDs and mappings of the node's EDS.

A layout learned from the bus SHALL apply from the frame that completed it, so PDO frames before it decode with the earlier layout. A PDO whose COB-ID is set invalid or whose mapping count is set to 0 SHALL stop decoding from that point. Where the bus gives only part of a PDO (for example only its mapping), the rest SHALL come from the next source. A layout read from the device SHALL apply to frames recorded after the read, and not to opened trace files.

Signals SHALL be named and typed from the node's EDS, or from the built-in CiA 301/401/402 object names when the node has no EDS; an object neither describes SHALL be shown as its index and subindex with its mapped length as an unsigned value. Decoded signals SHALL be available to graphs, triggers and the decoded CSV export like configured PDO signals.

#### Scenario: EDS defaults
- **WHEN** node 32 has an EDS whose TPDO1 maps a UNSIGNED16 Statusword and an INTEGER32 Position actual value at COB-ID 0x180+node ID, and the trace has `0x1A0 37 02 B0 04 00 00`
- **THEN** the row reads `TPDO1 node 32 Statusword=567, Position actual value=1200` with the "assumed" tag

#### Scenario: Mapping set by another master
- **WHEN** at 12.3 s the trace has SDO writes to node 32 that disable TPDO1, map 0x6064:0 alone and enable it again
- **THEN** TPDO1 frames before 12.3 s decode with the earlier layout, frames after it as `Position actual value=…`, and the inspector of a later frame says the layout was set on the bus at 12.3 s

#### Scenario: No EDS
- **WHEN** node 49 has no EDS, is a CiA 401 device by its 0x1000, and the bus set its TPDO1 to map 0x6000:1 (8 bits)
- **THEN** the row shows TPDO1 of node 49 with 0x6000:1 under its built-in CiA 401 name and its value

#### Scenario: Nothing known
- **WHEN** node 50 has no EDS, nothing on the bus sets its PDOs and its PDOs were not read
- **THEN** its PDO frames are shown as today, with the node and the bytes

### Requirement: DBC files in a trace
A trace SHALL decode with any number of DBC files the user adds, on every network kind, for live recordings and opened files alike. A DBC message SHALL be decoded as a raw message is (signal names, scale, offset, unit, byte order, multiplexing), in the rows, the inspector's bit grid, graphs, triggers and the decoded CSV export.

On an identifier, decoding SHALL be chosen in this order: the configuration's raw messages and PDOs; the DBC files, in the order listed; PDO layouts without a configuration; the predefined connection set. On identifiers of NMT, SYNC, TIME, EMCY, SDO, heartbeat and LSS the CANopen decoding SHALL stay and the DBC message's decoding SHALL be shown next to it. A DBC message not used because something earlier decodes its identifier SHALL be reported with what decodes it instead.

On a J1939 network, the network's own DBC SHALL keep decoding its PGNs; a trace DBC SHALL decode only identifiers that network does not decode.

#### Scenario: Vendor DBC in Commission a device
- **WHEN** the user adds a DBC whose message `Drive_Status` is 0x1A0 with signal `Position` (bytes 2-5, scale 0.01, unit mm), and the trace has node 32's TPDO1 on 0x1A0
- **THEN** the rows read `Drive_Status Position=1200 (12 mm)` instead of the inferred layout, and `Position` can be graphed

#### Scenario: Configuration wins
- **WHEN** a project configures node 32's TPDO1 on 0x1A0 and the user adds a DBC that also has a message on 0x1A0
- **THEN** the rows keep the configured TPDO1 and the DBC message is reported as not used because the configuration's TPDO1 of node 32 decodes 0x1A0

#### Scenario: Heartbeat in a DBC
- **WHEN** the DBC has a message on 0x720
- **THEN** the row still reads `Heartbeat node 32 OPERATIONAL`, the inspector also shows the DBC's decoding, and its signals are offered to graphs

#### Scenario: Trace command with a DBC
- **WHEN** the user runs `canworks-diag convert in.log out.csv --dbc machine.dbc`
- **THEN** the CSV's decoded column uses the DBC's messages
