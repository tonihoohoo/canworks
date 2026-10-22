## MODIFIED Requirements

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

### Requirement: Busy states and the Save button
Save, every export, Move into project, New editor project and Add node from EDS SHALL disable their control and show what is running ("Saving…", "Exporting…", "Adding…") until the request completes, and a second click meanwhile SHALL do nothing. The Save button SHALL read "Save" and be enabled whenever the draft differs from the file, with or without errors. It SHALL read "Saved" and be disabled when the draft equals the file and has no problems, and "Saved, N problems" (disabled) when it equals the file and has problems. The error count SHALL be shown in the Problems pane.

#### Scenario: Double click on Save
- **WHEN** the user clicks Save twice while the first save is still running
- **THEN** one save request is made and the button reads "Saving…" until it returns

#### Scenario: Clean draft
- **WHEN** the file on disk equals the draft and the check has no problems
- **THEN** the button reads "Saved" and is disabled

#### Scenario: Dirty draft with an error
- **WHEN** the draft has one error and differs from the file
- **THEN** the button reads "Save" and is enabled

### Requirement: Target of a new config
New config… SHALL be one dialog that asks first what will run the networks, with three choices and one sentence each: OpenPLC Runtime (the canworks plugin runs the networks), Modbus bridge (no PLC; the values are served as Modbus TCP registers, naming Node-RED, HMIs and other Modbus TCP clients) and CODESYS (a CODESYS PLC runs the CANopen master). OpenPLC SHALL be preselected. The dialog SHALL then ask for a name (the new folder) and its location, with Choose… opening the folder dialog. For OpenPLC it SHALL offer "Also create an OpenPLC Editor project here", ticked by default when the editor's `openplc-cli` is found and disabled with the reason when it is not; ticked, the folder SHALL become a new OpenPLC Editor project, opened as a project. Otherwise the folder SHALL become a config folder. In both cases Create SHALL write the target's empty config to disk (the project's `canworks/` folder, or the config folder) before the page opens it, so a reload shows the new config with its target.

#### Scenario: New CODESYS config
- **WHEN** the user creates a new config with target CODESYS
- **THEN** the config is version 2 with a `codesys` object, it is on disk, and the page shows the CODESYS target

#### Scenario: New Modbus bridge config
- **WHEN** the user creates a new config with target Modbus bridge and reloads the page
- **THEN** the folder holds a config with a `bridge` object, and the page shows it with the Modbus bridge target and "Saved"

#### Scenario: New OpenPLC config with an editor project
- **WHEN** `openplc-cli` is found and the user creates a new OpenPLC config in `~/plc/new-machine` with the editor-project tick on
- **THEN** `~/plc/new-machine` is an OpenPLC Editor project with an empty config in its `canworks/` folder, and the page shows the mode "project new-machine"

#### Scenario: No editor command-line tool
- **WHEN** `openplc-cli` is not found and the user picks OpenPLC
- **THEN** the editor-project tick is off and disabled with the reason, and Create makes a config folder

### Requirement: SocketCAN adapter settings
The configurator SHALL edit the `socketcan` adapter: interface name, bit rate chosen from the CiA 301 rates the contract allows, whether the plugin configures the link (`configure_link`, default on) and the bus-off restart delay (`restart_ms`). A config using the pre-contract top-level `interface`/`bitrate` keys SHALL be shown as that adapter and saved in the `adapter` form, with the page saying so.

#### Scenario: Set up can0 at 250 kbit/s
- **WHEN** the user sets interface `can0`, bit rate 250000, leaves "configure link" on, sets restart 100 ms and saves
- **THEN** `canworks.json` has `adapter` `{"type": "socketcan", "interface": "can0", "bitrate": 250000, "configure_link": true, "restart_ms": 100}`

#### Scenario: Bit rate outside CiA 301
- **WHEN** a loaded config has `bitrate: 300000`
- **THEN** the bit rate field shows the contract error and the hand-off steps refuse the config until a listed rate is chosen

#### Scenario: Old-style config
- **WHEN** a loaded config has top-level `interface: "vcan0"` and `bitrate: 125000`
- **THEN** the page shows a SocketCAN adapter on `vcan0` at 125000 with "configure link" off, says the file uses the old keys, and saving writes them as `adapter` with `configure_link: false`

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
- **THEN** the field shows the range error and the hand-off steps refuse the config

#### Scenario: Object not in the EDS
- **WHEN** the user types index 0x2100 subindex 0 that the EDS does not list
- **THEN** the write is refused, because the plugin only writes startup SDOs to objects the node's EDS defines

#### Scenario: Startup SDO with a value meaning
- **WHEN** the notes give 0x2011:2 the values 0 "hold position" and 1 "close" and the user adds a startup SDO for it
- **THEN** the value field lists "0 hold position" and "1 close", and the saved write has the number the user picked

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

### Requirement: LSS node settings
For each node the configurator SHALL show an "Assign node ID by serial number (LSS)" checkbox, saved as `lss.assign`, and a "Store node ID in the device" checkbox, saved as `lss.store`, which SHALL be unticked for a new node and disabled while the first is unticked. Unticked boxes SHALL be left out of the saved node, and an `lss` object with nothing in it SHALL be left out. While "Assign" is ticked the node's serial number field SHALL be required, `reset_communication` SHALL not be selectable as off, and the page SHALL say that the master gives the device this node ID at every start. When the node's EDS does not say `LSS_Supported=1` (left out or 0), both checkboxes SHALL be disabled and unticked, with the reason next to them as hint text ("This device's EDS has no LSS (LSS_Supported=1 missing)", see "One look for EDS limits"). A loaded node that still has an `lss` object SHALL show it as a problem with the plugin's message in warning colour and offer to remove it. Saving SHALL be refused until it is removed or the node gets an EDS with LSS.

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
- **THEN** the node shows the error and the hand-off steps refuse the config

#### Scenario: Cyclic on a timer network
- **WHEN** the user turns on "Cyclic synchronous" for axis `drive` on a network whose SYNC comes from the master's timer
- **THEN** the node shows the error that a cyclic axis needs SYNC from the PLC cycle, with a button that sets `"sync_source": "plc_cycle"` on that network (removing `sync_period_us`), and the hand-off steps refuse the config until it is fixed

### Requirement: The check refuses what the plugin refuses
The configurator's check (and the deploy tool's, which is the same) SHALL refuse every config the plugin refuses at start. In particular:
- an adapter without an interface (or an slcan adapter without a device);
- a number outside its range whatever base it is typed in (decimal or `0x` hex): node IDs, heartbeat times, identity values, COB-IDs, TIME COB-ID;
- two PDOs on one network with the same COB-ID, naming both;
- an axis scale numerator or denominator of 0.

