## ADDED Requirements

### Requirement: One EDS dialog
Every place that picks an EDS SHALL use one dialog. Its list SHALL group the files as **Matches this device**, **Built here**, **In this project** and **EDS library**, in that order, each shown only when it has files, and show each file's product name and file name. **Browse…** SHALL open the page's file browser on EDS files, then import the picked file and select it. The current EDS, else the best match, SHALL be selected when the dialog opens.

#### Scenario: Same list in Configure and Commission
- **WHEN** the config has `dio16.eds` used by node 6, an EDS library is set, and the user opens Add node… in Configure and Choose EDS… for an unconfigured node in Commission
- **THEN** both dialogs list `dio16.eds` under In this project with its product name and "used by 1 node", and the library's files under EDS library

#### Scenario: Matches first
- **WHEN** the user opens Choose EDS… for a scanned node whose identity matches two library files, one with the exact revision
- **THEN** the list starts with Matches this device, the exact-revision file first and selected, marked "exact revision"

#### Scenario: Browse with a name clash
- **WHEN** the user presses Browse… in the dialog and picks a file named like an EDS already in the config but with other content
- **THEN** the page asks to replace it or keep both, and the kept file is selected in the list

#### Scenario: Library file imported on use
- **WHEN** the user selects an EDS library file and presses the dialog's main button
- **THEN** the file is imported with the place's EDS lint and used, and Cancel before that imports nothing

### Requirement: Keyboard in the EDS dialog
Enter or a double-click on an entry of the EDS dialog's list SHALL press the dialog's main button. The dialog SHALL open with focus in the list, or on **Browse…** when the list is empty, and focus SHALL return to the control that opened it when it closes.

#### Scenario: Pick with Enter
- **WHEN** the user moves to an entry with the arrow keys and presses Enter
- **THEN** the dialog acts as if its main button (Add, Add node, Use) was pressed

#### Scenario: Cancel
- **WHEN** the user opens Change EDS… on a node's General tab, selects another file and presses Escape
- **THEN** the node's EDS is unchanged, the draft is not marked changed, and focus is on Change EDS…

### Requirement: One EDS field
Where a page shows the EDS chosen for a node, slave or device, it SHALL show the product name and file name as text with **Choose EDS…** when there is none and **Change EDS…** when there is one, both opening the EDS dialog. No page SHALL show a dropdown of EDS file names or a browser file input for an EDS.

#### Scenario: Node General tab
- **WHEN** the user opens node 6's General tab
- **THEN** the EDS reads as its product name and `dio16.eds` with Change EDS…, and there is no EDS dropdown

#### Scenario: No file inputs left
- **WHEN** the browser tests open every view of Configure, Commission, Trace and Simulation with a config that has a slave network and a node without an EDS match
- **THEN** no visible `input[type=file]` accepts `.eds`, and no `select` lists EDS file names

#### Scenario: Simulation extra device
- **WHEN** the user presses Choose EDS… for a new extra device in the simulation view
- **THEN** the dialog's Browse… accepts EDS and DCF files and In this project lists the folder's EDS and DCF files

### Requirement: EDS chosen in one place per node
In Commission a device, a node's EDS SHALL be chosen only through its EDS field (Nodes table and node header). The Parameters tab, the Trace Decoding panel and the frame inspector SHALL open that field's dialog for the node. **Add to config** and **Add to a config…** SHALL use the node's EDS on the page and open its dialog first only when it has none.

#### Scenario: Trace uses the node's EDS
- **WHEN** the user presses Choose EDS… for node 50 in the Trace Decoding panel and picks a file
- **THEN** the Nodes table shows that EDS for node 50 and the trace decodes with it

#### Scenario: Add to a config without an EDS
- **WHEN** node 12 has no EDS on the page and the user presses Add to a config…
- **THEN** the EDS dialog opens for node 12 first, and the config dialog follows with the picked EDS, without a file input

## MODIFIED Requirements

### Requirement: Slave device page
The slave device page SHALL edit node ID (or LSS), the EDS (choose a file, or build one), the bound objects with their PLC locations, `inputs_on_loss` and the status and EMCY locations. Object rows SHALL come from the EDS, show the direction from its access type, and offer only matching PLC areas. The EDS SHALL be an EDS field (see "One EDS field"); its dialog SHALL list the EDS files generated for a slave of this config under **Built here** and import with the slave's EDS lint.

