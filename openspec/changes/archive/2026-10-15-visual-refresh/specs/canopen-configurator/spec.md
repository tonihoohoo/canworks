## ADDED Requirements

### Requirement: State colours
The page SHALL use one set of state colours in both themes, and only states SHALL use them:
- **OK**: as intended (OPERATIONAL, rate confirmed);
- **in progress**: waiting or working (PRE-OPERATIONAL, a job);
- **warning**: needs a look (STOPPED, a warning, error passive);
- **error**: broken (an error, missing node, bus-off);
- **off**, a grey: no information (unknown, absent).

"Simulated" is not a state.

#### Scenario: Simulated is not a warning
- **WHEN** a config has a simulated node and no problems
- **THEN** no element on the page uses the warning colour

#### Scenario: Missing node
- **WHEN** a node goes missing
- **THEN** its state is shown in the error colour

### Requirement: Grey is normal
Text in tables and lists SHALL stay in the normal text colour whatever the state; the state SHALL show as its icon and word. Only the warning and error states SHALL tint a row or banner background. The accent colour SHALL be used only for focus, links, the primary button and the selected tab.

#### Scenario: Healthy network is calm
- **WHEN** every node of a network is OPERATIONAL with no problems
- **THEN** the tree and the Nodes table show neutral text with an OK icon per node, and no row or banner is tinted

#### Scenario: A fault stands out
- **WHEN** one node of five goes missing
- **THEN** only that node's icon and row use the error colour

### Requirement: State colour contrast
Each state colour SHALL reach 4.5:1 as text and 3:1 as an icon against the page and panel backgrounds and against its own tint, in both themes. A test that needs no browser SHALL compute these ratios from the style sheet. The frame inspector's field tints and the graph's series colours are not state colours.

#### Scenario: Token edit caught without a browser
- **WHEN** a change lightens the Dark theme's warning colour below 4.5:1 against the panel
- **THEN** the contrast test fails naming the token and the theme

### Requirement: State icons
Every state SHALL show an icon whose shape tells the state:
- operational: filled circle;
- pre-operational: half-filled circle;
- initialising, connecting or a job running: ring with a gap;
- stopped: filled square;
- warning: triangle with "!";
- error, missing, bus-off or ended: circle with a cross;
- unknown, absent or not connected: hollow circle.

The tree, Nodes table, node tabs, connection bar, status bar, problems, message bar and trace SHALL use these icons.

#### Scenario: Stopped and warning differ
- **WHEN** node 5 is STOPPED and node 9 has a warning problem
- **THEN** node 5 shows a square and node 9 a triangle, though both use the warning colour

#### Scenario: Pre-operational node on the tree
- **WHEN** node 7 is PRE-OPERATIONAL
- **THEN** its tree entry shows the half-filled circle

### Requirement: Diagnosis flag and simulated mark
A pending diagnosis (an EMCY or error problem not yet cleared) SHALL add a flag in the error colour after a node's state icon; once cleared the flag SHALL turn grey and stay until the history is cleared. A simulated node SHALL add a dashed outline to its state icon.

#### Scenario: Cleared diagnosis
- **WHEN** node 5 sent an EMCY that is later cleared
- **THEN** its flag turns from the error colour to grey

#### Scenario: Simulated node
- **WHEN** node 9 is simulated and OPERATIONAL
- **THEN** its icon is the filled circle with a dashed outline

### Requirement: State icons for every user
An icon shown without its state word SHALL have the word as its accessible name and tooltip. An icon next to its state word SHALL be hidden from assistive technology. In forced-colours (high contrast) mode the icons SHALL keep their shapes and inner marks. A turning animation SHALL show only when the user has not asked for reduced motion.

#### Scenario: Screen reader on the tree
- **WHEN** a screen reader reaches node 7, which is PRE-OPERATIONAL and simulated
- **THEN** it reads "Pre-operational, simulated" for the icon

#### Scenario: High contrast
- **WHEN** the page is shown in forced-colours mode
- **THEN** every state icon on the tree is visible with its shape

### Requirement: Colours and icons legend
The settings menu SHALL offer **Colours and icons**, showing every state icon, the diagnosis flag and the simulated mark with its word and one line on when it shows, drawn from the same definitions as the page's icons. It SHALL close on Escape and return focus to the menu.

#### Scenario: Open the legend
- **WHEN** the user opens the settings menu and picks Colours and icons
- **THEN** a legend lists the seven state icons, the diagnosis flag and the simulated outline, each with its word

### Requirement: Compact data tables
Data tables SHALL use rows of 28 px, or 32 px for rows that hold a field or button, and SHALL keep their header row in view while they scroll. Controls SHALL stay at least 24 px tall. Data tables are the Nodes table, PDO entries, startup SDO writes, SDO variables, object dictionary, watch list, trace, transmit list, PDO links, gateway routes, register map, CAN messages, J1939 signals, scan result and EMCY history.

#### Scenario: Header stays in view
- **WHEN** the user scrolls the object dictionary of a node with 300 entries
- **THEN** the column headers stay at the top of the table

#### Scenario: Row height
- **WHEN** the scan result lists 20 nodes
- **THEN** each row is at most 32 px tall

