## ADDED Requirements

### Requirement: Bus and master in commissioning
In Commission a device, the "Bus and master" tab SHALL hold everything about the connection:
- the adapter (picked from the found adapters, with Refresh, or typed);
- the bit rate (picked by the user, with no detection);
- "Device's node ID, to check the bit rate", shown for adapters that cannot report a sent frame;
- Allow changes;
- Connect, and Disconnect while connected;
- the bit rate check result and how it was confirmed;
- the bus state and error counters when the adapter reports them;
- another master with what was seen and since when;
- the commissioning log count with Save log.

A refused bit rate check SHALL show the backend's reason in the tab and leave the form filled in. A connection that ends (see `canopen-local-bus`, "Bus errors end the connection") SHALL show its reason there. Disconnect SHALL close the adapter and stop the scan, PDO test, SYNC, raw send jobs and trace recording that use it. Allow changes SHALL take effect on the open connection without reconnecting, and SHALL start off for every new connection. The adapter and bit rate SHALL be kept in the configurator's settings on this PC, never in a project.

#### Scenario: Wrong bit rate refused
- **WHEN** the bus runs at 500 kbit/s and the user connects at 1000 kbit/s
- **THEN** the tab says the bus does not run at 1000 kbit/s, nothing is shown as connected, and the user can pick 500 kbit/s and connect again without replugging the adapter

#### Scenario: Disconnect
- **WHEN** the user is connected and presses Disconnect
- **THEN** the adapter is closed, the tab shows the connect form, and `canworks-diag --adapter` can open the same adapter

#### Scenario: Allow changes on an open connection
- **WHEN** the user is connected read-only and ticks Allow changes
- **THEN** write controls are enabled without reconnecting, and no "another master" message appears

### Requirement: Nodes in commissioning
In Commission a device, the "Nodes" tab SHALL list the devices of this session: those heard (heartbeat or boot-up), found by a scan, given a node ID by LSS, or added with **Add node from EDS…**. Each SHALL show its node ID, name, NMT state, time since last heard and last EMCY. **Add node from EDS…** SHALL take a node ID and an EDS file and add the device to the list with that EDS, kept in this page only. The tab SHALL have **Scan the bus** with progress and **Cancel**, which stops the scan and keeps the devices found so far. It SHALL also have the devices without a node ID panel (LSS find, Set node ID, Set bit rate). Clicking a device SHALL open its page with the object dictionary, Parameters, PDO test and notes tabs, and **Add to a config…**. Before a connection exists, the tab SHALL say that Bus and master connects first, with a link to it.

#### Scenario: Device that does not answer the scan
- **WHEN** a device in STOPPED state is on the bus and the user adds node 23 with its EDS through Add node from EDS…
- **THEN** node 23 is listed with that EDS, and its object dictionary and Parameters tabs use it

#### Scenario: Cancel a long scan
- **WHEN** a scan is running and the user presses Cancel
- **THEN** the scan stops within a second and the devices found so far stay listed

### Requirement: Network picker in online and trace views
The online view and the trace view SHALL each have a network picker when the runtime reports more than one network. Each SHALL show and act on the picked network only. The picker SHALL start on the network whose tab is open.

#### Scenario: Online view of the second network
- **WHEN** the runtime runs `io` and `drives` and the user picks `drives` in the online view
- **THEN** the view shows `drives`' bus state and nodes, and SDO, NMT, parameter and object dictionary actions go to `drives`

## MODIFIED Requirements

### Requirement: Commission a device without a config
The configurator's start page SHALL offer "Commission a device". It opens USB adapter commissioning without any project or config. The side bar SHALL have four items:
- **Bus and master** (see "Bus and master in commissioning");
- **Nodes** (see "Nodes in commissioning");
- **Trace**;
- **Frame lab**.

The object dictionary view SHALL take the EDS from the scan match in the EDS library, from Add node from EDS…, or picked by the user. LSS, Parameters (backup, compare, restore, store, write configuration, restore defaults) and the PDO test SHALL be on the Nodes tab and each node's page. "Add as node" SHALL NOT be offered. Instead, each node's page SHALL offer "Add to a config…". It picks a project or standalone config folder and opens it with the device added as an unsaved node: node ID, EDS imported, serial number, and LSS assignment ticked when the node ID was set by LSS in this session and the device's EDS says `LSS_Supported=1`. With an EDS without LSS, the node SHALL be added without it and the page SHALL say why.

