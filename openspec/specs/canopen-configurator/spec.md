# canopen-configurator Specification

## Purpose
A local GUI on the engineering PC that creates and edits the CANopen config of an OpenPLC Editor project (its `canworks/` folder), so CANopen nodes can be added and mapped to PLC addresses without hand-writing JSON or changing the editor.

## Requirements

### Requirement: Choose what to edit
Started without arguments, the configurator SHALL open a start page with one line saying what the tool is for (configuring CANopen and J1939 networks for OpenPLC Runtime v4, and commissioning CANopen devices from the PC) and four choices: open an OpenPLC Editor project, open a standalone config folder, create a new standalone config, or commission a CANopen device. Each choice SHALL say in one or two short sentences what it opens and how it relates to OpenPLC: the project choice edits the `canworks/` folder of an OpenPLC Editor project and checks addresses against its program; a standalone config is used before an OpenPLC Editor project exists and can be moved into one later; commissioning needs no OpenPLC runtime. The choices SHALL sit in a grid with no lone card on a row of its own at desktop widths. The page SHALL let the user browse local folders and SHALL list recently opened ones. A path given on the command line SHALL open directly, as a project when the folder has `project.json` and as a standalone config otherwise. The current mode SHALL always be visible.

#### Scenario: Start page
- **WHEN** `canworks-config` runs without arguments in a 1280 px wide window
- **THEN** the browser shows the purpose line, the four choices in two rows of two, and the recent folders, and the project choice is titled "Open OpenPLC Editor project"

#### Scenario: Open a project from the start page
- **WHEN** the user chooses "Open OpenPLC Editor project" and picks `~/Documents/workspace/rtd-monitor`, which has `canworks/canworks.json`
- **THEN** the page shows that config with the mode "project rtd-monitor"

#### Scenario: Project without a config
- **WHEN** the user opens an OpenPLC Editor project that has no `canworks/` folder
- **THEN** the page shows an empty config and the project folder is unchanged until the user saves

#### Scenario: Not an editor project
- **WHEN** the user picks a folder without `project.json` under "Open OpenPLC Editor project"
- **THEN** the page says it is not an OpenPLC Editor project and offers to open it as a standalone config instead

### Requirement: Standalone config before a project exists
In standalone mode the configurator SHALL edit `canworks.json` and its EDS files in a plain folder, creating the folder on first save, with every check except the editor-project address checks, which the page SHALL show as skipped. The page SHALL offer "move into project", which runs the deploy tool's `--into-project` checks, copies the config into the picked project's `canworks/` folder and switches to project mode. The deploy tool's `--config` SHALL accept the folder unchanged.

#### Scenario: Configure first, project later
- **WHEN** the user creates a new standalone config in `~/canworks/rtd`, adds the RTD node and saves, then later chooses "move into project" and picks `~/Documents/workspace/rtd-monitor`
- **THEN** the project gets `canworks/canworks.json` and the EDS, the page switches to project mode and runs the address checks against the project

#### Scenario: Project already has a config
- **WHEN** the picked project already has a `canworks/` folder
- **THEN** nothing is copied until the user confirms replacing it

### Requirement: Local access only
The configurator SHALL listen only on the loopback interface and SHALL reject any request that does not carry the random session token it generated at start. The page SHALL load no resource from the network. The configurator's own outgoing connections SHALL go only to the runtime host and port the user entered for online access, and only while the user has the online view or scan open.

#### Scenario: Request from another host
- **WHEN** another machine on the LAN connects to the configurator's port
- **THEN** the connection is refused because nothing listens on a non-loopback address

#### Scenario: Request without the token
- **WHEN** a local process sends a save request without the session token
- **THEN** the request is rejected and nothing is written

#### Scenario: Offline editing makes no connection
- **WHEN** the user edits and saves a config without opening the online view or scan
- **THEN** the configurator opens no network connection

### Requirement: Import an EDS
Adding a node SHALL start from an EDS file the user picks. The configurator SHALL check that it is a CiA 306 EDS the deploy tool accepts, store it under `canworks/` as UTF-8 (converting from Latin-1/CP1252 when it is not valid UTF-8) and refer to it by a path relative to `canworks/`. A different file with the same name SHALL NOT be overwritten silently. When "keep both" gives the new EDS another name, it SHALL get its own notes file (see `canopen-device-notes`), and replacing an EDS SHALL keep its notes file.

At import, the configurator SHALL also run the checks the PLC runs before dcfgen, on the same prepared copy (see `canopen-master-bringup`, "Prepared EDS copy"): dcfgen's EDS read and lint, and Lely's EDS parse rules, sorting the lint findings as the plugin does (see `canopen-master-bringup`, "EDS lint scope") under the config's `eds_lint` setting. The import SHALL show:
- that the file is readable, when nothing below applies;
- the corrections the PLC will make (UTF-8 conversion, REAL rewrite, cleared OCTET_STRING values);
- findings that do not stop the PLC, as a collapsed list with each finding's object, saying they are accepted.

The import SHALL be refused, showing the reason, and no node SHALL be added, when dcfgen or Lely cannot read the file even after the corrections, or when the lint has findings that would stop the PLC.

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

### Requirement: SocketCAN adapter settings
The configurator SHALL edit the `socketcan` adapter: interface name, bit rate chosen from the CiA 301 rates the contract allows, whether the plugin configures the link (`configure_link`, default on) and the bus-off restart delay (`restart_ms`). A config using the pre-contract top-level `interface`/`bitrate` keys SHALL be shown as that adapter and saved in the `adapter` form, with the page saying so.

#### Scenario: Set up can0 at 250 kbit/s
- **WHEN** the user sets interface `can0`, bit rate 250000, leaves "configure link" on, sets restart 100 ms and saves
- **THEN** `canworks.json` has `adapter` `{"type": "socketcan", "interface": "can0", "bitrate": 250000, "configure_link": true, "restart_ms": 100}`

#### Scenario: Bit rate outside CiA 301
- **WHEN** a loaded config has `bitrate: 300000`
- **THEN** the bit rate field shows the contract error and the save is refused until a listed rate is chosen

#### Scenario: Old-style config
- **WHEN** a loaded config has top-level `interface: "vcan0"` and `bitrate: 125000`
- **THEN** the page shows a SocketCAN adapter on `vcan0` at 125000 with "configure link" off, says the file uses the old keys, and saving writes them as `adapter` with `configure_link: false`

### Requirement: Master settings
The configurator SHALL edit the master's node ID, SYNC source, SYNC period, PLC cycles per SYNC, master heartbeat period, EDS lint setting and boot SDO timeout. The SYNC period field SHALL be optional: left empty it SHALL show "off" as its placeholder and SHALL save no `sync_period_us`, and its hint SHALL say that synchronous PDOs then need an event-driven transmission type. New configs SHALL still start with a SYNC period of 10 ms. The SYNC source SHALL offer "timer" (saved as no field) and "PLC cycle" (`"plc_cycle"`); with "PLC cycle" the SYNC period field SHALL be hidden and not saved, and an "every N PLC cycles" field SHALL show 1 as its placeholder, save nothing when empty and save `sync_cycles` otherwise. The boot SDO timeout field SHALL show 1000 as its placeholder and SHALL save nothing when left empty. The EDS lint setting SHALL offer "communication objects" (`"communication"`, the default, saved as no field), "every object" (`"all"`) and "off" (`"off"`). A loaded config with `strict_eds` SHALL be shown as the matching setting and saved as `eds_lint`, with the page saying so.

#### Scenario: Change the SYNC period
- **WHEN** the user sets the SYNC period to 10 ms and saves
- **THEN** `master.sync_period_us` is 10000 and every other value is unchanged

#### Scenario: SYNC period left empty
- **WHEN** the user clears the SYNC period field and saves
- **THEN** the saved `master` object has no `sync_period_us`

#### Scenario: Check without SYNC
- **WHEN** the SYNC period is empty, a node's TPDO 1 has no transmission type and its EDS default is 1, and the user presses Check
- **THEN** the check reports the same error the plugin would log, naming the node and TPDO 1

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
- **THEN** the check reports the same lint error the plugin would log for that node

#### Scenario: Switch to PLC-cycle SYNC
- **WHEN** a config has `"sync_period_us": 10000`, the user picks "PLC cycle", enters 2 in "every N PLC cycles" and saves
- **THEN** the saved `master` object has `"sync_source": "plc_cycle"` and `"sync_cycles": 2` and no `sync_period_us`, and the Check accepts a node TPDO with EDS default type 1

