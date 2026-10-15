## ADDED Requirements

### Requirement: Workspaces
With a config open, the header SHALL have a **Configure | Commission** switch:
- **Configure** SHALL show the config pages.
- **Commission** SHALL show the live view of the runtime as its **Nodes** tab, with the node list and node pages of the online view.

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

A tool tab SHALL use the full page width, with no side bar and no bottom panel. The side bar SHALL list no tools. The tabs SHALL follow the page's tab pattern (see "Keyboard access and announcements").

#### Scenario: Trace from a node page
- **WHEN** the user is on node 5's page in Configure and picks the Trace tab
- **THEN** the trace view fills the width of the page, and picking Network returns to node 5's page

#### Scenario: Tools in Commission a device
- **WHEN** the user opens Commission a device
- **THEN** the tabs are Nodes, Trace and Frame lab

### Requirement: Connection bar
A connection bar SHALL show under the header: always in Commission, and in Configure while connected. It SHALL show:
- the target;
- for an adapter, the bit rate and how it was confirmed;
- for a runtime, the path and round trip, and the network picker when the runtime has several networks;
- the bus state and the frame and error frame counts;
- another master with what was seen, when one is seen;
- whether changes are allowed;
- **Connect…** while not connected, and **Disconnect** while connected.

While connecting it SHALL show the step of the bit rate check and **Cancel**. When a connection ends or stops answering it SHALL show the reason or the age of the last data. Colour SHALL be used only for a fault: an ended or lost connection, error passive or bus-off, a round trip above 100 ms, or another master. State changes SHALL be announced politely, and an ended connection as an alert.

#### Scenario: Visible on every page
- **WHEN** the user is connected to an adapter at 500 kbit/s and opens Frame lab
- **THEN** the bar still shows the adapter, "500 kbit/s" with how it was confirmed, the bus state and Disconnect

#### Scenario: Ended connection
- **WHEN** the adapter goes bus-off while the user is on a node's Object dictionary tab
- **THEN** the bar turns to the fault colour, says the connection ended on bus-off, offers Connect…, and a screen reader announces it

#### Scenario: Neutral when well
- **WHEN** the connection is up with no errors and no other master
- **THEN** the bar uses no warning or error colour

### Requirement: Connect panel
**Connect…** SHALL open one connect panel. It SHALL be the only place to connect.

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

The last target and bit rate SHALL be kept in the configurator's settings on this PC, never in a project. Entering Commission while not connected SHALL connect to the runtime at once when this PC has its host and a matching token and the user did not disconnect; otherwise it SHALL open the panel, once per folder or commissioning session. A USB adapter SHALL always need Connect, because of the bit rate check.

#### Scenario: Wrong bit rate refused
- **WHEN** the bus runs at 500 kbit/s and the user connects at 1000 kbit/s in the panel
- **THEN** the panel stays open, says the bus does not run at 1000 kbit/s, and the user can pick 500 kbit/s and connect without replugging the adapter

#### Scenario: Runtime needs a token
- **WHEN** the user picks a found runtime and this PC has no token for the config
- **THEN** the panel asks for the token, accepts it only if it matches the config's verifier, and connects

#### Scenario: Disconnect frees the adapter
- **WHEN** the user presses Disconnect in the bar while connected to an adapter
- **THEN** the adapter is closed, the scan, PDO test, SYNC, send jobs and trace recording on it stop, and `canworks-diag --adapter` can open the same adapter

### Requirement: One connection for every view
The Commission pages, Trace recording and its Send panel, the Simulation view's **Runtime** target and the PDO test SHALL use the connection in the connection bar. None of them SHALL have its own connect form, host field or adapter field. Without a connection, each SHALL say that it needs one, with a button that opens the connect panel. The Simulation view's **Standalone simulator** address and token SHALL stay in the Simulation view, because they reach `canworks-sim`'s control channel, not a bus.

#### Scenario: Trace uses the open connection
- **WHEN** the user connected to a runtime in Commission and opens Trace in Configure and presses Start
- **THEN** recording starts through that runtime without asking for a host or token

#### Scenario: Trace without a connection
- **WHEN** nothing is connected and the user opens Trace
- **THEN** files can be opened and viewed, and Start is replaced by a note that recording needs a connection with a Connect… button

