## MODIFIED Requirements

### Requirement: Tool tabs
Next to the workspace's own tab (**Network** in Configure, **Nodes** in Commission), the header SHALL have tool tabs, each tool in one workspace only:
- **Variable declarations** (OpenPLC) and **Simulation file** in Configure of a config;
- **Simulation** (live values, faults and power, with a link that edits the simulation file in Configure), **Trace** and **Frame lab** in Commission;
- **Trace** and **Frame lab** in Commission a device.

A link to a tool of the other workspace SHALL switch to that workspace. A tool tab SHALL use the full page width, with no network tree, side bar or bottom panel. The network tree SHALL list no tools. The tabs SHALL follow the page's tab pattern (see "Keyboard access and announcements").

#### Scenario: Trace from a node page
- **WHEN** the user is on node 5's PDOs tab in Configure and follows a problem's link to the Trace
- **THEN** the page switches to Commission with the trace view filling the width of the page, and switching back to Configure returns to node 5's PDOs tab

#### Scenario: Tools in Commission a device
- **WHEN** the user opens Commission a device
- **THEN** the tabs are Nodes, Trace and Frame lab

#### Scenario: Tools of a config
- **WHEN** a config is open
- **THEN** Configure's tabs are Network, Variable declarations and Simulation file, and Commission's tabs are Nodes, Simulation, Trace and Frame lab

### Requirement: Network picker in online and trace views
The connection bar's network picker SHALL be the only network picker of the Commission pages, Trace, Simulation and Frame lab; no tab row or tool SHALL have its own. When the runtime reports more than one network, the picker SHALL list them; while not connected, it SHALL list the config's networks. The Commission pages, Trace and Simulation SHALL show and act on the picked network only. The picker SHALL start on the network of the entry selected in Configure's tree. In Commission, picking a tree entry on another network SHALL move the picker, and changing the picker SHALL select that network's tree entry.

#### Scenario: Online view of the second network
- **WHEN** the runtime runs `io` and `drives` and the user picks `drives` in the connection bar
- **THEN** the Commission workspace shows `drives`' bus state and nodes, the tree selects `drives`, and SDO, NMT, parameter and object dictionary actions go to `drives`

#### Scenario: One picker on Trace
- **WHEN** the virtual plant example is open, connected, on Trace
- **THEN** the only network control on the page is the connection bar's picker

### Requirement: Project target
A project SHALL have one target: "OpenPLC" (default), "Modbus bridge" or "CODESYS", chosen in a "Project target" field on the Project page (see "Network tree") and shown in the header, where the badge opens the Project page. No network's Bus page and no Modbus bridge page SHALL have the field. The target SHALL come from the config: a `bridge` object makes it Modbus bridge, a `codesys` object CODESYS.

#### Scenario: Target shown
- **WHEN** the user opens a config with a `codesys` object
- **THEN** the Project page's Project target field and the header show CODESYS

### Requirement: Online access settings
The tree's **Project** entry SHALL hold **Online access**, once for the whole config: it turns `master.diagnostics` on and off and edits its port, bind address and "allow changes" (off by default, with a warning that anyone with the token can then write parameters and stop nodes). Turning it on SHALL generate a random token of at least 128 bits, write only its SCRAM-SHA-256 verifier to `token_verifier`, and keep the token in the configurator's own settings on this PC for this project, never in the project folder. The page SHALL let the user copy the token, enter an existing token (for a project set up on another PC, checked against `token_verifier`), and generate a new one. When a project's config still has the former `token_sha256`, the page SHALL say that the token must be set again for the encrypted channel and, when this PC holds the matching token, offer **Upgrade**, which replaces `token_sha256` with a `token_verifier` for the same token; otherwise **New token** or **Enter token…** replaces it. The runtime host for online access SHALL be stored with the token and default to the host last used by the deploy tool when known.

#### Scenario: Enable online access
- **WHEN** the user opens Project in the tree, turns Online access on in a project and saves
- **THEN** `canworks.json` has `master.diagnostics` with `token_verifier` and neither the token nor `token_sha256`, and the configurator's settings hold the token for this project

