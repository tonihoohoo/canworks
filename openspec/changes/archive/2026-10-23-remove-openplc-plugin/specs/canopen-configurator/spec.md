## RENAMED Requirements

- FROM: `### Requirement: The check refuses what the plugin refuses`
- TO: `### Requirement: The check refuses what the bridge refuses`

## MODIFIED Requirements

### Requirement: Project target
A project SHALL have one target: "OpenPLC" (default; OpenPLC Runtime through its Modbus master and the bridge), "Modbus bridge" or "CODESYS", chosen in a "Project target" field on the Project page (see "Network tree") and shown in the header, where the badge opens the Project page. No network's Bus page and no Modbus bridge page SHALL have the field. The target SHALL come from the config: a `bridge` object holding `openplc` makes it OpenPLC, any other `bridge` object Modbus bridge, a `codesys` object CODESYS. A config with neither (a config of the removed OpenPLC plugin) SHALL open read-only with one message saying the plugin is no longer supported, with **Switch to OpenPLC through Modbus**, which repacks the locations for the bridge, adds `"bridge": {"openplc": {}, "writers": ["127.0.0.1"]}` and removes what the bridge does not use (including `axis`, `sync_source`, `sync_cycles` and `scan_watchdog_ms`), as one undo step. Until the switch the page SHALL NOT save the config.

#### Scenario: Target shown
- **WHEN** the user opens a config with a `codesys` object
- **THEN** the Project page's Project target field and the header show CODESYS

#### Scenario: Plugin config opened
- **WHEN** the user opens a config with no `bridge` and no `codesys` object, whose master has `"sync_source": "plc_cycle"` and whose node `drive` has `axis`
- **THEN** the message offers Switch to OpenPLC through Modbus and Save is disabled; after the switch the config has `bridge.openplc`, no `sync_source` and no `axis`, timer SYNC is asked for in Problems, and one Undo restores the config as it was opened

### Requirement: Only what the target uses is shown
The page SHALL hide every field, table column, choice option, fieldset, node tab, tree entry, menu item, page and start-page action that the project's target does not use, as the relevance table of `canopen-config-contract` lists them, whether or not the config has a value for it, and SHALL NOT list, mark or ask about such values (Requirement: Settings the target does not use are left out on save). Hints, labels and page texts that differ between targets SHALL use the project target's wording: a bridge or CODESYS project SHALL NOT be told about the plugin, the Linux device, the PLC scan or PLC locations where they do not apply. The editor project's address scan line SHALL be shown for OpenPLC only. A section SHALL be hidden only when none of its controls is left, and a section whose settings the target does not use (the Emergency section for CODESYS) SHALL not be drawn. A node tab left with nothing SHALL say in one line that the target does not use its settings instead of staying blank. The same rules SHALL apply to all three targets. No target SHALL show a CiA 402 axis setting, a scan watchdog, SYNC from the PLC cycle or a Variable declarations page: they no longer exist.

#### Scenario: CODESYS project
- **WHEN** the project's target is CODESYS
- **THEN** the page shows no IEC location fields or column, status locations, SDO variables, EDS lint, simulated devices, raw CAN messages, gateway, Online access, Emergency section or OpenPLC Editor project actions, and the protocol choice offers only CANopen master

#### Scenario: Bridge project
- **WHEN** the project's target is Modbus bridge
- **THEN** the Project menu has no editor project actions and the Bus page's role hint says the bridge is the network's master

#### Scenario: OpenPLC project
- **WHEN** the project's target is OpenPLC
- **THEN** no Modbus bridge or CODESYS page, field or action is shown

#### Scenario: Leftover value
- **WHEN** a CODESYS project still has `on_plc_stop` set to `keep`
- **THEN** the field is hidden, nothing on the page or in Problems mentions it, and the next save leaves it out

#### Scenario: Leftover location in a CODESYS project
- **WHEN** a CODESYS project's node `dio` has one TPDO entry with `iec_location` `%IW100`
- **THEN** the node's PDO table has no PLC location column and the PDOs tab shows nothing about it

#### Scenario: Leftover simulate in a CODESYS project
- **WHEN** a CODESYS project's node has `simulate` set
- **THEN** the node has no Simulation tab and no simulated mark

#### Scenario: Supervision with the EDS's own settings in a CODESYS project
- **WHEN** a CODESYS project's node has no heartbeat or guarding settings (Method "EDS default") and the user opens its Supervision tab
- **THEN** the Method choice is shown, there is no Emergency section, and the tab is not blank

#### Scenario: Wording guard
- **WHEN** the browser tests open every page and node tab of a config with every setting set, once per target
- **THEN** no field the target does not use is visible, no node tab is blank, and no visible text uses another target's words (for CODESYS: the bridge, the Linux device, PLC location, an IEC address, OpenPLC), apart from the Project target field's help

