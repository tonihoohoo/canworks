## ADDED Requirements

### Requirement: Project target
A project SHALL have one target: "OpenPLC" (default), "Modbus bridge" or "CODESYS", chosen in a "Project target" field at the top of every Bus page and shown in the header. The target SHALL come from the config: a `bridge` object makes it Modbus bridge, a `codesys` object CODESYS.

#### Scenario: Target shown
- **WHEN** the user opens a config with a `codesys` object
- **THEN** the Project target field and the header show CODESYS

### Requirement: Only what the target uses is shown
The page SHALL hide every field, choice option, tree entry, menu item and start-page action that the project's target does not use, as the relevance table of `canopen-config-contract` lists them. A setting the target does not use that still has a value SHALL stay shown, marked "not used by <target>", with a Remove action. The same rules SHALL apply to all three targets.

#### Scenario: CODESYS project
- **WHEN** the project's target is CODESYS
- **THEN** the page shows no IEC location fields, status locations, SDO variables, CiA 402 axis, scan watchdog, EDS lint, simulated devices, raw CAN messages, gateway, Online access or OpenPLC Editor project actions, and the protocol choice offers only CANopen master

#### Scenario: Bridge project
- **WHEN** the project's target is Modbus bridge
- **THEN** the SYNC source offers no "PLC cycle", no scan watchdog field is shown, and the Project menu has no editor project actions

#### Scenario: OpenPLC project
- **WHEN** the project's target is OpenPLC
- **THEN** no Modbus bridge or CODESYS page, field or action is shown

#### Scenario: Leftover value
- **WHEN** a CODESYS project still has `on_plc_stop` set to `keep`
- **THEN** the field is shown marked "not used by CODESYS" with Remove, and Problems lists the same warning

### Requirement: Switching the target
Switching the target SHALL show one dialog naming what the new target does not use, and SHALL apply the switch as one undo step:
- to CODESYS: every PDO entry without a `name` gets its current generated name, and the dialog offers **Remove them** (default) or **Keep them** for the unused values; `bridge` is removed;
- from CODESYS: `codesys` objects are removed and the dialog offers to give every entry without a location one, per type for OpenPLC or packed for Modbus for the bridge; entry names stay;
- between OpenPLC and Modbus bridge: the repack choice as before, and Remove or Keep for the values the new target does not use.

#### Scenario: OpenPLC to CODESYS
- **WHEN** the user switches an OpenPLC project with node `dio` mapping 0x6000 sub 1 to `%IB8` to CODESYS and picks Remove them
- **THEN** the entry has `name` `Read_input_8_bit_1` and no `iec_location`, the config has a `codesys` object, Check reports no problems, and one Undo restores the OpenPLC project

#### Scenario: CODESYS to bridge
- **WHEN** the user switches that CODESYS project to Modbus bridge and accepts packing
- **THEN** every entry has a byte-addressed location, the `codesys` objects are gone and the register map row of the entry is named after `Read_input_8_bit_1`

### Requirement: Variable names of PDO entries
The PDO table SHALL have a Variable column for every target, editing the entry's `name`, with the generated name as placeholder. The Location column SHALL be shown only for targets that use locations.

#### Scenario: Rename a channel
- **WHEN** the user types `door_open` as the variable of an entry in a CODESYS project
- **THEN** the entry gets `name` `door_open` and the CODESYS export names that channel `<node>_door_open`

### Requirement: CODESYS settings
A CODESYS project SHALL have a "CODESYS" page in the tree with the project file, the device that gets the bus, the PLC device for a new project and variable names on or off, and each CANopen master network's Bus page SHALL have the CODESYS network number and CAN interface object, all stored in the config's `codesys` objects.

#### Scenario: Network number
- **WHEN** the user sets the CODESYS network number of network `field` to 0
- **THEN** the config's network `field` gets `codesys.net_id` 0 and the next CODESYS build uses network number 0

### Requirement: CODESYS actions
A CODESYS project SHALL have **Build into CODESYS project…** and **Download for CODESYS** in the header. Build SHALL require a saved config and a project file, run the `--codesys-import` route of `canopen-deploy` with the config's settings as a job, and show CODESYS's report in the log; when CODESYS is not found on this PC it SHALL say so and point to Download. Download SHALL offer the `codesys-export` folder as `<config folder name>_codesys.zip` and write no file in the project or config folder; on errors it SHALL download nothing and list them in Problems.

#### Scenario: Build
- **WHEN** a saved CODESYS project names `C:\Projects\cell.project` and the user clicks Build into CODESYS project on a PC with CODESYS
- **THEN** the project gets the bus, the log shows the report, and the job ends with the report's result

#### Scenario: Project open in CODESYS
- **WHEN** the build fails because the project is open in the CODESYS window
- **THEN** the log shows the failure with the hint to close the project in CODESYS first

#### Scenario: No CODESYS
- **WHEN** the user clicks Build on a PC without CODESYS
- **THEN** the page says CODESYS was not found and offers Download for CODESYS

### Requirement: Target of a new config
"New standalone config" on the start page SHALL ask for the target, and the start page's intro SHALL name the three targets.

#### Scenario: New CODESYS config
- **WHEN** the user creates a new standalone config with target CODESYS
- **THEN** the config is version 2 with a `codesys` object and the page shows the CODESYS target

### Requirement: Commission in a CODESYS project
In a CODESYS project, Commission SHALL connect through a USB adapter only, since no canworks runtime runs the bus.

#### Scenario: Connect
- **WHEN** the user opens Commission in a CODESYS project
- **THEN** the connect dialog offers the USB adapter and no runtime

## REMOVED Requirements

### Requirement: Modbus bridge target
**Reason**: Replaced by "Project target", "Only what the target uses is shown" and "Switching the target", which cover the bridge together with OpenPLC and CODESYS.
**Migration**: None; the `bridge` object still marks a bridge config.

### Requirement: Export for CODESYS
**Reason**: CODESYS is a project target; its export is "Download for CODESYS" under "CODESYS actions".
**Migration**: Switch the project to CODESYS, or use `canworks-deploy --export-codesys`.