#### Scenario: Token from another PC
- **WHEN** the project already has `token_verifier` and this PC has no token for it
- **THEN** the connect panel asks for the token and accepts it only if it matches the verifier

#### Scenario: Upgrade an old project
- **WHEN** the project has `token_sha256`, this PC holds its token, and the user presses **Upgrade** and saves
- **THEN** `canworks.json` has a `token_verifier` for the same token and no `token_sha256`, and the copied token still works after the next upload

### Requirement: Network tree
In both workspaces of a config, the left column of the workspace tab SHALL be a network tree, and it SHALL be the only navigation there. In Configure the tree SHALL start with a **Project** entry that opens the project page (target and online access). The tree SHALL show every network of the config at once, each as an entry with its name and protocol (CANopen master, CANopen slave, J1939 or Plain CAN). Under a network it SHALL show the entries that network has:
- Bus and master (Bus and ECU on J1939, Bus on Plain CAN and on a slave network);
- its nodes, sorted by node ID, each named by node ID and name;
- the slave device on a slave network;
- **Add node…** on a CANopen master network in Configure, which opens the EDS file chooser for that network;
- PDO links and CAN messages, when the network has them today.

After the networks the tree SHALL show Gateway and Modbus bridge when the config has them, and **Add network…** (Configure). Each network entry SHALL have a menu with **Rename…**, **Role** (CANopen networks) and **Remove…**, keeping today's confirmations. Which networks are folded SHALL be kept on this PC and SHALL come back after a page reload; a folded network SHALL show the sum of its entries' problem counts, and SHALL unfold by itself when a problem link opens an entry in it. The unused EDS files note and the address scan line SHALL be shown under the tree. Renaming a node SHALL update its entry as the user types.

#### Scenario: Two networks at once
- **WHEN** a config has networks `io` with nodes 5 and 7 and `drives` with node 2
- **THEN** the tree shows `io` and `drives` with their nodes, and opening node 2 needs no network switch

#### Scenario: Add a node to the second network
- **WHEN** the user picks **Add node…** under `drives` and chooses an EDS file
- **THEN** the node is added to `drives`, its entry is selected, and its General tab opens with focus in the name field

#### Scenario: Remove a network from its menu
- **WHEN** the user opens the menu of network `drives`, which has 3 nodes, and picks **Remove…**
- **THEN** the page asks for confirmation naming `drives` and its 3 nodes, with Cancel as the default

#### Scenario: Project entry
- **WHEN** a config is open in Configure
- **THEN** the tree's first entry is Project, and it opens the target and Online access

### Requirement: Connect panel
**Connect…** in the connection bar SHALL open one connect panel, and the panel SHALL be the only place to connect. No page SHALL have a connect form or a button that opens the panel, except Trace's Start while not connected (see "Trace Start without a connection").

The panel SHALL list first up to three recent connections of this PC of the kinds it offers, each connectable with one click. A recent adapter connection SHALL still run the bit rate check and SHALL start with Allow changes off. Recent connections SHALL be kept in the configurator's settings on this PC without tokens. The panel SHALL NOT open by itself on entering Commission.

In Commission a device the panel SHALL offer two targets, **USB adapter** (the default) and **Adapter on another machine**:
- USB adapter: the found adapters with Refresh, or a typed target; the bit rate, picked by the user, with no detection and no default; "Device's node ID, to check the bit rate", for adapters that cannot report a sent frame; **Allow changes**, unticked; **Connect**;
- Adapter on another machine: one host combobox listing the adapter servers found on the local network and taking a typed host (`HOST[:PORT]`, port 7536 when not given); the server's adapter and bit rate once known; a token field inside the panel when this PC has no token for that host, the token then kept on this PC per host; **Allow changes**, unticked; **Connect**.

A refused bit rate check SHALL keep the panel open with the reason and the form filled in.

