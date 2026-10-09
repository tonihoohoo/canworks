# canopen-configurator Specification

## Purpose
A local GUI on the engineering PC that creates and edits the CANopen config of an OpenPLC Editor project (its `canworks/` folder), so CANopen nodes can be added and mapped to PLC addresses without hand-writing JSON or changing the editor.

## Requirements

### Requirement: Choose what to edit
Started without arguments, the configurator SHALL open a start page offering: open an editor project, open a standalone config folder, or create a new standalone config. The page SHALL let the user browse local folders and SHALL list recently opened ones. A path given on the command line SHALL open directly, as a project when the folder has `project.json` and as a standalone config otherwise. The current mode SHALL always be visible.

#### Scenario: Start page
- **WHEN** `canworks-config` runs without arguments
- **THEN** the browser shows the start page with the three choices and the recent folders

#### Scenario: Open a project from the start page
- **WHEN** the user chooses "open editor project" and picks `~/Documents/workspace/rtd-monitor`, which has `canworks/canworks.json`
- **THEN** the page shows that config with the mode "project rtd-monitor"

#### Scenario: Project without a config
- **WHEN** the user opens an editor project that has no `canworks/` folder
- **THEN** the page shows an empty config and the project folder is unchanged until the user saves

#### Scenario: Not an editor project
- **WHEN** the user picks a folder without `project.json` under "open editor project"
- **THEN** the page says it is not an editor project and offers to open it as a standalone config instead

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
Adding a node SHALL start from an EDS file the user picks. The configurator SHALL check that it is a CiA 306 EDS the deploy tool accepts, store it under `canworks/` as UTF-8 (converting from Latin-1/CP1252 when it is not valid UTF-8) and refer to it by a path relative to `canworks/`. A different file with the same name SHALL NOT be overwritten silently.

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
For each node the configurator SHALL edit an ordered list of startup SDO writes, which the plugin performs every time the node is configured at boot. The user SHALL pick the object from the node's EDS or type an index and subindex, and the type SHALL come from the EDS. Objects the EDS does not define, or marks read-only or const, SHALL be refused, and each value SHALL be checked against its type's range.

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
Saving SHALL write `canworks/canworks.json` and the imported EDS files under `canworks/`, and no other file. `canworks.json` SHALL be replaced atomically, carry `schema_version` 1 and keep fields the configurator does not know. The saved folder SHALL be accepted unchanged by the deploy tool's `--config` and by the editor-upload hook.

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
The master settings SHALL have an "Online access" section that turns `master.diagnostics` on and off and edits its port, bind address and "allow changes" (off by default, with a warning that anyone with the token can then write parameters and stop nodes). Turning it on SHALL generate a random token of at least 128 bits, write only its SCRAM-SHA-256 verifier to `token_verifier`, and keep the token in the configurator's own settings on this PC for this project, never in the project folder. The page SHALL let the user copy the token, enter an existing token (for a project set up on another PC, checked against `token_verifier`), and generate a new one. When a project's config still has the former `token_sha256`, the section SHALL say that the token must be set again for the encrypted channel and, when this PC holds the matching token, offer **Upgrade**, which replaces `token_sha256` with a `token_verifier` for the same token; otherwise **New token** or **Enter token…** replaces it. The runtime host for online access SHALL be stored with the token and default to the host last used by the deploy tool when known.

#### Scenario: Enable online access
- **WHEN** the user turns on online access in a project and saves
- **THEN** `canworks.json` has `master.diagnostics` with `token_verifier` and neither the token nor `token_sha256`, and the configurator's settings hold the token for this project

#### Scenario: Token from another PC
- **WHEN** the project already has `token_verifier` and this PC has no token for it
- **THEN** the online view asks for the token and accepts it only if it matches the verifier

#### Scenario: Upgrade an old project
- **WHEN** the project has `token_sha256`, this PC holds its token, and the user presses **Upgrade** and saves
- **THEN** `canworks.json` has a `token_verifier` for the same token and no `token_sha256`, and the copied token still works after the next upload

### Requirement: Online view
With online access set up, the configurator SHALL offer an online view that connects to the runtime over the encrypted channel, refreshes about twice a second, and shows the bus state and counters, the master state, and for each node its state, status bit, boot result with error text, retry and hold state, last EMCY with class, SDO variable values and status, and a mark on each monitored TPDO that is timed out with its timeout count, using the node names from the config. Opening a node SHALL show its EMCY history with times and CiA 301 error classes, and for each monitored TPDO its timeout, count and time since its last PDO. When the runtime's config fingerprint differs from the saved `canworks.json`, the view SHALL say that the runtime runs a different configuration. Connection failures SHALL be shown with the reason (host unreachable, port closed, wrong token, runtime could not prove the token, plugin too old for encryption, no CANopen session) and retried. While retrying after a connection that was working, the last values SHALL stay visible but greyed, with the age of the last data shown and updated, so stale values are never mistaken for live ones. The different-configuration note SHALL say how to upload the saved config (the deploy tool command) so it can be acted on. The connection line SHALL be a polite live region.

#### Scenario: Watch a node come back
- **WHEN** the online view is open and node 23's cable is plugged back in
- **THEN** within about a second node 23's state goes from 0 to 127 to 5 and its boot result shows success

#### Scenario: Different config on the runtime
- **WHEN** the user saved a change but has not uploaded it yet
- **THEN** the online view shows that the runtime runs a different configuration

#### Scenario: Timed-out PDO
- **WHEN** node 23 is OPERATIONAL and its monitored TPDO 1 has timed out
- **THEN** node 23's row stays green for its state and shows "TPDO 1 timed out" with the count

#### Scenario: Plugin too old
- **WHEN** the runtime's plugin does not complete a TLS handshake
- **THEN** the view says the runtime's plugin is too old for encrypted diagnostics and must be updated, and offers no unencrypted connection

