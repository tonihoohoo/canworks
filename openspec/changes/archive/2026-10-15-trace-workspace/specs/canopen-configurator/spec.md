## ADDED Requirements

### Requirement: Trace toolbar and views
The Trace tool tab SHALL have one toolbar with:
- one Start / Stop button;
- Clear and Open…;
- a Save menu with "Save to traces folder" and "Download as…", each with its format, and the range;
- Capture… for capture filters and error frames;
- the time mode.

Under it SHALL be the header with the statistics and the view tabs **By identifier**, **Chronological**, **Graph**, **Sequences** (not on J1939) and **Trigger**.

#### Scenario: One Start / Stop button
- **WHEN** the user presses Start
- **THEN** the same button reads Stop until the recording stops

### Requirement: Display filters shared by both lists
One Filters control SHALL hold the display filters of By identifier and Chronological. It SHALL show the number of active filters, and while one is active the statistics SHALL say how many frames are shown.

#### Scenario: Filters shared
- **WHEN** the user filters node 5 in Chronological and opens By identifier
- **THEN** By identifier lists only node 5's identifiers and the Filters control shows one active filter

### Requirement: Docked inspector and transmit pane
With By identifier and Chronological, the frame inspector SHALL be docked:
- beside the view at 1280 px and wider;
- under it in narrower windows.

Its size SHALL change by dragging the split or with the arrow keys on the focused handle, and it SHALL be closable. The transmit list SHALL be a collapsible pane under the views, with its row and running job counts in its header. The inspector's size and state, the chosen view and the pane's height SHALL be kept on this PC.

#### Scenario: Wide window
- **WHEN** the window is 1440 px wide and the user selects a frame in Chronological
- **THEN** the inspector shows beside the list, and list, inspector and transmit pane fit without horizontal scrolling

#### Scenario: Narrow window
- **WHEN** the window is 1000 px wide
- **THEN** the inspector shows under the list, and every toolbar control is reachable without horizontal scrolling

#### Scenario: Split kept
- **WHEN** the user drags the inspector wider and reloads the page
- **THEN** the inspector opens at the width the user left it