### Requirement: Import an EDS
Adding a node SHALL start from an EDS file the user picks. The configurator SHALL check that it is a CiA 306 EDS the deploy tool accepts, store it under `canworks/` as UTF-8 (converting from Latin-1/CP1252 when it is not valid UTF-8) and refer to it by a path relative to `canworks/`. A different file with the same name SHALL NOT be overwritten silently. When "keep both" gives the new EDS another name, it SHALL get its own notes file (see `canopen-device-notes`), and replacing an EDS SHALL keep its notes file.

At import, the configurator SHALL also run the checks the PLC runs before dcfgen, on the same prepared copy (see `canopen-master-bringup`, "Prepared EDS copy"): dcfgen's EDS read and lint, and Lely's EDS parse rules, sorting the lint findings as the bridge does (see `canopen-master-bringup`, "EDS lint scope") under the config's `eds_lint` setting. The import SHALL show:
- that the file is readable, when nothing below applies;
- the corrections made in the prepared copy (UTF-8 conversion, `$NODEID` rewrites, REAL rewrite, cleared OCTET_STRING values), as described below;
- findings that do not stop the PLC, as a collapsed list with each finding's object, saying they are accepted.

The correction report SHALL name the imported file, SHALL say that the file is kept as imported, and SHALL name who reads the corrected copy for the project's target: canworks-bridge, the Modbus bridge, or, for a node under a CODESYS target, the DCFs exported to CODESYS, which are built from it. A slave EDS import under a CODESYS target SHALL name canworks as the reader. Each kind of correction SHALL be listed on its own line with how many values it changed, in words that read correctly for one value and for several. Under a CODESYS target, a node import SHALL NOT list the REAL rewrite, since the exported DCFs write REAL values as decimals. The UTF-8 conversion, which changes the stored file, SHALL be reported on its own line as before.

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

#### Scenario: $NODEID rewrite reported for OpenPLC
- **WHEN** the project target is OpenPLC and the user adds a node from `valve.eds`, which has 8 values written `<number>+$NODEID`
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

### Requirement: Device PDO mapping in the PDO editor
For each PDO the configurator SHALL show whether its mapping is written from the config or kept by the device, using the same rule as the bridge. When the node's EDS fixes the mapping, the PDO SHALL show "Set by the device" with its default mapping listed, the entry picker SHALL offer only the objects of that mapping, and no `mapping` field SHALL be saved. When the mapping is writable, the user SHALL be able to choose "Use device mapping", which saves `"mapping": "device"` and flags entries outside the default mapping. A device-mapped PDO SHALL offer "Map all", which adds every non-dummy object of the default mapping with suggested locations.

#### Scenario: Fixed PDO in the editor
- **WHEN** the user imports an EDS whose 0x1A00 is read-only with two UNSIGNED8 objects
- **THEN** TPDO 1 shows "Set by the device" with both objects, and "Map all" adds both as `%IB` inputs at the lowest free locations

#### Scenario: Switch a writable PDO to device mapping
- **WHEN** a writable TPDO has entries 0x4001 sub 0 and 0x4002 sub 0 and the EDS default maps only 0x4001 sub 0, and the user picks "Use device mapping"
- **THEN** the PDO saves with `"mapping": "device"` only after 0x4002 sub 0 is removed, and until then the entry shows an error listing the default mapping

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

### Requirement: Export the slave EDS
The page SHALL have an **Export EDS** button that saves the slave's EDS for import into the other master's tool, with a file name from the device name.

#### Scenario: Export
- **WHEN** the user clicks **Export EDS**
- **THEN** a save dialog offers the EDS the bridge runs

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

