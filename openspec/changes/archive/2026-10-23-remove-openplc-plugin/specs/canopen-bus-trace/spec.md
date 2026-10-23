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
- **WHEN** the bridge reports 120 lost frames during a fetch
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
