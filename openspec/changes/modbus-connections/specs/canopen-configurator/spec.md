## MODIFIED Requirements

### Requirement: Project target
A project SHALL have one target, by what runs the CAN networks: "Modbus bridge" (`bridge` object) or "CODESYS" (`codesys` object). The Project page's "Project target" field SHALL offer these two, the header SHALL show the target, and its badge SHALL open the Project page. OpenPLC SHALL NOT be a target: it is a connection (`modbus-connections`). A config with neither object SHALL open read-only with **Use with canworks-bridge** (Requirement: Plugin configs).

#### Scenario: Target shown
- **WHEN** the user opens a config with a `codesys` object
- **THEN** the Project page's Project target field and the header show CODESYS

#### Scenario: Two choices
- **WHEN** the user opens the Project target field of a Modbus bridge config with an OpenPLC connection
- **THEN** it offers Modbus bridge and CODESYS only, and the header reads "Modbus bridge"

#### Scenario: Plugin config opened
- **WHEN** the user opens a config with no `bridge` and no `codesys` object
- **THEN** it opens read-only with Use with canworks-bridge (Requirement: Plugin configs) and Save is disabled

#### Scenario: One name
- **WHEN** the user switches a Modbus bridge config with an OpenPLC connection to CODESYS and back
- **THEN** the header badge, the target field and the bridge page heading say "CODESYS" and "Modbus bridge", the connection row says "OpenPLC", and nothing says "OpenPLC through Modbus" or "OpenPLC Runtime"

### Requirement: Only what the target uses is shown
The page SHALL hide every field, column, option, section, node tab, tree entry, menu item, page and action that the target does not use, as the relevance table of `canopen-config-contract` lists it, with or without a value, and SHALL NOT mention such values. Texts that differ SHALL use the target's wording. A node tab left empty SHALL say the target does not use its settings. OpenPLC-only parts SHALL follow the OpenPLC connection instead of a target.

#### Scenario: CODESYS project
- **WHEN** the project's target is CODESYS
- **THEN** the page shows no IEC location fields or column, status locations, SDO variables, EDS lint, simulated devices, raw CAN messages, gateway, Online access, Emergency section, Connections or Editor project section, and the protocol choice offers only CANopen master

#### Scenario: Bridge project
- **WHEN** a Modbus bridge config has no OpenPLC connection and is not inside an editor project
- **THEN** the Project page has no Editor project section, the bridge page has no OpenPLC settings, and the Bus page's role hint says the bridge is the network's master

#### Scenario: OpenPLC project
- **WHEN** a Modbus bridge config has an OpenPLC connection
- **THEN** no CODESYS page, field or action is shown, the Project page has the Editor project section, and the bridge page shows its listen, word order and client fields as plain bridge settings

#### Scenario: Leftover location in a CODESYS project
- **WHEN** a CODESYS project's node `dio` has one TPDO entry with `iec_location` `%IW100`
- **THEN** the node's PDO table has no PLC location column and the PDOs tab shows nothing about it

#### Scenario: Leftover simulate in a CODESYS project
- **WHEN** a CODESYS project's node has `simulate` set
- **THEN** the node has no Simulation tab and no simulated mark

#### Scenario: Supervision with the EDS's own settings in a CODESYS project
- **WHEN** a CODESYS project's node has no heartbeat or guarding settings (Method "EDS default") and the user opens its Supervision tab
- **THEN** the Method choice is shown, there is no Emergency section, and the tab is not blank

#### Scenario: Leftover value
- **WHEN** a CODESYS project still has `on_plc_stop` set to `keep`
- **THEN** the field is hidden, nothing on the page or in Problems mentions it, and the next save leaves it out

#### Scenario: Wording guard
- **WHEN** the browser tests open every page and node tab of a config with every setting set, once per target
- **THEN** no field the target does not use is visible, no node tab is blank, and a CODESYS page names no bridge, Linux device, PLC location or OpenPLC

### Requirement: Switching the target
Picking the other target SHALL switch at once, without a dialog, as one undo step, with a message saying what was done and that Undo restores it. To CODESYS: entries without `name` get their generated name, values CODESYS does not use and `bridge` (with its connections) are removed. From CODESYS: `codesys` objects are removed and every entry gets a location packed for Modbus; names stay.

#### Scenario: OpenPLC to CODESYS
- **WHEN** the user switches a bridge project with node `dio` mapping 0x6000 sub 1 to `%IB12` and an OpenPLC connection to CODESYS
- **THEN** no dialog opens, the entry has `name` `Read_input_8_bit_1` and no `iec_location`, the config has a `codesys` object and no `bridge`, and one Undo restores the bridge project with its connection

#### Scenario: CODESYS to bridge
- **WHEN** the user switches that CODESYS project to Modbus bridge
- **THEN** every entry has a byte-addressed location, the `codesys` objects are gone, and Connections is empty