There SHALL be no Steps panel and no bit rate detection.

In this mode the page SHALL show no config editing: no Project or Export menu, no Save and no Problems pane. Nothing SHALL suggest a config is being edited. This mode SHALL connect only through a USB adapter on this PC, and no text in it SHALL link to a page the mode does not show.

#### Scenario: New device on the desk
- **WHEN** the user opens "Commission a device", connects to an adapter at 250 kbit/s with "Allow changes" on, finds an unconfigured device with LSS on the Nodes tab and gives it node ID 12
- **THEN** node 12 is listed on the Nodes tab, and nothing was stored on the device unless the user ticked "store"

#### Scenario: Nothing to save
- **WHEN** the user opens "Commission a device"
- **THEN** the header shows the mode badge, the theme choice and Close only, the side bar lists Bus and master, Nodes, Trace and Frame lab, and no problem is reported

#### Scenario: Guided commissioning
- **WHEN** the user connects at the bus's bit rate, gives the device node ID 12 by LSS on the Nodes tab, writes a configuration from a DCF on node 12's page and backs it up
- **THEN** each action is in the commissioning log with its result, and the page shows no Steps panel

#### Scenario: Runtime choice not offered
- **WHEN** the user opens "Commission a device" on a PC whose configurator last connected to a runtime
- **THEN** Bus and master shows the USB adapter form, with no Runtime choice and no "Online access is off for this config" text

#### Scenario: Carry the device into a config
- **WHEN** the user presses "Add to a config…" on node 12's page after setting node ID 12 by LSS and picks a standalone config folder
- **THEN** that config opens with node 12 added as an unsaved node with the device's EDS, serial number and LSS assignment ticked

### Requirement: Trace view
The side bar SHALL have a Trace view. Opening, viewing and exporting trace files SHALL work without a connection. Recording SHALL need a connection: in config mode, online access to a runtime; in Commission a device, the open adapter connection, with no runtime host or token. Without one, the hint SHALL name what that mode needs. The view SHALL offer:
- start and stop, capture filters, error frames and clear;
- "Save to traces folder" (on this PC), open, and "Download" (a file in the chosen format), the two format choices labelled apart;
- a scrolling decoded trace and a per-identifier table;
- display filters by node, frame kind (NMT, SYNC, EMCY, heartbeat, SDO, PDO, LSS, error, other), identifier range and text;
- the graph and trigger settings, and the statistics.

Times SHALL be shown relative to the trace start or as UTC clock time. When the runtime's plugin does not know the trace operations, the view SHALL say that the plugin is too old for traces. Clear and Start SHALL say that the current recording is lost unless it was saved or downloaded, with Cancel as the default. Closing the page or the folder with an unsaved recording SHALL ask first. The frame list SHALL move its selection with the arrow keys, Home, End, Page Up and Page Down. The view's tabs SHALL follow the page's tab pattern (see "Keyboard access and announcements").

#### Scenario: Start a trace
- **WHEN** online access is set up and the user opens Trace and presses Start
- **THEN** decoded frames appear and the statistics update while the bus runs

#### Scenario: Record while commissioning
- **WHEN** the user is connected in Commission a device and presses Start in Trace
- **THEN** the adapter's frames are recorded and decoded, and no runtime host or token is asked for

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

### Requirement: Send frames from the Trace view
The Trace view SHALL have a Send panel for the picked network. It SHALL have:
- the identifier (hex), extended and remote options, and a DLC for remote frames;
- up to 8 data bytes;
- single or cyclic sending, with a period and an optional count.

It SHALL send with `send_frame` and stop jobs with `send_frame_stop`, through online access in config mode or the adapter connection in Commission a device. It SHALL list the running cyclic jobs with their sent counts and a Stop for each, and list the last 20 frames sent. A frame selected in the trace SHALL be offered as "Send this frame", filling the panel. Without Allow changes, the panel SHALL be disabled and say why. When a frame is refused because `force` is needed, the configurator SHALL show the reason in a confirmation and resend with `force` only when the user confirms. Leaving the Trace view or closing the page SHALL stop the page's cyclic jobs.