A heartbeat consumer timeout shorter than the node's heartbeat period SHALL be refused, as the plugin refuses it. Each message SHALL name the place in the user's terms and say what is allowed ("node ID 1 to 127", "COB-ID 0x185 is also node 5's TPDO 1"), not quote a schema rule or pattern.

#### Scenario: Missing interface
- **WHEN** the user adds a network and leaves the SocketCAN interface empty
- **THEN** Problems lists "network net2: the CAN interface is missing" and the hand-off steps refuse the config

#### Scenario: Hex out of range
- **WHEN** the user types `0x80` as a node ID
- **THEN** the field is marked "node ID 1 to 127" exactly as for `128`

#### Scenario: Duplicate COB-ID
- **WHEN** node 6's TPDO 1 COB-ID is set to 0x185, which node 5's TPDO 1 uses
- **THEN** both PDOs are marked and Problems names the clash

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

### Requirement: EMCY section follows the EDS
When the node's EDS has no object 0x1014, the Emergency (EMCY) section SHALL hold only one line saying that the EDS has no EMCY COB-ID (0x1014), so the device sends no emergency messages, and no controls. Such a node SHALL be saved without EMCY fields. A loaded node that still has one SHALL show the plugin's message and offer to remove the EMCY settings; the hand-off steps SHALL refuse the config until they are removed.

#### Scenario: Device without EMCY
- **WHEN** the user opens the Supervision tab of a node whose EDS has no 0x1014
- **THEN** the Emergency section shows only the line that the EDS has no 0x1014, no EMCY field, Suggest button or COB-ID choice, and the saved node has no EMCY field

#### Scenario: Leftover EMCY mapping
- **WHEN** a loaded config gives `emcy_code_location` `%IW30` for a node whose EDS has no 0x1014
- **THEN** the section shows the problem in warning colour with "Remove the EMCY settings", and the hand-off steps refuse the config until the user presses it

### Requirement: Raw signal length errors
An empty or invalid raw signal length SHALL be reported as a field problem; the check SHALL NOT fail.

#### Scenario: Cleared length
- **WHEN** the user clears a raw signal's Length
- **THEN** Problems shows the length error and the hand-off steps refuse the config

### Requirement: Heartbeat consumer choice follows the EDS
When the node's EDS has no object 0x1016 with a writable sub-index, "Watches the master heartbeat" SHALL show "EDS default", be disabled, and say in hint text that the EDS has no consumer heartbeat time (0x1016), so the device cannot watch the master's heartbeat. The node's Heartbeat watch block SHALL NOT be shown while the node watches nobody. A loaded node that still has `heartbeat_consumer` or `heartbeat_watch` SHALL show the plugin's message and offer to remove it; the hand-off steps SHALL refuse the config until it is removed. The Heartbeat watch block SHALL span the section, with its heading and hint each on a line of their own.

#### Scenario: Device without 0x1016
- **WHEN** the user opens Advanced node settings of a node whose EDS has no 0x1016
- **THEN** the choice is disabled on "EDS default" with the reason, and the saved node has no `heartbeat_consumer`

#### Scenario: No heartbeat watch without 0x1016
- **WHEN** node 23's EDS has no 0x1016, it watches nobody, and the network has node 5
- **THEN** node 23's Supervision tab has no Heartbeat watch block

#### Scenario: Heartbeat watch layout
- **WHEN** node 5's EDS has a writable 0x1016 and the user opens its Supervision tab
- **THEN** "Heartbeat watch" is a heading on its own line above its hint, across the section's width

## ADDED Requirements

### Requirement: Hand-off steps need a config without errors
Build into CODESYS project and installing or updating the bridge config on a device SHALL use the saved config; Download for CODESYS SHALL use the draft. They SHALL refuse while the config they use has errors, and a CANopen master network without nodes SHALL count as one. A refusal SHALL be shown next to the control in one line naming the error count, with a link that opens Problems. Allowed overlaps SHALL NOT count. Exports of DCF, DBC and documentation SHALL keep their own rules.

#### Scenario: Build with an error
- **WHEN** a CODESYS config is saved with one error and the user presses Build into CODESYS project…
- **THEN** nothing runs, and the page says the saved config has 1 error, with a link to Problems

### Requirement: Empty network is a warning
A CANopen master network without nodes SHALL be one warning in Problems, not an error. The tree and the network's Bus page SHALL show the empty state: "No nodes yet", with **Add node…** and a pointer to finding devices in Commission. The hand-off steps SHALL still refuse a network without nodes.

#### Scenario: Fresh config
- **WHEN** the user creates a new OpenPLC config
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
