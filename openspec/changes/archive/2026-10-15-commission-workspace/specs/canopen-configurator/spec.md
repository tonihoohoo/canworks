## ADDED Requirements

### Requirement: Nodes table
The Commission workspace SHALL open on a **Nodes** table, with and without a config. It SHALL list every node known in the session:
- with a config, the configured nodes of the picked network;
- nodes heard (heartbeat or boot-up);
- nodes found by a scan or given a node ID by LSS;
- in Commission a device, nodes added with **Add node from EDS…**.

Each row SHALL show the node ID, name, NMT state as text and shape, time since last heard, last EMCY and EDS; with a config also the boot result, the comparison state and whether the node is simulated or absent. Values older than the last answer SHALL be greyed. Clicking a row, or Enter on its node ID button, SHALL select the node in the tree and open its Status tab. With a config, the table SHALL be what the tree's network entry opens (see "Tree in Commission with a config"); the node marks of "Live state on the network tree" SHALL use the tree's node mark slot.

#### Scenario: Same home in both modes
- **WHEN** the user opens Commission with a config, and later opens Commission a device
- **THEN** both open on the Nodes table, with the comparison column only in the first

#### Scenario: Open a node from the table
- **WHEN** the user presses Enter on node 5's node ID button
- **THEN** node 5 is selected in the tree and its Status tab shows

### Requirement: Connect from the Nodes table
While not connected, the Nodes table SHALL show the connect panel's form in place of its rows, with up to three recent connections of this PC, each connectable with one click. A recent adapter connection SHALL still run the bit rate check and SHALL start with Allow changes off. Recent connections SHALL be kept in the configurator's settings on this PC without tokens. The connect panel SHALL NOT open by itself on entering Commission.

#### Scenario: Reconnect to the last adapter
- **WHEN** the user opens Commission a device on a PC that last connected to gs_usb:0 at 500 kbit/s
- **THEN** the Nodes table offers "gs_usb:0 at 500 kbit/s", and one click connects after the bit rate check with Allow changes off

### Requirement: Scan compared with the config
With a config, **Scan the bus** on the Nodes table SHALL compare the devices found with the configured nodes of the picked network. Each row SHALL get one state, named in text:
- **Match**: configured, answered, identity as the config expects;
- **Missing**: configured, did not answer and was not heard;
- **Not in config**: answered or heard, not configured;
- **Identity differs**: configured and answered with a different vendor, product, revision or serial number than expected, listing the differing fields.

Before a scan the rows SHALL show Heard or Not heard. A summary SHALL count each state, each count filtering the table. Match SHALL use no warning or fault colour, Missing the fault colour, the others the warning colour. Without a config the scan SHALL list the devices found as before.

#### Scenario: One device missing, one new
- **WHEN** the config has nodes 3, 5 and 7, the bus has nodes 3, 5 and 9, and the user scans
- **THEN** 3 and 5 read Match, 7 reads Missing, 9 reads Not in config, and the summary reads "2 match · 1 missing · 1 not in config"

#### Scenario: Replaced device with another revision
- **WHEN** node 5's config sets revision 0x00020000 and the device answers 0x00030000
- **THEN** node 5 reads Identity differs and names the revision with both values

### Requirement: Add found devices to the config
On the comparison the page SHALL offer:
- **Add to config** for Not in config rows, one or several ticked rows at once: each becomes an unsaved node with that node ID, the matching EDS (a picker when several match, a file picker when none does), the EDS product name as name and the serial number, with `lss.assign` set when the ID was given by LSS in this session and the EDS says `LSS_Supported=1`;
- **Use matching EDS** for an Identity differs row when an EDS in the project or the EDS library matches the device;
- **Take serial number** when only the serial number differs.

Each action SHALL be a draft edit that Undo reverts. The user SHALL stay in Commission, the header SHALL show the unsaved mark, and problems the change causes SHALL show in the bottom panel's Problems tab.

#### Scenario: Add a found device
- **WHEN** node 9 reads Not in config, one EDS in the library matches it, and the user presses Add to config
- **THEN** the draft has node 9 with that EDS imported, its product name and serial number, the row reads Match, and the header shows the unsaved mark

