## MODIFIED Requirements

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

#### Scenario: One Connect button
- **WHEN** nothing is connected and the user opens Nodes, Simulation and Trace in turn, in either workspace of a config
- **THEN** each page shows exactly one Connect… button, the one in the connection bar, and each page's own text says what it needs a connection for

### Requirement: Connect panel
**Connect…** in the connection bar SHALL open one connect panel, and the panel SHALL be the only place to connect. No page SHALL have a connect form or a button that opens the panel.

The panel SHALL list first up to three recent connections of this PC of the kinds it offers, each connectable with one click. A recent adapter connection SHALL still run the bit rate check and SHALL start with Allow changes off. Recent connections SHALL be kept in the configurator's settings on this PC without tokens. The panel SHALL NOT open by itself on entering Commission.

In Commission a device the panel SHALL offer a USB adapter only:
- the found adapters with Refresh, or a typed target;
- the bit rate, picked by the user, with no detection and no default;
- "Device's node ID, to check the bit rate", for adapters that cannot report a sent frame;
- **Allow changes**, unticked;
- **Connect**.

A refused bit rate check SHALL keep the panel open with the reason and the form filled in.

With a config the panel SHALL offer two targets, **Runtime** (the default) and **Standalone simulator**:
- Runtime: the found and remembered runtimes, the host field and **Local simulator runtime**; the token prompt when this PC has no matching token; **Connect**;
- Standalone simulator: a running `canworks-sim` by address (`HOST[:PORT]`, port 7532 when not given) and its token when it was started with one, both kept on this PC per project folder; **Connect**.

When the config's online access is off, the Runtime target SHALL say so and link to Configure → Bus and master; the Standalone simulator target SHALL still work.

The last target (including Runtime or Standalone simulator) and bit rate SHALL be kept in the configurator's settings on this PC, never in a project.

#### Scenario: Wrong bit rate refused
- **WHEN** the bus runs at 500 kbit/s and the user connects at 1000 kbit/s in the panel
- **THEN** the panel stays open, says the bus does not run at 1000 kbit/s, and the user can pick 500 kbit/s and connect without replugging the adapter

#### Scenario: Runtime needs a token
- **WHEN** the user picks a found runtime and this PC has no token for the config
- **THEN** the panel asks for the token, accepts it only if it matches the config's verifier, and connects

#### Scenario: Disconnect frees the adapter
- **WHEN** the user presses Disconnect in the bar while connected to an adapter
- **THEN** the adapter is closed, the scan, PDO test, SYNC, send jobs and trace recording on it stop, and `canworks-diag --adapter` can open the same adapter

#### Scenario: Reconnect to the last adapter
- **WHEN** the user opens Commission a device on a PC that last connected to gs_usb:0 at 500 kbit/s and presses Connect… in the connection bar
- **THEN** the panel lists "gs_usb:0 at 500 kbit/s" first, and one click connects after the bit rate check with Allow changes off

#### Scenario: Standalone simulator
- **WHEN** the user picks Standalone simulator in the panel, enters 127.0.0.1:7532 and presses Connect
- **THEN** the panel closes, the connection bar shows the simulator's address and Disconnect, and Simulation shows its devices

### Requirement: One connection for every view
The Commission pages, Trace recording and its transmit list, the Simulation view and the PDO test SHALL use the connection in the connection bar. None of them SHALL have its own connect form, host, adapter, address or token field, or Connect button. Without a connection, each SHALL say in one line what it needs a connection for and that Connect… is in the connection bar. On a standalone simulator connection, the Nodes table, Trace recording and the PDO test SHALL say that they need a runtime connection.

#### Scenario: Trace uses the open connection
- **WHEN** the user connected to a runtime in Commission and opens Trace in Configure and presses Start
- **THEN** recording starts through that runtime without asking for a host or token

#### Scenario: Trace without a connection
- **WHEN** nothing is connected and the user opens Trace
- **THEN** files can be opened and viewed, and Start is replaced by a note that recording needs a connection made with Connect… in the connection bar, with no button of its own

### Requirement: Trace view
The Trace tool tab SHALL work without a connection for opening, viewing and exporting trace files. Recording and the transmit list SHALL use the connection in the connection bar, runtime or adapter, in every workspace. Without a connection, the view SHALL say that recording needs a connection and point to **Connect…** in the connection bar, with no connect button of its own. On a standalone simulator connection, the view SHALL say that recording needs a runtime or adapter connection. The trace header SHALL name the connection a recording uses (adapter and bit rate, or runtime) and the network.

The view SHALL offer (see "Trace toolbar and views"):
- start and stop, capture filters, error frames and clear;
- "Save to traces folder" (on this PC), open, and "Download" (a file in the chosen format), the two format choices labelled apart;
- the By identifier view and a scrolling decoded Chronological view;
- display filters by node, frame kind (NMT, SYNC, EMCY, heartbeat, SDO, PDO, LSS, error, other), identifier range, direction and text;
- the graph and trigger settings, and the statistics;
- the transmit list.

Times SHALL be shown relative to the trace start or as UTC clock time. When the runtime's plugin does not know the trace operations, the view SHALL say that the plugin is too old for traces.