#### Scenario: Single frame while recording
- **WHEN** a trace is recording and the user sends 0x60A with eight data bytes
- **THEN** the frame appears in the trace once, as Tx, and in the panel's sent list

#### Scenario: Force needs confirmation
- **WHEN** the user sends on 0x205, which is RPDO1 of node 5
- **THEN** a confirmation quotes "0x205 is RPDO1 of node 5" and nothing is sent unless the user confirms

#### Scenario: No changes allowed
- **WHEN** the config's online access has `allow_changes` off
- **THEN** the Send panel is disabled and says that sending needs Allow changes

### Requirement: CiA 402 axis setting
The node settings SHALL offer a "CiA 402 axis" switch with the three scaling fields, and a "Cyclic synchronous" switch with an optional interpolation period. Together they write the node's `axis` object. The axis checks' errors and warnings SHALL show with the node. The switch SHALL be enabled only when the node's EDS has the controlword 0x6040 and the statusword 0x6041. Otherwise it SHALL be disabled with "This device's EDS has no controlword (0x6040) and statusword (0x6041), so it cannot be a CiA 402 axis." The exception is a node that already has `axis`: its switch SHALL stay enabled so it can be switched off. The page SHALL still say when the EDS does not report device profile 402 in 0x1000. Turning it on SHALL require a status bit and SHALL suggest one when the node has none.

#### Scenario: Turn on
- **WHEN** the user turns on "CiA 402 axis" for node `drive`, whose EDS has 0x6040 and 0x6041 and which has a status bit, and saves
- **THEN** the saved config has `"axis": {}` on node `drive` (scaling left at the defaults is not written)

#### Scenario: Not a drive
- **WHEN** the user opens a digital I/O node whose EDS has no 0x6040 or 0x6041
- **THEN** the "Use as a CiA 402 axis" switch is disabled and says why

#### Scenario: Error shown
- **WHEN** the axis node does not map 0x6041
- **THEN** the node shows the error and the config is not saved

#### Scenario: Cyclic on a timer network
- **WHEN** the user turns on "Cyclic synchronous" for axis `drive` on a network whose SYNC comes from the master's timer
- **THEN** the node shows the error that a cyclic axis needs SYNC from the PLC cycle, with a button that sets `"sync_source": "plc_cycle"` on that network (removing `sync_period_us`), and the config is not saved until it is fixed

### Requirement: Commissioning log
In Commission a device, the configurator SHALL record every change made through the page in this session: SDO write, NMT, LSS set ID, set bit rate and store, write configuration, restore defaults, and store. Each entry SHALL have the UTC time, node, what was done and the result. "Save log" SHALL download `node<N>-commissioning-<time>.txt` with the device identity and EDS name at the top. The log SHALL NOT contain host names or tokens and SHALL NOT be written to any project. The log SHALL belong to the commissioning session. Leaving Commission a device (Close, or "Add to a config…") with entries not saved SHALL ask whether to save the log first. The log SHALL then be cleared. In config mode, no commissioning log SHALL be recorded or shown.

#### Scenario: Save the record
- **WHEN** the user gave the device node ID 12, wrote a configuration and stored it, then pressed Save log
- **THEN** the file lists those three changes in order with their results

#### Scenario: Not carried into the config
- **WHEN** the user made two changes while commissioning, pressed "Add to a config…" and chose not to save the log
- **THEN** the config opens with no commissioning log shown anywhere, and returning to Commission a device starts an empty log

### Requirement: PDO test tab
In Commission a device, each node SHALL have a "PDO test" tab. It SHALL load the node's PDO layout from the device, or from the configuration the user picks, and show:
- TPDOs with live decoded values, periods and counts;
- RPDOs with an input per entry and Send.

It SHALL offer NMT Start for the node, and SYNC with a period (off by default). Every control SHALL be disabled without Allow changes and say why. When another master is detected, the page SHALL ask before using `force`. Leaving the tab or closing the page SHALL stop the test and the SYNC. In config mode the tab SHALL NOT be shown, because the PLC runs the PDOs there.