#### Scenario: Connection drops
- **WHEN** the online view is connected and the runtime stops answering
- **THEN** within about two seconds the node table turns grey, the connection line says it is not connected and retrying, and shows "last data 2 s ago" counting up until data arrives again

### Requirement: Manual SDO and NMT in the online view
For each node the online view SHALL offer an SDO panel: pick an object from the node's EDS (all objects, not only mappable ones) or type index and subindex, read it, and show the value decoded with the EDS data type (numbers in decimal and hex, VISIBLE_STRING as text, other types as hex bytes), or the abort code with its CiA 301 text. When the runtime allows changes, the panel SHALL also write a value encoded from the EDS type after a range check, warning before writing an object the plugin configures itself or one owned by an SDO variable; and the node SHALL have NMT buttons (start, stop, pre-operational, reset node, reset communication), with confirmation for stop, pre-operational and the resets, since each of those holds or interrupts the node. When the runtime does not allow changes, write and NMT controls SHALL be shown disabled with the reason.

#### Scenario: Read the serial number
- **WHEN** the user reads 0x1018 subindex 4 of node 3
- **THEN** the panel shows the serial number in decimal and hex

#### Scenario: Write blocked
- **WHEN** the runtime's `allow_changes` is false
- **THEN** the write button and NMT buttons are disabled and say that online changes are not allowed in this configuration

#### Scenario: Pre-operational asks first
- **WHEN** the user clicks Pre-operational for node 2
- **THEN** a dialog says the node's PDOs stop until it is started again, with Cancel as the default, and nothing is sent until the user confirms

### Requirement: Scan the bus and add nodes
The configurator SHALL offer a scan page that runs a network scan through the runtime, shows progress, and lists each found device with node ID, vendor ID (with the vendor name when the EDS gives it), product code, revision, serial number, device name and its match against the config. For each device the page SHALL look for EDS files whose `[DeviceInfo]` VendorNumber and ProductNumber match, in the project's `canworks/` folder and in an optional EDS library folder set in the configurator's settings, preferring an exact RevisionNumber match. A not-configured device with a matching EDS SHALL be addable as a node with that node ID and EDS (imported into `canworks/` as an EDS import would), with an option to also set its identity check from the scanned values; a device without a matching EDS SHALL offer to pick an EDS file. Adding a node from the scan page SHALL open the new node's page with its name field focused, as "Add node from EDS…" does, and the message bar SHALL offer a way back to the scan results, which SHALL be kept. A "configured, different device" result SHALL show the differing fields side by side. Added nodes SHALL be saved only when the user saves.

#### Scenario: Add a found sensor
- **WHEN** the scan finds node 40 (vendor 0x000000AB, product 0x00001234) not configured, and the EDS library folder has an EDS with those numbers
- **THEN** the page offers that EDS, and adding it creates node 40 with that EDS, no PDO entries yet, and the project unchanged until save

#### Scenario: Unknown device
- **WHEN** the scan finds a device whose vendor and product match no EDS
- **THEN** the page shows its identity and offers to pick an EDS file

#### Scenario: Added node opens
- **WHEN** the user picks an EDS file for the unknown device at node 41
- **THEN** node 41's page opens with the name field focused, and the message bar says the node was added with a link back to the scan, whose results are still listed

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
The Problems pane and the messages next to fields SHALL name the place of a problem in the user's terms (node ID and name, PDO kind and number, object index and subindex, SDO variable name) and SHALL NOT show the internal config path (such as `nodes[2]: tx_pdos[1]: entries[0]:`). Selecting a problem SHALL still move to and highlight its field. The same wording SHALL be used wherever the configurator shows a check message: the Trace view's and Frame lab's "decoding without the config's PDOs" notes, the message bar and dialogs. No message shown on the page SHALL contain a filesystem path of the config or project, except where the path itself is the subject (the folder browser, the mode badge, the new-project dialog). An empty config SHALL be reported as "No nodes yet. Add a node from its EDS, or turn on Online access for a scan-only configuration." rather than as a schema error. An unexpected server error SHALL be shown as one sentence that points at the configurator's terminal, where the details are logged. The deploy tool's command-line messages are unchanged.

#### Scenario: Type does not fit the location
- **WHEN** node 5 (rtd) maps UNSIGNED8 object 0x6150:1 in TPDO 2 to `%IW320`
- **THEN** the Problems pane shows "Node 5 rtd, TPDO 2, 0x6150:1: type UNSIGNED8 (8 bit) does not fit location %IW320 (16 bit)" and clicking it scrolls to that entry's location field

#### Scenario: Trace note without a path
- **WHEN** the config has a type-does-not-fit error and the user opens a trace file
- **THEN** the Trace view's note reads "Decoding without the config's PDOs: Node 5 rtd, TPDO 2, 0x6150:1: type UNSIGNED8 (8 bit) does not fit location %IW320 (16 bit)" with no file path

#### Scenario: New config
- **WHEN** the user creates a new standalone config
- **THEN** the only problem reads "No nodes yet. Add a node from its EDS, or turn on Online access for a scan-only configuration."

### Requirement: Narrow window layout
Below 1000 px the page SHALL keep the problems in view: the node and view list SHALL become a compact bar at the top, and the Problems pane SHALL become a strip under the header showing the problem count, which opens the list. A node's error count SHALL stay next to the node's name.

#### Scenario: Problems at 900 px
- **WHEN** the window is 900 px wide and the config has 4 errors
- **THEN** the strip under the header reads "4 problems" without scrolling, and opening it lists them

### Requirement: Export DCF files
Each node's page SHALL have an "Export DCF" action next to "Remove node", and the header's Export menu SHALL offer "All DCFs" and, while a node page is open, "This node's DCF". The node list item SHALL carry no action of its own: clicking anywhere on it opens the node and nothing else. Both SHALL run the `canopen-dcf-export` export on the config as currently shown on the page, saved or not, and offer the result as a browser download: `node_<id>.dcf` for one node, `<config folder name>_dcf.zip` holding every `node_<id>.dcf` for all. When the config has errors or a DCF fails validation, the configurator SHALL download nothing and SHALL show the messages in the Problems pane, replacing the pane's current list rather than adding to it, so the problem count stays the number of distinct problems. The actions SHALL NOT write any file in the project or config folder.