**Connection end.** When the connection ends during a recording, the recording SHALL stop, keep its frames, add a marker with the reason, and the header SHALL say why it stopped.

**Start with frames.** Start with frames in the trace SHALL ask:
- **Continue this trace** (the default, adding a gap marker; only on the same network);
- **New trace**, saying that the current recording is lost unless it was saved or downloaded;
- **Cancel**.

Clear SHALL say that the current recording is lost unless it was saved or downloaded, with Cancel as the default. Closing the page or the folder with an unsaved recording SHALL ask first.

**Keyboard and jobs.** The Chronological and By identifier lists SHALL move their selection with the arrow keys, Home, End, Page Up and Page Down. The view's tabs SHALL follow the page's tab pattern (see "Keyboard access and announcements"). A running recording SHALL be listed in the status bar with its frame count and Cancel (stop).

#### Scenario: Start a trace
- **WHEN** the page is connected to a runtime and the user opens Trace and presses Start
- **THEN** the By identifier view fills with decoded rows, the statistics update while the bus runs, and the status bar lists the recording

#### Scenario: Record while commissioning
- **WHEN** the user is connected to an adapter in Commission a device and presses Start in Trace
- **THEN** the adapter's frames are recorded and decoded, the header names the adapter and its bit rate, and no runtime host or token is asked for

#### Scenario: Filter display
- **WHEN** the user shows only node 23 and frame kind SDO
- **THEN** both the By identifier and the Chronological view list only SDO requests and responses of node 23, and recording of other frames continues

#### Scenario: Old plugin
- **WHEN** the runtime's plugin answers the trace start as an unknown operation
- **THEN** the view says the plugin on the runtime is too old for traces and how to update it

#### Scenario: Open a file without a runtime
- **WHEN** nothing is connected and the user opens a candump log file in the Trace view
- **THEN** the frames are shown decoded and can be graphed and exported, and the view says that recording needs a connection made with Connect… in the connection bar, with no button of its own

#### Scenario: Works offline
- **WHEN** the PC has no internet access
- **THEN** the Trace view and its graphs load and work

#### Scenario: Clear asks
- **WHEN** a recording of 3,000 frames has not been saved and the user clicks Clear
- **THEN** a dialog says the 3,000 frames are lost unless saved or downloaded, Cancel is the default, and Enter keeps the recording

#### Scenario: Connection ends while recording
- **WHEN** an adapter connection ends with bus-off during a recording of 5,000 frames
- **THEN** the recording stops with the 5,000 frames kept, a marker reads "connection ended: bus-off", and the header says the recording stopped because the connection ended

#### Scenario: Continue after reconnecting
- **WHEN** the user reconnects to the same network and presses Start
- **THEN** a dialog offers Continue this trace as the default, and continuing appends new frames after a gap marker with the gap's length

### Requirement: Simulation view
The configurator SHALL have a **Simulation** tool tab, in both workspaces of a config. It shows the simulated devices of the connection in the connection bar: a runtime's, or a standalone simulator's. The view SHALL have no connect form, target choice, address or token field and no Connect button of its own, and no connection line that repeats what the connection bar says; it SHALL show only what is particular to simulation (nothing simulated on the runtime, read-only and why). It shows, per simulated device, whether it runs on a simulated or a real network, its NMT and power state, injected faults and the objects it carries in PDOs with live values, refreshed at least twice a second.

A user SHALL be able to:
- set and override values (switches for BOOLEAN and bits, sliders between the EDS limits for numbers);
- give and edit value sources and expressions, with checking as they type;
- inject and clear every fault the simulator offers from buttons;
- add extra devices.

Changes made here SHALL be saveable to `simulation.json`. With several networks, the view SHALL show and edit the network chosen in its network picker, and saving SHALL write that network's section of a version 2 file, keeping the other sections. A version 1 file of a several-network config SHALL be offered for conversion to version 2 before the first save. Without **Allow changes** the view SHALL be read-only and say why. Without a connection, the view SHALL say once that live values need a connection made with **Connect…** in the connection bar, and the simulation file and the scenarios SHALL stay editable.

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
- **WHEN** the page is connected to the local simulator runtime and the user opens Simulation
- **THEN** live values show without asking for a host or token

#### Scenario: Not connected
- **WHEN** nothing is connected and the user opens Simulation
- **THEN** the only Connect button on the page is the one in the connection bar, the view says once that live values need a connection, and the Simulation file and Scenarios tabs can be edited

#### Scenario: Standalone simulator from the connection bar
- **WHEN** the user connects to a standalone simulator at 127.0.0.1:7532 through Connect… in the connection bar and opens Simulation
- **THEN** the view shows that simulator's devices, and the connection bar names the simulator and offers Disconnect

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
- **THEN** the Nodes table says in place of its rows that it lists the devices once connected with Connect… in the connection bar, with no connect form or button of its own

## REMOVED Requirements

### Requirement: Connect from the Nodes table
**Reason**: The Nodes table's inline connect form was a second place to connect next to the connection bar.
**Migration**: Connect with Connect… in the connection bar; the recent connections, one click each, are listed first in the connect panel (see "Connect panel").
