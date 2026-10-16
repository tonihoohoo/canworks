# Spec Delta

## MODIFIED Requirements

### Requirement: Docked inspector and transmit pane
With By identifier and Chronological, the frame inspector SHALL be docked:
- beside the view at 1280 px and wider;
- under it in narrower windows, where the view and the inspector SHALL share the window's height below the toolbar, each scrolling on its own, so the selected row and the start of its explanation are in view together.

Its size SHALL change by dragging the split or with the arrow keys on the focused handle, and it SHALL be closable (see "Close and reopen the inspector"). The transmit list SHALL be a collapsible pane under the views, with its row and running job counts in its header. The inspector's size and state, the chosen view and the pane's height SHALL be kept on this PC.

#### Scenario: Wide window
- **WHEN** the window is 1440 px wide and the user selects a frame in Chronological
- **THEN** the inspector shows beside the list, and list, inspector and transmit pane fit without horizontal scrolling

#### Scenario: Narrow window
- **WHEN** the window is 1000 px wide
- **THEN** the inspector shows under the list, and every toolbar control is reachable without horizontal scrolling

#### Scenario: Narrow window shows the explanation
- **WHEN** the window is 1000 by 800 px and the user clicks the fifth row of Chronological
- **THEN** that row and the inspector's meaning are both inside the window without scrolling the page

#### Scenario: Split kept
- **WHEN** the user drags the inspector wider and reloads the page
- **THEN** the inspector opens at the width the user left it

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

#### Scenario: Bus after the deciding bit
- **WHEN** the arbitration demo runs `185#` against `183#`
- **THEN** after identifier bit 2 the Bus row shows the bits of 0x183 only (identifier bits 1 and 0 are 1 and 1), and node 5's row shows that it has stopped

## ADDED Requirements

### Requirement: Folding inspector layers
The inspector's Identifier, Data bits and On the wire layers SHALL each fold and unfold from their heading, by mouse or keyboard. The meaning SHALL always show. The folded state SHALL be kept on this PC and SHALL be the same in the Trace view and the Frame lab. A folded layer SHALL still show its one-line summary in its heading (for example the identifier arithmetic, the data bytes in hex, the frame length and time on the bus).

#### Scenario: Fold the data grid
- **WHEN** the user folds Data bits on an EMCY in the trace, then selects a TPDO and opens the Frame lab
- **THEN** Data bits is folded in both, its heading shows the frame's data bytes, and it is still folded after a reload

#### Scenario: Keyboard fold
- **WHEN** the user focuses the On the wire heading and presses Enter
- **THEN** the layer folds and its heading shows the frame length, stuff bits and time on the bus

### Requirement: Compact data grid
The data grid SHALL fit an 8-byte frame in no more than 260 px of height at the default font size. A field of two or more whole bytes that is unused or all zero SHALL show as one row with the field's name and bytes in hex, and opening that row SHALL show its bits. Every bit SHALL stay reachable with the keyboard, and pointing at the row SHALL highlight the field in every layer.

#### Scenario: Manufacturer data in one row
- **WHEN** the inspector explains `085#0010010000000000`
- **THEN** bytes 0 to 2 show as bit rows, bytes 3 to 7 show as one row "Manufacturer data: 00 00 00 00 00", and opening it shows those 40 bits

#### Scenario: Short grid
- **WHEN** an 8-byte SDO frame is explained in a 1440 px window
- **THEN** the data grid is at most 260 px tall

### Requirement: Close and reopen the inspector
The Trace inspector SHALL have a close button (✕) in its own title bar, and Esc with the focus inside the inspector SHALL close it and return the focus to the selected row. A closed inspector SHALL leave a slim **Inspector** rail at its edge that opens it again. Selecting a frame by click or Enter while it is closed SHALL open it. Moving through the list with the arrow keys SHALL NOT open it. The open or closed state SHALL be kept on this PC.

#### Scenario: Close with Esc
- **WHEN** the user tabs into the inspector of a selected SYNC frame and presses Esc
- **THEN** the inspector closes, the rail shows, and the focus is on the SYNC row

#### Scenario: Reopen by selecting
- **WHEN** the inspector is closed and the user clicks a TPDO row
- **THEN** the inspector opens on that TPDO

#### Scenario: Arrow keys keep it closed
- **WHEN** the inspector is closed and the user moves down the Chronological list with the arrow keys
- **THEN** the inspector stays closed and the selection moves

### Requirement: Frame lab layout
The Frame lab SHALL put the frame box (frame, Explain, bit rate) at the top, with tabs **Examples**, **Build** and **Arbitration** under it. Only the chosen tab's panel SHALL show, and the choice SHALL be kept for the page session. At 1280 px and wider, the result SHALL show in a column beside the input and SHALL stay in view while the page scrolls. In narrower windows the result SHALL show under the frame box, before the tabs. The Examples tab SHALL group the frames by network and node.

#### Scenario: Wide result beside the input
- **WHEN** the window is 1440 by 900 px and the user picks node 5's EMCY example
- **THEN** the result's meaning, identifier and data bits show beside the examples without scrolling the page

#### Scenario: Narrow result under the frame box
- **WHEN** the window is 1000 by 800 px and the user builds an SDO read
- **THEN** the result's meaning is inside the window without scrolling

#### Scenario: Arbitration result in the result column
- **WHEN** the user runs the arbitration demo at 1440 px
- **THEN** the demo's diagram and text show in the result column

### Requirement: Clear the Frame lab result
A Frame lab result SHALL have a **Clear** button that removes the result and empties the frame box, and leaves the chosen tab, the builder's values and the bit rate as they were. Esc in the frame box SHALL do the same. A frame from the trace SHALL keep **Back to trace** until Clear, an edit or another frame replaces it.

#### Scenario: Clear
- **WHEN** the user has explained `705#7F` and presses Clear
- **THEN** the result is gone, the frame box is empty and has the focus, and the Build tab still has its values

### Requirement: Frame lab result in view
Each new Frame lab result SHALL come into view without the user scrolling:
- Explain;
- an example frame;
- Build and explain;
- Run both;
- Explain in Frame lab from the trace.

The focus SHALL stay on the control the user used. On a result from Explain in Frame lab, the focus SHALL go to the result's heading.

#### Scenario: Explain in Frame lab at 1000 px
- **WHEN** the window is 1000 by 800 px and the user picks Explain in Frame lab on a SYNC frame
- **THEN** the Frame lab shows the frame's meaning and Back to trace inside the window

### Requirement: Simulation banner on one line
The simulation banner SHALL show one line per page: what is simulated, network by network, and that the configuration must not be uploaded to a machine as it is. Each network's part SHALL be short, for example "io (nodes 5, 6, 7)". A **Details** control SHALL open the full text of each network's simulation. On a phone-width window it SHALL take at most two lines.

#### Scenario: Four simulated networks
- **WHEN** the virtual plant example is open at 1440 px
- **THEN** the banner is one line naming io (nodes 5, 6, 7), motion (node 4), cell and host and saying not to upload it, and Details opens the full text
