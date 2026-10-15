## MODIFIED Requirements

### Requirement: Live updates of the By identifier view
While recording, rows SHALL update in place at least twice and at most four times a second. Updates SHALL keep focus, selection and the scroll position. The table SHALL stay responsive with 2,000 identifiers. **Pause view** SHALL stop updating the table while recording continues, and SHALL say how many updates are waiting. While the view is paused the button SHALL read **Resume view**; pressing it SHALL show the waiting updates and read Pause view again.

#### Scenario: Focus kept
- **WHEN** the user has focused the third row and new frames arrive for every identifier
- **THEN** the third row keeps focus and the list does not scroll

#### Scenario: Pause view
- **WHEN** the user presses Pause view while recording
- **THEN** the table stops changing, recording continues, and the view says updates are waiting

#### Scenario: Pause button says what it does
- **WHEN** the user presses Pause view while recording
- **THEN** the button reads Resume view, and pressing it again shows the waiting updates and the button reads Pause view

### Requirement: Frame inspector panel
In the Trace view, selecting a frame in the Chronological or By identifier view SHALL show the inspector docked beside or under the view (see "Docked inspector and transmit pane"). The inspector SHALL have the four layers of the `canopen-frame-explain` model:
- the meaning;
- the identifier bits split into function code and node ID;
- a data grid with one row per byte (most significant bit on the left, CANopen bit number on each bit, each bit coloured by its field);
- the field list with values and working;
- the wire strip with framing, stuff bits marked, the bus level line and the timing figures.

Pointing at or focusing a bit or field SHALL show its explanation in a box that stays in view. It SHALL highlight the same bits in every layer (a data bit in the grid and on the wire, a field's bits in the grid). Every bit SHALL be reachable with the keyboard.

The panel SHALL follow the selected frame when the user moves through the list with the arrow keys. When the panel moves to a newer frame on its own, it SHALL keep **About this kind of message** open or closed as the user left it; for a newer frame of the same identifier it SHALL also keep the explained field, its scroll position and focus. It SHALL offer the frame's SDO conversation, SYNC cycle or boot story where one exists, and Explain in Frame lab and Send… (see "Explain in Frame lab" and "Send… adds to the transmit list"). The same inspector component SHALL serve the Frame lab. It SHALL work on opened trace files without a runtime, offline, in light and dark themes and at phone width.

#### Scenario: Point at a data bit
- **WHEN** the user points at bit 2 of byte 0 of node 5's TPDO1, whose first byte is mapped to `%IB100`
- **THEN** the box names the bit, its value, "bit 2 of `%IB100`", the object and the wire bit number, and that bit is highlighted in the grid and on the wire strip

#### Scenario: Keyboard
- **WHEN** the user tabs into the data grid and moves with the arrow keys
- **THEN** each focused bit is explained in the box

#### Scenario: Same inspector in the Frame lab
- **WHEN** the user explains frame `185#2500EA00` in the Frame lab and the same frame in a trace
- **THEN** both inspectors show the same layers, fields and wire bits

#### Scenario: About stays open while live
- **WHEN** the user selects node 32's heartbeat row while recording, opens About this kind of message, and new heartbeats arrive
- **THEN** the section stays open, and it is still open when the user selects another row

## ADDED Requirements

### Requirement: Newest frame whole in the Chronological view
The Chronological view SHALL draw exactly the rows in view, including a row partly scrolled past the top edge. Scrolled to the end, and while it follows a recording, the newest frame SHALL be the last row and SHALL be shown whole at the bottom edge; any row cut short SHALL be the one at the top.

#### Scenario: Following a recording
- **WHEN** the Chronological view follows a recording and its height is not a whole number of rows
- **THEN** the newest frame is the bottom row, shown whole, and no newer frame is hidden below it

### Requirement: Picking a sequence keeps the list in place
Picking an SDO conversation or a boot story in the Sequences tab, by click or Enter, SHALL keep the list's scroll position and the page position, and the picked row SHALL keep focus.

#### Scenario: Pick a conversation far down the list
- **WHEN** the user scrolls the SDO conversations to the end and clicks the last conversation
- **THEN** the list stays scrolled where it was, the row is marked picked and its sequence diagram opens below