### Requirement: IDs and numbers in tables
Number columns SHALL be right-aligned with digits of even width. COB-IDs, CAN IDs, object indexes and subindexes, data bytes, hex values and PLC locations SHALL be shown in a fixed-width font. Hex values SHALL be written with `0x` and upper-case digits (`0x6150:1`, `0x1A5`); node IDs SHALL be decimal.

#### Scenario: Scan down a column of COB-IDs
- **WHEN** the trace's By identifier view lists 0x181, 0x1A5 and 0x705
- **THEN** the identifiers are in a fixed-width font and their counts are right-aligned

### Requirement: Word list for the page
Labels, headings, buttons, tooltips, empty states and messages SHALL follow `docs/wording.md`: one term per concept, sentence case, buttons that start with a verb (with "…" when they open a dialog), units after a space, no "Error:" or "Warning:" prefix, no exclamation marks, and messages that say what happened and what to do. Text from an EDS, a DBC or the config is data and is shown unchanged.

#### Scenario: One term
- **WHEN** the page shows the bit rate in the connect panel, the connection bar and the scan
- **THEN** each says "bit rate" and none says "baud" or "bitrate"

#### Scenario: Message says what to do
- **WHEN** a save fails because the folder is read-only
- **THEN** the message says the folder cannot be written and how to fix it, without an "Error:" prefix

### Requirement: Empty states say what to do
An empty list, table or panel SHALL say what it is for and offer the action that fills it, instead of showing nothing or only "None".

#### Scenario: No startup SDO writes
- **WHEN** a node has no startup SDO writes
- **THEN** the section says what startup SDO writes do and offers "Add write…"

### Requirement: Word list test
A test that needs no browser SHALL fail on a term the word list rules out, in the page's files or in the server's user-facing messages, naming the file, the line and the preferred term.

#### Scenario: Ruled-out term caught
- **WHEN** a change adds a button labelled "Set baudrate"
- **THEN** the word-list test fails naming the file, the line and "bit rate"

### Requirement: Disabled controls say why
Every disabled control SHALL carry the reason it is disabled as its tooltip and accessible description, such as "Needs a connection with changes allowed". A control disabled while its own action runs SHALL say what is running ("Saving…"). The browser layout test SHALL fail on a disabled control without a reason, naming the view and the control.

#### Scenario: Write without changes allowed
- **WHEN** the user is connected through an adapter with Allow changes off and looks at the object dictionary's Write button
- **THEN** the button is disabled and its tooltip reads "Needs a connection with changes allowed"

#### Scenario: Missing reason caught
- **WHEN** a change disables a button without a reason
- **THEN** the layout test fails naming the view and the button

### Requirement: Keyboard-only task tests
The browser tests SHALL do five user tasks with the keyboard alone, in the Light and the Dark theme: connect to a virtual USB adapter, scan the bus, add a found node to a config, map a PDO entry and save, and record and save a trace. They SHALL use the virtual adapter, the fake plugin runtime and the local simulator runtime, with no hardware, and SHALL fail if a step uses the pointer.

#### Scenario: Record a trace by keyboard in Dark
- **WHEN** the trace task runs in the Dark theme
- **THEN** it opens the Trace tab, starts and stops a recording and saves it with key presses only

#### Scenario: Pointer step caught
- **WHEN** a task test step clicks a button
- **THEN** the test fails saying the step used the pointer

### Requirement: Checks in each task step
After each step of a keyboard-only task test, the test SHALL run the accessibility audit, check that the focused control shows a visible focus ring, and check that no text in the view is clipped. A failed task SHALL leave a screenshot of each step with the test run.

#### Scenario: Focus lost
- **WHEN** a step leaves focus on the page body after a dialog closes
- **THEN** the task test fails at that step and keeps the step screenshots

### Requirement: High contrast check
The browser layout test SHALL open the network tree and the Nodes table once in forced-colours mode and SHALL fail if a state icon is not painted or has no accessible name.

#### Scenario: Icons in forced colours
- **WHEN** the layout test opens the network tree in forced-colours mode
- **THEN** each node's state icon is painted and has its state word as accessible name

## MODIFIED Requirements

### Requirement: Accessibility check in the browser tests
The browser layout test SHALL run an automated accessibility audit (WCAG 2.1 A and AA rules) on every view it opens, in both themes, and SHALL fail on any finding of critical or serious impact, naming the rule, the element and the view. Text SHALL meet the 4.5:1 contrast ratio (3:1 for large text) in both themes, including state colours and the frame inspector's field tints, state icons SHALL meet 3:1, and interactive controls SHALL be at least 24 px tall.

#### Scenario: Regression caught
- **WHEN** a change adds a button without an accessible name to the online view
- **THEN** the layout test fails naming the rule and the button

#### Scenario: State colours
- **WHEN** the online view shows a node as OPERATIONAL in the light theme
- **THEN** the state text's contrast against its background is at least 4.5:1

#### Scenario: State icons
- **WHEN** the tree shows a PRE-OPERATIONAL node in the dark theme
- **THEN** its icon's contrast against the tree background is at least 3:1
