## ADDED Requirements

### Requirement: Network tree
In both workspaces of a config, the left column of the workspace tab SHALL be a network tree, and it SHALL be the only navigation there. The tree SHALL show every network of the config at once, each as an entry with its name and protocol (CANopen master, CANopen slave, J1939 or Plain CAN). Under a network it SHALL show the entries that network has:
- Bus and master (Bus and ECU on J1939, Bus on Plain CAN and on a slave network);
- its nodes, sorted by node ID, each named by node ID and name;
- the slave device on a slave network;
- **Add node…** on a CANopen master network in Configure, which opens the EDS file chooser for that network;
- PDO links and CAN messages, when the network has them today.

After the networks the tree SHALL show Online access (Configure), Gateway and Modbus bridge when the config has them, and **Add network…** (Configure). Each network entry SHALL have a menu with **Rename…**, **Role** (CANopen networks) and **Remove…**, keeping today's confirmations. Which networks are folded SHALL be kept on this PC and SHALL come back after a page reload; a folded network SHALL show the sum of its entries' problem counts, and SHALL unfold by itself when a problem link opens an entry in it. The unused EDS files note and the address scan line SHALL be shown under the tree. Renaming a node SHALL update its entry as the user types.

#### Scenario: Two networks at once
- **WHEN** a config has networks `io` with nodes 5 and 7 and `drives` with node 2
- **THEN** the tree shows `io` and `drives` with their nodes, and opening node 2 needs no network switch

#### Scenario: Add a node to the second network
- **WHEN** the user picks **Add node…** under `drives` and chooses an EDS file
- **THEN** the node is added to `drives`, its entry is selected, and its General tab opens with focus in the name field

#### Scenario: Remove a network from its menu
- **WHEN** the user opens the menu of network `drives`, which has 3 nodes, and picks **Remove…**
- **THEN** the page asks for confirmation naming `drives` and its 3 nodes, with Cancel as the default

### Requirement: Network tree keyboard
The tree SHALL follow the WAI-ARIA tree view pattern: one tab stop, Down and Up to the next and previous visible entry, Right to expand a network or move to its first child, Left to collapse a network or move to its parent, Home and End to the first and last entry, Enter or Space to open an entry, and type-ahead on the entry text. Shift+F10 on a network entry SHALL open its menu. The open entry SHALL be marked as selected. Focus SHALL stay on the same entry when the tree is redrawn. A name too long for the column SHALL be cut with an ellipsis and given whole in a tooltip and in the accessible name.

#### Scenario: Find a node by typing
- **WHEN** focus is in the tree and the user types `2`
- **THEN** focus moves to the first entry whose text starts with `2`, such as node 23, and Enter opens it

#### Scenario: Collapse with Left
- **WHEN** focus is on node 5 under `io` and the user presses Left twice
- **THEN** focus moves to `io` and then `io` collapses

### Requirement: Node tabs
A node page in Configure SHALL show its heading, Export DCF and Remove node above a tab list, and SHALL show one tab at a time:
- **General**: node ID, name, EDS and Simulated, and the EDS error when the EDS cannot be read;
- **PDOs** (see "PDOs tab");
- **SDOs** (see "SDOs tab");
- **Supervision**: heartbeat or guarding, status bit, state byte, NMT command, boot error byte, EMCY code, error register and EMCY COB-ID;
- **CiA 402**: the axis settings, shown only when the node's EDS has 0x6040 and 0x6041 or the node already has an axis;
- **Simulation**, shown only for a simulated node (see "Simulation tab of a node");
- **Notes** (see "Notes tab");
- **Advanced**.

The tabs SHALL follow the page's tab pattern. Opening another node SHALL keep the open tab when that node has it, and open General otherwise. The open tab SHALL come back after a page reload. A node just added from an EDS SHALL open on General with focus in its name. Objects SHALL be mapped from within the PDO they go into ("Add entry…" per PDO, listing that direction's mappable objects), with "Map all" kept for device-mapped PDOs.

