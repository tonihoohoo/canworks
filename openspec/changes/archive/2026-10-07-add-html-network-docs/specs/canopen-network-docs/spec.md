## ADDED Requirements

### Requirement: One HTML document of the configured networks
The export SHALL produce one HTML file describing every network of the config, or only the network named with the network option. It SHALL be built on the engineering PC from the config and the nodes' EDS files alone, with no PLC, runtime or CAN bus. Only a config that passes the deploy tool's existing checks (schema, EDS checks, EDS lint under the config's `eds_lint` setting) SHALL be exported; otherwise the export SHALL stop with those checks' messages and write nothing. Every value the document shows about frames, COB-IDs, PDO layouts and boot writes SHALL be the value the DBC and DCF exports give for the same config.

#### Scenario: Example config
- **WHEN** `config/rtd-sensor/canopen_config.json` is exported
- **THEN** one HTML file is written that names network interface `vcan0` at 125 kbit/s, node 5 `rtd`, TPDO 1 at COB-ID 0x185 and TPDO 2 at 0x285, and the PLC addresses `%IW100`-`%IW103` and `%IB100`-`%IB103`

#### Scenario: Config with an error
- **WHEN** a TPDO number does not exist in the node's EDS
- **THEN** the export stops with the same message the deploy tool's checks give and no file is written

#### Scenario: Two networks
- **WHEN** a config has networks `io` and `drives`
- **THEN** the one document has a section for each network, and with the network option `drives` it has only the `drives` section

#### Scenario: Same values as the DBC
- **WHEN** a node's TPDO 5 has `"cob_id": "auto"` and the DBC export gives it COB-ID 0x57F
- **THEN** the document shows TPDO 5 at 0x57F

### Requirement: Self-contained, offline and printable
The document SHALL be a single HTML5 file, UTF-8, that needs no network access to display: styles, scripts, diagrams and icons SHALL be inline. All content SHALL be present in the HTML as delivered, so the document reads completely with scripts disabled. It SHALL follow the viewer's light or dark preference and offer a switch between them. It SHALL have a print layout in which navigation and controls are hidden, collapsed parts are expanded, each network and each node starts on a new page, and table headers repeat across pages. It SHALL be usable at phone width without horizontal page scrolling (wide tables scroll inside themselves).

#### Scenario: Offline
- **WHEN** the document is opened in a browser with no network connection
- **THEN** it displays completely, including diagrams, and makes no network request

#### Scenario: Print to PDF
- **WHEN** the document of the CiA 402 example is printed to PDF at A4
- **THEN** the PDF has no navigation sidebar, node 4 starts on a new page and no table is cut off at the right edge

#### Scenario: Scripts disabled
- **WHEN** the document is opened with scripting disabled
- **THEN** every section and table is shown

### Requirement: Navigation, sorting and filtering
The document SHALL have a table of contents linking to the summary, each network, each node and the appendices. Sections SHALL have stable anchors derived from network name, node ID and PDO number, the same in every export of the same config. Data tables SHALL be sortable by any column and the COB-ID map, the PLC I/O cross-reference and the object dictionary appendix SHALL have a text filter. Node names in tables and in the topology diagram SHALL link to the node's section.

#### Scenario: Deep link
- **WHEN** a user opens the document with the anchor of network `drives`, node 4
- **THEN** the browser shows node 4 of `drives`

#### Scenario: Filter the I/O list
- **WHEN** the user types `%QD` into the PLC I/O filter
- **THEN** only rows with a `%QD` address remain

### Requirement: Summary
The document SHALL begin with: a title (from the title option, else "CANopen network documentation"), the config file name and its SHA-256, the exporting tool and version, the generation date and time, and per network the name, interface, bitrate, number of nodes, number of PDOs, and the cyclic and worst-case bus load estimates. It SHALL list every warning the deploy tool's checks and the export give, and SHALL state "no warnings" when there are none.

#### Scenario: Warnings listed
- **WHEN** the config has a startup SDO that writes a PDO communication object
- **THEN** the summary lists the same warning the DBC export gives for it

### Requirement: Network section
Each network SHALL have: a topology diagram showing the master and every node on the bus line with name and node ID, each linking to its section; the master's settings (adapter type and interface, bitrate, master node ID, SYNC source and period, SYNC window and counter, master heartbeat and heartbeat consumers, TIME production, NMT start behaviour, boot time, SDO timeout, error behaviour, and whether diagnostics are enabled with its port and whether changes are allowed); and the master's status PLC addresses.

#### Scenario: SYNC off
- **WHEN** the master has no `sync_period_us` and SYNC does not follow the PLC cycle
- **THEN** the network settings show SYNC as off and the COB-ID map has no SYNC frame

#### Scenario: Topology
- **WHEN** a network has nodes 2, 5 and 23
- **THEN** the diagram shows the master and three nodes in node ID order on one bus line

### Requirement: COB-ID map
Each network SHALL have a table of every frame the configured network puts on the bus, sorted by COB-ID: NMT, SYNC (when produced), TIME (when produced), each node's EMCY, each configured TPDO and RPDO, each node's SDO request and response channel, each node's heartbeat or node guarding, and the master's heartbeat (when produced). Each row SHALL give COB-ID, frame name, producer, consumers, data length, period or trigger, frame bits and load share. Two frames of one network with the same COB-ID SHALL be flagged in the table.

#### Scenario: Master heartbeat
- **WHEN** master node 1 has `heartbeat_ms` 100
- **THEN** the map has a 0x701 frame from the master with period 100 ms

#### Scenario: SDO channels
- **WHEN** node 5 is configured
- **THEN** the map has 0x605 (master to node 5) and 0x585 (node 5 to master), marked as on demand

### Requirement: Bus-load estimate
For each network the document SHALL estimate bus load from the configured frames as frame bits (11-bit identifier, worst-case bit stuffing, interframe space) times frame rate divided by the bitrate, and show the figure per frame and in total, labelled as an estimate with its method. It SHALL give two totals: cyclic (SYNC, SYNC-driven PDOs, heartbeats and node guarding, the master heartbeat, TIME) and worst case (cyclic plus each event-driven PDO at its fastest: a TPDO at its inhibit time, else at its event timer; an RPDO at the SYNC rate, or at the master's 1 ms output check without SYNC; an acyclic synchronous PDO at the SYNC rate). An event-driven TPDO with neither inhibit time nor event timer SHALL be listed as unbounded and add a warning. When SYNC follows the PLC cycle, the estimate SHALL use the PLC cycle given to the export, and without one SHALL leave SYNC and the SYNC-driven PDOs out of the totals with a note. A worst-case total above 60 % SHALL be marked as a warning.

#### Scenario: Cyclic PDOs
- **WHEN** SYNC is every 100 ms and a TPDO with 8 data bytes has transmission type 1 on a 125 kbit/s bus
- **THEN** that TPDO's load share is 135 bits × 10 per second / 125000, shown as 1.08 %

#### Scenario: Event PDO with inhibit time
- **WHEN** an event-driven TPDO has an inhibit time of 10 ms
- **THEN** it counts in the worst case at 100 frames per second and not in the cyclic total

#### Scenario: Unbounded event PDO
- **WHEN** an event-driven TPDO has neither inhibit time nor event timer
- **THEN** it is listed as unbounded and the summary has a warning naming the node and PDO

### Requirement: Node sheet
Each node SHALL have a section with: node ID and name; the device's vendor name, product name, vendor ID, product code and revision from its EDS, and the identity values the config checks (vendor, product, revision, serial) with whether each is checked; the EDS file name and its SHA-256; heartbeat production and consumption or node guarding; mandatory, boot, reset-communication, restore, store and configuration-check settings; error behaviour; LSS assignment; CiA 402 axis settings; program download file and version; and every status and error PLC address of the node with what it holds.

#### Scenario: Identity from the EDS
- **WHEN** node 4 uses `config/cia402-drive/servo402.eds`
- **THEN** its sheet shows the vendor ID, product code and revision from that file's `[DeviceInfo]` and the file's SHA-256

### Requirement: PDO details
For each configured PDO the node sheet SHALL show its number and direction, COB-ID, transmission type (marked when taken from the EDS), inhibit time, event timer and SYNC start value where they apply, and whether the master writes the mapping or the device's mapping is kept. It SHALL show the mapping as a byte grid of the frame with each mapped object spanning its bits, and as a table with bit offset, length, object index and sub-index, the object's name from the EDS, data type, PLC address and, in editor-project mode, the PLC variable name. Mapped objects that no PLC address uses and dummy entries SHALL be shown as such.

#### Scenario: Device mapping kept
- **WHEN** a TPDO keeps the device's mapping and the config maps only one of its three objects
- **THEN** all three objects appear in the layout and two are shown as not used by the PLC

#### Scenario: PLC variable names
- **WHEN** the export runs on an editor project's `canopen/canopen.json` and `%IW100` is declared as `rtd_ch1`
- **THEN** the PDO table shows `rtd_ch1` next to `%IW100`

### Requirement: Boot configuration
For each node the document SHALL list, in the order the master performs them, every SDO write of the node's boot configuration with object index and sub-index, the object's name, the value written (as a number and, for known objects such as COB-IDs and transmission types, its meaning), the object's access and EDS default, and where the write comes from (PDO configuration, node settings, startup SDO, configuration check). It SHALL list the boot steps that are not settings (restore defaults, program download, store) in their place. The list SHALL match the DCF export's writes for the node.

#### Scenario: Startup SDO
- **WHEN** node 5 has a startup SDO writing 30 to 0x6110 sub 1
- **THEN** the boot list has that write with source "startup SDO" after the PDO configuration writes

#### Scenario: Same as DCF
- **WHEN** the DCF export gives node 4 thirty-nine writes
- **THEN** the boot list of node 4 has the same thirty-nine writes in the same order

### Requirement: PLC I/O cross-reference
The document SHALL have one table of every IEC location the config uses across all exported networks, sorted by area, size and address, with network, node, what it is (PDO object, status bit, SDO variable and its trigger, status and abort code, master status) and, in editor-project mode, the PLC variable name.

#### Scenario: Master bus state
- **WHEN** the master has `bus_state_location` `%IB10`
- **THEN** the cross-reference has `%IB10` as the master's bus state

### Requirement: Appendices
The document SHALL end with an object dictionary extract per node and the config file. The extract SHALL by default list every object the config, the PDO configuration or the plugin writes or maps, with name, data type, access, limits, EDS default and configured value; with the "all" option it SHALL list every object of the EDS, collapsed by default on screen. The config file SHALL be included verbatim except for the diagnostics token hash, collapsed by default on screen. With the embed option, each node's EDS file SHALL be downloadable from the document.

#### Scenario: Embedded EDS
- **WHEN** the export runs with the embed option
- **THEN** each node sheet has a link that saves its EDS file with its original name and identical content

### Requirement: Machine-readable content
The document SHALL carry the data it shows as JSON inside the page, with a `doc_schema_version` field (1 for this version), so other tools can read networks, nodes, frames, PDOs, boot writes and I/O without parsing the HTML.

#### Scenario: Read the JSON
- **WHEN** a script extracts the embedded JSON of the rtd-sensor document
- **THEN** it finds network `vcan0`'s node 5 with TPDO 1 at COB-ID 0x185 and four mapped objects

### Requirement: Stable output
Two exports of the same config, EDS files and options SHALL differ only in the generation date and time.

#### Scenario: Re-export
- **WHEN** the same config is exported twice a minute apart
- **THEN** the files differ only in the generation timestamp

### Requirement: Nothing private in the document
The document SHALL NOT contain the diagnostics token or its hash, absolute file system paths of the computer that exported it, or the contents of any file other than the config and, with the embed option, the EDS files.

#### Scenario: Token hash
- **WHEN** the config has `diagnostics.token_sha256`
- **THEN** that hash appears nowhere in the document

#### Scenario: Paths
- **WHEN** the config refers to `eds/servo.eds` and is exported from `/srv/plant/canopen`
- **THEN** the document shows `eds/servo.eds` and never `/srv/plant`