#### Scenario: Export one node
- **WHEN** the config is valid and the user clicks "Export DCF" on node 23's page
- **THEN** the browser downloads `node_23.dcf` and no file under the project changes

#### Scenario: Unsaved change is exported
- **WHEN** the user changes node 23's heartbeat to 200 ms without saving and exports it
- **THEN** the downloaded DCF has `ParameterValue` 200 on 0x1017

#### Scenario: Validation failure
- **WHEN** a DCF fails validation
- **THEN** nothing is downloaded and the Problems pane names the node, the DCF section and the key

#### Scenario: Clicking a node item never exports
- **WHEN** the user clicks the middle of "5 rtd" in the node list, with the pointer resting on it
- **THEN** node 5's page opens, no download starts and the Problems pane is unchanged

#### Scenario: Failed export keeps the count
- **WHEN** the config has 4 errors and the user runs "All DCFs" from the Export menu
- **THEN** nothing is downloaded and the Problems pane still lists 4 problems, not 8

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

### Requirement: New editor project from a standalone config
In standalone mode the page SHALL offer "New editor project" next to "move into project". It SHALL ask for a parent folder (prefilled with the home folder, as "move into project" does), a project name, the task interval (default `T#20ms`) and whether to enable the CANopen SDO blocks (unchecked by default), create the project as `canopen-editor-project` describes, and then switch to project mode on the new project. It SHALL require the config to be saved first and SHALL show the reason when creation is refused. The standalone folder SHALL be left unchanged.

#### Scenario: Create and switch
- **WHEN** the user has saved a standalone config in `~/canworks/rtd`, chooses "New editor project", picks `~/workspace` and the name `rtd-monitor`
- **THEN** `~/workspace/rtd-monitor` is created with the config in its `canworks/` folder and `main` declaring its I/O, and the page shows mode "project rtd-monitor" with every CANopen entry marked as declared

#### Scenario: SDO blocks enabled
- **WHEN** the user ticks "Enable CANopen SDO blocks" in the dialog
- **THEN** the project is created as with `--sdo-blocks`, and the page shows how to install the library when the creation output says it is missing

#### Scenario: Unsaved changes
- **WHEN** the config has unsaved changes
- **THEN** the page asks the user to save first and creates nothing

#### Scenario: Name taken
- **WHEN** `~/workspace/rtd-monitor` already exists
- **THEN** the dialog says the folder exists and stays open, nothing is written and the page stays in standalone mode

### Requirement: LSS node settings
For each node the configurator SHALL show an "Assign node ID by serial number (LSS)" checkbox, saved as `lss.assign`, and a "Store node ID in the device" checkbox, saved as `lss.store`, which SHALL be unticked for a new node and disabled while the first is unticked. Unticked boxes SHALL be left out of the saved node, and an `lss` object with nothing in it SHALL be left out. While "Assign" is ticked the node's serial number field SHALL be required, `reset_communication` SHALL not be selectable as off, and the page SHALL say that the master gives the device this node ID at every start. When the node's EDS does not say `LSS_Supported=1`, the page SHALL show a warning next to the checkbox and still allow it.

#### Scenario: Turn on LSS for a node
- **WHEN** the user ticks "Assign node ID by serial number (LSS)" for node 12, enters serial number 0x1234 and saves
- **THEN** node 12 has `"lss": {"assign": true}` and `"serial_number"` 0x1234 (kept as typed, like the other identity fields), and no `lss.store`

#### Scenario: Assign without a serial number
- **WHEN** "Assign" is ticked for node 12 and its serial number is empty
- **THEN** saving is refused and the serial number field says it is needed for LSS

### Requirement: Unconfigured devices in the online view
When the runtime allows changes, the online view SHALL offer an "Unconfigured devices" panel that finds a device without a node ID through the runtime, shows its vendor ID (with the vendor name when an EDS gives it), product code, revision and serial number and a matching EDS when one is found (as on the scan page), and offers "Set node ID" and "Set bit rate" for it. Both dialogs SHALL have a "Store in the device" checkbox that is unticked each time the dialog opens. "Set node ID" SHALL suggest the lowest node ID that is neither configured nor the master's and SHALL offer, after success, to add the device as a node with that ID and EDS (as the scan page adds a found device), with `serial_number` and `lss.assign` set. "Set bit rate" SHALL say before sending that the device switches after its next power cycle and that the adapter bit rate must be changed to match. When the runtime does not allow changes the panel SHALL be shown disabled with the reason.

#### Scenario: Commission a new sensor
- **WHEN** the user finds a device without node ID, sets node ID 40 with "Store in the device" ticked, and accepts adding it as a node
- **THEN** the runtime sets and stores node ID 40, and the project gets node 40 with the matching EDS, the device's serial number and `"lss": {"assign": true}`, unsaved until the user saves

#### Scenario: Store unticked by default
- **WHEN** the user opens "Set node ID" a second time after storing once
- **THEN** the "Store in the device" checkbox is unticked

### Requirement: Use a scanned device for a node
On the scan page, a found device with a serial number SHALL offer "Use for node…", listing the configured nodes whose EDS vendor ID and product code match the device. Picking a node SHALL set that node's `serial_number` from the device and tick its `lss.assign`, unsaved until the user saves, and SHALL say that the device gets the node's ID at the next PLC start.

#### Scenario: Replacement device
- **WHEN** node 12 is configured for a valve with serial 0x1234, the scan finds a valve with the same vendor ID and product code at node 5 with serial 0x5678, and the user picks "Use for node 12"
- **THEN** node 12 gets `serial_number` 0x5678 and `"lss": {"assign": true}`, and the page says the device becomes node 12 at the next start