#### Scenario: Compare heartbeats across nodes
- **WHEN** the user is on node 5's Supervision tab and opens node 7 in the tree
- **THEN** node 7's Supervision tab is shown

#### Scenario: No CiA 402 tab for an I/O module
- **WHEN** the user opens a node whose EDS has neither 0x6040 nor 0x6041 and that has no axis
- **THEN** the node has no CiA 402 tab

#### Scenario: Reload keeps the tab
- **WHEN** the user is on node 5's PDOs tab and reloads the page
- **THEN** node 5's PDOs tab is shown

#### Scenario: Add an entry from the PDO
- **WHEN** the user clicks "Add entry…" on TPDO 1 and picks 0x6150:1
- **THEN** 0x6150:1 is added to TPDO 1 with a suggested location, and the picker lists only input-direction objects

### Requirement: PDOs tab
The PDOs tab SHALL show the node's inputs (TPDOs) and outputs (RPDOs), side by side when the page is at least 1400 px wide and stacked, inputs first, when narrower. Each PDO SHALL show its title, its mapping table with "Add entry…", and one line summing up its communication settings (COB-ID, transmission type, event timer, timeout). **Settings** on that line SHALL open the communication settings for editing. They SHALL start closed and SHALL open by themselves when one of them has a problem; the user's own open or close SHALL be kept while the node stays open.

#### Scenario: Settings at a glance
- **WHEN** TPDO 1 of node 5 has COB-ID 0x185, transmission type 255, event timer 100 ms and a 500 ms timeout
- **THEN** its summary line reads "COB-ID 0x185 · on change · event 100 ms · timeout 500 ms" with the settings closed

#### Scenario: Problem opens the settings
- **WHEN** RPDO 2's COB-ID clashes with another node's
- **THEN** RPDO 2's settings are open with the COB-ID field marked

#### Scenario: Width at 1280 px
- **WHEN** the window is 1280 px wide and the user opens the PDOs tab of a node with 4 TPDOs and 4 RPDOs
- **THEN** the inputs are above the outputs and nothing scrolls sideways

### Requirement: SDOs tab
The SDOs tab SHALL show the startup SDO writes and the SDO variables as two tables, each with its heading, its count and its add action, both shown even when empty.

#### Scenario: Empty node
- **WHEN** the user opens the SDOs tab of a node with no startup writes and no SDO variables
- **THEN** both tables show with a count of 0 and their add actions

### Requirement: Simulation tab of a node
A simulated node (its `simulate`, or a node on a simulated network that is not switched off) SHALL have a Simulation tab that edits that node's part of the simulation file: its value sources, its faults at start and its default behaviour switch. It SHALL edit the same draft as the Simulation tool, so a change shows in both, and SHALL be saved with **Save to simulation file**. With several networks it SHALL edit the node's own network section.

#### Scenario: Source from the node
- **WHEN** the user gives node 5's 0x6401:1 a sine on its Simulation tab and saves to the simulation file
- **THEN** `simulation.json` has that source for node 5, and the Simulation tool shows it

### Requirement: Notes tab
The Notes tab SHALL list the objects of the node's EDS that have a note, built-in or the user's own, with the note's text, unit and value meanings, a search by index or name, a **Note** button opening the Note editor, and **Export merged notes**. When the node has no EDS or its notes cannot be edited, the tab SHALL be read-only and say why.

#### Scenario: Find a note
- **WHEN** the user types `6060` in the Notes tab's search of a drive
- **THEN** only 0x6060 is listed with its note, and **Note** opens its editor

### Requirement: Problem badges
Each tree entry and each node tab SHALL show its number of errors and of warnings, marked by shape and text as well as colour, with an accessible name such as "2 errors, 1 warning". A collapsed network SHALL show the sum of its entries' problems; an expanded network SHALL show only its own. A problem whose place cannot be matched to an entry SHALL be counted on its network, or on the node's Advanced tab when it names a node field no other tab holds (General when it names the node itself). Selecting a problem in the bottom panel SHALL select its entry, expand its network, open its tab and any closed part holding the field, and focus the field.