### Requirement: Allow changes in the connection bar
On an adapter connection, **Allow changes** SHALL be a switch in the connection bar. It SHALL be off for every new connection, SHALL ask before switching on, and SHALL apply to the open connection without reconnecting. On a runtime connection, the bar SHALL show the runtime's own setting as read-only text with a lock and SHALL say that it is set in Configure → Bus and master → Online access and takes effect after an upload.

#### Scenario: Switch on an open adapter connection
- **WHEN** the user is connected read-only to an adapter and switches Allow changes on and confirms
- **THEN** write controls on every page are enabled without reconnecting, and no "another master" message appears

#### Scenario: Runtime decides
- **WHEN** the user is connected to a runtime whose config has allow changes off
- **THEN** the bar shows "Read-only (runtime setting)" with no switch

### Requirement: Jobs in the status bar
A status bar at the bottom of the page SHALL list the running jobs of the session:
- scan;
- LSS find;
- Read all;
- back up, compare, restore and write configuration;
- trace recording;
- PDO test and SYNC;
- cyclic send jobs.

Each SHALL show a short label and its progress on every page and tool tab, and every job that can be stopped SHALL have **Cancel**. LSS find, which ends by itself within about 15 seconds, SHALL be listed without Cancel. More than two jobs SHALL collapse into a count that opens the list. Cancel of a restore or write configuration SHALL ask first, with keeping it running as the default. While connected through a connection that counts frames (a USB adapter), the status bar SHALL also show the frame rate and the estimated bus load.

#### Scenario: Cancel a scan from another page
- **WHEN** a scan is running and the user has opened Frame lab
- **THEN** the status bar shows the scan's progress, and Cancel there stops the scan within a second with the devices found so far kept

#### Scenario: LSS find in the status bar
- **WHEN** LSS find is searching
- **THEN** the status bar lists it with the seconds it has run and no Cancel

#### Scenario: Cancel of a restore asks
- **WHEN** a restore of node 5 is running and the user presses its Cancel in the status bar
- **THEN** a dialog asks first, with keeping it running as the focused default

### Requirement: Bottom panel
The page SHALL have a collapsible panel under the page, which stays at the bottom of the window while the page scrolls; whether Problems is open in Configure SHALL be kept on this PC. Its contents SHALL depend on the workspace:
- **Configure:** a **Problems** tab, with Allow overlap.
- **Commission a device:** a **Log** tab with the commissioning log and **Save log**.
- **Commission with a config:** the **Problems** tab, collapsed.

Each tab title SHALL carry its count. There SHALL be no right-hand Problems column.

#### Scenario: Problems under the page
- **WHEN** the config has 4 errors in Configure
- **THEN** the panel's tab reads "Problems 4", the page uses the full width beside the side bar, and clicking a problem goes to its field

#### Scenario: Log while commissioning
- **WHEN** the user gave a device node ID 12 by LSS in Commission a device
- **THEN** the Log tab reads "Log 1" and Save log downloads the log

## MODIFIED Requirements