### Requirement: Trace view
The side bar SHALL have a Trace view next to the online view and the scan page. Opening, viewing and exporting trace files SHALL work without a runtime; recording SHALL need online access set up for the project. It SHALL offer start and stop, capture filters, error frames, clear, "Save to traces folder" (on this PC), open and "Download" (a file in the chosen format), the two format choices labelled apart; a scrolling decoded trace and a per-identifier table; display filters by node, frame kind (NMT, SYNC, EMCY, heartbeat, SDO, PDO, LSS, error, other), identifier range and text; the graph and trigger settings; and the statistics. Times SHALL be shown relative to the trace start or as UTC clock time. When the runtime's plugin does not know the trace operations, the view SHALL say that the plugin is too old for traces. Clear and Start SHALL say that the current recording is lost unless it was saved or downloaded, with Cancel as the default; closing the page or the folder with an unsaved recording SHALL ask first. The frame list SHALL move its selection with the arrow keys, Home, End, Page Up and Page Down, and the view's tabs SHALL follow the page's tab pattern (see "Keyboard access and announcements").

#### Scenario: Start a trace
- **WHEN** online access is set up and the user opens Trace and presses Start
- **THEN** decoded frames appear and the statistics update while the bus runs

#### Scenario: Filter display
- **WHEN** the user shows only node 23 and frame kind SDO
- **THEN** the trace lists only SDO requests and responses of node 23, and recording of other frames continues

#### Scenario: Old plugin
- **WHEN** the runtime's plugin answers the trace start as an unknown operation
- **THEN** the view says the plugin on the runtime is too old for traces and how to update it

#### Scenario: Open a file without a runtime
- **WHEN** the project has no online access and the user opens a candump log file in the Trace view
- **THEN** the frames are shown decoded and can be graphed and exported, and Start says online access must be set up

#### Scenario: Works offline
- **WHEN** the PC has no internet access
- **THEN** the Trace view and its graphs load and work

#### Scenario: Clear asks
- **WHEN** a recording of 3,000 frames has not been saved and the user clicks Clear
- **THEN** a dialog says the 3,000 frames are lost unless saved or downloaded, Cancel is the default, and Enter keeps the recording

### Requirement: Object dictionary view
In the online view each configured node, and each scanned node with a matched or picked EDS, SHALL have an object dictionary tab: a tree of every object in its EDS grouped as communication (0x1000-0x1FFF), manufacturer (0x2000-0x5FFF) and profile (0x6000-0x9FFF), with index, subindex, name, data type, access, EDS default and device value. Each object SHALL be one row: a VAR object with its value in that row, an ARRAY or RECORD object as a foldable row with its sub-entries below it, each sub-entry named by its own name without the object's name in front. Groups and objects SHALL start folded, except that a search or filter unfolds the groups and objects that hold a match. The tab SHALL use the full width of the online view, and long names SHALL wrap so that the row's buttons and watch box always stay inside the view without sideways scrolling. A search box SHALL filter by name or index.

#### Scenario: Browse node 3
- **WHEN** the user opens the object dictionary tab of node 3
- **THEN** the tree shows the objects from node 3's EDS in three folded groups, values empty until read

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
When the runtime allows changes, writable entries in the object dictionary tab SHALL be editable in place, using the SDO panel's write with its range check and its warnings for entries the configuration writes or an SDO variable owns. The editor SHALL show the entry's EDS LowLimit and HighLimit when the EDS has them, and a value outside them SHALL need a confirmation before it is written. The value shown SHALL be read back after the write. When changes are not allowed, entries SHALL be read-only with the reason shown.

#### Scenario: Edit a parameter
- **WHEN** the runtime allows changes and the user changes 0x6110 subindex 1 of node 3 to 30
- **THEN** the value is written, read back and shown as 30

#### Scenario: Value outside the EDS limits
- **WHEN** the EDS gives 0x2010 subindex 1 a HighLimit of 100 and the user enters 150
- **THEN** the editor says the EDS allows 0 to 100 and writes only after the user confirms

#### Scenario: Read-only runtime
- **WHEN** the runtime's `allow_changes` is false
- **THEN** no entry is editable and the tab says online changes are not allowed

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
Next to the search box the object dictionary tab SHALL offer filters that can be combined with the search: changed from the EDS default, writable, set by the configuration or an SDO variable, mapped in a PDO, not readable (an entry whose last read failed), and different in the last compare. A filter that needs values SHALL apply to the entries read so far.

#### Scenario: Only changed values
- **WHEN** the user has read all of node 3 and picks "changed from default"
- **THEN** only the entries whose value differs from the EDS default are shown, with their objects and groups unfolded

#### Scenario: Filter and search together
- **WHEN** the user picks "writable" and types `sensor`
- **THEN** only writable entries whose name or index contains "sensor" are shown

### Requirement: Value formats in the object dictionary view
Each numeric entry SHALL be shown in decimal by default and SHALL let the user switch it to hex or binary, the choice kept for that entry while the page is open. INTEGER entries in hex or binary SHALL show their two's-complement bits. For a known bit-field object (at least 0x1001 error register, 0x1002 manufacturer status register, 0x6040 controlword and 0x6041 statusword of CiA 402) the entry SHALL offer a bit view naming each set bit; the bit names SHALL come from a table in the configurator, not from the EDS.

#### Scenario: Hex view
- **WHEN** 0x6110 subindex 1 reads 30 and the user switches it to hex
- **THEN** it shows `0x001E`

#### Scenario: Statusword bits
- **WHEN** 0x6041 of a CiA 402 drive reads 0x0237 and the user opens its bit view
- **THEN** the bits ready to switch on, switched on, operation enabled, voltage enabled, quick stop and remote are shown as set

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
The node settings SHALL offer a "CiA 402 axis" switch with the three scaling fields and a "Cyclic synchronous" switch with an optional interpolation period, writing the node's `axis` object, and SHALL show the axis checks' errors and warnings with the node. The switch SHALL be offered for every node and SHALL say when the EDS does not report device profile 402. Turning it on SHALL require a status bit and SHALL suggest one when the node has none.