#### Scenario: Back to the timer
- **WHEN** the user switches a PLC-cycle config back to "timer", enters 10 ms and saves
- **THEN** the saved `master` object has `"sync_period_us": 10000` and neither `sync_source` nor `sync_cycles`

### Requirement: Node supervision settings
For each node the configurator SHALL edit node ID, name, heartbeat period and timeout, or node guarding time and life time factor, and the status bit location. A new node's status bit SHALL get a suggested free `%IX` location.

#### Scenario: Heartbeat for a new node
- **WHEN** the user adds a node from an EDS, sets heartbeat 100 ms and timeout 300 ms and saves
- **THEN** the node has `heartbeat_ms` 100, `heartbeat_timeout_ms` 300 and a `status_location` that is free in the project

### Requirement: PDO communication parameters
For each PDO the configurator SHALL edit the PDO number, COB-ID, transmission type and event timer, leaving each unset to use the default unless the user sets it. For a TPDO it SHALL also edit the receive timeout: an empty field (no `timeout_ms`, shown as "off"), a number of milliseconds, or Auto, which SHALL show the resolved value next to it (two times the event timer from the config or the EDS) and SHALL be offered only when that event timer is not 0. When a timeout is set the configurator SHALL show the "on timeout" choice (hold, the default and saved as no field, or zero) and a timeout bit address field (`%IX`, optional, included in the address suggestion and clash checks). The Check SHALL give the same messages as the plugin for these fields, and SHALL warn when a numeric timeout is shorter than the PDO's effective event timer.

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
Every setting the plugin defaults when it is left out SHALL show that default on the page (in the empty field and in a short hint), computed where it depends on other values: the CiA 301 COB-ID of PDOs 1 to 4 from the node ID and PDO number, and the heartbeat timeout as 3 × the heartbeat period. Settings with a fixed set of values SHALL be dropdowns that explain each choice: adapter type, bit rate, supervision method (none, heartbeat, node guarding, showing only the chosen method's fields), PDO transmission type and startup SDO data type.

#### Scenario: Defaults shown
- **WHEN** node 5 has TPDO 1 with no `cob_id` and no `transmission`, and a heartbeat of 100 ms with no timeout
- **THEN** the COB-ID field shows `0x185`, the transmission dropdown shows "1: every SYNC (default)", and the timeout field shows `300`, and none of these values is written to `canworks.json`

#### Scenario: Supervision method
- **WHEN** the user picks node guarding for a node that has a heartbeat set
- **THEN** the heartbeat fields are removed from the node and only guard time and life time factor are shown

### Requirement: Startup SDO writes
For each node the configurator SHALL edit an ordered list of startup SDO writes, which the plugin performs every time the node is configured at boot. The user SHALL pick the object from the node's EDS or type an index and subindex, and the type SHALL come from the EDS. Objects the EDS does not define, or marks read-only or const, SHALL be refused, and each value SHALL be checked against its type's range. The picker and the list SHALL show each object's note `text` under its name; the value field SHALL show the value's meaning and unit from the merged note, and SHALL offer the note's `values` as a list with "Other value…" when it has them.

#### Scenario: Set the RTD sensor type
- **WHEN** the user adds a write to 0x6110 subindex 1 (`AI0_Sensor_Type`, `rw`, UNSIGNED16, EDS default 0x1E), enters `0x1E`, and moves it to the top of the list
- **THEN** the saved node's `sdo` list starts with `{"index": "0x6110", "subindex": 1, "type": "UNSIGNED16", "value": "0x1E"}`, and the plugin writes it before the other startup SDOs

#### Scenario: Read-only object
- **WHEN** the user picks object 0x1018 subindex 1 (const)
- **THEN** the write is refused with the reason

#### Scenario: Value out of range
- **WHEN** the user enters 300 for an UNSIGNED8 object
- **THEN** the field shows the range error and the save is refused

#### Scenario: Object not in the EDS
- **WHEN** the user types index 0x2100 subindex 0 that the EDS does not list
- **THEN** the write is refused, because the plugin only writes startup SDOs to objects the node's EDS defines

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
- **THEN** the entry shows an error naming the EtherCAT device file and the save is refused

#### Scenario: Matching located variable
- **WHEN** the project declares `rtd1 AT %IW100 : INT` and a CANopen INTEGER16 entry uses `%IW100`
- **THEN** no clash is reported and the entry shows that it is declared as `rtd1`

#### Scenario: Editor-style declaration
- **WHEN** the project's `main.st` declares `rtd1 : INT AT %IW100;` (as the editor writes it after an edit in its variable table) and a CANopen INTEGER16 entry uses `%IW100`
- **THEN** the entry shows that it is declared as `rtd1`, not as `INT`

### Requirement: Validate before save
Before saving, the configurator SHALL run the deploy tool's checks: contract schema, EDS type and access checks, node ID uniqueness, overlapping locations and SDO value ranges. It SHALL show every error next to the field it concerns and SHALL refuse to save a config with errors. An overlap with the editor project MAY be saved only when the user explicitly allows it, as the deploy tool's `--allow-clash` does. The control that allows it SHALL be shown in the Problems pane together with the editor-project overlap errors, and only while there are such errors; it SHALL NOT be shown in the page header or in standalone mode. While it is ticked, the Save button SHALL say that overlaps are allowed.

#### Scenario: Duplicate node ID
- **WHEN** two nodes have node ID 5
- **THEN** both node ID fields show the error, the save button reports the error count, and the file on disk is unchanged

#### Scenario: No overlap, no override
- **WHEN** a project config has no location that overlaps the editor project
- **THEN** neither the header nor the Problems pane shows an "Allow overlap" control

#### Scenario: Save despite an overlap
- **WHEN** node 2's TPDO entry uses `%ID100`, which the editor project's EtherCAT config also uses, and the user ticks "Allow overlap" under that error in the Problems pane
- **THEN** the Save button reads "Save (overlaps allowed)" and saving writes the config

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

### Requirement: Located variable declarations
The configurator SHALL list, for every mapped entry and node status bit, a variable name, its location and the matching IEC type, and SHALL offer them as an ST `VAR ... END_VAR` block ready to copy into the editor's global variables or a program's variables. Entries already declared in the project SHALL be marked and left out of the block.

#### Scenario: Copy declarations
- **WHEN** the RTD node maps four INTEGER16 inputs at `%IW100` to `%IW103` and has status bit `%IX10.0`, none declared yet
- **THEN** the block declares four `INT` variables at `%IW100` to `%IW103` and one `BOOL` at `%IX10.0`

### Requirement: PDO timing from the EDS
For each PDO the configurator SHALL show the communication fields that the node's EDS defines for that PDO kind (TPDO: inhibit time, event timer, SYNC start; RPDO: event timer), with the EDS default as the empty field's placeholder and times in milliseconds. A field the EDS marks read-only SHALL show its value and not be editable. A field the EDS does not define SHALL not be shown. The COB-ID field SHALL offer "auto" and show the COB-ID it resolves to.

#### Scenario: TPDO with an inhibit time
- **WHEN** the user enters 10 ms as the inhibit time of a TPDO whose EDS defines 0x1800 sub 3 `rw` with default 0
- **THEN** the saved PDO has `"inhibit_time_us": 10000`

#### Scenario: Read-only RPDO transmission type
- **WHEN** a node's EDS marks 0x1400 sub 2 `ro` with default 255
- **THEN** the RPDO's transmission type shows "255 (fixed by the EDS)" and cannot be changed

### Requirement: Startup SDO picker shows settings
The startup SDO picker SHALL by default list only writable objects that are not PDO-mappable, are not communication objects the plugin writes itself (0x1005-0x1007, 0x100C, 0x100D, 0x1014-0x1017, 0x1400-0x1BFF, 0x1F80), and are not already in the node's list. It SHALL say how many objects are hidden, and a "Show all writable objects" switch SHALL list every writable object. Saving SHALL accept any writable object, as before. A startup SDO that writes a PDO parameter, or a supervision object with a value other than the node's setting, SHALL get a warning.

#### Scenario: Valve with non-mappable settings
- **WHEN** the picker opens for a node whose EDS has PDO-mappable outputs 0x2010 sub 1-4 and a non-mappable setting 0x2020 sub 1-4
- **THEN** 0x2020 sub 1-4 are listed, 0x2010 is not, and the hidden count includes the four outputs

#### Scenario: Show all
- **WHEN** the user turns on "Show all writable objects"
- **THEN** 0x2010 sub 1-4 and the writable communication objects are listed too, and adding one works as today

#### Scenario: Startup SDO overlaps a plugin setting
- **WHEN** a node's startup SDO list writes 200 to 0x1017 sub 0 and the node also sets `heartbeat_ms` to 100
- **THEN** the configurator and the deploy tool warn that the startup SDO runs last and overrides the heartbeat setting, and the save still succeeds

### Requirement: SDO variables table
For each node the configurator SHALL edit the `sdo_variables` list with one entry per variable: name, object (picked from the node's EDS or typed as index and subindex, with the type taken from the EDS), direction, location, period, trigger, status and abort code locations. The object picker SHALL list readable objects for a read entry and writable objects for a write entry, and SHALL refuse objects the EDS does not define. Each location SHALL have a Suggest button that picks a free location of the right area and size. A write entry to an object the plugin configures itself SHALL show the same warning as the plugin. The located variable declarations SHALL include each entry's value (IEC type of the object), trigger (`BOOL`), status (`USINT`) and abort code (`UDINT`), named after the node and the entry.

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
- **WHEN** a write entry targets 0x1017, which the plugin configures itself
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
For each PDO the configurator SHALL show whether its mapping is written from the config or kept by the device, using the same rule as the plugin. When the node's EDS fixes the mapping, the PDO SHALL show "Set by the device" with its default mapping listed, the entry picker SHALL offer only the objects of that mapping, and no `mapping` field SHALL be saved. When the mapping is writable, the user SHALL be able to choose "Use device mapping", which saves `"mapping": "device"` and flags entries outside the default mapping. A device-mapped PDO SHALL offer "Map all", which adds every non-dummy object of the default mapping with suggested locations.

#### Scenario: Fixed PDO in the editor
- **WHEN** the user imports an EDS whose 0x1A00 is read-only with two UNSIGNED8 objects
- **THEN** TPDO 1 shows "Set by the device" with both objects, and "Map all" adds both as `%IB` inputs at the lowest free locations

#### Scenario: Switch a writable PDO to device mapping
- **WHEN** a writable TPDO has entries 0x4001 sub 0 and 0x4002 sub 0 and the EDS default maps only 0x4001 sub 0, and the user picks "Use device mapping"
- **THEN** the PDO saves with `"mapping": "device"` only after 0x4002 sub 0 is removed, and until then the entry shows an error listing the default mapping

### Requirement: Online access settings
The tree SHALL have an **Online access** entry, once for the whole config, that turns `master.diagnostics` on and off and edits its port, bind address and "allow changes" (off by default, with a warning that anyone with the token can then write parameters and stop nodes). Turning it on SHALL generate a random token of at least 128 bits, write only its SCRAM-SHA-256 verifier to `token_verifier`, and keep the token in the configurator's own settings on this PC for this project, never in the project folder. The page SHALL let the user copy the token, enter an existing token (for a project set up on another PC, checked against `token_verifier`), and generate a new one. When a project's config still has the former `token_sha256`, the page SHALL say that the token must be set again for the encrypted channel and, when this PC holds the matching token, offer **Upgrade**, which replaces `token_sha256` with a `token_verifier` for the same token; otherwise **New token** or **Enter token…** replaces it. The runtime host for online access SHALL be stored with the token and default to the host last used by the deploy tool when known.

#### Scenario: Enable online access
- **WHEN** the user opens Online access in the tree, turns it on in a project and saves
- **THEN** `canworks.json` has `master.diagnostics` with `token_verifier` and neither the token nor `token_sha256`, and the configurator's settings hold the token for this project

#### Scenario: Token from another PC
- **WHEN** the project already has `token_verifier` and this PC has no token for it
- **THEN** the connect panel asks for the token and accepts it only if it matches the verifier

#### Scenario: Upgrade an old project
- **WHEN** the project has `token_sha256`, this PC holds its token, and the user presses **Upgrade** and saves
- **THEN** `canworks.json` has a `token_verifier` for the same token and no `token_sha256`, and the copied token still works after the next upload

### Requirement: Online view
With online access set up and a runtime connected, the Commission workspace of a config SHALL show the runtime's state through the encrypted channel, refreshed about twice a second: the bus state and counters and the master state in the connection bar, and each node in the Nodes table and its Status tab, using the node names from the config. For each node it SHALL show its state, status bit, boot result with error text, retry and hold state, last EMCY with class, SDO variable values and status, and a mark on each monitored TPDO that is timed out with its timeout count. When the runtime's config fingerprint differs from the saved `canworks.json`, the workspace SHALL say that the runtime runs a different configuration and how to upload the saved config (the deploy tool command). Connection failures SHALL be shown in the connection bar with the reason (host unreachable, port closed, wrong token, runtime could not prove the token, plugin too old for encryption, no CANopen session) and retried. While retrying after a connection that was working, the last values SHALL stay visible but greyed, with the age of the last data shown and updated.

#### Scenario: Watch a node come back
- **WHEN** the Nodes table is open and node 23's cable is plugged back in
- **THEN** within about a second node 23's state goes from 0 to 127 to 5 and its boot result shows success

#### Scenario: Different config on the runtime
- **WHEN** the user saved a change but has not uploaded it yet
- **THEN** the Commission workspace shows that the runtime runs a different configuration

#### Scenario: Timed-out PDO
- **WHEN** node 23 is OPERATIONAL and its monitored TPDO 1 has timed out
- **THEN** node 23's row keeps its Operational state and shows "TPDO 1 timed out" with the count

#### Scenario: Plugin too old
- **WHEN** the runtime's plugin does not complete a TLS handshake
- **THEN** the connection bar says the runtime's plugin is too old for encrypted diagnostics and must be updated, and no unencrypted connection is offered

#### Scenario: Connection drops
- **WHEN** the runtime stops answering
- **THEN** within about two seconds the Nodes table turns grey, the connection bar says it is not connected and retrying, and shows "last data 2 s ago" counting up until data arrives again

### Requirement: Manual SDO and NMT in the online view
For each node the online view SHALL offer an SDO panel: pick an object from the node's EDS, or from the standard object dictionary when the node has no EDS (all objects, not only mappable ones), or type index and subindex, read it, and show the value decoded with the object's data type (numbers in decimal and hex, VISIBLE_STRING as text, other types as hex bytes), or the abort code with its CiA 301 text. When the runtime allows changes, the panel SHALL also write a value encoded from the object's type after a range check, warning before writing an object the plugin configures itself or one owned by an SDO variable; and the node SHALL have NMT buttons (start, stop, pre-operational, reset node, reset communication), with confirmation for stop, pre-operational and the resets, since each of those holds or interrupts the node. When the runtime does not allow changes, write and NMT controls SHALL be shown disabled with the reason.

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
Messages about the user's actions (saved, sent, copied, added, and errors) SHALL be shown in a bar under the header that stays in view while the page scrolls and has a close button. Information messages SHALL close by themselves after about 6 seconds; error messages SHALL stay until the user closes them or a new message replaces them. Switching to another view (bus and master, a node, declarations, online, scan) SHALL clear the bar. The bar SHALL be a polite live region for information messages and an alert for errors, so assistive technology reads them. A message about a removal SHALL carry an Undo action for as long as it is shown.

#### Scenario: NMT command sent
- **WHEN** the user sends Start to node 2 in the online view
- **THEN** "Node 2: Start sent." is shown and disappears after about 6 seconds without a page reload

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
- **THEN** its "Pick EDS file…" button shows its label on one line

#### Scenario: Automatic check
- **WHEN** the browser tests open each view (start, bus and master, each node, declarations, online, scan) at 1000, 1280 and 1440 px
- **THEN** a check over the page finds no clipped field or button and no horizontal overflow

### Requirement: Readable problem messages
The Problems panel and the messages next to fields SHALL name the place of a problem in the user's terms (node ID and name, PDO kind and number, object index and subindex, SDO variable name) and SHALL NOT show the internal config path (such as `nodes[2]: tx_pdos[1]: entries[0]:`). Selecting a problem SHALL still move to and highlight its field, opening its tree entry and tab first. The same wording SHALL be used wherever the configurator shows a check message: the Trace view's and Frame lab's "decoding without the config's PDOs" notes, the message bar and dialogs. No message shown on the page SHALL contain a filesystem path of the config or project, except where the path itself is the subject (the folder browser, the mode badge, the new-project dialog). An empty config SHALL be reported as "No nodes yet. Add a node from its EDS, or turn on Online access for a scan-only configuration." rather than as a schema error. An unexpected server error SHALL be shown as one sentence that points at the configurator's terminal, where the details are logged. The deploy tool's command-line messages are unchanged.

#### Scenario: Type does not fit the location
- **WHEN** node 5 (rtd) maps UNSIGNED8 object 0x6150:1 in TPDO 2 to `%IW320`
- **THEN** the Problems panel shows "Node 5 rtd, TPDO 2, 0x6150:1: type UNSIGNED8 (8 bit) does not fit location %IW320 (16 bit)" and clicking it opens node 5's PDOs tab with that entry's location field focused

#### Scenario: Trace note without a path
- **WHEN** the config has a type-does-not-fit error and the user opens a trace file
- **THEN** the Trace view's note reads "Decoding without the config's PDOs: Node 5 rtd, TPDO 2, 0x6150:1: type UNSIGNED8 (8 bit) does not fit location %IW320 (16 bit)" with no file path

#### Scenario: New config
- **WHEN** the user creates a new standalone config
- **THEN** the only problem reads "No nodes yet. Add a node from its EDS, or turn on Online access for a scan-only configuration."

### Requirement: Narrow window layout
At 1100 px wide and narrower (the page's existing narrow breakpoint) the network tree SHALL fold into a button at the top of the workspace tab that names the selected entry and shows the config's error count, and opens the tree over the page; picking an entry SHALL close it. The bottom panel SHALL stay, with its tab title showing the problem count, so the problems stay in view without a separate strip. A node's error count SHALL stay next to the node's name in the tree.

#### Scenario: Problems at 900 px
- **WHEN** the window is 900 px wide and the config has 4 errors
- **THEN** the bottom panel's tab reads "Problems 4" without scrolling, and opening it lists them

#### Scenario: Tree at 900 px
- **WHEN** the window is 900 px wide and the user opens the tree button and picks node 7
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
For each node the configurator SHALL show an "Assign node ID by serial number (LSS)" checkbox, saved as `lss.assign`, and a "Store node ID in the device" checkbox, saved as `lss.store`, which SHALL be unticked for a new node and disabled while the first is unticked. Unticked boxes SHALL be left out of the saved node, and an `lss` object with nothing in it SHALL be left out. While "Assign" is ticked the node's serial number field SHALL be required, `reset_communication` SHALL not be selectable as off, and the page SHALL say that the master gives the device this node ID at every start. When the node's EDS does not say `LSS_Supported=1` (left out or 0), both checkboxes SHALL be disabled and unticked, with the reason next to them ("This device's EDS has no LSS (LSS_Supported=1 missing)"). A loaded node that still has an `lss` object SHALL show it as a problem with the plugin's message and offer to remove it. Saving SHALL be refused until it is removed or the node gets an EDS with LSS.

#### Scenario: Turn on LSS for a node
- **WHEN** the user ticks "Assign node ID by serial number (LSS)" for node 12, enters serial number 0x1234 and saves
- **THEN** node 12 has `"lss": {"assign": true}` and `"serial_number"` 0x1234 (kept as typed, like the other identity fields), and no `lss.store`

#### Scenario: Assign without a serial number
- **WHEN** "Assign" is ticked for node 12 and its serial number is empty
- **THEN** saving is refused and the serial number field says it is needed for LSS

#### Scenario: EDS without LSS
- **WHEN** the user adds a node whose EDS says `LSS_Supported=0`
- **THEN** both LSS checkboxes are disabled with the reason, and the saved node has no `lss`

### Requirement: Unconfigured devices in the online view
The Nodes table SHALL have an **Unconfigured devices** panel, with and without a config. It SHALL be collapsed until changes are allowed or a search runs. It SHALL find a device without a node ID and show:
- its vendor ID, with the vendor name when an EDS gives it;
- its product code, revision and serial number;
- a matching EDS when the project's `canworks/` folder or the EDS library has one.

It SHALL offer "Set node ID" and "Set bit rate" for the device. Both dialogs SHALL have a "Store in the device" checkbox that is unticked each time the dialog opens.

"Set node ID" SHALL suggest the lowest node ID that is neither configured nor the master's. With a config, after success, the device SHALL be listed as Not in config and the page SHALL offer Add to config with that ID and EDS, setting `serial_number` and `lss.assign`. "Set bit rate" SHALL say before sending that the device switches after its next power cycle and that the connection's bit rate must be changed to match. Without changes allowed, the panel's controls SHALL be disabled with Unlock… (see "Unlock from a locked control").

When the matching EDS does not say `LSS_Supported=1`, the device SHALL be added without `lss.assign`, and the page SHALL say that its EDS has no LSS, so the node gets no LSS assignment.

#### Scenario: Commission a new sensor
- **WHEN** the user finds a device without node ID, sets node ID 40 with "Store in the device" ticked, and presses Add to config
- **THEN** the runtime sets and stores node ID 40, and the draft gets node 40 with the matching EDS, the device's serial number and `"lss": {"assign": true}`, unsaved until the user saves

#### Scenario: Store unticked by default
- **WHEN** the user opens "Set node ID" a second time after storing once
- **THEN** the "Store in the device" checkbox is unticked

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

### Requirement: Object dictionary view
In the online view every node SHALL have an object dictionary tab: from its EDS for each configured node and each node with a matched or picked EDS, else from the standard object dictionary (see "Standard object dictionary without an EDS"). The tab SHALL show a tree of every object, grouped as communication (0x1000-0x1FFF), manufacturer (0x2000-0x5FFF) and profile (0x6000-0x9FFF), with index, subindex, name, data type, access, EDS default and device value. Each object SHALL be one row: a VAR object with its value in that row, an ARRAY or RECORD object as a foldable row with its sub-entries below it, each sub-entry named by its own name without the object's name in front. Groups and objects SHALL start folded, except that a search or filter unfolds the groups and objects that hold a match. The tab SHALL use the full width of the online view, and long names SHALL wrap so that the row's buttons and watch box always stay inside the view without sideways scrolling. A search box SHALL filter by name or index.

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
The object dictionary tab SHALL offer "Read all" (the parameter read-all, with progress and cancel), "Read" on an object (all its readable sub-entries, in subindex order) and on a single entry, and a watch list of up to 32 entries refreshed at a period the user picks (500 ms or longer). Values SHALL be decoded as in the SDO panel. An entry whose value differs from its EDS default SHALL be marked, and an entry the configuration writes at boot or an SDO variable owns SHALL be marked as such.

#### Scenario: Read all and see changed values
- **WHEN** the user presses Read all on node 3 and 0x6110 subindex 1 differs from the EDS default
- **THEN** progress is shown while reading, and afterwards 0x6110 subindex 1 is marked as different from the default and its object row says that one of its entries differs

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
After a successful write in the object dictionary tab of a configured node, the page SHALL offer "Keep in configuration", which adds a startup SDO with the read-back value for that entry to the node in the draft configuration, or changes the value of the node's startup SDO for that entry when it has one, unsaved until the user saves. It SHALL be offered only for entries a startup SDO may write (a numeric type, writable access) and SHALL be refused, naming the reason, for an entry an SDO variable owns, for an object the plugin configures itself, and for an entry another setting of the configuration writes. It SHALL never write the device's non-volatile memory.

#### Scenario: Keep a tuned value
- **WHEN** the user writes 30 to 0x6110 subindex 2 of node 3, which has no startup SDO for it, and presses Keep in configuration
- **THEN** node 3 gets a startup SDO 0x6110 subindex 2 UNSIGNED16 30, the configuration shows as unsaved, and nothing more is sent to the node

#### Scenario: Startup SDO already there
- **WHEN** node 3 already has a startup SDO 0x6110 subindex 1 with value 30 and the user writes 40 and presses Keep in configuration
- **THEN** that startup SDO's value becomes 40 and no second entry is added

#### Scenario: Heartbeat object
- **WHEN** the user writes 0x1017 of node 3 and looks for Keep in configuration
- **THEN** it is not offered, saying the plugin sets 0x1017 itself from the node's heartbeat setting

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
The object dictionary tab SHALL offer "Copy as ST call" for a selected entry. It SHALL copy Structured Text that declares an instance of the matching block and calls it with the node ID, index and subindex filled in: `CO_SDO_READ_REAL`/`CO_SDO_WRITE_REAL` for REAL32 and REAL64, `CO_SDO_READ_STRING`/`CO_SDO_WRITE_STRING` for VISIBLE_STRING, `CO_SDO_READ_BYTES`/`CO_SDO_WRITE_BYTES` for OCTET_STRING and DOMAIN, and `CO_SDO_READ`/`CO_SDO_WRITE` for every other type, with the `LWORD_TO_<type>` conversion for the entry's IEC type in a comment. It SHALL offer the read call for readable entries and the write call for writable ones, and both when both apply. With several networks the call SHALL set `NETWORK` to the number of the network the online view talks to, with its name in a comment, and the instance name SHALL include the network's name. The entry row for any index and subindex SHALL offer the same, using `CO_SDO_READ`/`CO_SDO_WRITE` when no type is given.

#### Scenario: INTEGER16 entry
- **WHEN** the user picks "Copy as ST call", read, on node 5's 0x6401 subindex 1 (INTEGER16, `ro`)
- **THEN** the clipboard holds a declaration of a `CO_SDO_READ` instance, a call with `NODE := 5, INDEX := 16#6401, SUBINDEX := 1`, and a comment showing `LWORD_TO_INT(...DATA)`

#### Scenario: Device name
- **WHEN** the user picks "Copy as ST call" on 0x1008 subindex 0 (VISIBLE_STRING, `const`)
- **THEN** only the read is offered and it uses `CO_SDO_READ_STRING`

#### Scenario: Node on the second network
- **WHEN** the online view talks to `drives`, the second of two networks, and the user copies the read call for node 2's 0x1017 subindex 0
- **THEN** the clipboard declares `rd_drives_n2_1017_0 : CO_SDO_READ;` and calls it with `NETWORK := 1 (* drives *), NODE := 2, INDEX := 16#1017`

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

### Requirement: Map CiA 402 objects
For an axis node the configurator SHALL offer "Map CiA 402 objects", which adds each standard axis object that the EDS has as PDO-mappable and that is not yet mapped to a free entry of an RPDO (outputs) or TPDO (inputs) the device lets the master map, with suggested locations of the bridge's IEC types, and leaves PDO communication settings at the EDS's values. For a cyclic axis it SHALL put 0x6040, 0x6060 and 0x607A together in one RPDO and the other set-points in the next, and 0x6041, 0x6061 and 0x6064 together in one TPDO, and SHALL set transmission type 1 on the PDOs it fills whose effective type is not synchronous, listing each such change in its result. Objects that do not fit SHALL be listed by name and nothing already mapped SHALL change.

#### Scenario: Servo drive
- **WHEN** the user runs "Map CiA 402 objects" on an axis node whose EDS has all eleven standard objects, writable mapping and four RPDOs and TPDOs, with nothing mapped
- **THEN** all eleven objects are mapped with locations of the right IEC types and the axis check passes

#### Scenario: Does not fit
- **WHEN** the EDS has no 0x6077 object
- **THEN** the action maps the others and says 0x6077 is not in the EDS

#### Scenario: Cyclic layout
- **WHEN** the user runs "Map CiA 402 objects" on a cyclic axis whose EDS has writable mapping and event-driven (255) default PDOs
- **THEN** RPDO 1 holds 0x6040, 0x6060 and 0x607A, TPDO 1 holds 0x6041, 0x6061 and 0x6064, the PDOs it filled have transmission type 1 in the config, the result lists those type changes, and the cyclic axis check passes

### Requirement: Map CiA 402 objects on a fixed-mapping device
For a device whose PDO mapping the master cannot change, "Map CiA 402 objects" SHALL only give suggested locations to the standard objects already in the device's mapping and SHALL list the missing ones.

#### Scenario: Fixed mapping
- **WHEN** the device's fixed RPDO 1 holds 0x6040 and 0x60FF and the action runs
- **THEN** both get locations and the other standard outputs are listed as not in the device's mapping

### Requirement: Axis lines in the declarations
For an axis node the located variable declarations SHALL also offer the axis and bridge declarations and the bridge call lines the project generator writes, including the cycle time line of a cyclic axis from a task interval the user can enter (default T#20ms, the generator's default), ready to copy into an existing project.

#### Scenario: Copy axis lines
- **WHEN** node `drive` is an axis
- **THEN** the declarations panel shows the `drive : AXIS_REF_SM3;` and `drive_bridge` declarations and the call of `drive_bridge` with the node's mapped objects

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
The slave device page SHALL edit node ID (or LSS), the EDS (pick a file, or build one), the bound objects with their PLC locations, `inputs_on_loss` and the status and EMCY locations. Object rows SHALL come from the EDS, show the direction from its access type, and offer only matching PLC areas.

#### Scenario: Bind an object
- **WHEN** the user adds 0x2100:1 (access `ro`, UNSIGNED16) from the EDS
- **THEN** the row suggests a free `%QW` location and refuses an `%I` one

### Requirement: Build the slave EDS in the configurator
The page SHALL have an object list editor (name, type, direction, default, limits), identity fields and a layout choice, and SHALL generate the EDS with the same generator as `slave-eds` into the project's `canworks/` folder, then offer to bind every generated object to suggested locations.

#### Scenario: Build and bind
- **WHEN** the user enters four objects, generates and accepts the suggested bindings
- **THEN** `canworks/` has the EDS and the config binds all four objects

### Requirement: Export the slave EDS
The page SHALL have an **Export EDS** button that saves the slave's EDS for import into the other master's tool, with a file name from the device name.

#### Scenario: Export
- **WHEN** the user clicks **Export EDS**
- **THEN** a save dialog offers the EDS the plugin runs

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

### Requirement: Busy states and the Save button
Save, every export, Move into project, New editor project and Add node from EDS SHALL disable their control and show what is running ("Saving…", "Exporting…", "Adding…") until the request completes, and a second click meanwhile SHALL do nothing. The Save button SHALL read "Saved" and be disabled when the draft equals the file, "Save" when the draft is dirty, "Save (overlaps allowed)" when the overlap override is on; when the draft has errors it SHALL be disabled with a tooltip giving the error count, and the count SHALL be shown in the Problems pane rather than in the button's label.

#### Scenario: Double click on Save
- **WHEN** the user clicks Save twice while the first save is still running
- **THEN** one save request is made and the button reads "Saving…" until it returns

#### Scenario: Clean draft
- **WHEN** the file on disk equals the draft
- **THEN** the button reads "Saved" and is disabled

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
- error history clear.

"Save log" in the bottom panel's Log tab SHALL download `node<N>-commissioning-<time>.txt` with the device identity and EDS name at the top and the changes in order, and the bus events too when "Include bus events" is ticked (unticked by default).

The log SHALL belong to the commissioning session. Leaving Commission a device (Close, or "Add to a config…") with changes not saved SHALL ask whether to save the log first. The log SHALL then be cleared.

#### Scenario: Save the record
- **WHEN** the user gave the device node ID 12, wrote a configuration and stored it, then pressed Save log
- **THEN** the file lists those three changes in order with their results and no bus events

#### Scenario: Not carried into the config
- **WHEN** the user made two changes while commissioning, pressed "Add to a config…" and chose not to save the log
- **THEN** the config opens with an empty session log, and returning to Commission a device starts an empty log

### Requirement: Note editor
The Notes tab SHALL be the only place in a project that opens the Note editor: each row's **Note** button and **Add note…**. The editor SHALL edit one object or sub-object with text, details, unit, scale, a values table, a bits table and manual. For an object with a built-in note the editor SHALL start from the built-in fields and SHALL save only the fields the user changed into the device notes file. Emptying a field that shows a built-in or inherited value SHALL save that field as `null` (cleared); such a field SHALL show the built-in value greyed and marked hidden, with **Use built-in** to bring it back. The object dictionary view, the startup SDO editor and picker and the PDO entry picker SHALL show notes and SHALL NOT offer a Note button.

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
A note edit SHALL mark the draft as changed, SHALL be written with Save, and SHALL be undoable like other draft edits.

#### Scenario: Undo a note
- **WHEN** the user changes the text of 0x2010 in the Note editor and presses Ctrl+Z
- **THEN** the earlier text is back and the draft is clean again if nothing else changed

### Requirement: Notes read-only without a config
In "Commission a device" without a config, notes SHALL be shown but not editable.

#### Scenario: Read-only when commissioning
- **WHEN** the user opens the object dictionary view in "Commission a device" without a config
- **THEN** notes are shown and no Note button is offered

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

### Requirement: The check refuses what the plugin refuses
The configurator's check (and the deploy tool's, which is the same) SHALL refuse every config the plugin refuses at start. In particular:
- an adapter without an interface (or an slcan adapter without a device);
- a number outside its range whatever base it is typed in (decimal or `0x` hex): node IDs, heartbeat times, identity values, COB-IDs, TIME COB-ID;
- two PDOs on one network with the same COB-ID, naming both;
- an axis scale numerator or denominator of 0.

A heartbeat consumer timeout shorter than the node's heartbeat period SHALL be refused, as the plugin refuses it. Each message SHALL name the place in the user's terms and say what is allowed ("node ID 1 to 127", "COB-ID 0x185 is also node 5's TPDO 1"), not quote a schema rule or pattern.

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

### Requirement: Modbus bridge target
A project SHALL have a target, "OpenPLC" (default) or "Modbus bridge". Switching the target SHALL offer to repack all locations for the new addressing (per-type for OpenPLC, Pack for Modbus for the bridge), and SHALL add or remove the `bridge` object. The settings that make no sense for the target (`sync_source: plc_cycle` for the bridge) SHALL be marked as problems.

#### Scenario: Switch to the bridge
- **WHEN** the user switches an OpenPLC project with two nodes to "Modbus bridge" and accepts repacking
- **THEN** the file gets a `bridge` object with `listen` `0.0.0.0:502`, every location is byte-addressed and packed, and Check reports no problems

### Requirement: Bridge settings panel
A bridge project SHALL have a "Modbus bridge" page with:
- listen address and port, unit ID, word order, maximum clients
- writer and reader allowlists
- watchdog time and client-loss action
- status block, control block, live lists and SDO bridge locations, each with a "Suggest" button that places it after the packed data

#### Scenario: Add a live list
- **WHEN** the user adds a live list for network `field` and clicks Suggest
- **THEN** a free 16-byte input range is chosen and shown in the register map

### Requirement: Register map preview and export
The bridge page SHALL show the register map as a table (Modbus table, address, size, type, name, source) with a filter, the suggested client channels, and buttons to export CSV, JSON and the ST variable list. "Pack for Modbus" SHALL be available on the page.

#### Scenario: Export the ST list
- **WHEN** the user clicks "Export ST variables"
- **THEN** the browser downloads the same file `canworks-deploy --export-modbus-map map.st` writes for this config

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
- **THEN** the position is marked, Problems names the link, the consumer and both sizes, and Save is disabled

#### Scenario: Producer removed
- **WHEN** the user deletes node 10's TPDO 1 that a link uses
- **THEN** the configurator asks to delete the link too, defaulting to cancel

### Requirement: Heartbeat watch setting
The node page's supervision section SHALL list the node's heartbeat watch entries (watched node from the network's nodes, timeout with the default shown when empty), and the check SHALL give the same messages as the plugin for them, including the 0x1016 capacity from the node's EDS.

#### Scenario: Default timeout shown
- **WHEN** node 20 watches node 10, which has `heartbeat_ms` 100, and the timeout field is empty
- **THEN** the field shows "default (300 ms)" and the saved entry has no `timeout_ms`

### Requirement: Links in the online view
With online access the Links page SHALL show for each link the NMT state of its producer and of each consumer from the live status, mark a link whose producer or any consumer is not OPERATIONAL, and show the producer TPDO's timeout state when it has `timeout_ms`.

#### Scenario: Consumer down
- **WHEN** the online view is open and node 20 of a link is lost
- **THEN** the link row is marked and node 20's cell shows no contact while node 10 stays OPERATIONAL

### Requirement: CiA 309-3 gateway settings
The Online access settings SHALL have a "CiA 309-3 gateway" part that turns `cia309` on and off and edits its plain port (or none), `max_clients`, "allow changes" and "allow force on running nodes" (both off by default; force with a warning that a standard tool can then stop nodes the program drives), and shows the network numbering, with optional explicit numbers per network. It SHALL say that the plain port listens on the PLC's loopback address only and that other machines connect through `canworks-diag gateway` with the project's token. The deploy tool's config check and the configurator's Check SHALL apply the plugin's `cia309` rules.

#### Scenario: Turn the gateway on
- **WHEN** the user turns on the CiA 309-3 gateway in a project with networks `io` and `drives` and saves
- **THEN** `canworks.json` has a top-level `cia309` object with `allow_changes` false, and the page shows `1 = io, 2 = drives`

#### Scenario: Network bind refused in Check
- **WHEN** a hand-edited project has `cia309.bind` set to `0.0.0.0`
- **THEN** Check reports `cia309.bind` with the plugin's message

### Requirement: Copy NMT calls as ST
The online view SHALL offer "Copy as ST call" next to each node's NMT buttons (start, stop, pre-operational, reset node, reset communication). It SHALL copy Structured Text that declares a `CO_NMT` instance and calls it with the node ID and the CiA 301 command code of that button, with the command's name in a comment, and SHALL be available whether or not the runtime allows changes, since it sends nothing. With several networks the call SHALL set `NETWORK` to the number of the network the online view talks to, with its name in a comment, and the instance name SHALL include the network's name. The master's "Master goes operational" setting SHALL say that, when it is off, the master stays pre-operational until the PLC program starts it with `CO_NETWORK_START`, and SHALL offer "Copy as ST call" for a `CO_NETWORK_START` instance and call.

#### Scenario: Stop call for a node
- **WHEN** the user picks "Copy as ST call" next to node 5's Stop button
- **THEN** the clipboard holds a declaration of a `CO_NMT` instance and a call with `NODE := 5, COMMAND := 2 (* STOP *)`

#### Scenario: Changes not allowed
- **WHEN** the runtime's `allow_changes` is false
- **THEN** the NMT buttons are disabled and "Copy as ST call" still copies the call

#### Scenario: Network start call
- **WHEN** the user turns "Master goes operational" off
- **THEN** the hint says the program starts the master with `CO_NETWORK_START`, and "Copy as ST call" copies a `CO_NETWORK_START` declaration and call

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
The node page's Emergency (EMCY) section SHALL edit `emcy_cob_id`: Device (the default, saved as no field), EDS, or a COB-ID typed in hex or decimal. The Check SHALL give the plugin's messages for a COB-ID the plugin rejects. The online view's node row SHALL show the EMCY COB-ID in use, with its source, when it is not 0x80 + node ID, and SHALL mark it when the device reports its EMCY not valid.

#### Scenario: Default not saved
- **WHEN** the user leaves the EMCY COB-ID on Device and saves
- **THEN** the saved node has no `emcy_cob_id`

#### Scenario: Clashing COB-ID typed
- **WHEN** the user types node 6's TPDO 1 COB-ID as node 5's EMCY COB-ID
- **THEN** the Check reports node 5's `emcy_cob_id` clashing with node 6's TPDO 1

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

### Requirement: Network picker in online and trace views
When the runtime reports more than one network, the connection bar SHALL have a network picker. The Commission pages, Trace and Simulation SHALL show and act on the picked network only. The picker SHALL start on the network of the entry selected in Configure's tree. In Commission, picking a tree entry on another network SHALL move the picker, and changing the picker SHALL select that network's tree entry.

#### Scenario: Online view of the second network
- **WHEN** the runtime runs `io` and `drives` and the user picks `drives` in the connection bar
- **THEN** the Commission workspace shows `drives`' bus state and nodes, the tree selects `drives`, and SDO, NMT, parameter and object dictionary actions go to `drives`

### Requirement: Workspaces
With a config open, the header SHALL have a **Configure | Commission** switch:
- **Configure** SHALL show the config pages.
- **Commission** SHALL show the live view of the runtime as its **Nodes** tab, with the network tree (see "Tree in Commission with a config") and the node pages of the online view.

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

A tool tab SHALL use the full page width, with no network tree, side bar or bottom panel. The network tree SHALL list no tools. The tabs SHALL follow the page's tab pattern (see "Keyboard access and announcements").

#### Scenario: Trace from a node page
- **WHEN** the user is on node 5's PDOs tab in Configure and picks the Trace tab
- **THEN** the trace view fills the width of the page, and picking Network returns to node 5's PDOs tab

#### Scenario: Tools in Commission a device
- **WHEN** the user opens Commission a device
- **THEN** the tabs are Nodes, Trace and Frame lab

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

### Requirement: Allow changes in the connection bar
On an adapter connection, **Allow changes** SHALL be a switch in the connection bar. It SHALL be off for every new connection, SHALL ask before switching on, and SHALL apply to the open connection without reconnecting. On a runtime connection, the bar SHALL show the runtime's own setting as read-only text with a lock and SHALL say that it is set in Configure → Online access and takes effect after an upload, with a link that opens that entry.

#### Scenario: Switch on an open adapter connection
- **WHEN** the user is connected read-only to an adapter and switches Allow changes on and confirms
- **THEN** write controls on every page are enabled without reconnecting, and no "another master" message appears

#### Scenario: Runtime decides
- **WHEN** the user is connected to a runtime whose config has allow changes off
- **THEN** the bar shows "Read-only (runtime setting)" with no switch, and its link opens Online access in Configure

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

Each tab title SHALL carry its count. There SHALL be no right-hand Problems column.

#### Scenario: Problems under the page
- **WHEN** the config has 4 errors in Configure
- **THEN** the panel's tab reads "Problems 4", the page uses the full width beside the tree, and clicking a problem goes to its field

#### Scenario: Log while commissioning
- **WHEN** the user gave a device node ID 12 by LSS in Commission a device
- **THEN** the Log tab lists the change, the Changes filter reads 1, and Save log downloads the log

#### Scenario: Problem after adding a found device
- **WHEN** the user adds a found node 9 whose EDS has no TPDO the config can map, and the check reports a problem
- **THEN** the Problems tab opens with that problem and the user stays in Commission

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
- **THEN** the row shows the refusal with the plugin's reason and the other 8 keep running

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
In both workspaces of a config, the left column of the workspace tab SHALL be a network tree, and it SHALL be the only navigation there. The tree SHALL show every network of the config at once, each as an entry with its name and protocol (CANopen master, CANopen slave, J1939 or Plain CAN). Under a network it SHALL show the entries that network has:
- Bus and master (Bus and ECU on J1939, Bus on Plain CAN and on a slave network);
- its nodes, sorted by node ID, each named by node ID and name;
- the slave device on a slave network;
- **Add node…** on a CANopen master network in Configure, which opens the EDS file chooser for that network;
- PDO links and CAN messages, when the network has them today.

After the networks the tree SHALL show Online access (Configure), Gateway and Modbus bridge when the config has them, and **Add network…** (Configure). Each network entry SHALL have a menu with **Rename…**, **Role** (CANopen networks) and **Remove…**, keeping today's confirmations. Which networks are folded SHALL be kept on this PC and SHALL come back after a page reload; a folded network SHALL show the sum of its entries' problem counts, and SHALL unfold by itself when a problem link opens an entry in it. The unused EDS files note and the address scan line SHALL be shown under the tree. Renaming a node SHALL update its entry as the user types.

#### Scenario: Two networks at once
- **WHEN** a config has networks `io` with nodes 5 and 7 and `drives` with node 2
- **THEN** the tree shows `io` and `drives` with their nodes, and opening node 2 needs no network switch

#### Scenario: Add a node to the second network
- **WHEN** the user picks **Add node…** under `drives` and chooses an EDS file
- **THEN** the node is added to `drives`, its entry is selected, and its General tab opens with focus in the name field

#### Scenario: Remove a network from its menu
- **WHEN** the user opens the menu of network `drives`, which has 3 nodes, and picks **Remove…**
- **THEN** the page asks for confirmation naming `drives` and its 3 nodes, with Cancel as the default

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
- **CiA 402**: the axis settings, shown only when the node's EDS has 0x6040 and 0x6041 or the node already has an axis;
- **Simulation**, shown only for a simulated node (see "Simulation tab of a node");
- **Notes** (see "Notes tab");
- **Advanced**.

The tabs SHALL follow the page's tab pattern. Opening another node SHALL keep the open tab when that node has it, and open General otherwise. The open tab SHALL come back after a page reload. A node just added from an EDS SHALL open on General with focus in its name. Objects SHALL be mapped from within the PDO they go into ("Add entry…" per PDO, listing that direction's mappable objects), with "Map all" kept for device-mapped PDOs.

#### Scenario: Compare heartbeats across nodes
- **WHEN** the user is on node 5's Supervision tab and opens node 7 in the tree
- **THEN** node 7's Supervision tab is shown

#### Scenario: No CiA 402 tab for an I/O module
- **WHEN** the user opens a node whose EDS has neither 0x6040 nor 0x6041 and that has no axis
- **THEN** the node has no CiA 402 tab

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
A simulated node (its `simulate`, or a node on a simulated network that is not switched off) SHALL have a Simulation tab that edits that node's part of the simulation file: its value sources, its faults at start and its default behaviour switch. It SHALL edit the same draft as the Simulation tool, so a change shows in both, and SHALL be saved with **Save to simulation file**. With several networks it SHALL edit the node's own network section.

#### Scenario: Source from the node
- **WHEN** the user gives node 5's 0x6401:1 a sine on its Simulation tab and saves to the simulation file
- **THEN** `simulation.json` has that source for node 5, and the Simulation tool shows it

### Requirement: Notes tab
The Notes tab SHALL list the objects of the node's EDS in one of three views chosen above the list: **My notes** (the default), the objects and sub-objects whose device notes entry, with the page's unsaved edits, has at least one field other than `name`; **All notes**, the objects with a note, built-in or the user's own; and **All objects**, every object and sub-object of the EDS. Each row SHALL show the object, its name, the note's text, unit and value meanings, where the note comes from as text (**Mine**, **Built-in** or **Built-in, changed**), and a **Note** button opening the Note editor. The tab SHALL offer a search by index or name and, next to it, **Add note…**, **Import notes…** and **Export notes…** (see `canopen-device-notes`). **Add note…** SHALL open a picker of all objects and sub-objects of the EDS, searchable by index or name and marking those with a note, and then the Note editor of the chosen one. The tab's label SHALL show the number of the user's notes. The chosen view and the search SHALL be kept while the page is open. An empty view SHALL say why and offer **Add note…**, **Import notes…** and a way to show **All notes**. When the node has no EDS or its notes cannot be edited, the tab SHALL be read-only, SHALL say why, and SHALL offer only the views, the search and **Export notes…**.

#### Scenario: Own notes first
- **WHEN** the user opens the Notes tab of a drive whose notes file has a text for 0x2010 and only `name` entries for its other manufacturer objects, and the user has changed the values of 0x6060
- **THEN** My notes lists 0x2010 marked Mine and 0x6060 marked Built-in, changed, and nothing else, and the tab reads "Notes 2"

#### Scenario: Find a note
- **WHEN** the user picks All notes and types `6060` in the search of a drive
- **THEN** only 0x6060 is listed with its note, and **Note** opens its editor

#### Scenario: Note for an object without one
- **WHEN** the user presses **Add note…**, types `2011`, picks 0x2011:1, types a text in the Note editor and keeps it
- **THEN** My notes lists 0x2011:1 marked Mine with the focus on its row, and the draft is unsaved

#### Scenario: No notes yet
- **WHEN** the user opens the Notes tab of a node whose EDS has no notes of the user's own
- **THEN** the tab says there are no notes of the user's own yet and offers Add note…, Import notes… and Show all notes

#### Scenario: Read-only Notes tab
- **WHEN** the user opens the Notes tab of a node in "Commission a device" without a config
- **THEN** the notes are listed and can be exported, and no Note, Add note… or Import notes… button is offered

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
In Commission with a config, the tree SHALL show the config's networks and their nodes, without the configuration-only entries (Bus and master, Add node…, PDO links, CAN messages, Online access, Gateway, Modbus bridge, Add network…) and without the network menu. A network entry SHALL open that network's node table with its bus state, and a node entry the node's live tabs. Picking an entry on another network SHALL move the connection bar's network picker to that network, and changing the picker SHALL select that network's entry. Each workspace SHALL keep its own selected entry.

#### Scenario: Open a live node
- **WHEN** the page is connected to a runtime running `io` and `drives` and the user opens node 2 under `drives` in Commission
- **THEN** node 2's live tabs open and the connection bar's picker shows `drives`

#### Scenario: Back to where the user was
- **WHEN** the user was on node 5's PDOs tab in Configure, opened node 2 in Commission, and switches back to Configure
- **THEN** node 5's PDOs tab is shown

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
- **Add to config** for Not in config rows, one or several ticked rows at once: each becomes an unsaved node with that node ID, the matching EDS (a picker when several match, a file picker when none does), the EDS product name as name and the serial number, with `lss.assign` set when the ID was given by LSS in this session and the EDS says `LSS_Supported=1`;
- **Use matching EDS** for an Identity differs row when an EDS in the project or the EDS library matches the device;
- **Take serial number** when only the serial number differs.

Each action SHALL be a draft edit that Undo reverts. The user SHALL stay in Commission, the header SHALL show the unsaved mark, and problems the change causes SHALL show in the bottom panel's Problems tab.

#### Scenario: Add a found device
- **WHEN** node 9 reads Not in config, one EDS in the library matches it, and the user presses Add to config
- **THEN** the draft has node 9 with that EDS imported, its product name and serial number, the row reads Match, and the header shows the unsaved mark

#### Scenario: Undo an add
- **WHEN** the user added node 9 from the comparison and presses Undo
- **THEN** node 9 is gone from the draft and its row reads Not in config again

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
A write control disabled because changes are not allowed SHALL say "Locked. Changes are not allowed on this connection." and offer **Unlock…**. On an adapter, Unlock SHALL ask the same question as the lock in the connection bar and, when confirmed, allow changes on the open connection without reconnecting, with focus kept on the control. On a runtime, Unlock SHALL explain that Allow changes is set in Configure → Bus and master → Online access and takes effect after an upload. Controls disabled for another reason SHALL keep their own reason.

#### Scenario: Unlock in place
- **WHEN** the user is connected read-only to an adapter, presses Unlock… beside node 5's Start button and confirms
- **THEN** Allow changes is on in the connection bar, Start is enabled and focused, and no "another master" message appears

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
A pending diagnosis (an EMCY or error problem not yet cleared) SHALL add a flag in the error colour after a node's state icon; once cleared the flag SHALL turn grey and stay until the history is cleared. A simulated node SHALL add a dashed outline to its state icon.

#### Scenario: Cleared diagnosis
- **WHEN** node 5 sent an EMCY that is later cleared
- **THEN** its flag turns from the error colour to grey

#### Scenario: Simulated node
- **WHEN** node 9 is simulated and OPERATIONAL
- **THEN** its icon is the filled circle with a dashed outline

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
The browser tests SHALL do five user tasks with the keyboard alone, in the Light and the Dark theme: connect to a virtual USB adapter, scan the bus, add a found node to a config, map a PDO entry and save, and record and save a trace. They SHALL use the virtual adapter, the fake plugin runtime and the local simulator runtime, with no hardware, and SHALL fail if a step uses the pointer.

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
- **Nodes**, on a CANopen network: each node heard on the bus or on the Nodes tab, with its device name, its EDS file or "none, built-in CiA names", the source of its PDO layout ("set on the bus at …", "read from the device at …", "EDS defaults", "configuration", or "unknown"), and the actions **Pick EDS…** or **Change EDS…** (the Nodes table's menu for that node) and **Read PDOs from device**.

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
On a selected row of a list or table (filled with the accent colour), every button and text of the row SHALL keep at least WCAG AA contrast against what is behind it, in both themes. A button SHALL keep its own colours rather than take the row's text colour.

#### Scenario: Remove on a selected CAN message
- **WHEN** the user selects a received message on the CAN messages page in the dark theme
- **THEN** its Remove button reads clearly (red on the button's own fill), and "(no name)" reads in the row's text colour

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
The Parameters tab of a node without an EDS SHALL say that back up, compare and restore need the device's EDS and offer the node's EDS matches and **Pick EDS file…**.

#### Scenario: Parameters without an EDS
- **WHEN** the user opens the Parameters tab of node 49, which has no EDS
- **THEN** the tab says back up, compare and restore need the device's EDS and offers Pick EDS file…

### Requirement: Change or clear a node's EDS
In the Nodes table, a node whose EDS was picked, matched or added on the page (not from the config) SHALL show the EDS file name with **Change EDS…**. It SHALL ask, in a dialog, for one of the node's other EDS library matches, **Pick EDS file…** or **Clear EDS**. Changing SHALL reload the node's tabs from the new EDS, clearing SHALL return the node to the standard dictionary, and both SHALL be logged in the Commissioning log.

#### Scenario: Wrong EDS picked
- **WHEN** node 23 shows an EDS file the user picked by mistake and the user picks another file through Change EDS…
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
The Commission workspace SHALL compare the runtime's config fingerprint with both the saved `canworks.json` and the `conf/canworks.json` the deploy tool and the editor hook write from it, with every node's and every slave's EDS path rewritten as they do. Right after an upload of the saved config, the workspace SHALL NOT say that the runtime runs a different configuration, also when the config has a slave network.

#### Scenario: Gateway config uploaded
- **WHEN** the virtual plant (a slave network `cell` with its own EDS) is uploaded with `canworks-deploy` and the configurator connects to that runtime
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

### Requirement: Export for CODESYS
The header's Export menu SHALL offer "CODESYS", which runs the `codesys-export` export on the config as shown on the page, saved or not, with every master network, and offers the folder as a browser download `<config folder name>_codesys.zip`. When the config has errors or a DCF fails validation, it SHALL download nothing and show the messages in the Problems panel, as the DCF export does. It SHALL NOT write any file in the project or config folder.

#### Scenario: Download
- **WHEN** the config is valid and the user picks Export > CODESYS
- **THEN** the browser downloads `<folder>_codesys.zip` holding the network folders with their DCFs, `canworks-codesys.json`, `import_canworks.py` and `README.txt`

#### Scenario: Config with errors
- **WHEN** the config has errors and the user picks Export > CODESYS
- **THEN** nothing is downloaded and the Problems panel lists the errors

### Requirement: New editor project in standalone mode
In standalone mode the page SHALL offer "New editor project" next to "move into project". It SHALL ask for a parent folder (prefilled with the home folder, as "move into project" does), a project name, the task interval (default `T#20ms`) and whether to enable the canworks function blocks (unchecked by default), create the project as `canopen-editor-project` describes, and then switch to project mode on the new project. It SHALL require the config to be saved first and SHALL show the reason when creation is refused. The standalone folder SHALL be left unchanged.

#### Scenario: Create and switch
- **WHEN** the user has saved a standalone config in `~/canworks/rtd`, chooses "New editor project", picks `~/workspace` and the name `rtd-monitor`
- **THEN** `~/workspace/rtd-monitor` is created with the config in its `canworks/` folder and `main` declaring its I/O, and the page shows mode "project rtd-monitor" with every CANopen entry marked as declared

#### Scenario: Function blocks enabled
- **WHEN** the user ticks "Enable the canworks function blocks" in the dialog
- **THEN** the project is created as with `--blocks`, and the page shows how to install the library when the creation output says it is missing

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
The Trace inspector SHALL have a close button (✕) in its own title bar, and Esc with the focus inside the inspector SHALL close it and return the focus to the selected row. A closed inspector SHALL leave a slim **Inspector** rail at its edge that opens it again. Selecting a frame by click or Enter while it is closed SHALL open it. Moving through the list with the arrow keys SHALL NOT open it. The open or closed state SHALL be kept on this PC.

#### Scenario: Close with Esc
- **WHEN** the user tabs into the inspector of a selected SYNC frame and presses Esc
- **THEN** the inspector closes, the rail shows, and the focus is on the SYNC row

#### Scenario: Reopen by selecting
- **WHEN** the inspector is closed and the user clicks a TPDO row
- **THEN** the inspector opens on that TPDO

#### Scenario: Arrow keys keep it closed
- **WHEN** the inspector is closed and the user moves down the Chronological list with the arrow keys
- **THEN** the inspector stays closed and the selection moves

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
The simulation banner SHALL show one line per page: what is simulated, network by network, and that the configuration must not be uploaded to a machine as it is. Each network's part SHALL be short, for example "io (nodes 5, 6, 7)". A **Details** control SHALL open the full text of each network's simulation. On a phone-width window it SHALL take at most two lines.

#### Scenario: Four simulated networks
- **WHEN** the virtual plant example is open at 1440 px
- **THEN** the banner is one line naming io (nodes 5, 6, 7), motion (node 4), cell and host and saying not to upload it, and Details opens the full text
