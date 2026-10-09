## ADDED Requirements

### Requirement: The check refuses what the plugin refuses
The configurator's check (and the deploy tool's, which is the same) SHALL refuse every config the plugin refuses at start. In particular:
- an adapter without an interface (or an slcan adapter without a device);
- a number outside its range whatever base it is typed in (decimal or `0x` hex): node IDs, heartbeat times, identity values, COB-IDs, TIME COB-ID;
- two PDOs on one network with the same COB-ID, naming both;
- an axis scale numerator or denominator of 0.

A heartbeat consumer timeout shorter than the node's heartbeat period SHALL be a warning. Each message SHALL name the place in the user's terms and say what is allowed ("node ID 1 to 127", "COB-ID 0x185 is also node 5's TPDO 1"), not quote a schema rule or pattern.

#### Scenario: Missing interface
- **WHEN** the user adds a network and leaves the SocketCAN interface empty
- **THEN** Problems lists "network net2: the CAN interface is missing" and Save is disabled

#### Scenario: Hex out of range
- **WHEN** the user types `0x80` as a node ID
- **THEN** the field is marked "node ID 1 to 127" exactly as for `128`

#### Scenario: Duplicate COB-ID
- **WHEN** node 6's TPDO 1 COB-ID is set to 0x185, which node 5's TPDO 1 uses
- **THEN** both PDOs are marked and Problems names the clash

### Requirement: Folders the configurator cannot use
Opening a folder the configurator cannot read, or saving where it cannot write, SHALL end with a message naming the folder and the reason in plain words, and the configurator SHALL stay where it was (the start page or the open config), usable without a restart. A folder is added to Recent only after it opened. "Open standalone config" SHALL refuse a folder that does not exist or has no `canworks.json`; "New standalone config" SHALL refuse a folder that already has one, offering to open it instead.

#### Scenario: Unreadable folder
- **WHEN** the user opens a folder without read permission
- **THEN** the page says it cannot read the folder, stays on the start page, Recent does not list it, and the next request works

#### Scenario: Mistyped standalone path
- **WHEN** the user types a path that does not exist and picks "Open standalone config"
- **THEN** the page says the folder does not exist and nothing opens

### Requirement: Moving a config keeps its files
"Move into project…" and "New editor project…" SHALL take along every file of the standalone config: `canworks.json`, the EDS files, `simulation.json`, the machine file and the slave EDS description, and the replace question SHALL name the project's `canworks/` folder.

#### Scenario: Simulation file moves
- **WHEN** a standalone config with a `simulation.json` is moved into an editor project
- **THEN** the project's `canworks/simulation.json` has the same content and the Simulation view shows it as saved

### Requirement: Edits carried through dependent settings
Renaming a network or changing a node's ID SHALL update the gateway routes that name it. Removing the gateway's upper network SHALL ask whether to remove the gateway too, naming it. Importing a DBC file on a J1939 network that already has one SHALL ask before replacing it. A PDO whose last entry is removed SHALL be removable, and a startup SDO write to an object that already has one SHALL be marked.

#### Scenario: Network rename with routes
- **WHEN** the user renames network io to field while two gateway routes name io
- **THEN** both routes name field and the check finds no problem

### Requirement: Online view keeps up with the device
In the online view:
- the node table SHALL update its cells in place, so keyboard focus and a pending click stay on their row;
- object dictionary values SHALL be refreshed after a write, a restore and a compare;
- writing an object that one of the node's RPDOs maps SHALL warn that the PLC program overwrites it every cycle, and "Keep in configuration" SHALL keep the written value;
- while the connection is lost the node panel SHALL be greyed and say so;
- the watch list graph SHALL draw each numeric entry as a line in its own colour in both themes;
- "Connection…" SHALL open the connection settings for every target kind.

#### Scenario: Watch graph
- **WHEN** two numeric entries are on the watch list and the graph is open
- **THEN** after a few rounds of reads each entry has a visible line

#### Scenario: Focus across polls
- **WHEN** keyboard focus is on node 6's row of the online table for 5 s
- **THEN** focus is still on that row

### Requirement: Keyboard reach and focus
Every action on the page SHALL be reachable and usable with the keyboard alone, including the Recent list, the folder browser entries and "Add node from EDS…". After a dialog or menu closes, focus SHALL return to the control that opened it, or to the nearest remaining control when that one is gone. A menu SHALL close when focus leaves it or on Escape.

#### Scenario: Recent with the keyboard
- **WHEN** the user tabs to a Recent entry on the start page and presses Enter
- **THEN** that folder opens

### Requirement: Wide tables fit
At 1280 px the gateway routes table, the slave objects table and the J1939 signal tables SHALL show every column without clipping a value or scrolling the page sideways; below 1000 px they MAY scroll inside their own box but SHALL NOT make the page scroll sideways.

#### Scenario: Gateway routes at 1280 px
- **WHEN** the virtual-plant example's gateway page is shown at 1280 px
- **THEN** each route's name ("temperature", "analog_out") and PDO entry are shown in full and nothing runs under the Problems pane

### Requirement: Exports report progress and keep Problems clean
While an export runs, the page SHALL show that it is running. The findings of a failed export SHALL replace those of the previous export, not add to them, and an export that does not apply to the open network (DCF or DBC of a slave or J1939 network) SHALL not be offered there.

#### Scenario: Repeated failing export
- **WHEN** the user runs a failing DBC export three times
- **THEN** Problems lists its findings once