### Requirement: Heartbeat watch setting
The node page's supervision section SHALL list the node's heartbeat watch entries (watched node from the network's nodes, timeout with the default shown when empty), and the check SHALL give the same messages as the bridge for them, including the 0x1016 capacity from the node's EDS.

#### Scenario: Default timeout shown
- **WHEN** node 20 watches node 10, which has `heartbeat_ms` 100, and the timeout field is empty
- **THEN** the field shows "default (300 ms)" and the saved entry has no `timeout_ms`

### Requirement: CiA 309-3 gateway settings
The Online access settings SHALL have a "CiA 309-3 gateway" part that turns `cia309` on and off and edits its plain port (or none), `max_clients`, "allow changes" and "allow force on running nodes" (both off by default; force with a warning that a standard tool can then stop nodes the program drives), and shows the network numbering, with optional explicit numbers per network. It SHALL say that the plain port listens on the PLC's loopback address only and that other machines connect through `canworks-diag gateway` with the project's token. The deploy tool's config check and the configurator's Check SHALL apply the bridge's `cia309` rules.

#### Scenario: Turn the gateway on
- **WHEN** the user turns on the CiA 309-3 gateway in a project with networks `io` and `drives` and saves
- **THEN** `canworks.json` has a top-level `cia309` object with `allow_changes` false, and the page shows `1 = io, 2 = drives`

#### Scenario: Network bind refused in Check
- **WHEN** a hand-edited project has `cia309.bind` set to `0.0.0.0`
- **THEN** Check reports `cia309.bind` with the bridge's message

### Requirement: EMCY COB-ID on the node page
The node page's Emergency (EMCY) section SHALL edit `emcy_cob_id`: Device (the default, saved as no field), EDS, or a COB-ID typed in hex or decimal. The Check SHALL give the bridge's messages for a COB-ID the bridge rejects. The online view's node row SHALL show the EMCY COB-ID in use, with its source, when it is not 0x80 + node ID, and SHALL mark it when the device reports its EMCY not valid.

#### Scenario: Default not saved
- **WHEN** the user leaves the EMCY COB-ID on Device and saves
- **THEN** the saved node has no `emcy_cob_id`

#### Scenario: Clashing COB-ID typed
- **WHEN** the user types node 6's TPDO 1 COB-ID as node 5's EMCY COB-ID
- **THEN** the Check reports node 5's `emcy_cob_id` clashing with node 6's TPDO 1

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

### Requirement: Keyboard-only task tests
The browser tests SHALL do five user tasks with the keyboard alone, in the Light and the Dark theme: connect to a virtual USB adapter, scan the bus, add a found node to a config, map a PDO entry and save, and record and save a trace. They SHALL use the virtual adapter, the fake bridge runtime and the local simulator runtime, with no hardware, and SHALL fail if a step uses the pointer.

#### Scenario: Record a trace by keyboard in Dark
- **WHEN** the trace task runs in the Dark theme
- **THEN** it opens the Trace tab, starts and stops a recording and saves it with key presses only

#### Scenario: Pointer step caught
- **WHEN** a task test step clicks a button
- **THEN** the test fails saying the step used the pointer

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

### Requirement: Last heard in Commission
The Nodes table and the node header SHALL show the time since the node was last heard, from the bridge's status for a runtime connection and from the adapter for a direct one. "-" SHALL be shown only for a node never heard in the session.

#### Scenario: Heartbeat every 100 ms
- **WHEN** node 6 sends a heartbeat every 100 ms and the page is connected to the runtime
- **THEN** node 6's Last heard reads about "0.1 s ago"

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

## REMOVED Requirements

### Requirement: CiA 402 axis setting
**Reason**: CiA 402 support is dropped entirely (Toni, 2026-10-22).
**Migration**: None; drive objects can still be mapped as plain PDO values.

### Requirement: Map CiA 402 objects
**Reason**: CiA 402 support is dropped entirely (Toni, 2026-10-22).
**Migration**: None; drive objects can still be mapped as plain PDO values.

### Requirement: Map CiA 402 objects on a fixed-mapping device
**Reason**: CiA 402 support is dropped entirely (Toni, 2026-10-22).
**Migration**: None; drive objects can still be mapped as plain PDO values.

### Requirement: Axis lines in the declarations
**Reason**: CiA 402 support is dropped entirely (Toni, 2026-10-22).
**Migration**: None; drive objects can still be mapped as plain PDO values.

### Requirement: Located variable declarations
**Reason**: The Variable declarations page served the plugin target's located variables; an OpenPLC project now gets the generated `canworks` variable list (canopen-editor-project, change add-openplc-modbus-target).
**Migration**: **Update declarations** on the Project page.

### Requirement: Declarations at a glance
**Reason**: The Variable declarations page served the plugin target's located variables; an OpenPLC project now gets the generated `canworks` variable list (canopen-editor-project, change add-openplc-modbus-target).
**Migration**: **Update declarations** on the Project page.

### Requirement: Master settings
**Reason**: It described the removed OpenPLC plugin; its scenarios change with the plugin gone.
**Migration**: Requirement: Master settings on the Bus page.

### Requirement: Startup SDO picker shows settings
**Reason**: It described the removed OpenPLC plugin; its scenarios change with the plugin gone.
**Migration**: Requirement: Startup SDO picker shows the bridge's settings.

### Requirement: Online view
**Reason**: It described the removed OpenPLC plugin; its scenarios change with the plugin gone.
**Migration**: Requirement: Online view of the bridge.

### Requirement: Trace view
**Reason**: It described the removed OpenPLC plugin; its scenarios change with the plugin gone.
**Migration**: Requirement: Trace view of the bus.

### Requirement: Devices in the header and from other pages
**Reason**: It described the removed OpenPLC plugin; its scenarios change with the plugin gone.
**Migration**: Requirement: Devices from the header and other pages.

## ADDED Requirements

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