### Requirement: Target of a new config
New config… SHALL ask "What runs the CAN networks?" with two cards: **Modbus bridge** (canworks-bridge runs the networks and serves Modbus TCP registers; the card lists OpenPLC, truST, other PLCs, Node-RED and HMI, SCADA or scripts as what it works with) and **CODESYS** (a CODESYS PLC runs the CANopen master). Modbus bridge SHALL be preselected. Then it SHALL ask for the name and location, and Create SHALL write the empty config before the page opens it.

#### Scenario: New Modbus bridge config
- **WHEN** the user creates a new Modbus bridge config and reloads the page
- **THEN** the folder holds a config with a `bridge` object and no connections, and the page shows it with the Modbus bridge target and "Saved"

#### Scenario: New CODESYS config
- **WHEN** the user creates a new config with target CODESYS
- **THEN** the config is version 2 with a `codesys` object, it is on disk, and the page shows the CODESYS target

#### Scenario: New OpenPLC config with an editor project
- **WHEN** `openplc-cli` is found, the user creates a new Modbus bridge config and adds an OpenPLC connection with New editor project… in `~/plc/new-machine`
- **THEN** the dialog shows "Creating the editor project…" until `~/plc/new-machine` is an OpenPLC Editor project with the config in its `canworks/` folder holding an `openplc` connection and `devices/remote/canworks.json`, and the page shows the mode "project new-machine"

#### Scenario: No editor command-line tool
- **WHEN** `openplc-cli` is not found and the user adds an OpenPLC connection to a standalone config
- **THEN** New editor project… is disabled with the reason, and the connection is added to the config in its folder

### Requirement: Export menu groups
Export ▾ SHALL hold the network files: All DCFs, This node's DCF, DBC and Documentation, and on a CODESYS config Download for CODESYS. It SHALL hold no register map, ST, PLCopen or Node-RED item: those are each connection's Download (`modbus-connections`).

#### Scenario: Bridge config
- **WHEN** the user opens Export ▾ on a Modbus bridge config with connections
- **THEN** it lists All DCFs, This node's DCF, DBC and Documentation, and nothing for a program

#### Scenario: OpenPLC config
- **WHEN** the user opens Export ▾ on a Modbus bridge config with an OpenPLC connection
- **THEN** it has no register map, ST, PLCopen or Node-RED item

#### Scenario: Node-RED flow from the menu
- **WHEN** a Modbus bridge config has a valid map and the user opens Export ▾
- **THEN** there is no Node-RED flow item, and the bridge page's Add connection offers Node-RED, whose Download gives `<config name>-<connection name>.json`, equal to the command-line export

#### Scenario: CODESYS download from the menu
- **WHEN** the user picks Download for CODESYS in Export ▾ on a CODESYS config
- **THEN** the browser downloads `<config folder name>_codesys.zip` as Download on the CODESYS page does

### Requirement: Same files from the menu
Each connection's Download and each Export ▾ item SHALL give the same file as its command-line export: `--export-modbus-map` formats, `--export-nodered` with the connection's host and period, `--export-plcopen` with the connection's settings, and the `codesys-export` zip. When the file cannot be computed, it SHALL show the reason instead.

#### Scenario: Map cannot be computed
- **WHEN** the register map of a Modbus bridge config has an error and the user presses Download on an HMI connection
- **THEN** nothing downloads, the reason is shown, and the connection's `map_hash` is unchanged

### Requirement: Where things are
The configurator SHALL place its parts by one rule: the Project page holds the target and whole-project actions; the header's primary button puts the config onto the target; Export ▾ holds the network files; the Modbus bridge page holds the bridge settings and the Connections, each with its program-side files; Copy as ST call stays on its item. `docs/configurator.md` SHALL state this rule.

#### Scenario: Node-RED flow
- **WHEN** a user of a Modbus bridge config looks for the Node-RED flow
- **THEN** it is the Download of a Node-RED connection on the Modbus bridge page, and Export ▾ has no Node-RED item

### Requirement: Register map preview and export
The bridge page SHALL show the register map as a table (Modbus table, address, size, type, name, source) with a filter, the suggested client channels and "Pack for Modbus". It SHALL have no export buttons of its own: the map files are the Downloads of HMI, SCADA or script connections.

#### Scenario: Export the ST list
- **WHEN** the user downloads an HMI connection with `format` `st`
- **THEN** the browser gets the same file `canworks-deploy --export-modbus-map map.st` writes for this config

### Requirement: Bridge settings panel
A bridge project SHALL have a "Modbus bridge" page with Connections first, then: listen address and port, unit ID, word order, maximum clients; "Who may write" from the connections and the readers allowlist; watchdog time and client-loss action; status block, control block, live lists and SDO bridge locations, each with "Suggest".

#### Scenario: Add a live list
- **WHEN** the user adds a live list for network `field` and clicks Suggest
- **THEN** a free 16-byte input range is chosen and shown in the register map