#### Scenario: Undo an add
- **WHEN** the user added node 9 from the comparison and presses Undo
- **THEN** node 9 is gone from the draft and its row reads Not in config again

### Requirement: Scan through a runtime
With a config, the scan SHALL run through the runtime connection, from the Commission workspace only. It SHALL NOT need Allow changes. When the runtime refuses because a node is OPERATIONAL, the page SHALL name those nodes, say that the scan sends SDO requests to every node ID while the program runs, and scan with force only after the user confirms, with Cancel as the default. On a relayed path or a round trip above 100 ms the page SHALL ask first, as for LSS.

#### Scenario: Scan a running machine
- **WHEN** nodes 3 and 5 are OPERATIONAL and the user presses Scan the bus
- **THEN** a dialog names nodes 3 and 5, nothing is sent while it is open, and confirming scans with force and lists the progress in the status bar

### Requirement: Commission node tabs
A node opened in the Commission workspace SHALL have the tabs:
- **Status**;
- **Object dictionary**;
- **Parameters**;
- **PDO test**, in Commission a device only;
- **Notes**;
- **Log**.

The selected tab SHALL stay selected when the user picks another node. The tabs SHALL follow the page's tab pattern.

#### Scenario: Step through nodes on one tab
- **WHEN** the user is on node 5's Object dictionary tab and picks node 7 in the tree
- **THEN** node 7's Object dictionary tab shows

### Requirement: Node Status tab
A node's **Status** tab SHALL show, in this order:
- NMT state, time since last heard and heartbeat state;
- boot result with its error text, and retry or hold state (with a config);
- the NMT buttons with their confirmations;
- for each monitored TPDO, its timeout, count and time since its last PDO (with a config);
- the EMCY history with times and CiA 301 error classes;
- the error history (0x1003).

Opening the tab SHALL clear the node's new-entry flag on the tree.

#### Scenario: Stopped node
- **WHEN** node 7 is STOPPED and the user opens its Status tab
- **THEN** the tab shows Stopped as text and shape, its last heartbeat age, and Start enabled when changes are allowed

### Requirement: Session log
The Commission workspace SHALL keep a log of the page session with:
- events: NMT state changes, boot results, EMCY, error history changes, SDO aborts, PDO timeouts, connection ended;
- changes made through the page (see "Commissioning log"), and the comparison's actions.

Each entry SHALL have the UTC time, network, node, kind, text and result. A node's **Log** tab SHALL show that node's entries; the bottom panel's **Log** tab SHALL show all, with a filter All, Changes or Events. The log SHALL keep at least the last 5,000 events and every change. It SHALL NOT contain host names or tokens and SHALL NOT be written into any project. With a config, the log SHALL be shown only in Commission, and Save log SHALL download `<config>-commission-<time>.txt`.

#### Scenario: Node log after a power cycle
- **WHEN** node 23 is power cycled while the user is connected
- **THEN** node 23's Log tab lists the state change to not answering, the boot-up and the return to Operational with their times

#### Scenario: No log in Configure
- **WHEN** the user switches from Commission to Configure with a config
- **THEN** the bottom panel shows Problems only and no log is shown

### Requirement: Live state on the network tree
While connected in Commission, and in Configure while connected to a runtime, each node in the network tree SHALL show:
- its NMT state by shape (circle Operational, triangle Pre-operational, square Stopped, cross not answering or boot failed, hollow circle not heard) with the state as text for assistive technology;
- a flag when a new EMCY or error history entry arrived since its Status tab was last opened;
- after a scan, a mark for Missing or Identity differs.

The state SHALL never be shown by colour alone. Without a connection the tree SHALL show no live state.

#### Scenario: Node drops out
- **WHEN** node 7 stops answering while the user is on node 5's Object dictionary tab
- **THEN** node 7's tree entry shows the not-answering cross, and a screen reader reads "7 valve, not answering"