#### Scenario: Where the errors are
- **WHEN** node 5 on `io` has one error in TPDO 2 and one in its heartbeat, and `io` is collapsed
- **THEN** `io` shows 2 errors, and after expanding it node 5 shows 2 errors, its PDOs tab 1 and its Supervision tab 1

#### Scenario: Problem to field
- **WHEN** the user is on node 7's General tab and selects the problem "Node 5 rtd, TPDO 2, 0x6150:1: type UNSIGNED8 (8 bit) does not fit location %IW320 (16 bit)"
- **THEN** node 5's PDOs tab opens and the location field of 0x6150:1 in TPDO 2 has focus

#### Scenario: Badge after a fix
- **WHEN** the user corrects the only error of node 5
- **THEN** node 5's entry, its tab and its network show no error count

### Requirement: Tree in Commission with a config
In Commission with a config, the tree SHALL show the config's networks and their nodes, without the configuration-only entries (Bus and master, Add node…, PDO links, CAN messages, Online access, Gateway, Modbus bridge, Add network…) and without the network menu. A network entry SHALL open that network's node table with its bus state, and a node entry the node's live tabs. Picking an entry on another network SHALL move the connection bar's network picker to that network, and changing the picker SHALL select that network's entry. Each workspace SHALL keep its own selected entry.

#### Scenario: Open a live node
- **WHEN** the page is connected to a runtime running `io` and `drives` and the user opens node 2 under `drives` in Commission
- **THEN** node 2's live tabs open and the connection bar's picker shows `drives`

#### Scenario: Back to where the user was
- **WHEN** the user was on node 5's PDOs tab in Configure, opened node 2 in Commission, and switches back to Configure
- **THEN** node 5's PDOs tab is shown

## MODIFIED Requirements

### Requirement: Workspaces
With a config open, the header SHALL have a **Configure | Commission** switch:
- **Configure** SHALL show the config pages.
- **Commission** SHALL show the live view of the runtime as its **Nodes** tab, with the network tree (see "Tree in Commission with a config") and the node pages of the online view.

Commission a device SHALL open in Commission and SHALL show no switch. Switching workspace SHALL keep the draft, the connection and every running job. The workspace SHALL be kept on this PC and SHALL come back after a page reload. A link to a page of the other workspace (a problem, "Back to the online view") SHALL switch to that workspace. The first time a config opens with this version, the switch SHALL show a note that the Online view is now the Commission workspace, until the user closes it or switches workspace; it SHALL NOT show again on this PC.

#### Scenario: Switch while editing
- **WHEN** the user has an unsaved change in Configure and switches to Commission and back
- **THEN** the change is still in the draft, Save still reads "Save", and the connection is unchanged

#### Scenario: Reload keeps the workspace
- **WHEN** the user is in Commission and reloads the page
- **THEN** the page opens in Commission

#### Scenario: No switch without a config
- **WHEN** the user opens Commission a device
- **THEN** the header has no Configure | Commission switch

### Requirement: Tool tabs
Next to the workspace's own tab (**Network** in Configure, **Nodes** in Commission), the header SHALL have tool tabs:
- **Variable declarations** in Configure;
- **Simulation** in both workspaces of a config;
- **Trace** and **Frame lab** in every workspace.

A tool tab SHALL use the full page width, with no network tree, side bar or bottom panel. The network tree SHALL list no tools. The tabs SHALL follow the page's tab pattern (see "Keyboard access and announcements").

#### Scenario: Trace from a node page
- **WHEN** the user is on node 5's PDOs tab in Configure and picks the Trace tab
- **THEN** the trace view fills the width of the page, and picking Network returns to node 5's PDOs tab

#### Scenario: Tools in Commission a device
- **WHEN** the user opens Commission a device
- **THEN** the tabs are Nodes, Trace and Frame lab