### Requirement: Header menus
The header SHALL show, left to right:
- the title;
- the workspace switch (see "Workspaces");
- the config's folder name with an unsaved mark;
- a settings menu with the theme choice;
- Reload from disk;
- Close;
- a Project menu (Move into project…, New editor project…; standalone mode only);
- an Export menu (All DCFs, This node's DCF, DBC with its SDO-frames choice, Documentation);
- Save as the only primary button.

The tool tabs SHALL be on a row under it. Menus SHALL open on click or Enter, close on Escape or a click elsewhere, and SHALL be navigable with the arrow keys. The header SHALL fit on one line at 1000 px. In Commission a device the header SHALL show only the title, the settings menu and Close.

#### Scenario: Export a DBC from the menu
- **WHEN** the user opens Export, picks "SDO: configured objects" and clicks DBC
- **THEN** the DBC file downloads as before and the menu closes

#### Scenario: One line
- **WHEN** the window is 1000 px wide in standalone mode
- **THEN** the header's actions are on one line

#### Scenario: Theme from the settings menu
- **WHEN** the user opens the settings menu and picks Dark
- **THEN** the page turns dark and the choice is kept in `ui.json`

### Requirement: Narrow window layout
Below 1000 px the node and view list SHALL become a compact bar at the top. The bottom panel SHALL stay, with its tab title showing the problem count, so the problems stay in view without a separate strip. A node's error count SHALL stay next to the node's name.

#### Scenario: Problems at 900 px
- **WHEN** the window is 900 px wide and the config has 4 errors
- **THEN** the bottom panel's tab reads "Problems 4" without scrolling, and opening it lists them

### Requirement: Trace view
The Trace tool tab SHALL work without a connection for opening, viewing and exporting trace files. Recording and the Send panel SHALL use the connection in the connection bar: a runtime with a config, the adapter in Commission a device. Without a connection, the view SHALL say that recording needs one and offer Connect…, which opens the connect panel. The view SHALL offer:
- start and stop, capture filters, error frames and clear;
- "Save to traces folder" (on this PC), open, and "Download" (a file in the chosen format), the two format choices labelled apart;
- a scrolling decoded trace and a per-identifier table;
- display filters by node, frame kind (NMT, SYNC, EMCY, heartbeat, SDO, PDO, LSS, error, other), identifier range and text;
- the graph and trigger settings, and the statistics.

Times SHALL be shown relative to the trace start or as UTC clock time. When the runtime's plugin does not know the trace operations, the view SHALL say that the plugin is too old for traces. Clear and Start SHALL say that the current recording is lost unless it was saved or downloaded, with Cancel as the default. Closing the page or the folder with an unsaved recording SHALL ask first. The frame list SHALL move its selection with the arrow keys, Home, End, Page Up and Page Down. The view's tabs SHALL follow the page's tab pattern (see "Keyboard access and announcements"). A running recording SHALL be listed in the status bar with its frame count and Cancel (stop).

#### Scenario: Start a trace
- **WHEN** the page is connected to a runtime and the user opens Trace and presses Start
- **THEN** decoded frames appear, the statistics update while the bus runs, and the status bar lists the recording

#### Scenario: Record while commissioning
- **WHEN** the user is connected to an adapter in Commission a device and presses Start in Trace
- **THEN** the adapter's frames are recorded and decoded, and no runtime host or token is asked for

#### Scenario: Filter display
- **WHEN** the user shows only node 23 and frame kind SDO
- **THEN** the trace lists only SDO requests and responses of node 23, and recording of other frames continues

#### Scenario: Old plugin
- **WHEN** the runtime's plugin answers the trace start as an unknown operation
- **THEN** the view says the plugin on the runtime is too old for traces and how to update it

#### Scenario: Open a file without a runtime
- **WHEN** nothing is connected and the user opens a candump log file in the Trace view
- **THEN** the frames are shown decoded and can be graphed and exported, and recording offers Connect…

#### Scenario: Works offline
- **WHEN** the PC has no internet access
- **THEN** the Trace view and its graphs load and work

#### Scenario: Clear asks
- **WHEN** a recording of 3,000 frames has not been saved and the user clicks Clear
- **THEN** a dialog says the 3,000 frames are lost unless saved or downloaded, Cancel is the default, and Enter keeps the recording

### Requirement: Simulation view
The configurator SHALL have a **Simulation** tool tab, in both workspaces of a config. It connects either to the runtime's simulated devices, through the connection in the connection bar, or to a standalone simulator by address and token entered in the view. It shows, per simulated device, whether it runs on a simulated or a real network, its NMT and power state, injected faults and the objects it carries in PDOs with live values, refreshed at least twice a second.

A user SHALL be able to:
- set and override values (switches for BOOLEAN and bits, sliders between the EDS limits for numbers);
- give and edit value sources and expressions, with checking as they type;
- inject and clear every fault the simulator offers from buttons;
- add extra devices.

Changes made here SHALL be saveable to `simulation.json`. With several networks, the view SHALL show and edit the network chosen in its network picker, and saving SHALL write that network's section of a version 2 file, keeping the other sections. A version 1 file of a several-network config SHALL be offered for conversion to version 2 before the first save. Without **Allow changes** the view SHALL be read-only and say why. With the Runtime target and no connection, the view SHALL offer Connect…, which opens the connect panel, and the simulation file SHALL stay editable.

#### Scenario: Move a sensor value by hand
- **WHEN** a user drags the slider of node 5's 0x7130:1 to 900 in the Simulation view
- **THEN** the simulated device holds 900, the PLC sees it in the mapped input, and the slider shows an override that **Release** removes

#### Scenario: Save behaviour
- **WHEN** a user gives 0x6401:1 a sine in the view and presses **Save to simulation file**
- **THEN** `canworks/simulation.json` has that source and the next simulated start uses it

#### Scenario: Save one network's section
- **WHEN** the config has networks `io` and `motion`, the picker shows `motion`, and the user saves a drive setting for node 4
- **THEN** `simulation.json` is version 2, its `motion` section has the setting and its `io` section is unchanged

#### Scenario: Runtime target uses the bar's connection
- **WHEN** the page is connected to the local simulator runtime and the user opens Simulation with the Runtime target
- **THEN** live values show without asking for a host or token

### Requirement: Commission a device without a config
The configurator's start page SHALL offer "Commission a device". It opens the Commission workspace with no project or config, connected only through a USB adapter on this PC (see "Connect panel"). Its tabs SHALL be **Nodes** (see "Nodes in commissioning"), **Trace** and **Frame lab**, and its bottom panel SHALL hold the commissioning log.

The object dictionary view SHALL take the EDS from the scan match in the EDS library, from Add node from EDS…, or picked by the user. LSS, Parameters (backup, compare, restore, store, write configuration, restore defaults) and the PDO test SHALL be on the Nodes tab and each node's page. "Add as node" SHALL NOT be offered. Instead, each node's page SHALL offer "Add to a config…". It picks a project or standalone config folder and opens it with the device added as an unsaved node: node ID, EDS imported, serial number, and LSS assignment ticked when the node ID was set by LSS in this session and the device's EDS says `LSS_Supported=1`. With an EDS without LSS, the node SHALL be added without it and the page SHALL say why.

There SHALL be no Steps panel and no bit rate detection.

In this mode the page SHALL show no config editing:
- no workspace switch;
- no Project or Export menu;
- no Save;
- no Problems.

Nothing SHALL suggest a config is being edited, and no text SHALL link to a page the mode does not show.

#### Scenario: New device on the desk
- **WHEN** the user opens "Commission a device", connects to an adapter at 250 kbit/s with "Allow changes" on, finds an unconfigured device with LSS on the Nodes tab and gives it node ID 12
- **THEN** node 12 is listed on the Nodes tab, and nothing was stored on the device unless the user ticked "store"

#### Scenario: Nothing to save
- **WHEN** the user opens "Commission a device"
- **THEN** the header shows the title, the settings menu and Close only, the tabs are Nodes, Trace and Frame lab, the connection bar shows "Not connected" with Connect…, and no problem is reported

#### Scenario: Guided commissioning
- **WHEN** the user connects at the bus's bit rate, gives the device node ID 12 by LSS on the Nodes tab, writes a configuration from a DCF on node 12's page and backs it up
- **THEN** each action is in the Log tab of the bottom panel with its result, and the page shows no Steps panel

#### Scenario: Runtime choice not offered
- **WHEN** the user opens "Commission a device" on a PC whose configurator last connected to a runtime
- **THEN** the connect panel shows the USB adapter form, with no Runtime choice and no "Online access is off for this config" text

#### Scenario: Carry the device into a config
- **WHEN** the user presses "Add to a config…" on node 12's page after setting node ID 12 by LSS and picks a standalone config folder
- **THEN** that config opens with node 12 added as an unsaved node with the device's EDS, serial number and LSS assignment ticked

### Requirement: Commissioning log
In Commission a device, the configurator SHALL record every change made through the page in this session:
- SDO write;
- NMT;
- LSS set ID, set bit rate and store;
- write configuration;
- restore defaults;
- store.

Each entry SHALL have the UTC time, node, what was done and the result. The log SHALL be shown in the bottom panel's Log tab with its count. "Save log" there SHALL download `node<N>-commissioning-<time>.txt` with the device identity and EDS name at the top. The log SHALL NOT contain host names or tokens and SHALL NOT be written to any project.

The log SHALL belong to the commissioning session. Leaving Commission a device (Close, or "Add to a config…") with entries not saved SHALL ask whether to save the log first. The log SHALL then be cleared. With a config open, no commissioning log SHALL be recorded or shown, in either workspace.

#### Scenario: Save the record
- **WHEN** the user gave the device node ID 12, wrote a configuration and stored it, then pressed Save log
- **THEN** the file lists those three changes in order with their results

#### Scenario: Not carried into the config
- **WHEN** the user made two changes while commissioning, pressed "Add to a config…" and chose not to save the log
- **THEN** the config opens with no commissioning log shown anywhere, and returning to Commission a device starts an empty log

### Requirement: Nodes in commissioning
In Commission a device, the "Nodes" tab SHALL list the devices of this session: those heard (heartbeat or boot-up), found by a scan, given a node ID by LSS, or added with **Add node from EDS…**. Each SHALL show its node ID, name, NMT state, time since last heard and last EMCY. **Add node from EDS…** SHALL take a node ID and an EDS file and add the device to the list with that EDS, kept in this page only.

The tab SHALL have:
- **Scan the bus**, with progress on the tab and in the status bar, and **Cancel**, which stops the scan and keeps the devices found so far;
- the devices without a node ID panel (LSS find, Set node ID, Set bit rate).

Clicking a device SHALL open its page with the object dictionary, Parameters, PDO test and notes tabs, and **Add to a config…**. Before a connection exists, the tab SHALL say that it needs a connection, with a button that opens the connect panel.

#### Scenario: Device that does not answer the scan
- **WHEN** a device in STOPPED state is on the bus and the user adds node 23 with its EDS through Add node from EDS…
- **THEN** node 23 is listed with that EDS, and its object dictionary and Parameters tabs use it

#### Scenario: Cancel a long scan
- **WHEN** a scan is running and the user presses Cancel
- **THEN** the scan stops within a second and the devices found so far stay listed

#### Scenario: Not connected yet
- **WHEN** the user opens the Nodes tab before connecting and closes the connect panel
- **THEN** the tab says it needs a connection and its button opens the connect panel

### Requirement: Discovered and remembered runtimes in the connect box
With a config, the connect panel SHALL list runtimes found by discovery and remembered runtimes by name, next to typing an address. Choosing one SHALL connect by the automatic path choice; the user SHALL never have to choose between the local network and the link.

#### Scenario: Pick a discovered runtime
- **WHEN** the connect panel opens on a LAN with one advertised runtime
- **THEN** the runtime is listed by name and address, and choosing it and entering the token connects

#### Scenario: Same runtime from home
- **WHEN** the user picks the same runtime later from another network and the PC is paired and internet access is on
- **THEN** the connection is made with the same steps and the connection bar shows `internet direct` or `internet relayed`

### Requirement: Path and round trip in the online view
On a runtime connection, the connection bar SHALL show the path (`LAN`, `internet direct`, `internet relayed`) and the measured round trip, amber above 100 ms and red above 300 ms. LSS fast scan and a PDO test with a SYNC period SHALL ask for confirmation when the path is relayed or the round trip is above 100 ms.

#### Scenario: LSS on a relayed path
- **WHEN** the path is `internet relayed` and the user starts an LSS fast scan
- **THEN** a confirmation explains that the scan runs on the runtime but results and stop commands arrive late, and nothing is sent until the user confirms

#### Scenario: Round trip in the bar
- **WHEN** the runtime answers in 150 ms over `internet direct`
- **THEN** the connection bar shows "internet direct · 150 ms" in amber

### Requirement: Network picker in online and trace views
When the runtime reports more than one network, the connection bar SHALL have a network picker. The Commission pages, Trace and Simulation SHALL show and act on the picked network only. The picker SHALL start on the network whose tab is open in Configure.

#### Scenario: Online view of the second network
- **WHEN** the runtime runs `io` and `drives` and the user picks `drives` in the connection bar
- **THEN** the Commission workspace shows `drives`' bus state and nodes, and SDO, NMT, parameter and object dictionary actions go to `drives`

## REMOVED Requirements

### Requirement: Bus and master in commissioning
**Reason**: Its parts move to the shell: the adapter form to the connect panel, the check result, bus state, counters, other master, Allow changes and Disconnect to the connection bar, and the log and Save log to the bottom panel's Log tab.
**Migration**: Use **Connect…** in the connection bar to connect, the bar for state, Allow changes and Disconnect, and the Log tab to save the log. The behaviour is unchanged and is specified in "Connect panel", "Connection bar", "Allow changes in the connection bar" and "Commissioning log".
