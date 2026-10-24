# canopen-configurator Specification

## Purpose
A local GUI on the engineering PC that creates and edits a canworks config (a config folder, or the `canworks/` folder of an OpenPLC Editor project) for the Modbus bridge or CODESYS, so networks and nodes can be set up and mapped without hand-writing JSON.

## Requirements

### Requirement: Choose what to edit
Started without arguments, the configurator SHALL open a start page with one line saying what the tool is for (setting up CANopen and J1939 networks for a PLC, working on a CANopen device directly from the PC, and installing canworks on a Linux device), two buttons, **Open…** and **New config…**, two links, **Commission a device without a config** and **Install on a device**, and the **Recent** list as the page's main content. The page SHALL NOT show a folder browser of its own; Open… and New config… SHALL pick folders in the configurator's folder dialog.

Open… SHALL open the picked folder as an OpenPLC Editor project when it has `project.json` (editing its `canworks/` folder and checking addresses against its program), else as a config folder when it has `canworks.json`. A folder with neither SHALL get one question offering to start a new config there, which opens New config… with that folder filled in.

Each Recent entry SHALL show the folder's name, its path, a tag with the config's target (Modbus bridge or CODESYS, or "OpenPLC plugin (removed)" for a config of the removed plugin; none when the config cannot be read) and whether it is an editor project or a config folder, and when it was last opened when known. One click or Enter SHALL open it, and each entry SHALL have a Remove button that takes it off the list and leaves the folder alone. With nothing in Recent, the page SHALL show four short starting choices in its place, each in one sentence of plain words: open an OpenPLC project (Open…), start something new (New config…), talk to a device with a USB CAN adapter (Commission), and set up a Linux device (Install on a device). The start page SHALL NOT use the words "standalone", "canworks.json", "LSS" or "object dictionary", and SHALL NOT name a board brand.

A path given on the command line SHALL open directly, as a project when the folder has `project.json` and as a config folder otherwise. The current mode SHALL always be visible.

#### Scenario: Start page
- **WHEN** `canworks-config` runs without arguments in a 1280 px wide window and Recent has entries
- **THEN** the browser shows the purpose line, Open… and New config…, the Commission and Install on a device links and the Recent list, with no folder browser and no clipped text

#### Scenario: First run
- **WHEN** `canworks-config` runs with an empty Recent
- **THEN** the page shows the four starting choices instead of the list, and each runs the same action as Open…, New config…, the Commission link or the Install on a device link

#### Scenario: Open a project from the start page
- **WHEN** the user chooses Open… and picks `~/Documents/workspace/rtd-monitor`, which has `project.json` and `canworks/canworks.json`
- **THEN** the page shows that config with the mode "project rtd-monitor"

#### Scenario: Open a config folder
- **WHEN** the user chooses Open… and picks `~/canworks/rtd`, which has `canworks.json` and no `project.json`
- **THEN** the page shows that config as a config folder

#### Scenario: Project without a config
- **WHEN** the user opens an OpenPLC Editor project that has no `canworks/` folder
- **THEN** the page shows an empty config and the project folder is unchanged until the user saves

#### Scenario: Not an editor project
- **WHEN** the user chooses Open… and picks a folder with neither `project.json` nor `canworks.json`
- **THEN** the page asks whether to start a new config there, and Yes opens New config… with that folder

#### Scenario: Recent shows the target
- **WHEN** Recent holds a Modbus bridge config folder and a CODESYS config
- **THEN** their entries are tagged "Modbus bridge" and "CODESYS", and one click on either opens it

### Requirement: Standalone config before a project exists
In standalone mode the configurator SHALL edit `canworks.json` and its EDS files in a plain folder, creating the folder on first save, with every check except the editor-project address checks, which the page SHALL show as skipped. The page SHALL offer "move into project", which runs the deploy tool's `--into-project` checks, copies the config into the picked project's `canworks/` folder and switches to project mode. The deploy tool's `--config` SHALL accept the folder unchanged.

#### Scenario: Configure first, project later
- **WHEN** the user creates a new standalone config in `~/canworks/rtd`, adds the RTD node and saves, then later chooses "move into project" and picks `~/Documents/workspace/rtd-monitor`
- **THEN** the project gets `canworks/canworks.json` and the EDS, the page switches to project mode and runs the address checks against the project

#### Scenario: Project already has a config
- **WHEN** the picked project already has a `canworks/` folder
- **THEN** nothing is copied until the user confirms replacing it

### Requirement: Local access only
The configurator SHALL listen only on the loopback interface and SHALL reject any request that does not carry the random session token it generated at start; the only exception SHALL be the running-instance request of a second start, which needs the instance secret instead. The session cookie's name SHALL include the port in the request's Host, so configurators on different ports keep separate sessions. The page SHALL load no resource from the network. The configurator's own outgoing connections SHALL go only to the runtime host and port the user entered for online access, and only while the user has the online view or scan open.

#### Scenario: Request from another host
- **WHEN** another machine on the LAN connects to the configurator's port
- **THEN** the connection is refused because nothing listens on a non-loopback address

#### Scenario: Request without the token
- **WHEN** a local process sends a save request without the session token
- **THEN** the request is rejected and nothing is written

#### Scenario: Offline editing makes no connection
- **WHEN** the user edits and saves a config without opening the online view or scan
- **THEN** the configurator opens no network connection

#### Scenario: Two configurators in one browser
- **WHEN** one configurator is open at port 9000 and one started with `--new-instance` at port 9001 in the same browser
- **THEN** both pages keep working and neither is logged out by the other

### Requirement: Import an EDS
Adding a node SHALL start from an EDS file the user picks. The configurator SHALL check that it is a CiA 306 EDS the deploy tool accepts, store it under `canworks/` as UTF-8 (converting from Latin-1/CP1252 when it is not valid UTF-8) and refer to it by a path relative to `canworks/`. A different file with the same name SHALL NOT be overwritten silently. When "keep both" gives the new EDS another name, it SHALL get its own notes file (see `canopen-device-notes`), and replacing an EDS SHALL keep its notes file.

At import, the configurator SHALL also run the checks the bridge runs before dcfgen, on the same prepared copy (see `canopen-master-bringup`, "Prepared EDS copy"): dcfgen's EDS read and lint, and Lely's EDS parse rules, sorting the lint findings as the bridge does (see `canopen-master-bringup`, "EDS lint scope") under the config's `eds_lint` setting. The import SHALL show:
- that the file is readable, when nothing below applies;
- the corrections made in the prepared copy (UTF-8 conversion, `$NODEID` rewrites, REAL rewrite, cleared OCTET_STRING values), as described below;
- findings that do not stop the bridge, as a collapsed list with each finding's object, saying they are accepted.

The correction report SHALL name the imported file, SHALL say that the file is kept as imported, and SHALL name who reads the corrected copy for the project's target: canworks-bridge, the Modbus bridge, or, for a node under a CODESYS target, the DCFs exported to CODESYS, which are built from it. A slave EDS import under a CODESYS target SHALL name canworks as the reader. Each kind of correction SHALL be listed on its own line with how many values it changed, in words that read correctly for one value and for several. Under a CODESYS target, a node import SHALL NOT list the REAL rewrite, since the exported DCFs write REAL values as decimals. The UTF-8 conversion, which changes the stored file, SHALL be reported on its own line as before.

The import SHALL be refused, showing the reason, and no node SHALL be added, when dcfgen or Lely cannot read the file even after the corrections, or when the lint has findings that would stop the bridge.

#### Scenario: Latin-1 vendor EDS
- **WHEN** the user imports `vendor.eds`, encoded in Latin-1 with `°C` in a ParameterName
- **THEN** on save `canworks/vendor.eds` is valid UTF-8 with the same text and the node's `eds` is `vendor.eds`

#### Scenario: Not an EDS
- **WHEN** the user picks a file without objects 0x1000 and 0x1018
- **THEN** the import is refused with the reason and no node is added

#### Scenario: Same name, different content
- **WHEN** an imported EDS has the same name as a different EDS already in `canworks/`
- **THEN** the user is asked to replace it or keep both under a new name, and nothing is overwritten without that choice

#### Scenario: Vendor EDS with findings in profile objects
- **WHEN** the user imports a drive EDS with signed limits written as unsigned hex in its profile objects
- **THEN** the node is added and the import shows its findings as accepted, listed collapsed with their objects

#### Scenario: Finding in a communication object
- **WHEN** the user imports an EDS whose 0x1A00 sub 0 has the data type UNSIGNED16, and `eds_lint` is unset
- **THEN** the import is refused, the finding in 0x1A00 sub 0 is shown, and no node is added

#### Scenario: Notes file for a new EDS
- **WHEN** the user imports `valve.eds`, which has no notes file, adds the node and saves
- **THEN** `canworks/valve.eds.notes.json` is written with the valve's identity and an entry for each manufacturer object

#### Scenario: $NODEID rewrite reported for OpenPLC
- **WHEN** the project target is Modbus bridge with an OpenPLC connection and the user adds a node from `valve.eds`, which has 8 values written `<number>+$NODEID`
- **THEN** the banner names `valve.eds`, says it is kept as imported and that canworks-bridge reads a corrected copy, and lists that 8 values written `<number>+$NODEID` are read as `$NODEID+<number>`

#### Scenario: One rewritten value
- **WHEN** the imported EDS has exactly one value written `<number>+$NODEID`
- **THEN** the line reads as one value ("1 value ... is read as"), not "1 values"

#### Scenario: $NODEID rewrite reported for CODESYS
- **WHEN** the project target is CODESYS and the user adds a node from the same `valve.eds`
- **THEN** the banner names `valve.eds`, says it is kept as imported and that the DCFs exported to CODESYS are built from a corrected copy, and lists the 8 rewritten values

#### Scenario: REAL rewrite only, CODESYS
- **WHEN** the project target is CODESYS and the only correction an imported EDS needs is decimal REAL values
- **THEN** no correction is listed, and the banner says the file is readable when nothing else applies

### Requirement: SocketCAN adapter settings
The configurator SHALL edit the `socketcan` adapter: interface name, bit rate chosen from the CiA 301 rates the contract allows, whether the bridge configures the link (`configure_link`, default on) and the bus-off restart delay (`restart_ms`). A config using the pre-contract top-level `interface`/`bitrate` keys SHALL be shown as that adapter and saved in the `adapter` form, with the page saying so.

#### Scenario: Set up can0 at 250 kbit/s
- **WHEN** the user sets interface `can0`, bit rate 250000, leaves "configure link" on, sets restart 100 ms and saves
- **THEN** `canworks.json` has `adapter` `{"type": "socketcan", "interface": "can0", "bitrate": 250000, "configure_link": true, "restart_ms": 100}`

#### Scenario: Bit rate outside CiA 301
- **WHEN** a loaded config has `bitrate: 300000`
- **THEN** the bit rate field shows the contract error and the hand-off steps refuse the config until a listed rate is chosen

#### Scenario: Old-style config
- **WHEN** a loaded config has top-level `interface: "vcan0"` and `bitrate: 125000`
- **THEN** the page shows a SocketCAN adapter on `vcan0` at 125000 with "configure link" off, says the file uses the old keys, and saving writes them as `adapter` with `configure_link: false`

### Requirement: Node supervision settings
For each node the configurator SHALL edit node ID, name, heartbeat period and timeout, or node guarding time and life time factor, and the status bit location. A new node's status bit SHALL get a suggested free `%IX` location.

#### Scenario: Heartbeat for a new node
- **WHEN** the user adds a node from an EDS, sets heartbeat 100 ms and timeout 300 ms and saves
- **THEN** the node has `heartbeat_ms` 100, `heartbeat_timeout_ms` 300 and a `status_location` that is free in the project

### Requirement: PDO communication parameters
For each PDO the configurator SHALL edit the PDO number, COB-ID, transmission type and event timer, leaving each unset to use the default unless the user sets it. For a TPDO it SHALL also edit the receive timeout: an empty field (no `timeout_ms`, shown as "off"), a number of milliseconds, or Auto, which SHALL show the resolved value next to it (two times the event timer from the config or the EDS) and SHALL be offered only when that event timer is not 0. When a timeout is set the configurator SHALL show the "on timeout" choice (hold, the default and saved as no field, or zero) and a timeout bit address field (`%IX`, optional, included in the address suggestion and clash checks). The Check SHALL give the same messages as the bridge for these fields, and SHALL warn when a numeric timeout is shorter than the PDO's effective event timer.

#### Scenario: Event-driven TPDO
- **WHEN** the user sets a TPDO's transmission type to 254 and event timer to 500 ms
- **THEN** the saved PDO has `transmission` 254 and `event_timer_ms` 500, and no `cob_id` unless one was set

#### Scenario: Auto timeout from the EDS
- **WHEN** a TPDO has no event timer set, its EDS gives 100 ms, and the user picks Auto
- **THEN** the field shows "auto (200 ms)" next to it and the saved PDO has `"timeout_ms": "auto"`

#### Scenario: Timeout off
- **WHEN** the user clears the timeout field and saves
- **THEN** the saved PDO has no `timeout_ms`, `on_timeout` or `timeout_location`