#### Scenario: Turn on
- **WHEN** the user turns on "CiA 402 axis" for node `drive`, which has a status bit, and saves
- **THEN** the saved config has `"axis": {}` on node `drive` (scaling left at the defaults is not written)

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
The **Bus and master** page SHALL have a **Network** choice, **Real** or **Simulated** (`adapter.simulate`), and each node SHALL have a **Simulated** switch (the node's `simulate`), shown on the node and as a badge in the node list, with **Simulate all** and **Simulate none** buttons. On a simulated network a node switched off SHALL be shown as absent. Choosing a simulated network SHALL keep the adapter settings. Simulating anything SHALL turn on online access with **Allow changes** when it is off (saying so), and every page SHALL show a banner naming what is simulated (the network, or the simulated node IDs on the real network) and that the configuration must not be uploaded to a machine as it is.

#### Scenario: Simulated network
- **WHEN** a user chooses **Simulated** network in a project with online access off
- **THEN** the saved config has `adapter.simulate: true`, its adapter settings unchanged, online access on with **Allow changes**, every node shows the **Simulated** badge, and every page shows the banner

#### Scenario: One device on the real network
- **WHEN** a user keeps the **Real** network and switches on **Simulated** for node 5 only
- **THEN** the saved config has `"simulate": true` on node 5 only and the banner says node 5 is simulated on the real network

### Requirement: Simulation view
The configurator SHALL have a **Simulation** view that connects to the runtime's simulated devices (or to a standalone simulator by address) and shows, per simulated device, whether it runs on a simulated or a real network, its NMT and power state, injected faults and the objects it carries in PDOs with live values, refreshed at least twice a second. A user SHALL be able to set and override values (switches for BOOLEAN and bits, sliders between the EDS limits for numbers), give and edit value sources and expressions with checking as they type, inject and clear every fault the simulator offers from buttons, and add extra devices. Changes made here SHALL be saveable to `simulation.json`. With several networks, the view SHALL show and edit the network chosen in its network picker, and saving SHALL write that network's section of a version 2 file, keeping the other sections; a version 1 file of a several-network config SHALL be offered for conversion to version 2 before the first save. Without **Allow changes** the view SHALL be read-only and say why.

#### Scenario: Move a sensor value by hand
- **WHEN** a user drags the slider of node 5's 0x7130:1 to 900 in the Simulation view
- **THEN** the simulated device holds 900, the PLC sees it in the mapped input, and the slider shows an override that **Release** removes

#### Scenario: Save behaviour
- **WHEN** a user gives 0x6401:1 a sine in the view and presses **Save to simulation file**
- **THEN** `canworks/simulation.json` has that source and the next simulated start uses it

#### Scenario: Save one network's section
- **WHEN** the config has networks `io` and `motion`, the picker shows `motion`, and the user saves a drive setting for node 4
- **THEN** `simulation.json` is version 2, its `motion` section has the setting and its `io` section is unchanged

### Requirement: Scenarios in the configurator
The Simulation view SHALL list the scenarios of the simulation file, let a user create and edit them as a list of steps with checking, start and stop them, and show the running step, the time and the result of each expect, with failed expects showing the condition and the value seen.

#### Scenario: Run a scenario
- **WHEN** a user starts the scenario `sensor-break` from the view
- **THEN** the view shows each step as it runs and the scenario's result when it ends

### Requirement: Network bar
The configurator SHALL show a network bar above the Bus and master section, with one tab per network and buttons to add, rename and remove a network. Each tab SHALL hold that network's Bus and master settings and its node list. With one network the bar SHALL show only the add button, so a single-network page looks as before.

#### Scenario: Add a second network
- **WHEN** the user opens a config with one network on `can0` and presses Add network
- **THEN** a second tab appears with an empty node list and an adapter interface the user must fill in, and the first tab is named `can0`

#### Scenario: Remove a network with nodes
- **WHEN** the user removes a network that has nodes
- **THEN** the page asks for confirmation naming the network and its number of nodes before removing it

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

### Requirement: Network picker in online, scan and trace views
The online view, the scan page and the trace view SHALL each have a network picker when the runtime reports more than one network, and SHALL show and act on the picked network only. The picker SHALL start on the network whose tab is open.

#### Scenario: Online view of the second network
- **WHEN** the runtime runs `io` and `drives` and the user picks `drives` in the online view
- **THEN** the view shows `drives`' bus state and nodes, and SDO, NMT, parameter and object dictionary actions go to `drives`

#### Scenario: Scan adds to the picked network
- **WHEN** the user scans `drives` and adds a found device as a node
- **THEN** the node is added to the `drives` tab

### Requirement: Exports per network in the configurator
The configurator's DBC export SHALL export the network of the open tab. Its DCF export SHALL export the open tab's nodes, or every network into per-network folders when the user chooses all.

#### Scenario: DBC of the open tab
- **WHEN** the `drives` tab is open and the user exports a DBC file
- **THEN** the file describes only `drives`' nodes and is named after the network

### Requirement: Network role switch
Each network tab SHALL have a role, master or slave. Switching a network with nodes to slave SHALL ask before dropping the master settings and nodes; switching back SHALL start with an empty master network.

#### Scenario: Switch to slave
- **WHEN** the user sets a new network's role to slave
- **THEN** the tab shows the adapter settings and the slave device page instead of the master settings and node list

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

### Requirement: USB adapter as online target
The online access settings SHALL offer three targets: a runtime host, the local simulator runtime, and a USB adapter on this PC. For a USB adapter the page SHALL offer the adapter type, a port picked from the adapters found on this PC (with a refresh button) or typed, the bit rate (defaulting to the current network's `adapter.bitrate`), and an "Allow changes" checkbox that starts off for every connection and is not saved. The adapter type, port and bit rate SHALL be kept in the configurator's settings on this PC per project folder, never in the project. No token SHALL be needed for an adapter.

#### Scenario: Connect to a CANable
- **WHEN** the user picks "USB adapter", the found port `COM5` (slcan) and 250 kbit/s, and connects
- **THEN** the online view opens on that adapter, the banner says "USB adapter slcan:COM5, 250 kbit/s, read-only", and the project folder is unchanged

#### Scenario: Different bit rate than the config
- **WHEN** the network's `adapter.bitrate` is 500000 and the user types 250
- **THEN** the connection is made at 250 kbit/s and the banner shows both rates

### Requirement: Online pages on a USB adapter
On a USB adapter the Online view, scan page, object dictionary view with watch, Parameters actions and Trace view SHALL work as on a runtime, through the local backend. Fields the local backend does not report (boot result, retry, hold, SDO variable values, SYNC counters) SHALL be hidden, and the Simulation view and slave and gateway status SHALL be hidden. When another master is detected, the banner SHALL say so, and LSS buttons SHALL ask whether to go ahead anyway before sending with `force`. Write, NMT, LSS and restore controls SHALL be disabled with the reason while "Allow changes" is off.

#### Scenario: Scan from the PC
- **WHEN** the user runs a scan on a USB adapter target with a project open
- **THEN** found devices are listed and matched against EDS files and the config as on a runtime, and "Add as node" works

#### Scenario: PLC still running
- **WHEN** the user clicks LSS Find on a USB adapter while a PLC master runs on the bus
- **THEN** the page warns that another master is active and sends nothing unless the user confirms

### Requirement: Commission a device without a config
The configurator's start page SHALL offer "Commission a device", which opens the online pages on a USB adapter without any project or config: scan, object dictionary view (EDS from the scan match in the EDS library, or picked by the user), LSS, Parameters (backup, compare, restore, store) and Trace. "Add as node" SHALL be offered only when a config is open; instead the mode SHALL offer "Add to a config…", which picks a project or standalone config folder and opens it with the device added as an unsaved node (node ID, EDS imported, serial number, and LSS assignment ticked when the node ID was set by LSS in this session). The mode SHALL show a Steps panel listing Bit rate, Find the device, Node ID and bit rate, Identity and EDS, Write configuration, PDO test, Store, Verify after power cycle and Back up; each step SHALL open its panel and show done or skipped with a one-line result, steps SHALL be possible in any order or skipped, and none SHALL run by itself. In this mode the page SHALL show no config editing: no Project or Export menu, no Save, no Problems pane, and a side bar with only the online pages (Online, Scan the bus, Trace, Frame lab), so nothing suggests a config is being edited.

#### Scenario: New device on the desk
- **WHEN** the user opens "Commission a device", connects to a CANable at 250 kbit/s with "Allow changes" on, finds an unconfigured device with LSS and gives it node ID 12
- **THEN** a scan lists node 12, and nothing was stored on the device unless the user ticked "store"

#### Scenario: Nothing to save
- **WHEN** the user opens "Commission a device"
- **THEN** the header shows the mode badge, the theme choice and Close only, the side bar lists Online, Scan the bus, Trace and Frame lab, and no problem is reported

#### Scenario: Guided commissioning
- **WHEN** the user detects the bit rate, gives the device node ID 12 by LSS, writes a configuration from a DCF and backs it up
- **THEN** the Steps panel marks Bit rate, Node ID and bit rate, Write configuration and Back up as done with their results, and Store as not done

#### Scenario: Carry the device into a config
- **WHEN** the user presses "Add to a config…" after setting node ID 12 by LSS and picks a standalone config folder
- **THEN** that config opens with node 12 added as an unsaved node with the device's EDS, serial number and LSS assignment ticked

### Requirement: Send frames from the Trace view
The Trace view SHALL have a Send panel for the picked network with the identifier (hex), extended and remote options, a DLC for remote frames, up to 8 data bytes, and single or cyclic sending with a period and an optional count. It SHALL send through online access with `send_frame` and stop jobs with `send_frame_stop`, list the running cyclic jobs with their sent counts and a Stop for each, and list the last 20 frames sent. A frame selected in the trace SHALL be offered as "Send this frame", filling the panel. When online access has no `allow_changes`, the panel SHALL be disabled and say why. When the plugin refuses a frame because `force` is needed, the configurator SHALL show the plugin's reason in a confirmation and resend with `force` only when the user confirms. Leaving the Trace view or closing the page SHALL stop the page's cyclic jobs.

#### Scenario: Single frame while recording
- **WHEN** a trace is recording and the user sends 0x60A with eight data bytes
- **THEN** the frame appears in the trace as Tx and in the panel's sent list

#### Scenario: Force needs confirmation
- **WHEN** the user sends on 0x205, which is RPDO1 of node 5
- **THEN** a confirmation quotes "0x205 is RPDO1 of node 5" and nothing is sent unless the user confirms

#### Scenario: No changes allowed
- **WHEN** the config's online access has `allow_changes` off
- **THEN** the Send panel is disabled and says that sending needs Allow changes

### Requirement: Detect the bit rate from the Scan page
The Scan the bus page SHALL have a "Detect bit rate" action for the picked network. Before starting it SHALL warn that CANopen on that network stops during the sweep and the nodes boot again afterwards, and ask for confirmation (with `force` when the plugin says a node is OPERATIONAL). While it runs it SHALL show the rate being listened to and the per-rate counts so far; when finished, the verdict and a table of the rates with frame, error frame and identifier counts. On `detected` with a rate different from the network's `adapter.bitrate`, it SHALL offer "Use N kbit/s", which sets the network's bit rate on the page without saving. It SHALL show no such button for `silent`, `ambiguous` or `failed`, and SHALL show the plugin's reason for `failed` and refusals.

#### Scenario: Unknown device's rate
- **WHEN** the tab's bit rate is 500 kbit/s and the sweep finds 250 kbit/s
- **THEN** the page shows `250 kbit/s detected` and a "Use 250 kbit/s" button, and clicking it sets the bit rate field to 250 kbit/s with the page marked unsaved

#### Scenario: Silent bus
- **WHEN** the sweep finds no frames
- **THEN** the page says the bus was silent, that a single device on the bus needs a second device or adapter that acknowledges its frames, and suggests powering a device on or resetting it during the sweep

### Requirement: Frame inspector panel
In the Trace view, selecting a frame SHALL open an inspector panel with the four layers of the `canopen-frame-explain` model: meaning, identifier bits split into function code and node ID, a data grid with one row per byte (most significant bit on the left, CANopen bit number on each bit, each bit coloured by its field), the field list with values and working, and the wire strip with framing, stuff bits marked, the bus level line and the timing figures. Pointing at or focusing a bit or field SHALL show its explanation in a box that stays in view and SHALL highlight the same bits in every layer (a data bit in the grid and on the wire, a field's bits in the grid). Every bit SHALL be reachable with the keyboard. The panel SHALL follow the selected frame when the user moves through the list with the arrow keys, and SHALL offer the frame's SDO conversation, SYNC cycle or boot story where one exists. It SHALL work on opened trace files without a runtime, offline, in light and dark themes and at phone width.

#### Scenario: Point at a data bit
- **WHEN** the user points at bit 2 of byte 0 of node 5's TPDO1, whose first byte is mapped to `%IB100`
- **THEN** the box names the bit, its value, "bit 2 of `%IB100`", the object and the wire bit number, and that bit is highlighted in the grid and on the wire strip

#### Scenario: Keyboard
- **WHEN** the user tabs into the data grid and moves with the arrow keys
- **THEN** each focused bit is explained in the box

### Requirement: Sequences in the Trace view
The Trace view SHALL have a Sequences tab listing SDO conversations and boot stories with filters by node and result, and a SYNC cycle timeline with stepping and a jump to the slowest cycle, as the `canopen-bus-trace` capability describes. Sequence diagrams and timelines SHALL be drawn without a third-party library, and every step SHALL open its frame in the inspector panel.

#### Scenario: From a conversation to the frame
- **WHEN** the user clicks the abort arrow of an SDO conversation
- **THEN** the inspector panel opens on that abort frame with its abort code explained

### Requirement: Frame lab view
The side bar SHALL have a Frame lab view that works without a runtime and without a trace. It SHALL accept a frame typed as identifier and data or pasted in candump syntax, offer example frames generated from the open configuration (saved or not) and the frame builder of the `canopen-frame-explain` capability, and show the result in the inspector panel at the network's bit rate, with a bit rate picker. It SHALL have an arbitration demo: two frames chosen by the user are shown sent at the same time bit by bit, with each sender's bit, the bus level and the bit where the sender of a recessive bit reads a dominant level and stops, and which frame wins. The Frame lab SHALL never send anything to the bus and SHALL say so, and none of its controls SHALL be labelled as sending (the arbitration demo's button is "Run both").

#### Scenario: Paste a frame
- **WHEN** the user pastes `705#7F` in the Frame lab
- **THEN** it is explained as node 5's heartbeat in Pre-operational

#### Scenario: Arbitration
- **WHEN** the user picks node 5's TPDO1 (0x185) and node 3's TPDO1 (0x183) for the arbitration demo
- **THEN** the demo shows both identical up to identifier bit 2, node 3's frame driving it dominant there, node 5's sender stopping, and 0x183 winning

#### Scenario: Example frames follow the config
- **WHEN** the user adds node 7 without saving and opens the Frame lab
- **THEN** the example frames include node 7's boot-up, heartbeat, SDO read of 1018h:01 and its PDOs

### Requirement: Keyboard access and announcements
Everything the pointer can do on the page SHALL be possible with the keyboard: the node list and the problem list SHALL be made of buttons in the tab order, the active node marked as current; rows that open something (online nodes, scanned devices, simulated devices) SHALL be focusable and open on Enter or Space; tabs (Trace, the online node's Overview / Object dictionary / Parameters, Simulation) SHALL be a tab list with the selected tab marked, each tab naming its panel, and Left, Right, Home and End moving between them; every focused control SHALL show a visible focus ring in the accent colour. Progress lines (reading all, backup, scan) and the problem count SHALL be polite live regions. Landmarks SHALL not be nested complementary regions, heading levels SHALL not skip, and every table column with only buttons SHALL have a header text for assistive technology.

#### Scenario: Open a node with the keyboard
- **WHEN** the user presses Tab from the Save button
- **THEN** focus moves through the node list, and Enter on "5 rtd" opens node 5's page

#### Scenario: Problems by keyboard
- **WHEN** the user tabs into the Problems pane and presses Enter on the first problem
- **THEN** the field with that problem gets focus

#### Scenario: Tabs by keyboard
- **WHEN** focus is on the Trace view's "Frames" tab and the user presses Right
- **THEN** "Identifiers" is selected and its panel shows

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
The header SHALL show, left to right: the title and mode badge, the theme choice, Reload from disk, Close, a Project menu (Move into project…, New editor project…; standalone mode only), an Export menu (All DCFs, This node's DCF, DBC with its SDO-frames choice, Documentation) and Save as the only primary button. Menus SHALL open on click or Enter, close on Escape or a click elsewhere, and SHALL be navigable with the arrow keys. The header SHALL fit on one line at 1000 px.

#### Scenario: Export a DBC from the menu
- **WHEN** the user opens Export, picks "SDO: configured objects" and clicks DBC
- **THEN** the DBC file downloads as before and the menu closes

#### Scenario: One line
- **WHEN** the window is 1000 px wide in standalone mode
- **THEN** the header's actions are on one line

### Requirement: Node page sections
A node page SHALL have a section index under its heading that stays in view while the page scrolls, with an entry per section (Node, Supervision, Emergency, Axis, Advanced, Inputs, Outputs, Startup SDO writes, SDO variables), the current section marked as the page scrolls and each entry scrolling to its section. Sections that can be empty (Startup SDO writes, SDO variables) SHALL be collapsed when empty, with their count and their add action visible in the summary, and open when they have entries or a problem. Objects SHALL be mapped from within the PDO block they go into ("Add entry…" per PDO, listing that direction's mappable objects), with "Map all" kept for device-mapped PDOs. Editing the node's name SHALL update the side bar as the user types, and adding a node SHALL put focus in its name field.

#### Scenario: Jump to SDO variables
- **WHEN** the user clicks "SDO variables" in the section index of a node with two PDOs
- **THEN** the page scrolls to that section and the index marks it

#### Scenario: Add an entry from the PDO
- **WHEN** the user clicks "Add entry…" on TPDO 1 and picks 0x6150:1
- **THEN** 0x6150:1 is added to TPDO 1 with a suggested location, and the picker lists only input-direction objects

### Requirement: Busy states and the Save button
Save, every export, Move into project, New editor project and Add node from EDS SHALL disable their control and show what is running ("Saving…", "Exporting…", "Adding…") until the request completes, and a second click meanwhile SHALL do nothing. The Save button SHALL read "Saved" and be disabled when the draft equals the file, "Save" when the draft is dirty, "Save (overlaps allowed)" when the overlap override is on; when the draft has errors it SHALL be disabled with a tooltip giving the error count, and the count SHALL be shown in the Problems pane rather than in the button's label.

#### Scenario: Double click on Save
- **WHEN** the user clicks Save twice while the first save is still running
- **THEN** one save request is made and the button reads "Saving…" until it returns

#### Scenario: Clean draft
- **WHEN** the file on disk equals the draft
- **THEN** the button reads "Saved" and is disabled

### Requirement: Accessibility check in the browser tests
The browser layout test SHALL run an automated accessibility audit (WCAG 2.1 A and AA rules) on every view it opens, in both themes, and SHALL fail on any finding of critical or serious impact, naming the rule, the element and the view. Text SHALL meet the 4.5:1 contrast ratio (3:1 for large text) in both themes, including state colours and the frame inspector's field tints, and interactive controls SHALL be at least 24 px tall.

#### Scenario: Regression caught
- **WHEN** a change adds a button without an accessible name to the online view
- **THEN** the layout test fails naming the rule and the button

#### Scenario: State colours
- **WHEN** the online view shows a node as OPERATIONAL in the light theme
- **THEN** the state text's contrast against its background is at least 4.5:1

### Requirement: Write configuration dialog
A node's Parameters tab SHALL have "Write configuration…" (also in the Commission a device steps), enabled only with Allow changes. It SHALL take a DCF file or a node of a config folder (the open config's own node by default when the target is not a runtime that configures it), show the plan from `canopen-device-commissioning` (writes with source value, device value and differs or same, PDO sequences grouped, communication writes marked, left-out entries with reasons, identity and node ID checks), and write only after the user confirms. "Hold in PRE-OPERATIONAL while writing" SHALL start ticked; "Restore defaults first" and "Store on device afterwards" SHALL start unticked every time the dialog opens. It SHALL run in the configurator like restore, with progress and Cancel, and show the result with the read-back verdict. "Verify" in the same dialog SHALL compare without writing.

#### Scenario: Plan before writing
- **WHEN** the user picks node5.dcf in Write configuration
- **THEN** the dialog lists the planned writes with both values, writes nothing until the user confirms, and both store and restore-defaults ticks are off

### Requirement: Restore defaults button
The Parameters tab SHALL have "Restore defaults…" next to "Store on device…", offered only when the EDS has 0x1011 and enabled only with Allow changes. It SHALL ask first, offer "Reset the node afterwards" (ticked), and show whether the device accepted it.

#### Scenario: Restore defaults asks
- **WHEN** the user presses Restore defaults… on node 5
- **THEN** a confirmation names node 5 and 0x1011, and nothing is written unless the user confirms

### Requirement: PDO test tab
On a USB adapter target, each node SHALL have a "PDO test" tab. It SHALL load the node's PDO layout from the open config when the node is configured, otherwise from the device, and show TPDOs with live decoded values, periods and counts, and RPDOs with an input per entry and Send. It SHALL offer NMT Start for the node, and SYNC with a period (off by default). Every control SHALL be disabled without Allow changes and say why. When another master is detected the page SHALL ask before using `force`. Leaving the tab or closing the page SHALL stop the test and the SYNC. On a runtime target the tab SHALL not be shown, because the PLC runs the PDOs there.

#### Scenario: Set an output
- **WHEN** the user types 15 in RPDO1's 0x6200:01 input and presses Send
- **THEN** the frame is sent and the RPDO's sent count goes up by one

### Requirement: Lone device in Detect
The adapter connect box's Detect and the Scan page's Detect bit rate on a USB adapter SHALL have "Only this device is on the bus", unticked by default. Ticked, it SHALL ask for confirmation that nothing else is on the bus and that the adapter's error frames will reach it at wrong rates, need Allow changes on the Scan page, and run the lone-device sweep with the LSS probe. A `silent` result without it SHALL suggest ticking it when a single device is on the bench.

#### Scenario: Bench device found
- **WHEN** the only device runs at 125 kbit/s, the user ticks "Only this device is on the bus", confirms and presses Detect
- **THEN** the form shows `125 kbit/s detected` and selects 125 kbit/s

### Requirement: Commissioning log
In Commission a device and on a USB adapter target, the configurator SHALL record every change made through the page in this session (SDO write, NMT, LSS set ID, set bit rate and store, write configuration, restore defaults, store) with UTC time, node, what was done and the result. "Save log" SHALL download `node<N>-commissioning-<time>.txt` with the device identity and EDS name at the top. The log SHALL not contain host names or tokens and SHALL not be written to any project.

#### Scenario: Save the record
- **WHEN** the user gave the device node ID 12, wrote a configuration and stored it, then pressed Save log
- **THEN** the file lists those three changes in order with their results
