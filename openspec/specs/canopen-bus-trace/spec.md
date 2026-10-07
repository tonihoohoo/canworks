# canopen-bus-trace Specification

## Purpose
Records the CAN traffic of the runtime's CANopen interface through the plugin's diagnostics channel, decodes it as CANopen, and lets the engineering PC save, open, export, graph and trigger on traces.

## Requirements

### Requirement: Record a trace on the PC
The configurator SHALL record a trace from the runtime's diagnostics channel in its own server process, so the trace survives a page reload or switching views, and SHALL stop recording only when the user stops it, a single-mode trigger ends it, or the configurator exits. It SHALL keep at least 2 million frames; past the limit the oldest frames SHALL be dropped and the user told. Frames lost on the PLC side SHALL be shown as gaps with their count.

#### Scenario: Reload during recording
- **WHEN** a trace is recording and the user reloads the configurator page
- **THEN** the trace view shows the frames recorded so far and recording continues

#### Scenario: Lost frames shown
- **WHEN** the plugin reports 120 lost frames during a fetch
- **THEN** the trace shows a gap marker with 120 lost frames at that time and the statistics count them

### Requirement: CANopen decoding
Every frame SHALL be decoded using the configuration and its EDS files: NMT commands with target node, SYNC, TIME, EMCY with error code text, error register and node name, heartbeat and boot-up with the NMT state, SDO requests and responses with the object index, subindex and EDS object name, expedited values as the EDS data type, abort codes with their text and segmented transfers shown as one completed transfer, LSS requests, and PDOs as signals named as in the DBC export (PLC variable names in editor-project mode) with values as the EDS data type. Frames that match nothing in the configuration SHALL be shown raw.

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
The trace SHALL show frames per second, estimated bus load in percent of the configured bit rate, lost and dropped frames, and error frame count, and a per-identifier table with frame count, decoded name, last data and minimum, average and maximum cycle time.

#### Scenario: PDO cycle time
- **WHEN** node 23 sends TPDO1 every 10 ms for 10 s
- **THEN** the per-identifier table shows TPDO1 of node 23 with about 1000 frames and an average cycle time of about 10 ms

### Requirement: A trace records one network
A trace SHALL record one network, picked in the trace view or by `--network NAME` on the trace command, and SHALL decode its frames with that network's nodes from the config. Saved traces SHALL record the network name with the interface and bit rate.

#### Scenario: Decode with the right nodes
- **WHEN** node 2 is an I/O module on `io` and a drive on `drives`, and the user traces `drives`
- **THEN** node 2's PDOs are decoded with the drive's mapping

#### Scenario: Trace command without a network
- **WHEN** the user runs the trace command without `--network` against two networks
- **THEN** it exits with status 1 naming `io` and `drives`