### Requirement: Unlock from a locked control
A write control disabled because changes are not allowed SHALL say "Locked. Changes are not allowed on this connection." and offer **Unlock…**. On an adapter, Unlock SHALL ask the same question as the lock in the connection bar and, when confirmed, allow changes on the open connection without reconnecting, with focus kept on the control. On a runtime, Unlock SHALL explain that Allow changes is set in Configure → Bus and master → Online access and takes effect after an upload. Controls disabled for another reason SHALL keep their own reason.

#### Scenario: Unlock in place
- **WHEN** the user is connected read-only to an adapter, presses Unlock… beside node 5's Start button and confirms
- **THEN** Allow changes is on in the connection bar, Start is enabled and focused, and no "another master" message appears

### Requirement: Simulated devices in Commission
Connected to a runtime with simulated devices, such as the local simulator runtime, the Commission workspace SHALL work as on a real bus: scan, LSS, object dictionary, Parameters and NMT. Simulated nodes SHALL be marked in the Nodes table. Extra devices of the simulation file SHALL appear as Not in config when found. A simulated node's Status tab SHALL have a **Simulated device** panel with:
- its power state with Power off and Power on;
- the faults the simulator offers, to inject and clear;
- its PDO objects with live values, each with Override and Release.

The panel SHALL follow Allow changes as the Simulation tool does.

#### Scenario: Practise adding a device
- **WHEN** the simulation file has an extra device with node ID 40 and the user scans on the local simulator runtime
- **THEN** node 40 reads Not in config and Add to config adds it to the draft

#### Scenario: Inject a fault from the Status tab
- **WHEN** the user injects heartbeat stop on simulated node 5's Status tab with changes allowed
- **THEN** node 5's state turns to not answering in the table and the tree, its Log tab records it, and Clear brings it back

## MODIFIED Requirements

### Requirement: Online view
With online access set up and a runtime connected, the Commission workspace of a config SHALL show the runtime's state through the encrypted channel, refreshed about twice a second: the bus state and counters and the master state in the connection bar, and each node in the Nodes table and its Status tab, using the node names from the config. For each node it SHALL show its state, status bit, boot result with error text, retry and hold state, last EMCY with class, SDO variable values and status, and a mark on each monitored TPDO that is timed out with its timeout count. When the runtime's config fingerprint differs from the saved `canworks.json`, the workspace SHALL say that the runtime runs a different configuration and how to upload the saved config (the deploy tool command). Connection failures SHALL be shown in the connection bar with the reason (host unreachable, port closed, wrong token, runtime could not prove the token, plugin too old for encryption, no CANopen session) and retried. While retrying after a connection that was working, the last values SHALL stay visible but greyed, with the age of the last data shown and updated.

#### Scenario: Watch a node come back
- **WHEN** the Nodes table is open and node 23's cable is plugged back in
- **THEN** within about a second node 23's state goes from 0 to 127 to 5 and its boot result shows success

#### Scenario: Different config on the runtime
- **WHEN** the user saved a change but has not uploaded it yet
- **THEN** the Commission workspace shows that the runtime runs a different configuration

#### Scenario: Timed-out PDO
- **WHEN** node 23 is OPERATIONAL and its monitored TPDO 1 has timed out
- **THEN** node 23's row keeps its Operational state and shows "TPDO 1 timed out" with the count

#### Scenario: Plugin too old
- **WHEN** the runtime's plugin does not complete a TLS handshake
- **THEN** the connection bar says the runtime's plugin is too old for encrypted diagnostics and must be updated, and no unencrypted connection is offered

#### Scenario: Connection drops
- **WHEN** the runtime stops answering
- **THEN** within about two seconds the Nodes table turns grey, the connection bar says it is not connected and retrying, and shows "last data 2 s ago" counting up until data arrives again

### Requirement: Nodes in commissioning
In Commission a device, the Nodes table (see "Nodes table") SHALL list the devices of this session: heard, found by a scan, given a node ID by LSS, or added with **Add node from EDS…**. **Add node from EDS…** SHALL take a node ID and an EDS file and add the device with that EDS, kept in this page only.

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
- **THEN** the Nodes table shows the connect form and the recent connections in place of its rows