#### Scenario: Bind an object
- **WHEN** the user adds 0x2100:1 (access `ro`, UNSIGNED16) from the EDS
- **THEN** the row suggests a free `%QW` location and refuses an `%I` one

#### Scenario: Choose a library EDS for the slave
- **WHEN** the slave has no EDS, an EDS library is set, and the user presses Choose EDS…, picks a library file and presses Use
- **THEN** the file is imported with the slave's EDS lint, the EDS field shows its product name and file name, and the object list offers its objects

#### Scenario: Generated EDS comes first
- **WHEN** the config has a generated `openplc-slave.eds` and two node EDS files, and the user opens Change EDS… on the slave page
- **THEN** `openplc-slave.eds` is under Built here, above In this project, and selected

### Requirement: Add node dialog
**Add node…** SHALL open a dialog with:
- the device description: the list of "One EDS dialog", with the config's EDS files (product name, file name, nodes using it), the EDS library's files, and **Browse…**;
- the node ID: the lowest free ID, checked as typed;
- the name: from the EDS product name, unique in the network;
- **Map the EDS's default PDOs**, ticked.

**Add** SHALL add the node to that network. Cancel SHALL add nothing.

#### Scenario: Second node of a known type
- **WHEN** the virtual plant's `io` network has node 6 with `dio16.eds` and the user opens Add node…, picks dio16.eds from the list, and presses Add
- **THEN** a node with the lowest free ID and a unique name is added with `dio16.eds`, and no file picker was opened

#### Scenario: Taken node ID
- **WHEN** the user types 6 as the node ID in the dialog on `io`
- **THEN** the field says node 6 is already used and Add is disabled with that reason

#### Scenario: Double-click adds
- **WHEN** the node ID and name are valid and the user double-clicks `dio16.eds` in the list
- **THEN** the node is added as if Add was pressed

### Requirement: Nodes in commissioning
In Commission a device, the Nodes table (see "Nodes table") SHALL list the devices of this session: heard, found by a scan, given a node ID by LSS, or added with **Add node from EDS…**. **Add node from EDS…** SHALL open a dialog with the list of "One EDS dialog" and a node ID, and **Add node** SHALL add the device with that EDS, kept in this page only. It SHALL NOT open the system file picker before the dialog.

The table SHALL have:
- **Scan the bus**, with progress and **Cancel** in the status bar, which stops the scan and keeps the devices found so far;
- the Unconfigured devices panel (LSS find, Set node ID, Set bit rate).

A device's node tabs SHALL be those of "Commission node tabs", and its Status tab SHALL offer **Add to a config…**.

#### Scenario: Device that does not answer the scan
- **WHEN** a device in STOPPED state is on the bus and the user adds node 23 with its EDS through Add node from EDS…
- **THEN** node 23 is listed with that EDS, and its Object dictionary and Parameters tabs use it

#### Scenario: Cancel a long scan
- **WHEN** a scan is running and the user presses Cancel
- **THEN** the scan stops within a second and the devices found so far stay listed

#### Scenario: Not connected yet
- **WHEN** the user opens Commission a device before connecting
- **THEN** the Nodes table says in place of its rows that it lists the devices once connected with Connect… in the connection bar, with no connect form or button of its own

#### Scenario: Add node from the library
- **WHEN** the user presses Add node from EDS…, picks a library file, types 23 and presses Add node
- **THEN** node 23 is listed with that EDS, and no system file picker was opened

### Requirement: Add found devices to the config
On the comparison the page SHALL offer:
- **Add to config** for Not in config rows, one or several ticked rows at once: each becomes an unsaved node with that node ID, the matching EDS (the EDS dialog, with **Add node** and **Skip**, when several match or none does), the EDS product name as name and the serial number, with `lss.assign` set when the ID was given by LSS in this session and the EDS says `LSS_Supported=1`;
- **Use matching EDS** for an Identity differs row when an EDS in the project or the EDS library matches the device;
- **Take serial number** when only the serial number differs.

Each action SHALL be a draft edit that Undo reverts. The user SHALL stay in Commission, the header SHALL show the unsaved mark, and problems the change causes SHALL show in the bottom panel's Problems tab.