### Requirement: By identifier view
The Trace tab SHALL open on **By identifier**, or on the view last chosen on this PC. It SHALL show one row per identifier, extended flag and direction, with:
- direction, identifier (hex) and decoded name (PGN and source on J1939);
- DLC, last data and decoded values;
- count, and last, average, minimum and maximum cycle;
- time since last seen (for a file, the last frame's time).

Rows SHALL be in identifier order by default and SHALL NOT move as frames arrive.

#### Scenario: Busy bus at a glance
- **WHEN** a network carries 40 identifiers at 800 frames per second and the user opens Trace and presses Start
- **THEN** the By identifier view shows 40 rows in identifier order whose counts, cycle times and data update in place

#### Scenario: Opened file
- **WHEN** nothing is connected and the user opens a candump log file
- **THEN** the By identifier view lists every identifier of the file with its count and cycle times over the whole file

### Requirement: Sorting the By identifier view
Each column header of the By identifier view SHALL sort the rows by that column and SHALL announce the sort order. The chosen sort SHALL be kept on this PC.

#### Scenario: Sort by count
- **WHEN** the user clicks the Count header
- **THEN** rows are sorted by count and the header announces the sort order

### Requirement: Live updates of the By identifier view
While recording, rows SHALL update in place at least twice and at most four times a second. Updates SHALL keep focus, selection and the scroll position. The table SHALL stay responsive with 2,000 identifiers. **Pause view** SHALL stop updating the table while recording continues, and SHALL say how many updates are waiting.

#### Scenario: Focus kept
- **WHEN** the user has focused the third row and new frames arrive for every identifier
- **THEN** the third row keeps focus and the list does not scroll

#### Scenario: Pause view
- **WHEN** the user presses Pause view while recording
- **THEN** the table stops changing, recording continues, and the view says updates are waiting

### Requirement: Change marks and reference
Bytes that changed since the identifier's previous frame SHALL be marked for one second, not by colour alone. Pointing at or focusing the data SHALL show which bits changed. Bytes that never changed in the trace SHALL be muted.

**Set reference** SHALL take each row's current data as the reference (for a file, the data at a picked frame). Until **Clear reference**, bytes that differ from it SHALL stay marked, and rows that appeared after it SHALL be marked new.

#### Scenario: Find the byte that follows a switch
- **WHEN** the user presses Set reference, then flips a digital input wired to node 5, whose TPDO1 byte 2 changes from 00 to 04
- **THEN** byte 2 of node 5's TPDO1 row stays marked as different from the reference, and pointing at it shows bit 2 changed

#### Scenario: New after reference
- **WHEN** a reference is set and node 9 then boots
- **THEN** node 9's boot-up and heartbeat rows are marked new

### Requirement: Silent identifiers
A row not seen for more than three of its average cycles, and at least one second, SHALL be shown as silent with the time since it was last seen. Rows with fewer than three frames SHALL never be marked silent.

#### Scenario: Silent node
- **WHEN** node 7's heartbeat came every 100 ms and node 7 is switched off
- **THEN** within a second its heartbeat row is shown as silent with the time since it was last seen

### Requirement: Selection in the By identifier view
Selecting a row SHALL show the identifier's latest frame in the inspector, which SHALL follow new frames until the user holds it. The arrow keys, Home, End, Page Up and Page Down SHALL move the selection. The selected row SHALL offer:
- **Show frames**: Chronological filtered to that identifier;
- **Explain in Frame lab**;
- **Send…**;
- **Graph signals**: its decoded signals added to the graph.

#### Scenario: Row moves to the inspector
- **WHEN** the user selects node 5's TPDO1 row
- **THEN** the inspector explains its latest frame and follows each new frame of that identifier until the user holds it

#### Scenario: Show frames
- **WHEN** the user picks Show frames on the row of identifier 0x285
- **THEN** the Chronological view opens filtered to identifier 0x285

### Requirement: Transmit list
The Trace tab SHALL have a transmit list for the picked network. Each row SHALL hold:
- an optional name;
- identifier (hex), extended, remote and DLC;
- up to 8 data bytes;
- a period of 10 to 60000 ms (empty: one frame) and an optional count.

Each row SHALL show its state (idle, last sent, running with count, or refused with the reason) and a decoded preview. Rows SHALL be added, edited in place, duplicated, moved and removed, checked as typed. Clear list SHALL ask, Cancel being the default.

#### Scenario: Bad data
- **WHEN** the user types `0F 1` in a row's data
- **THEN** the field says the data needs whole bytes and the row's Send is disabled

#### Scenario: Preview names the identifier
- **WHEN** the user types identifier 205 on a network where it is RPDO1 of node 5
- **THEN** the row's preview names RPDO1 of node 5 and says the identifier is in use

### Requirement: Sending from the transmit list
A single row SHALL have Send, and a cyclic row Start or Stop, using `send_frame` and `send_frame_stop` through the connection bar's connection.
- Without a connection with Allow changes, they SHALL be disabled with the reason, and the list SHALL stay editable.
- A `force` refusal SHALL show the reason in a confirmation and resend with `force` only when confirmed.

#### Scenario: Single frame while recording
- **WHEN** a trace is recording and the user presses Send on a row with 0x60A and eight data bytes
- **THEN** the frame appears in the trace once, as Tx, and the row shows the time it was sent

### Requirement: Cyclic send jobs
Running cyclic jobs SHALL be listed in the status bar with their network, identifier, period, sent count and Cancel. They SHALL keep running across tabs, workspaces and network switches. They SHALL stop on Stop, Stop all, Cancel, Disconnect, a connection end or closing the page.

#### Scenario: Cyclic job outlives the tab
- **WHEN** the user starts a row with 0x301 every 100 ms and opens the Network tab
- **THEN** the job keeps sending, the status bar lists it with its sent count, and Cancel there stops it

#### Scenario: Force needs confirmation
- **WHEN** the user sends a row with 0x205, which is RPDO1 of node 5
- **THEN** a confirmation quotes "0x205 is RPDO1 of node 5" and nothing is sent unless the user confirms

#### Scenario: No changes allowed
- **WHEN** the connection does not allow changes
- **THEN** Send and Start are disabled, the list says that sending needs Allow changes, and rows can still be edited and saved

#### Scenario: Ninth cyclic job
- **WHEN** 8 cyclic jobs run on network io and the user starts a ninth
- **THEN** the row shows the refusal with the plugin's reason and the other 8 keep running

### Requirement: Transmit list storage and files
The transmit list SHALL be kept on this PC per folder and network, and per network in Commission a device. It SHALL come back after a reload with no job running. It SHALL NOT be written into the project folder or the config. Save list… SHALL write a JSON file (`"format": "canworks-transmit"`, `"version": 1`, the network and the rows). Open list… SHALL replace the list or add to it, as the user chooses, and SHALL ask before using a list saved for another network.

#### Scenario: List comes back
- **WHEN** the user has three rows on network io, closes the configurator and opens the same folder the next day
- **THEN** the transmit list of io has the same three rows, none running

#### Scenario: Save and open a list
- **WHEN** the user saves the list as `valve-test.transmit.json` and opens it on another PC for the same network
- **THEN** the rows are the same, with names, identifiers, data, periods and counts

### Requirement: Explain in Frame lab
A trace frame (Chronological, By identifier or the inspector) SHALL offer **Explain in Frame lab**. It SHALL open the Frame lab with the frame, the trace's network and bit rate, and the frame's SDO context, showing where the frame came from with **Back to trace**. Back to trace SHALL return to the trace with that frame selected. Editing the frame SHALL drop the SDO context and SHALL say the frame was edited. Trace and Frame lab SHALL use one inspector component.

#### Scenario: Change a bit of a recorded frame
- **WHEN** the user picks Explain in Frame lab on node 5's TPDO1 frame and sets bit 3 of byte 0
- **THEN** the Frame lab explains the changed frame at the trace's bit rate and says it was edited from that trace frame

#### Scenario: Segment keeps its transfer
- **WHEN** the user picks Explain in Frame lab on the third segment of an upload of 1008h:00
- **THEN** the Frame lab explains it as segment 3 of that upload

#### Scenario: Back to trace
- **WHEN** the user presses Back to trace in the Frame lab
- **THEN** the Trace tab shows the same view with that frame selected

### Requirement: Send… adds to the transmit list
A trace frame and a Frame lab result SHALL offer **Send…**. It SHALL:
- add the frame as a new single-send row at the end of the transmit list of the frame's network;
- show the Trace tab with the transmit list open;
- move focus to that row's Send button.

Send… SHALL put nothing on the bus itself. It SHALL be enabled only while a connection with Allow changes is open, and SHALL otherwise say why.

#### Scenario: Send a built frame
- **WHEN** the user builds a write of 1017h:00 = 1000 to node 5 in the Frame lab, is connected with Allow changes and picks Send…
- **THEN** the transmit list gets a row `605` `2B 17 10 00 E8 03 00 00`, focus is on its Send button, and nothing is sent until the user presses it

#### Scenario: Send… without a connection
- **WHEN** nothing is connected
- **THEN** Send… is disabled and says that sending needs a connection with Allow changes

## MODIFIED Requirements

### Requirement: Trace view
The Trace tool tab SHALL work without a connection for opening, viewing and exporting trace files. Recording and the transmit list SHALL use the connection in the connection bar, runtime or adapter, in every workspace. Without a connection, the view SHALL say that recording needs one and offer Connect…, which opens the connect panel. The trace header SHALL name the connection a recording uses (adapter and bit rate, or runtime) and the network.

The view SHALL offer (see "Trace toolbar and views"):
- start and stop, capture filters, error frames and clear;
- "Save to traces folder" (on this PC), open, and "Download" (a file in the chosen format), the two format choices labelled apart;
- the By identifier view and a scrolling decoded Chronological view;
- display filters by node, frame kind (NMT, SYNC, EMCY, heartbeat, SDO, PDO, LSS, error, other), identifier range, direction and text;
- the graph and trigger settings, and the statistics;
- the transmit list.

Times SHALL be shown relative to the trace start or as UTC clock time. When the runtime's plugin does not know the trace operations, the view SHALL say that the plugin is too old for traces.

**Connection end.** When the connection ends during a recording, the recording SHALL stop, keep its frames, add a marker with the reason, and the header SHALL say why it stopped.

**Start with frames.** Start with frames in the trace SHALL ask:
- **Continue this trace** (the default, adding a gap marker; only on the same network);
- **New trace**, saying that the current recording is lost unless it was saved or downloaded;
- **Cancel**.

Clear SHALL say that the current recording is lost unless it was saved or downloaded, with Cancel as the default. Closing the page or the folder with an unsaved recording SHALL ask first.

**Keyboard and jobs.** The Chronological and By identifier lists SHALL move their selection with the arrow keys, Home, End, Page Up and Page Down. The view's tabs SHALL follow the page's tab pattern (see "Keyboard access and announcements"). A running recording SHALL be listed in the status bar with its frame count and Cancel (stop).

#### Scenario: Start a trace
- **WHEN** the page is connected to a runtime and the user opens Trace and presses Start
- **THEN** the By identifier view fills with decoded rows, the statistics update while the bus runs, and the status bar lists the recording

#### Scenario: Record while commissioning
- **WHEN** the user is connected to an adapter in Commission a device and presses Start in Trace
- **THEN** the adapter's frames are recorded and decoded, the header names the adapter and its bit rate, and no runtime host or token is asked for

#### Scenario: Filter display
- **WHEN** the user shows only node 23 and frame kind SDO
- **THEN** both the By identifier and the Chronological view list only SDO requests and responses of node 23, and recording of other frames continues

#### Scenario: Old plugin
- **WHEN** the runtime's plugin answers the trace start as an unknown operation
- **THEN** the view says the plugin on the runtime is too old for traces and how to update it

#### Scenario: Open a file without a runtime
- **WHEN** nothing is connected and the user opens a candump log file in the Trace view
- **THEN** the frames are shown decoded and can be graphed and exported, and recording offers Connect…

#### Scenario: Works offline
- **WHEN** the PC has no internet access
- **THEN** the Trace view and its graphs load and work

#### Scenario: Clear asks
- **WHEN** a recording of 3,000 frames has not been saved and the user clicks Clear
- **THEN** a dialog says the 3,000 frames are lost unless saved or downloaded, Cancel is the default, and Enter keeps the recording

#### Scenario: Connection ends while recording
- **WHEN** an adapter connection ends with bus-off during a recording of 5,000 frames
- **THEN** the recording stops with the 5,000 frames kept, a marker reads "connection ended: bus-off", and the header says the recording stopped because the connection ended

#### Scenario: Continue after reconnecting
- **WHEN** the user reconnects to the same network and presses Start
- **THEN** a dialog offers Continue this trace as the default, and continuing appends new frames after a gap marker with the gap's length

### Requirement: Frame inspector panel
In the Trace view, selecting a frame in the Chronological or By identifier view SHALL show the inspector docked beside or under the view (see "Docked inspector and transmit pane"). The inspector SHALL have the four layers of the `canopen-frame-explain` model:
- the meaning;
- the identifier bits split into function code and node ID;
- a data grid with one row per byte (most significant bit on the left, CANopen bit number on each bit, each bit coloured by its field);
- the field list with values and working;
- the wire strip with framing, stuff bits marked, the bus level line and the timing figures.

Pointing at or focusing a bit or field SHALL show its explanation in a box that stays in view. It SHALL highlight the same bits in every layer (a data bit in the grid and on the wire, a field's bits in the grid). Every bit SHALL be reachable with the keyboard.

The panel SHALL follow the selected frame when the user moves through the list with the arrow keys. It SHALL offer the frame's SDO conversation, SYNC cycle or boot story where one exists, and Explain in Frame lab and Send… (see "Explain in Frame lab" and "Send… adds to the transmit list"). The same inspector component SHALL serve the Frame lab. It SHALL work on opened trace files without a runtime, offline, in light and dark themes and at phone width.

#### Scenario: Point at a data bit
- **WHEN** the user points at bit 2 of byte 0 of node 5's TPDO1, whose first byte is mapped to `%IB100`
- **THEN** the box names the bit, its value, "bit 2 of `%IB100`", the object and the wire bit number, and that bit is highlighted in the grid and on the wire strip

#### Scenario: Keyboard
- **WHEN** the user tabs into the data grid and moves with the arrow keys
- **THEN** each focused bit is explained in the box

#### Scenario: Same inspector in the Frame lab
- **WHEN** the user explains frame `185#2500EA00` in the Frame lab and the same frame in a trace
- **THEN** both inspectors show the same layers, fields and wire bits

### Requirement: Frame lab view
The Frame lab SHALL be a tool tab in every workspace that works without a connection and without a trace. It SHALL:
- accept a frame typed as identifier and data or pasted in candump syntax;
- offer example frames and the frame builder of the `canopen-frame-explain` capability;
- show the result in the shared inspector at the network's bit rate, with a bit rate picker.

The example frames SHALL come from the open configuration (saved or not). In Commission a device they SHALL come from the EDS files of the nodes on the Nodes tab: each node's boot-up, heartbeat, and SDO read of 1018h:01 with its answer.

The Frame lab SHALL have an arbitration demo: two frames chosen by the user are shown sent at the same time bit by bit. The demo SHALL show each sender's bit, the bus level, the bit where the sender of a recessive bit reads a dominant level and stops, and which frame wins.

The Frame lab SHALL accept a frame from the trace with its context (see "Explain in Frame lab"). It SHALL send nothing to the bus itself and SHALL say so. Its only route to the bus SHALL be **Send…**, which adds the frame to the transmit list without sending it. None of its other controls SHALL be labelled as sending (the arbitration demo's button is "Run both").

#### Scenario: Paste a frame
- **WHEN** the user pastes `705#7F` in the Frame lab
- **THEN** it is explained as node 5's heartbeat in Pre-operational

#### Scenario: Arbitration
- **WHEN** the user picks node 5's TPDO1 (0x185) and node 3's TPDO1 (0x183) for the arbitration demo
- **THEN** the demo shows both identical up to identifier bit 2, node 3's frame driving it dominant there, node 5's sender stopping, and 0x183 winning

#### Scenario: Example frames follow the config
- **WHEN** the user adds node 7 without saving and opens the Frame lab
- **THEN** the example frames include node 7's boot-up, heartbeat, SDO read of 1018h:01 and its PDOs

#### Scenario: Examples in Commission a device
- **WHEN** the Nodes tab of Commission a device has node 12 with an EDS from the library
- **THEN** the Frame lab's example frames include node 12's boot-up, heartbeat and SDO read of 1018h:01 with the EDS's object name

### Requirement: One connection for every view
The Commission pages, Trace recording and its transmit list, the Simulation view's **Runtime** target and the PDO test SHALL use the connection in the connection bar. None of them SHALL have its own connect form, host field or adapter field. Without a connection, each SHALL say that it needs one, with a button that opens the connect panel. The Simulation view's **Standalone simulator** address and token SHALL stay in the Simulation view, because they reach `canworks-sim`'s control channel, not a bus.

#### Scenario: Trace uses the open connection
- **WHEN** the user connected to a runtime in Commission and opens Trace in Configure and presses Start
- **THEN** recording starts through that runtime without asking for a host or token

#### Scenario: Trace without a connection
- **WHEN** nothing is connected and the user opens Trace
- **THEN** files can be opened and viewed, and Start is replaced by a note that recording needs a connection with a Connect… button

### Requirement: Keyboard access and announcements
Everything the pointer can do on the page SHALL be possible with the keyboard.
- **Lists:** the node list and the problem list SHALL be made of buttons in the tab order, with the active node marked as current. Rows that open something (online nodes, scanned devices, simulated devices) SHALL be focusable and open on Enter or Space.
- **Tabs:** tabs (Trace, the online node's Overview / Object dictionary / Parameters, Simulation) SHALL be a tab list with the selected tab marked and each tab naming its panel. Left, Right, Home and End SHALL move between them.
- **Focus:** every focused control SHALL show a visible focus ring in the accent colour.
- **Announcements:** progress lines (reading all, backup, scan) and the problem count SHALL be polite live regions.
- **Structure:** landmarks SHALL not be nested complementary regions, heading levels SHALL not skip, and every table column with only buttons SHALL have a header text for assistive technology.

#### Scenario: Open a node with the keyboard
- **WHEN** the user presses Tab from the Save button
- **THEN** focus moves through the node list, and Enter on "5 rtd" opens node 5's page

#### Scenario: Problems by keyboard
- **WHEN** the user tabs into the Problems pane and presses Enter on the first problem
- **THEN** the field with that problem gets focus

#### Scenario: Tabs by keyboard
- **WHEN** focus is on the Trace view's "By identifier" tab and the user presses Right
- **THEN** "Chronological" is selected and its panel shows

## REMOVED Requirements

### Requirement: Send frames from the Trace view
**Reason**: The one-frame Send panel becomes the transmit list. It keeps several frames, keeps them on this PC and in files, and keeps cyclic jobs running outside the Trace tab. "Send this frame" becomes Send…, which adds a row instead of filling a form.
**Migration**: Use the transmit list under the trace views. Add a frame with Add frame or Send… on a trace row, then press Send (single) or Start (cyclic). The send rules (Allow changes, `force` confirmation, hex identifiers, the plugin's job limit) are unchanged and are specified in "Sending from the transmit list".
