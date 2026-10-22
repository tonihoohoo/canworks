## MODIFIED Requirements

### Requirement: Simulation banner on one line
While any part of the config is simulated, the page header SHALL show a simulation chip with the warning tint and icon, for example "Simulated: 4 networks". The chip SHALL stay in view while the page scrolls and SHALL take no row of its own. Its **Details** popover SHALL say what is simulated, network by network (for example "io (nodes 5, 6, 7)"), and that the configuration must not be uploaded to a machine as it is. The chip SHALL fit the header at every width; on a phone-width window it MAY shorten to "Simulated".

#### Scenario: Four simulated networks
- **WHEN** the virtual plant example is open at 1440 px
- **THEN** the header shows the chip "Simulated: 4 networks", and Details lists io (nodes 5, 6, 7), motion (node 4), cell and host and says not to upload it

#### Scenario: Stays in view
- **WHEN** the virtual plant example is open and the user scrolls a long node page down
- **THEN** the simulation chip stays in the header with the warning tint and icon

### Requirement: Narrow window layout
From 800 px to 1100 px wide, the network tree SHALL fold into a rail at the left of the workspace tab. The rail SHALL show each network's initials and its nodes' IDs with their state icons and error counts. Picking a node in the rail SHALL open it. The rail's button SHALL open the full tree over the page, and picking an entry SHALL close it. Under 800 px the tree SHALL fold into a button at the top of the workspace tab that names the selected entry and shows the config's error count, and opens the tree over the page. The bottom panel SHALL stay, with its tab title showing the problem count. A node's error count SHALL stay next to the node's name in the tree.

#### Scenario: Problems at 900 px
- **WHEN** the window is 900 px wide and the config has 4 errors
- **THEN** the bottom panel's tab reads "Problems 4" without scrolling, and opening it lists them

#### Scenario: Tree at 900 px
- **WHEN** the window is 900 px wide and the user picks node 7 in the rail
- **THEN** node 7's page opens beside the rail

#### Scenario: Tree at 700 px
- **WHEN** the window is 700 px wide and the user opens the tree button and picks node 7
- **THEN** the tree closes and node 7's page uses the full width

### Requirement: Workspaces
With a config open, the header SHALL have a **Configure | Commission** switch:
- **Configure** SHALL show the config pages.
- **Commission** SHALL show the live view of the runtime as its **Nodes** tab, with the network tree (see "Tree in Commission with a config") and the node pages of the online view.

Commission a device SHALL open in Commission and SHALL show no switch. Switching workspace SHALL keep the draft, the connection and every running job. The workspace SHALL be kept on this PC and SHALL come back after a page reload. A link to a page of the other workspace (a problem, "Back to the online view") SHALL switch to that workspace. The page SHALL NOT show a note about the former Online view.

#### Scenario: Switch while editing
- **WHEN** the user has an unsaved change in Configure and switches to Commission and back
- **THEN** the change is still in the draft, Save still reads "Save", and the connection is unchanged

#### Scenario: Reload keeps the workspace
- **WHEN** the user is in Commission and reloads the page
- **THEN** the page opens in Commission

#### Scenario: No switch without a config
- **WHEN** the user opens Commission a device
- **THEN** the header has no Configure | Commission switch

### Requirement: Bottom panel
The page SHALL have a collapsible panel under the page, with its height kept on this PC. Its contents SHALL depend on the workspace:
- **Configure:** a **Problems** tab, with Allow overlap. It SHALL open by itself when problems appear after a save or check.
- **Commission a device:** a **Log** tab with the session log and **Save log**.
- **Commission with a config:** a **Log** tab (selected by default) and a **Problems** tab; Problems SHALL open by itself when a comparison action causes a problem.

Each tab title SHALL carry its count. There SHALL be no right-hand Problems column. While Problems has nothing and no log entry is new, the panel SHALL be a one-line strip with the tab titles and counts. A Log that has entries SHALL start collapsed and show its count in the strip. The resize handle SHALL look like a handle (a grip mark on a thin line), not like a scrollbar.

#### Scenario: Problems under the page
- **WHEN** the config has 4 errors in Configure
- **THEN** the panel's tab reads "Problems 4", the page uses the full width beside the tree, and clicking a problem goes to its field

