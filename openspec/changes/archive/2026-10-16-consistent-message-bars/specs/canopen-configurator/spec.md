## ADDED Requirements

### Requirement: One look for messages
Every message about a page, view, section or dialog SHALL be a message bar of one of four kinds: information, done, warning or error. Each kind SHALL have one tint, one left accent bar in its state colour and one state icon, the same on every page, tool tab and dialog, in light and dark theme. Information and done SHALL use the neutral tint; warning the warning tint; error the error tint.

#### Scenario: Same warning everywhere
- **WHEN** the user sees a warning in the message bar, in a node's Parameters tab and in the Machine view
- **THEN** the three have the same tint, accent bar and warning icon

#### Scenario: Dark theme
- **WHEN** the theme is Dark
- **THEN** each kind uses the dark values of its tokens and its text keeps the normal text colour

### Requirement: Message actions
A message bar MAY carry actions after its text, such as Undo, Unlock…, Remove, Details or Retry, as buttons in the same row. The text SHALL say what happened and what to do, with no "Error:" or "Warning:" prefix, as the word list says.

#### Scenario: Locked with Unlock
- **WHEN** the user is connected read-only and opens node 5's Error history
- **THEN** a warning bar says "Locked. Changes are not allowed on this connection." with Unlock… in the same bar

### Requirement: Messages at the top
A message SHALL sit at the top of what it is about. A view's or section's message SHALL sit directly under its heading, before its first control. No message SHALL sit below a section's buttons or at the bottom of a view or panel. Several messages in one place SHALL be ordered error, warning, information, done.

#### Scenario: Parameters job result
- **WHEN** Read all on node 5's Parameters tab ends
- **THEN** its result is a bar under the Parameters heading, above the buttons, and nothing is added at the bottom of the tab

#### Scenario: Connection line in Nodes
- **WHEN** the user opens Commission → Nodes without a connection
- **THEN** the line saying what the view needs a connection for is under the heading, above the scan toolbar

#### Scenario: NMT locked note
- **WHEN** the user is connected read-only and opens node 5's Status tab
- **THEN** the NMT box's locked note is at the top of the box, above Start, Stop and the other NMT buttons

### Requirement: Field text stays at the field
A hint, a field's own error, a table row's own error and a value read into a row SHALL stay next to the field or in the row, and SHALL NOT be message bars. The Problems panel and the status bar SHALL stay at the bottom of the page, and Problems rows SHALL use the warning and error tints and icons of the message bars.

#### Scenario: Send row error
- **WHEN** a row of the Send panel has an identifier out of range
- **THEN** the error is in that row, next to the identifier field

### Requirement: Messages in dialogs
A message about a dialog's work SHALL be a message bar at the top of the dialog body, under its title or question, while the dialog is open. A dialog SHALL NOT report in the page's message bar behind it or refer to it.

#### Scenario: Connect fails
- **WHEN** the user presses Connect in the connect panel and the runtime does not answer
- **THEN** an error bar at the top of the panel says why, the panel stays open, and the page's message bar is unchanged

#### Scenario: Nothing to restore
- **WHEN** the restore preview finds no differences
- **THEN** an information bar at the top of the dialog says so

### Requirement: Announced once
An error bar SHALL have the alert role and a warning, information or done bar the status role when it appears or changes. A bar that is drawn with its view SHALL NOT be announced again when the view opens.

#### Scenario: Opening a locked tab
- **WHEN** the user opens the Object dictionary tab while connected read-only
- **THEN** the locked bar is shown and a screen reader does not read it unless the user moves to it

## MODIFIED Requirements

### Requirement: Message bar
Messages about the user's actions that are not tied to one section (saved, sent, copied, added, and errors of a request) SHALL be shown in a message bar under the header and the simulation banner that stays in view while the page scrolls and has a close button. Information and done messages SHALL close by themselves after about 6 seconds; warnings and errors SHALL stay until closed or replaced. Switching view SHALL clear the bar. A removal message SHALL carry Undo.

#### Scenario: NMT command sent
- **WHEN** the user sends Start to node 2 in the online view
- **THEN** "Node 2: Start sent." is shown as a done bar and disappears after about 6 seconds without a page reload

#### Scenario: Leaving the view clears the message
- **WHEN** a message from the online view is shown and the user opens "Bus and master"
- **THEN** the message bar is hidden

#### Scenario: Errors stay until closed
- **WHEN** a save fails with an error
- **THEN** the error stays in the bar until the user closes it, saves again or switches view

#### Scenario: Error is announced
- **WHEN** a save fails
- **THEN** the bar has the alert role and a screen reader reads the message without the user moving focus

### Requirement: Simulation banner on one line
The simulation banner SHALL be a warning bar under the header, above the message bar, and SHALL stay in view while the page scrolls. It SHALL show one line per page: what is simulated, network by network, and that the configuration must not be uploaded to a machine as it is. Each network's part SHALL be short, for example "io (nodes 5, 6, 7)". A **Details** control SHALL open the full text. On a phone-width window it SHALL take at most two lines.

#### Scenario: Four simulated networks
- **WHEN** the virtual plant example is open at 1440 px
- **THEN** the banner is one line naming io (nodes 5, 6, 7), motion (node 4), cell and host and saying not to upload it, and Details opens the full text

#### Scenario: Stays in view
- **WHEN** the virtual plant example is open and the user scrolls a long node page down
- **THEN** the simulation banner stays under the header with the warning tint and icon

### Requirement: Connection bar
The connection bar SHALL be the one place on the page to connect and disconnect. It SHALL show under the header: always in Commission, and in Configure while connected and on the Trace and Simulation tool tabs. It SHALL show:
- the target;
- for an adapter, the bit rate and how it was confirmed;
- for a runtime, the path and round trip, and the network picker when the runtime has several networks;
- for a standalone simulator, its address;
- the bus state and the frame and error frame counts;
- another master with what was seen, when one is seen;
- whether changes are allowed;
- **Connect…** while not connected, and **Disconnect** while connected.

While connecting it SHALL show the step of the bit rate check and **Cancel**. When a connection ends or stops answering it SHALL show the reason or the age of the last data. The bar SHALL be neutral while all is well and take the tint of its most severe state, as the message bars do: error for an ended or lost connection, bus-off, another master or a round trip above 300 ms; warning for error passive or a round trip above 100 ms. State changes SHALL be announced politely, and an ended connection as an alert.

#### Scenario: Visible on every page
- **WHEN** the user is connected to an adapter at 500 kbit/s and opens Frame lab
- **THEN** the bar still shows the adapter, "500 kbit/s" with how it was confirmed, the bus state and Disconnect

#### Scenario: Ended connection
- **WHEN** the adapter goes bus-off while the user is on a node's Object dictionary tab
- **THEN** the bar turns to the error tint, says the connection ended on bus-off, offers Connect…, and a screen reader announces it

#### Scenario: Slow path is a warning
- **WHEN** the round trip to the runtime is 150 ms
- **THEN** the bar has the warning tint and icon, not the error tint

#### Scenario: Neutral when well
- **WHEN** the connection is up with no errors and no other master
- **THEN** the bar uses no warning or error colour

#### Scenario: One Connect button
- **WHEN** nothing is connected and the user opens Nodes, Simulation and Trace in turn, in either workspace of a config
- **THEN** each page shows exactly one Connect… button, the one in the connection bar, and each page's own text says what it needs a connection for
