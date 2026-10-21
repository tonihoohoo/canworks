## MODIFIED Requirements

### Requirement: Only what the target uses is shown
The page SHALL hide every field, table column, choice option, fieldset, node tab, tree entry, menu item, page and start-page action that the project's target does not use, as the relevance table of `canopen-config-contract` lists them, whether or not the config has a value for it. Values the target does not use SHALL be listed instead as Requirement: Settings the target does not use on the page describes, and SHALL be shown in place only while Requirement: Show fields the target does not use is on. Hints, labels and page texts that differ between targets SHALL use the project target's wording: a bridge or CODESYS project SHALL NOT be told about the plugin, the Pi, the PLC scan or PLC locations where they do not apply. The editor project's address scan line SHALL be shown for OpenPLC only, and the Variable declarations page SHALL be OpenPLC only. The same rules SHALL apply to all three targets.

#### Scenario: CODESYS project
- **WHEN** the project's target is CODESYS
- **THEN** the page shows no IEC location fields or column, status locations, SDO variables, CiA 402 axis, scan watchdog, EDS lint, simulated devices, raw CAN messages, gateway, Online access or OpenPLC Editor project actions, and the protocol choice offers only CANopen master

#### Scenario: Bridge project
- **WHEN** the project's target is Modbus bridge
- **THEN** the SYNC source offers no "PLC cycle", no scan watchdog field is shown, the Project menu has no editor project actions, no Variable declarations page is in the tree, and the Bus page's role hint says the bridge is the network's master

#### Scenario: OpenPLC project
- **WHEN** the project's target is OpenPLC
- **THEN** no Modbus bridge or CODESYS page, field or action is shown

#### Scenario: Leftover value
- **WHEN** a CODESYS project still has `on_plc_stop` set to `keep`
- **THEN** the field is hidden, the Bus page's bar lists "When the PLC stops: keep" with Remove, and Problems lists it in the grouped warning

#### Scenario: Leftover location in a CODESYS project
- **WHEN** a CODESYS project's node `dio` has one TPDO entry with `iec_location` `%IW100`
- **THEN** the node's PDO table has no PLC location column, and the PDOs tab shows the bar "1 setting here is not used by CODESYS"

#### Scenario: Leftover simulate in a CODESYS project
- **WHEN** a CODESYS project's node has `simulate` set
- **THEN** the node has no Simulation tab and its General tab's bar lists the setting

#### Scenario: Wording guard
- **WHEN** the browser tests open every page and node tab of a config with every setting set, once per target
- **THEN** no field the target does not use is visible, and no visible text uses another target's words (for CODESYS: the plugin, the Pi, PLC location, an IEC address, scan watchdog, OpenPLC), apart from the Project target field's help

### Requirement: Variable names of PDO entries
The PDO table SHALL have a Variable column for every target, editing the entry's `name`, with the generated name as placeholder. The Location column SHALL be shown only for targets that use locations, also when an entry of a target without locations still has one, unless Requirement: Show fields the target does not use is on.

#### Scenario: Rename a channel
- **WHEN** the user types `door_open` as the variable of an entry in a CODESYS project
- **THEN** the entry gets `name` `door_open` and the CODESYS export names that channel `<node>_door_open`

#### Scenario: No Location column for CODESYS
- **WHEN** a CODESYS project has an entry with `iec_location` left over
- **THEN** the PDO table's columns are Object, Name, Type, Variable, PDO and the remove button

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

## ADDED Requirements

### Requirement: Settings the target does not use on the page
A page or node tab that holds values its project's target does not use SHALL show, under its heading, one folded bar "N setting(s) here are not used by <target>" with **Remove all** and **Show**. Unfolded, the bar SHALL list each value in the user's terms (place, field label, value) with its own Remove. Each Remove and each Remove all SHALL be one undo step. A network kind the target does not use (a slave, J1939 or plain CAN network in a CODESYS project) SHALL keep its current handling, with no Remove.

#### Scenario: Remove all on a tab
- **WHEN** a CODESYS project's node 5 Supervision tab holds a status location and a heartbeat timeout, and the user clicks Remove all in its bar
- **THEN** both values are gone from the config, the bar disappears, and one Undo brings both back

### Requirement: One problem for the settings the target does not use
Problems SHALL show the values the target does not use as one grouped warning "N settings are not used by <target>" with **Remove all** and a fold-out list, whose rows open the value's page with its bar unfolded. Tree and tab badges SHALL NOT count these warnings, and no message SHALL be written next to their hidden fields. The command-line check SHALL keep one warning per value.

#### Scenario: Grouped problem
- **WHEN** a CODESYS project has 5 values CODESYS does not use on three pages
- **THEN** Problems shows one warning "5 settings are not used by CODESYS", no tab badge counts them, and clicking its "Node 5 rtd, TPDO 1: PLC location %IW100" row opens node 5's PDOs tab with the bar unfolded

#### Scenario: Command-line check
- **WHEN** `canworks-deploy --check` runs on that config
- **THEN** it prints five warnings, one per value, as before

### Requirement: Show fields the target does not use
The View menu SHALL have a toggle "Show fields the target does not use", off by default and remembered on this PC (not in the config). While it is on, every field, column, tab and page the target does not use SHALL be shown, dimmed and tagged "not used by <target>", and editable, with Remove when it has a value, and the header's target badge SHALL add "· all fields". A bar's **Show** SHALL turn the toggle on.

#### Scenario: Turn on from the bar
- **WHEN** the user clicks Show in the PDOs tab's bar of a CODESYS project
- **THEN** the PLC location column appears dimmed with `%IW100` tagged "not used by CODESYS" and Remove, and the header badge reads "· CODESYS · all fields"

#### Scenario: Remembered per PC
- **WHEN** the user turns the toggle off, closes the configurator and opens another config
- **THEN** the toggle is still off and the config file has not changed