With a config the panel SHALL offer three targets, **Runtime** (the default), **Standalone simulator** and **Adapter on another machine**:
- Runtime: one host combobox listing the found and remembered runtimes and "Local simulator runtime" and taking a typed host, saying "Looking for runtimes…" while it searches; a token field inside the panel when this PC has no matching token; **Connect**;
- Standalone simulator: a running `canworks-sim` by address (`HOST[:PORT]`, port 7532 when not given) and its token when it was started with one, both kept on this PC per project folder; **Connect**;
- Adapter on another machine: as in Commission a device, with a warning when the server's bit rate differs from the network's.

A token SHALL never be asked in a second dialog over the panel. When the config's online access is off, the Runtime target SHALL say so and link to Configure → Project; the other targets SHALL still work.

The last target (including Runtime, Standalone simulator or Adapter on another machine) and bit rate SHALL be kept in the configurator's settings on this PC, never in a project.

#### Scenario: Wrong bit rate refused
- **WHEN** the bus runs at 500 kbit/s and the user connects at 1000 kbit/s in the panel
- **THEN** the panel stays open, says the bus does not run at 1000 kbit/s, and the user can pick 500 kbit/s and connect without replugging the adapter

#### Scenario: Runtime needs a token
- **WHEN** the user picks a found runtime and this PC has no token for the config
- **THEN** the panel shows a token field next to Connect, accepts the token only if it matches the config's verifier, and connects, with no second dialog

#### Scenario: Disconnect frees the adapter
- **WHEN** the user presses Disconnect in the bar while connected to an adapter
- **THEN** the adapter is closed, the scan, PDO test, SYNC, send jobs and trace recording on it stop, and `canworks-diag --adapter` can open the same adapter

#### Scenario: Reconnect to the last adapter
- **WHEN** the user opens Commission a device on a PC that last connected to gs_usb:0 at 500 kbit/s and presses Connect… in the connection bar
- **THEN** the panel lists "gs_usb:0 at 500 kbit/s" first, and one click connects after the bit rate check with Allow changes off

#### Scenario: Standalone simulator
- **WHEN** the user picks Standalone simulator in the panel, enters 127.0.0.1:7532 and presses Connect
- **THEN** the panel closes, the connection bar shows the simulator's address and Disconnect, and Simulation shows its devices

#### Scenario: Adapter on another machine
- **WHEN** the user opens Commission a device, picks Adapter on another machine, chooses the found server `linuxbox`, enters its token in the panel and presses Connect
- **THEN** the connection bar shows the adapter and `linuxbox` with the round trip, and the commission pages work on linuxbox's bus; the next time the token is not asked again

#### Scenario: Bit rate differs from the network
- **WHEN** with a config whose network runs at 250 kbit/s the user picks an adapter server serving 500 kbit/s
- **THEN** the panel warns that the server runs the bus at 500 kbit/s and the network is set to 250 kbit/s before Connect

### Requirement: Simulation tab of a node
A simulated node (its `simulate`, or a node on a simulated network that is not switched off) SHALL have a **Simulated device** tab that edits that node's part of the simulation file: its value sources, its faults at start and its default behaviour switch. It SHALL edit the same draft as the Simulation file tab, so a change shows in both, and SHALL be saved with **Save to simulation file**. With several networks it SHALL edit the node's own network section. Its text SHALL point to Commission → Simulation for live values.

#### Scenario: Source from the node
- **WHEN** the user gives node 5's 0x6401:1 a sine on its Simulated device tab and saves to the simulation file
- **THEN** `simulation.json` has that source for node 5, and the Simulation file tab shows it

## ADDED Requirements

### Requirement: Trace Start without a connection
Trace's **Start** while not connected SHALL open the connect panel and start the trace once the connection is up. Canceling the panel SHALL leave Trace as it was. No message on the page SHALL name the former Online view.

#### Scenario: Start first, connect after
- **WHEN** the user presses Start on Trace while not connected, then connects to the runtime in the panel
- **THEN** the trace starts recording without a second press and no error is shown