### Requirement: Unconfigured devices in the online view
The Nodes table SHALL have an **Unconfigured devices** panel, with and without a config. It SHALL be collapsed until changes are allowed or a search runs. It SHALL find a device without a node ID and show:
- its vendor ID, with the vendor name when an EDS gives it;
- its product code, revision and serial number;
- a matching EDS when the project's `canworks/` folder or the EDS library has one.

It SHALL offer "Set node ID" and "Set bit rate" for the device. Both dialogs SHALL have a "Store in the device" checkbox that is unticked each time the dialog opens.

"Set node ID" SHALL suggest the lowest node ID that is neither configured nor the master's. With a config, after success, the device SHALL be listed as Not in config and the page SHALL offer Add to config with that ID and EDS, setting `serial_number` and `lss.assign`. "Set bit rate" SHALL say before sending that the device switches after its next power cycle and that the connection's bit rate must be changed to match. Without changes allowed, the panel's controls SHALL be disabled with Unlock… (see "Unlock from a locked control").

When the matching EDS does not say `LSS_Supported=1`, the device SHALL be added without `lss.assign`, and the page SHALL say that its EDS has no LSS, so the node gets no LSS assignment.

#### Scenario: Commission a new sensor
- **WHEN** the user finds a device without node ID, sets node ID 40 with "Store in the device" ticked, and presses Add to config
- **THEN** the runtime sets and stores node ID 40, and the draft gets node 40 with the matching EDS, the device's serial number and `"lss": {"assign": true}`, unsaved until the user saves

#### Scenario: Store unticked by default
- **WHEN** the user opens "Set node ID" a second time after storing once
- **THEN** the "Store in the device" checkbox is unticked

### Requirement: Device error history in the online view
A node's Status tab SHALL show, under its EMCY history, an "Error history (0x1003)" section with the count and the entries as the diagnostics' device error history defines them, a Refresh button and a Clear button. Clear SHALL be disabled with Unlock… when the connection does not allow changes; otherwise it SHALL ask for confirmation naming the node and the number of entries, with Cancel as the default, and when the node is OPERATIONAL a second confirmation SHALL say that the node is running and offer to force the write. After a clear the section SHALL read the history again, and the Log SHALL record the clear.

#### Scenario: History shown
- **WHEN** the user opens node 5's Status tab and node 5's 0x1003 holds 2 entries
- **THEN** the section shows count 2 and both entries, newest first, with code, class and manufacturer information

#### Scenario: Clear without changes allowed
- **WHEN** the connection does not allow changes
- **THEN** the Clear button is disabled and offers Unlock…

#### Scenario: Clear a running node
- **WHEN** changes are allowed, node 5 is OPERATIONAL and the user clicks Clear and confirms
- **THEN** the page asks again, saying node 5 is OPERATIONAL; after the user confirms the forced write, the section shows count 0

### Requirement: Commissioning log
In Commission a device, the session log (see "Session log") SHALL record every change made through the page:
- SDO write;
- NMT;
- LSS set ID, set bit rate and store;
- write configuration;
- restore and restore defaults;
- store;
- error history clear.

"Save log" in the bottom panel's Log tab SHALL download `node<N>-commissioning-<time>.txt` with the device identity and EDS name at the top and the changes in order, and the bus events too when "Include bus events" is ticked (unticked by default).

The log SHALL belong to the commissioning session. Leaving Commission a device (Close, or "Add to a config…") with changes not saved SHALL ask whether to save the log first. The log SHALL then be cleared.

#### Scenario: Save the record
- **WHEN** the user gave the device node ID 12, wrote a configuration and stored it, then pressed Save log
- **THEN** the file lists those three changes in order with their results and no bus events

#### Scenario: Not carried into the config
- **WHEN** the user made two changes while commissioning, pressed "Add to a config…" and chose not to save the log
- **THEN** the config opens with an empty session log, and returning to Commission a device starts an empty log