### Requirement: Defaults and fixed choices on the page
Every setting the bridge defaults when it is left out SHALL show that default on the page (in the empty field and in a short hint), computed where it depends on other values: the CiA 301 COB-ID of PDOs 1 to 4 from the node ID and PDO number, and the heartbeat timeout as 3 × the heartbeat period. Settings with a fixed set of values SHALL be dropdowns that explain each choice: adapter type, bit rate, supervision method (none, heartbeat, node guarding, showing only the chosen method's fields), PDO transmission type and startup SDO data type.

#### Scenario: Defaults shown
- **WHEN** node 5 has TPDO 1 with no `cob_id` and no `transmission`, and a heartbeat of 100 ms with no timeout
- **THEN** the COB-ID field shows `0x185`, the transmission dropdown shows "1: every SYNC (default)", and the timeout field shows `300`, and none of these values is written to `canworks.json`

#### Scenario: Supervision method
- **WHEN** the user picks node guarding for a node that has a heartbeat set
- **THEN** the heartbeat fields are removed from the node and only guard time and life time factor are shown

### Requirement: Startup SDO writes
For each node the configurator SHALL edit an ordered list of startup SDO writes, which the bridge performs every time the node is configured at boot. The user SHALL pick the object from the node's EDS or type an index and subindex, and the type SHALL come from the EDS. Objects the EDS does not define, or marks read-only or const, SHALL be refused, and each value SHALL be checked against its type's range. The picker and the list SHALL show each object's note `text` under its name; the value field SHALL show the value's meaning and unit from the merged note, and SHALL offer the note's `values` as a list with "Other value…" when it has them.

#### Scenario: Set the RTD sensor type
- **WHEN** the user adds a write to 0x6110 subindex 1 (`AI0_Sensor_Type`, `rw`, UNSIGNED16, EDS default 0x1E), enters `0x1E`, and moves it to the top of the list
- **THEN** the saved node's `sdo` list starts with `{"index": "0x6110", "subindex": 1, "type": "UNSIGNED16", "value": "0x1E"}`, and the bridge writes it before the other startup SDOs

#### Scenario: Read-only object
- **WHEN** the user picks object 0x1018 subindex 1 (const)
- **THEN** the write is refused with the reason

#### Scenario: Value out of range
- **WHEN** the user enters 300 for an UNSIGNED8 object
- **THEN** the field shows the range error and the hand-off steps refuse the config

#### Scenario: Object not in the EDS
- **WHEN** the user types index 0x2100 subindex 0 that the EDS does not list
- **THEN** the write is refused, because the bridge only writes startup SDOs to objects the node's EDS defines

#### Scenario: Startup SDO with a value meaning
- **WHEN** the notes give 0x2011:2 the values 0 "hold position" and 1 "close" and the user adds a startup SDO for it
- **THEN** the value field lists "0 hold position" and "1 close", and the saved write has the number the user picked

### Requirement: Map PDO entries from the EDS
When mapping a node's PDO entries, the configurator SHALL list only objects the node's EDS marks as PDO-mappable, with index, subindex, name and data type. An object the slave can only send SHALL be offered as an input (TPDO), one it can only receive as an output (RPDO). The entry's `type` SHALL be taken from the EDS.

#### Scenario: Map a temperature input
- **WHEN** the user picks object 0x7130 subindex 1 (`AI0_Input_PV`, INTEGER16, read-only, PDO-mappable) from the RTD sensor's EDS
- **THEN** it is added to a TPDO of that node with `type` INTEGER16 and an `%IW` location

#### Scenario: Object not mappable
- **WHEN** an object's EDS entry has PDOMapping 0
- **THEN** it is not offered for PDO mapping

#### Scenario: PDO full
- **WHEN** adding an entry would make a PDO longer than 64 bits
- **THEN** the configurator puts the entry in the next PDO of the same direction, or says the node has no PDO left

### Requirement: Suggest PLC addresses
For each new PDO entry the configurator SHALL suggest the lowest free location of the area and size that fit its data type, skipping locations used in the CANopen config and anywhere else in the editor project. The user SHALL be able to replace the suggestion with any location.

#### Scenario: Next free word
- **WHEN** the project's Modbus remote device already uses `%IW100` and the user maps an INTEGER16 input
- **THEN** the suggestion is the lowest free `%IW` location that is not `%IW100`

### Requirement: Check addresses against the editor project
The configurator SHALL read, never write, the editor project's files and collect every IEC location they use (remote devices, pin mapping, located variables). A CANopen location that overlaps one of them SHALL be shown as an error naming the other use. Located variables at exactly a CANopen entry's location SHALL count as declarations of that entry, not as clashes. A located variable SHALL be named correctly in both declaration forms, `name AT location : TYPE` and the editor's own `name : TYPE AT location`.

#### Scenario: Clash with EtherCAT
- **WHEN** the user sets a CANopen entry to `%ID100` and the project's EtherCAT device maps a channel to `%ID100`
- **THEN** the entry shows an error naming the EtherCAT device file and the hand-off steps refuse the config

#### Scenario: Matching located variable
- **WHEN** the project declares `rtd1 AT %IW100 : INT` and a CANopen INTEGER16 entry uses `%IW100`
- **THEN** no clash is reported and the entry shows that it is declared as `rtd1`

#### Scenario: Editor-style declaration
- **WHEN** the project's `main.st` declares `rtd1 : INT AT %IW100;` (as the editor writes it after an edit in its variable table) and a CANopen INTEGER16 entry uses `%IW100`
- **THEN** the entry shows that it is declared as `rtd1`, not as `INT`

### Requirement: Validate before save
Before and after saving, the configurator SHALL run the deploy tool's checks: contract schema, EDS type and access checks, node ID uniqueness, overlapping locations and SDO value ranges. It SHALL show every error next to the field it concerns and in Problems. Save SHALL write the draft even when it has errors, and SHALL then show a message bar saying how many errors the saved config has and that the runtime refuses it until they are fixed. The steps that hand the config over SHALL refuse it while it has errors (see "Hand-off steps need a config without errors"). An overlap with the editor project MAY be handed over only when the user explicitly allows it, as the deploy tool's `--allow-clash` does. The control that allows it SHALL be shown in the Problems pane together with the editor-project overlap errors, and only while there are such errors; it SHALL NOT be shown in the page header or in standalone mode.

#### Scenario: Duplicate node ID
- **WHEN** two nodes have node ID 5 and the user presses Save
- **THEN** the config is written, both node ID fields show the error, and a message bar says the saved config has 1 error that the runtime refuses

#### Scenario: No overlap, no override
- **WHEN** a project config has no location that overlaps the editor project
- **THEN** neither the header nor the Problems pane shows an "Allow overlap" control

#### Scenario: Save despite an overlap
- **WHEN** node 2's TPDO entry uses `%ID100`, which the editor project's EtherCAT config also uses, and the user ticks "Allow overlap" under that error in the Problems pane
- **THEN** saving writes the config, the overlap no longer blocks the hand-off steps, and the Problems pane says overlaps are allowed

### Requirement: Save only the project's canopen folder
Saving SHALL write `canworks/canworks.json`, the imported EDS files and their notes files (`<eds file name>.notes.json`, see `canopen-device-notes`) under `canworks/`, and no other file. `canworks.json` SHALL be replaced atomically, carry `schema_version` 1 and keep fields the configurator does not know. The saved folder SHALL be accepted unchanged by the deploy tool's `--config` and by the editor-upload hook.

#### Scenario: Unknown field kept
- **WHEN** a loaded config has a field the configurator does not know and the user changes a heartbeat and saves
- **THEN** the unknown field is still in the saved file with its value

#### Scenario: Only canopen is touched
- **WHEN** the user saves
- **THEN** no file outside `canworks/` is created or modified

#### Scenario: Deploy tool reads the result
- **WHEN** `canworks-deploy --config <project>/canworks/canworks.json` runs on a saved config
- **THEN** its checks pass with no change to the file

### Requirement: Changes made outside the configurator
If `canworks/canworks.json` changed on disk after the configurator loaded it, saving SHALL NOT overwrite it without the user confirming, and the user SHALL be able to reload the file from disk instead.

#### Scenario: Edited in a text editor meanwhile
- **WHEN** the file was edited by hand after the page loaded and the user presses save
- **THEN** the configurator says the file changed on disk and offers to reload or overwrite

### Requirement: PDO timing from the EDS
For each PDO the configurator SHALL show the communication fields that the node's EDS defines for that PDO kind (TPDO: inhibit time, event timer, SYNC start; RPDO: event timer), with the EDS default as the empty field's placeholder and times in milliseconds. A field the EDS marks read-only SHALL show its value and not be editable. A field the EDS does not define SHALL not be shown. The COB-ID field SHALL offer "auto" and show the COB-ID it resolves to.

#### Scenario: TPDO with an inhibit time
- **WHEN** the user enters 10 ms as the inhibit time of a TPDO whose EDS defines 0x1800 sub 3 `rw` with default 0
- **THEN** the saved PDO has `"inhibit_time_us": 10000`

#### Scenario: Read-only RPDO transmission type
- **WHEN** a node's EDS marks 0x1400 sub 2 `ro` with default 255
- **THEN** the RPDO's transmission type shows "255 (fixed by the EDS)" and cannot be changed

### Requirement: SDO variables table
For each node the configurator SHALL edit the `sdo_variables` list with one entry per variable: name, object (picked from the node's EDS or typed as index and subindex, with the type taken from the EDS), direction, location, period, trigger, status and abort code locations. The object picker SHALL list readable objects for a read entry and writable objects for a write entry, and SHALL refuse objects the EDS does not define. Each location SHALL have a Suggest button that picks a free location of the right area and size. A write entry to an object the bridge configures itself SHALL show the same warning as the bridge. The located variable declarations SHALL include each entry's value (IEC type of the object), trigger (`BOOL`), status (`USINT`) and abort code (`UDINT`), named after the node and the entry.

Each entry SHALL fit the node view's width without horizontal scrolling down to a 1280 px wide window: the fields SHALL wrap onto a second line instead of narrowing. The name input SHALL show at least 24 characters, each location input at least 9 characters next to its Suggest button, and the entry's remove button SHALL be visible without scrolling sideways. Field messages SHALL be shown on their own line under the entry, not inside another field's cell.

#### Scenario: Read the serial number
- **WHEN** the user adds a read entry on node 5, picks 0x1018 subindex 4 (`Serial number`, UNSIGNED32, `const`) and presses Suggest for the value and the status
- **THEN** the saved entry has `"type": "UNSIGNED32"`, `"direction": "read"`, a free `%ID` location and a free `%IB` status location, and the declarations add a `UDINT` and a `USINT` variable

#### Scenario: Write picker hides read-only objects
- **WHEN** the user adds a write entry and opens the object picker
- **THEN** objects the EDS marks `ro` or `const` are not listed

#### Scenario: Long name and all locations on a laptop screen
- **WHEN** a node has a read entry named `producer_heartbeat_time` with value, trigger, status and abort code locations, and the window is 1280 px wide
- **THEN** the whole name, every location (for example `%QX300.0`) and the remove button are visible without scrolling sideways

#### Scenario: Warning under the entry
- **WHEN** a write entry targets 0x1017, which the bridge configures itself
- **THEN** the warning is shown on a line under that entry and the object cell keeps showing only `0x1017:0`

### Requirement: NMT command field
The configurator SHALL show an "NMT command" field with a Suggest button next to each node's state byte field, saved as `nmt_command_location`, with a hint listing the command codes. The declarations SHALL include it as a `USINT` variable named after the node.

#### Scenario: Add an NMT command byte
- **WHEN** the user presses Suggest on node 23's NMT command field and saves
- **THEN** node 23 has `nmt_command_location` set to a free `%QB` location, and the declarations add `<name>_nmt : USINT` at that location

### Requirement: slcan adapter settings
The configurator SHALL offer the adapter types "CANable / serial (slcan)" and "SocketCAN (CAN HAT, candleLight/gs_usb, PEAK, vcan)"; for `slcan` it SHALL show the serial device (with `/dev/serial/by-id/` as the hint), interface name, bit rate and optional serial speed, hide `configure_link` and `restart_ms`, check the `slcan` adapter rules before saving, and say that slcan gives no bus error state. Switching type SHALL keep `interface` and `bitrate` and drop the fields the new type does not accept.

#### Scenario: Switch an existing config to slcan
- **WHEN** a config has a `socketcan` adapter on `can0` at 500000 with `configure_link: false`, and the user picks "CANable / serial (slcan)" and enters the device path
- **THEN** saving writes `{"type": "slcan", "device": "<path>", "interface": "can0", "bitrate": 500000}`

#### Scenario: Device path not absolute
- **WHEN** the user enters `ttyACM0` as the serial device
- **THEN** the page marks the field invalid and does not save until it is an absolute path such as `/dev/ttyACM0`

### Requirement: Configuration check and store settings
For each node the configurator SHALL show a "Skip download when unchanged (0x1020)" checkbox, saved as `config_check` (left out when not checked), and a "Save configuration on the device (0x1010)" choice listing "No" and each writable 0x1010 sub-index the node's EDS defines with its parameter name, saved as `store_configuration` (left out for "No"). When the EDS lacks a writable 0x1020 sub 1 and sub 2 the checkbox SHALL be disabled with a hint naming the missing object, and when it lacks a writable 0x1010 sub-index the choice SHALL be disabled the same way.

#### Scenario: Turn on the check and the save
- **WHEN** node 2's EDS defines writable 0x1020 sub 1 and sub 2 and 0x1010 sub 1, and the user ticks the checkbox and picks sub 1 "Save all parameters", then saves
- **THEN** node 2 has `"config_check": true` and `"store_configuration": 1`

#### Scenario: Device without a configuration date
- **WHEN** node 5's EDS has no object 0x1020
- **THEN** the checkbox is disabled and its hint says the EDS has no 0x1020

### Requirement: Device PDO mapping in the PDO editor
For each PDO the configurator SHALL show whether its mapping is written from the config or kept by the device, using the same rule as the bridge. When the node's EDS fixes the mapping, the PDO SHALL show "Set by the device" with its default mapping listed, the entry picker SHALL offer only the objects of that mapping, and no `mapping` field SHALL be saved. When the mapping is writable, the user SHALL be able to choose "Use device mapping", which saves `"mapping": "device"` and flags entries outside the default mapping. A device-mapped PDO SHALL offer "Map all", which adds every non-dummy object of the default mapping with suggested locations.

#### Scenario: Fixed PDO in the editor
- **WHEN** the user imports an EDS whose 0x1A00 is read-only with two UNSIGNED8 objects
- **THEN** TPDO 1 shows "Set by the device" with both objects, and "Map all" adds both as `%IB` inputs at the lowest free locations

#### Scenario: Switch a writable PDO to device mapping
- **WHEN** a writable TPDO has entries 0x4001 sub 0 and 0x4002 sub 0 and the EDS default maps only 0x4001 sub 0, and the user picks "Use device mapping"
- **THEN** the PDO saves with `"mapping": "device"` only after 0x4002 sub 0 is removed, and until then the entry shows an error listing the default mapping

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

### Requirement: Manual SDO and NMT in the online view
For each node the online view SHALL offer an SDO panel: pick an object from the node's EDS, or from the standard object dictionary when the node has no EDS (all objects, not only mappable ones), or type index and subindex, read it, and show the value decoded with the object's data type (numbers in decimal and hex, VISIBLE_STRING as text, other types as hex bytes), or the abort code with its CiA 301 text. When the runtime allows changes, the panel SHALL also write a value encoded from the object's type after a range check, warning before writing an object the bridge configures itself or one owned by an SDO variable; and the node SHALL have NMT buttons (start, stop, pre-operational, reset node, reset communication), with confirmation for stop, pre-operational and the resets, since each of those holds or interrupts the node. When the runtime does not allow changes, write and NMT controls SHALL be shown disabled with the reason.

#### Scenario: Read the serial number
- **WHEN** the user reads 0x1018 subindex 4 of node 3
- **THEN** the panel shows the serial number in decimal and hex

#### Scenario: Picker without an EDS
- **WHEN** node 49 has no EDS and the user opens the object picker
- **THEN** it lists the standard objects, and does not say "No EDS objects"

#### Scenario: Write blocked
- **WHEN** the runtime's `allow_changes` is false
- **THEN** the write button and NMT buttons are disabled and say that online changes are not allowed in this configuration

#### Scenario: Pre-operational asks first
- **WHEN** the user clicks Pre-operational for node 2
- **THEN** a dialog says the node's PDOs stop until it is started again, with Cancel as the default, and nothing is sent until the user confirms

### Requirement: PDO settings layout
Each PDO SHALL show its settings (number, COB-ID, transmission type and, where shown, the SYNC count, inhibit time, event timer or deadline, SYNC start, and mapping) as labelled fields with the label above the input and the hint below, aligned at the top of their row. Every input SHALL be wide enough to show its placeholder and the longest value of its choices without clipping. A setting the EDS fixes (read-only transmission type, device-set mapping) SHALL be shown as plain text with the reason, not as a disabled input. The device mapping objects SHALL be listed one per line, marking those the config uses.

#### Scenario: Fixed transmission type
- **WHEN** an RPDO's transmission type is read-only in the EDS with default 1
- **THEN** the PDO shows "Transmission type: 1: at SYNC, fixed by the EDS" in full, with the hint that the slave keeps its own value

#### Scenario: Fields line up
- **WHEN** the user opens a node with a TPDO whose number, COB-ID and transmission type are left to the EDS
- **THEN** the Number, COB-ID and Transmission type labels are on one line at the same height, each field shows its default in full ("EDS default (1: every SYNC)"), and the timing inputs show "EDS default" unclipped

### Requirement: Message bar
Messages about the user's actions that are not tied to one section (saved, sent, copied, added, and errors of a request) SHALL be shown in a message bar under the header and the simulation banner that stays in view while the page scrolls and has a close button. Information and done messages SHALL close by themselves after about 6 seconds; warnings and errors SHALL stay until closed or replaced. Switching view SHALL clear the bar. A removal message SHALL carry Undo.

#### Scenario: NMT command sent
- **WHEN** the user sends Start to node 2 in the online view
- **THEN** "Node 2: Start sent." is shown as a done bar and disappears after about 6 seconds without a page reload

#### Scenario: Leaving the view clears the message
- **WHEN** a message from the online view is shown and the user opens "Bus and master"
- **THEN** the message bar is hidden

#### Scenario: Errors stay until closed
- **WHEN** a save fails with an error
- **THEN** the error stays in the bar until the user closes it, saves again or switches view

#### Scenario: Error is announced
- **WHEN** a save fails
- **THEN** the bar has the alert role and a screen reader reads the message without the user moving focus

### Requirement: Theme setting
The page header SHALL offer a Light / Dark / Auto choice. Auto SHALL follow the operating system's light or dark setting and SHALL be the default. The choice SHALL be kept in the configurator's settings folder, not in the project or the browser, so it survives restarts of the configurator on a new port, and the page SHALL open in the kept theme without first showing the other one. The page SHALL declare the theme's `color-scheme` so the browser's own controls (checkboxes, dropdown lists, scrollbars) match it.

#### Scenario: Dark on a light OS
- **WHEN** the OS uses a light theme and the user picks Dark
- **THEN** the page, including its checkboxes and dropdown lists, switches to dark at once, and after the configurator is closed and started again the page opens dark

#### Scenario: Auto follows the OS
- **WHEN** the choice is Auto and the OS switches from light to dark
- **THEN** the page switches to dark without a reload

#### Scenario: Nothing written to the project
- **WHEN** the user changes the theme and saves the config
- **THEN** `canworks.json` and the project folder are unchanged by the theme choice

### Requirement: Fields and buttons fit their content
On every view, at window widths from 1000 px up, no input, dropdown or button SHALL clip its value, placeholder, selected choice or label, and no view SHALL need horizontal scrolling. Dropdowns SHALL be as wide as their longest choice up to the width of their column. A button SHALL NOT wrap its label. Buttons that belong to one row (move up, move down, remove; Read and Write) SHALL stay on one line, and an object picker's "by hand" index, subindex and Add controls SHALL stay together. Buttons in table rows SHALL be vertically centred with the row's text.

#### Scenario: Adapter type
- **WHEN** the bus page shows adapter type "SocketCAN (CAN HAT, candleLight/gs_usb, PEAK, vcan)" in a 1280 px window
- **THEN** the whole choice text is visible

#### Scenario: Startup SDO row buttons
- **WHEN** a node has four startup SDO writes
- **THEN** each row shows ↑, ↓ and ✕ side by side on one line

#### Scenario: Scan page button
- **WHEN** the scan finds a device with no matching EDS
- **THEN** its "Choose EDS…" button shows its label on one line

#### Scenario: Automatic check
- **WHEN** the browser tests open each view (start, bus and master, each node, declarations, online, scan, the EDS dialog) at 1000, 1280 and 1440 px
- **THEN** a check over the page finds no clipped field or button and no horizontal overflow

### Requirement: Readable problem messages
The Problems panel and the messages next to fields SHALL name the place of a problem in the user's terms (node ID and name, PDO kind and number, object index and subindex, SDO variable name) and SHALL NOT show the internal config path (such as `nodes[2]: tx_pdos[1]: entries[0]:`). Selecting a problem SHALL still move to and highlight its field, opening its tree entry and tab first. The same wording SHALL be used wherever the configurator shows a check message: the Trace view's and Frame lab's "decoding without the config's PDOs" notes, the message bar and dialogs. No message shown on the page SHALL contain a filesystem path of the config or project, on any operating system (a Windows path with a drive letter included), except where the path itself is the subject (the folder browser, the mode badge, the new-project dialog). An empty config SHALL be reported as "No nodes yet. Add a node from its EDS, or turn on Online access for a scan-only configuration." rather than as a schema error. An unexpected server error SHALL be shown as one sentence that points at the configurator's terminal, where the details are logged. The deploy tool's command-line messages are unchanged.

#### Scenario: Type does not fit the location
- **WHEN** node 5 (rtd) maps UNSIGNED8 object 0x6150:1 in TPDO 2 to `%IW320`
- **THEN** the Problems panel shows "Node 5 rtd, TPDO 2, 0x6150:1: type UNSIGNED8 (8 bit) does not fit location %IW320 (16 bit)" and clicking it opens node 5's PDOs tab with that entry's location field focused

#### Scenario: Trace note without a path
- **WHEN** the config has a type-does-not-fit error and the user opens a trace file
- **THEN** the Trace view's note reads "Decoding without the config's PDOs: Node 5 rtd, TPDO 2, 0x6150:1: type UNSIGNED8 (8 bit) does not fit location %IW320 (16 bit)" with no file path

#### Scenario: Windows config path
- **WHEN** the config is `C:\Users\me\cell\canworks.json` and has the type-does-not-fit error above
- **THEN** the message next to the location field and the Problems panel show no part of `C:\Users\me\cell\canworks.json`

#### Scenario: New config
- **WHEN** the user creates a new standalone config
- **THEN** the only problem reads "No nodes yet. Add a node from its EDS, or turn on Online access for a scan-only configuration."

### Requirement: Narrow window layout
From 800 px to 1100 px wide, the network tree SHALL fold into a rail at the left of the workspace tab. The rail SHALL show each network's initials and its nodes' IDs with their state icons and error counts. Picking a node in the rail SHALL open it. The rail's button SHALL open the full tree over the page, and picking an entry SHALL close it. Under 800 px the tree SHALL fold into a button at the top of the workspace tab that names the selected entry and shows the config's error count, and opens the tree over the page. The bottom panel SHALL stay, with its tab title showing the problem count. A node's error count SHALL stay next to the node's name in the tree.

#### Scenario: Problems at 900 px
- **WHEN** the window is 900 px wide and the config has 4 errors
- **THEN** the bottom panel's tab reads "Problems 4" without scrolling, and opening it lists them

#### Scenario: Tree at 900 px
- **WHEN** the window is 900 px wide and the user picks node 7 in the rail
- **THEN** node 7's page opens beside the rail

#### Scenario: Tree at 700 px
- **WHEN** the window is 700 px wide and the user opens the tree button and picks node 7
- **THEN** the tree closes and node 7's page uses the full width

### Requirement: Export DCF files
Each node's page SHALL have an "Export DCF" action next to "Remove node", above its tabs, and the header's Export menu SHALL offer "All DCFs" and, while a node page is open, "This node's DCF". The node's tree entry SHALL carry no action of its own: clicking anywhere on it opens the node and nothing else. Both SHALL run the `canopen-dcf-export` export on the config as currently shown on the page, saved or not, and offer the result as a browser download: `node_<id>.dcf` for one node, `<config folder name>_dcf.zip` holding every `node_<id>.dcf` for all. When the config has errors or a DCF fails validation, the configurator SHALL download nothing and SHALL show the messages in the Problems panel, replacing the panel's current list rather than adding to it, so the problem count stays the number of distinct problems. The actions SHALL NOT write any file in the project or config folder.

#### Scenario: Export one node
- **WHEN** the config is valid and the user clicks "Export DCF" on node 23's page
- **THEN** the browser downloads `node_23.dcf` and no file under the project changes

#### Scenario: Unsaved change is exported
- **WHEN** the user changes node 23's heartbeat to 200 ms without saving and exports it
- **THEN** the downloaded DCF has `ParameterValue` 200 on 0x1017

#### Scenario: Validation failure
- **WHEN** a DCF fails validation
- **THEN** nothing is downloaded and the Problems panel names the node, the DCF section and the key

#### Scenario: Clicking a node item never exports
- **WHEN** the user clicks the middle of "5 rtd" in the network tree, with the pointer resting on it
- **THEN** node 5's page opens, no download starts and the Problems panel is unchanged

#### Scenario: Failed export keeps the count
- **WHEN** the config has 4 errors and the user runs "All DCFs" from the Export menu
- **THEN** nothing is downloaded and the Problems panel still lists 4 problems, not 8

### Requirement: Export a DBC file
The page header SHALL have an "Export DBC" action. It SHALL run the `canopen-dbc-export` export on the config as currently shown on the page, saved or not, and offer the result as a browser download named `<config folder name>.dbc`. Next to the action the page SHALL offer the SDO option as a choice of "No SDO frames" (the default), "SDO: configured objects" and "SDO: all EDS objects"; the choice SHALL be remembered with the page's other UI settings, not in the config. In project mode the export SHALL use the project's located variables for signal names. When the config has errors, the configurator SHALL download nothing and SHALL show the messages in the Problems pane; warnings from the export SHALL be shown there after the download. The action SHALL NOT write any file in the project or config folder.

#### Scenario: Export
- **WHEN** the config is valid and the user clicks "Export DBC"
- **THEN** the browser downloads the DBC and no file under the project changes

#### Scenario: Unsaved change is exported
- **WHEN** the user adds TPDO 2 to node 5 without saving and exports
- **THEN** the downloaded DBC has the message for TPDO 2

#### Scenario: Include SDO frames
- **WHEN** the user picks "SDO: configured objects" and exports a config with SDO variables
- **THEN** the downloaded DBC has the SDO request and response messages for each node

#### Scenario: Config with errors
- **WHEN** the config has a duplicate node ID
- **THEN** nothing is downloaded and the Problems pane shows the error

### Requirement: LSS node settings
For each node the configurator SHALL show an "Assign node ID by serial number (LSS)" checkbox, saved as `lss.assign`, and a "Store node ID in the device" checkbox, saved as `lss.store`, which SHALL be unticked for a new node and disabled while the first is unticked. Unticked boxes SHALL be left out of the saved node, and an `lss` object with nothing in it SHALL be left out. While "Assign" is ticked the node's serial number field SHALL be required, `reset_communication` SHALL not be selectable as off, and the page SHALL say that the master gives the device this node ID at every start. When the node's EDS does not say `LSS_Supported=1` (left out or 0), both checkboxes SHALL be disabled and unticked, with the reason next to them as hint text ("This device's EDS has no LSS (LSS_Supported=1 missing)", see "One look for EDS limits"). A loaded node that still has an `lss` object SHALL show it as a problem with the bridge's message in warning colour and offer to remove it. Saving SHALL be refused until it is removed or the node gets an EDS with LSS.

#### Scenario: Turn on LSS for a node
- **WHEN** the user ticks "Assign node ID by serial number (LSS)" for node 12, enters serial number 0x1234 and saves
- **THEN** node 12 has `"lss": {"assign": true}` and `"serial_number"` 0x1234 (kept as typed, like the other identity fields), and no `lss.store`

#### Scenario: Assign without a serial number
- **WHEN** "Assign" is ticked for node 12 and its serial number is empty
- **THEN** the hand-off steps refuse the config and the serial number field says it is needed for LSS

#### Scenario: EDS without LSS
- **WHEN** the user adds a node whose EDS says `LSS_Supported=0`
- **THEN** both LSS checkboxes are disabled with the reason in hint text, and the saved node has no `lss`

#### Scenario: Leftover LSS settings
- **WHEN** a loaded config gives `"lss": {"assign": true}` for a node whose EDS says `LSS_Supported=0`
- **THEN** the reason is shown in warning colour with "Remove the LSS settings"

### Requirement: Unconfigured devices in the online view
The Nodes table SHALL have an **Unconfigured devices** panel, with and without a config. It SHALL be collapsed until changes are allowed or a search runs. It SHALL find a device without a node ID and show:
- its vendor ID, with the vendor name when an EDS gives it;
- its product code, revision and serial number;
- the best matching EDS from the project's `canworks/` folder or the EDS library, as text (product name and file name), with no picker of its own: after "Set node ID" the node's EDS is changed in the Nodes table.

It SHALL offer "Set node ID" and "Set bit rate" for the device. Both dialogs SHALL have a "Store in the device" checkbox that is unticked each time the dialog opens.

"Set node ID" SHALL suggest the lowest node ID that is neither configured nor the master's. With a config, after success, the device SHALL be listed as Not in config and the page SHALL offer Add to config with that ID and EDS, setting `serial_number` and `lss.assign`. "Set bit rate" SHALL say before sending that the device switches after its next power cycle and that the connection's bit rate must be changed to match. Without changes allowed, the panel's controls SHALL be disabled with Unlock… (see "Unlock from a locked control").

When the matching EDS does not say `LSS_Supported=1`, the device SHALL be added without `lss.assign`, and the page SHALL say that its EDS has no LSS, so the node gets no LSS assignment.

#### Scenario: Commission a new sensor
- **WHEN** the user finds a device without node ID, sets node ID 40 with "Store in the device" ticked, and presses Add to config
- **THEN** the runtime sets and stores node ID 40, and the draft gets node 40 with the matching EDS, the device's serial number and `"lss": {"assign": true}`, unsaved until the user saves

#### Scenario: Store unticked by default
- **WHEN** the user opens "Set node ID" a second time after storing once
- **THEN** the "Store in the device" checkbox is unticked

### Requirement: Object dictionary view
In the online view every node SHALL have an object dictionary tab: from its EDS for each configured node and each node with a matched or picked EDS, else from the standard object dictionary (see "Standard object dictionary without an EDS"). The tab SHALL show a tree of every object, grouped as communication (0x1000-0x1FFF), manufacturer (0x2000-0x5FFF) and profile (0x6000-0x9FFF), with index, subindex, name, data type, access, EDS default and device value. Each object SHALL be one row: a VAR object with its value in that row, an ARRAY or RECORD object as a foldable row with its sub-entries below it, each sub-entry named by its own name without the object's name in front. Groups and objects SHALL start folded, except that a search or filter unfolds the groups and objects that hold a match, and Read all unfolds as "Reading values in the object dictionary view" says. The tab SHALL use the full width of the online view, and long names SHALL wrap so that the row's buttons and watch box always stay inside the view without sideways scrolling. A search box SHALL filter by name or index.

#### Scenario: Browse node 3
- **WHEN** the user opens the object dictionary tab of node 3
- **THEN** the tree shows the objects from node 3's EDS in three folded groups, values empty until read

#### Scenario: Node without an EDS
- **WHEN** the user opens the object dictionary tab of a heard node that has no EDS
- **THEN** the tree shows the standard objects instead of saying the node has no EDS

#### Scenario: Object with sub-entries
- **WHEN** the user unfolds object 0x6110 "AI Sensor Type" of node 3
- **THEN** one row for the object and one row per sub-entry are shown, the sub-entries named "Number Of Entries", "AI0_Sensor_Type" and so on

#### Scenario: Long names
- **WHEN** a node's EDS has names such as `Store_Parameters_Field_Highest_subindex_supported` and the window is 1280 px wide
- **THEN** the names wrap and every row's Read and Edit buttons and Watch box are fully visible

#### Scenario: Search by index
- **WHEN** the user types `6110` in the search box
- **THEN** only object 0x6110 and its subindices are shown, unfolded

### Requirement: Reading values in the object dictionary view
The object dictionary tab SHALL offer "Read all" (the parameter read-all, with progress and cancel), "Read" on an object (all its readable sub-entries, in subindex order) and on a single entry, and a watch list of up to 32 entries refreshed at a period the user picks (500 ms or longer). Values SHALL be decoded as in the SDO panel. An entry whose value differs from its EDS default SHALL be marked, and an entry the configuration writes at boot or an SDO variable owns SHALL be marked as such. When Read all ends, every group that got a value SHALL unfold, and every object holding an entry that differs from its EDS default SHALL unfold; the other objects SHALL stay folded.

#### Scenario: Read all and see changed values
- **WHEN** the user presses Read all on node 3 and 0x6110 subindex 1 differs from the EDS default
- **THEN** progress is shown while reading, and afterwards the groups are unfolded, object 0x6110 is unfolded with subindex 1 marked as different from the default, and its object row says that one of its entries differs

#### Scenario: Read one object
- **WHEN** the user presses Read on object 0x6110 of node 3, which has subindices 0 to 8
- **THEN** 9 SDO reads are sent and all 9 values are shown

#### Scenario: Watch limit
- **WHEN** 32 entries are watched and the user adds another
- **THEN** the page refuses it and says at most 32 entries can be watched

### Requirement: Editing values in the object dictionary view
When the runtime allows changes, writable entries in the object dictionary tab SHALL be editable in place, using the SDO panel's write with its range check and its warnings for entries the configuration writes or an SDO variable owns. The editor SHALL show the entry's EDS LowLimit and HighLimit when the EDS has them, and a value outside them SHALL need a confirmation before it is written. When the entry's merged note has `values`, the editor SHALL offer them as a list with their meanings plus "Other value…" for any value in range. The value shown SHALL be read back after the write. When changes are not allowed, entries SHALL be read-only with the reason shown.

#### Scenario: Edit a parameter
- **WHEN** the runtime allows changes and the user changes 0x6110 subindex 1 of node 3 to 30
- **THEN** the value is written, read back and shown as 30

#### Scenario: Value outside the EDS limits
- **WHEN** the EDS gives 0x2010 subindex 1 a HighLimit of 100 and the user enters 150
- **THEN** the editor says the EDS allows 0 to 100 and writes only after the user confirms

#### Scenario: Read-only runtime
- **WHEN** the runtime's `allow_changes` is false
- **THEN** no entry is editable and the tab says online changes are not allowed

#### Scenario: Pick a mode by name
- **WHEN** the runtime allows changes and the user edits 0x6060 of a CiA 402 drive
- **THEN** the editor lists the modes of operation by name, and picking "profile velocity" writes 3

### Requirement: Parameters actions for a node
The online view SHALL offer per node: Back up (downloads the backup DCF), Compare (with a chosen backup file, the configuration or the EDS defaults, with an option for read-only entries; differences listed first), Restore from a chosen backup file, and Store on device. Back up and Compare SHALL work without `allow_changes`; Restore and Store SHALL be disabled with the reason when changes are not allowed.

#### Scenario: Back up from the browser
- **WHEN** the user presses Back up on node 23
- **THEN** progress is shown and the browser saves `node23-<name>-<date>-<time>.dcf`

#### Scenario: Compare with the configuration
- **WHEN** the user compares node 23 with the configuration
- **THEN** each value the configuration writes at boot is listed as equal or different with both values

### Requirement: Restore dialog
Restore SHALL first show the preview: planned writes with backup and device values, left-out entries with reasons, and identity differences. It SHALL offer "include communication objects" and "hold in PRE-OPERATIONAL while writing" (both off by default), and SHALL write only after the user confirms. A vendor ID or product code difference SHALL need a separate confirmation. The result SHALL list written, unchanged, skipped and failed entries and SHALL say the values are not stored on the device until Store on device is used.

#### Scenario: Restore to a replacement valve
- **WHEN** the user restores a node 23 backup to a new valve with the same product code and confirms
- **THEN** the differing values are written, the result lists them, and the page says they are not stored yet

#### Scenario: Different product
- **WHEN** the device's product code differs from the backup's
- **THEN** the dialog shows both values and the restore button stays disabled until the user ticks "restore to a different product"

### Requirement: Store on device dialog
Store on device SHALL be offered only when the node's EDS has 0x1010. It SHALL let the user pick the subindex (default 1, all parameters), SHALL say that storing writes the device's non-volatile memory, and SHALL write only after confirmation. It SHALL never run as part of another action.

#### Scenario: Store after restore
- **WHEN** the user opens Store on device for node 23 and confirms subindex 1
- **THEN** one "save" write is sent to 0x1010 subindex 1 and the result says whether the device accepted it

### Requirement: TIME period setting
The master settings SHALL have a TIME period field in milliseconds (100 to 3600000). Left empty, it SHALL save no `time_period_ms`. When set, the page SHALL show the TIME COB-ID that will be used (the master's `time_cob_id`, or 0x100) and SHALL warn when no node sets `time_cob_id` with the consumer bit.

#### Scenario: Turn on TIME
- **WHEN** the user enters 1000 in the TIME period field and saves
- **THEN** `master.time_period_ms` is 1000 and the page shows COB-ID 0x100

#### Scenario: Left empty
- **WHEN** the field is empty and the user saves
- **THEN** the saved `master` has no `time_period_ms`

### Requirement: Filters in the object dictionary view
Next to the search box the object dictionary tab SHALL offer filters that can be combined with the search: changed from the EDS default, writable, set by the configuration or an SDO variable, mapped in a PDO, not readable (an entry whose last read failed), and different in the last compare. For the standard object dictionary it SHALL also offer **Hide objects the device lacks**, on by default, which hides entries marked "not on this device" and objects whose entries are all marked so. A filter that needs values SHALL apply to the entries read so far.

#### Scenario: Only changed values
- **WHEN** the user has read all of node 3 and picks "changed from default"
- **THEN** only the entries whose value differs from the EDS default are shown, with their objects and groups unfolded

#### Scenario: Filter and search together
- **WHEN** the user picks "writable" and types `sensor`
- **THEN** only writable entries whose name or index contains "sensor" are shown

#### Scenario: Show what the device lacks
- **WHEN** node 49's standard dictionary has been read and the user turns off Hide objects the device lacks
- **THEN** the entries the device refused are shown again, marked "not on this device"

### Requirement: Value formats in the object dictionary view
Each numeric entry SHALL be shown in decimal by default and SHALL let the user switch it to hex or binary, the choice kept for that entry while the page is open. INTEGER entries in hex or binary SHALL show their two's-complement bits. For an object whose merged note has `bits` (see `canopen-device-notes`; built in at least for 0x1001 error register, 0x1002 manufacturer status register, 0x6040 controlword and 0x6041 statusword of CiA 402; an empty `bits` marks a bit field without names) the entry SHALL offer a bit view naming each set bit from those notes; a set bit without a name SHALL be shown by its number. An entry whose merged note has `values` SHALL show the meaning after the value, as `3 (profile velocity)`, and a value without a meaning as the number alone. An entry whose note has `unit` SHALL show it after the value, and with `scale` the scaled value too, as `1234 (12.34 bar)`. An entry's note `text` SHALL be shown under its name, with `details` and `manual` on hover.

#### Scenario: Hex view
- **WHEN** 0x6110 subindex 1 reads 30 and the user switches it to hex
- **THEN** it shows `0x001E`

#### Scenario: Statusword bits
- **WHEN** 0x6041 of a CiA 402 drive reads 0x0237 and the user opens its bit view
- **THEN** the bits ready to switch on, switched on, operation enabled, voltage enabled, quick stop and remote are shown as set

#### Scenario: Vendor bit field
- **WHEN** the notes of `valve.eds` give 0x2100 the bits 0 "coil A open" and 7 "overtemperature", and 0x2100 reads 0x81
- **THEN** its bit view shows "coil A open" and "overtemperature" as set

#### Scenario: Scaled value with unit
- **WHEN** the notes give 0x2200:1 the unit bar and scale 0.01, and it reads 1234
- **THEN** the entry shows `1234 (12.34 bar)`

### Requirement: PDO marks in the object dictionary view
For a configured node, an entry mapped in one of the node's PDOs in the configuration (a config-written mapping or a device mapping the configuration names) SHALL be marked with the PDO and the bits it takes, such as "TPDO2 bits 16-31", and the mark SHALL name the PLC location. Reading such an entry SHALL still use SDO.

#### Scenario: Mapped input
- **WHEN** node 3's TPDO1 maps 0x7130 subindex 1 in bits 0-15 to `%IW100`
- **THEN** 0x7130 subindex 1 is marked "TPDO1 bits 0-15, %IW100"

#### Scenario: Scanned node
- **WHEN** the tab belongs to a scanned node that is not in the configuration
- **THEN** no entry has a PDO mark

### Requirement: Watch list kept on this PC
The watch list SHALL be kept per project folder and node in the configurator's settings on this PC (not in the project) and SHALL come back when the page or the configurator is opened again, without the values. For each watched entry it SHALL show the value, its age, a mark for a few seconds after the value changed, and the minimum and maximum since watching started (numeric entries), with a button that resets them. The list SHALL show the real time one round of reads took and say so when it is longer than the chosen period. When the node has periodic SDO variables, the list SHALL say that the watch reads go before them on the bus and may delay them.

#### Scenario: Watch list after reopening
- **WHEN** the user watches 0x7130 subindex 1 and 0x6110 subindex 1 of node 3, closes the configurator and opens the project again
- **THEN** the node's watch list holds those two entries and starts reading them when the online view is connected

#### Scenario: Slow cycle
- **WHEN** 32 entries are watched every 500 ms and one round of reads takes 800 ms
- **THEN** the list shows that a round takes 800 ms, longer than the chosen 500 ms

#### Scenario: SDO variables on the node
- **WHEN** node 23 has an SDO variable read every 100 ms and the user watches an entry of node 23
- **THEN** the watch list says that its reads go before the program's SDO variable reads

### Requirement: Watch graph
The watch list SHALL offer a graph of its numeric entries against time, updated with each round of reads, holding at least the last 10 minutes while the page is open, with each entry turned on or off in the graph. The graph SHALL use the same plotting as the trace graphs.

#### Scenario: Plot two entries
- **WHEN** two numeric entries are watched every second and the user opens the graph
- **THEN** both entries are plotted against time and a new point is added every second

#### Scenario: String entry
- **WHEN** a VISIBLE_STRING entry is watched
- **THEN** it is listed in the watch list but offered no graph line

### Requirement: Keep a live value in the configuration
After a successful write in the object dictionary tab of a configured node, the page SHALL offer "Keep in configuration", which adds a startup SDO with the read-back value for that entry to the node in the draft configuration, or changes the value of the node's startup SDO for that entry when it has one, unsaved until the user saves. It SHALL be offered only for entries a startup SDO may write (a numeric type, writable access) and SHALL be refused, naming the reason, for an entry an SDO variable owns, for an object the bridge configures itself, and for an entry another setting of the configuration writes. It SHALL never write the device's non-volatile memory.

#### Scenario: Keep a tuned value
- **WHEN** the user writes 30 to 0x6110 subindex 2 of node 3, which has no startup SDO for it, and presses Keep in configuration
- **THEN** node 3 gets a startup SDO 0x6110 subindex 2 UNSIGNED16 30, the configuration shows as unsaved, and nothing more is sent to the node

#### Scenario: Startup SDO already there
- **WHEN** node 3 already has a startup SDO 0x6110 subindex 1 with value 30 and the user writes 40 and presses Keep in configuration
- **THEN** that startup SDO's value becomes 40 and no second entry is added

#### Scenario: Heartbeat object
- **WHEN** the user writes 0x1017 of node 3 and looks for Keep in configuration
- **THEN** it is not offered, saying the bridge sets 0x1017 itself from the node's heartbeat setting

### Requirement: Read or write any entry
The object dictionary tab SHALL have a row where the user enters an index, a subindex and optionally a data type, and reads or (when changes are allowed) writes that entry, also when the node's EDS does not list it. A value read without a type SHALL be shown as hex bytes.

#### Scenario: Entry not in the EDS
- **WHEN** the user reads 0x2100 subindex 3 of node 23, which its EDS does not list, without a type
- **THEN** the value is read and shown as hex bytes, or the abort code and its text are shown

### Requirement: Compare marks in the object dictionary view
After a compare on the node's Parameters tab, the object dictionary tab SHALL mark each compared entry as equal, different (with the reference value in the mark's text) or not readable, name the reference (backup file name, configuration or EDS defaults) above the tree, and offer to clear the marks. The marks SHALL last until the page is reloaded, the user clears them or another compare of the node is made.

#### Scenario: Differences from a backup
- **WHEN** the user compares node 23 with `node23-valve.dcf` on the Parameters tab and 0x2010 subindex 1 differs
- **THEN** the object dictionary tab marks 0x2010 subindex 1 as different from the backup value and the filter "different in the last compare" shows it

### Requirement: Copy and save the object dictionary rows
The object dictionary tab SHALL copy the rows it shows to the clipboard as tab-separated text and save them as a CSV file, with the columns entry, name, type, access, EDS default, value, and marks. Folded objects SHALL be included; rows hidden by search or filter SHALL be left out.

#### Scenario: Save changed values
- **WHEN** the filter "changed from default" is on and the user saves CSV
- **THEN** the file holds one line per changed entry, with a header line

### Requirement: Copy as ST call
The object dictionary tab SHALL offer "Copy as ST call" for a selected entry. It SHALL copy Structured Text that declares an instance of the matching block and calls it with the node ID, index and subindex filled in: `CO_SDO_READ_REAL`/`CO_SDO_WRITE_REAL` for REAL32 and REAL64, `CO_SDO_READ_STRING`/`CO_SDO_WRITE_STRING` for VISIBLE_STRING, `CO_SDO_READ_BYTES`/`CO_SDO_WRITE_BYTES` for OCTET_STRING, DOMAIN and integers wider than 4 bytes, and `CO_SDO_READ`/`CO_SDO_WRITE` for every other type, with the `UDINT_TO_<type>` conversion of a read's `DATA` in a comment and a write's `DATA` converted with `<type>_TO_UDINT` and its `SIZE` set to the type's size. Every call SHALL pass `LINK := canworks.link`. It SHALL offer the read call for readable entries and the write call for writable ones, and both when both apply. With several networks the call SHALL set `NETWORK` to the number of the network the online view talks to, with its name in a comment, and the instance name SHALL include the network's name. The entry row for any index and subindex SHALL offer the same, using `CO_SDO_READ`/`CO_SDO_WRITE` when no type is given.

#### Scenario: INTEGER16 entry
- **WHEN** the user picks "Copy as ST call", read, on node 5's 0x6401 subindex 1 (INTEGER16, `ro`)
- **THEN** the clipboard holds a declaration of a `CO_SDO_READ` instance, a call with `NODE := 5, INDEX := 16#6401, SUBINDEX := 1`, `LINK := canworks.link`, and a comment showing `UDINT_TO_INT(...DATA)`

#### Scenario: Device name
- **WHEN** the user picks "Copy as ST call" on 0x1008 subindex 0 (VISIBLE_STRING, `const`)
- **THEN** only the read is offered and it uses `CO_SDO_READ_STRING`

#### Scenario: Node on the second network
- **WHEN** the online view talks to `drives`, the second of two networks, and the user copies the read call for node 2's 0x1017 subindex 0
- **THEN** the clipboard declares `rd_drives_n2_1017_0 : CO_SDO_READ;` and calls it with `NETWORK := 1 (* drives *), NODE := 2, INDEX := 16#1017`

### Requirement: Choose what is simulated
The **Bus and master** page SHALL have a **Network** choice, **Real** or **Simulated** (`adapter.simulate`), and each node SHALL have a **Simulated** switch (the node's `simulate`) on its General tab, with **Simulate all** and **Simulate none** buttons on Bus and master. In the network tree a simulated node SHALL have a hollow mark and "(simulated)" in its accessible name, and on a simulated network a node switched off SHALL be drawn dashed and named absent. Choosing a simulated network SHALL keep the adapter settings. Simulating anything SHALL turn on online access with **Allow changes** when it is off (saying so), and every page SHALL show a banner naming what is simulated (the network, or the simulated node IDs on the real network) and that the configuration must not be uploaded to a machine as it is.

#### Scenario: Simulated network
- **WHEN** a user chooses **Simulated** network in a project with online access off
- **THEN** the saved config has `adapter.simulate: true`, its adapter settings unchanged, online access on with **Allow changes**, every node of that network has the hollow mark in the tree, and every page shows the banner

#### Scenario: One device on the real network
- **WHEN** a user keeps the **Real** network and switches on **Simulated** for node 5 only
- **THEN** the saved config has `"simulate": true` on node 5 only, node 5 alone has the hollow mark, and the banner says node 5 is simulated on the real network

#### Scenario: Absent node
- **WHEN** the network is simulated and the user switches **Simulated** off for node 7
- **THEN** node 7's entry is drawn dashed and its accessible name says it is absent

### Requirement: Simulation view
The configurator SHALL have a **Simulation** tool tab, in both workspaces of a config. It shows the simulated devices of the connection in the connection bar: a runtime's, or a CANopen simulator's. The view SHALL have no connect form, target choice, address or token field and no Connect button of its own, and no connection line that repeats what the connection bar says; it SHALL show only what is particular to simulation (nothing simulated on the runtime, read-only and why). It shows, per simulated device, whether it runs on a simulated or a real network, its NMT and power state, injected faults and the objects it carries in PDOs with live values, refreshed at least twice a second.

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
- **WHEN** the user connects to a CANopen simulator at 127.0.0.1:7532 through Connect… in the connection bar and opens Simulation
- **THEN** the view shows that simulator's devices, and the connection bar names the simulator and offers Disconnect

### Requirement: Scenarios in the configurator
The Simulation view SHALL list the scenarios of the simulation file, let a user create and edit them as a list of steps with checking, start and stop them, and show the running step, the time and the result of each expect, with failed expects showing the condition and the value seen.

#### Scenario: Run a scenario
- **WHEN** a user starts the scenario `sensor-break` from the view
- **THEN** the view shows each step as it runs and the scenario's result when it ends

### Requirement: Checks across networks in the configurator
Address suggestions SHALL skip locations used by any network, and Validate before save SHALL report the cross-network checks (duplicate names, shared interfaces or serial devices, IEC location clashes) with the network names in each message.

#### Scenario: Suggested address on the second network
- **WHEN** network `io` uses `%IW100` and the user asks for a suggested address for a 16-bit input on network `drives`
- **THEN** the suggestion is not `%IW100`

### Requirement: Online access for all networks
The Online access settings SHALL be shown once for the whole config, not per network.

#### Scenario: Online access with two networks
- **WHEN** a config has two networks and the user turns Online access on
- **THEN** the saved version 2 file has one top-level `diagnostics` object

### Requirement: Exports per network in the configurator
The configurator's DBC export SHALL export the network of the open tab. Its DCF export SHALL export the open tab's nodes, or every network into per-network folders when the user chooses all.

#### Scenario: DBC of the open tab
- **WHEN** the `drives` tab is open and the user exports a DBC file
- **THEN** the file describes only `drives`' nodes and is named after the network

### Requirement: Network role switch
Each CANopen network SHALL have a role, master or slave, set from **Role** on its bus page or from the role item of its network menu in the tree. Switching a network with nodes to slave SHALL ask before dropping the master settings and nodes; switching back SHALL start with an empty master network.

#### Scenario: Switch to slave
- **WHEN** the user sets a new network's role to slave
- **THEN** the network's tree entries become Bus and the slave device, and Bus shows the adapter settings

### Requirement: Slave device page
The slave device page SHALL edit node ID (or LSS), the EDS (choose a file, or build one), the bound objects with their PLC locations, `inputs_on_loss` and the status and EMCY locations. Object rows SHALL come from the EDS, show the direction from its access type, and offer only matching PLC areas. The EDS SHALL be an EDS field (see "One EDS field"); its dialog SHALL list the EDS files generated for a slave of this config under **Built here** and import with the slave's EDS lint.

#### Scenario: Bind an object
- **WHEN** the user adds 0x2100:1 (access `ro`, UNSIGNED16) from the EDS
- **THEN** the row suggests a free `%QW` location and refuses an `%I` one

#### Scenario: Choose a library EDS for the slave
- **WHEN** the slave has no EDS, an EDS library is set, and the user presses Choose EDS…, picks a library file and presses Use
- **THEN** the file is imported with the slave's EDS lint, the EDS field shows its product name and file name, and the object list offers its objects

#### Scenario: Generated EDS comes first
- **WHEN** the config has a generated `openplc-slave.eds` and two node EDS files, and the user opens Change EDS… on the slave page
- **THEN** `openplc-slave.eds` is under Built here, above In this project, and selected

### Requirement: Build the slave EDS in the configurator
The page SHALL have an object list editor (name, type, direction, default, limits), identity fields and a layout choice, and SHALL generate the EDS with the same generator as `slave-eds` into the project's `canworks/` folder, then offer to bind every generated object to suggested locations.

#### Scenario: Build and bind
- **WHEN** the user enters four objects, generates and accepts the suggested bindings
- **THEN** `canworks/` has the EDS and the config binds all four objects

### Requirement: Export the slave EDS
The page SHALL have an **Export EDS** button that saves the slave's EDS for import into the other master's tool, with a file name from the device name.

#### Scenario: Export
- **WHEN** the user clicks **Export EDS**
- **THEN** a save dialog offers the EDS the bridge runs

### Requirement: Export network documentation
The page header SHALL have an "Export documentation" action. It SHALL run the `canopen-network-docs` export on the config as currently shown on the page, saved or not, for all networks, and offer the result as a browser download named `<config folder name>.html`. In project mode the export SHALL use the project's located variables for PLC variable names and the project's task interval as the PLC cycle. When the config has errors, the configurator SHALL download nothing and SHALL show the messages in the Problems pane; warnings from the export SHALL be shown there after the download. The action SHALL NOT write any file in the project or config folder.

#### Scenario: Export
- **WHEN** the config is valid and the user clicks "Export documentation"
- **THEN** the browser downloads the HTML document and no file under the project changes

#### Scenario: Unsaved change is documented
- **WHEN** the user adds node 7 without saving and exports
- **THEN** the downloaded document has a section for node 7

#### Scenario: Config with errors
- **WHEN** the config has a duplicate node ID
- **THEN** nothing is downloaded and the Problems pane shows the error

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

### Requirement: Frame inspector panel
In the Trace view, selecting a frame in the Chronological or By identifier view SHALL show the inspector docked beside or under the view (see "Docked inspector and transmit pane"). The inspector SHALL have the four layers of the `canopen-frame-explain` model:
- the meaning;
- the identifier bits split into function code and node ID;
- a data grid with one row per byte (most significant bit on the left, CANopen bit number on each bit, each bit coloured by its field);
- the field list with values and working;
- the wire strip with framing, stuff bits marked, the bus level line and the timing figures.

Pointing at or focusing a bit or field SHALL show its explanation in a box that stays in view. It SHALL highlight the same bits in every layer (a data bit in the grid and on the wire, a field's bits in the grid). Every bit SHALL be reachable with the keyboard.

The panel SHALL follow the selected frame when the user moves through the list with the arrow keys. When the panel moves to a newer frame on its own, it SHALL keep **About this kind of message** open or closed as the user left it; for a newer frame of the same identifier it SHALL also keep the explained field, its scroll position and focus. It SHALL offer the frame's SDO conversation, SYNC cycle or boot story where one exists, and Explain in Frame lab and Send… (see "Explain in Frame lab" and "Send… adds to the transmit list"). The same inspector component SHALL serve the Frame lab. It SHALL work on opened trace files without a runtime, offline, in light and dark themes and at phone width.

#### Scenario: Point at a data bit
- **WHEN** the user points at bit 2 of byte 0 of node 5's TPDO1, whose first byte is mapped to `%IB100`
- **THEN** the box names the bit, its value, "bit 2 of `%IB100`", the object and the wire bit number, and that bit is highlighted in the grid and on the wire strip

#### Scenario: Keyboard
- **WHEN** the user tabs into the data grid and moves with the arrow keys
- **THEN** each focused bit is explained in the box

#### Scenario: Same inspector in the Frame lab
- **WHEN** the user explains frame `185#2500EA00` in the Frame lab and the same frame in a trace
- **THEN** both inspectors show the same layers, fields and wire bits

#### Scenario: About stays open while live
- **WHEN** the user selects node 32's heartbeat row while recording, opens About this kind of message, and new heartbeats arrive
- **THEN** the section stays open, and it is still open when the user selects another row

### Requirement: Sequences in the Trace view
The Trace view SHALL have a Sequences tab listing SDO conversations and boot stories with filters by node and result, and a SYNC cycle timeline with stepping and a jump to the slowest cycle, as the `canopen-bus-trace` capability describes. Sequence diagrams and timelines SHALL be drawn without a third-party library, and every step SHALL open its frame in the inspector panel.

#### Scenario: From a conversation to the frame
- **WHEN** the user clicks the abort arrow of an SDO conversation
- **THEN** the inspector panel opens on that abort frame with its abort code explained

### Requirement: Frame lab view
The Frame lab SHALL be a tool tab in every workspace that works without a connection and without a trace. It SHALL:
- accept a frame typed as identifier and data or pasted in candump syntax;
- offer example frames and the frame builder of the `canopen-frame-explain` capability;
- show the result in the shared inspector at the network's bit rate, with a bit rate picker.

The example frames SHALL come from the open configuration (saved or not). In Commission a device they SHALL come from the EDS files of the nodes on the Nodes tab: each node's boot-up, heartbeat, and SDO read of 1018h:01 with its answer.

The Frame lab SHALL have an arbitration demo: two frames chosen by the user are shown sent at the same time bit by bit. The demo SHALL show each sender's bit, the bus level, the bit where the sender of a recessive bit reads a dominant level and stops, and which frame wins.

The Frame lab SHALL accept a frame from the trace with its context (see "Explain in Frame lab"). It SHALL send nothing to the bus itself and SHALL say so. Its only route to the bus SHALL be **Send…**, which adds the frame to the transmit list without sending it. None of its other controls SHALL be labelled as sending (the arbitration demo's button is "Run both").

#### Scenario: Paste a frame
- **WHEN** the user pastes `705#7F` in the Frame lab
- **THEN** it is explained as node 5's heartbeat in Pre-operational

#### Scenario: Arbitration
- **WHEN** the user picks node 5's TPDO1 (0x185) and node 3's TPDO1 (0x183) for the arbitration demo
- **THEN** the demo shows both identical up to identifier bit 2, node 3's frame driving it dominant there, node 5's sender stopping, and 0x183 winning

#### Scenario: Example frames follow the config
- **WHEN** the user adds node 7 without saving and opens the Frame lab
- **THEN** the example frames include node 7's boot-up, heartbeat, SDO read of 1018h:01 and its PDOs

#### Scenario: Examples in Commission a device
- **WHEN** the Nodes tab of Commission a device has node 12 with an EDS from the library
- **THEN** the Frame lab's example frames include node 12's boot-up, heartbeat and SDO read of 1018h:01 with the EDS's object name

#### Scenario: Bus after the deciding bit
- **WHEN** the arbitration demo runs `185#` against `183#`
- **THEN** after identifier bit 2 the Bus row shows the bits of 0x183 only (identifier bits 1 and 0 are 1 and 1), and node 5's row shows that it has stopped

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

### Requirement: Confirmation dialogs default to the safe choice
In every confirmation dialog the safe choice (Cancel, or keep) SHALL be the default and SHALL receive focus when the dialog opens, so Enter never removes, discards, overwrites, resets or stores anything; the destructive choice SHALL be styled as destructive and SHALL NOT be the first button; Escape SHALL cancel. Dialogs that collect input (new project, restore) SHALL focus their first field, with the action button last.

#### Scenario: Enter keeps the node
- **WHEN** the user clicks "Remove node" and presses Enter
- **THEN** the dialog closes and the node is still there

#### Scenario: Close without saving
- **WHEN** the user clicks Close with unsaved changes
- **THEN** the dialog offers Cancel (focused) and "Close without saving", and only the latter discards the draft

### Requirement: Undo
Edits of the draft SHALL be undoable with Ctrl+Z (Cmd+Z on macOS) and redoable with Ctrl+Shift+Z, as whole steps (one typed value, one removal, one added entry), across views, until the draft is reloaded from disk or the folder is closed. Removing a PDO entry, startup SDO write, SDO variable, slave object, descriptor object or gateway route SHALL show a message naming what was removed with an Undo action that restores it with every setting it had. Online, trace and simulation actions are not part of the undo history.

#### Scenario: Undo a removed entry
- **WHEN** the user removes 0x6150:1 from TPDO 2, which had location %IW320 and a 500 ms timeout, and clicks Undo in the message bar
- **THEN** the entry is back in TPDO 2 with %IW320 and the 500 ms timeout

#### Scenario: Undo typing
- **WHEN** the user changes a heartbeat period from 100 to 250, clicks elsewhere and presses Ctrl+Z
- **THEN** the field shows 100 again and the Save button reads as dirty only if other edits remain

### Requirement: Header menus
The header SHALL show, left to right:
- the title;
- the workspace switch (see "Workspaces");
- the config's folder name with an unsaved mark;
- a settings menu with the theme choice;
- Reload from disk;
- Close;
- an Export menu (see "Export menu groups");
- the target's primary button (see "Header target action");
- Save.

The header SHALL have no Project menu; the editor project's actions are on the Project page (see "Editor project on the Project page").

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

### Requirement: Busy states and the Save button
Save, every export, Move into project, New editor project and Add node from EDS SHALL disable their control and show what is running ("Saving…", "Exporting…", "Adding…") until the request completes, and a second click meanwhile SHALL do nothing. The Save button SHALL read "Save" and be enabled whenever the draft differs from the file, with or without errors, and also when the draft equals the file but an OpenPLC project's editor files are out of date ("Out-of-date OpenPLC editor files"). It SHALL read "Saved" and be disabled when the draft equals the file, nothing is out of date and there are no problems, and "Saved, N problems" (disabled) when it equals the file, nothing is out of date and there are problems. The error count SHALL be shown in the Problems pane.

#### Scenario: Double click on Save
- **WHEN** the user clicks Save twice while the first save is still running
- **THEN** one save request is made and the button reads "Saving…" until it returns

#### Scenario: Clean draft
- **WHEN** the file on disk equals the draft, the check has no problems and no editor file is out of date
- **THEN** the button reads "Saved" and is disabled

#### Scenario: Dirty draft with an error
- **WHEN** the draft has one error and differs from the file
- **THEN** the button reads "Save" and is enabled

### Requirement: Accessibility check in the browser tests
The browser layout test SHALL run an automated accessibility audit (WCAG 2.1 A and AA rules) on every view it opens, in both themes, and SHALL fail on any finding of critical or serious impact, naming the rule, the element and the view. Text SHALL meet the 4.5:1 contrast ratio (3:1 for large text) in both themes, including state colours and the frame inspector's field tints, state icons SHALL meet 3:1, and interactive controls SHALL be at least 24 px tall.

#### Scenario: Regression caught
- **WHEN** a change adds a button without an accessible name to the online view
- **THEN** the layout test fails naming the rule and the button

#### Scenario: State colours
- **WHEN** the online view shows a node as OPERATIONAL in the light theme
- **THEN** the state text's contrast against its background is at least 4.5:1

#### Scenario: State icons
- **WHEN** the tree shows a PRE-OPERATIONAL node in the dark theme
- **THEN** its icon's contrast against the tree background is at least 3:1

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

### Requirement: Restore defaults button
The Parameters tab SHALL have "Restore defaults…" next to "Store on device…", offered only when the EDS has 0x1011 and enabled only with Allow changes. It SHALL ask first, offer "Reset the node afterwards" (ticked), and show whether the device accepted it.

#### Scenario: Restore defaults asks
- **WHEN** the user presses Restore defaults… on node 5
- **THEN** a confirmation names node 5 and 0x1011, and nothing is written unless the user confirms

### Requirement: PDO test tab
In Commission a device, each node SHALL have a "PDO test" tab. It SHALL load the node's PDO layout from the device, or from the configuration the user picks, and show:
- TPDOs with live decoded values, periods and counts;
- RPDOs with an input per entry and Send.

It SHALL offer NMT Start for the node, and SYNC with a period (off by default). Every control SHALL be disabled without Allow changes and say why. When another master is detected, the page SHALL ask before using `force`. Leaving the tab or closing the page SHALL stop the test and the SYNC. In config mode the tab SHALL NOT be shown, because the PLC runs the PDOs there.

#### Scenario: Set an output
- **WHEN** the user types 15 in RPDO1's 0x6200:01 input and presses Send
- **THEN** the frame is sent and the RPDO's sent count goes up by one

### Requirement: Commissioning log
In Commission a device, the session log (see "Session log") SHALL record every change made through the page:
- SDO write;
- NMT;
- LSS set ID, set bit rate and store;
- write configuration;
- restore and restore defaults;
- store;
- error history clear;
- note write, notes import and their undo, with the notes file's name.

"Save log" in the bottom panel's Log tab SHALL download `node<N>-commissioning-<time>.txt` with the device identity and EDS name at the top and the changes in order, and the bus events too when "Include bus events" is ticked (unticked by default).

The log SHALL belong to the commissioning session. Leaving Commission a device (Close, or "Add to a config…") with changes not saved SHALL ask whether to save the log first. The log SHALL then be cleared.

#### Scenario: Save the record
- **WHEN** the user gave the device node ID 12, wrote a configuration and stored it, then pressed Save log
- **THEN** the file lists those three changes in order with their results and no bus events

#### Scenario: Not carried into the config
- **WHEN** the user made two changes while commissioning, pressed "Add to a config…" and chose not to save the log
- **THEN** the config opens with an empty session log, and returning to Commission a device starts an empty log

#### Scenario: Note in the log
- **WHEN** the user writes a note for 0x2010 of node 12 while commissioning a device
- **THEN** the log has a change line naming 0x2010 and the notes file

### Requirement: Note editor
The Notes tab SHALL be the only place that opens the Note editor: each row's **Note** button or a click on the row, and **Add note…**. The editor SHALL edit one object or sub-object with text, details, unit, scale, a values table, a bits table and manual. For an object with a built-in note the editor SHALL start from the built-in fields and SHALL save only the fields the user changed into the device notes file. Emptying a field that shows a built-in or inherited value SHALL save that field as `null` (cleared); such a field SHALL show the built-in value greyed and marked hidden, with **Use built-in** to bring it back. The object dictionary view, the startup SDO editor and picker and the PDO entry picker SHALL show notes and SHALL NOT offer a Note button.

#### Scenario: Write a note while commissioning
- **WHEN** the user opens the Note editor of 0x2010 of node 7 from its Notes tab, types "Opening ramp of the valve", unit ms, and saves the project
- **THEN** `0x2010` in the EDS's notes file has that text and unit, and the object dictionary view shows them

#### Scenario: Override a built-in note
- **WHEN** the user adds the value -1 "vendor jog mode" to the values of 0x6060 in the Note editor and saves
- **THEN** the device notes file has only a `values` entry for 0x6060 and the built-in text is not copied

#### Scenario: No Note button in the PDO picker
- **WHEN** the user opens Add entry… on a TPDO of a node whose 0x2010 has a note
- **THEN** the picker shows the note's text under 0x2010's name and has no Note button

#### Scenario: Hide an inherited unit
- **WHEN** the user opens the Note editor of 0x6071 sub 0, which shows the built-in unit ‰, empties the unit and keeps the note
- **THEN** the device notes file has `"0x6071:0": {"unit": null}`, the object dictionary shows sub 0 without a unit, and reopening the editor shows ‰ greyed as hidden with **Use built-in**

#### Scenario: Bring the built-in value back
- **WHEN** the user presses **Use built-in** on that unit and keeps the note
- **THEN** the `null` is removed and sub 0 shows ‰ again

### Requirement: Note edits are draft edits
With a config open, a note edit SHALL mark the draft as changed, SHALL be written with Save, and SHALL be undoable like other draft edits. In "Commission a device", which has no Save, a kept note SHALL be written at once to the notes file next to the node's EDS file, with the same rules as Save (a new file starts from the skeleton; only changed fields are written). A banner SHALL name the file and offer **Undo**; Undo and Ctrl+Z SHALL put back the file as it was before the last note write of the page session. The Object dictionary, Parameters and PDO test tabs SHALL show the new note without reconnecting.

#### Scenario: Undo a note
- **WHEN** the user changes the text of 0x2010 in the Note editor of a config and presses Ctrl+Z
- **THEN** the earlier text is back and the draft is clean again if nothing else changed

#### Scenario: Write a note in Commission a device
- **WHEN** in "Commission a device" the user keeps the text "Opening ramp of the valve" for 0x2010 of node 12, whose EDS is `valve.eds` in the EDS library
- **THEN** `valve.eds.notes.json` in the EDS library has that text for 0x2010, the banner names that file and offers Undo, and the Object dictionary tab of node 12 shows the text

#### Scenario: Undo in Commission a device
- **WHEN** the user then presses Undo in the banner
- **THEN** the notes file is as it was before, and the Notes tab no longer lists 0x2010 under My notes

### Requirement: Notes in the other node lists
The PDO entry picker and the Parameters compare and restore lists SHALL show each object's note `text` under its name and the meaning and unit of each value from its merged note.

#### Scenario: Compare with meanings
- **WHEN** the user compares node 4 against a backup and 0x6060 differs (3 on the device, 1 in the backup)
- **THEN** the compare list shows `3 (profile velocity)` and `1 (profile position)`

### Requirement: Plain CAN networks in the configurator
Add network SHALL offer "Plain CAN" next to the other protocols. A plain CAN network page SHALL show the adapter settings, a "Listen only" switch, and the CAN messages page; it SHALL show no master, node or J1939 settings. Turning on "Listen only" while the network has send messages SHALL be refused with a message naming them.

#### Scenario: New plain network
- **WHEN** the user adds a Plain CAN network on `can1` at 250 kbit/s and saves
- **THEN** the file has a version 2 network with `"protocol": "none"` and that adapter, and Check reports no problems

### Requirement: CAN messages page
Every network SHALL have a CAN messages page with a receive table and a send table. A row SHALL edit one message (name, identifier in hex, extended, remote, mask for receive, DLC, timing for send, timeout and status locations for receive, and `pages` for a send message with switches) and SHALL open its signal rows (name, start bit, length, byte order, signed, scale, offset, unit, Switch, Page, PLC location, and valid location for receive). Signal rows SHALL be sorted with always-active signals first, then by page. The page SHALL draw the selected message's 8 bytes as a bit grid with each signal's bits marked, as the frame inspector does; for a message with switches the grid SHALL show one page at a time with a page picker. "Suggest addresses" SHALL fill free PLC locations of the right size, and SHALL leave switches of send messages with `pages` `all` or `rotate` without a location. A send message on an identifier the network's protocol uses SHALL be marked with the use and an "Override protocol" switch.

#### Scenario: Overlapping signals
- **WHEN** the user gives two signals of one message overlapping bits
- **THEN** both rows are marked with a problem naming the other signal, and the bit grid shows the overlap

#### Scenario: Send on a PDO identifier
- **WHEN** the user adds a send message 0x205 on a network where 0x205 is RPDO1 of node 5
- **THEN** the row says "RPDO1 of node 5" and Check reports a problem until "Override protocol" is on

#### Scenario: Pages in the bit grid
- **WHEN** the user marks `Page` as Switch, gives `Temp` Page `1` and `Press` Page `2` on the same bits, and picks page 2 in the grid
- **THEN** the grid shows `Page` and `Press`, no overlap problem is reported, and picking page 1 shows `Page` and `Temp`

### Requirement: Import a DBC into CAN messages
The CAN messages page SHALL have an "Import DBC…" file button that opens the system's file picker directly, with no dialog before it, the same way as "Import DBC…" on a J1939 network and "+ Add node…". The chosen file SHALL be kept with the draft and written into the config folder on Save when a network names it in `raw.dbc` or `j1939.dbc`; a different file of the same name already in the folder or in the draft SHALL ask whether to replace it or keep both (keep both gives the new file a `-2` suffix). The page SHALL then open the message picker, which SHALL list the file's messages with identifier, DLC, cycle and signal count and set each to Receive, Send or Leave out (Send preselected for messages sent by a node named `PLC` or like the network; Send not offered on a listen-only network). A message the network already has in that direction (same identifier and extended flag) SHALL be marked as already there and start as Leave out. Messages the file has but the import cannot take SHALL be listed under "Left out of the import". "Add picked messages" SHALL add the chosen messages as receive or send messages with free PLC addresses. Imported messages SHALL keep the DBC's names, layouts, scale, offset, unit, limits and multiplexing (simple and extended); a cycle time from the DBC SHALL become `period_ms` for send and three times the cycle as `timeout_ms` for receive. A message with several switches but no `SG_MUL_VAL_` SHALL be listed with a note that its multiplexing cannot be read. The imported file's name SHALL be stored in `raw.dbc`.

The page SHALL show the network's DBC file as read-only text ("Messages come from <file>." or "No DBC file yet."), marked as missing when the file is neither in the config folder nor in the draft, and SHALL offer "Pick messages…" to open the picker again on that file. Importing a file other than the one `raw.dbc` names, on a network that has raw messages, SHALL ask first, naming both files. Removing the network's last raw message SHALL clear `raw.dbc`. The J1939 and CAN messages pages SHALL use the same picker, differing only in their columns.

#### Scenario: Import two messages
- **WHEN** the user clicks Import DBC…, picks a DBC with messages `Joystick` (cycle 100 ms) and `Lamps` in the system file picker, chooses Receive for `Joystick` and Send for `Lamps`, clicks Add picked messages and saves
- **THEN** no dialog appeared before the file picker, the file has `Joystick` in `raw.rx` with `timeout_ms` 300 and `Lamps` in `raw.tx` with every signal at a location, `raw.dbc` names the file, the DBC file is in the config folder, and Check reports no problems

#### Scenario: Import a multiplexed message
- **WHEN** the user imports `Status` with switch `Page` and signals on pages 1 and 2 as receive
- **THEN** the file has `Page` with `multiplexer: true` and each page's signals with their `mux.values`, and Check reports no problems

#### Scenario: Same name, different file
- **WHEN** the config folder has `machine.dbc` and the user imports a different file also named `machine.dbc` and answers Keep both
- **THEN** the picker opens on `machine-2.dbc`, `raw.dbc` becomes `machine-2.dbc` after the import, and Save writes `machine-2.dbc` next to the unchanged `machine.dbc`

#### Scenario: A second DBC file
- **WHEN** the network has messages imported from `a.dbc` and the user picks `b.dbc`
- **THEN** the page asks whether to keep `a.dbc` or use `b.dbc` before anything is uploaded, and Keep `a.dbc` changes nothing

#### Scenario: Pick more messages later
- **WHEN** a saved network names `machine.dbc` with `Joystick` received, and the user clicks Pick messages…
- **THEN** the picker lists the file's messages with `Joystick` marked as already in received messages and set to Leave out

#### Scenario: Missing DBC file
- **WHEN** the config's `raw.dbc` names `old.dbc` and the config folder has no such file
- **THEN** the DBC line says `old.dbc` is not in the config folder and Pick messages… is not offered

#### Scenario: DBC line is not a text field
- **WHEN** the user opens the CAN messages page
- **THEN** the DBC file is shown as text with Import DBC… beside it, and there is no field to type a file name into

### Requirement: Raw messages in the online view
The online view SHALL list each raw message of the network with its last data, age, counter, timeout state and short-frame count (receive) or sent count and last error (send), and the numbers of program receivers and cyclic jobs with their drops.

#### Scenario: Message timed out
- **WHEN** a receive message with `timeout_ms` 300 has not arrived for a second
- **THEN** its row shows timed out and the age in milliseconds

### Requirement: Copy a raw message as ST
"Copy as ST call" on a raw message SHALL copy ST that receives it with `CAN_RECEIVE` and unpacks each signal with `CAN_GET_BITS` (receive), or packs each signal with `CAN_SET_BITS` and sends it with `CAN_SEND` or `CAN_SEND_CYCLIC` at its period (send), with the network's number set.

#### Scenario: Copy a receive message
- **WHEN** the user copies receive message `Joystick` on the second network
- **THEN** the clipboard holds a `CAN_RECEIVE` call with `NETWORK := 1` and `ID := 16#123`, and one `CAN_GET_BITS` line per signal with its layout

### Requirement: The check refuses what the bridge refuses
The configurator's check (and the deploy tool's, which is the same) SHALL refuse every config the bridge refuses at start. In particular:
- an adapter without an interface (or an slcan adapter without a device);
- a number outside its range whatever base it is typed in (decimal or `0x` hex): node IDs, heartbeat times, identity values, COB-IDs, TIME COB-ID;
- two PDOs on one network with the same COB-ID, naming both.

A heartbeat consumer timeout shorter than the node's heartbeat period SHALL be refused, as the bridge refuses it. Each message SHALL name the place in the user's terms and say what is allowed ("node ID 1 to 127", "COB-ID 0x185 is also node 5's TPDO 1"), not quote a schema rule or pattern.

#### Scenario: Missing interface
- **WHEN** the user adds a network and leaves the SocketCAN interface empty
- **THEN** Problems lists "network net2: the CAN interface is missing" and the hand-off steps refuse the config

#### Scenario: Hex out of range
- **WHEN** the user types `0x80` as a node ID
- **THEN** the field is marked "node ID 1 to 127" exactly as for `128`

#### Scenario: Duplicate COB-ID
- **WHEN** node 6's TPDO 1 COB-ID is set to 0x185, which node 5's TPDO 1 uses
- **THEN** both PDOs are marked and Problems names the clash

### Requirement: Folders the configurator cannot use
Opening a folder the configurator cannot read, or saving where it cannot write, SHALL end with a message naming the folder and the reason in plain words, and the configurator SHALL stay where it was (the start page or the open config), usable without a restart. A folder is added to Recent only after it opened. Open… SHALL refuse a folder that does not exist. New config… SHALL refuse a folder that already has a `canworks.json` or `project.json`, offering to open it instead. With "Also create an OpenPLC Editor project" it SHALL accept an existing folder that the editor project rules allow (`canopen-editor-project`, Never overwrite) and refuse any other, naming the file in the way. When Windows refuses to replace a file because another program holds it open, Save and Create SHALL try again for about 5 seconds before failing. The message SHALL then name the file and say that another program, often antivirus or a sync client, kept it open, and that trying again may work.

#### Scenario: Unreadable folder
- **WHEN** the user opens a folder without read permission
- **THEN** the page says it cannot read the folder, stays on the start page, Recent does not list it, and the next request works

#### Scenario: Mistyped standalone path
- **WHEN** the user types a path that does not exist in the Open… dialog and uses it
- **THEN** the page says the folder does not exist and nothing opens

#### Scenario: New config where one exists
- **WHEN** the user creates a new config in a folder that already has `canworks.json`
- **THEN** nothing is written and the page offers to open that config

#### Scenario: New config with an editor project in an existing empty folder
- **WHEN** `openplc-cli` is found, `~/plc/cell` exists and is empty, and the user creates a new OpenPLC config named `cell` in `~/plc` with the editor-project tick on
- **THEN** `~/plc/cell` becomes an OpenPLC Editor project with an empty config in its `canworks/` folder, and the page opens it as a project

#### Scenario: File held open on Save
- **WHEN** another program holds `canworks.json` open for 2 seconds while the user saves
- **THEN** the save succeeds after the program lets go

#### Scenario: File held open too long
- **WHEN** another program keeps `canworks.json` open for longer than the retry
- **THEN** Save fails with a message naming `canworks.json` and the held-open reason, the draft stays, and Save is offered again

### Requirement: Moving a config keeps its files
"Move into project…" and "New editor project…" SHALL take along every file of the standalone config: `canworks.json`, the EDS files, `simulation.json` and the slave EDS description, and the replace question SHALL name the project's `canworks/` folder.

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

A failed export (DCF, Documentation, Download for CODESYS, DBC, register map, Node-RED flow) SHALL report in the Problems panel only: its findings as Problems rows, and an error bar at the top of the panel naming the export and saying that nothing was downloaded. It SHALL NOT also show the page message bar. The panel SHALL open if it was closed and scroll into view, and the summary SHALL be announced as an alert. The summary SHALL go when the next check after an edit replaces the export's findings or when an export runs again. If the Problems panel is not shown on the current page, the failure SHALL be reported in the message bar instead.

A successful export SHALL report in the message bar; when it has warnings, the message SHALL give their number and Problems SHALL open with them.

#### Scenario: Repeated failing export
- **WHEN** the user runs a failing DBC export three times
- **THEN** Problems lists its findings once

#### Scenario: CODESYS export with no nodes
- **WHEN** the config's only network has no nodes and the user presses Download for CODESYS
- **THEN** no message bar is shown at the top, Problems lists the two findings under a bar "CODESYS export stopped. Nothing was downloaded. Fix the problems below and export again.", and nothing is downloaded

#### Scenario: Problems was closed
- **WHEN** the user has closed Problems and a DCF export fails
- **THEN** Problems opens and scrolls into view with the summary bar on top and focus stays on the export control

#### Scenario: Summary clears after an edit
- **WHEN** a failed export's summary is shown and the user adds a node
- **THEN** the next check replaces the list and the summary bar is gone

#### Scenario: Register map export findings
- **WHEN** the register map export stops with two findings
- **THEN** each finding is its own Problems row under the "Register map export stopped" summary, and the message bar stays hidden

#### Scenario: Export with warnings
- **WHEN** a DBC export succeeds with two warnings
- **THEN** the message bar says "Exported <file> with 2 warnings." and Problems is open with the two warnings

### Requirement: Bridge settings panel
A bridge project SHALL have a "Modbus bridge" page with Connections first, then: listen address and port, unit ID, word order, maximum clients; "Who may write" from the connections and the readers allowlist; watchdog time and client-loss action; status block, control block, live lists and SDO bridge locations, each with "Suggest".

#### Scenario: Add a live list
- **WHEN** the user adds a live list for network `field` and clicks Suggest
- **THEN** a free 16-byte input range is chosen and shown in the register map

### Requirement: Register map preview and export
The bridge page SHALL show the register map as a table (Modbus table, address, size, type, name, source) with a filter, the suggested client channels and "Pack for Modbus". It SHALL have no export buttons of its own: the map files are the Downloads of HMI, SCADA or script connections.

#### Scenario: Export the ST list
- **WHEN** the user downloads an HMI connection with `format` `st`
- **THEN** the browser gets the same file `canworks-deploy --export-modbus-map map.st` writes for this config

### Requirement: Changes are never sent twice
When a request to the runtime or the adapter gets no answer in time, the configurator SHALL send it again only for operations that only read. For any other operation it SHALL report that there was no answer and that the request may have been carried out, without sending it again.

#### Scenario: Slow answer to a reset
- **WHEN** the user sends RESET NODE to node 5 and the answer takes longer than the time limit
- **THEN** the configurator says there was no answer and the reset may have happened, and no second reset is sent

### Requirement: Confirm changes to a running node
The online view and the object dictionary view SHALL ask before an SDO write or an NMT command other than START to a node that is OPERATIONAL, naming the node, and SHALL send the request with `force` only after the user confirms.

#### Scenario: Write while running
- **WHEN** node 5 is OPERATIONAL and the user writes 0x2000:1 in the object dictionary view
- **THEN** a dialog says node 5 is running; on confirm the write is sent with `force`, on cancel nothing is sent

### Requirement: Session token never in a URL
The address the configurator opens in the browser SHALL carry a one-time code that the server swaps for its session cookie on first use and then forgets; the session token itself SHALL never be part of a URL.

#### Scenario: Opened link reused
- **WHEN** the start address is opened a second time
- **THEN** the server refuses the code and does not set a session cookie

### Requirement: Discovered and remembered runtimes in the connect box
With a config, the connect panel SHALL list runtimes found by discovery and remembered runtimes by name, next to typing an address. Choosing one SHALL connect by the automatic path choice; the user SHALL never have to choose between the local network and the link.

#### Scenario: Pick a discovered runtime
- **WHEN** the connect panel opens on a LAN with one advertised runtime
- **THEN** the runtime is listed by name and address, and choosing it and entering the token connects

#### Scenario: Same runtime from home
- **WHEN** the user picks the same runtime later from another network and the PC is paired and internet access is on
- **THEN** the connection is made with the same steps and the connection bar shows `internet direct` or `internet relayed`

### Requirement: Automatic pairing and paired PCs
After a successful direct login to a runtime that advertises a link ID, the configurator SHALL pair the PC with the same token in the background. The Online access section SHALL show **Reachable from other networks** (sets `remote_link.internet`), an optional relay URL list, and, on **Show paired PCs** when this PC knows the token and the runtime has a link ID, the paired PCs with **Remove**. When internet access is on and the PC has just been paired, the online view SHALL say once that this PC can now reach the runtime from other networks.

#### Scenario: Tick internet access
- **WHEN** the user ticks **Reachable from other networks**, saves and uploads
- **THEN** the config has `remote_link.internet` true and the runtime becomes reachable from other networks for paired PCs

#### Scenario: Remove a PC
- **WHEN** the user presses **Remove** next to a paired PC
- **THEN** that PC is removed and its open sessions end

### Requirement: Path and round trip in the online view
On a runtime connection, the connection bar SHALL show the path (`LAN`, `internet direct`, `internet relayed`) and the measured round trip, amber above 100 ms and red above 300 ms. LSS fast scan and a PDO test with a SYNC period SHALL ask for confirmation when the path is relayed or the round trip is above 100 ms.

#### Scenario: LSS on a relayed path
- **WHEN** the path is `internet relayed` and the user starts an LSS fast scan
- **THEN** a confirmation explains that the scan runs on the runtime but results and stop commands arrive late, and nothing is sent until the user confirms

#### Scenario: Round trip in the bar
- **WHEN** the runtime answers in 150 ms over `internet direct`
- **THEN** the connection bar shows "internet direct · 150 ms" in amber

### Requirement: Links table
Each CANopen master network SHALL have a Links page with one row per link: name, producer (node and one of its configured TPDOs, picked from lists), COB-ID (shown, taken from the producer), consumers, and on PLC stop (follow or keep). Adding a consumer SHALL offer the consumer node's RPDOs from its EDS that are not in its `rx_pdos` or another link, and SHALL fill its entries from the producer layout: objects of matching size from the consumer's RPDO-mappable objects to pick per position, or a dummy entry, or the device mapping when the consumer's mapping is fixed. The page SHALL show both layouts side by side as byte grids with each position's status. Each consumer row SHALL have a "watch producer" checkbox that adds or removes the producer in the consumer's `heartbeat_watch`, ticked by default when the producer has a heartbeat. On the producer's TPDO settings the configurator SHALL show which link it feeds and allow its entries without a PLC address.

#### Scenario: Add a link
- **WHEN** the user adds a link from node 10 TPDO 1 to node 20, picks RPDO 2 and 0x6411:1 for the first position and a dummy for the second
- **THEN** the saved config has the link with those entries, and node 20's `heartbeat_watch` lists node 10

#### Scenario: Size mismatch shown
- **WHEN** the user picks an 8-bit object for a 16-bit producer position
- **THEN** the position is marked, Problems names the link, the consumer and both sizes, and the hand-off steps refuse the config

#### Scenario: Producer removed
- **WHEN** the user deletes node 10's TPDO 1 that a link uses
- **THEN** the configurator asks to delete the link too, defaulting to cancel

### Requirement: Heartbeat watch setting
The node page's supervision section SHALL list the node's heartbeat watch entries (watched node from the network's nodes, timeout with the default shown when empty), and the check SHALL give the same messages as the bridge for them, including the 0x1016 capacity from the node's EDS.

#### Scenario: Default timeout shown
- **WHEN** node 20 watches node 10, which has `heartbeat_ms` 100, and the timeout field is empty
- **THEN** the field shows "default (300 ms)" and the saved entry has no `timeout_ms`

### Requirement: Links in the online view
With online access the Links page SHALL show for each link the NMT state of its producer and of each consumer from the live status, mark a link whose producer or any consumer is not OPERATIONAL, and show the producer TPDO's timeout state when it has `timeout_ms`.

#### Scenario: Consumer down
- **WHEN** the online view is open and node 20 of a link is lost
- **THEN** the link row is marked and node 20's cell shows no contact while node 10 stays OPERATIONAL

### Requirement: CiA 309-3 gateway settings
The Online access settings SHALL have a "CiA 309-3 gateway" part that turns `cia309` on and off and edits its plain port (or none), `max_clients`, "allow changes" and "allow force on running nodes" (both off by default; force with a warning that a standard tool can then stop nodes the program drives), and shows the network numbering, with optional explicit numbers per network. It SHALL say that the plain port listens on the PLC's loopback address only and that other machines connect through `canworks-diag gateway` with the project's token. The deploy tool's config check and the configurator's Check SHALL apply the bridge's `cia309` rules.

#### Scenario: Turn the gateway on
- **WHEN** the user turns on the CiA 309-3 gateway in a project with networks `io` and `drives` and saves
- **THEN** `canworks.json` has a top-level `cia309` object with `allow_changes` false, and the page shows `1 = io, 2 = drives`

#### Scenario: Network bind refused in Check
- **WHEN** a hand-edited project has `cia309.bind` set to `0.0.0.0`
- **THEN** Check reports `cia309.bind` with the bridge's message

### Requirement: Copy NMT calls as ST
The online view SHALL offer "Copy as ST call" next to each node's NMT buttons (start, stop, pre-operational, reset node, reset communication). It SHALL copy Structured Text that declares a `CO_NMT` instance and calls it with the node ID and the CiA 301 command code of that button, with the command's name in a comment, and SHALL be available whether or not the runtime allows changes, since it sends nothing. With several networks the call SHALL set `NETWORK` to the number of the network the online view talks to, with its name in a comment, and the instance name SHALL include the network's name. The master's "Master goes operational" setting SHALL say that, when it is off, the master stays pre-operational and no PDOs move, and that the bridge has no command that starts it; it SHALL offer no ST call for it.

#### Scenario: Stop call for a node
- **WHEN** the user picks "Copy as ST call" next to node 5's Stop button
- **THEN** the clipboard holds a declaration of a `CO_NMT` instance and a call with `NODE := 5, COMMAND := 2 (* STOP *)`

#### Scenario: Changes not allowed
- **WHEN** the runtime's `allow_changes` is false
- **THEN** the NMT buttons are disabled and "Copy as ST call" still copies the call

#### Scenario: Network start call
- **WHEN** the user turns "Master goes operational" off
- **THEN** the hint says the master stays pre-operational, no PDOs move and the bridge has no command that starts it, and no "Copy as ST call" is offered for it

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

### Requirement: EMCY COB-ID on the node page
The node page's Emergency (EMCY) section SHALL edit `emcy_cob_id`: Device (the default, saved as no field), EDS, or a COB-ID typed in hex or decimal. The Check SHALL give the bridge's messages for a COB-ID the bridge rejects. The online view's node row SHALL show the EMCY COB-ID in use, with its source, when it is not 0x80 + node ID, and SHALL mark it when the device reports its EMCY not valid.

#### Scenario: Default not saved
- **WHEN** the user leaves the EMCY COB-ID on Device and saves
- **THEN** the saved node has no `emcy_cob_id`

#### Scenario: Clashing COB-ID typed
- **WHEN** the user types node 6's TPDO 1 COB-ID as node 5's EMCY COB-ID
- **THEN** the Check reports node 5's `emcy_cob_id` clashing with node 6's TPDO 1

### Requirement: Nodes in commissioning
In Commission a device, the Nodes table (see "Nodes table") SHALL list the devices of this session: heard, found by a scan, given a node ID by LSS, or added with **Add node from EDS…**. **Add node from EDS…** SHALL open a dialog with the list of "One EDS dialog" and a node ID, and **Add node** SHALL add the device with that EDS, kept in this page only. It SHALL NOT open the system file picker before the dialog.

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

#### Scenario: Add node from the library
- **WHEN** the user presses Add node from EDS…, picks a library file, types 23 and presses Add node
- **THEN** node 23 is listed with that EDS, and no system file picker was opened

### Requirement: Network picker in online and trace views
The connection bar's network picker SHALL be the only network picker of the Commission pages, Trace, Simulation and Frame lab; no tab row or tool SHALL have its own. When the runtime reports more than one network, the picker SHALL list them; while not connected, it SHALL list the config's networks. The Commission pages, Trace and Simulation SHALL show and act on the picked network only. The picker SHALL start on the network of the entry selected in Configure's tree. In Commission, picking a tree entry on another network SHALL move the picker, and changing the picker SHALL select that network's tree entry.

#### Scenario: Online view of the second network
- **WHEN** the runtime runs `io` and `drives` and the user picks `drives` in the connection bar
- **THEN** the Commission workspace shows `drives`' bus state and nodes, the tree selects `drives`, and SDO, NMT, parameter and object dictionary actions go to `drives`

#### Scenario: One picker on Trace
- **WHEN** the virtual plant example is open, connected, on Trace
- **THEN** the only network control on the page is the connection bar's picker

### Requirement: Workspaces
With a config open, the header SHALL have a **Configure | Commission** switch:
- **Configure** SHALL show the config pages.
- **Commission** SHALL show the live view of the runtime as its **Nodes** tab, with the network tree (see "Tree in Commission with a config") and the node pages of the online view.

Commission a device SHALL open in Commission and SHALL show no switch. Switching workspace SHALL keep the draft, the connection and every running job. The workspace SHALL be kept on this PC and SHALL come back after a page reload. A link to a page of the other workspace (a problem, "Back to the online view") SHALL switch to that workspace. The page SHALL NOT show a note about the former Online view.

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

### Requirement: Connection bar
The connection bar SHALL be the one place on the page to connect and disconnect. It SHALL show under the header: always in Commission, and in Configure while connected and on the Trace and Simulation tool tabs. It SHALL show:
- the target;
- for an adapter, the bit rate and how it was confirmed;
- for a runtime, the path and round trip, and the network picker when the runtime has several networks;
- for a CANopen simulator, its address;
- the bus state and the frame and error frame counts;
- another master with what was seen, when one is seen;
- whether changes are allowed;
- **Connect…** while not connected, and **Disconnect** while connected.

While connecting it SHALL show the step of the bit rate check and **Cancel**. When a connection ends or stops answering it SHALL show the reason or the age of the last data. The bar SHALL be neutral while all is well and take the tint of its most severe state, as the message bars do: error for an ended or lost connection, bus-off, another master or a round trip above 300 ms; warning for error passive or a round trip above 100 ms. State changes SHALL be announced politely, and an ended connection as an alert.

#### Scenario: Visible on every page
- **WHEN** the user is connected to an adapter at 500 kbit/s and opens Frame lab
- **THEN** the bar still shows the adapter, "500 kbit/s" with how it was confirmed, the bus state and Disconnect

#### Scenario: Ended connection
- **WHEN** the adapter goes bus-off while the user is on a node's Object dictionary tab
- **THEN** the bar turns to the error tint, says the connection ended on bus-off, offers Connect…, and a screen reader announces it

#### Scenario: Slow path is a warning
- **WHEN** the round trip to the runtime is 150 ms
- **THEN** the bar has the warning tint and icon, not the error tint

#### Scenario: Neutral when well
- **WHEN** the connection is up with no errors and no other master
- **THEN** the bar uses no warning or error colour

#### Scenario: One Connect button
- **WHEN** nothing is connected and the user opens Nodes, Simulation and Trace in turn, in either workspace of a config
- **THEN** each page shows exactly one Connect… button, the one in the connection bar, and each page's own text says what it needs a connection for

### Requirement: Connect panel
**Connect…** in the connection bar SHALL open one connect panel, and the panel SHALL be the only place to connect. No page SHALL have a connect form or a button that opens the panel, except Trace's Start while not connected (see "Trace Start without a connection").

The panel SHALL list first up to three recent connections of this PC of the kinds it offers, each connectable with one click. A recent adapter connection SHALL still run the bit rate check and SHALL start with Allow changes off. Recent connections SHALL be kept in the configurator's settings on this PC without tokens. The panel SHALL NOT open by itself on entering Commission.

In Commission a device the panel SHALL offer two targets, **USB adapter** (the default) and **Adapter on another machine**:
- USB adapter: the found adapters with Refresh, or a typed target; the bit rate, picked by the user, with no detection and no default; "Device's node ID, to check the bit rate", for adapters that cannot report a sent frame; **Allow changes**, unticked; **Connect**;
- Adapter on another machine: one host combobox listing the adapter servers found on the local network and taking a typed host (`HOST[:PORT]`, port 7536 when not given); the server's adapter and bit rate once known; a token field inside the panel when this PC has no token for that host, the token then kept on this PC per host; **Allow changes**, unticked; **Connect**.

A refused bit rate check SHALL keep the panel open with the reason and the form filled in.

With a config the panel SHALL offer three targets, **Runtime** (the default), **CANopen simulator** and **Adapter on another machine**:
- Runtime: one host combobox listing the found and remembered runtimes and "Local simulator runtime" and taking a typed host, saying "Looking for runtimes…" while it searches; a token field inside the panel when this PC has no matching token; **Connect**;
- CANopen simulator: a running `canworks-canopen-sim` by address (`HOST[:PORT]`, port 7532 when not given) and its token when it was started with one, both kept on this PC per project folder; **Connect**;
- Adapter on another machine: as in Commission a device, with a warning when the server's bit rate differs from the network's.

A token SHALL never be asked in a second dialog over the panel. When the config's online access is off, the Runtime target SHALL say so and link to Configure → Project; the other targets SHALL still work.

The last target (including Runtime, CANopen simulator or Adapter on another machine) and bit rate SHALL be kept in the configurator's settings on this PC, never in a project.

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
- **WHEN** the user picks CANopen simulator in the panel, enters 127.0.0.1:7532 and presses Connect
- **THEN** the panel closes, the connection bar shows the simulator's address and Disconnect, and Simulation shows its devices

#### Scenario: Adapter on another machine
- **WHEN** the user opens Commission a device, picks Adapter on another machine, chooses the found server `linuxbox`, enters its token in the panel and presses Connect
- **THEN** the connection bar shows the adapter and `linuxbox` with the round trip, and the commission pages work on linuxbox's bus; the next time the token is not asked again

#### Scenario: Bit rate differs from the network
- **WHEN** with a config whose network runs at 250 kbit/s the user picks an adapter server serving 500 kbit/s
- **THEN** the panel warns that the server runs the bus at 500 kbit/s and the network is set to 250 kbit/s before Connect

### Requirement: One connection for every view
The Commission pages, Trace recording and its transmit list, the Simulation view and the PDO test SHALL use the connection in the connection bar. None of them SHALL have its own connect form, host, adapter, address or token field, or Connect button. Without a connection, each SHALL say in one line what it needs a connection for and that Connect… is in the connection bar. On a CANopen simulator connection, the Nodes table, Trace recording and the PDO test SHALL say that they need a runtime connection.

#### Scenario: Trace uses the open connection
- **WHEN** the user connected to a runtime in Commission and opens Trace in Configure and presses Start
- **THEN** recording starts through that runtime without asking for a host or token

#### Scenario: Trace without a connection
- **WHEN** nothing is connected and the user opens Trace
- **THEN** files can be opened and viewed, and Start is replaced by a note that recording needs a connection made with Connect… in the connection bar, with no button of its own

### Requirement: Allow changes in the connection bar
On an adapter connection, the connection bar SHALL show the lock's state with one button: "🔒 Read-only" with **Unlock…**, or "🔓 Changes allowed" with **Lock**. It SHALL NOT be a checkbox, and no label SHALL name the opposite of what its click does. Changes SHALL be off for every new connection. **Unlock…** SHALL ask before allowing changes; **Lock** SHALL go back to read-only without asking. Both SHALL apply to the open connection without reconnecting and keep focus on the bar's button. On a runtime connection, the bar SHALL show the runtime's own setting as read-only text with a lock and SHALL say that it is set in Configure → Online access and takes effect after an upload, with a link that opens that entry.

#### Scenario: Switch on an open adapter connection
- **WHEN** the user is connected read-only to an adapter, presses Unlock… in the connection bar and confirms
- **THEN** the bar shows "Changes allowed" with Lock, write controls on every page are enabled without reconnecting, and no "another master" message appears

#### Scenario: Read-only adapter bar
- **WHEN** the user is connected read-only to an adapter
- **THEN** the bar shows "Read-only" with an Unlock… button and no checkbox, and pressing Unlock… asks "Allow changes on this adapter connection?"; Cancel leaves it read-only

#### Scenario: Lock again
- **WHEN** changes are allowed on an adapter connection and the user presses Lock
- **THEN** the bar shows "Read-only" with Unlock… without asking, write controls show "Locked" with Unlock…, and the connection stays open

#### Scenario: Runtime decides
- **WHEN** the user is connected to a runtime whose config has allow changes off
- **THEN** the bar shows "Read-only (runtime setting)" with no button, and its link opens Online access in Configure

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
The page SHALL have a collapsible panel under the page, with its height kept on this PC. Its contents SHALL depend on the workspace:
- **Configure:** a **Problems** tab, with Allow overlap. It SHALL open by itself when problems appear after a save or check.
- **Commission a device:** a **Log** tab with the session log and **Save log**.
- **Commission with a config:** a **Log** tab (selected by default) and a **Problems** tab; Problems SHALL open by itself when a comparison action causes a problem.

Each tab title SHALL carry its count. There SHALL be no right-hand Problems column. While Problems has nothing and no log entry is new, the panel SHALL be a one-line strip with the tab titles and counts. A Log that has entries SHALL start collapsed and show its count in the strip. The resize handle SHALL look like a handle (a grip mark on a thin line), not like a scrollbar.

#### Scenario: Problems under the page
- **WHEN** the config has 4 errors in Configure
- **THEN** the panel's tab reads "Problems 4", the page uses the full width beside the tree, and clicking a problem goes to its field

#### Scenario: Log while commissioning
- **WHEN** the user gave a device node ID 12 by LSS in Commission a device
- **THEN** the Log tab lists the change, the Changes filter reads 1, and Save log downloads the log

#### Scenario: Problem after adding a found device
- **WHEN** the user adds a found node 9 whose EDS has no TPDO the config can map, and the check reports a problem
- **THEN** the Problems tab opens with that problem and the user stays in Commission

#### Scenario: Nothing to show
- **WHEN** a config without problems is open in Configure
- **THEN** the bottom panel is one line reading "Problems: none"

### Requirement: Trace toolbar and views
The Trace tool tab SHALL have one toolbar with:
- one Start / Stop button;
- Clear and Open…;
- a Save menu with "Save to traces folder" and "Download as…", each with its format, and the range;
- Capture… for capture filters and error frames;
- Decoding… for DBC files and the nodes' PDO layouts (see "Decoding panel in the Trace view");
- the time mode.

Under it SHALL be the header with the statistics and the view tabs **By identifier**, **Chronological**, **Graph**, **Sequences** (not on J1939) and **Trigger**.

The height of the By identifier list, the Chronological list and the Graph SHALL be adjustable by dragging a resize bar under each, bigger or smaller, with the arrow keys on the focused bar (Up smaller, Down bigger, 40 px a step) and double-click on the bar back to the default. The lists SHALL be between 120 px and 3000 px high, and one setting SHALL cover both lists. The graph's height SHALL be set per lane, between 80 px and 1000 px, and all lanes SHALL share it; the default stays 200 px per lane (150 px with more than two lanes) until the user resizes. The heights SHALL be kept on this PC with the other trace view settings and SHALL be used again after a reload. While the list and the inspector share the window height (between the phone and the wide layout), the list's bar SHALL be hidden and that layout is unchanged.

#### Scenario: One Start / Stop button
- **WHEN** the user presses Start
- **THEN** the same button reads Stop until the recording stops

#### Scenario: Make the list taller
- **WHEN** the user drags the bar under the Chronological list 300 px down and reloads the page
- **THEN** the list is 300 px taller, shows more rows, and is still that height after the reload and in By identifier

#### Scenario: Make the graph lanes taller
- **WHEN** two lanes are graphed and the user drags the bar under the graph 200 px down
- **THEN** each lane is 300 px high, the graph is redrawn at that height with the cursors kept, and double-click on the bar returns both lanes to 200 px

### Requirement: Display filters shared by both lists
One Filters control SHALL hold the display filters of By identifier and Chronological. It SHALL show the number of active filters, and while one is active the statistics SHALL say how many frames are shown.

#### Scenario: Filters shared
- **WHEN** the user filters node 5 in Chronological and opens By identifier
- **THEN** By identifier lists only node 5's identifiers and the Filters control shows one active filter

### Requirement: Docked inspector and transmit pane
With By identifier and Chronological, the frame inspector SHALL be docked:
- beside the view at 1280 px and wider;
- under it in narrower windows, where the view and the inspector SHALL share the window's height below the toolbar, each scrolling on its own, so the selected row and the start of its explanation are in view together.

Its size SHALL change by dragging the split or with the arrow keys on the focused handle, and it SHALL be closable (see "Close and reopen the inspector"). The transmit list SHALL be a collapsible pane under the views, with its row and running job counts in its header. The inspector's size and state, the chosen view and the pane's height SHALL be kept on this PC.

#### Scenario: Wide window
- **WHEN** the window is 1440 px wide and the user selects a frame in Chronological
- **THEN** the inspector shows beside the list, and list, inspector and transmit pane fit without horizontal scrolling

#### Scenario: Narrow window
- **WHEN** the window is 1000 px wide
- **THEN** the inspector shows under the list, and every toolbar control is reachable without horizontal scrolling

#### Scenario: Narrow window shows the explanation
- **WHEN** the window is 1000 by 800 px and the user clicks the fifth row of Chronological
- **THEN** that row and the inspector's meaning are both inside the window without scrolling the page

#### Scenario: Split kept
- **WHEN** the user drags the inspector wider and reloads the page
- **THEN** the inspector opens at the width the user left it

### Requirement: By identifier view
The Trace tab SHALL open on **By identifier**, or on the view last chosen on this PC. It SHALL show one row per identifier, extended flag and direction, with:
- direction, identifier (hex) and decoded name (PGN and source on J1939);
- DLC, last data and decoded values;
- count, and last, average, minimum and maximum cycle;
- time since last seen (for a file, the last frame's time).

Rows SHALL be in identifier order by default and SHALL NOT move as frames arrive.

#### Scenario: Busy bus at a glance
- **WHEN** a network carries 40 identifiers at 800 frames per second and the user opens Trace and presses Start
- **THEN** the By identifier view shows 40 rows in identifier order whose counts, cycle times and data update in place

#### Scenario: Opened file
- **WHEN** nothing is connected and the user opens a candump log file
- **THEN** the By identifier view lists every identifier of the file with its count and cycle times over the whole file

### Requirement: Sorting the By identifier view
Each column header of the By identifier view SHALL sort the rows by that column and SHALL announce the sort order. The chosen sort SHALL be kept on this PC.

#### Scenario: Sort by count
- **WHEN** the user clicks the Count header
- **THEN** rows are sorted by count and the header announces the sort order

### Requirement: Live updates of the By identifier view
While recording, rows SHALL update in place at least twice and at most four times a second. Updates SHALL keep focus, selection and the scroll position. The table SHALL stay responsive with 2,000 identifiers. **Pause view** SHALL stop updating the table while recording continues, and SHALL say how many updates are waiting. While the view is paused the button SHALL read **Resume view**; pressing it SHALL show the waiting updates and read Pause view again.

#### Scenario: Focus kept
- **WHEN** the user has focused the third row and new frames arrive for every identifier
- **THEN** the third row keeps focus and the list does not scroll

#### Scenario: Pause view
- **WHEN** the user presses Pause view while recording
- **THEN** the table stops changing, recording continues, and the view says updates are waiting

#### Scenario: Pause button says what it does
- **WHEN** the user presses Pause view while recording
- **THEN** the button reads Resume view, and pressing it again shows the waiting updates and the button reads Pause view

### Requirement: Change marks and reference
Bytes that changed since the identifier's previous frame SHALL be marked for one second, not by colour alone. Pointing at or focusing the data SHALL show which bits changed. Bytes that never changed in the trace SHALL be muted.

**Set reference** SHALL take each row's current data as the reference (for a file, the data at a picked frame). Until **Clear reference**, bytes that differ from it SHALL stay marked, and rows that appeared after it SHALL be marked new.

#### Scenario: Find the byte that follows a switch
- **WHEN** the user presses Set reference, then flips a digital input wired to node 5, whose TPDO1 byte 2 changes from 00 to 04
- **THEN** byte 2 of node 5's TPDO1 row stays marked as different from the reference, and pointing at it shows bit 2 changed

#### Scenario: New after reference
- **WHEN** a reference is set and node 9 then boots
- **THEN** node 9's boot-up and heartbeat rows are marked new

### Requirement: Silent identifiers
A row not seen for more than three of its average cycles, and at least one second, SHALL be shown as silent with the time since it was last seen. Rows with fewer than three frames SHALL never be marked silent.

#### Scenario: Silent node
- **WHEN** node 7's heartbeat came every 100 ms and node 7 is switched off
- **THEN** within a second its heartbeat row is shown as silent with the time since it was last seen

### Requirement: Selection in the By identifier view
Selecting a row SHALL show the identifier's latest frame in the inspector, which SHALL follow new frames until the user holds it. The arrow keys, Home, End, Page Up and Page Down SHALL move the selection. The selected row SHALL offer:
- **Show frames**: Chronological filtered to that identifier;
- **Explain in Frame lab**;
- **Send…**;
- **Graph signals**: its decoded signals added to the graph.

#### Scenario: Row moves to the inspector
- **WHEN** the user selects node 5's TPDO1 row
- **THEN** the inspector explains its latest frame and follows each new frame of that identifier until the user holds it

#### Scenario: Show frames
- **WHEN** the user picks Show frames on the row of identifier 0x285
- **THEN** the Chronological view opens filtered to identifier 0x285

### Requirement: Transmit list
The Trace tab SHALL have a transmit list for the picked network. Each row SHALL hold:
- an optional name;
- identifier (hex), extended, remote and DLC;
- up to 8 data bytes;
- a period of 10 to 60000 ms (empty: one frame) and an optional count.

Each row SHALL show its state (idle, last sent, running with count, or refused with the reason) and a decoded preview. Rows SHALL be added, edited in place, duplicated, moved and removed, checked as typed. Clear list SHALL ask, Cancel being the default.

#### Scenario: Bad data
- **WHEN** the user types `0F 1` in a row's data
- **THEN** the field says the data needs whole bytes and the row's Send is disabled

#### Scenario: Preview names the identifier
- **WHEN** the user types identifier 205 on a network where it is RPDO1 of node 5
- **THEN** the row's preview names RPDO1 of node 5 and says the identifier is in use

### Requirement: Sending from the transmit list
A single row SHALL have Send, and a cyclic row Start or Stop, using `send_frame` and `send_frame_stop` through the connection bar's connection.
- Without a connection with Allow changes, they SHALL be disabled with the reason, and the list SHALL stay editable.
- A `force` refusal SHALL show the reason in a confirmation and resend with `force` only when confirmed.

#### Scenario: Single frame while recording
- **WHEN** a trace is recording and the user presses Send on a row with 0x60A and eight data bytes
- **THEN** the frame appears in the trace once, as Tx, and the row shows the time it was sent

### Requirement: Cyclic send jobs
Running cyclic jobs SHALL be listed in the status bar with their network, identifier, period, sent count and Cancel. They SHALL keep running across tabs, workspaces and network switches. They SHALL stop on Stop, Stop all, Cancel, Disconnect, a connection end or closing the page.

#### Scenario: Cyclic job outlives the tab
- **WHEN** the user starts a row with 0x301 every 100 ms and opens the Network tab
- **THEN** the job keeps sending, the status bar lists it with its sent count, and Cancel there stops it

#### Scenario: Force needs confirmation
- **WHEN** the user sends a row with 0x205, which is RPDO1 of node 5
- **THEN** a confirmation quotes "0x205 is RPDO1 of node 5" and nothing is sent unless the user confirms

#### Scenario: No changes allowed
- **WHEN** the connection does not allow changes
- **THEN** Send and Start are disabled, the list says that sending needs Allow changes, and rows can still be edited and saved

#### Scenario: Ninth cyclic job
- **WHEN** 8 cyclic jobs run on network io and the user starts a ninth
- **THEN** the row shows the refusal with the bridge's reason and the other 8 keep running

### Requirement: Transmit list storage and files
The transmit list SHALL be kept on this PC per folder and network, and per network in Commission a device. It SHALL come back after a reload with no job running. It SHALL NOT be written into the project folder or the config. Save list… SHALL write a JSON file (`"format": "canworks-transmit"`, `"version": 1`, the network and the rows). Open list… SHALL replace the list or add to it, as the user chooses, and SHALL ask before using a list saved for another network.

#### Scenario: List comes back
- **WHEN** the user has three rows on network io, closes the configurator and opens the same folder the next day
- **THEN** the transmit list of io has the same three rows, none running

#### Scenario: Save and open a list
- **WHEN** the user saves the list as `valve-test.transmit.json` and opens it on another PC for the same network
- **THEN** the rows are the same, with names, identifiers, data, periods and counts

### Requirement: Explain in Frame lab
A trace frame (Chronological, By identifier or the inspector) SHALL offer **Explain in Frame lab**. It SHALL open the Frame lab with the frame, the trace's network and bit rate, and the frame's SDO context, showing where the frame came from with **Back to trace**. Back to trace SHALL return to the trace with that frame selected. Editing the frame SHALL drop the SDO context and SHALL say the frame was edited. Trace and Frame lab SHALL use one inspector component.

#### Scenario: Change a bit of a recorded frame
- **WHEN** the user picks Explain in Frame lab on node 5's TPDO1 frame and sets bit 3 of byte 0
- **THEN** the Frame lab explains the changed frame at the trace's bit rate and says it was edited from that trace frame

#### Scenario: Segment keeps its transfer
- **WHEN** the user picks Explain in Frame lab on the third segment of an upload of 1008h:00
- **THEN** the Frame lab explains it as segment 3 of that upload

#### Scenario: Back to trace
- **WHEN** the user presses Back to trace in the Frame lab
- **THEN** the Trace tab shows the same view with that frame selected

### Requirement: Send… adds to the transmit list
A trace frame and a Frame lab result SHALL offer **Send…**. It SHALL:
- add the frame as a new single-send row at the end of the transmit list of the frame's network;
- show the Trace tab with the transmit list open;
- move focus to that row's Send button.

Send… SHALL put nothing on the bus itself. It SHALL be enabled only while a connection with Allow changes is open, and SHALL otherwise say why.

#### Scenario: Send a built frame
- **WHEN** the user builds a write of 1017h:00 = 1000 to node 5 in the Frame lab, is connected with Allow changes and picks Send…
- **THEN** the transmit list gets a row `605` `2B 17 10 00 E8 03 00 00`, focus is on its Send button, and nothing is sent until the user presses it

#### Scenario: Send… without a connection
- **WHEN** nothing is connected
- **THEN** Send… is disabled and says that sending needs a connection with Allow changes

### Requirement: Network tree
In both workspaces of a config, the left column of the workspace tab SHALL be a network tree, and it SHALL be the only navigation there. In Configure the tree SHALL start with a **Project** entry that opens the project page (target and online access). The tree SHALL show every network of the config at once, each as an entry with its name and protocol (CANopen master, CANopen slave, J1939 or Plain CAN). Under a network it SHALL show the entries that network has:
- Bus and master (Bus and ECU on J1939, Bus on Plain CAN and on a slave network);
- its nodes, sorted by node ID, each named by node ID and name;
- the slave device on a slave network;
- **Add node…** on a CANopen master network in Configure, which opens the Add node dialog for that network (see "Add node dialog");
- PDO links and CAN messages, when the network has them today.

After the networks the tree SHALL show Gateway and Modbus bridge when the config has them, and **Add network…** (Configure). Each network entry SHALL have a menu with **Rename…**, **Role** (CANopen networks) and **Remove…**, keeping today's confirmations. Which networks are folded SHALL be kept on this PC and SHALL come back after a page reload; a folded network SHALL show the sum of its entries' problem counts, and SHALL unfold by itself when a problem link opens an entry in it. The unused EDS files note and the address scan line SHALL be shown under the tree. Renaming a node SHALL update its entry as the user types.

#### Scenario: Two networks at once
- **WHEN** a config has networks `io` with nodes 5 and 7 and `drives` with node 2
- **THEN** the tree shows `io` and `drives` with their nodes, and opening node 2 needs no network switch

#### Scenario: Add a node to the second network
- **WHEN** the user picks **Add node…** under `drives`, picks an EDS from the dialog's list and presses Add
- **THEN** the node is added to `drives`, its entry is selected, and its PDOs tab opens

#### Scenario: Remove a network from its menu
- **WHEN** the user opens the menu of network `drives`, which has 3 nodes, and picks **Remove…**
- **THEN** the page asks for confirmation naming `drives` and its 3 nodes, with Cancel as the default

#### Scenario: Project entry
- **WHEN** a config is open in Configure
- **THEN** the tree's first entry is Project, and it opens the target and Online access

### Requirement: Network tree keyboard
The tree SHALL follow the WAI-ARIA tree view pattern: one tab stop, Down and Up to the next and previous visible entry, Right to expand a network or move to its first child, Left to collapse a network or move to its parent, Home and End to the first and last entry, Enter or Space to open an entry, and type-ahead on the entry text. Shift+F10 on a network entry SHALL open its menu. The open entry SHALL be marked as selected. Focus SHALL stay on the same entry when the tree is redrawn. A name too long for the column SHALL wrap as "Whole names in the network tree" says, and SHALL be given whole in a tooltip and in the accessible name.

#### Scenario: Find a node by typing
- **WHEN** focus is in the tree and the user types `2`
- **THEN** focus moves to the first entry whose text starts with `2`, such as node 23, and Enter opens it

#### Scenario: Collapse with Left
- **WHEN** focus is on node 5 under `io` and the user presses Left twice
- **THEN** focus moves to `io` and then `io` collapses

### Requirement: Node tabs
A node page in Configure SHALL show its heading, Export DCF and Remove node above a tab list, and SHALL show one tab at a time:
- **General**: node ID, name, EDS and Simulated, and the EDS error when the EDS cannot be read;
- **PDOs** (see "PDOs tab");
- **SDOs** (see "SDOs tab");
- **Supervision**: heartbeat or guarding, status bit, state byte, NMT command, boot error byte, EMCY code, error register and EMCY COB-ID;
- **Simulation**, shown only for a simulated node (see "Simulation tab of a node");
- **Notes** (see "Notes tab");
- **Advanced**.

The tabs SHALL follow the page's tab pattern. Opening another node SHALL keep the open tab when that node has it, and open General otherwise. The open tab SHALL come back after a page reload. A node just added SHALL open on PDOs when its default PDOs were mapped, else on General, whatever tab another node had open. Objects SHALL be mapped from within the PDO they go into ("Add entry…" per PDO, listing that direction's mappable objects), with "Map all" kept for device-mapped PDOs.

#### Scenario: Compare heartbeats across nodes
- **WHEN** the user is on node 5's Supervision tab and opens node 7 in the tree
- **THEN** node 7's Supervision tab is shown

#### Scenario: No CiA 402 tab for an I/O module
- **WHEN** the user opens a node whose EDS has neither 0x6040 nor 0x6041
- **THEN** the node has no CiA 402 tab

#### Scenario: Drive has the same tabs
- **WHEN** the user opens a node whose EDS has 0x6040 and 0x6041
- **THEN** it has the same tabs as any other node, and no tab for drive or axis settings

#### Scenario: Reload keeps the tab
- **WHEN** the user is on node 5's PDOs tab and reloads the page
- **THEN** node 5's PDOs tab is shown

#### Scenario: Add an entry from the PDO
- **WHEN** the user clicks "Add entry…" on TPDO 1 and picks 0x6150:1
- **THEN** 0x6150:1 is added to TPDO 1 with a suggested location, and the picker lists only input-direction objects

### Requirement: PDOs tab
The PDOs tab SHALL show the node's inputs (TPDOs) and outputs (RPDOs), side by side when the page is at least 1400 px wide and stacked, inputs first, when narrower. Each PDO SHALL show its title, its mapping table with "Add entry…", and one line summing up its communication settings (COB-ID, transmission type, event timer, timeout). **Settings** on that line SHALL open the communication settings for editing. They SHALL start closed and SHALL open by themselves when one of them has a problem; the user's own open or close SHALL be kept while the node stays open.

#### Scenario: Settings at a glance
- **WHEN** TPDO 1 of node 5 has COB-ID 0x185, transmission type 255, event timer 100 ms and a 500 ms timeout
- **THEN** its summary line reads "COB-ID 0x185 · on change · event 100 ms · timeout 500 ms" with the settings closed

#### Scenario: Problem opens the settings
- **WHEN** RPDO 2's COB-ID clashes with another node's
- **THEN** RPDO 2's settings are open with the COB-ID field marked

#### Scenario: Width at 1280 px
- **WHEN** the window is 1280 px wide and the user opens the PDOs tab of a node with 4 TPDOs and 4 RPDOs
- **THEN** the inputs are above the outputs and nothing scrolls sideways

### Requirement: SDOs tab
The SDOs tab SHALL show the startup SDO writes and the SDO variables as two tables, each with its heading, its count and its add action, both shown even when empty.

#### Scenario: Empty node
- **WHEN** the user opens the SDOs tab of a node with no startup writes and no SDO variables
- **THEN** both tables show with a count of 0 and their add actions

### Requirement: Simulation tab of a node
A simulated node (its `simulate`, or a node on a simulated network that is not switched off) SHALL have a **Simulated device** tab that edits that node's part of the simulation file: its value sources, its faults at start and its default behaviour switch. It SHALL edit the same draft as the Simulation file tab, so a change shows in both, and SHALL be saved with **Save to simulation file**. With several networks it SHALL edit the node's own network section. Its text SHALL point to Commission → Simulation for live values.

#### Scenario: Source from the node
- **WHEN** the user gives node 5's 0x6401:1 a sine on its Simulated device tab and saves to the simulation file
- **THEN** `simulation.json` has that source for node 5, and the Simulation file tab shows it

### Requirement: Notes tab
The Notes tab SHALL list the objects of the node's EDS in one of three views chosen above the list: **My notes** (the default), the objects and sub-objects whose device notes entry, with the page's unsaved edits, has at least one field other than `name`; **All notes**, the objects with a note, built-in or the user's own; and **All objects**, every object and sub-object of the EDS. Each row SHALL show the object, its name, the note's text, unit and value meanings, where the note comes from as text (**Mine**, **Built-in** or **Built-in, changed**), and a **Note** button opening the Note editor. When the notes can be edited, a click on a row outside its buttons SHALL also open its Note editor, unless the click ends a text selection. The tab SHALL offer a search by index or name and, next to it, **Add note…** (see "Add note picker"), **Import notes…** and **Export notes…** (see `canopen-device-notes`). The tab's label SHALL show the number of the user's notes. The chosen view and the search SHALL be kept while the page is open. An empty view SHALL say why and offer **Add note…**, **Import notes…** and a way to show **All notes**. The tab SHALL work the same in Configure, in Commission with a config and in Commission a device. When the node has no EDS or its notes cannot be edited (a canworks-built EDS, an unreadable notes file, a notes file that cannot be written), the tab SHALL be read-only, SHALL say why, and SHALL offer only the views, the search and **Export notes…**.

#### Scenario: Own notes first
- **WHEN** the user opens the Notes tab of a drive whose notes file has a text for 0x2010 and only `name` entries for its other manufacturer objects, and the user has changed the values of 0x6060
- **THEN** My notes lists 0x2010 marked Mine and 0x6060 marked Built-in, changed, and nothing else, and the tab reads "Notes 2"

#### Scenario: Find a note
- **WHEN** the user picks All notes and types `6060` in the search of a drive
- **THEN** only 0x6060 is listed with its note, and **Note** opens its editor

#### Scenario: Open a note by its row
- **WHEN** the user clicks the text of 0x2010's row on the Notes tab
- **THEN** the Note editor of 0x2010 opens

#### Scenario: Copy note text
- **WHEN** the user drags over part of 0x2010's note text to select it
- **THEN** the text is selected and no editor opens

#### Scenario: Note for an object without one
- **WHEN** the user presses **Add note…**, types `2011`, clicks the row of 0x2011:1, types a text in the Note editor and keeps it
- **THEN** My notes lists 0x2011:1 marked Mine with the focus on its row, and the draft is unsaved

#### Scenario: No notes yet
- **WHEN** the user opens the Notes tab of a node whose EDS has no notes of the user's own
- **THEN** the tab says there are no notes of the user's own yet and offers Add note…, Import notes… and Show all notes

#### Scenario: Notes while commissioning a device
- **WHEN** the user opens the Notes tab of node 12 in "Commission a device", whose EDS is in the EDS library
- **THEN** the tab offers the same views, Note buttons, Add note…, Import notes… and Export notes… as in a config

#### Scenario: Read-only Notes tab
- **WHEN** the EDS of node 12 in "Commission a device" is in a folder that cannot be written
- **THEN** the notes are listed and can be exported, the tab says the notes file next to the EDS cannot be written, and no Note, Add note… or Import notes… button is offered

### Requirement: Problem badges
Each tree entry and each node tab SHALL show its number of errors and of warnings, marked by shape and text as well as colour, with an accessible name such as "2 errors, 1 warning". A collapsed network SHALL show the sum of its entries' problems; an expanded network SHALL show only its own. A problem whose place cannot be matched to an entry SHALL be counted on its network, or on the node's Advanced tab when it names a node field no other tab holds (General when it names the node itself). Selecting a problem in the bottom panel SHALL select its entry, expand its network, open its tab and any closed part holding the field, and focus the field.

#### Scenario: Where the errors are
- **WHEN** node 5 on `io` has one error in TPDO 2 and one in its heartbeat, and `io` is collapsed
- **THEN** `io` shows 2 errors, and after expanding it node 5 shows 2 errors, its PDOs tab 1 and its Supervision tab 1

#### Scenario: Problem to field
- **WHEN** the user is on node 7's General tab and selects the problem "Node 5 rtd, TPDO 2, 0x6150:1: type UNSIGNED8 (8 bit) does not fit location %IW320 (16 bit)"
- **THEN** node 5's PDOs tab opens and the location field of 0x6150:1 in TPDO 2 has focus

#### Scenario: Badge after a fix
- **WHEN** the user corrects the only error of node 5
- **THEN** node 5's entry, its tab and its network show no error count

### Requirement: Tree in Commission with a config
In Commission with a config, the tree SHALL show the config's networks and their nodes, without the configuration-only entries (Bus and master, Add node…, PDO links, CAN messages, Online access, Gateway, Modbus bridge, Add network…) and without the network menu. A network entry SHALL open that network's page: bus state, SYNC, the Nodes table and Unconfigured devices. A node entry SHALL open only that node's page: a one-line node header (node ID, name, state shape and text, last heard, boot result, simulated mark, and a link back to the Nodes table) above the node's live tabs. The node's page SHALL NOT be drawn under the Nodes table, and opening a page or a tab SHALL show its top with the tab row in view. Picking an entry on another network SHALL move the connection bar's network picker to that network, and changing the picker SHALL select that network's entry. Each workspace SHALL keep its own selected entry. Commission a device SHALL lay out its Nodes table and node pages the same way.

#### Scenario: Open a live node
- **WHEN** the page is connected to a runtime running `io` and `drives` and the user opens node 2 under `drives` in Commission
- **THEN** node 2's page opens with its header and live tabs at the top of the work area, no Nodes table is shown above it, and the connection bar's picker shows `drives`

#### Scenario: Back to where the user was
- **WHEN** the user was on node 5's PDOs tab in Configure, opened node 2 in Commission, and switches back to Configure
- **THEN** node 5's PDOs tab is shown

#### Scenario: Back to the table
- **WHEN** the user is on node 7's Object dictionary tab and presses the node header's link back to Nodes
- **THEN** the network's page with the Nodes table is shown and node 7's row is selected

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
- **Add to config** for Not in config rows, one or several ticked rows at once: each becomes an unsaved node with that node ID, the matching EDS (the EDS dialog, with **Add node** and **Skip**, when several match or none does), the EDS product name as name and the serial number, with `lss.assign` set when the ID was given by LSS in this session and the EDS says `LSS_Supported=1`;
- **Use matching EDS** for an Identity differs row when an EDS in the project or the EDS library matches the device;
- **Take serial number** when only the serial number differs.

Each action SHALL be a draft edit that Undo reverts. The user SHALL stay in Commission, the header SHALL show the unsaved mark, and problems the change causes SHALL show in the bottom panel's Problems tab.

#### Scenario: Add a found device
- **WHEN** node 9 reads Not in config, one EDS in the library matches it, and the user presses Add to config
- **THEN** the draft has node 9 with that EDS imported, its product name and serial number, the row reads Match, and the header shows the unsaved mark

#### Scenario: Undo an add
- **WHEN** the user added node 9 from the comparison and presses Undo
- **THEN** node 9 is gone from the draft and its row reads Not in config again

#### Scenario: No match
- **WHEN** node 12 reads Not in config, no EDS matches it, and the user presses Add to config
- **THEN** the EDS dialog opens for node 12 with In this project, EDS library and Browse…, and Skip leaves node 12 out of the draft

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
- the device: name, vendor, product, revision, serial number, hardware and software version and device profile, as read by "Device identity of heard nodes", with **Read again**;
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

#### Scenario: Device line
- **WHEN** the user opens the Status tab of heard node 23 after its identity was read
- **THEN** the first line shows its device name, vendor, product, revision, serial number and versions; values the device did not answer are left out

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
A write control disabled because changes are not allowed SHALL say "Locked. Changes are not allowed on this connection." and offer **Unlock…**. On an adapter, Unlock SHALL ask the same question as **Unlock…** in the connection bar and, when confirmed, allow changes on the open connection without reconnecting, with focus kept on the control. On a runtime, Unlock SHALL explain that Allow changes is set in Configure → Bus and master → Online access and takes effect after an upload. Controls disabled for another reason SHALL keep their own reason.

#### Scenario: Unlock in place
- **WHEN** the user is connected read-only to an adapter, presses Unlock… beside node 5's Start button and confirms
- **THEN** the connection bar shows "Changes allowed" with Lock, Start is enabled and focused, and no "another master" message appears

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

### Requirement: State colours
The page SHALL use one set of state colours in both themes, and only states SHALL use them:
- **OK**: as intended (OPERATIONAL, rate confirmed);
- **in progress**: waiting or working (PRE-OPERATIONAL, a job);
- **warning**: needs a look (STOPPED, a warning, error passive);
- **error**: broken (an error, missing node, bus-off);
- **off**, a grey: no information (unknown, absent).

"Simulated" is not a state.

#### Scenario: Simulated is not a warning
- **WHEN** a config has a simulated node and no problems
- **THEN** no element on the page uses the warning colour

#### Scenario: Missing node
- **WHEN** a node goes missing
- **THEN** its state is shown in the error colour

### Requirement: Grey is normal
Text in tables and lists SHALL stay in the normal text colour whatever the state; the state SHALL show as its icon and word. Only the warning and error states SHALL tint a row or banner background. The accent colour SHALL be used only for focus, links, the primary button and the selected tab.

#### Scenario: Healthy network is calm
- **WHEN** every node of a network is OPERATIONAL with no problems
- **THEN** the tree and the Nodes table show neutral text with an OK icon per node, and no row or banner is tinted

#### Scenario: A fault stands out
- **WHEN** one node of five goes missing
- **THEN** only that node's icon and row use the error colour

### Requirement: State colour contrast
Each state colour SHALL reach 4.5:1 as text and 3:1 as an icon against the page and panel backgrounds and against its own tint, in both themes. A test that needs no browser SHALL compute these ratios from the style sheet. The frame inspector's field tints and the graph's series colours are not state colours.

#### Scenario: Token edit caught without a browser
- **WHEN** a change lightens the Dark theme's warning colour below 4.5:1 against the panel
- **THEN** the contrast test fails naming the token and the theme

### Requirement: State icons
Every state SHALL show an icon whose shape tells the state:
- operational: filled circle;
- pre-operational: half-filled circle;
- initialising, connecting or a job running: ring with a gap;
- stopped: filled square;
- warning: triangle with "!";
- error, missing, bus-off or ended: circle with a cross;
- unknown, absent or not connected: hollow circle.

The tree, Nodes table, node tabs, connection bar, status bar, problems, message bar and trace SHALL use these icons.

#### Scenario: Stopped and warning differ
- **WHEN** node 5 is STOPPED and node 9 has a warning problem
- **THEN** node 5 shows a square and node 9 a triangle, though both use the warning colour

#### Scenario: Pre-operational node on the tree
- **WHEN** node 7 is PRE-OPERATIONAL
- **THEN** its tree entry shows the half-filled circle

### Requirement: Diagnosis flag and simulated mark
A pending diagnosis (an EMCY or error problem not yet cleared) SHALL add a flag in the error colour after a node's state icon; once cleared the flag SHALL turn grey and stay until the history is cleared. An EMCY with error code 0x0000 SHALL count as clearing the node's diagnosis and SHALL NOT raise the error-colour flag; the Last EMCY column SHALL show it as "cleared (0x0000)" in neutral text. A simulated node SHALL add a dashed outline to its state icon.

#### Scenario: Cleared diagnosis
- **WHEN** node 5 sent an EMCY that is later cleared
- **THEN** its flag turns from the error colour to grey

#### Scenario: Simulated node
- **WHEN** node 9 is simulated and OPERATIONAL
- **THEN** its icon is the filled circle with a dashed outline

#### Scenario: Error reset EMCY
- **WHEN** node 5 sends EMCY 0x5000 and then EMCY 0x0000
- **THEN** node 5's flag is grey and its Last EMCY reads "cleared (0x0000)"

### Requirement: State icons for every user
An icon shown without its state word SHALL have the word as its accessible name and tooltip. An icon next to its state word SHALL be hidden from assistive technology. In forced-colours (high contrast) mode the icons SHALL keep their shapes and inner marks. A turning animation SHALL show only when the user has not asked for reduced motion.

#### Scenario: Screen reader on the tree
- **WHEN** a screen reader reaches node 7, which is PRE-OPERATIONAL and simulated
- **THEN** it reads "Pre-operational, simulated" for the icon

#### Scenario: High contrast
- **WHEN** the page is shown in forced-colours mode
- **THEN** every state icon on the tree is visible with its shape

### Requirement: Colours and icons legend
The settings menu SHALL offer **Colours and icons**, showing every state icon, the diagnosis flag and the simulated mark with its word and one line on when it shows, drawn from the same definitions as the page's icons. It SHALL close on Escape and return focus to the menu.

#### Scenario: Open the legend
- **WHEN** the user opens the settings menu and picks Colours and icons
- **THEN** a legend lists the seven state icons, the diagnosis flag and the simulated outline, each with its word

### Requirement: Compact data tables
Data tables SHALL use rows of 28 px, or 32 px for rows that hold a field or button, and SHALL keep their header row in view while they scroll. Controls SHALL stay at least 24 px tall. Data tables are the Nodes table, PDO entries, startup SDO writes, SDO variables, object dictionary, watch list, trace, transmit list, PDO links, gateway routes, register map, CAN messages, J1939 signals, scan result and EMCY history.

#### Scenario: Header stays in view
- **WHEN** the user scrolls the object dictionary of a node with 300 entries
- **THEN** the column headers stay at the top of the table

#### Scenario: Row height
- **WHEN** the scan result lists 20 nodes
- **THEN** each row is at most 32 px tall

### Requirement: IDs and numbers in tables
Number columns SHALL be right-aligned with digits of even width. COB-IDs, CAN IDs, object indexes and subindexes, data bytes, hex values and PLC locations SHALL be shown in a fixed-width font. Hex values SHALL be written with `0x` and upper-case digits (`0x6150:1`, `0x1A5`); node IDs SHALL be decimal.

#### Scenario: Scan down a column of COB-IDs
- **WHEN** the trace's By identifier view lists 0x181, 0x1A5 and 0x705
- **THEN** the identifiers are in a fixed-width font and their counts are right-aligned

### Requirement: Word list for the page
Labels, headings, buttons, tooltips, empty states and messages SHALL follow `docs/wording.md`: one term per concept, sentence case, buttons that start with a verb (with "…" when they open a dialog), units after a space, no "Error:" or "Warning:" prefix, no exclamation marks, and messages that say what happened and what to do. Text from an EDS, a DBC or the config is data and is shown unchanged.

#### Scenario: One term
- **WHEN** the page shows the bit rate in the connect panel, the connection bar and the scan
- **THEN** each says "bit rate" and none says "baud" or "bitrate"

#### Scenario: Message says what to do
- **WHEN** a save fails because the folder is read-only
- **THEN** the message says the folder cannot be written and how to fix it, without an "Error:" prefix

### Requirement: Empty states say what to do
An empty list, table or panel SHALL say what it is for and offer the action that fills it, instead of showing nothing or only "None".

#### Scenario: No startup SDO writes
- **WHEN** a node has no startup SDO writes
- **THEN** the section says what startup SDO writes do and offers "Add write…"

### Requirement: Word list test
A test that needs no browser SHALL fail on a term the word list rules out, in the page's files or in the server's user-facing messages, naming the file, the line and the preferred term.

#### Scenario: Ruled-out term caught
- **WHEN** a change adds a button labelled "Set baudrate"
- **THEN** the word-list test fails naming the file, the line and "bit rate"

### Requirement: Disabled controls say why
Every disabled control SHALL carry the reason it is disabled as its tooltip and accessible description, such as "Needs a connection with changes allowed". A control disabled while its own action runs SHALL say what is running ("Saving…"). The browser layout test SHALL fail on a disabled control without a reason, naming the view and the control.

#### Scenario: Write without changes allowed
- **WHEN** the user is connected through an adapter with Allow changes off and looks at the object dictionary's Write button
- **THEN** the button is disabled and its tooltip reads "Needs a connection with changes allowed"

#### Scenario: Missing reason caught
- **WHEN** a change disables a button without a reason
- **THEN** the layout test fails naming the view and the button

### Requirement: Keyboard-only task tests
The browser tests SHALL do five user tasks with the keyboard alone, in the Light and the Dark theme: connect to a virtual USB adapter, scan the bus, add a found node to a config, map a PDO entry and save, and record and save a trace. They SHALL use the virtual adapter, the fake bridge runtime and the local simulator runtime, with no hardware, and SHALL fail if a step uses the pointer.

#### Scenario: Record a trace by keyboard in Dark
- **WHEN** the trace task runs in the Dark theme
- **THEN** it opens the Trace tab, starts and stops a recording and saves it with key presses only

#### Scenario: Pointer step caught
- **WHEN** a task test step clicks a button
- **THEN** the test fails saying the step used the pointer

### Requirement: Checks in each task step
After each step of a keyboard-only task test, the test SHALL run the accessibility audit, check that the focused control shows a visible focus ring, and check that no text in the view is clipped. A failed task SHALL leave a screenshot of each step with the test run.

#### Scenario: Focus lost
- **WHEN** a step leaves focus on the page body after a dialog closes
- **THEN** the task test fails at that step and keeps the step screenshots

### Requirement: High contrast check
The browser layout test SHALL open the network tree and the Nodes table once in forced-colours mode and SHALL fail if a state icon is not painted or has no accessible name.

#### Scenario: Icons in forced colours
- **WHEN** the layout test opens the network tree in forced-colours mode
- **THEN** each node's state icon is painted and has its state word as accessible name

### Requirement: Selected row in the object dictionary view
Clicking anywhere on a row of the object dictionary tab (VAR object, foldable object or sub-entry), its buttons and Watch box included, or moving keyboard focus into it SHALL select that row. At most one row SHALL be selected, and Escape inside the tree SHALL clear the selection. The selected row SHALL be shown across its whole width with a background tint and an accent bar on its left edge, and marked `aria-current`.

#### Scenario: Click a sub-entry
- **WHEN** the user unfolds object 0x1010 and clicks the name of sub-entry 2
- **THEN** that row, from its subindex to its Watch box, is highlighted and no other row is

#### Scenario: Button selects its row
- **WHEN** sub-entry 2 of 0x1010 is selected and the user clicks Read on sub-entry 3
- **THEN** sub-entry 3 is highlighted, sub-entry 2 is not, and the read runs as before

#### Scenario: Keyboard
- **WHEN** the user tabs to the Edit button of 0x1017
- **THEN** the 0x1017 row is highlighted, and pressing Escape removes the highlight

### Requirement: Selection kept in the object dictionary view
The selected row SHALL stay selected while values are read, the watch list refreshes, Read all runs, the search or filters change, objects are folded and unfolded, and the user moves to another tab or node and back, until the page is reloaded. A selected row hidden by a search, filter or fold SHALL be highlighted again when it is shown again. A row being edited in place SHALL be the selected row. The selection SHALL NOT be saved to the configurator's settings.

#### Scenario: Watch refresh
- **WHEN** 0x1001 is selected and on the watch list refreshed every second
- **THEN** its row stays highlighted through every refresh

#### Scenario: Search hides and shows the row
- **WHEN** 0x1017 is selected, the user types `6110` in the search box and then clears it
- **THEN** 0x1017 is highlighted again once it is shown

### Requirement: Row highlight visibility
With a mouse, the row under the pointer SHALL get a lighter tint than the selected row; a touch screen SHALL NOT keep a hover tint. The selected row's accent bar SHALL meet 3:1 contrast against the page and panel backgrounds in the Light and Dark themes, the tint SHALL keep the row's text and buttons at their normal contrast, and in forced-colours mode the selected row SHALL be outlined in the system highlight colour.

#### Scenario: Dark theme
- **WHEN** the page is in the Dark theme and 0x1018 sub-entry 1 is selected
- **THEN** the row is visibly highlighted, its Read and Edit buttons are readable, and the contrast check passes

#### Scenario: Forced colours
- **WHEN** the operating system's high contrast mode is on and a row is selected
- **THEN** the row is outlined in the system highlight colour

### Requirement: Newest frame whole in the Chronological view
The Chronological view SHALL draw exactly the rows in view, including a row partly scrolled past the top edge. Scrolled to the end, and while it follows a recording, the newest frame SHALL be the last row and SHALL be shown whole at the bottom edge; any row cut short SHALL be the one at the top.

#### Scenario: Following a recording
- **WHEN** the Chronological view follows a recording and its height is not a whole number of rows
- **THEN** the newest frame is the bottom row, shown whole, and no newer frame is hidden below it

### Requirement: Picking a sequence keeps the list in place
Picking an SDO conversation or a boot story in the Sequences tab, by click or Enter, SHALL keep the list's scroll position and the page position, and the picked row SHALL keep focus.

#### Scenario: Pick a conversation far down the list
- **WHEN** the user scrolls the SDO conversations to the end and clicks the last conversation
- **THEN** the list stays scrolled where it was, the row is marked picked and its sequence diagram opens below

### Requirement: EDS library folder button
The Nodes tab of Commission a device SHALL show the EDS library folder as text ("None chosen" when unset) with a **Choose folder…** button and, when a folder is set, a **Clear** button, and SHALL NOT offer a text field for it. The folder SHALL be kept in the configurator's settings on this PC, not in a project. After a folder is chosen or cleared, the devices already scanned SHALL be matched against the new folder.

#### Scenario: Choose a folder
- **WHEN** the user presses Choose folder…, opens `eds` under the home folder and presses Use this folder
- **THEN** the row shows the folder's path and the scanned devices are matched against it

#### Scenario: Clear
- **WHEN** a library folder is set and the user presses Clear
- **THEN** the row shows "None chosen", Clear is hidden, and scanned devices show no library matches

### Requirement: Folder dialog
**Choose folder…** SHALL open a dialog that lists the PC's folders through the configurator's server, with the current path, **Up**, a path field with **Go** that accepts a typed or pasted path, the subfolders (hidden ones left out), **Cancel** and **Use this folder**. Each listed folder that directly holds EDS files SHALL show how many.

#### Scenario: EDS counts in the list
- **WHEN** the dialog lists a folder whose subfolder `eds` holds 12 EDS files
- **THEN** that subfolder's entry shows "12 EDS"

#### Scenario: Cancel changes nothing
- **WHEN** the user opens the dialog, moves to another folder and presses Cancel
- **THEN** the library folder is unchanged and no settings request is sent

#### Scenario: Pasted path
- **WHEN** the user pastes a path into the dialog's path field and presses Enter
- **THEN** the dialog lists that folder, or says in the dialog that it is not a folder

### Requirement: Folder dialog start and drives
The folder dialog SHALL open in the current library folder, else its nearest existing parent, else the home folder. On Windows, **Up** from a drive root SHALL list the PC's drives.

#### Scenario: Opens where the library is
- **WHEN** the library folder is set and the user presses Choose folder…
- **THEN** the dialog lists the library folder

#### Scenario: Another drive on Windows
- **WHEN** the dialog shows `C:\` and the user presses Up
- **THEN** the dialog lists the PC's drives, and opening `D:\` lists its folders

### Requirement: Browse for the Add to a config folder
The "Add to a config…" dialog SHALL offer **Browse…** next to its Folder field. It SHALL open the folder dialog over the Add to a config dialog, starting in the typed folder or its nearest existing parent, and the picked folder SHALL fill the field. When the picked folder has `project.json` the folder kind SHALL switch to editor project, and when it has `canworks.json` to standalone config folder. Cancel SHALL leave the field and the Add to a config dialog as they were.

#### Scenario: Browse to a config folder
- **WHEN** the user presses Browse… in Add node 32 to a config, opens a folder holding `canworks.json` and presses Use this folder
- **THEN** the folder dialog closes, the Add to a config dialog is still open with the folder in its Folder field and the kind set to standalone config folder

### Requirement: Folder dialog keyboard use
The folder dialog SHALL work with the keyboard alone: focus starts in the folder list, Enter opens the focused folder, Escape cancels, and focus returns to **Choose folder…** when the dialog closes.

#### Scenario: Keyboard only
- **WHEN** the user tabs to Choose folder…, presses Enter, moves to a folder with the arrow keys, presses Enter, then tabs to Use this folder and presses Enter
- **THEN** that folder is the library folder and focus is back on Choose folder…

### Requirement: EDS library contents shown
After a library folder is chosen, the row SHALL say how many EDS files the folder holds with its subfolders, or that it holds none. Counting SHALL stop after 5000 directory entries; above that the row SHALL say the folder is large and scans may be slow.

#### Scenario: Count shown
- **WHEN** the chosen folder holds 34 EDS files in it and its subfolders
- **THEN** the row says "34 EDS files"

#### Scenario: Folder without EDS files
- **WHEN** the user chooses a folder with no EDS files in it or its subfolders
- **THEN** the row says the folder has no EDS files, and the folder stays chosen

#### Scenario: Large folder
- **WHEN** the user chooses the home folder and it has more than 5000 entries below it
- **THEN** the row says the folder is large and scans may be slow, and the page stays responsive

### Requirement: Decoding panel in the Trace view
The Trace toolbar's **Decoding** button SHALL open a panel that says what the trace decodes with and lets the user change it. The button SHALL show a short summary (number of DBC files, number of nodes with a known PDO layout) and a warning mark when a DBC file is missing or has problems.

The panel SHALL have:
- **DBC files**: each file's name, how many of its messages are used out of its total, its problems and the messages not used with what decodes their identifier instead; **Add DBC…** (one or more files), remove, and a way to change the order with the mouse and the keyboard.
- **Nodes**, on a CANopen network: each node heard on the bus or on the Nodes tab, with its device name, its EDS file or "none, built-in CiA names", the source of its PDO layout ("set on the bus at …", "read from the device at …", "EDS defaults", "configuration", or "unknown"), and the actions **Choose EDS…** or **Change EDS…** (the EDS dialog, as in the Nodes table) and **Read PDOs from device**.

**Read PDOs from device** SHALL be disabled with its reason without a live connection. While the connection bar reports another master, it SHALL ask first, saying that the other master's SDO transfers to the node can be mixed with the read.

The DBC files SHALL be remembered on this PC per project folder, and once for Commission a device, outside the project's canworks folder. A remembered file that is missing SHALL be listed as missing with Locate… and Remove, and decoding SHALL go on without it.

#### Scenario: Add a DBC
- **WHEN** the user opens Decoding, presses Add DBC… and picks `machine.dbc` with 12 messages, 2 of which are on identifiers the configuration decodes
- **THEN** the panel lists `machine.dbc` with "10 of 12 messages used", names the 2 messages and what decodes them, the rows of the other 10 identifiers decode with the DBC, and the button reads "1 DBC"

#### Scenario: Remembered
- **WHEN** the user closes the page and opens Commission a device again the next day
- **THEN** the Trace decodes with the same DBC files without asking

#### Scenario: Fix a raw PDO from the panel
- **WHEN** node 50's PDOs show as bytes and its layout source reads "unknown", and the user picks its EDS with Choose EDS…
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
For a PDO frame the frame inspector SHALL show a Layout line naming where the layout came from (configuration, DBC file, set on the bus at a time, read from the device at a time, or EDS defaults). Rows and inspectors decoded with EDS defaults SHALL carry an "assumed" tag whose tooltip says that the device may be mapped differently and how to make it certain. For a PDO frame shown as bytes, the Layout line SHALL say why and offer **Choose EDS…** and **Read PDOs from device** for its node.

#### Scenario: Raw PDO in the inspector
- **WHEN** the user selects a TPDO1 row of node 50 that shows only bytes
- **THEN** the inspector's Layout line says node 50 has no EDS and its PDOs were not read, with Choose EDS… and Read PDOs from device

#### Scenario: Assumed layout
- **WHEN** node 32's TPDO1 decodes with its EDS defaults
- **THEN** the row shows the "assumed" tag and the inspector's Layout line reads "EDS defaults: the device may be mapped differently"

### Requirement: Dialog buttons stay inside the dialog
In every dialog of the configurator, every button SHALL be shown whole and inside the dialog's box, at any window width the page supports. Buttons that do not fit on one row SHALL wrap onto further rows, and a button label wider than the dialog SHALL wrap inside its button. The order of the buttons and which button gets the focus SHALL NOT change.

#### Scenario: Network menu with a long name
- **WHEN** the user opens the menu of a network named `conveyor_line_01` in a 1000 px window
- **THEN** Cancel, Rename…, Make it a slave network… and Remove… are all shown whole inside the dialog

#### Scenario: Focused button is visible
- **WHEN** any dialog opens
- **THEN** the button that has the focus is inside the dialog's box and on screen

### Requirement: Add network protocol choice
**Add network…** SHALL ask for the new network's protocol with one choice per row (CANopen, J1939, Plain CAN), each showing the protocol's name and one line on what it is for, followed by Cancel. CANopen SHALL be first and have the focus. Escape and Cancel SHALL add nothing.

#### Scenario: Pick with the keyboard
- **WHEN** the dialog opens and the user presses Down twice and Enter
- **THEN** focus moved from CANopen to J1939 to Plain CAN, and a plain CAN network is added

#### Scenario: Add a plain CAN network
- **WHEN** the user picks **Add network…** and then **Plain CAN**
- **THEN** a plain CAN network is added and its Bus page opens, as today

#### Scenario: Cancel is visible and works
- **WHEN** the user opens **Add network…** in a 1280 px window and presses Escape
- **THEN** every choice and Cancel were shown whole inside the dialog, and no network is added

### Requirement: Whole names in the network tree
The network tree SHALL show the whole name of every network and node: a name wider than the tree column SHALL wrap onto the next line, breaking inside the name when it has no space, and SHALL NOT be cut. A network entry SHALL show its name, fold arrow, problem badge and menu button on its first line and its protocol on a second line under the name. Each entry SHALL keep its tooltip with the whole text.

#### Scenario: New network with a problem
- **WHEN** a config has one CANopen master network `can0` with no nodes, so its entry carries an error badge
- **THEN** the entry reads `can0` on its first line and `CANopen master` on the second, neither cut

#### Scenario: Longest network name
- **WHEN** a network is named `conveyor_line_01` and the window is 1280 px wide
- **THEN** all 16 characters of the name are shown in the tree, on one or more lines

#### Scenario: Long node name
- **WHEN** node 5 is named `temperature_inputs_left`
- **THEN** its entry shows `5 temperature_inputs_left` whole, wrapped if needed

### Requirement: No cut text in Configure
In the Configure workspace no label, heading, button, tree entry or hint SHALL be cut by its box (an ellipsis, or text hidden by its box's overflow) at 1000 px wide and wider. Only cells of data tables that carry their whole value in a tooltip MAY be cut. The column headings of the Trace identifier table SHALL be shown whole with their sort mark.

#### Scenario: Trace Dir heading
- **WHEN** the user opens Trace and sorts the identifier table by Dir
- **THEN** the heading reads `Dir` whole, with its sort mark

### Requirement: Selected rows keep their controls readable
On a selected row of a list or table, every button and text of the row SHALL keep at least WCAG AA contrast against what is behind it, in both themes, and text that has its own colour on the row (an EMCY or error row, a Tx mark) SHALL keep that colour. A button SHALL keep its own colours rather than take the row's text colour.

#### Scenario: Remove on a selected CAN message
- **WHEN** the user selects a received message on the CAN messages page in the dark theme
- **THEN** its Remove button reads clearly (red on the button's own fill), and "(no name)" reads in the row's text colour

#### Scenario: Selected EMCY frame
- **WHEN** the user selects an EMCY frame in the Chronological trace list in the light theme
- **THEN** the frame's text keeps its EMCY colour and reads clearly on the selected row's tint

### Requirement: Text boxes stay in their column
A multi-line text box SHALL take the width of its column and SHALL only be resizable in height, so dragging its corner never makes the page wider than the window. A field with a multi-line box SHALL stack its label, the box, its help and its message, in that order. On Online access, Relay URLs SHALL be laid out this way.

#### Scenario: Relay URLs with the remote link on
- **WHEN** the user turns on "Reachable from other networks" on Online access
- **THEN** "Relay URLs (optional)" is above its box and the help is under it, and no text of the page runs past the right edge

#### Scenario: Dragging the box
- **WHEN** the user drags the Relay URLs box's corner to the right
- **THEN** the box keeps its width and only its height changes

### Requirement: Device identity of heard nodes
While connected in Commission, and in Configure while connected to a runtime, the configurator SHALL read the identity of every node in the Nodes table without a scan: 0x1018 sub-indices 1-4, 0x1000, 0x1008, 0x1009 and 0x100A, with the connection's manual SDO read, one node at a time. Identity reads SHALL NOT need force or Allow changes.

#### Scenario: Heard nodes are read without a scan
- **WHEN** the user connects an adapter, nodes 23, 32 and 49 send heartbeats and no scan has run
- **THEN** the configurator reads each node's identity with SDO, one node at a time

### Requirement: When identity is read again
The configurator SHALL read a node's identity once per connection, again after the node boots up, and SHALL wait while the node is STOPPED. A scan's answer for a node SHALL count as its identity read.

#### Scenario: Stopped node
- **WHEN** node 49 is heard in STOPPED
- **THEN** its identity is read once the node goes pre-operational or operational

#### Scenario: New device on the same node ID
- **WHEN** node 23 is replaced by another device that boots up with node ID 23
- **THEN** node 23's identity is read again

#### Scenario: Scan then heard
- **WHEN** a scan has already read node 23
- **THEN** no identity read is sent for node 23 when its heartbeat is heard

### Requirement: Device names in the Nodes table
The Nodes table's Device column SHALL show, in full and wrapped when long, the first of: the device's name from 0x1008; the product name of a matching EDS in the project or EDS library; the device profile named by 0x1000 (such as "CiA 401 I/O device"); the vendor and product numbers. Muted text after it SHALL give the vendor (with the matching EDS's vendor name), product and profile not already shown.

#### Scenario: Heard nodes get their names
- **WHEN** nodes 23, 32 and 49 have been heard and their identity read
- **THEN** each row's Device column shows the device's 0x1008 name, with vendor and product numbers in muted text

#### Scenario: Device without a name object
- **WHEN** node 32 aborts the read of 0x1008 and its 0x1000 reads 0x00020191
- **THEN** its Device column shows "CiA 401 I/O device" followed by its vendor and product numbers

### Requirement: Device column while the identity is unknown
While a node's identity is being read, its Device cell SHALL say "Reading…"; while the node is STOPPED and not read yet, that it waits for the node to leave Stopped; when the node does not answer SDO, "No SDO answer" with **Read again**.

#### Scenario: Stopped node waits
- **WHEN** node 49 is heard in STOPPED and its identity is not read yet
- **THEN** its Device column says it is waiting for the node to leave Stopped

#### Scenario: No answer
- **WHEN** node 49's identity reads time out
- **THEN** its Device column says No SDO answer and offers Read again

### Requirement: Device name outside the Nodes table
With a config, the Nodes table's Name column SHALL keep the configured name and show the device's own name under it in muted text. A node without a configured name SHALL use the device's name in its heading, and **Add to a config…** SHALL name the new node after it.

#### Scenario: Heading of a heard node
- **WHEN** the user opens heard node 23 in Commission a device after its identity was read
- **THEN** the heading reads "Node 23" followed by the device's name, and Add to a config… names the new node after it

### Requirement: Standard object dictionary without an EDS
A node with no configured, matched or picked EDS SHALL have a standard object dictionary: the CiA 301 communication objects, plus the CiA 401 or CiA 402 standard objects when its 0x1000 low 16 bits are 401 or 402. Its Object dictionary tab and SDO object picker SHALL use it as they use an EDS (tree, reading, watch, formats, notes, editing). Standard entries SHALL have no default value.

#### Scenario: Object dictionary without an EDS
- **WHEN** the user opens the Object dictionary tab of heard node 49, which has no EDS and whose 0x1000 reads 0x00000000
- **THEN** the tab shows the CiA 301 objects in the communication group

#### Scenario: Profile objects
- **WHEN** node 32's 0x1000 low 16 bits read 402 and it has no EDS
- **THEN** its Object dictionary tab also shows the CiA 402 objects such as 0x6040 Controlword and 0x6041 Statusword in the profile group, with the controlword and statusword bit views

#### Scenario: Pick an object without an EDS
- **WHEN** node 49 has no EDS and the user types `heartbeat` in the SDO panel's filter
- **THEN** the picker offers 0x1016 Consumer heartbeat time and 0x1017 Producer heartbeat time, and picking 0x1017 fills index 0x1017, sub-index 0 and type UNSIGNED16

### Requirement: Standard dictionary says what it is
The standard dictionary's tab SHALL say at the top that these are standard objects and the device may lack some, name the device profile and, for a profile other than 301, 401 and 402, say its profile objects are not built in. It SHALL offer the node's EDS matches and **Pick EDS file…**; picking an EDS SHALL replace the standard dictionary.

#### Scenario: Other profile
- **WHEN** node 49's 0x1000 low 16 bits read 406 and it has no EDS
- **THEN** the tab shows the CiA 301 objects and says the CiA 406 objects are not built in

#### Scenario: EDS picked later
- **WHEN** the user picks the device's EDS from the line at the top of node 49's standard dictionary
- **THEN** the tab shows the EDS's objects, including its manufacturer objects

### Requirement: Objects a device lacks in the standard dictionary
A read of a standard entry refused with abort 0x06020000 or 0x06090011 SHALL mark it "not on this device". An array object SHALL show sub-entries up to the value read from its sub-index 0, and sub-indices 0 and 1 before that.

#### Scenario: Missing object
- **WHEN** the user reads 0x1013 of node 49 and the device aborts with 0x06020000
- **THEN** the entry is marked not on this device

#### Scenario: Error history length
- **WHEN** node 49's 0x1003 sub-index 0 reads 3
- **THEN** 0x1003 shows sub-indices 0 to 3

### Requirement: Read all on the standard dictionary
The standard dictionary SHALL list RPDO and TPDO 1-4. **Read all** SHALL read each object's sub-index 0 before its other entries, skip the rest of an object that does not exist, and add RPDOs and TPDOs from 5 onwards until the first that does not exist.

#### Scenario: Read all hides what is missing
- **WHEN** the user presses Read all on node 49's standard dictionary and the device has no 0x1013 and two TPDOs
- **THEN** 0x1013 and TPDO 3 and 4 are hidden by **Hide objects the device lacks**, and turning the filter off shows them marked "not on this device"

#### Scenario: More PDOs
- **WHEN** node 49 has 8 RPDOs
- **THEN** after Read all its standard dictionary shows RPDO 1-8

### Requirement: Parameters of a node without an EDS
The Parameters tab of a node without an EDS SHALL say that back up, compare and restore need the device's EDS and offer **Choose EDS…**, whose dialog lists the node's EDS matches first.

#### Scenario: Parameters without an EDS
- **WHEN** the user opens the Parameters tab of node 49, which has no EDS
- **THEN** the tab says back up, compare and restore need the device's EDS and offers Choose EDS…

### Requirement: Change or clear a node's EDS
In the Nodes table, a node whose EDS was picked, matched or added on the page (not from the config) SHALL show the EDS file name with **Change EDS…**. It SHALL open the EDS dialog, with the node's matches first and **Clear EDS** (or **Remove node** for a node only added on the page) beside **Use** and **Cancel**. Changing SHALL reload the node's tabs from the new EDS, clearing SHALL return the node to the standard dictionary, and both SHALL be logged in the Commissioning log.

#### Scenario: Wrong EDS picked
- **WHEN** node 23 shows an EDS file the user picked by mistake and the user picks another file in the Change EDS… dialog
- **THEN** the EDS column shows the new file name and node 23's Object dictionary tab shows the new EDS's objects

#### Scenario: Clear the EDS
- **WHEN** the user chooses Clear EDS for heard node 23
- **THEN** the EDS column offers the EDS choices again and node 23's Object dictionary tab shows the standard dictionary

#### Scenario: Node added only from an EDS
- **WHEN** node 40 was added with Add node from EDS… and is not heard
- **THEN** its menu offers Remove node in place of Clear EDS, and removing it takes the row away

#### Scenario: EDS from the config
- **WHEN** node 5 is in the config with its EDS
- **THEN** its EDS cell shows the config's EDS without Change EDS…, and its tooltip says the EDS is changed on the node's page in Configure

### Requirement: Saved config compared like the deploy tool writes it
The Commission workspace SHALL compare the bridge's config fingerprint with the saved `canworks.json` as `canworks-deploy --bridge` uploads it, with every node's and every slave's EDS path rewritten as the upload does. Right after an upload of the saved config, the workspace SHALL NOT say that the bridge runs a different configuration, also when the config has a slave network.

#### Scenario: Gateway config uploaded
- **WHEN** the virtual plant (a slave network `cell` with its own EDS) is uploaded with `canworks-deploy --bridge` and the configurator connects to that bridge
- **THEN** the Commission workspace shows no "different configuration" note

### Requirement: Connect panel without empty parts
The connect panel SHALL show nothing in place of the recent connections when there are none, and nothing in place of the runtime and simulator choice on a USB adapter.

#### Scenario: First connection on a PC
- **WHEN** a PC that has never connected opens the connect panel in Commission a device
- **THEN** the panel starts with the adapter form, and no stray text such as "null" appears

### Requirement: Settings on this PC saved while another program reads them
Saving the configurator's settings files on this PC (`online.json`, `ui.json`, `recent.json`, notes files) SHALL try the final rename again for about a second while Windows refuses it because another process has the file open, such as a second configurator. When it still fails, the temporary file SHALL be removed and the error shown as before.

#### Scenario: Two configurators on Windows
- **WHEN** two configurators run on one Windows PC and one connects to an adapter while the other reads `online.json`
- **THEN** the connection is saved without an "access is denied" message, and no `.tmp` file is left in the settings folder

### Requirement: Quick reboots in the Commission log
The Commission log SHALL add "Booted" for a node whenever the runtime's boot count of that node (`boots`) goes up, also when the node's state and boot result did not change between two status answers.

#### Scenario: Reset node from the Status tab
- **WHEN** the user resets node 6 from its Status tab and the master boots it again before the next status answer
- **THEN** the log has the NMT reset and then "Booted" for node 6

### Requirement: New editor project in standalone mode
In standalone mode the page SHALL offer "New editor project" next to "move into project". It SHALL ask for a parent folder (prefilled with the home folder, as "move into project" does), a project name, the task interval (default `T#20ms`) and whether to install the canworks library in the project ("Install the canworks library in the project", unchecked by default, with a hint that the mailbox blocks also need the bridge's mailboxes, which Problems offers once the program declares them). It SHALL create the project as `canopen-editor-project` describes, and then switch to project mode on the new project. It SHALL require the config to be saved first and SHALL show the reason when creation is refused. The standalone folder SHALL be left unchanged.

#### Scenario: Create and switch
- **WHEN** the user has saved a standalone config in `~/canworks/rtd`, chooses "New editor project", picks `~/workspace` and the name `rtd-monitor`
- **THEN** `~/workspace/rtd-monitor` is created with the config in its `canworks/` folder and `main` declaring its I/O, and the page shows mode "project rtd-monitor" with every CANopen entry marked as declared

#### Scenario: Function blocks enabled
- **WHEN** the user ticks "Install the canworks library in the project" in the dialog
- **THEN** the project is created as with `--blocks`, the config still has no mailboxes, and the page shows how to install the library when the creation output says it is missing

#### Scenario: Unsaved changes
- **WHEN** the config has unsaved changes
- **THEN** the page asks the user to save first and creates nothing

#### Scenario: Name taken
- **WHEN** `~/workspace/rtd-monitor` already exists
- **THEN** the dialog says the folder exists and stays open, nothing is written and the page stays in standalone mode

### Requirement: Saving a one-network config with a CiA 309-3 block
The configurator SHALL save a valid version 2 config with one network and a top-level `cia309` block without an error, writing the block where the saved schema version expects it.

#### Scenario: One network with the gateway on
- **WHEN** a version 2 config with one network and `cia309` at the top level is opened and saved without changes
- **THEN** the save succeeds and the saved file passes the check with the gateway settings unchanged

### Requirement: Folding inspector layers
The inspector's Identifier, Data bits and On the wire layers SHALL each fold and unfold from their heading, by mouse or keyboard. The meaning SHALL always show. The folded state SHALL be kept on this PC and SHALL be the same in the Trace view and the Frame lab. A folded layer SHALL still show its one-line summary in its heading (for example the identifier arithmetic, the data bytes in hex, the frame length and time on the bus).

#### Scenario: Fold the data grid
- **WHEN** the user folds Data bits on an EMCY in the trace, then selects a TPDO and opens the Frame lab
- **THEN** Data bits is folded in both, its heading shows the frame's data bytes, and it is still folded after a reload

#### Scenario: Keyboard fold
- **WHEN** the user focuses the On the wire heading and presses Enter
- **THEN** the layer folds and its heading shows the frame length, stuff bits and time on the bus

### Requirement: Compact data grid
The data grid SHALL fit an 8-byte frame in no more than 260 px of height at the default font size. A field of two or more whole bytes that is unused or all zero SHALL show as one row with the field's name and bytes in hex, and opening that row SHALL show its bits. Every bit SHALL stay reachable with the keyboard, and pointing at the row SHALL highlight the field in every layer.

#### Scenario: Manufacturer data in one row
- **WHEN** the inspector explains `085#0010010000000000`
- **THEN** bytes 0 to 2 show as bit rows, bytes 3 to 7 show as one row "Manufacturer data: 00 00 00 00 00", and opening it shows those 40 bits

#### Scenario: Short grid
- **WHEN** an 8-byte SDO frame is explained in a 1440 px window
- **THEN** the data grid is at most 260 px tall

### Requirement: Close and reopen the inspector
The Trace inspector SHALL have a close button (✕) in its own title bar, and Esc with the focus inside the inspector SHALL close it and return the focus to the selected row. A closed inspector SHALL leave a slim **Inspector** rail at its edge that opens it again. With no frame selected, the inspector SHALL start closed. Selecting a frame by click or Enter while it is closed SHALL open it. Moving through the list with the arrow keys SHALL NOT open it. From 1280 px to under 1440 px wide, an open inspector SHALL be a drawer over the right part of the list rather than a column beside it; narrower, it stays under the list. The open or closed state SHALL be kept on this PC once a frame has been selected.

#### Scenario: Close with Esc
- **WHEN** the user tabs into the inspector of a selected SYNC frame and presses Esc
- **THEN** the inspector closes, the rail shows, and the focus is on the SYNC row

#### Scenario: Reopen by selecting
- **WHEN** the inspector is closed and the user clicks a TPDO row
- **THEN** the inspector opens on that TPDO

#### Scenario: Arrow keys keep it closed
- **WHEN** the inspector is closed and the user moves down the Chronological list with the arrow keys
- **THEN** the inspector stays closed and the selection moves

#### Scenario: Whole columns before a selection
- **WHEN** the user starts a trace at 1366 px wide and has selected no frame
- **THEN** the inspector is a rail, and the Name and Decoded columns are not cut

### Requirement: Frame lab layout
The Frame lab SHALL put the frame box (frame, Explain, bit rate) at the top, with tabs **Examples**, **Build** and **Arbitration** under it. Only the chosen tab's panel SHALL show, and the choice SHALL be kept for the page session. At 1280 px and wider, the result SHALL show in a column beside the input and SHALL stay in view while the page scrolls. In narrower windows the result SHALL show under the frame box, before the tabs. The Examples tab SHALL group the frames by network and node, and SHALL show the example frames every time it is shown, including after switching from another tab and after coming back to the Frame lab.

#### Scenario: Wide result beside the input
- **WHEN** the window is 1440 by 900 px and the user picks node 5's EMCY example
- **THEN** the result's meaning, identifier and data bits show beside the examples without scrolling the page

#### Scenario: Narrow result under the frame box
- **WHEN** the window is 1000 by 800 px and the user builds an SDO read
- **THEN** the result's meaning is inside the window without scrolling

#### Scenario: Arbitration result in the result column
- **WHEN** the user runs the arbitration demo at 1440 px
- **THEN** the demo's diagram and text show in the result column

#### Scenario: Examples after switching tabs
- **WHEN** the examples have loaded and the user picks Build, then Examples again
- **THEN** the Examples tab shows the example frames grouped by network and node, and no text such as `[object HTMLDivElement]`

#### Scenario: Examples in Commission a device after coming back
- **WHEN** in Commission a device the user opens the Frame lab, goes to the Nodes tab and back to the Frame lab
- **THEN** the Examples tab shows the example frames

### Requirement: Clear the Frame lab result
A Frame lab result SHALL have a **Clear** button that removes the result and empties the frame box, and leaves the chosen tab, the builder's values and the bit rate as they were. Esc in the frame box SHALL do the same. A frame from the trace SHALL keep **Back to trace** until Clear, an edit or another frame replaces it.

#### Scenario: Clear
- **WHEN** the user has explained `705#7F` and presses Clear
- **THEN** the result is gone, the frame box is empty and has the focus, and the Build tab still has its values

### Requirement: Frame lab result in view
Each new Frame lab result SHALL come into view without the user scrolling:
- Explain;
- an example frame;
- Build and explain;
- Run both;
- Explain in Frame lab from the trace.

The focus SHALL stay on the control the user used. On a result from Explain in Frame lab, the focus SHALL go to the result's heading.

#### Scenario: Explain in Frame lab at 1000 px
- **WHEN** the window is 1000 by 800 px and the user picks Explain in Frame lab on a SYNC frame
- **THEN** the Frame lab shows the frame's meaning and Back to trace inside the window

### Requirement: Simulation banner on one line
While any part of the config is simulated, the page header SHALL show a simulation chip with the warning tint and icon, for example "Simulated: 4 networks". The chip SHALL stay in view while the page scrolls and SHALL take no row of its own. Its **Details** popover SHALL say what is simulated, network by network (for example "io (nodes 5, 6, 7)"), and that the configuration must not be uploaded to a machine as it is. The chip SHALL fit the header at every width; on a phone-width window it MAY shorten to "Simulated".

#### Scenario: Four simulated networks
- **WHEN** the virtual plant example is open at 1440 px
- **THEN** the header shows the chip "Simulated: 4 networks", and Details lists io (nodes 5, 6, 7), motion (node 4), cell and host and says not to upload it

#### Scenario: Stays in view
- **WHEN** the virtual plant example is open and the user scrolls a long node page down
- **THEN** the simulation chip stays in the header with the warning tint and icon

### Requirement: Add note picker
**Add note…** SHALL open a picker of every object and sub-object of the node's EDS with a search by index or name; each row shows the object, its name and where its note comes from. A click anywhere on a row SHALL pick that object and open its Note editor. The picker SHALL fit its dialog without sideways scrolling at 1000 px; long names SHALL wrap. Rows SHALL show a hover tint and the focused row the selected tint of the Object dictionary tab.

#### Scenario: Pick by clicking a row
- **WHEN** the user opens Add note… and clicks the name "Save_Communication_Parameters" in the row of 0x1010:2
- **THEN** the Note editor of 0x1010:2 opens

#### Scenario: Nothing hidden sideways
- **WHEN** the user opens Add note… for an EDS with long object names in a window 1000 px wide
- **THEN** every column is visible and the list scrolls only up and down

### Requirement: Add note picker by keyboard
Each row of the Add note picker SHALL hold one button named after the object (for example "Write a note for 0x2010:0 Ramp_time"). Down in the search SHALL move to the first row, Up and Down SHALL move between rows, Up on the first row SHALL go back to the search, Enter or Space SHALL pick the focused row, Enter in the search SHALL pick the first match, and Escape SHALL close the picker.

#### Scenario: Pick by keyboard
- **WHEN** the user types `1010` in the search, presses Down twice and Enter
- **THEN** the Note editor of 0x1010:1 opens

### Requirement: Device EDS carried into a config
**Add to a config…** in Commission a device SHALL carry the node's EDS into the opened config when the node has one in Commission: from Add node from EDS…, picked on the node's page or in Trace, or the scan match. The EDS SHALL be added to the config as an unsaved EDS import, and the dialog SHALL NOT ask for the EDS file.

#### Scenario: Node added from an EDS
- **WHEN** the user adds node 23 with Add node from EDS… in Commission a device, presses Add to a config… on node 23's page and picks a standalone config folder without that EDS
- **THEN** the config opens with node 23 added as an unsaved node using that EDS, and no "only EDS files" error is shown

#### Scenario: Same EDS already in the config
- **WHEN** the config folder already holds the identical EDS file
- **THEN** node 23 uses that file and no second copy is added

#### Scenario: Different EDS with the same name
- **WHEN** the config folder holds a different file with the same name
- **THEN** the carried EDS is kept under a new name and node 23 uses it

### Requirement: EDS carry failure keeps Commission
When the node's EDS cannot be carried into the config, the config folder SHALL NOT open. The page SHALL stay in Commission a device with its connection and log, and the banner SHALL name the EDS and the reason.

#### Scenario: EDS cannot be read
- **WHEN** the node's EDS file was removed from the EDS library before Add to a config…
- **THEN** the page stays in Commission a device with the log and connection kept, and the banner names the EDS that could not be carried

### Requirement: Result of a PDO layout read
A PDO layout read in Commission a device SHALL keep, for each PDO with a valid COB-ID, whether it now decodes, and if not, the first object not read and why (abort code and text, or no answer). A mapping read with no answer SHALL be tried once more. The message after **Read PDOs from device** SHALL name as read only the PDOs that now decode and each other PDO with its reason, and SHALL be an error when no PDO decodes.

#### Scenario: Mapping not readable
- **WHEN** the user presses Read PDOs from device for node 49, whose TPDO1-3 communication objects answer and whose mapping objects get no answer, even when tried again
- **THEN** the error message says that no PDO of node 49 decodes and names 0x1A00:0 not read (no answer)

#### Scenario: One PDO not usable
- **WHEN** node 49's TPDO1 and TPDO2 read completely and reading 0x1A02:1 is aborted with 0x06020000
- **THEN** the message reads "Node 49: TPDO1, TPDO2 read from the device." and names TPDO3 with "TPDO3 not usable: 0x1A02:1 not read (abort 0x06020000, object does not exist in the object dictionary)", and TPDO1 and TPDO2 frames decode

### Requirement: PDO layout read result in the Decoding panel
The Decoding panel's PDO layout column SHALL show the node's last read: the PDOs read from the device with the time, and each PDO that does not decode with its reason; "not read" with the reason when no PDO is usable. "unknown" SHALL be shown only for a node never read and with no other layout source. A node with an EDS SHALL keep decoding with its EDS defaults the PDOs whose mapping the device did not give.

#### Scenario: Nothing usable
- **WHEN** a read of node 49 gave no usable PDO because 0x1A00:0 got no answer
- **THEN** node 49's PDO layout column reads "not read" with that reason instead of "unknown"

#### Scenario: Automatic read
- **WHEN** an automatic read of node 32 gives TPDO1 but TPDO2's mapping is aborted
- **THEN** no message is shown, and node 32's row shows TPDO1 read from the device and TPDO2 with its reason on its own line

### Requirement: Trace in its own window
The Trace view SHALL have an **Open in new window** button that opens the trace in a separate browser window, so the trace can be watched while the main window sends messages or edits the config. It SHALL NOT be shown below the phone width, and SHALL bring an already open trace window to the front.

#### Scenario: Watch the trace while sending
- **WHEN** the user records in Trace, presses **Open in new window**, and then sends an SDO write from the online view in the main window
- **THEN** the trace window keeps recording and shows the SDO request and response as they happen

### Requirement: Trace window contents
The trace window SHALL show only the Trace view (toolbar, header, view tabs and transmit list) under a one-line bar naming the project folder, network and connection, titled "Trace" and the folder's name. It SHALL use the main window's session, recording and connection, with no Connect button of its own, and SHALL stay a trace window when reloaded. Its last size SHALL be kept with the trace view settings.

#### Scenario: No connection
- **WHEN** the trace window is open and nothing is connected
- **THEN** it says that recording needs a connection made with **Connect…** in the main window

#### Scenario: Main window changes network
- **WHEN** the main window connects to another network or opens another project folder
- **THEN** the trace window follows it

### Requirement: Main window while the trace has its own window
While the trace window is open, the main window's Trace tab SHALL say "Trace is open in its own window" with **Show trace window** and **Bring trace back here**, and SHALL NOT draw or poll the trace. Actions in the trace window that lead to another view (Explain in Frame lab) SHALL be carried out in the main window, or open the main page when it was closed.

#### Scenario: Bring the trace back
- **WHEN** the trace window is open and the user presses **Bring trace back here** in the main window's Trace tab
- **THEN** the trace window closes and the main window's Trace tab shows the same recording, with no frames lost

#### Scenario: Explain a frame from the trace window
- **WHEN** the user selects a frame in the trace window's Chronological view and presses **Explain in Frame lab**
- **THEN** the main window shows the frame in the Frame lab and the trace window stays open; **Back to trace** there selects the frame in the trace window

### Requirement: Closing a trace window
Recording SHALL go on when either window closes. Closing a window SHALL ask about an unsaved recording only when no other window shows it: the main window asks only while no trace window is open, the trace window only when no main window is left.

#### Scenario: Main window closed
- **WHEN** the user closes the main window during a recording while the trace window is open
- **THEN** the trace window keeps recording and the main window asks nothing about the recording, and closing the trace window after that asks about the unsaved recording

#### Scenario: Trace window closed
- **WHEN** the user closes the trace window
- **THEN** the main window's Trace tab shows the trace again

### Requirement: Selected row in every list
Every list and table of the configurator whose rows are items (objects, nodes, messages, frames, writes, signals, routes, notes, devices) SHALL show a selected row the same way as the object dictionary view: a background tint across the whole row and an accent bar on its left edge, a lighter tint under the mouse pointer, and `aria-current` on the row. The network tree's selected entry SHALL use the same look. Key/value status tables and bit grids SHALL NOT be selectable.

#### Scenario: Startup SDO picker
- **WHEN** the user clicks the name of object 0x1010:2 in a node's Startup SDO writes picker
- **THEN** that row, from its object to its Add button, is highlighted with the tint and accent bar, and no other row of the picker is

#### Scenario: Trace row looks the same
- **WHEN** the user selects a frame in the Chronological trace list
- **THEN** its row shows the same tint and accent bar as a selected row in the object dictionary view, not a solid accent fill

### Requirement: Selecting a row in a list
Clicking anywhere on a row of a selectable list, its buttons included, or moving keyboard focus into it SHALL select that row, with at most one selected row per list. Escape in the list SHALL clear the selection, except in lists whose selection drives an inspector (Chronological, By identifier, Frame lab), which keep their own keys. The selection SHALL be kept while the page redraws, a live value refreshes or a filter hides and shows the row, until the page is reloaded, and SHALL NOT be saved.

#### Scenario: Button selects its row
- **WHEN** the user presses Add on object 0x2001:0 in the SDO variables picker
- **THEN** that row is highlighted and the variable is added as before

#### Scenario: Kept through a redraw
- **WHEN** a row of the Startup SDO writes list is selected and the user edits that write's value
- **THEN** the row is still highlighted after the page redraws

#### Scenario: Keyboard
- **WHEN** the user tabs to a Remove button in the gateway routes table and then presses Escape outside a text field
- **THEN** the route's row is highlighted when the focus arrives and the highlight goes away on Escape

### Requirement: Resizable list boxes
Each fixed-height list box on the page (the node page's pickers, the slave's objects, gateway routes, table scroll boxes, Frame lab lists, the bridge map, the problems list) SHALL have a resize bar under it. Dragging the bar, or Up and Down by 40 px while it has the focus, SHALL change the height between 120 px and 3000 px; double-click SHALL restore the default. Lists in dialogs SHALL keep fitting the window.

#### Scenario: Keyboard and reset
- **WHEN** the bar under the PDO picker has the focus and the user presses Up twice, then double-clicks the bar
- **THEN** the picker is 80 px shorter after the key presses and back to its default height after the double-click

### Requirement: List box heights kept
The height chosen for a resizable list box SHALL be kept per kind of box in the configurator's page settings on this PC, and SHALL apply to that box on every node and after a reload.

#### Scenario: Taller SDO picker
- **WHEN** the user drags the bar under node 5's Startup SDO writes picker down by 300 px
- **THEN** the picker shows more rows, and node 7's Startup SDO writes picker opens at the same height

#### Scenario: Kept after reload
- **WHEN** the user has made the SDO variables picker taller and reloads the page
- **THEN** the SDO variables picker opens at the chosen height

### Requirement: Device notes in the SDO variables picker
Each object row of the SDO variables picker SHALL show the object's device note line under its name, as the Startup SDO writes picker does, and each added SDO variable SHALL show its object's note line under its header.

#### Scenario: Picker row with a note
- **WHEN** object 0x2001:0 has a device note and the user opens the SDO variables picker
- **THEN** the note line appears under the object's name in the picker row

#### Scenario: Added variable
- **WHEN** the user adds 0x2001:0 as an SDO variable
- **THEN** the variable's block shows the object's note line under its header

### Requirement: Whole notes on pickers and lists
Under an object's name on the PDO, Startup SDO writes and SDO variables pickers, the Startup SDO writes list, PDO entries and SDO variables, the configurator SHALL show the object's merged note whenever it has text, a unit, a scale, named values or bit meanings: the text, then a line with the unit, scale and named values or bits. The picker filters SHALL also match note text.

#### Scenario: Note with named values only
- **WHEN** object 0x2002:0 has a note with named values 0 = off and 1 = on and no text
- **THEN** the PDO, Startup SDO writes and SDO variables pickers show "0 = off, 1 = on" under its name

#### Scenario: Filter by note text
- **WHEN** an object's note text says "pump pressure" and the user types "pressure" in the Startup SDO writes picker's filter
- **THEN** that object is listed

### Requirement: EMCY section follows the EDS
When the node's EDS has no object 0x1014, the Emergency (EMCY) section SHALL hold only one line saying that the EDS has no EMCY COB-ID (0x1014), so the device sends no emergency messages, and no controls. Such a node SHALL be saved without EMCY fields. A loaded node that still has one SHALL show the bridge's message and offer to remove the EMCY settings; the hand-off steps SHALL refuse the config until they are removed.

#### Scenario: Device without EMCY
- **WHEN** the user opens the Supervision tab of a node whose EDS has no 0x1014
- **THEN** the Emergency section shows only the line that the EDS has no 0x1014, no EMCY field, Suggest button or COB-ID choice, and the saved node has no EMCY field

#### Scenario: Leftover EMCY mapping
- **WHEN** a loaded config gives `emcy_code_location` `%IW30` for a node whose EDS has no 0x1014
- **THEN** the section shows the problem in warning colour with "Remove the EMCY settings", and the hand-off steps refuse the config until the user presses it

### Requirement: Heartbeat consumer choice follows the EDS
When the node's EDS has no object 0x1016 with a writable sub-index, "Watches the master heartbeat" SHALL show "EDS default", be disabled, and say in hint text that the EDS has no consumer heartbeat time (0x1016), so the device cannot watch the master's heartbeat. The node's Heartbeat watch block SHALL NOT be shown while the node watches nobody. A loaded node that still has `heartbeat_consumer` or `heartbeat_watch` SHALL show the bridge's message and offer to remove it; the hand-off steps SHALL refuse the config until it is removed. The Heartbeat watch block SHALL span the section, with its heading and hint each on a line of their own.

#### Scenario: Device without 0x1016
- **WHEN** the user opens Advanced node settings of a node whose EDS has no 0x1016
- **THEN** the choice is disabled on "EDS default" with the reason, and the saved node has no `heartbeat_consumer`

#### Scenario: No heartbeat watch without 0x1016
- **WHEN** node 23's EDS has no 0x1016, it watches nobody, and the network has node 5
- **THEN** node 23's Supervision tab has no Heartbeat watch block

#### Scenario: Heartbeat watch layout
- **WHEN** node 5's EDS has a writable 0x1016 and the user opens its Supervision tab
- **THEN** "Heartbeat watch" is a heading on its own line above its hint, across the section's width

### Requirement: One look for EDS limits
The reason why a node setting is disabled because the node's EDS lacks what it needs (LSS, 0x1020, 0x1010, 0x1014, 0x1016) SHALL be shown as hint text, in the same colour and size as the other hints of the page. Warning colour SHALL be used only when the config still has a setting the EDS cannot back, together with a way to remove it.

#### Scenario: Same colour for LSS and configuration check
- **WHEN** a node's EDS has no LSS and no 0x1020, and its config has neither `lss` nor `config_check`
- **THEN** the LSS reason and the Configuration check reason have the same text colour, in light and dark theme

### Requirement: One look for messages
Every message about a page, view, section or dialog SHALL be a message bar of one of four kinds: information, done, warning or error. Each kind SHALL have one tint, one left accent bar in its state colour and one state icon, the same on every page, tool tab and dialog, in light and dark theme. Information and done SHALL use the neutral tint; warning the warning tint; error the error tint.

#### Scenario: Same warning everywhere
- **WHEN** the user sees a warning in the message bar, in a node's Parameters tab and in the Simulation view
- **THEN** the three have the same tint, accent bar and warning icon

#### Scenario: Dark theme
- **WHEN** the theme is Dark
- **THEN** each kind uses the dark values of its tokens and its text keeps the normal text colour

### Requirement: Message actions
A message bar MAY carry actions after its text, such as Undo, Unlock…, Remove, Details or Retry, as buttons in the same row. The text SHALL say what happened and what to do, with no "Error:" or "Warning:" prefix, as the word list says.

#### Scenario: Locked with Unlock
- **WHEN** the user is connected read-only and opens node 5's Error history
- **THEN** a warning bar says "Locked. Changes are not allowed on this connection." with Unlock… in the same bar

### Requirement: Messages at the top
A message SHALL sit at the top of what it is about. A view's or section's message SHALL sit directly under its heading, before its first control. No message SHALL sit below a section's buttons or at the bottom of a view or panel. Several messages in one place SHALL be ordered error, warning, information, done.

#### Scenario: Parameters job result
- **WHEN** Read all on node 5's Parameters tab ends
- **THEN** its result is a bar under the Parameters heading, above the buttons, and nothing is added at the bottom of the tab

#### Scenario: Connection line in Nodes
- **WHEN** the user opens Commission → Nodes without a connection
- **THEN** the line saying what the view needs a connection for is under the heading, above the scan toolbar

#### Scenario: NMT locked note
- **WHEN** the user is connected read-only and opens node 5's Status tab
- **THEN** the NMT box's locked note is at the top of the box, above Start, Stop and the other NMT buttons

### Requirement: Field text stays at the field
A hint, a field's own error, a table row's own error and a value read into a row SHALL stay next to the field or in the row, and SHALL NOT be message bars. The Problems panel and the status bar SHALL stay at the bottom of the page, and Problems rows SHALL use the warning and error tints and icons of the message bars.

#### Scenario: Send row error
- **WHEN** a row of the Send panel has an identifier out of range
- **THEN** the error is in that row, next to the identifier field

### Requirement: Messages in dialogs
A message about a dialog's work SHALL be a message bar at the top of the dialog body, under its title or question, while the dialog is open. A dialog SHALL NOT report in the page's message bar behind it or refer to it.

#### Scenario: Connect fails
- **WHEN** the user presses Connect in the connect panel and the runtime does not answer
- **THEN** an error bar at the top of the panel says why, the panel stays open, and the page's message bar is unchanged

#### Scenario: Nothing to restore
- **WHEN** the restore preview finds no differences
- **THEN** an information bar at the top of the dialog says so

### Requirement: Announced once
An error bar SHALL have the alert role and a warning, information or done bar the status role when it appears or changes. A bar that is drawn with its view SHALL NOT be announced again when the view opens.

#### Scenario: Opening a locked tab
- **WHEN** the user opens the Object dictionary tab while connected read-only
- **THEN** the locked bar is shown and a screen reader does not read it unless the user moves to it

### Requirement: Raw signal length errors
An empty or invalid raw signal length SHALL be reported as a field problem; the check SHALL NOT fail.

#### Scenario: Cleared length
- **WHEN** the user clears a raw signal's Length
- **THEN** Problems shows the length error and the hand-off steps refuse the config

### Requirement: References follow node and network changes
Changing a node ID SHALL update PDO links and heartbeat watches that name the node. Removing a node SHALL list the links, routes and watches that use it and offer to remove them. Renaming or removing a network SHALL update the Modbus bridge live lists.

#### Scenario: Node ID change
- **WHEN** a PDO link's producer is node 10 and its ID changes to 11
- **THEN** the link names node 11 and no problem is shown

#### Scenario: Network rename
- **WHEN** the network in a bridge live list is renamed
- **THEN** the live list follows the new name

### Requirement: Quiet status while the runtime is away
While the runtime does not answer, the online status SHALL be reported without an HTTP error on every poll.

#### Scenario: Runtime stopped
- **WHEN** the connected runtime stops answering
- **THEN** the page shows the connection state and the console has no repeated errors

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

### Requirement: Variable names of PDO entries
The PDO table SHALL have a Variable column for every target, editing the entry's `name`, with the full name the declarations and exports will use as placeholder (for OpenPLC the declared name, such as `io_rtd_AI0_Input_PV`). The entry SHALL show a "declared as" line only when the editor project declares its location under a different name. The Location column SHALL be shown only for targets that use locations, also when an entry of a target without locations still has one.

#### Scenario: Rename a channel
- **WHEN** the user types `door_open` as the variable of an entry in a CODESYS project
- **THEN** the entry gets `name` `door_open` and the CODESYS export names that channel `<node>_door_open`

#### Scenario: No Location column for CODESYS
- **WHEN** a CODESYS project has an entry with `iec_location` left over
- **THEN** the PDO table's columns are Object, Name, Type, Variable, PDO and the remove button

#### Scenario: One name shown
- **WHEN** node 5's entry 0x7130:1 has no `name`, its location `%IW100`, and the project declares `io_rtd_AI0_Input_PV AT %IW100`
- **THEN** the Variable field's placeholder reads `io_rtd_AI0_Input_PV` and no "declared as" line is shown

### Requirement: CODESYS settings
A CODESYS project SHALL have a "CODESYS" page in the tree with the project file, the device that gets the bus, the PLC device for a new project and variable names on or off, and each CANopen master network's Bus page SHALL have the CODESYS network number and CAN interface object, all stored in the config's `codesys` objects. The project file SHALL have **Browse…** (Requirement: CODESYS project file dialog), and a project file without an extension SHALL get `.project`. The PLC device for a new project SHALL be a dropdown of the PLC devices installed in CODESYS (Requirement: PLC devices installed in CODESYS) with "Other…" for typing `TYPE:ID:VERSION`, and SHALL be shown only while the project file does not exist; for an existing project the page SHALL say that canworks adds the bus to it.

#### Scenario: Network number
- **WHEN** the user sets the CODESYS network number of network `field` to 0
- **THEN** the config's network `field` gets `codesys.net_id` 0 and the next CODESYS build uses network number 0

#### Scenario: New project file
- **WHEN** the user types `C:\Projects\cell` as the project file and no such file exists
- **THEN** the field shows `C:\Projects\cell.project` and the PLC device dropdown is shown

#### Scenario: Existing project file
- **WHEN** the project file names an existing `.project` file
- **THEN** the PLC device field is hidden and the page says canworks adds the bus to the existing project

### Requirement: CODESYS actions
A CODESYS project SHALL have **Build into CODESYS project…** in the header and on the CODESYS page, and **Download for CODESYS** in Export ▾ and on the CODESYS page.

Build SHALL:
- require a saved config and a project file;
- run the `--codesys-import` route of `canopen-deploy` with the config's settings;
- show CODESYS's report, its first sentence naming the device the bus went to and why (from the report's device line);
- when CODESYS is not found on this PC, say so and point to Download.

When the project file does not exist and no PLC device for a new project is set, Build SHALL NOT run CODESYS. It SHALL ask whether to create a new project, with the PLC device dropdown. **Create and build** SHALL set the device, save and build, and Cancel SHALL change nothing. Build failures SHALL be worded in the page's terms (fields and buttons), not command-line options.

Download SHALL offer the `codesys-export` folder as `<config folder name>_codesys.zip` and write no file in the project or config folder. On errors it SHALL download nothing and list them in Problems.

#### Scenario: Build
- **WHEN** a saved CODESYS project names `C:\Projects\cell.project` and the user clicks Build into CODESYS project on a PC with CODESYS
- **THEN** the project gets the bus and the page shows CODESYS's report with its result

#### Scenario: Build names the device
- **WHEN** the build's report says the bus went to `ExampleApp (active application)`
- **THEN** the dialog's first sentence names `ExampleApp` and that it is the active application's device

#### Scenario: Build a new project
- **WHEN** the project file `C:\Projects\new.project` does not exist, no PLC device is set and the user clicks Build
- **THEN** a dialog asks to create a new CODESYS project with a PLC device dropdown, and Create and build saves the device and builds `C:\Projects\new.project` with it

#### Scenario: Cancel the new project
- **WHEN** the create dialog is open and the user presses Cancel
- **THEN** the config is unchanged and CODESYS does not run

#### Scenario: Project open in CODESYS
- **WHEN** the build fails because the project is open in the CODESYS window
- **THEN** the page shows the failure with the hint to close the project in CODESYS first

#### Scenario: No CODESYS
- **WHEN** the user clicks Build on a PC without CODESYS
- **THEN** the page says CODESYS was not found and offers Download for CODESYS

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

### Requirement: Commission in a CODESYS project
In a CODESYS project, Commission SHALL connect through a USB adapter only, since no canworks runtime runs the bus.

#### Scenario: Connect
- **WHEN** the user opens Commission in a CODESYS project
- **THEN** the connect dialog offers the USB adapter and no runtime

### Requirement: Bit channels in the PDOs tab
An integer entry in a PDO mapping table SHALL have **Bits…**, which unfolds a table of the entry's bits: bit number, the device note's bit name, a tick that maps the bit and the name (placeholder: the default name). A bit has no location of its own: it is a bit of the entry's value at the entry's location (see `canopen-pdo-io`, "Bit channels of a PDO entry"). **Bits…** SHALL show how many bits are mapped. **Map all bits** SHALL map every bit; **Unmap all** SHALL remove them. A newly mapped bit SHALL take its name from the device note's bit name, turned into an identifier, when there is one; renaming or removing a note SHALL NOT change a mapped bit's name. Unticked bits of an RPDO entry without a location SHALL read "sent as 0". Each change SHALL be one undo step, and problems SHALL name the node, the PDO, the object and the bit. In a CODESYS config the location column SHALL be hidden; in a Modbus bridge config it SHALL show the bit's coil or discrete input number, read-only.

#### Scenario: Names from the statusword note
- **WHEN** the user opens **Bits…** on a drive's 0x6041 entry and presses **Map all bits**
- **THEN** 16 bits are mapped, bit 0 named `ready_to_switch_on` from the built-in CiA 402 note, and each shows its discrete input number from the entry's location

#### Scenario: Rename a button
- **WHEN** the user maps bit 3 of node `panel`'s 0x6000:1 and types `jog_x_plus` as its name
- **THEN** the draft's entry has `{"bit": 3, "name": "jog_x_plus", "iec_location": ...}` and the located declarations show `panel_jog_x_plus`

#### Scenario: Output entry
- **WHEN** an RPDO entry 0x6200:1 has `%QB40` in a Modbus bridge config and the user ticks its bit 0
- **THEN** `%QB40` stays, and bit 0 shows its coil number from `%QB40`

### Requirement: Online bit values
With online access, a node's **Object dictionary** SHALL show, under the read value of an object that a PDO entry with bit channels maps, each mapped bit with its name and its state.

#### Scenario: Button state
- **WHEN** the panel's 0x6000:1 is 0x08 and bit 3 is named `jog_x_plus`
- **THEN** `jog_x_plus` shows as on and the other mapped bits as off

### Requirement: Quit from the page
Every page of the configurator, the start page included, SHALL have a **Quit** button in the header that stops the configurator. It SHALL always ask first: with unsaved changes offering Save and quit, Quit without saving and Cancel, otherwise Quit and Cancel. With an open adapter connection, send jobs, a trace recording or a PDO test it SHALL say they will stop. After quitting, the tab SHALL show that the configurator has stopped, that the tab can be closed, and how to start it again.

#### Scenario: Quit asks first
- **WHEN** the user presses Quit with nothing unsaved
- **THEN** the configurator asks whether to quit, and Cancel leaves it running

#### Scenario: Quit with unsaved changes
- **WHEN** the user has changed a node and presses Quit
- **THEN** the configurator asks; Save and quit saves and stops it, Cancel leaves everything as it was

#### Scenario: Quit while connected to an adapter
- **WHEN** the user is connected to a USB adapter with a cyclic send job and presses Quit
- **THEN** the dialog says the connection and the send job will stop, and after Quit the adapter is free for other tools

### Requirement: One configurator per user
A running configurator SHALL make itself known to later starts by the same user only, with a secret readable only by that user. A second `canworks-config` SHALL open a new start address of the running configurator in the browser and exit, and with a PATH SHALL ask the running configurator to open that folder, which SHALL ask first when the open config has unsaved changes. `--new-instance` SHALL start a separate configurator. A configurator that no longer runs SHALL NOT stop a new start.

#### Scenario: Started again after closing the tab
- **WHEN** the configurator runs and the user closed its tab, then runs `canworks-config` again
- **THEN** a tab opens on the running configurator with the same open folder, and no second server is started

#### Scenario: Another user on the same PC
- **WHEN** a second user on the same computer runs `canworks-config`
- **THEN** that user gets a configurator of their own and cannot reach the first user's

### Requirement: Closing the last tab stops the configurator
The configurator SHALL stop when its last page is closed: 10 s after the page said it was closing, so that a reload does not stop it. A page that stopped answering without saying it was closing (browser crash, a locked screen, sleep) SHALL count as closed only when its last answer said it had no unsaved changes and then only 60 minutes after that answer; a page whose last answer said it had unsaved changes SHALL NOT count as closed until it says it is closing, the configurator is quit, or it is stopped by a signal. Time in which the configurator itself did not run (the computer slept) SHALL NOT count toward the 60 minutes on any operating system. When it stops by itself, its log SHALL say why, with different words for a closed page (`its last page was closed`) and a silent one (`its last page sent no heartbeat for 60 minutes`). Stopping SHALL close every connection as Disconnect does. Closing or reloading a page SHALL always first get the browser's leave-page question (browsers show it only after the user has clicked or typed on the page, and with their own wording). `--keep-running` SHALL keep the configurator running without pages until Quit or Ctrl-C, for scripts and remote use.

#### Scenario: Tab closed
- **WHEN** the user closes the configurator's only tab with nothing unsaved
- **THEN** within 15 s the configurator has stopped, its terminal (if any) shows the prompt again, its USB adapter is free, and its log says its last page was closed

#### Scenario: Browser quit
- **WHEN** the user quits the browser while it shows the configurator's only tab with nothing unsaved
- **THEN** within 15 s the configurator has stopped

#### Scenario: Reload
- **WHEN** the user reloads the page
- **THEN** the configurator keeps running and the page comes back with the same folder and connection

#### Scenario: Two tabs
- **WHEN** two tabs of the configurator are open and the user closes one
- **THEN** the configurator keeps running

#### Scenario: Closing asks first
- **WHEN** the user has worked on the page and closes the tab
- **THEN** the browser asks first whether to leave the page, and Cancel keeps the configurator running

#### Scenario: Screen locked
- **WHEN** the configurator's only tab is open in a browser that stops its timers while the screen is locked, and the screen stays locked for 20 minutes
- **THEN** after unlocking, the page works without a reload and Save works

#### Scenario: Unsaved changes and a silent page
- **WHEN** the page has unsaved changes and sends no heartbeat for two hours
- **THEN** the configurator keeps running, and the page can save when it answers again

#### Scenario: Browser crashed
- **WHEN** the browser stops without the page saying it is closing and the page had nothing unsaved
- **THEN** the configurator stops 60 minutes after the page's last heartbeat, and its log says its last page sent no heartbeat for 60 minutes

#### Scenario: Computer slept
- **WHEN** the computer sleeps for two hours with the configurator's tab open and nothing unsaved
- **THEN** after waking, the configurator is still running and the page works without a reload

### Requirement: Start without a terminal
`canworks-config` SHALL by default start the configurator detached from the terminal (with no console window on Windows), print its start address, ask the browser to open it and return as soon as the browser was asked (without waiting for the page to load), writing its output to a log file in the configurator's settings folder, kept to 1 MB plus one older file. `--foreground` SHALL keep it in the terminal as before, stopped also by Ctrl-C. It SHALL start in the foreground by itself with `--no-browser` or `--keep-running`, in an SSH session, and on Linux without `DISPLAY` or `WAYLAND_DISPLAY`. When no page has opened 15 s after the browser was asked to open it, the background configurator SHALL write its start address to the log and, when it was started from the app shortcut, show it in a message window (Windows message box, macOS dialog, Linux desktop dialog or notification when one is available) from which the address can be copied. A configurator whose first page has not opened within 10 minutes of starting SHALL stop. In every case it SHALL stop when its last tab closes, or by Quit.

#### Scenario: Terminal closed
- **WHEN** the user runs `canworks-config` and closes the terminal
- **THEN** the prompt came back at once, the configurator keeps running and its page keeps working

#### Scenario: Foreground
- **WHEN** the user runs `canworks-config --foreground`
- **THEN** the configurator runs in the terminal, prints its messages there, and Ctrl-C stops it

#### Scenario: Over SSH
- **WHEN** the user runs `canworks-config` in an SSH session
- **THEN** it stays in the terminal, as with `--foreground`

#### Scenario: Browser does not open from the shortcut
- **WHEN** the user starts the configurator from the shortcut and no browser opens
- **THEN** after about 15 s a message window shows the start address to copy into a browser, and the configurator waits up to 10 minutes for it

#### Scenario: Browser does not open from a terminal
- **WHEN** the user runs `canworks-config` and the browser does not open
- **THEN** the terminal already shows the start address, the prompt is back, and no message window appears

#### Scenario: Prompt back before the page loads
- **WHEN** the user runs `canworks-config` and the browser is slow to load the page
- **THEN** the prompt comes back once the browser was asked, without waiting for the page

#### Scenario: Background start fails
- **WHEN** the configurator cannot start (for example the folder given cannot be opened)
- **THEN** `canworks-config` prints the reason from the log and exits non-zero

### Requirement: App shortcut
`canworks-config --create-shortcut` SHALL add a shortcut that starts the configurator with no terminal: on Windows a Start menu and a desktop shortcut that run it with `pythonw` (no console window) and `--from-shortcut`, on macOS an app "canworks configurator" in `~/Applications`, on Linux a `.desktop` entry in the user's applications folder. The shortcut SHALL start the configurator from the installed PC tools, so it keeps working after an update. Started from the shortcut (`--from-shortcut`), the process SHALL itself become the background configurator when none runs, and otherwise open a tab of the running one and exit; it SHALL NOT start a second Python process. Writing the Windows shortcuts SHALL NOT use `-ExecutionPolicy Bypass`. `--remove-shortcut` SHALL remove what `--create-shortcut` added and nothing else. The one-line PC installers SHALL create the shortcut unless given `--no-shortcut` (`-NoShortcut` on Windows), and their uninstall SHALL remove it.

#### Scenario: Started from the shortcut
- **WHEN** the user double-clicks the shortcut
- **THEN** the browser opens on the configurator's start page and no terminal or console window appears

#### Scenario: One process from the shortcut
- **WHEN** the user double-clicks the shortcut and no configurator runs
- **THEN** the process the shortcut started serves the page, and no further Python process is started for it

#### Scenario: Shortcut while running
- **WHEN** the configurator already runs and the user double-clicks the shortcut again
- **THEN** a new tab opens on the running configurator

#### Scenario: Installer
- **WHEN** the user installs the PC tools with the one-line installer
- **THEN** the shortcut is there afterwards, and the installer's uninstall removes it

### Requirement: Page of a stopped configurator
When a page of the configurator becomes visible again, comes back from the browser's back/forward cache or gets focus, it SHALL ask the configurator at once whether it runs. When the configurator does not answer two asks in a row, 2 s apart, the page SHALL replace its content with a notice that canworks-config is not running any more and how to start it again (the app shortcut, or `canworks-config` in a terminal, which opens a new tab). A single unanswered ask SHALL NOT show the notice. With unsaved changes, the notice SHALL say that they could not be saved, SHALL offer **Download canworks.json** with the page's unsaved config, and SHALL name what the download does not hold (EDS and notes files imported since the last save, unsaved simulation edits). After the notice nothing on the page SHALL ask the configurator any more.

#### Scenario: Configurator gone while the page was hidden
- **WHEN** the configurator was stopped from a terminal while its tab was in the background, and the user returns to the tab
- **THEN** within 5 s the tab says canworks-config is not running any more and how to start it again, instead of showing a working page whose buttons fail

#### Scenario: Unsaved changes kept as a file
- **WHEN** the configurator stopped while its page had an unsaved node change, and the user presses Download canworks.json on the notice
- **THEN** the browser saves a canworks.json that holds the change, and opening it in a new configurator shows the node as edited

### Requirement: Words for a remote adapter connection
On a connection to an adapter on another machine, the configurator SHALL NOT call the connection a USB adapter connection, and SHALL name the host: the lock texts SHALL say changes are off for the connection to the adapter on HOST, and the trace SHALL report frames the adapter machine's kernel dropped as dropped by the adapter machine's kernel, not the PLC's.

#### Scenario: Locked remote adapter
- **WHEN** the user is connected read-only to an adapter on another machine and presses a write control
- **THEN** the message says changes are off for the connection to the adapter on that host, and does not say USB adapter

#### Scenario: Drops in a remote trace
- **WHEN** a trace through an adapter on another machine reports kernel drops
- **THEN** the trace summary says they were dropped by the adapter machine's kernel and names the host, and does not mention a PLC

### Requirement: Start timing in the log
Each start of the configurator SHALL write one line to its log with the time, in milliseconds from the moment the start was launched (the shortcut or `canworks-config`), at which Python was running, the configurator listened, the browser was asked and the first page loaded, and whether it was started from the shortcut or a terminal. A start whose page does not load SHALL log the line without the page time.

#### Scenario: Normal start
- **WHEN** the user starts the configurator from the shortcut and the page opens
- **THEN** `configurator.log` has one line like `start timing: python 140 ms, listening 420 ms, browser asked 450 ms, page 1310 ms (from shortcut)`

### Requirement: Light starter
The `canworks-config` command SHALL parse its arguments, find a running configurator and start or hand over without importing the configurator's server module or the diagnostics and config validation modules; only a process that serves pages SHALL import them. A unit test in CI SHALL import the entry module in a fresh interpreter and fail when the server or diagnostics module was imported.

#### Scenario: Starter import
- **WHEN** a fresh Python process imports the `canworks-config` entry module
- **THEN** neither `canworks.configurator.server` nor `canworks.diag` is in `sys.modules`

### Requirement: Placeholder look
Every input's placeholder SHALL look different from a value in both themes (muted colour and italic), so a default or example is never read as a filled-in setting. A placeholder that is an example rather than the value used when the field is empty SHALL start with "e.g.".

#### Scenario: Example placeholder
- **WHEN** the CODESYS page shows an empty project file field
- **THEN** its placeholder reads "e.g. C:\Projects\cell.project" in muted italic, unlike the typed text of other fields

### Requirement: CODESYS project file dialog
**Browse…** next to the CODESYS project file SHALL open the folder dialog (Requirement: Folder dialog) in a file mode that also lists the shown folder's `.project` files after its subfolders; picking one SHALL fill the field with its path. It SHALL start in the field's folder, else its nearest existing parent, else the home folder, and keep the folder dialog's Up, drives, typed path and keyboard use. Cancel SHALL leave the field as it was. Other folder dialogs SHALL NOT list files.

#### Scenario: Pick an existing project
- **WHEN** the user presses Browse…, opens `C:\Projects` and clicks `cell.project`
- **THEN** the dialog closes and the project file field holds `C:\Projects\cell.project`

### Requirement: New project name in the file dialog
The CODESYS project file dialog SHALL have a **New project name** field with **Create here** that fills the project file field with `<shown folder>\<name>.project` without writing a file. A name with slashes, or one whose file exists, SHALL be refused in the dialog.

#### Scenario: Name a new project
- **WHEN** the user opens `C:\Projects` in the dialog, types `line2` as New project name and presses Create here
- **THEN** the field holds `C:\Projects\line2.project`, no file is written and the PLC device dropdown is shown

### Requirement: PLC devices installed in CODESYS
The configurator SHALL list the PLC devices installed in CODESYS on this PC from CODESYS's device repository, each with its name and version, newest version first per name, and SHALL leave out devices that are not PLCs. The list SHALL be read once per configurator start, with a refresh in the dropdown. With no CODESYS or no readable repository the PLC device field SHALL be a text field for `TYPE:ID:VERSION`. A saved device not in the list SHALL be shown as typed.

#### Scenario: Pick the PLC
- **WHEN** CODESYS with CODESYS Control Win V3 x64 3.5.22.40 is installed and the user picks it in the dropdown
- **THEN** the config's `codesys.create` is that device's `TYPE:ID:VERSION`

#### Scenario: No CODESYS
- **WHEN** the configurator runs on a PC without CODESYS
- **THEN** the PLC device field is a text field with an example placeholder

### Requirement: Settings the target does not use are left out on save
Saving SHALL write the config without the values its target does not use (those the relevance table lists as removable), and the save message SHALL name how many were left out. Opening a config with such values SHALL NOT mark it unsaved. Values a target refuses and network kinds it cannot run SHALL keep their existing checks.

#### Scenario: Save a CODESYS config with old locations
- **WHEN** a CODESYS config with three PDO entries that still have `iec_location` is opened and saved
- **THEN** the file has no `iec_location`, and the message says 3 settings CODESYS does not use were left out

#### Scenario: Open without a change
- **WHEN** that config is opened
- **THEN** the header does not show it as unsaved

### Requirement: Hand-off steps need a config without errors
Build into CODESYS project and installing or updating the bridge config on a device SHALL use the saved config; Download for CODESYS SHALL use the draft. They SHALL refuse while the config they use has errors, and a CANopen master network without nodes SHALL count as one. A refusal SHALL be shown next to the control in one line naming the error count, with a link that opens Problems. Allowed overlaps SHALL NOT count. Exports of DCF, DBC and documentation SHALL keep their own rules.

#### Scenario: Build with an error
- **WHEN** a CODESYS config is saved with one error and the user presses Build into CODESYS project…
- **THEN** nothing runs, and the page says the saved config has 1 error, with a link to Problems

### Requirement: Empty network is a warning
A CANopen master network without nodes SHALL be one warning in Problems, not an error. The tree and the network's Bus page SHALL show the empty state: "No nodes yet", with **Add node…** and a pointer to finding devices in Commission. The hand-off steps SHALL still refuse a network without nodes.

#### Scenario: Fresh config
- **WHEN** the user creates a new Modbus bridge config
- **THEN** Problems shows one warning about the empty network and no error, and Save is not blocked

### Requirement: Supervision of a new node
When a node is added from an EDS whose heartbeat producer default (0x1017) is 0, the configurator SHALL give it supervision:
- `heartbeat_ms: 1000` when 0x1017 is writable;
- else node guarding at 1000 ms with life time factor 3, when the EDS supports guarding;
- else none, leaving the supervision problem.

Supervision SHALL say the value was set when the node was added.

#### Scenario: Node with a writable heartbeat
- **WHEN** the user adds a node from an EDS with 0x1017 writable and default 0
- **THEN** the node has a 1000 ms heartbeat and Problems shows nothing for it

### Requirement: Quick fixes in Problems
A problem MAY carry actions that fix it. Each action SHALL be one undo step. The supervision problem SHALL offer **Use heartbeat 1000 ms**, or **Use guarding** when the EDS only supports guarding, and **Accept no supervision**, which saves `heartbeat_ms: 0`. Its text SHALL name the field in the page's words (Supervision tab, heartbeat period) and SHALL NOT quote config keys.

#### Scenario: Fix from Problems
- **WHEN** node 2 has the supervision problem and the user presses Use heartbeat 1000 ms in Problems
- **THEN** node 2's heartbeat period is 1000 ms, the problem is gone, and Ctrl+Z brings it back

### Requirement: Errors in the New config dialog
The New config dialog SHALL show an error under the field it concerns, mark that field and move focus to it. The dialog's title SHALL stay.

#### Scenario: Empty name
- **WHEN** the user presses Create with an empty name
- **THEN** the Name field is marked with "Give the new config a name: it becomes its folder." under it and has focus, and the dialog's title still reads "New config"

### Requirement: Short window layout
When the window is 800 px high or less, the header and tab rows SHALL use compact spacing, and message bars SHALL use slim padding. A message bar SHALL never cover controls of the work area. The connection status SHALL sit at the right end of the sub-tab row in every window, and SHALL wrap to a second line only when that row is too narrow.

#### Scenario: Laptop at 150 %
- **WHEN** the window is 1280×720 with the virtual plant example in Commission, connected
- **THEN** the work area is at least 60 % of the window height

### Requirement: Header target action
The header SHALL hold the target's hand-off action as one primary button with no menu: **Build into CODESYS project…** for CODESYS, **Install on device…** for Modbus bridge, with or without an OpenPLC connection. Download for CODESYS SHALL be in Export ▾ (see "Export menu groups").

At 1280 px and wider the header SHALL be one row for every target, also while the simulation chip is shown (see "Header menus stay inside the window").

Under 1500 px with a config open, Reload from disk, Close, Settings and Quit SHALL be in one "⋯" menu. With no config open (start page, Devices without a config) they SHALL stay buttons in the header.

#### Scenario: CODESYS at 1366 px
- **WHEN** a CODESYS config is open at 1366 px wide
- **THEN** the header is one row with one Build button and no ▾ next to it

#### Scenario: OpenPLC with simulated nodes at 1280 px
- **WHEN** a Modbus bridge config with an OpenPLC connection and simulated nodes is open at 1280 px wide
- **THEN** the header is one row with Install on device…

### Requirement: Wide window sections
From 1800 px wide, the sections of a network's Bus page and of a node's Supervision tab SHALL lay out in two columns.

#### Scenario: Bus page at 2560 px
- **WHEN** the window is 2560 px wide and the user opens Bus and master
- **THEN** the sections are in two columns side by side

### Requirement: PDO table on a phone-width window
Under 640 px wide, each PDO entry SHALL be shown as a card with object and name, variable and location, and its PDO and Remove. The page itself SHALL NOT scroll sideways at any width. Only a table's own box MAY scroll sideways.

#### Scenario: Phone width
- **WHEN** the window is 375 px wide and the user opens node 5's PDOs tab
- **THEN** each entry is a card and the page has no sideways scroll

### Requirement: Work area share in the layout check
The browser layout check SHALL run at 1280×720 and 911×512 besides its other sizes. For the main views of both workspaces it SHALL check that the work area, the space between the fixed bars, is at least 55 % of the window height.

#### Scenario: A new bar
- **WHEN** a change adds another always-shown bar under the header
- **THEN** the layout check fails at 911×512 naming the view and the work area's share

### Requirement: Watch list only when used
The Watch list card SHALL be shown only while at least one entry of the node is watched. Before that, a one-line hint under the filters SHALL say how to watch an entry.

#### Scenario: Nothing watched
- **WHEN** the user opens node 6's Object dictionary tab with no watched entries and presses Read all
- **THEN** no Watch list card is shown above the groups, and the hint line is

### Requirement: Last heard in Commission
The Nodes table and the node header SHALL show the time since the node was last heard, from the bridge's status for a runtime connection and from the adapter for a direct one. "-" SHALL be shown only for a node never heard in the session.

#### Scenario: Heartbeat every 100 ms
- **WHEN** node 6 sends a heartbeat every 100 ms and the page is connected to the runtime
- **THEN** node 6's Last heard reads about "0.1 s ago"

### Requirement: Trace Start without a connection
Trace's **Start** while not connected SHALL open the connect panel and start the trace once the connection is up. Canceling the panel SHALL leave Trace as it was. No message on the page SHALL name the former Online view.

#### Scenario: Start first, connect after
- **WHEN** the user presses Start on Trace while not connected, then connects to the runtime in the panel
- **THEN** the trace starts recording without a second press and no error is shown

### Requirement: Add node dialog
**Add node…** SHALL open a dialog with:
- the device description: the list of "One EDS dialog", with the config's EDS files (product name, file name, nodes using it), the EDS library's files, and **Browse…**;
- the node ID: the lowest free ID, checked as typed;
- the name: from the EDS product name, unique in the network;
- **Map the EDS's default PDOs**, ticked.

**Add** SHALL add the node to that network. Cancel SHALL add nothing.

#### Scenario: Second node of a known type
- **WHEN** the virtual plant's `io` network has node 6 with `dio16.eds` and the user opens Add node…, picks dio16.eds from the list, and presses Add
- **THEN** a node with the lowest free ID and a unique name is added with `dio16.eds`, and no file picker was opened

#### Scenario: Taken node ID
- **WHEN** the user types 6 as the node ID in the dialog on `io`
- **THEN** the field says node 6 is already used and Add is disabled with that reason

#### Scenario: Double-click adds
- **WHEN** the node ID and name are valid and the user double-clicks `dio16.eds` in the list
- **THEN** the node is added as if Add was pressed

### Requirement: Default PDOs of a new node
With **Map the EDS's default PDOs** ticked, adding a node SHALL map, for each PDO the EDS enables by default (COB-ID without the invalid bit), the objects of its default mapping, leaving out dummy entries, with suggested names and, for targets that use locations, suggested free locations. Unticked, the node SHALL start with no PDO entries.

#### Scenario: I/O module defaults
- **WHEN** the user adds a node from an EDS whose TPDO 1 default maps 0x6000:1 and 0x6000:2 and whose RPDO 1 default maps 0x6200:1, with the box ticked
- **THEN** the node's TPDO 1 has the two inputs and RPDO 1 the output, each with a suggested location, and the PDOs tab is open

### Requirement: EDS check after adding a node
After a node is added, the EDS check SHALL show a message only when it has findings (the EDS cannot be read by the tools on the PLC, or lint warnings), in the message bar, with the findings in words. A clean EDS SHALL show no message.

#### Scenario: Clean EDS
- **WHEN** the user adds a node from an EDS without findings
- **THEN** no banner or message about the EDS is shown

### Requirement: Entries without a location
For a target that uses locations, a PDO entry without a location SHALL show "not mapped to the PLC" in warning text, with **Suggest** filling a free location.

#### Scenario: Unmapped output
- **WHEN** dio's RPDO 1 entry 0x6411:1 has no location
- **THEN** the row shows "not mapped to the PLC" and Suggest, and pressing Suggest gives it a free `%QW` location

### Requirement: Bus page of a simulated network
On a network set to Simulated, the CAN adapter section SHALL be folded to one line saying the adapter settings are kept for switching back, with **Show**. Its fields SHALL NOT be marked Required while folded. A choice that has one possible value for the target SHALL be shown as text, not as a dropdown.

#### Scenario: Simulated io
- **WHEN** the user opens Bus and master of the virtual plant's simulated `io` network
- **THEN** the CAN adapter section is one folded line with Show, and no field on the page says Required for the interface

#### Scenario: CODESYS role
- **WHEN** a CODESYS config's Bus and master page is open
- **THEN** Protocol reads "CANopen" and Role reads "Master" as text, without dropdowns

### Requirement: No empty message bars
No message bar or notice SHALL be shown without text. A notice whose text depends on a connection SHALL be hidden until it has text.

#### Scenario: Simulation without a connection
- **WHEN** the user opens Simulation while not connected
- **THEN** no warning bar without text is shown

### Requirement: Save to simulation file state
**Save to simulation file** SHALL be disabled, reading "Saved", while the simulation draft equals the file, and enabled only when it differs.

#### Scenario: Nothing changed
- **WHEN** the user opens a node's simulation tab without changing anything
- **THEN** the button reads "Saved" and is disabled

### Requirement: Parameters names and file buttons
On the Parameters tab, restoring a backup SHALL be named **Restore from backup…** and restoring factory values **Factory defaults (0x1011)…**, the latter in a section marked as changing the device. File choices SHALL use the page's button style with the chosen file's name next to it, not the browser's unstyled file input.

#### Scenario: Two restores
- **WHEN** the user opens node 6's Parameters tab
- **THEN** one button reads "Restore from backup…" and another "Factory defaults (0x1011)…", and no "Choose File / No file chosen" control is shown

### Requirement: Simulated value control range
The slider of a simulated value SHALL span the value source's range when the object has one, else the EDS limits of the object, else its type's range. **Set** and **Override** SHALL each have a tooltip saying that Set changes the value once and the source moves it again, while Override holds it until Release.

#### Scenario: Sine source
- **WHEN** node 5's 0x7130:1 has a sine source from 200 to 260 and the user opens Simulation live values
- **THEN** its slider spans 200 to 260

### Requirement: Device messages
The Add device dialog SHALL show a check message under the field it concerns, starting with a capital letter. A device that is not reached SHALL show one sentence without the SSH library's text ("Can't reach 192.0.2.10 on SSH port 22.") and a short list of what to check: SSH on the device, the same network, the address, the port. The device's action menu SHALL be named **Actions**.

#### Scenario: Unreachable
- **WHEN** the user adds 192.0.2.10 and nothing answers on port 22
- **THEN** the device reads "Not reached" with one sentence and the checklist, and no "[Errno" text is shown

### Requirement: Folder dialog marks projects
The folder dialog SHALL mark each listed folder that is an OpenPLC Editor project or holds a canworks config, with a tag ("OpenPLC project", "canworks config") before the user enters it. A single click SHALL select a folder, and double-click or Enter SHALL open it; **Use this folder** SHALL use the selected folder, or the current one when none is selected. The EDS count line SHALL be shown only when the dialog is picking an EDS folder.

#### Scenario: Pick the example
- **WHEN** the user opens Open… in a folder holding `virtual-plant` and clicks it once
- **THEN** `virtual-plant` is tagged "OpenPLC project" and selected, and Use this folder opens it

### Requirement: Network menu anchored
A network's ⋯ menu SHALL open as a menu anchored to its button, listing Rename…, Role and Remove… one per line, and SHALL close on Escape or a click outside.

#### Scenario: Open the menu
- **WHEN** the user presses ⋯ on network `io`
- **THEN** a menu opens next to the button, not a centred dialog

### Requirement: PDO headings per target
The PDOs tab headings and column titles SHALL use the target's words: "Inputs (TPDOs, device to Modbus registers)", "Outputs (RPDOs, Modbus registers to device)" and "Location" for the Modbus bridge, and "Inputs (TPDOs, device to CODESYS)" without a location column for CODESYS.

#### Scenario: Bridge headings
- **WHEN** a Modbus bridge config's node PDOs tab is open
- **THEN** no heading or column title says "PLC"

### Requirement: Small fixes on node tabs
- The SDOs tab SHALL title each table once.
- A startup write's value SHALL be shown in the same notation as its EDS default (both hex, or both decimal).
- The Notes tab SHALL show **Add note…** and **Import notes…** once.
- The Supervision tab SHALL group its PLC signal fields under "PLC signals", with **Suggest all** filling every empty one.

#### Scenario: Startup write notation
- **WHEN** a startup write to 0x6110:1 holds 0x1E and the EDS default is 0x1E
- **THEN** both read 0x1E

#### Scenario: Suggest all
- **WHEN** node 2 has no status bit, state byte, NMT command or boot error byte and the user presses Suggest all
- **THEN** each gets a free location

### Requirement: Graph series names
The Trace graph's series list SHALL show each series' whole name on hover and focus, and SHALL start with the first PDO signal ticked when no series was ticked before for the network.

#### Scenario: First graph
- **WHEN** the user opens Graph on a new trace of `io`
- **THEN** one series is drawn, and hovering a cut name shows it whole

### Requirement: Disabled and selected look different
A disabled primary button SHALL NOT share the fill of a selected tab or segment in either theme.

#### Scenario: Dark header
- **WHEN** the dark theme is on, the draft is saved and Configure is selected
- **THEN** the Saved button and the Configure segment have clearly different fills

### Requirement: Mode badge names the folder
The header's mode badge SHALL show the folder's name for both projects and config folders, with the full path in its tooltip.

#### Scenario: Config folder
- **WHEN** the config folder `/home/user/work/cs-machine` is open
- **THEN** the badge reads "config cs-machine" and its tooltip the full path

### Requirement: One EDS dialog
Every place that picks an EDS SHALL use one dialog. Its list SHALL group the files as **Matches this device**, **Built here**, **In this project** and **EDS library**, in that order, each shown only when it has files, and show each file's product name and file name. **Browse…** SHALL open the page's file browser on EDS files and import the picked file; a dialog without other fields SHALL use it at once, others SHALL select it.

#### Scenario: Same list in Configure and Commission
- **WHEN** the config has `dio16.eds` used by node 6, an EDS library is set, and the user opens Add node… in Configure and Choose EDS… for an unconfigured node in Commission
- **THEN** both dialogs list `dio16.eds` under In this project with its product name and "used by 1 node", and the library's files under EDS library

#### Scenario: Matches first
- **WHEN** the user opens Choose EDS… for a scanned node whose identity matches two library files, one with the exact revision
- **THEN** the list starts with Matches this device, the exact-revision file first and selected, marked "exact revision"

#### Scenario: Browse with a name clash
- **WHEN** the user presses Browse… in the dialog and picks a file named like an EDS already in the config but with other content
- **THEN** the page asks to replace it or keep both, and the kept file is selected in the list

#### Scenario: Library file imported on use
- **WHEN** the user selects an EDS library file and presses the dialog's main button
- **THEN** the file is imported with the place's EDS lint and used, and Cancel before that imports nothing

### Requirement: Selection in the EDS dialog
The current EDS, else the best match, SHALL be selected when the EDS dialog opens.

#### Scenario: Current EDS selected
- **WHEN** the user opens Change EDS… on a node that uses `dio16.eds`
- **THEN** `dio16.eds` is selected in the list

### Requirement: Keyboard in the EDS dialog
Enter or a double-click on an entry of the EDS dialog's list SHALL press the dialog's main button. The dialog SHALL open with focus in the list, or on **Browse…** when the list is empty, and focus SHALL return to the control that opened it when it closes.

#### Scenario: Pick with Enter
- **WHEN** the user moves to an entry with the arrow keys and presses Enter
- **THEN** the dialog acts as if its main button (Add, Add node, Use) was pressed

#### Scenario: Cancel
- **WHEN** the user opens Change EDS… on a node's General tab, selects another file and presses Escape
- **THEN** the node's EDS is unchanged, the draft is not marked changed, and focus is on Change EDS…

### Requirement: One EDS field
Where a page shows the EDS chosen for a node, slave or device, it SHALL show the product name and file name as text with **Choose EDS…** when there is none and **Change EDS…** when there is one, both opening the EDS dialog. No page SHALL show a dropdown of EDS file names or a browser file input for an EDS.

#### Scenario: Node General tab
- **WHEN** the user opens node 6's General tab
- **THEN** the EDS reads as its product name and `dio16.eds` with Change EDS…, and there is no EDS dropdown

#### Scenario: No file inputs left
- **WHEN** the browser tests open every view of Configure, Commission, Trace and Simulation with a config that has a slave network and a node without an EDS match
- **THEN** no visible `input[type=file]` accepts `.eds`, and no `select` lists EDS file names

#### Scenario: Simulation extra device
- **WHEN** the user presses Choose EDS… for a new extra device in the simulation view
- **THEN** the dialog's Browse… accepts EDS and DCF files and In this project lists the folder's EDS and DCF files

### Requirement: EDS chosen in one place per node
In Commission a device, a node's EDS SHALL be chosen only through its EDS field in the Nodes table and its EDS dialog. The Parameters tab, the Trace Decoding panel and the frame inspector SHALL open that field's dialog for the node. **Add to config** and **Add to a config…** SHALL use the node's EDS on the page and open its dialog first only when it has none.

#### Scenario: Trace uses the node's EDS
- **WHEN** the user presses Choose EDS… for node 50 in the Trace Decoding panel and picks a file
- **THEN** the Nodes table shows that EDS for node 50 and the trace decodes with it

#### Scenario: Add to a config without an EDS
- **WHEN** node 12 has no EDS on the page and the user presses Add to a config…
- **THEN** the EDS dialog opens for node 12 first, and the config dialog follows with the picked EDS, without a file input

### Requirement: Defaults of a new network
Every network the configurator creates SHALL start with its protocol's default bit rate: 500 kbit/s for CANopen (master or slave), 250 kbit/s for J1939 and 500 kbit/s for plain CAN. A new CANopen master SHALL start with node ID 1 and no SYNC (no `sync_period_us`). This SHALL hold for New config…, Add network…, switching a network's protocol or switching a slave back to master. **Add network…** SHALL NOT copy another network's bit rate. Switching a network's protocol SHALL change its bit rate to the new protocol's default only when the rate is the old protocol's default, and SHALL keep any other rate. Existing configs SHALL keep their settings.

#### Scenario: New config
- **WHEN** the user creates a new Modbus bridge config
- **THEN** the saved config's network has `"bitrate": 500000` and its master is `{"node_id": 1}` with no SYNC keys

#### Scenario: Add a J1939 network next to a CANopen one
- **WHEN** a config's first network runs at 500 kbit/s and the user adds a J1939 network
- **THEN** the new network's bit rate is 250 kbit/s

#### Scenario: Add a CANopen network
- **WHEN** the user adds a CANopen network
- **THEN** it runs at 500 kbit/s and its bus page shows SYNC source Off

#### Scenario: Switch a default network to J1939
- **WHEN** a CANopen network at 500 kbit/s with no nodes is switched to J1939
- **THEN** its bit rate is 250 kbit/s

#### Scenario: Switch keeps a chosen rate
- **WHEN** a CANopen network at 125 kbit/s is switched to J1939
- **THEN** its bit rate stays 125 kbit/s

### Requirement: SYNC Off on the bus page
A CANopen master's bus page SHALL offer **SYNC source** with two choices: **Off** (no SYNC) and **Timer**. The choice SHALL follow the config: Timer when `sync_period_us` is above 0, else Off. Off SHALL show no period field and remove `sync_period_us`. A config with `"sync_source": "plc_cycle"` is an error in Problems (see `canopen-config-contract`); the page SHALL NOT offer PLC cycle. Picking Timer SHALL set the SYNC period to 10 ms; emptying the period SHALL make the choice Off.

#### Scenario: Turn SYNC on
- **WHEN** on a new network the user picks SYNC source Timer
- **THEN** the SYNC period field shows 10 and the config has `"sync_period_us": 10000`

#### Scenario: Clear the period
- **WHEN** SYNC source is Timer and the user empties the SYNC period
- **THEN** SYNC source shows Off and the config has no `sync_period_us`

#### Scenario: Turn SYNC off from the PLC cycle
- **WHEN** a config of the removed plugin whose master has `"sync_source": "plc_cycle"`, `"sync_cycles": 2` and no `sync_period_us` gets Use with canworks-bridge
- **THEN** the master has no `sync_source` or `sync_cycles`, and SYNC source shows Off

#### Scenario: No PLC cycle choice
- **WHEN** the user opens SYNC source on any target
- **THEN** it lists Off and Timer only

### Requirement: Default PDOs on a network without SYNC
When a node is added with **Map the EDS's default PDOs** on a network that produces no SYNC, each mapped PDO whose EDS transmission type needs SYNC (0-240 or 252) SHALL get transmission type 255, unless the EDS marks that type read-only, and the add message SHALL name those PDOs. On a network with SYNC, the PDOs SHALL keep their EDS transmission type.

#### Scenario: Synchronous EDS default without SYNC
- **WHEN** a network has no SYNC and the user adds a node whose EDS gives TPDO 1 transmission type 1, with the box ticked
- **THEN** the node's TPDO 1 has transmission 255, the message names TPDO 1, and Problems shows no "needs SYNC" error

#### Scenario: Same EDS with SYNC on
- **WHEN** the network's SYNC source is Timer and the user adds the same node
- **THEN** TPDO 1 has no `transmission` field and keeps the EDS type 1

### Requirement: Simulation on a J1939 network
On a J1939 network the **Simulation** tool tab SHALL stay in the tool tabs and SHALL show, in place of the simulated devices, one line saying that the runtime does not simulate J1939 networks and that `canworks-j1939-sim` plays the other ECUs from the network's DBC file, naming its doc and with a command line for the network's DBC to copy. The **Simulated device** node tab and the **Simulation file** page SHALL stay hidden there.

#### Scenario: J1939 project
- **WHEN** the user opens Simulation on a J1939 network whose DBC is `machine.dbc`
- **THEN** the view says the runtime does not simulate J1939 and offers `canworks-j1939-sim --dbc machine.dbc --node NAME --interface IF` to copy, and names the J1939 simulator doc

### Requirement: OpenPLC editor files on save
Saving a Modbus bridge config with an OpenPLC connection inside an editor project with no errors SHALL also write the editor files of `canopen-editor-project` (the remote device file, the `canworks_in` and `canworks_out` programs, the `canworks` variable list and the task instances) and SHALL touch no other editor file or POU, except that it SHALL enable the `canworks` library in the project when it is not enabled, and install the library into OpenPLC Editor when it is missing there or older, as New editor project does. A save with errors SHALL write none of them. When the remote device file or one of the two programs changed on disk since canworks last wrote it, Save SHALL ask before writing anything, naming those files; Cancel SHALL save nothing. After writing them the message SHALL say that an OpenPLC Editor with this project open must reopen it before Build. A standalone config folder with an OpenPLC connection SHALL write no editor files and SHALL say so on its Project page.

#### Scenario: Save writes the device
- **WHEN** the user adds a TPDO entry in a project with an OpenPLC connection and saves
- **THEN** `devices/remote/canworks.json` gains a read group for it, `canworks_in` reads it into a new `canworks` variable, and the user's `main` is unchanged

#### Scenario: Program edited in the editor
- **WHEN** the user changed `pous/programs/canworks_in.st` in OpenPLC Editor and then saves in the configurator
- **THEN** Save asks whether to write the files again, naming that file, and Cancel leaves the config and the editor files as they were

#### Scenario: Library enabled on save
- **WHEN** a switched plugin project without the `canworks` library is saved
- **THEN** the project lists the library as enabled and `canworks_in` builds without adding it by hand

### Requirement: OpenPLC project page
A bridge config's OpenPLC connection SHALL have **Settings** on its row, opening the poll period (`poll_ms`, placeholder 10), the remote device name and the first editor location, with facts from the saved config: the remote device and port, the poll with requests per poll and the warning above 40, the writer-loss time, the map hash and the first editor `%IW`/`%QW`.

#### Scenario: Requests per poll
- **WHEN** a config with an OpenPLC connection has 30 nodes with two TPDOs and two RPDOs each, none contiguous
- **THEN** the OpenPLC connection's settings show the request count above 40 with the warning, and Problems lists it

### Requirement: Master settings on the Bus page
The configurator SHALL edit the master's node ID, SYNC period, master heartbeat period, EDS lint setting and boot SDO timeout. The SYNC period field SHALL be optional: left empty it SHALL show "off" as its placeholder and SHALL save no `sync_period_us`, and its hint SHALL say that synchronous PDOs then need an event-driven transmission type. New configs SHALL still start with a SYNC period of 10 ms. The boot SDO timeout field SHALL show 1000 as its placeholder and SHALL save nothing when left empty. The EDS lint setting SHALL offer "communication objects" (`"communication"`, the default, saved as no field), "every object" (`"all"`) and "off" (`"off"`). A loaded config with `strict_eds` SHALL be shown as the matching setting and saved as `eds_lint`, with the page saying so.

#### Scenario: Change the SYNC period
- **WHEN** the user sets the SYNC period to 10 ms and saves
- **THEN** `master.sync_period_us` is 10000 and every other value is unchanged

#### Scenario: SYNC period left empty
- **WHEN** the user clears the SYNC period field and saves
- **THEN** the saved `master` object has no `sync_period_us`

#### Scenario: Check without SYNC
- **WHEN** the SYNC period is empty, a node's TPDO 1 has no transmission type and its EDS default is 1, and the user presses Check
- **THEN** the check reports the same error the bridge would log, naming the node and TPDO 1

#### Scenario: Raise the boot SDO timeout
- **WHEN** the user enters 3000 in the boot SDO timeout field and saves
- **THEN** `master.sdo_timeout_ms` is 3000

#### Scenario: Boot SDO timeout left empty
- **WHEN** the user leaves the boot SDO timeout field empty and saves
- **THEN** the saved `master` object has no `sdo_timeout_ms`

#### Scenario: Old strict_eds false
- **WHEN** a loaded config has `"strict_eds": false` and the user saves
- **THEN** the saved `master` has `"eds_lint": "off"` and no `strict_eds`

#### Scenario: Lint rerun on check
- **WHEN** the user changes the EDS lint setting from "off" to "every object" for a config whose node EDS has findings in 0x6061, and presses Check
- **THEN** the check reports the same lint error the bridge would log for that node

### Requirement: Startup SDO picker shows the bridge's settings
The startup SDO picker SHALL by default list only writable objects that are not PDO-mappable, are not communication objects the bridge writes itself (0x1005-0x1007, 0x100C, 0x100D, 0x1014-0x1017, 0x1400-0x1BFF, 0x1F80), and are not already in the node's list. It SHALL say how many objects are hidden, and a "Show all writable objects" switch SHALL list every writable object. Saving SHALL accept any writable object except the store and restore commands 0x1010 and 0x1011, which SHALL NOT be listed even with the switch on and SHALL be refused when typed, with a reason pointing to Store on device and Restore defaults in Commission. A startup SDO that writes a PDO parameter, or a supervision object with a value other than the node's setting, SHALL get a warning.

#### Scenario: Valve with non-mappable settings
- **WHEN** the picker opens for a node whose EDS has PDO-mappable outputs 0x2010 sub 1-4 and a non-mappable setting 0x2020 sub 1-4
- **THEN** 0x2020 sub 1-4 are listed, 0x2010 is not, and the hidden count includes the four outputs

#### Scenario: Show all
- **WHEN** the user turns on "Show all writable objects"
- **THEN** 0x2010 sub 1-4 and the writable communication objects are listed too, and adding one works as today

#### Scenario: Startup SDO overlaps a bridge setting
- **WHEN** a node's startup SDO list writes 200 to 0x1017 sub 0 and the node also sets `heartbeat_ms` to 100
- **THEN** the configurator and the deploy tool warn that the startup SDO runs last and overrides the heartbeat setting, and the save still succeeds

#### Scenario: Store command refused
- **WHEN** the user turns on "Show all writable objects" on a node whose EDS has 0x1010 and 0x1011
- **THEN** neither is listed, and typing 0x1010 sub 1 by hand is refused with the reason

### Requirement: Online view of the bridge
With online access set up and a runtime connected, the Commission workspace of a config SHALL show the runtime's state through the encrypted channel, refreshed about twice a second: the bus state and counters and the master state in the connection bar, and each node in the Nodes table and its Status tab, using the node names from the config. For each node it SHALL show its state, status bit, boot result with error text, retry and hold state, last EMCY with class, SDO variable values and status, and a mark on each monitored TPDO that is timed out with its timeout count. When the runtime's config fingerprint differs from the saved `canworks.json`, the workspace SHALL say that the runtime runs a different configuration and how to upload the saved config (the deploy tool command). Connection failures SHALL be shown in the connection bar with the reason (host unreachable, port closed, wrong token, runtime could not prove the token, bridge too old for encryption, no CANopen session) and retried. While retrying after a connection that was working, the last values SHALL stay visible but greyed, with the age of the last data shown and updated.

#### Scenario: Watch a node come back
- **WHEN** the Nodes table is open and node 23's cable is plugged back in
- **THEN** within about a second node 23's state goes from 0 to 127 to 5 and its boot result shows success

#### Scenario: Different config on the runtime
- **WHEN** the user saved a change but has not uploaded it yet
- **THEN** the Commission workspace shows that the runtime runs a different configuration

#### Scenario: Timed-out PDO
- **WHEN** node 23 is OPERATIONAL and its monitored TPDO 1 has timed out
- **THEN** node 23's row keeps its Operational state and shows "TPDO 1 timed out" with the count

#### Scenario: Bridge too old
- **WHEN** the bridge does not complete a TLS handshake
- **THEN** the connection bar says the bridge is too old for encrypted diagnostics and must be updated, and no unencrypted connection is offered

#### Scenario: Connection drops
- **WHEN** the runtime stops answering
- **THEN** within about two seconds the Nodes table turns grey, the connection bar says it is not connected and retrying, and shows "last data 2 s ago" counting up until data arrives again

### Requirement: Trace view of the bus
The Trace tool tab SHALL work without a connection for opening, viewing and exporting trace files. Recording and the transmit list SHALL use the connection in the connection bar, runtime or adapter, in every workspace. Without a connection, the view SHALL say that recording needs a connection and point to **Connect…** in the connection bar, with no connect button of its own. On a CANopen simulator connection, the view SHALL say that recording needs a runtime or adapter connection. The trace header SHALL name the connection a recording uses (adapter and bit rate, or runtime) and the network.

The view SHALL offer (see "Trace toolbar and views"):
- start and stop, capture filters, error frames and clear;
- "Save to traces folder" (on this PC), open, and "Download" (a file in the chosen format), the two format choices labelled apart;
- the By identifier view and a scrolling decoded Chronological view;
- display filters by node, frame kind (NMT, SYNC, EMCY, heartbeat, SDO, PDO, LSS, error, other), identifier range, direction and text;
- the graph and trigger settings, and the statistics;
- the transmit list.

Times SHALL be shown relative to the trace start or as UTC clock time. When the bridge does not know the trace operations, the view SHALL say that the bridge is too old for traces.

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

#### Scenario: Old bridge
- **WHEN** the bridge answers the trace start as an unknown operation
- **THEN** the view says the bridge on the runtime is too old for traces and how to update it

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

### Requirement: Devices from the header and other pages
The header's workspace switch SHALL read **Configure | Commission | Devices** while a config is open, with Devices as described by the `device-install` capability. The start page's **Install on a device** SHALL open Devices with no config: the header SHALL show the mode "Devices · no config" and no workspace switch, Save, Export or Project menus, and **Close** SHALL return to the start page. While a project is open, its devices SHALL also be reachable from the pages that need them: Online access's **Runtime host** SHALL show the state of the device with that host (for example `canworks 0.93.4, off`) with **Open in Devices**; the Modbus bridge page SHALL show where the bridge runs and its state, with **Install on device…** when no device runs it; Commission's connect panel, when it lists no runtime, SHALL offer **Install canworks on a device…**; the status bar SHALL list a running install job with **Show**. Commission a CANopen device (no config) SHALL show no Devices workspace.

#### Scenario: Host with an old bridge
- **WHEN** Online access's runtime host is a device of the project whose last probe found bridge 0.93.4 off
- **THEN** the field shows `canworks 0.93.4, off` and **Open in Devices** opens that device's page

#### Scenario: Bridge not installed
- **WHEN** a bridge project has no device running its bridge
- **THEN** the Modbus bridge page shows **Install on device…**, which opens Devices with Add device or the project's device selected

#### Scenario: Devices from the start page
- **WHEN** the user presses Install on a device on the start page
- **THEN** Devices opens with the PC's device list, the mode reads "Devices · no config", and Close returns to the start page

### Requirement: Function blocks section
The Modbus bridge page of a bridge config SHALL have a **Function blocks** section with the switch "Mailboxes for the canworks mailbox blocks" and, while on, the number of request mailboxes (0-4), the receive mailbox on or off with its receive blocks (1 or 2), the number of cyclic jobs (0-16), network info on or off and the input and output areas with Suggest, writing `bridge.mailboxes`. Turning it on SHALL place both areas in free ranges.

Whether the switch is on or off, the section SHALL show:
- a **Works without mailboxes** list: the config's values, `CO_NMT`, `CO_NODE_LIVE`, and `CO_SDO_READ` and `CO_SDO_WRITE` up to 4 bytes;
- a **Needs mailboxes** table: each part, the blocks that need it (for example "CAN_RECEIVE, J1939_RECEIVE and CO_RECV_EMCY" for the receive mailbox) and the config-only alternative where one exists (an `rx` message for `CAN_RECEIVE`, a periodic `tx` message for `CAN_SEND_CYCLIC`, `emcy_code_location` for the latest EMCY per node, `bus_state_location` for the bus state);
- the cost as a difference against the map without mailboxes: the extra input and holding registers and, with an OpenPLC connection, the Modbus requests per poll with and without them against the budget of 40 (with the switch off: what the default parts would add);
- the expected receive rate with the receive mailbox on ("about N CAN frames/s at this poll": the CAN records per batch times the poll rate, halved);
- who needs which part: each connection's canworks blocks choice and the mailbox blocks the OpenPLC program declares.

With an OpenPLC connection, a count change SHALL move both areas to free ranges at once, and the section SHALL say that the editor project needs a Save (or `canworks-deploy --into-project`) and a new Build. A new config, adding a connection of any kind and a target change SHALL NOT turn the mailboxes on; only the switch, a connection's canworks blocks choice and **Turn on what the program uses** do.

#### Scenario: New OpenPLC config
- **WHEN** the user creates a new Modbus bridge config and adds an OpenPLC connection
- **THEN** the config has no `bridge.mailboxes`, the section is off and shows the Works without mailboxes list, the Needs mailboxes table and "+227 input / +79 holding registers, 7 instead of 5 Modbus requests per poll" for the defaults

#### Scenario: Turn on the receive mailbox
- **WHEN** the user turns on the receive mailbox of a config with an OpenPLC connection
- **THEN** the areas move to free ranges, the register and request counts grow, and the page says to save the editor project and build again

#### Scenario: Second receive block
- **WHEN** the user sets receive blocks to 2 in a config with an OpenPLC connection and a 10 ms poll
- **THEN** the areas move to free ranges, the register and request counts grow by 120 registers and one request, and the expected rate reads about 1050 CAN frames/s

#### Scenario: Who needs them
- **WHEN** the OpenPLC program declares a `CAN_RECEIVE` in `main`, or in a config without OpenPLC a truST connection "Line" has canworks blocks SDO and send
- **THEN** the section says "The OpenPLC program declares CAN_RECEIVE (main)", or "Line: canworks blocks SDO and send (1 request mailbox)"

### Requirement: ST calls for the blocks over the bridge
Every **Copy as ST call** of the configurator (an object dictionary entry, an NMT command, a CAN message, a J1939 PGN) SHALL write a call of the library's blocks over the bridge with `LINK := canworks.link`. An SDO call of an integer of up to 4 bytes SHALL use `CO_SDO_READ` or `CO_SDO_WRITE` with `DATA` converted to and from `UDINT` and the object's size; a wider integer, an OCTET_STRING or a DOMAIN SHALL use the `_BYTES` blocks, a REAL the `_REAL` blocks and a VISIBLE_STRING the `_STRING` blocks.

#### Scenario: Copy an SDO read
- **WHEN** the user copies the ST call of an INTEGER16 entry in the Online view's object dictionary
- **THEN** the copied text declares a `CO_SDO_READ`, calls it with `LINK := canworks.link` and converts the result with `UDINT_TO_INT`

### Requirement: Old located variables in an OpenPLC project's main
For an OpenPLC project (a config with an OpenPLC connection, inside an editor project) the configurator SHALL find, in `pous/programs/main.st`, the located declarations whose names are members of the `canworks` variable list. When there are any, the Project page SHALL show a warning that `main` still declares that many canworks values at their old plugin locations, which read nothing now, naming the first locations, with the button **Use canworks.\* in main**; Problems SHALL list the same as a warning that opens the Project page; and the message after **Use with canworks-bridge** SHALL mention it.

The button SHALL first copy `main.st` to `canworks/main-before-move.st`, then remove those declarations and the generated comment `(* CANopen I/O declared from canworks/canworks.json *)`, keep the `VAR` block even when it is left empty (as the editor writes an empty program), and replace each use of a removed name in the program's code with `canworks.<name>`, matching names without regard to case, and leaving comments, strings and names after a `.` unchanged. A name that `main` also declares without a location SHALL be neither removed nor replaced. The message SHALL give the number of declarations and uses moved, name any names left, say where the copy is, and say that an OpenPLC Editor with the project open must reopen it before Build. Located declarations of other names, other POUs and the config SHALL NOT change.

#### Scenario: Switched plugin project
- **WHEN** a plugin project whose `main` declares `rtd_ok : BOOL AT %IX10.0;` and uses `IF rtd_ok THEN` gets Use with canworks-bridge and is saved
- **THEN** the Project page warns that `main` declares 1 canworks value at its old plugin location `%IX10.0`, and Problems lists the warning

#### Scenario: Move
- **WHEN** the user presses **Use canworks.\* in main** on that project
- **THEN** `main.st` has no `rtd_ok` declaration, its code reads `IF canworks.rtd_ok THEN`, `canworks/main-before-move.st` holds the old text, and the warning is gone

#### Scenario: User's own I/O and comments kept
- **WHEN** `main` also declares `start_button : BOOL AT %IX0.0;` and has the comment `(* rtd_ok is the sensor *)`
- **THEN** after the move `start_button` is still declared at `%IX0.0` and the comment still reads `rtd_ok`

### Requirement: Where things are
The configurator SHALL place its parts by one rule: the Project page holds the target and whole-project actions; the header's primary button puts the config onto the target; Export ▾ holds the network files; the Modbus bridge page holds the bridge settings and the Connections, each with its program-side files; Copy as ST call stays on its item. `docs/configurator.md` SHALL state this rule.

#### Scenario: Node-RED flow
- **WHEN** a user of a Modbus bridge config looks for the Node-RED flow
- **THEN** it is the Download of a Node-RED connection on the Modbus bridge page, and Export ▾ has no Node-RED item

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

### Requirement: Editor project on the Project page
The Project page SHALL have an **Editor project** section when the config is inside an OpenPLC Editor project or has an OpenPLC connection. In project mode it SHALL name the project, its folder and the files Save writes. Standalone, it SHALL offer **Move into project…** and **New editor project…**. CODESYS configs SHALL NOT have the section.

#### Scenario: Standalone OpenPLC config
- **WHEN** a standalone config with an OpenPLC connection opens its Project page
- **THEN** the Editor project section offers Move into project… and New editor project…

#### Scenario: Modbus bridge config
- **WHEN** a standalone bridge config without an OpenPLC connection opens its Project page
- **THEN** it has no Editor project section

### Requirement: Header menus stay inside the window
A header menu's panel SHALL open fully inside the window. It SHALL be right-aligned under its button unless that would cross the window's left edge, and then left-aligned.

When the header would not fit one row, the simulation chip SHALL show only its mark and "Simulated", with the full text in its tooltip and in Details.

#### Scenario: Export with the simulation chip
- **WHEN** an OpenPLC config with simulated nodes is open at 1440 px and the user opens Export ▾
- **THEN** the header is one row and the whole Export panel is inside the window

#### Scenario: Narrow window
- **WHEN** the window is 1280 px wide with a simulated network and the user opens Export ▾
- **THEN** the chip reads "Simulated", and the Export panel is inside the window

### Requirement: Copy as ST call only where the blocks run
Copy as ST call (object dictionary entry, NMT command, CAN message, J1939 PGN) SHALL be offered only on Modbus bridge configs, not on a CODESYS config and not when commissioning a device without a config.

#### Scenario: CODESYS config
- **WHEN** the user opens a node's object dictionary in Commission on a CODESYS config
- **THEN** no entry offers ST, and NMT offers no Copy as ST call

### Requirement: Copy as ST call names the missing part
When the config lacks the bridge part a copied block needs, the button SHALL stay enabled, and its tooltip and the copied text's first comment SHALL name the setting and its page: SDO bridge registers for `CO_SDO_READ`/`CO_SDO_WRITE`, the control block for `CO_NMT`, a request mailbox for the other SDO, send and request blocks, the receive mailbox for the receive blocks.

#### Scenario: Receive mailbox off
- **WHEN** a Modbus bridge config has the Function blocks section on without the receive mailbox, and the user copies the ST call of a received J1939 PGN
- **THEN** the copied text starts with a comment saying it needs the Function blocks' receive mailbox on the Modbus bridge page

### Requirement: Out-of-date OpenPLC editor files
For an OpenPLC project (a config with an OpenPLC connection, inside an editor project) the configurator SHALL compare the editor files Save writes for the saved config (the remote device file and the `canworks_in` and `canworks_out` programs) with the files on disk. A file SHALL count as out of date when canworks wrote it last and it is missing now or Save would now write a different text; in a project canworks never wrote into, nothing SHALL count. `project.json` SHALL count as out of date when its `canworks` variable list has other member names or types than Save writes, or when it does not enable the `canworks` library; the library entry's version SHALL NOT count, since Save installs the configurator's own library into the editor. A file changed since canworks wrote it SHALL NOT count as out of date; Save keeps asking before writing it. When anything is out of date, the Project page SHALL list it under the editor files, Problems SHALL list one warning that opens the Project page, and Save SHALL be enabled with the title "The editor files are from an older canworks; Save writes them again". Saving then SHALL write the editor files as a normal save does and SHALL leave `canworks.json` unchanged.

#### Scenario: Tools update changes canworks_in
- **WHEN** a project saved with an older canworks is opened in a configurator whose `canworks_in` code differs, and the user has made no change
- **THEN** the Project page lists `pous/programs/canworks_in.st` as out of date, Save is enabled, and pressing it rewrites `canworks_in.st` without changing `canworks.json`

#### Scenario: Nothing new
- **WHEN** the editor files on disk are what Save would write and the project enables the library
- **THEN** nothing is listed and Save reads "Saved"

#### Scenario: Edited in the editor
- **WHEN** the user changed `canworks_in.st` in OpenPLC Editor and the config is unchanged
- **THEN** the file is not listed as out of date and Save stays disabled; a later save asks before writing it, as today

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

### Requirement: Plugin configs
A config with neither `bridge` nor `codesys` (the removed plugin's) SHALL open read-only with one message and **Use with canworks-bridge**. As one undo step it SHALL repack for the bridge, add `bridge`, add an OpenPLC connection when the folder is inside an OpenPLC Editor project, and remove `axis`, `sync_source`, `sync_cycles` and `scan_watchdog_ms`. Until then the page SHALL NOT save.

#### Scenario: Plugin project
- **WHEN** the user opens a plugin config inside an editor project, whose master has `"sync_source": "plc_cycle"`, and presses Use with canworks-bridge
- **THEN** the config has `bridge` with an OpenPLC connection, `plc_link` true and no `sync_source`, and one Undo restores the config as opened

### Requirement: Safe settings for new nodes and adapters
When the user adds a node, the configurator SHALL save it with `"config_check": true` when its EDS defines 0x1020 sub 1 and sub 2 as writable. When a node gets its first output entry (an RPDO entry with a location) and its EDS has a writable 0x1016, the configurator SHALL set `"heartbeat_consumer": true` in the same undo step, and when the master sends no heartbeat it SHALL also set `master.heartbeat_ms` to 100. When the user adds a `socketcan` adapter with `configure_link` on, the configurator SHALL save `"restart_ms": 100`. Each value SHALL show in its usual field and the user SHALL be able to turn it off; the configurator SHALL NOT set them again on a node or adapter where the user turned them off. Nodes and adapters loaded from a file SHALL NOT be changed. No value SHALL write a node's non-volatile memory (`store_configuration` stays off).

#### Scenario: New output node
- **WHEN** the user adds node 23 whose EDS has writable 0x1016 and 0x1020, and maps an RPDO entry to a location, on a master with `heartbeat_ms` 0
- **THEN** the saved node has `"config_check": true` and `"heartbeat_consumer": true`, the master has `"heartbeat_ms": 100`, and one undo removes the heartbeat settings and the mapping together

#### Scenario: New CAN interface
- **WHEN** the user adds a network with a SocketCAN adapter `can0`
- **THEN** the saved adapter has `"restart_ms": 100`

#### Scenario: User turns it off
- **WHEN** the user clears "Watches the master heartbeat" on node 23 and then maps another RPDO entry
- **THEN** `heartbeat_consumer` stays off

### Requirement: Problems for bridge stop and bus-off
Problems SHALL show, as warnings that do not block saving or the hand-off steps:
- every node that canopen-node-supervision "Nodes not protected against a bridge stop" names, with the message that it keeps its last outputs when the bridge crashes or loses power and a **Watch the master heartbeat** button, offered when the EDS has a writable 0x1016, that sets `heartbeat_consumer` true (and `master.heartbeat_ms` 100 when it is 0) in one undo step;
- every `socketcan` adapter with `configure_link` on and no `restart_ms` (not a simulated bus or a `vcan` interface, which have no bus-off), with the message that a bus-off then lasts until the interface is restarted and a **Restart after bus-off (100 ms)** button.

#### Scenario: Fix from Problems
- **WHEN** a loaded config has node 23 with RPDO entries and no protection, and the user presses Watch the master heartbeat
- **THEN** node 23 has `"heartbeat_consumer": true`, the warning is gone, and one undo brings both back

#### Scenario: Bus-off restart fix
- **WHEN** a loaded config has adapter `can0` without `restart_ms` and the user presses Restart after bus-off (100 ms)
- **THEN** the adapter has `"restart_ms": 100` and the warning is gone

### Requirement: Mailbox blocks the OpenPLC program declares
For a config with an OpenPLC connection, Check and Save SHALL scan the editor project's Structured Text POUs and global variable lists for instances of mailbox blocks, ignoring comments and strings and leaving out the generated `canworks_in` and `canworks_out`. For each mailbox part that a declared block needs and the config lacks, Problems SHALL show an error naming the POU, the block and the part, with **Turn on what the program uses**.

#### Scenario: Program receives frames
- **WHEN** `main` declares `rx : CAN_RECEIVE;` and the config has no mailboxes
- **THEN** Problems shows an error "main declares CAN_RECEIVE, which needs the request and receive mailboxes" with Turn on what the program uses

#### Scenario: Commented out
- **WHEN** `main` has `(* rx : CAN_RECEIVE; *)` and no other mailbox block
- **THEN** no mailbox error is shown

### Requirement: Turn on what the program uses
**Turn on what the program uses** SHALL, in one undo step, turn on exactly the parts the declared blocks need and place both areas in free ranges. The parts are: one request mailbox; the receive mailbox for a receiving block; one cyclic job per declared `CAN_SEND_CYCLIC` instance (at least 4, at most 16); and network info for an info block.

#### Scenario: Only what is needed
- **WHEN** the program declares one `CAN_RECEIVE` and one `CO_SDO_READ_STRING`, and the user presses Turn on what the program uses
- **THEN** the config gets one request mailbox and the receive mailbox, without cyclic jobs or network info, and one Undo removes them again

### Requirement: Mailboxes nobody needs
When the config has mailboxes and connections, and neither the OpenPLC program nor any connection's canworks blocks choice needs them, Problems SHALL show a warning with what the mailboxes take (the Modbus requests per poll with an OpenPLC connection, otherwise their registers), and **Turn off the mailboxes**, which removes `bridge.mailboxes` in one undo step. A config without connections (a client run by hand) SHALL get no such warning.

#### Scenario: Mailboxes nobody uses
- **WHEN** the config has the default mailboxes, the program declares no mailbox block and no connection has a canworks blocks choice other than None
- **THEN** Problems shows a warning saying the mailboxes take 2 of the 7 Modbus requests per poll, and Turn off the mailboxes removes `bridge.mailboxes` in one undo step

### Requirement: Import from CODESYS
The start page and a CODESYS config's CODESYS page SHALL offer **Import from CODESYS…**. Its file dialog SHALL list CODESYS `.project` files only when CODESYS is found on this PC (otherwise it says to export PLCopenXML in CODESYS and lists `.xml` files only) and PLCopenXML `.xml` files; then it SHALL show the device list when the file has several devices with a CANopen Manager, then the import preview. Nothing SHALL be written before Create config or Add to this config.

#### Scenario: No CODESYS on this PC
- **WHEN** the user opens Import from CODESYS… on a Mac
- **THEN** the dialog says to export PLCopenXML in CODESYS and pick that file, and lists no `.project` files

### Requirement: Import preview
The preview SHALL show each network and node, each node's EDS state (in this config / from the library / from CODESYS on this PC / added / missing) and the not-carried list. **Add EDS…** on a node SHALL give every node of that CODESYS device type the EDS. Create config and Add to this config SHALL stay disabled while a node has no EDS.

#### Scenario: Missing EDS
- **WHEN** no EDS matches node `rtd`
- **THEN** its row says EDS missing with Add EDS…, and Create config is disabled until an EDS is added

#### Scenario: Cancel
- **WHEN** the user closes the preview
- **THEN** no file is written

### Requirement: Create config from an import
**Create config…** SHALL ask for a name and location and write a new CODESYS config with its EDS files, `codesys.project` set to the imported project (when it came from one) and `codesys.device` to the chosen device.

#### Scenario: Import a project
- **WHEN** the user imports `C:\Projects\line2.project`, picks `PLC` and presses Create config
- **THEN** a new CODESYS config opens with the project's networks and nodes, its CODESYS page names `line2.project` and device `PLC`, and Build into CODESYS project reports every device up to date

### Requirement: Add an import to this config
With a CODESYS config open, **Add to this config** SHALL add the imported networks to the draft, which Save writes. An imported network whose name or CODESYS network number the config uses already SHALL ask **Add it as a new network** (a new name and, when needed, a free network number) or **Replace** the config's network.

#### Scenario: Same network twice
- **WHEN** the user adds an import whose network `io` the config already has, and answers Add it as a new network
- **THEN** the draft has `io` and `io2` on different network numbers

### Requirement: Build asks before removing nodes
When a build would remove project nodes that canworks managed earlier (`codesys.managed`) and that are no longer in the config, Build SHALL list them by network and node ID and ask **Remove N nodes** or **Keep them**; Keep SHALL build without removing them. After a build each CANopen master network's `codesys.managed` SHALL be its node IDs, so kept nodes leave the list and the next build does not ask again.

#### Scenario: Node deleted in canworks
- **WHEN** node `new_io` (node 7) was deleted in the configurator and the user presses Build
- **THEN** the dialog names node 7 and asks before building

#### Scenario: Keep them
- **WHEN** the user answers Keep them
- **THEN** node 7 stays in the project and the saved config's `managed` list no longer has 7

### Requirement: Mailbox detection in programs
The scan for mailbox blocks SHALL count arrays of a block with any bounds and dimensions, namespaced block types, blocks inside user function blocks once per instance, and blocks in every POU file of the editor project. When a count cannot be worked out, Turn on what the program uses SHALL give the most for that part and Problems SHALL NOT offer to turn the mailboxes off.

#### Scenario: Arrays and function blocks
- **WHEN** main declares `rx : ARRAY[1..N] OF CAN_RECEIVE` with constant N 3, `cy : ARRAY[0..1, 0..1] OF CAN_SEND_CYCLIC` and `a : ARRAY[0..7] OF Axis` where Axis holds one `canworks.CAN_SEND_CYCLIC`
- **THEN** the scan finds the receive mailbox needed and 12 cyclic jobs

#### Scenario: Unknown size
- **WHEN** an array bound is an expression the scan cannot work out
- **THEN** Turn on what the program uses sets the maximum for that part and no Turn off fix is offered

### Requirement: New editor project needs openplc-cli
The Project page's **New editor project…** SHALL be disabled with the reason when openplc-cli is not found, as in the Add connection dialog.

#### Scenario: No openplc-cli
- **WHEN** the configurator runs without openplc-cli and the user opens the Project page of an OpenPLC config
- **THEN** New editor project is disabled and its title names openplc-cli

### Requirement: Restarted configurator
A tab whose requests are refused because the configurator was restarted with a new session SHALL stop polling and say that the configurator was restarted, with a link to open it again.

#### Scenario: Old tab
- **WHEN** canworks-config is stopped and started again while a tab is open
- **THEN** the old tab shows the restarted notice within 2 s and sends no more requests

### Requirement: Project name in the header
When the header is short of room, the project chip SHALL shorten the target part before the project name.

#### Scenario: Update chip shown
- **WHEN** the update chip is shown at 1280 px with project virtual-plant
- **THEN** the project chip still shows "virtual-plant"