### Requirement: Keyboard access and announcements
Everything the pointer can do on the page SHALL be possible with the keyboard.
- **Lists:** the network tree SHALL be reachable with one tab stop and work as in "Network tree keyboard", with the open entry marked as selected. The problem list SHALL be made of buttons in the tab order. Rows that open something (online nodes, scanned devices, simulated devices) SHALL be focusable and open on Enter or Space.
- **Tabs:** tabs (the node tabs, Trace, the online node's Overview / Object dictionary / Parameters, Simulation) SHALL be a tab list with the selected tab marked and each tab naming its panel. Left, Right, Home and End SHALL move between them.
- **Focus:** every focused control SHALL show a visible focus ring in the accent colour.
- **Announcements:** progress lines (reading all, backup, scan) and the problem count SHALL be polite live regions, and the tree's and tabs' badges SHALL carry their counts in their accessible names.
- **Structure:** landmarks SHALL not be nested complementary regions, heading levels SHALL not skip, and every table column with only buttons SHALL have a header text for assistive technology.

#### Scenario: Open a node with the keyboard
- **WHEN** the user tabs into the network tree, presses Down until "5 rtd" and presses Enter
- **THEN** node 5's page opens on its last used tab

#### Scenario: Problems by keyboard
- **WHEN** the user tabs into the Problems panel and presses Enter on the first problem
- **THEN** the field with that problem gets focus, on the tab that holds it

#### Scenario: Tabs by keyboard
- **WHEN** focus is on the Trace view's "By identifier" tab and the user presses Right
- **THEN** "Chronological" is selected and its panel shows

#### Scenario: Node tabs by keyboard
- **WHEN** focus is on node 5's "General" tab and the user presses Right
- **THEN** "PDOs" is selected and its panel shows

### Requirement: Narrow window layout
At 1100 px wide and narrower (the page's existing narrow breakpoint) the network tree SHALL fold into a button at the top of the workspace tab that names the selected entry and shows the config's error count, and opens the tree over the page; picking an entry SHALL close it. The bottom panel SHALL stay, with its tab title showing the problem count, so the problems stay in view without a separate strip. A node's error count SHALL stay next to the node's name in the tree.

#### Scenario: Problems at 900 px
- **WHEN** the window is 900 px wide and the config has 4 errors
- **THEN** the bottom panel's tab reads "Problems 4" without scrolling, and opening it lists them

#### Scenario: Tree at 900 px
- **WHEN** the window is 900 px wide and the user opens the tree button and picks node 7
- **THEN** the tree closes and node 7's page uses the full width

### Requirement: Choose what is simulated
The **Bus and master** page SHALL have a **Network** choice, **Real** or **Simulated** (`adapter.simulate`), and each node SHALL have a **Simulated** switch (the node's `simulate`) on its General tab, with **Simulate all** and **Simulate none** buttons on Bus and master. In the network tree a simulated node SHALL have a hollow mark and "(simulated)" in its accessible name, and on a simulated network a node switched off SHALL be drawn dashed and named absent. Choosing a simulated network SHALL keep the adapter settings. Simulating anything SHALL turn on online access with **Allow changes** when it is off (saying so), and every page SHALL show a banner naming what is simulated (the network, or the simulated node IDs on the real network) and that the configuration must not be uploaded to a machine as it is.

#### Scenario: Simulated network
- **WHEN** a user chooses **Simulated** network in a project with online access off
- **THEN** the saved config has `adapter.simulate: true`, its adapter settings unchanged, online access on with **Allow changes**, every node of that network has the hollow mark in the tree, and every page shows the banner

#### Scenario: One device on the real network
- **WHEN** a user keeps the **Real** network and switches on **Simulated** for node 5 only
- **THEN** the saved config has `"simulate": true` on node 5 only, node 5 alone has the hollow mark, and the banner says node 5 is simulated on the real network

#### Scenario: Absent node
- **WHEN** the network is simulated and the user switches **Simulated** off for node 7
- **THEN** node 7's entry is drawn dashed and its accessible name says it is absent

### Requirement: Readable problem messages
The Problems panel and the messages next to fields SHALL name the place of a problem in the user's terms (node ID and name, PDO kind and number, object index and subindex, SDO variable name) and SHALL NOT show the internal config path (such as `nodes[2]: tx_pdos[1]: entries[0]:`). Selecting a problem SHALL still move to and highlight its field, opening its tree entry and tab first. The same wording SHALL be used wherever the configurator shows a check message: the Trace view's and Frame lab's "decoding without the config's PDOs" notes, the message bar and dialogs. No message shown on the page SHALL contain a filesystem path of the config or project, except where the path itself is the subject (the folder browser, the mode badge, the new-project dialog). An empty config SHALL be reported as "No nodes yet. Add a node from its EDS, or turn on Online access for a scan-only configuration." rather than as a schema error. An unexpected server error SHALL be shown as one sentence that points at the configurator's terminal, where the details are logged. The deploy tool's command-line messages are unchanged.

#### Scenario: Type does not fit the location
- **WHEN** node 5 (rtd) maps UNSIGNED8 object 0x6150:1 in TPDO 2 to `%IW320`
- **THEN** the Problems panel shows "Node 5 rtd, TPDO 2, 0x6150:1: type UNSIGNED8 (8 bit) does not fit location %IW320 (16 bit)" and clicking it opens node 5's PDOs tab with that entry's location field focused

#### Scenario: Trace note without a path
- **WHEN** the config has a type-does-not-fit error and the user opens a trace file
- **THEN** the Trace view's note reads "Decoding without the config's PDOs: Node 5 rtd, TPDO 2, 0x6150:1: type UNSIGNED8 (8 bit) does not fit location %IW320 (16 bit)" with no file path

#### Scenario: New config
- **WHEN** the user creates a new standalone config
- **THEN** the only problem reads "No nodes yet. Add a node from its EDS, or turn on Online access for a scan-only configuration."

### Requirement: Export DCF files
Each node's page SHALL have an "Export DCF" action next to "Remove node", above its tabs, and the header's Export menu SHALL offer "All DCFs" and, while a node page is open, "This node's DCF". The node's tree entry SHALL carry no action of its own: clicking anywhere on it opens the node and nothing else. Both SHALL run the `canopen-dcf-export` export on the config as currently shown on the page, saved or not, and offer the result as a browser download: `node_<id>.dcf` for one node, `<config folder name>_dcf.zip` holding every `node_<id>.dcf` for all. When the config has errors or a DCF fails validation, the configurator SHALL download nothing and SHALL show the messages in the Problems panel, replacing the panel's current list rather than adding to it, so the problem count stays the number of distinct problems. The actions SHALL NOT write any file in the project or config folder.

#### Scenario: Export one node
- **WHEN** the config is valid and the user clicks "Export DCF" on node 23's page
- **THEN** the browser downloads `node_23.dcf` and no file under the project changes

#### Scenario: Unsaved change is exported
- **WHEN** the user changes node 23's heartbeat to 200 ms without saving and exports it
- **THEN** the downloaded DCF has `ParameterValue` 200 on 0x1017

#### Scenario: Validation failure
- **WHEN** a DCF fails validation
- **THEN** nothing is downloaded and the Problems panel names the node, the DCF section and the key

#### Scenario: Clicking a node item never exports
- **WHEN** the user clicks the middle of "5 rtd" in the network tree, with the pointer resting on it
- **THEN** node 5's page opens, no download starts and the Problems panel is unchanged

#### Scenario: Failed export keeps the count
- **WHEN** the config has 4 errors and the user runs "All DCFs" from the Export menu
- **THEN** nothing is downloaded and the Problems panel still lists 4 problems, not 8

### Requirement: Network role switch
Each CANopen network SHALL have a role, master or slave, set from **Role** on its bus page or from the role item of its network menu in the tree. Switching a network with nodes to slave SHALL ask before dropping the master settings and nodes; switching back SHALL start with an empty master network.

#### Scenario: Switch to slave
- **WHEN** the user sets a new network's role to slave
- **THEN** the network's tree entries become Bus and the slave device, and Bus shows the adapter settings

### Requirement: Online access settings
The tree SHALL have an **Online access** entry, once for the whole config, that turns `master.diagnostics` on and off and edits its port, bind address and "allow changes" (off by default, with a warning that anyone with the token can then write parameters and stop nodes). Turning it on SHALL generate a random token of at least 128 bits, write only its SCRAM-SHA-256 verifier to `token_verifier`, and keep the token in the configurator's own settings on this PC for this project, never in the project folder. The page SHALL let the user copy the token, enter an existing token (for a project set up on another PC, checked against `token_verifier`), and generate a new one. When a project's config still has the former `token_sha256`, the page SHALL say that the token must be set again for the encrypted channel and, when this PC holds the matching token, offer **Upgrade**, which replaces `token_sha256` with a `token_verifier` for the same token; otherwise **New token** or **Enter token…** replaces it. The runtime host for online access SHALL be stored with the token and default to the host last used by the deploy tool when known.

#### Scenario: Enable online access
- **WHEN** the user opens Online access in the tree, turns it on in a project and saves
- **THEN** `canworks.json` has `master.diagnostics` with `token_verifier` and neither the token nor `token_sha256`, and the configurator's settings hold the token for this project

#### Scenario: Token from another PC
- **WHEN** the project already has `token_verifier` and this PC has no token for it
- **THEN** the connect panel asks for the token and accepts it only if it matches the verifier

#### Scenario: Upgrade an old project
- **WHEN** the project has `token_sha256`, this PC holds its token, and the user presses **Upgrade** and saves
- **THEN** `canworks.json` has a `token_verifier` for the same token and no `token_sha256`, and the copied token still works after the next upload

### Requirement: Allow changes in the connection bar
On an adapter connection, **Allow changes** SHALL be a switch in the connection bar. It SHALL be off for every new connection, SHALL ask before switching on, and SHALL apply to the open connection without reconnecting. On a runtime connection, the bar SHALL show the runtime's own setting as read-only text with a lock and SHALL say that it is set in Configure → Online access and takes effect after an upload, with a link that opens that entry.

#### Scenario: Switch on an open adapter connection
- **WHEN** the user is connected read-only to an adapter and switches Allow changes on and confirms
- **THEN** write controls on every page are enabled without reconnecting, and no "another master" message appears

#### Scenario: Runtime decides
- **WHEN** the user is connected to a runtime whose config has allow changes off
- **THEN** the bar shows "Read-only (runtime setting)" with no switch, and its link opens Online access in Configure

### Requirement: Network picker in online and trace views
When the runtime reports more than one network, the connection bar SHALL have a network picker. The Commission pages, Trace and Simulation SHALL show and act on the picked network only. The picker SHALL start on the network of the entry selected in Configure's tree. In Commission, picking a tree entry on another network SHALL move the picker, and changing the picker SHALL select that network's tree entry.

#### Scenario: Online view of the second network
- **WHEN** the runtime runs `io` and `drives` and the user picks `drives` in the connection bar
- **THEN** the Commission workspace shows `drives`' bus state and nodes, the tree selects `drives`, and SDO, NMT, parameter and object dictionary actions go to `drives`

## REMOVED Requirements

### Requirement: Network bar
**Reason**: The network tree shows every network at once, so the bar of network tabs above the side bar goes away.
**Migration**: Networks are entries of the network tree; add one with **Add network…** at the end of the tree, and rename, change role or remove one from its entry's menu (see "Network tree"). With one network the tree shows its entry, expanded.

### Requirement: Node page sections
**Reason**: The node page becomes tabs, so the section index over one long page goes away.
**Migration**: Each former section is on a node tab (see "Node tabs"): Node on General; Supervision and Emergency on Supervision; Axis on CiA 402; Inputs and Outputs on PDOs; Startup SDO writes and SDO variables on SDOs; Advanced on Advanced. "Add entry…" per PDO and "Map all" are unchanged.
