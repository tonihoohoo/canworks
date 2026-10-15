## ADDED Requirements

### Requirement: Decoding panel in the Trace view
The Trace toolbar's **Decoding** button SHALL open a panel that says what the trace decodes with and lets the user change it. The button SHALL show a short summary (number of DBC files, number of nodes with a known PDO layout) and a warning mark when a DBC file is missing or has problems.

The panel SHALL have:
- **DBC files**: each file's name, how many of its messages are used out of its total, its problems and the messages not used with what decodes their identifier instead; **Add DBC…** (one or more files), remove, and a way to change the order with the mouse and the keyboard.
- **Nodes**, on a CANopen network: each node heard on the bus or on the Nodes tab, with its device name, its EDS file or "standard objects", the source of its PDO layout ("set on the bus at …", "read from the device at …", "EDS defaults", "configuration", or "unknown"), and the actions **Pick EDS…** or **Change EDS…** (the Nodes table's menu for that node) and **Read PDOs from device**.

**Read PDOs from device** SHALL be disabled with its reason without a live connection. While the connection bar reports another master, it SHALL ask first, saying that the other master's SDO transfers to the node can be mixed with the read.

The DBC files SHALL be remembered on this PC per project folder, and once for Commission a device, outside the project's canworks folder. A remembered file that is missing SHALL be listed as missing with Locate… and Remove, and decoding SHALL go on without it.

#### Scenario: Add a DBC
- **WHEN** the user opens Decoding, presses Add DBC… and picks `machine.dbc` with 12 messages, 2 of which are on identifiers the configuration decodes
- **THEN** the panel lists `machine.dbc` with "10 of 12 messages used", names the 2 messages and what decodes them, the rows of the other 10 identifiers decode with the DBC, and the button reads "1 DBC"

#### Scenario: Remembered
- **WHEN** the user closes the page and opens Commission a device again the next day
- **THEN** the Trace decodes with the same DBC files without asking

#### Scenario: Fix a raw PDO from the panel
- **WHEN** node 50's PDOs show as bytes and its layout source reads "unknown", and the user picks its EDS with Pick EDS…
- **THEN** its PDO rows decode with the EDS defaults and the source reads "EDS defaults"

### Requirement: Automatic PDO layout reads in Commission a device
On a live connection that can send in Commission a device, the page SHALL read the PDO communication and mapping objects of each node heard on the bus: one node at a time after its identity read, once per connection, and again after the node boots up. It SHALL NOT read from a node in STOPPED, and SHALL NOT read automatically while the connection bar reports another master. The reads SHALL need no Allow changes. PDO 1-4 SHALL always be tried and PDO 5 onwards until the first whose communication object does not exist.

#### Scenario: Read after hearing a node
- **WHEN** the page connects through a USB adapter and hears node 32's heartbeat, and no other master is reported
- **THEN** the page reads node 32's PDO objects once, and its PDO rows recorded after the read decode with the layout read from the device

#### Scenario: Another master
- **WHEN** the connection bar reports another master on the bus
- **THEN** no PDO objects are read automatically, and the Decoding panel's node rows offer Read PDOs from device

### Requirement: PDO layout in the frame inspector
For a PDO frame the frame inspector SHALL show a Layout line naming where the layout came from (configuration, DBC file, set on the bus at a time, read from the device at a time, or EDS defaults). Rows and inspectors decoded with EDS defaults SHALL carry an "assumed" tag whose tooltip says that the device may be mapped differently and how to make it certain. For a PDO frame shown as bytes, the Layout line SHALL say why and offer **Pick EDS…** and **Read PDOs from device** for its node.

#### Scenario: Raw PDO in the inspector
- **WHEN** the user selects a TPDO1 row of node 50 that shows only bytes
- **THEN** the inspector's Layout line says node 50 has no EDS and its PDOs were not read, with Pick EDS… and Read PDOs from device

#### Scenario: Assumed layout
- **WHEN** node 32's TPDO1 decodes with its EDS defaults
- **THEN** the row shows the "assumed" tag and the inspector's Layout line reads "EDS defaults: the device may be mapped differently"

## MODIFIED Requirements

### Requirement: Trace toolbar and views
The Trace tool tab SHALL have one toolbar with:
- one Start / Stop button;
- Clear and Open…;
- a Save menu with "Save to traces folder" and "Download as…", each with its format, and the range;
- Capture… for capture filters and error frames;
- Decoding… for DBC files and the nodes' PDO layouts (see "Decoding panel in the Trace view");
- the time mode.

Under it SHALL be the header with the statistics and the view tabs **By identifier**, **Chronological**, **Graph**, **Sequences** (not on J1939) and **Trigger**.

#### Scenario: One Start / Stop button
- **WHEN** the user presses Start
- **THEN** the same button reads Stop until the recording stops
