## ADDED Requirements

### Requirement: Keyboard access and announcements
Everything the pointer can do on the page SHALL be possible with the keyboard: the node list and the problem list SHALL be made of buttons in the tab order, the active node marked as current; rows that open something (online nodes, scanned devices, simulated devices) SHALL be focusable and open on Enter or Space; tabs (Trace, the online node's Overview / Object dictionary / Parameters, Simulation) SHALL be a tab list with the selected tab marked, each tab naming its panel, and Left, Right, Home and End moving between them; every focused control SHALL show a visible focus ring in the accent colour. Progress lines (reading all, backup, scan) and the problem count SHALL be polite live regions. Landmarks SHALL not be nested complementary regions, heading levels SHALL not skip, and every table column with only buttons SHALL have a header text for assistive technology.

#### Scenario: Open a node with the keyboard
- **WHEN** the user presses Tab from the Save button
- **THEN** focus moves through the node list, and Enter on "5 rtd" opens node 5's page

#### Scenario: Problems by keyboard
- **WHEN** the user tabs into the Problems pane and presses Enter on the first problem
- **THEN** the field with that problem gets focus

#### Scenario: Tabs by keyboard
- **WHEN** focus is on the Trace view's "Frames" tab and the user presses Right
- **THEN** "Identifiers" is selected and its panel shows

### Requirement: Confirmation dialogs default to the safe choice
In every confirmation dialog the safe choice (Cancel, or keep) SHALL be the default and SHALL receive focus when the dialog opens, so Enter never removes, discards, overwrites, resets or stores anything; the destructive choice SHALL be styled as destructive and SHALL NOT be the first button; Escape SHALL cancel. Dialogs that collect input (new project, restore) SHALL focus their first field, with the action button last.

#### Scenario: Enter keeps the node
- **WHEN** the user clicks "Remove node" and presses Enter
- **THEN** the dialog closes and the node is still there

#### Scenario: Close without saving
- **WHEN** the user clicks Close with unsaved changes
- **THEN** the dialog offers Cancel (focused) and "Close without saving", and only the latter discards the draft

### Requirement: Undo
Edits of the draft SHALL be undoable with Ctrl+Z (Cmd+Z on macOS) and redoable with Ctrl+Shift+Z, as whole steps (one typed value, one removal, one added entry), across views, until the draft is reloaded from disk or the folder is closed. Removing a PDO entry, startup SDO write, SDO variable, slave object, descriptor object or gateway route SHALL show a message naming what was removed with an Undo action that restores it with every setting it had. Online, trace and simulation actions are not part of the undo history.

#### Scenario: Undo a removed entry
- **WHEN** the user removes 0x6150:1 from TPDO 2, which had location %IW320 and a 500 ms timeout, and clicks Undo in the message bar
- **THEN** the entry is back in TPDO 2 with %IW320 and the 500 ms timeout

#### Scenario: Undo typing
- **WHEN** the user changes a heartbeat period from 100 to 250, clicks elsewhere and presses Ctrl+Z
- **THEN** the field shows 100 again and the Save button reads as dirty only if other edits remain

### Requirement: Header menus
The header SHALL show, left to right: the title and mode badge, the theme choice, Reload from disk, Close, a Project menu (Move into project…, New editor project…; standalone mode only), an Export menu (All DCFs, This node's DCF, DBC with its SDO-frames choice, Documentation) and Save as the only primary button. Menus SHALL open on click or Enter, close on Escape or a click elsewhere, and SHALL be navigable with the arrow keys. The header SHALL fit on one line at 1000 px.

#### Scenario: Export a DBC from the menu
- **WHEN** the user opens Export, picks "SDO: configured objects" and clicks DBC
- **THEN** the DBC file downloads as before and the menu closes

#### Scenario: One line
- **WHEN** the window is 1000 px wide in standalone mode
- **THEN** the header's actions are on one line

### Requirement: Node page sections
A node page SHALL have a section index under its heading that stays in view while the page scrolls, with an entry per section (Node, Supervision, Emergency, Axis, Advanced, Inputs, Outputs, Startup SDO writes, SDO variables), the current section marked as the page scrolls and each entry scrolling to its section. Sections that can be empty (Startup SDO writes, SDO variables) SHALL be collapsed when empty, with their count and their add action visible in the summary, and open when they have entries or a problem. Objects SHALL be mapped from within the PDO block they go into ("Add entry…" per PDO, listing that direction's mappable objects), with "Map all" kept for device-mapped PDOs. Editing the node's name SHALL update the side bar as the user types, and adding a node SHALL put focus in its name field.

#### Scenario: Jump to SDO variables
- **WHEN** the user clicks "SDO variables" in the section index of a node with two PDOs
- **THEN** the page scrolls to that section and the index marks it

#### Scenario: Add an entry from the PDO
- **WHEN** the user clicks "Add entry…" on TPDO 1 and picks 0x6150:1
- **THEN** 0x6150:1 is added to TPDO 1 with a suggested location, and the picker lists only input-direction objects

### Requirement: Busy states and the Save button
Save, every export, Move into project, New editor project and Add node from EDS SHALL disable their control and show what is running ("Saving…", "Exporting…", "Adding…") until the request completes, and a second click meanwhile SHALL do nothing. The Save button SHALL read "Saved" and be disabled when the draft equals the file, "Save" when the draft is dirty, "Save (overlaps allowed)" when the overlap override is on; when the draft has errors it SHALL be disabled with a tooltip giving the error count, and the count SHALL be shown in the Problems pane rather than in the button's label.

#### Scenario: Double click on Save
- **WHEN** the user clicks Save twice while the first save is still running
- **THEN** one save request is made and the button reads "Saving…" until it returns

#### Scenario: Clean draft
- **WHEN** the file on disk equals the draft
- **THEN** the button reads "Saved" and is disabled

### Requirement: Accessibility check in the browser tests
The browser layout test SHALL run an automated accessibility audit (WCAG 2.1 A and AA rules) on every view it opens, in both themes, and SHALL fail on any finding of critical or serious impact, naming the rule, the element and the view. Text SHALL meet the 4.5:1 contrast ratio (3:1 for large text) in both themes, including state colours and the frame inspector's field tints, and interactive controls SHALL be at least 24 px tall.

#### Scenario: Regression caught
- **WHEN** a change adds a button without an accessible name to the online view
- **THEN** the layout test fails naming the rule and the button

#### Scenario: State colours
- **WHEN** the online view shows a node as OPERATIONAL in the light theme
- **THEN** the state text's contrast against its background is at least 4.5:1

## MODIFIED Requirements

### Requirement: Export DCF files
Each node's page SHALL have an "Export DCF" action next to "Remove node", and the header's Export menu SHALL offer "All DCFs" and, while a node page is open, "This node's DCF". The node list item SHALL carry no action of its own: clicking anywhere on it opens the node and nothing else. Both SHALL run the `canopen-dcf-export` export on the config as currently shown on the page, saved or not, and offer the result as a browser download: `node_<id>.dcf` for one node, `<config folder name>_dcf.zip` holding every `node_<id>.dcf` for all. When the config has errors or a DCF fails validation, the configurator SHALL download nothing and SHALL show the messages in the Problems pane, replacing the pane's current list rather than adding to it, so the problem count stays the number of distinct problems. The actions SHALL NOT write any file in the project or config folder.

#### Scenario: Export one node
- **WHEN** the config is valid and the user clicks "Export DCF" on node 23's page
- **THEN** the browser downloads `node_23.dcf` and no file under the project changes

#### Scenario: Unsaved change is exported
- **WHEN** the user changes node 23's heartbeat to 200 ms without saving and exports it
- **THEN** the downloaded DCF has `ParameterValue` 200 on 0x1017

#### Scenario: Validation failure
- **WHEN** a DCF fails validation
- **THEN** nothing is downloaded and the Problems pane names the node, the DCF section and the key

#### Scenario: Clicking a node item never exports
- **WHEN** the user clicks the middle of "5 rtd" in the node list, with the pointer resting on it
- **THEN** node 5's page opens, no download starts and the Problems pane is unchanged

#### Scenario: Failed export keeps the count
- **WHEN** the config has 4 errors and the user runs "All DCFs" from the Export menu
- **THEN** nothing is downloaded and the Problems pane still lists 4 problems, not 8

### Requirement: Scan the bus and add nodes
The configurator SHALL offer a scan page that runs a network scan through the runtime, shows progress, and lists each found device with node ID, vendor ID (with the vendor name when the EDS gives it), product code, revision, serial number, device name and its match against the config. For each device the page SHALL look for EDS files whose `[DeviceInfo]` VendorNumber and ProductNumber match, in the project's `canopen/` folder and in an optional EDS library folder set in the configurator's settings, preferring an exact RevisionNumber match. A not-configured device with a matching EDS SHALL be addable as a node with that node ID and EDS (imported into `canopen/` as an EDS import would), with an option to also set its identity check from the scanned values; a device without a matching EDS SHALL offer to pick an EDS file. Adding a node from the scan page SHALL open the new node's page with its name field focused, as "Add node from EDS…" does, and the message bar SHALL offer a way back to the scan results, which SHALL be kept. A "configured, different device" result SHALL show the differing fields side by side. Added nodes SHALL be saved only when the user saves.

#### Scenario: Add a found sensor
- **WHEN** the scan finds node 40 (vendor 0x000000AB, product 0x00001234) not configured, and the EDS library folder has an EDS with those numbers
- **THEN** the page offers that EDS, and adding it creates node 40 with that EDS, no PDO entries yet, and the project unchanged until save

#### Scenario: Unknown device
- **WHEN** the scan finds a device whose vendor and product match no EDS
- **THEN** the page shows its identity and offers to pick an EDS file

#### Scenario: Added node opens
- **WHEN** the user picks an EDS file for the unknown device at node 41
- **THEN** node 41's page opens with the name field focused, and the message bar says the node was added with a link back to the scan, whose results are still listed

### Requirement: Manual SDO and NMT in the online view
For each node the online view SHALL offer an SDO panel: pick an object from the node's EDS (all objects, not only mappable ones) or type index and subindex, read it, and show the value decoded with the EDS data type (numbers in decimal and hex, VISIBLE_STRING as text, other types as hex bytes), or the abort code with its CiA 301 text. When the runtime allows changes, the panel SHALL also write a value encoded from the EDS type after a range check, warning before writing an object the plugin configures itself or one owned by an SDO variable; and the node SHALL have NMT buttons (start, stop, pre-operational, reset node, reset communication), with confirmation for stop, pre-operational and the resets, since each of those holds or interrupts the node. When the runtime does not allow changes, write and NMT controls SHALL be shown disabled with the reason.

#### Scenario: Read the serial number
- **WHEN** the user reads 0x1018 subindex 4 of node 3
- **THEN** the panel shows the serial number in decimal and hex

#### Scenario: Write blocked
- **WHEN** the runtime's `allow_changes` is false
- **THEN** the write button and NMT buttons are disabled and say that online changes are not allowed in this configuration

#### Scenario: Pre-operational asks first
- **WHEN** the user clicks Pre-operational for node 2
- **THEN** a dialog says the node's PDOs stop until it is started again, with Cancel as the default, and nothing is sent until the user confirms

### Requirement: Readable problem messages
The Problems pane and the messages next to fields SHALL name the place of a problem in the user's terms (node ID and name, PDO kind and number, object index and subindex, SDO variable name) and SHALL NOT show the internal config path (such as `nodes[2]: tx_pdos[1]: entries[0]:`). Selecting a problem SHALL still move to and highlight its field. The same wording SHALL be used wherever the configurator shows a check message: the Trace view's and Frame lab's "decoding without the config's PDOs" notes, the message bar and dialogs. No message shown on the page SHALL contain a filesystem path of the config or project, except where the path itself is the subject (the folder browser, the mode badge, the new-project dialog). An empty config SHALL be reported as "No nodes yet. Add a node from its EDS, or turn on Online access for a scan-only configuration." rather than as a schema error. An unexpected server error SHALL be shown as one sentence that points at the configurator's terminal, where the details are logged. The deploy tool's command-line messages are unchanged.

#### Scenario: Type does not fit the location
- **WHEN** node 5 (rtd) maps UNSIGNED8 object 0x6150:1 in TPDO 2 to `%IW320`
- **THEN** the Problems pane shows "Node 5 rtd, TPDO 2, 0x6150:1: type UNSIGNED8 (8 bit) does not fit location %IW320 (16 bit)" and clicking it scrolls to that entry's location field

#### Scenario: Trace note without a path
- **WHEN** the config has a type-does-not-fit error and the user opens a trace file
- **THEN** the Trace view's note reads "Decoding without the config's PDOs: Node 5 rtd, TPDO 2, 0x6150:1: type UNSIGNED8 (8 bit) does not fit location %IW320 (16 bit)" with no file path

#### Scenario: New config
- **WHEN** the user creates a new standalone config
- **THEN** the only problem reads "No nodes yet. Add a node from its EDS, or turn on Online access for a scan-only configuration."

### Requirement: Message bar
Messages about the user's actions (saved, sent, copied, added, and errors) SHALL be shown in a bar under the header that stays in view while the page scrolls and has a close button. Information messages SHALL close by themselves after about 6 seconds; error messages SHALL stay until the user closes them or a new message replaces them. Switching to another view (bus and master, a node, declarations, online, scan) SHALL clear the bar. The bar SHALL be a polite live region for information messages and an alert for errors, so assistive technology reads them. A message about a removal SHALL carry an Undo action for as long as it is shown.

#### Scenario: NMT command sent
- **WHEN** the user sends Start to node 2 in the online view
- **THEN** "Node 2: Start sent." is shown and disappears after about 6 seconds without a page reload

#### Scenario: Leaving the view clears the message
- **WHEN** a message from the online view is shown and the user opens "Bus and master"
- **THEN** the message bar is hidden

#### Scenario: Errors stay until closed
- **WHEN** a save fails with an error
- **THEN** the error stays in the bar until the user closes it, saves again or switches view

#### Scenario: Error is announced
- **WHEN** a save fails
- **THEN** the bar has the alert role and a screen reader reads the message without the user moving focus

### Requirement: Online view
With online access set up, the configurator SHALL offer an online view that connects to the runtime over the encrypted channel, refreshes about twice a second, and shows the bus state and counters, the master state, and for each node its state, status bit, boot result with error text, retry and hold state, last EMCY with class, SDO variable values and status, and a mark on each monitored TPDO that is timed out with its timeout count, using the node names from the config. Opening a node SHALL show its EMCY history with times and CiA 301 error classes, and for each monitored TPDO its timeout, count and time since its last PDO. When the runtime's config fingerprint differs from the saved `canopen.json`, the view SHALL say that the runtime runs a different configuration. Connection failures SHALL be shown with the reason (host unreachable, port closed, wrong token, runtime could not prove the token, plugin too old for encryption, no CANopen session) and retried. While retrying after a connection that was working, the last values SHALL stay visible but greyed, with the age of the last data shown and updated, so stale values are never mistaken for live ones. The different-configuration note SHALL say how to upload the saved config (the deploy tool command) so it can be acted on. The connection line SHALL be a polite live region.

#### Scenario: Watch a node come back
- **WHEN** the online view is open and node 23's cable is plugged back in
- **THEN** within about a second node 23's state goes from 0 to 127 to 5 and its boot result shows success

#### Scenario: Different config on the runtime
- **WHEN** the user saved a change but has not uploaded it yet
- **THEN** the online view shows that the runtime runs a different configuration

#### Scenario: Timed-out PDO
- **WHEN** node 23 is OPERATIONAL and its monitored TPDO 1 has timed out
- **THEN** node 23's row stays green for its state and shows "TPDO 1 timed out" with the count

#### Scenario: Plugin too old
- **WHEN** the runtime's plugin does not complete a TLS handshake
- **THEN** the view says the runtime's plugin is too old for encrypted diagnostics and must be updated, and offers no unencrypted connection

#### Scenario: Connection drops
- **WHEN** the online view is connected and the runtime stops answering
- **THEN** within about two seconds the node table turns grey, the connection line says it is not connected and retrying, and shows "last data 2 s ago" counting up until data arrives again

### Requirement: Trace view
The side bar SHALL have a Trace view next to the online view and the scan page. Opening, viewing and exporting trace files SHALL work without a runtime; recording SHALL need online access set up for the project. It SHALL offer start and stop, capture filters, error frames, clear, "Save to traces folder" (on this PC), open and "Download" (a file in the chosen format), the two format choices labelled apart; a scrolling decoded trace and a per-identifier table; display filters by node, frame kind (NMT, SYNC, EMCY, heartbeat, SDO, PDO, LSS, error, other), identifier range and text; the graph and trigger settings; and the statistics. Times SHALL be shown relative to the trace start or as UTC clock time. When the runtime's plugin does not know the trace operations, the view SHALL say that the plugin is too old for traces. Clear and Start SHALL say that the current recording is lost unless it was saved or downloaded, with Cancel as the default; closing the page or the folder with an unsaved recording SHALL ask first. The frame list SHALL move its selection with the arrow keys, Home, End, Page Up and Page Down, and the view's tabs SHALL follow the page's tab pattern (see "Keyboard access and announcements").

#### Scenario: Start a trace
- **WHEN** online access is set up and the user opens Trace and presses Start
- **THEN** decoded frames appear and the statistics update while the bus runs

#### Scenario: Filter display
- **WHEN** the user shows only node 23 and frame kind SDO
- **THEN** the trace lists only SDO requests and responses of node 23, and recording of other frames continues

#### Scenario: Old plugin
- **WHEN** the runtime's plugin answers the trace start as an unknown operation
- **THEN** the view says the plugin on the runtime is too old for traces and how to update it

#### Scenario: Open a file without a runtime
- **WHEN** the project has no online access and the user opens a candump log file in the Trace view
- **THEN** the frames are shown decoded and can be graphed and exported, and Start says online access must be set up

#### Scenario: Works offline
- **WHEN** the PC has no internet access
- **THEN** the Trace view and its graphs load and work

#### Scenario: Clear asks
- **WHEN** a recording of 3,000 frames has not been saved and the user clicks Clear
- **THEN** a dialog says the 3,000 frames are lost unless saved or downloaded, Cancel is the default, and Enter keeps the recording

### Requirement: Commission a device without a config
The configurator's start page SHALL offer "Commission a device", which opens the online pages on a USB adapter without any project or config: scan, object dictionary view (EDS from the scan match in the EDS library, or picked by the user), LSS, Parameters (backup, compare, restore, store) and Trace. "Add as node" SHALL be offered only when a config is open. In this mode the page SHALL show no config editing: no Project or Export menu, no Save, no Problems pane, and a side bar with only the online pages (Online, Scan the bus, Trace, Frame lab), so nothing suggests a config is being edited.

#### Scenario: New device on the desk
- **WHEN** the user opens "Commission a device", connects to a CANable at 250 kbit/s with "Allow changes" on, finds an unconfigured device with LSS and gives it node ID 12
- **THEN** a scan lists node 12, and nothing was stored on the device unless the user ticked "store"

#### Scenario: Nothing to save
- **WHEN** the user opens "Commission a device"
- **THEN** the header shows the mode badge, the theme choice and Close only, the side bar lists Online, Scan the bus, Trace and Frame lab, and no problem is reported

### Requirement: Frame lab view
The side bar SHALL have a Frame lab view that works without a runtime and without a trace. It SHALL accept a frame typed as identifier and data or pasted in candump syntax, offer example frames generated from the open configuration (saved or not) and the frame builder of the `canopen-frame-explain` capability, and show the result in the inspector panel at the network's bit rate, with a bit rate picker. It SHALL have an arbitration demo: two frames chosen by the user are shown sent at the same time bit by bit, with each sender's bit, the bus level and the bit where the sender of a recessive bit reads a dominant level and stops, and which frame wins. The Frame lab SHALL never send anything to the bus and SHALL say so, and none of its controls SHALL be labelled as sending (the arbitration demo's button is "Run both").

#### Scenario: Paste a frame
- **WHEN** the user pastes `705#7F` in the Frame lab
- **THEN** it is explained as node 5's heartbeat in Pre-operational

#### Scenario: Arbitration
- **WHEN** the user picks node 5's TPDO1 (0x185) and node 3's TPDO1 (0x183) for the arbitration demo
- **THEN** the demo shows both identical up to identifier bit 2, node 3's frame driving it dominant there, node 5's sender stopping, and 0x183 winning

#### Scenario: Example frames follow the config
- **WHEN** the user adds node 7 without saving and opens the Frame lab
- **THEN** the example frames include node 7's boot-up, heartbeat, SDO read of 1018h:01 and its PDOs
