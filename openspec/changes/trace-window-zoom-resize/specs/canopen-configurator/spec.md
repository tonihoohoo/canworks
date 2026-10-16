## MODIFIED Requirements

### Requirement: Trace toolbar and views
The Trace tool tab SHALL have one toolbar with:
- one Start / Stop button;
- Clear and Open…;
- a Save menu with "Save to traces folder" and "Download as…", each with its format, and the range;
- Capture… for capture filters and error frames;
- Decoding… for DBC files and the nodes' PDO layouts (see "Decoding panel in the Trace view");
- the time mode.

Under it SHALL be the header with the statistics and the view tabs **By identifier**, **Chronological**, **Graph**, **Sequences** (not on J1939) and **Trigger**.

The height of the By identifier list, the Chronological list and the Graph SHALL be adjustable by dragging a resize bar under each, bigger or smaller, with the arrow keys on the focused bar (Up smaller, Down bigger, 40 px a step) and double-click on the bar back to the default. The lists SHALL be between 120 px and 3000 px high, and one setting SHALL cover both lists. The graph's height SHALL be set per lane, between 80 px and 1000 px, and all lanes SHALL share it; the default stays 200 px per lane (150 px with more than two lanes) until the user resizes. The heights SHALL be kept on this PC with the other trace view settings and SHALL be used again after a reload. While the list and the inspector share the window height (between the phone and the wide layout), the list's bar SHALL be hidden and that layout is unchanged.

#### Scenario: One Start / Stop button
- **WHEN** the user presses Start
- **THEN** the same button reads Stop until the recording stops

#### Scenario: Make the list taller
- **WHEN** the user drags the bar under the Chronological list 300 px down and reloads the page
- **THEN** the list is 300 px taller, shows more rows, and is still that height after the reload and in By identifier

#### Scenario: Make the graph lanes taller
- **WHEN** two lanes are graphed and the user drags the bar under the graph 200 px down
- **THEN** each lane is 300 px high, the graph is redrawn at that height with the cursors kept, and double-click on the bar returns both lanes to 200 px

## ADDED Requirements

### Requirement: Trace in its own window
The Trace view SHALL have an **Open in new window** button that opens the trace in a separate browser window, so the trace can be watched while the main window sends messages or edits the config. It SHALL NOT be shown below the phone width, and SHALL bring an already open trace window to the front.

#### Scenario: Watch the trace while sending
- **WHEN** the user records in Trace, presses **Open in new window**, and then sends an SDO write from the online view in the main window
- **THEN** the trace window keeps recording and shows the SDO request and response as they happen

### Requirement: Trace window contents
The trace window SHALL show only the Trace view (toolbar, header, view tabs and transmit list) under a one-line bar naming the project folder, network and connection, titled "Trace" and the folder's name. It SHALL use the main window's session, recording and connection, with no Connect button of its own, and SHALL stay a trace window when reloaded. Its last size SHALL be kept with the trace view settings.

#### Scenario: No connection
- **WHEN** the trace window is open and nothing is connected
- **THEN** it says that recording needs a connection made with **Connect…** in the main window

#### Scenario: Main window changes network
- **WHEN** the main window connects to another network or opens another project folder
- **THEN** the trace window follows it

### Requirement: Main window while the trace has its own window
While the trace window is open, the main window's Trace tab SHALL say "Trace is open in its own window" with **Show trace window** and **Bring trace back here**, and SHALL NOT draw or poll the trace. Actions in the trace window that lead to another view SHALL be carried out in the main window, or open the main page when it was closed.

#### Scenario: Bring the trace back
- **WHEN** the trace window is open and the user presses **Bring trace back here** in the main window's Trace tab
- **THEN** the trace window closes and the main window's Trace tab shows the same recording, with no frames lost

#### Scenario: Open a node from the trace window
- **WHEN** the user selects an SDO frame of node 5 in the trace window and opens node 5 from the inspector
- **THEN** the main window shows node 5 in the online view and comes to the front, and the trace window stays open

### Requirement: Closing a trace window
Recording SHALL go on when either window closes, and only the window showing the trace SHALL ask about an unsaved recording on closing.

#### Scenario: Main window closed
- **WHEN** the user closes the main window during a recording while the trace window is open
- **THEN** the trace window keeps recording and the main window asks nothing about the recording

#### Scenario: Trace window closed
- **WHEN** the user closes the trace window
- **THEN** the main window's Trace tab shows the trace again