#### Scenario: Set an output
- **WHEN** the user types 15 in RPDO1's 0x6200:01 input and presses Send
- **THEN** the frame is sent and the RPDO's sent count goes up by one

### Requirement: Write configuration dialog
A node's Parameters tab SHALL have "Write configuration…", enabled only with Allow changes. It SHALL take a DCF file or a node of a config folder (the open config's own node by default when the target is not a runtime that configures it). It SHALL show the plan from `canopen-device-commissioning`:
- the writes, with source value, device value, and differs or same;
- PDO sequences grouped, and communication writes marked;
- left-out entries with reasons;
- identity and node ID checks.

It SHALL write only after the user confirms. "Hold in PRE-OPERATIONAL while writing" SHALL start ticked. "Restore defaults first" and "Store on device afterwards" SHALL start unticked every time the dialog opens. It SHALL run in the configurator like restore, with progress and Cancel, and show the result with the read-back verdict. "Verify" in the same dialog SHALL compare without writing.

#### Scenario: Plan before writing
- **WHEN** the user picks node5.dcf in Write configuration
- **THEN** the dialog lists the planned writes with both values, writes nothing until the user confirms, and both store and restore-defaults ticks are off

### Requirement: Unconfigured devices in the online view
When the connection allows changes, the runtime's online view in config mode and the Nodes tab in Commission a device SHALL offer an "Unconfigured devices" panel. It SHALL find a device without a node ID and show:
- its vendor ID, with the vendor name when an EDS gives it;
- its product code, revision and serial number;
- a matching EDS when the project's `canworks/` folder or the EDS library has one.

It SHALL offer "Set node ID" and "Set bit rate" for the device. Both dialogs SHALL have a "Store in the device" checkbox that is unticked each time the dialog opens.

"Set node ID" SHALL suggest the lowest node ID that is neither configured nor the master's. In config mode, after success, it SHALL offer to add the device as a node with that ID and EDS, with `serial_number` and `lss.assign` set. "Set bit rate" SHALL say before sending that the device switches after its next power cycle and that the adapter bit rate must be changed to match. Without changes allowed, the panel SHALL be shown disabled with the reason.

When the matching EDS does not say `LSS_Supported=1`, the device SHALL be added without `lss.assign`, and the page SHALL say that its EDS has no LSS, so the node gets no LSS assignment.

#### Scenario: Commission a new sensor
- **WHEN** the user finds a device without node ID, sets node ID 40 with "Store in the device" ticked, and accepts adding it as a node
- **THEN** the runtime sets and stores node ID 40, and the project gets node 40 with the matching EDS, the device's serial number and `"lss": {"assign": true}`, unsaved until the user saves

#### Scenario: Store unticked by default
- **WHEN** the user opens "Set node ID" a second time after storing once
- **THEN** the "Store in the device" checkbox is unticked

## REMOVED Requirements

### Requirement: Scan the bus and add nodes
**Reason**: Toni: Scan the bus is not needed in the configurator. Scanning is part of Commission a device.
**Migration**: Add nodes with "Add node from EDS…", or commission the device and use "Add to a config…".

### Requirement: Use a scanned device for a node
**Reason**: It lived on the configurator's Scan page, which is removed.
**Migration**: Set a node's `serial_number` and LSS assignment on the node page.

### Requirement: USB adapter as online target
**Reason**: Toni: Runtime > Online > Connect should not offer a USB adapter. USB adapter work is done in Commission a device.
**Migration**: Use Commission a device for a USB adapter on this PC.

### Requirement: Online pages on a USB adapter
**Reason**: The configurator has no USB adapter target. Commission a device covers these pages (see "Commission a device without a config", "Bus and master in commissioning" and "Nodes in commissioning").
**Migration**: None.

### Requirement: Detect the bit rate from the Scan page
**Reason**: There is no Scan page and no bit rate detection.
**Migration**: None.

### Requirement: Lone device in Detect
**Reason**: There is no bit rate detection.
**Migration**: None.

### Requirement: Lone-device sweep guarded by the server
**Reason**: There is no bit rate detection.
**Migration**: None.

### Requirement: Network picker in online, scan and trace views
**Reason**: Replaced by "Network picker in online and trace views", without the Scan page.
**Migration**: None.
