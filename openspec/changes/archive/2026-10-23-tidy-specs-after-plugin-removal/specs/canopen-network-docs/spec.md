## MODIFIED Requirements

### Requirement: Self-contained, offline and printable
The document SHALL be a single HTML5 file, UTF-8, that needs no network access to display: styles, scripts, diagrams and icons SHALL be inline. All content SHALL be present in the HTML as delivered, so the document reads completely with scripts disabled. It SHALL follow the viewer's light or dark preference and offer a switch between them. It SHALL have a print layout in which navigation and controls are hidden, collapsed parts are expanded, each network and each node starts on a new page, and table headers repeat across pages. It SHALL be usable at phone width without horizontal page scrolling (wide tables scroll inside themselves).

#### Scenario: Offline
- **WHEN** the document is opened in a browser with no network connection
- **THEN** it displays completely, including diagrams, and makes no network request

#### Scenario: Print to PDF
- **WHEN** the document of `examples/virtual-plant` is printed to PDF at A4
- **THEN** the PDF has no navigation sidebar, each node starts on a new page and no table is cut off at the right edge

#### Scenario: Scripts disabled
- **WHEN** the document is opened with scripting disabled
- **THEN** every section and table is shown

### Requirement: Network section
Each network SHALL have: a topology diagram showing the master and every node on the bus line with name and node ID, each linking to its section; the master's settings (adapter type and interface, bitrate, master node ID, SYNC source and period, SYNC window and counter, master heartbeat and heartbeat consumers, TIME production, NMT start behaviour, boot time, SDO timeout, error behaviour, and whether diagnostics are enabled with its port and whether changes are allowed); and the master's status PLC addresses.

#### Scenario: SYNC off
- **WHEN** the master has no `sync_period_us`
- **THEN** the network settings show SYNC as off and the COB-ID map has no SYNC frame

#### Scenario: Topology
- **WHEN** a network has nodes 2, 5 and 23
- **THEN** the diagram shows the master and three nodes in node ID order on one bus line

### Requirement: Node sheet
Each node SHALL have a section with: node ID and name; the device's vendor name, product name, vendor ID, product code and revision from its EDS, and the identity values the config checks (vendor, product, revision, serial) with whether each is checked; the EDS file name and its SHA-256; heartbeat production and consumption or node guarding; mandatory, boot, reset-communication, restore, store and configuration-check settings; error behaviour; LSS assignment; and every status and error PLC address of the node with what it holds.

#### Scenario: Identity from the EDS
- **WHEN** node 5 uses `config/rtd-sensor/rtd8.eds`
- **THEN** its sheet shows the vendor ID, product code and revision from that file's `[DeviceInfo]` and the file's SHA-256