### Requirement: Editor project on the Project page
The Project page SHALL have an **Editor project** section when the config is inside an OpenPLC Editor project or has an OpenPLC connection. In project mode it SHALL name the project, its folder and the files Save writes. Standalone, it SHALL offer **Move into project…** and **New editor project…**. CODESYS configs SHALL NOT have the section.

#### Scenario: Standalone OpenPLC config
- **WHEN** a standalone config with an OpenPLC connection opens its Project page
- **THEN** the Editor project section offers Move into project… and New editor project…

#### Scenario: Modbus bridge config
- **WHEN** a standalone bridge config without an OpenPLC connection opens its Project page
- **THEN** it has no Editor project section

### Requirement: OpenPLC project page
A bridge config's OpenPLC connection SHALL have **Settings** on its row, opening the poll period (`poll_ms`, placeholder 10), the remote device name and the first editor location, with facts from the saved config: the remote device and port, the poll with requests per poll and the warning above 40, the writer-loss time, the map hash and the first editor `%IW`/`%QW`.

#### Scenario: Requests per poll
- **WHEN** a config with an OpenPLC connection has 30 nodes with two TPDOs and two RPDOs each, none contiguous
- **THEN** the OpenPLC connection's settings show the request count above 40 with the warning, and Problems lists it

### Requirement: Export for another PLC
The truST and Other PLC (`format` `plcopen`) connections SHALL download the `--export-plcopen` folder as a zip for `trust` or `generic`. Their settings SHALL hold the bridge address the PLC uses (default: `listen` when it is neither a wildcard nor a loopback address) and whether to include the library (on).

#### Scenario: truST connection
- **WHEN** the user downloads a truST connection with bridge address 192.168.10.5 on a config with `plc_link`
- **THEN** the zip equals `canworks-deploy --export-plcopen --for trust --bridge-host 192.168.10.5` for the config

#### Scenario: Only on Modbus bridge configs
- **WHEN** a CODESYS config is open
- **THEN** there is no Connections list and nothing offers a PLCopen download

### Requirement: Export for another PLC download
The zip SHALL be named `<config name>-<connection name>.zip`. On a config without `plc_link` a PLCopen connection SHALL say so and offer **Turn on the PLC link and repack**, one undo step.

#### Scenario: PLC link off
- **WHEN** the config has no `plc_link` and the user adds an Other PLC connection with `format` `plcopen`
- **THEN** the row explains the PLC link and offers to turn it on and repack, and Undo restores the previous layout

#### Scenario: Export for CODESYS
- **WHEN** the user opens an Other PLC connection's settings
- **THEN** its format offers PLCopen XML and ST only, with no CODESYS choice, and a line says CODESYS uses the CODESYS target

### Requirement: Reachability warnings for other PLCs
A PLCopen or ST connection whose bridge address is empty SHALL show a warning on its row and in Problems. Connection addresses that cannot reach `listen` SHALL be the error of `modbus-connections` "Connections reach the bridge".

#### Scenario: No bridge address
- **WHEN** a truST connection has no bridge address and `listen` is `0.0.0.0:502`
- **THEN** its row and Problems warn that the PLC needs the bridge's address

#### Scenario: Loopback listen
- **WHEN** a config with `plc_link` listens on `127.0.0.1:1502` and has a truST connection at 192.168.10.7
- **THEN** Problems shows the error naming the truST connection with Listen on all addresses

### Requirement: Copy as ST call only where the blocks run
Copy as ST call (object dictionary entry, NMT command, CAN message, J1939 PGN) SHALL be offered only on Modbus bridge configs, not on a CODESYS config and not when commissioning a device without a config.

#### Scenario: CODESYS config
- **WHEN** the user opens a node's object dictionary in Commission on a CODESYS config
- **THEN** no entry offers ST, and NMT offers no Copy as ST call

## ADDED Requirements

### Requirement: Plugin configs
A config with neither `bridge` nor `codesys` (the removed plugin's) SHALL open read-only with one message and **Use with canworks-bridge**. As one undo step it SHALL repack for the bridge, add `bridge`, add an OpenPLC connection when the folder is inside an OpenPLC Editor project, and remove `axis`, `sync_source`, `sync_cycles` and `scan_watchdog_ms`. Until then the page SHALL NOT save.

#### Scenario: Plugin project
- **WHEN** the user opens a plugin config inside an editor project, whose master has `"sync_source": "plc_cycle"`, and presses Use with canworks-bridge
- **THEN** the config has `bridge` with an OpenPLC connection, `plc_link` true and no `sync_source`, and one Undo restores the config as opened

## REMOVED Requirements

### Requirement: CODESYS route explained
**Reason**: CODESYS as a Modbus client of the bridge is not a supported use (Toni 2026-10-23); the PLCopen export no longer has a CODESYS route.
**Migration**: CODESYS users pick the CODESYS target, where CODESYS runs the CANopen master.

### Requirement: Live lists for every network on switch to OpenPLC
**Reason**: There is no switch to an OpenPLC target any more.
**Migration**: Adding an OpenPLC connection adds the live lists (`modbus-connections` "OpenPLC connection bridge settings").
