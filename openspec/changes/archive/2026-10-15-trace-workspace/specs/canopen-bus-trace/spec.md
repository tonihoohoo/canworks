## MODIFIED Requirements

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
