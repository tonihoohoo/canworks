## MODIFIED Requirements

### Requirement: Only what the target uses is shown
The page SHALL hide every field, table column, choice option, fieldset, node tab, tree entry, menu item, page and start-page action that the project's target does not use, as the relevance table of `canopen-config-contract` lists them, whether or not the config has a value for it, and SHALL NOT list, mark or ask about such values (Requirement: Settings the target does not use are left out on save). Hints, labels and page texts that differ between targets SHALL use the project target's wording: a bridge or CODESYS project SHALL NOT be told about the plugin, the Pi, the PLC scan or PLC locations where they do not apply. The editor project's address scan line SHALL be shown for OpenPLC only, and the Variable declarations page SHALL be OpenPLC only. A section SHALL be hidden only when none of its controls is left, and a section whose settings the target does not use (the Emergency section for CODESYS) SHALL not be drawn. A node tab left with nothing SHALL say in one line that the target does not use its settings instead of staying blank. The same rules SHALL apply to all three targets.

#### Scenario: CODESYS project
- **WHEN** the project's target is CODESYS
- **THEN** the page shows no IEC location fields or column, status locations, SDO variables, CiA 402 axis, scan watchdog, EDS lint, simulated devices, raw CAN messages, gateway, Online access, Emergency section or OpenPLC Editor project actions, and the protocol choice offers only CANopen master

#### Scenario: Bridge project
- **WHEN** the project's target is Modbus bridge
- **THEN** the SYNC source offers no "PLC cycle", no scan watchdog field is shown, the Project menu has no editor project actions, no Variable declarations page is in the tree, and the Bus page's role hint says the bridge is the network's master

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
- **THEN** no field the target does not use is visible, no node tab is blank, and no visible text uses another target's words (for CODESYS: the plugin, the Pi, PLC location, an IEC address, scan watchdog, OpenPLC), apart from the Project target field's help

### Requirement: Switching the target
Picking another target SHALL switch at once, without a dialog, as one undo step, and a message SHALL say what was done and that Undo restores the previous target:
- to CODESYS: every PDO entry without a `name` gets its current generated name, the values CODESYS does not use are removed, and `bridge` is removed;
- from CODESYS: `codesys` objects are removed and every entry without a location gets one, per type for OpenPLC or packed for Modbus for the bridge; entry names stay;
- between OpenPLC and Modbus bridge: every location is repacked for the new target and the values it does not use are removed.

#### Scenario: OpenPLC to CODESYS
- **WHEN** the user switches an OpenPLC project with node `dio` mapping 0x6000 sub 1 to `%IB8` to CODESYS
- **THEN** no dialog opens, the entry has `name` `Read_input_8_bit_1` and no `iec_location`, the config has a `codesys` object, Check reports no problems, and one Undo restores the OpenPLC project

#### Scenario: CODESYS to bridge
- **WHEN** the user switches that CODESYS project to Modbus bridge
- **THEN** every entry has a byte-addressed location, the `codesys` objects are gone and the register map row of the entry is named after `Read_input_8_bit_1`

### Requirement: Variable names of PDO entries
The PDO table SHALL have a Variable column for every target, editing the entry's `name`, with the generated name as placeholder. The Location column SHALL be shown only for targets that use locations, also when an entry of a target without locations still has one.

#### Scenario: Rename a channel
- **WHEN** the user types `door_open` as the variable of an entry in a CODESYS project
- **THEN** the entry gets `name` `door_open` and the CODESYS export names that channel `<node>_door_open`

#### Scenario: No Location column for CODESYS
- **WHEN** a CODESYS project has an entry with `iec_location` left over
- **THEN** the PDO table's columns are Object, Name, Type, Variable, PDO and the remove button

### Requirement: EMCY section follows the EDS
When the node's EDS has no object 0x1014, the Emergency (EMCY) section SHALL hold only one line saying that the EDS has no EMCY COB-ID (0x1014), so the device sends no emergency messages, and no controls. Such a node SHALL be saved without EMCY fields. A loaded node that still has one SHALL show the plugin's message and offer to remove the EMCY settings; saving SHALL be refused until they are removed.

#### Scenario: Device without EMCY
- **WHEN** the user opens the Supervision tab of a node whose EDS has no 0x1014
- **THEN** the Emergency section shows only the line that the EDS has no 0x1014, no EMCY field, Suggest button or COB-ID choice, and the saved node has no EMCY field

#### Scenario: Leftover EMCY mapping
- **WHEN** a loaded config gives `emcy_code_location` `%IW30` for a node whose EDS has no 0x1014
- **THEN** the section shows the problem in warning colour with "Remove the EMCY settings", and Save is refused until the user presses it

### Requirement: Heartbeat consumer choice follows the EDS
When the node's EDS has no object 0x1016 with a writable sub-index, "Watches the master heartbeat" SHALL show "EDS default", be disabled, and say in hint text that the EDS has no consumer heartbeat time (0x1016), so the device cannot watch the master's heartbeat. The node's Heartbeat watch block SHALL NOT be shown while the node watches nobody. A loaded node that still has `heartbeat_consumer` or `heartbeat_watch` SHALL show the plugin's message and offer to remove it; saving SHALL be refused until it is removed. The Heartbeat watch block SHALL span the section, with its heading and hint each on a line of their own.

#### Scenario: Device without 0x1016
- **WHEN** the user opens Advanced node settings of a node whose EDS has no 0x1016
- **THEN** the choice is disabled on "EDS default" with the reason, and the saved node has no `heartbeat_consumer`

#### Scenario: No heartbeat watch without 0x1016
- **WHEN** node 23's EDS has no 0x1016, it watches nobody, and the network has node 5
- **THEN** node 23's Supervision tab has no Heartbeat watch block

#### Scenario: Heartbeat watch layout
- **WHEN** node 5's EDS has a writable 0x1016 and the user opens its Supervision tab
- **THEN** "Heartbeat watch" is a heading on its own line above its hint, across the section's width

## REMOVED Requirements

### Requirement: Settings the target does not use on the page
**Reason**: The configurator drops values the target does not use by itself (Requirement: Settings the target does not use are left out on save); listing them asked the user to do the configurator's job.
**Migration**: None; save leaves them out.

### Requirement: One problem for the settings the target does not use
**Reason**: Same as above: the page no longer reports values the target does not use. The command-line check still warns per value.
**Migration**: None.

### Requirement: Show fields the target does not use
**Reason**: With values the target does not use left out on save, showing and editing them has no effect.
**Migration**: The `show_all_fields` page setting is ignored.

## ADDED Requirements

### Requirement: Settings the target does not use are left out on save
Saving SHALL write the config without the values its target does not use (those the relevance table lists as removable), and the save message SHALL name how many were left out. Opening a config with such values SHALL NOT mark it unsaved. Values a target refuses and network kinds it cannot run SHALL keep their existing checks.

#### Scenario: Save a CODESYS config with old locations
- **WHEN** a CODESYS config with three PDO entries that still have `iec_location` is opened and saved
- **THEN** the file has no `iec_location`, and the message says 3 settings CODESYS does not use were left out

#### Scenario: Open without a change
- **WHEN** that config is opened
- **THEN** the header does not show it as unsaved