#### Scenario: Add a found device
- **WHEN** node 9 reads Not in config, one EDS in the library matches it, and the user presses Add to config
- **THEN** the draft has node 9 with that EDS imported, its product name and serial number, the row reads Match, and the header shows the unsaved mark

#### Scenario: Undo an add
- **WHEN** the user added node 9 from the comparison and presses Undo
- **THEN** node 9 is gone from the draft and its row reads Not in config again

#### Scenario: No match
- **WHEN** node 12 reads Not in config, no EDS matches it, and the user presses Add to config
- **THEN** the EDS dialog opens for node 12 with In this project, EDS library and Browse…, and Skip leaves node 12 out of the draft

### Requirement: Parameters of a node without an EDS
The Parameters tab of a node without an EDS SHALL say that back up, compare and restore need the device's EDS and offer **Choose EDS…**, whose dialog lists the node's EDS matches first.

#### Scenario: Parameters without an EDS
- **WHEN** the user opens the Parameters tab of node 49, which has no EDS
- **THEN** the tab says back up, compare and restore need the device's EDS and offers Choose EDS…

### Requirement: Change or clear a node's EDS
In the Nodes table, a node whose EDS was picked, matched or added on the page (not from the config) SHALL show the EDS file name with **Change EDS…**. It SHALL open the EDS dialog, with the node's matches first and **Clear EDS** (or **Remove node** for a node only added on the page) beside **Use** and **Cancel**. Changing SHALL reload the node's tabs from the new EDS, clearing SHALL return the node to the standard dictionary, and both SHALL be logged in the Commissioning log.

#### Scenario: Wrong EDS picked
- **WHEN** node 23 shows an EDS file the user picked by mistake and the user picks another file in the Change EDS… dialog
- **THEN** the EDS column shows the new file name and node 23's Object dictionary tab shows the new EDS's objects

#### Scenario: Clear the EDS
- **WHEN** the user chooses Clear EDS for heard node 23
- **THEN** the EDS column offers the EDS choices again and node 23's Object dictionary tab shows the standard dictionary

#### Scenario: Node added only from an EDS
- **WHEN** node 40 was added with Add node from EDS… and is not heard
- **THEN** its menu offers Remove node in place of Clear EDS, and removing it takes the row away

#### Scenario: EDS from the config
- **WHEN** node 5 is in the config with its EDS
- **THEN** its EDS cell shows the config's EDS without Change EDS…, and its tooltip says the EDS is changed on the node's page in Configure

### Requirement: Decoding panel in the Trace view
The Trace toolbar's **Decoding** button SHALL open a panel that says what the trace decodes with and lets the user change it. The button SHALL show a short summary (number of DBC files, number of nodes with a known PDO layout) and a warning mark when a DBC file is missing or has problems.

The panel SHALL have:
- **DBC files**: each file's name, how many of its messages are used out of its total, its problems and the messages not used with what decodes their identifier instead; **Add DBC…** (one or more files), remove, and a way to change the order with the mouse and the keyboard.
- **Nodes**, on a CANopen network: each node heard on the bus or on the Nodes tab, with its device name, its EDS file or "none, built-in CiA names", the source of its PDO layout ("set on the bus at …", "read from the device at …", "EDS defaults", "configuration", or "unknown"), and the actions **Choose EDS…** or **Change EDS…** (the EDS dialog, as in the Nodes table) and **Read PDOs from device**.

**Read PDOs from device** SHALL be disabled with its reason without a live connection. While the connection bar reports another master, it SHALL ask first, saying that the other master's SDO transfers to the node can be mixed with the read.

The DBC files SHALL be remembered on this PC per project folder, and once for Commission a device, outside the project's canworks folder. A remembered file that is missing SHALL be listed as missing with Locate… and Remove, and decoding SHALL go on without it.

#### Scenario: Add a DBC
- **WHEN** the user opens Decoding, presses Add DBC… and picks `machine.dbc` with 12 messages, 2 of which are on identifiers the configuration decodes
- **THEN** the panel lists `machine.dbc` with "10 of 12 messages used", names the 2 messages and what decodes them, the rows of the other 10 identifiers decode with the DBC, and the button reads "1 DBC"

#### Scenario: Remembered
- **WHEN** the user closes the page and opens Commission a device again the next day
- **THEN** the Trace decodes with the same DBC files without asking