#### Scenario: Log while commissioning
- **WHEN** the user gave a device node ID 12 by LSS in Commission a device
- **THEN** the Log tab lists the change, the Changes filter reads 1, and Save log downloads the log

#### Scenario: Problem after adding a found device
- **WHEN** the user adds a found node 9 whose EDS has no TPDO the config can map, and the check reports a problem
- **THEN** the Problems tab opens with that problem and the user stays in Commission

#### Scenario: Nothing to show
- **WHEN** a config without problems is open in Configure
- **THEN** the bottom panel is one line reading "Problems: none"

### Requirement: Close and reopen the inspector
The Trace inspector SHALL have a close button (✕) in its own title bar, and Esc with the focus inside the inspector SHALL close it and return the focus to the selected row. A closed inspector SHALL leave a slim **Inspector** rail at its edge that opens it again. With no frame selected, the inspector SHALL start closed. Selecting a frame by click or Enter while it is closed SHALL open it. Moving through the list with the arrow keys SHALL NOT open it. From 1280 px to under 1440 px wide, an open inspector SHALL be a drawer over the right part of the list rather than a column beside it; narrower, it stays under the list. The open or closed state SHALL be kept on this PC once a frame has been selected.

#### Scenario: Close with Esc
- **WHEN** the user tabs into the inspector of a selected SYNC frame and presses Esc
- **THEN** the inspector closes, the rail shows, and the focus is on the SYNC row

#### Scenario: Reopen by selecting
- **WHEN** the inspector is closed and the user clicks a TPDO row
- **THEN** the inspector opens on that TPDO

#### Scenario: Arrow keys keep it closed
- **WHEN** the inspector is closed and the user moves down the Chronological list with the arrow keys
- **THEN** the inspector stays closed and the selection moves

#### Scenario: Whole columns before a selection
- **WHEN** the user starts a trace at 1366 px wide and has selected no frame
- **THEN** the inspector is a rail, and the Name and Decoded columns are not cut

## ADDED Requirements

### Requirement: Short window layout
When the window is 800 px high or less, the header and tab rows SHALL use compact spacing, and message bars SHALL use slim padding. A message bar SHALL never cover controls of the work area. The connection status SHALL sit at the right end of the sub-tab row in every window, and SHALL wrap to a second line only when that row is too narrow.

#### Scenario: Laptop at 150 %
- **WHEN** the window is 1280×720 with the virtual plant example in Commission, connected
- **THEN** the work area is at least 60 % of the window height

### Requirement: Header target action
The header SHALL hold the target's hand-off actions as one primary split button: Build into CODESYS project… with Download for CODESYS for CODESYS, Install on device… for the Modbus bridge. At 1280 px and wider the header SHALL be one row for every target. Under 1500 px, Reload from disk, Close, Settings and Quit SHALL be in one "⋯" menu.

#### Scenario: CODESYS at 1366 px
- **WHEN** a CODESYS config is open at 1366 px wide
- **THEN** the header is one row with one Build split button

### Requirement: Wide window sections
From 1800 px wide, the sections of a network's Bus page and of a node's Supervision tab SHALL lay out in two columns.

#### Scenario: Bus page at 2560 px
- **WHEN** the window is 2560 px wide and the user opens Bus and master
- **THEN** the sections are in two columns side by side

### Requirement: PDO table on a phone-width window
Under 640 px wide, each PDO entry SHALL be shown as a card with object and name, variable and location, and its PDO and Remove. The page itself SHALL NOT scroll sideways at any width. Only a table's own box MAY scroll sideways.

#### Scenario: Phone width
- **WHEN** the window is 375 px wide and the user opens node 5's PDOs tab
- **THEN** each entry is a card and the page has no sideways scroll

### Requirement: Work area share in the layout check
The browser layout check SHALL run at 1280×720 and 911×512 besides its other sizes. For the main views of both workspaces it SHALL check that the work area, the space between the fixed bars, is at least 55 % of the window height.

#### Scenario: A new bar
- **WHEN** a change adds another always-shown bar under the header
- **THEN** the layout check fails at 911×512 naming the view and the work area's share