### Requirement: Bottom panel
The page SHALL have a collapsible panel under the page, with its height kept on this PC. Its contents SHALL depend on the workspace:
- **Configure:** a **Problems** tab, with Allow overlap. It SHALL open by itself when problems appear after a save or check.
- **Commission a device:** a **Log** tab with the session log and **Save log**.
- **Commission with a config:** a **Log** tab (selected by default) and a **Problems** tab; Problems SHALL open by itself when a comparison action causes a problem.

Each tab title SHALL carry its count. There SHALL be no right-hand Problems column.

#### Scenario: Problems under the page
- **WHEN** the config has 4 errors in Configure
- **THEN** the panel's tab reads "Problems 4", the page uses the full width beside the tree, and clicking a problem goes to its field

#### Scenario: Log while commissioning
- **WHEN** the user gave a device node ID 12 by LSS in Commission a device
- **THEN** the Log tab lists the change, the Changes filter reads 1, and Save log downloads the log

#### Scenario: Problem after adding a found device
- **WHEN** the user adds a found node 9 whose EDS has no TPDO the config can map, and the check reports a problem
- **THEN** the Problems tab opens with that problem and the user stays in Commission

### Requirement: Connect panel
**Connect…** SHALL open one connect panel. It and its inline form on the Nodes table (see "Connect from the Nodes table") SHALL be the only places to connect.

In Commission a device the panel SHALL offer a USB adapter only:
- the found adapters with Refresh, or a typed target;
- the bit rate, picked by the user, with no detection and no default;
- "Device's node ID, to check the bit rate", for adapters that cannot report a sent frame;
- **Allow changes**, unticked;
- **Connect**.

A refused bit rate check SHALL keep the panel open with the reason and the form filled in.

With a config the panel SHALL offer a runtime only:
- the found and remembered runtimes, the host field and **Local simulator runtime**;
- the token prompt when this PC has no matching token;
- **Connect**.

When the config's online access is off, the panel SHALL say so and link to Configure → Bus and master.

The last target and bit rate SHALL be kept in the configurator's settings on this PC, never in a project.

#### Scenario: Wrong bit rate refused
- **WHEN** the bus runs at 500 kbit/s and the user connects at 1000 kbit/s in the panel
- **THEN** the panel stays open, says the bus does not run at 1000 kbit/s, and the user can pick 500 kbit/s and connect without replugging the adapter

#### Scenario: Runtime needs a token
- **WHEN** the user picks a found runtime and this PC has no token for the config
- **THEN** the panel asks for the token, accepts it only if it matches the config's verifier, and connects

#### Scenario: Disconnect frees the adapter
- **WHEN** the user presses Disconnect in the bar while connected to an adapter
- **THEN** the adapter is closed, the scan, PDO test, SYNC, send jobs and trace recording on it stop, and `canworks-diag --adapter` can open the same adapter

### Requirement: Keyboard access and announcements
Everything the pointer can do on the page SHALL be possible with the keyboard.
- **Lists:** the network tree SHALL be reachable with one tab stop and work as in "Network tree keyboard", with the open entry marked as selected. The problem list SHALL be made of buttons in the tab order. Rows that open something (scanned devices, simulated devices) SHALL be focusable and open on Enter or Space; a Nodes table row SHALL open from its node ID button, which is in the tab order, since the row holds the comparison's buttons too.
- **Tabs:** tabs (the node tabs, Trace, the Commission node tabs Status / Object dictionary / Parameters / PDO test / Notes / Log, Simulation) SHALL be a tab list with the selected tab marked and each tab naming its panel. Left, Right, Home and End SHALL move between them.
- **Focus:** every focused control SHALL show a visible focus ring in the accent colour.
- **Announcements:** progress lines (reading all, backup, scan), the problem count, the comparison summary and node state changes on the tree SHALL be polite live regions, and the tree's and tabs' badges SHALL carry their counts in their accessible names.
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

#### Scenario: Open a node from the Nodes table by keyboard
- **WHEN** focus is on node 5's node ID button in the Nodes table and the user presses Enter
- **THEN** node 5's Status tab opens and focus moves to its tab list

#### Scenario: Commission node tabs by keyboard
- **WHEN** focus is on node 5's "Status" tab in Commission and the user presses Right
- **THEN** "Object dictionary" is selected and its panel shows