#### Scenario: Fix a raw PDO from the panel
- **WHEN** node 50's PDOs show as bytes and its layout source reads "unknown", and the user picks its EDS with Choose EDS…
- **THEN** its PDO rows decode with the EDS defaults and the source reads "EDS defaults"

### Requirement: PDO layout in the frame inspector
For a PDO frame the frame inspector SHALL show a Layout line naming where the layout came from (configuration, DBC file, set on the bus at a time, read from the device at a time, or EDS defaults). Rows and inspectors decoded with EDS defaults SHALL carry an "assumed" tag whose tooltip says that the device may be mapped differently and how to make it certain. For a PDO frame shown as bytes, the Layout line SHALL say why and offer **Choose EDS…** and **Read PDOs from device** for its node.

#### Scenario: Raw PDO in the inspector
- **WHEN** the user selects a TPDO1 row of node 50 that shows only bytes
- **THEN** the inspector's Layout line says node 50 has no EDS and its PDOs were not read, with Choose EDS… and Read PDOs from device

#### Scenario: Assumed layout
- **WHEN** node 32's TPDO1 decodes with its EDS defaults
- **THEN** the row shows the "assumed" tag and the inspector's Layout line reads "EDS defaults: the device may be mapped differently"

### Requirement: Fields and buttons fit their content
On every view, at window widths from 1000 px up, no input, dropdown or button SHALL clip its value, placeholder, selected choice or label, and no view SHALL need horizontal scrolling. Dropdowns SHALL be as wide as their longest choice up to the width of their column. A button SHALL NOT wrap its label. Buttons that belong to one row (move up, move down, remove; Read and Write) SHALL stay on one line, and an object picker's "by hand" index, subindex and Add controls SHALL stay together. Buttons in table rows SHALL be vertically centred with the row's text.

#### Scenario: Adapter type
- **WHEN** the bus page shows adapter type "SocketCAN (CAN HAT, candleLight/gs_usb, PEAK, vcan)" in a 1280 px window
- **THEN** the whole choice text is visible

#### Scenario: Startup SDO row buttons
- **WHEN** a node has four startup SDO writes
- **THEN** each row shows ↑, ↓ and ✕ side by side on one line

#### Scenario: Scan page button
- **WHEN** the scan finds a device with no matching EDS
- **THEN** its "Choose EDS…" button shows its label on one line

#### Scenario: Automatic check
- **WHEN** the browser tests open each view (start, bus and master, each node, declarations, online, scan, the EDS dialog) at 1000, 1280 and 1440 px
- **THEN** a check over the page finds no clipped field or button and no horizontal overflow

### Requirement: Unconfigured devices in the online view
The Nodes table SHALL have an **Unconfigured devices** panel, with and without a config. It SHALL be collapsed until changes are allowed or a search runs. It SHALL find a device without a node ID and show:
- its vendor ID, with the vendor name when an EDS gives it;
- its product code, revision and serial number;
- the best matching EDS from the project's `canworks/` folder or the EDS library, as text (product name and file name), with no picker of its own: after "Set node ID" the node's EDS is changed in the Nodes table.

It SHALL offer "Set node ID" and "Set bit rate" for the device. Both dialogs SHALL have a "Store in the device" checkbox that is unticked each time the dialog opens.

"Set node ID" SHALL suggest the lowest node ID that is neither configured nor the master's. With a config, after success, the device SHALL be listed as Not in config and the page SHALL offer Add to config with that ID and EDS, setting `serial_number` and `lss.assign`. "Set bit rate" SHALL say before sending that the device switches after its next power cycle and that the connection's bit rate must be changed to match. Without changes allowed, the panel's controls SHALL be disabled with Unlock… (see "Unlock from a locked control").

When the matching EDS does not say `LSS_Supported=1`, the device SHALL be added without `lss.assign`, and the page SHALL say that its EDS has no LSS, so the node gets no LSS assignment.

#### Scenario: Commission a new sensor
- **WHEN** the user finds a device without node ID, sets node ID 40 with "Store in the device" ticked, and presses Add to config
- **THEN** the runtime sets and stores node ID 40, and the draft gets node 40 with the matching EDS, the device's serial number and `"lss": {"assign": true}`, unsaved until the user saves

#### Scenario: Store unticked by default
- **WHEN** the user opens "Set node ID" a second time after storing once
- **THEN** the "Store in the device" checkbox is unticked
