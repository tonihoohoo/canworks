# codesys-export Specification

## Purpose
Builds a canworks CANopen network into a CODESYS project, so a CODESYS controller or display with CAN runs the same nodes, PDOs, startup SDOs and variable names with its own CANopen Manager: node DCFs, a plan of every setting and one fixed script that CODESYS runs in the IDE or headless.

## Requirements

### Requirement: Export folder for CODESYS
The CODESYS export SHALL write a folder holding one subfolder per exported network with that network's node DCFs exactly as `canopen-dcf-export` writes them, a plan file `canworks-codesys.json`, the script `import_canworks.py` (the same file for every config) and a `README.txt` saying how to run it. It SHALL be built on the PC from the config and its EDS files alone.

#### Scenario: One network, two nodes
- **WHEN** a valid config has network `field` with nodes 5 and 6
- **THEN** the folder has `field/node_5.dcf`, `field/node_6.dcf`, `canworks-codesys.json`, `import_canworks.py` and `README.txt`, and the DCFs equal the `--export-dcf` files for the same config

### Requirement: Only master CANopen networks are exported
The export SHALL cover master CANopen networks only. Slave, gateway, J1939 and plain CAN networks and raw messages SHALL be listed in the plan's `not_carried` list instead.

#### Scenario: J1939 network next to CANopen
- **WHEN** the config also has a J1939 network `engine`
- **THEN** no folder is written for `engine` and the plan's `not_carried` names it

### Requirement: Nothing written on errors
A config that fails the deploy tool's checks, or a DCF that fails validation, SHALL stop the export with those messages and write nothing.

#### Scenario: Config with an error
- **WHEN** an `rx_pdos` entry targets a read-only object
- **THEN** the export stops with the deploy tool's message and the folder gets no file

### Requirement: Plan settings per network
The plan SHALL hold, per exported network, its name, CODESYS network number, bit rate in kbit/s and the CANopen Manager settings: node ID, heartbeat producer time, SYNC on or off with period and window, autostart and start behaviour.

#### Scenario: Manager settings
- **WHEN** network `field` has master node ID 1, heartbeat 100 ms and SYNC every 20 ms at 250 kbit/s
- **THEN** the plan's `field` entry has those values and bit rate 250

### Requirement: Plan settings per node
The plan SHALL hold, per node, its node ID, a name that is a valid IEC 61131-3 identifier, its DCF path, its CODESYS device settings (node ID, optional or mandatory, do not initialize, restore before configuring, SDO timeout, and the heartbeat producer time when the node has `heartbeat_ms`) and its PDO channels with PDO mapping object, index, sub-index and variable name. The heartbeat producer time SHALL be planned even when it equals the EDS default. A channel SHALL be planned for every mapped PDO entry, with or without an IEC location. Variable names SHALL be the names the editor declarations give the same entries, using the entry's `name` when it has one.

#### Scenario: Variable names match the editor
- **WHEN** node `dio` maps 0x6000 sub 1 to `%IB8` and the editor declarations name that location `dio_Read_input_8_bit_1`
- **THEN** the plan's channel for input 0x6000 sub 1 of `dio` has that variable name

#### Scenario: Entry without a location
- **WHEN** a CODESYS config's node `dio` maps 0x6000 sub 1 with `name` `door_open` and no `iec_location`
- **THEN** the plan has a channel for input 0x6000 sub 1 of `dio` named `dio_door_open`

#### Scenario: Heartbeat equal to the EDS default
- **WHEN** node `conveyor` has `heartbeat_ms` 50 and its EDS default for 0x1017 is 50
- **THEN** the plan's device settings for `conveyor` set the heartbeat producer to 50 ms, and the CODESYS device shows 50 ms after the build

### Requirement: CODESYS network number
A network's CODESYS network number SHALL come from the user's override for that network when given, else the network's `codesys.net_id`, else the interface's trailing number, else 0 with a `not_carried` note.

#### Scenario: Number from the interface
- **WHEN** network `field` runs on `can1`, has no `codesys.net_id` and no override is given
- **THEN** the plan gives `field` network number 1

#### Scenario: Number from the config
- **WHEN** network `field` runs on `can1` and has `codesys.net_id` 0
- **THEN** the plan gives `field` network number 0

#### Scenario: Override
- **WHEN** the user gives `field=2` for a network with `codesys.net_id` 0
- **THEN** the plan gives `field` network number 2

### Requirement: Run in the CODESYS IDE on the open project
Run from CODESYS's script menu, the script SHALL work on the project open in the IDE, read the plan next to itself, apply it, write `import_report.txt` next to itself, show the report in CODESYS's message view, and SHALL NOT save the project. With no project open it SHALL stop with a message and change nothing.

#### Scenario: Open project
- **WHEN** the user opens a project with one PLC and runs `import_canworks.py` from the script menu
- **THEN** the PLC gets the bus from the plan, the report appears, and the project shows as modified but unsaved

#### Scenario: No project open
- **WHEN** the script runs with no project open in the IDE
- **THEN** it says a project must be open and changes nothing

### Requirement: Run from the command line
Run headless (`CODESYS.exe --profile=<profile> --noUI --runscript=<folder>\import_canworks.py`), the script SHALL open the project the plan names, or create a new project with the PLC device the plan names, apply the plan, build, save the project when no step failed, and write `import_report.txt`. It SHALL take no paths from the command line, so folders and project paths with spaces work.

#### Scenario: Existing project
- **WHEN** the plan names `C:\Projects\Line 2\cell.project` and CODESYS runs the script headless
- **THEN** the project is opened, gets the bus, builds and is saved, and the report is next to the script

#### Scenario: New project
- **WHEN** the plan asks for a new project with a given PLC device type, id and version
- **THEN** the project is created with that device and the bus

### Requirement: Uses the project's PLC
The script SHALL put the bus on one device of the project: the device the plan names; else the device that holds the project's active application, found at any depth in the device tree; else the only top-level device. It SHALL NOT depend on a particular PLC type or CODESYS install path. A project with several devices, no name in the plan and no active application SHALL stop the run with the list of devices and how to set an active application or name a device, and SHALL change nothing.

#### Scenario: Two devices, one active
- **WHEN** the project has devices `PLC` and `HMI`, `HMI` holds the active application and the plan names none
- **THEN** the bus is added under `HMI`, `PLC` is unchanged and the report's device line names `HMI` as the active application's device

#### Scenario: Two PLCs
- **WHEN** the project has two devices, neither holds the active application and the plan names none
- **THEN** the script stops, names both, says to set an active application or name a device, and changes nothing

#### Scenario: Named device
- **WHEN** the plan names `PLC` and `HMI` holds the active application
- **THEN** the bus is added under `PLC` and the report warns that the build checked the active application on `HMI`

#### Scenario: One device
- **WHEN** the project has one device and no application
- **THEN** the bus is added under that device

#### Scenario: Nested device
- **WHEN** the active application belongs to a device below the project's top level
- **THEN** the bus is added under that device

### Requirement: Reuses the device's CAN interfaces
For each network the script SHALL use an existing CANbus anywhere under the PLC whose network number equals the plan's, and an existing CANopen Manager under it. Only when none exists SHALL it add one under the network's CAN interface object, trying CANbus devices in this order and keeping the first one CODESYS accepts: the CANbus devices the project already has under an interface with the same device identification as the chosen one, then the project's other CANbus devices, then the CANbus devices installed in that CODESYS in their highest versions, CODESYS's standard CANbus first among those. When the interface refuses every CANbus, it SHALL add the CANopen Manager directly under that object. A new manager SHALL use the manager identification found under a CANbus of the same identification in the project, else the version matching the CANbus, else the highest installed. It SHALL then set the bit rate and the manager settings from the plan, and the report SHALL name the added CANbus's id and version and where that choice came from.

#### Scenario: Device that ships its CAN interfaces
- **WHEN** the project's PLC already has CANbus objects with network numbers 0 and 1 and the plan's network has number 1
- **THEN** the script adds the manager and nodes under the existing CANbus with number 1 and adds no CANbus

#### Scenario: Plain PLC
- **WHEN** the PLC has no CANbus and the project and CODESYS have only the standard CANbus
- **THEN** the script adds a CANbus and a CANopen Manager in the highest installed versions and sets network number, bit rate and manager settings

#### Scenario: Interface that takes only its vendor's CANbus
- **WHEN** the active device's `Communication/CAN` has no CANbus, accepts only a vendor CANbus, and another device of the same type in the project has that vendor CANbus
- **THEN** the script adds the vendor CANbus (not the standard one) under `CAN`, a CANopen Manager under it and the nodes, and the report names the vendor CANbus and the device it was taken from

#### Scenario: Vendor CANbus installed but not in the project
- **WHEN** no device in the project has a CANbus and the interface accepts only a vendor CANbus that is installed in CODESYS
- **THEN** the script adds that installed vendor CANbus after the refused tries, which leave nothing in the project

#### Scenario: CODESYS as a slave on that interface
- **WHEN** the matching CANbus holds a CANopen device object instead of a manager
- **THEN** that network stops with a message naming the CANbus, and other networks continue

#### Scenario: CAN interface under Communication
- **WHEN** the device has `Communication/CAN`, refuses a CANbus at its root and has no CANbus
- **THEN** the script adds a CANbus (or, if `CAN` refuses every CANbus, the CANopen Manager) under `CAN` and the report names `CAN` as the interface

### Requirement: Nodes from their DCF
For each node that is new in the project or replaced, the script SHALL install the node's DCF in CODESYS's device repository and add it under the manager before installing the next DCF, name the device after the node (or its carried CODESYS name), and apply the plan's device settings and carried CODESYS settings. PDO communication parameters, PDO mappings, heartbeat and guarding settings and startup SDOs of a new or replaced node SHALL come from the DCF.

#### Scenario: Three drives of one product
- **WHEN** nodes 4, 5 and 6 use the same EDS with different COB-IDs
- **THEN** each CODESYS device has its own node's COB-IDs and mapping

#### Scenario: Startup SDOs
- **WHEN** node 4 has startup SDOs 0x6065 = 20000 and 0x6098 = 21
- **THEN** the CODESYS device's SDO list writes both with those values

### Requirement: Variable names on I/O channels
The script SHALL name each planned channel's I/O mapping with the plan's variable name, finding the channel by direction, index and sub-index, unless the plan turns variable names off.

#### Scenario: Named input
- **WHEN** node `rtd` maps 0x7130 sub 1 to an input named `rtd_Temperature_1`
- **THEN** that I/O channel of device `rtd` maps a new variable `rtd_Temperature_1`

### Requirement: Re-runnable
Running the script again SHALL update each remote device under the network's manager that has the node ID of a node in the plan in place: it SHALL change only the settings whose project value differs from the plan, and SHALL leave every other setting of that device, including settings canworks does not manage, as it is. A device whose PDO mapping layout or user startup SDO list differs in structure from the plan (an entry or row added, removed, reordered or of another length) SHALL be replaced from its DCF instead, and then get the plan's carried CODESYS settings. Devices with node IDs not in the plan SHALL be kept unless the plan lists them for removal. It SHALL NOT add a second CANbus or manager for a network that already has one. The report SHALL list updated settings per device, replaced devices with the reason, added, removed and kept devices.

#### Scenario: Run twice
- **WHEN** the script runs twice on the same project and plan
- **THEN** the project has one CANbus, one manager and one device per node, and the second report says every device was up to date

#### Scenario: Event timer changed
- **WHEN** only TPDO1's event timer of node `rtd` changed from 100 to 200 ms in the config
- **THEN** that value is the only change in the project, and a fixed I/O address set in CODESYS on another `rtd` channel is kept

#### Scenario: Mapping entry added
- **WHEN** an entry was added to TPDO1 of `dio` in the config
- **THEN** `dio` is replaced from its DCF, its carried settings are written back, and the report names `dio` with "PDO mapping changed"

#### Scenario: Device added by hand
- **WHEN** the user added a device with node ID 20 that is not in the plan
- **THEN** it stays and the report lists it as not managed by canworks

#### Scenario: Node removed in canworks
- **WHEN** node 7 was built by canworks earlier and is no longer in the config, and the plan lists it for removal
- **THEN** device 7 is removed and the report says so

### Requirement: Settings found by id
The script SHALL find CANbus, manager and device settings by CODESYS's numeric parameter id. A missing parameter SHALL skip that setting with a report line and SHALL NOT stop the run. A parameter whose name differs from the plan's (CODESYS shows names in the user's language) SHALL be set and the difference noted in the report.

#### Scenario: Older manager without a setting
- **WHEN** the installed CANopen Manager has no parameter for the SYNC window
- **THEN** the other settings are applied and the report says the SYNC window was not set

### Requirement: Import report
The report SHALL list what was created, reused, replaced and skipped, every `not_carried` entry, and the build's errors and warnings. A failed step (a DCF that does not install, a device that cannot be added, a build error) SHALL be reported as an error, and a command-line run SHALL then not save the project.

#### Scenario: Variable name taken
- **WHEN** the project already declares a global `rtd_Temperature_1`
- **THEN** the report shows the build error naming it, and the command-line run does not save

### Requirement: Script runs on IronPython 2.7 and CPython 3
`import_canworks.py` SHALL use only the CODESYS scripting API and the Python standard library, in syntax both IronPython 2.7 and CPython 3 accept, so CI runs it under CPython against a stand-in for the CODESYS API.

#### Scenario: CI
- **WHEN** CI runs the script under CPython 3 with the stand-in API and the virtual-plant plan
- **THEN** it creates the recorded tree and settings and reports no error

### Requirement: Numbers written as strings in the export
The CODESYS export SHALL read every number of the config (PDO numbers, node IDs, COB-IDs, indexes) as the config contract does, so a number written as a string gives the same project as the plain number. A failure while naming I/O channels SHALL end the export with an error naming the node and PDO, never with an empty channel list.

#### Scenario: PDO number and node ID as strings
- **WHEN** a config has `"number": "1"` on a TPDO and `"node_id": "0x02"`
- **THEN** the export gives the same CODESYS project and channel names as with `1` and `2`

### Requirement: Choosing among several CAN interfaces
A network's CAN interface object SHALL be the object the plan names, else the device's only CAN interface object, else the device itself when it has none. When the device has several CAN interface objects and the plan names none for a network, the script SHALL use the one whose name ends in the network number; when none or several match, that network SHALL stop with the list of interfaces and the option that names one, and other networks SHALL continue.

#### Scenario: Two interfaces
- **WHEN** the device has `CAN1` and `CAN2`, the network has number 2 and no interface is named
- **THEN** the bus goes under `CAN2`

### Requirement: Nowhere to add the bus
When neither a CANbus nor a CANopen Manager can be added under the chosen interface, the network SHALL stop with an error naming that object, its device type and CODESYS's message, listing each CANbus device it tried with CODESYS's answer, and listing the device's other objects, instead of only CODESYS's exception.

#### Scenario: Refused everywhere
- **WHEN** CODESYS refuses every CANbus and a manager under the chosen object
- **THEN** the report's error names the object, the CANbus devices tried and CODESYS's messages, and lists the device's objects

### Requirement: Same network on another device
When other top-level devices than the chosen one have a CANopen Manager on a CANbus with the same network number as a planned network, the report SHALL give one warning for that network naming those devices (the first five, then how many more), and the script SHALL leave those devices unchanged.

#### Scenario: Active device switched between runs
- **WHEN** the script ran with `PLC` active, the user makes `HMI` active and runs it again
- **THEN** `HMI` gets the bus, `PLC` keeps its manager and nodes, and the report warns that `PLC` has a manager on the same network number

#### Scenario: Many variant devices
- **WHEN** the project has 23 devices, 22 of them not chosen and each with a CANopen Manager on network number 0
- **THEN** the report has one warning for network number 0 naming five of them and "and 17 more"

### Requirement: Bit channels in the CODESYS export
The plan SHALL list each channel's bit channels with bit number and variable name, named as the editor declarations would name them. The script SHALL map each to the bit sub-channel of the channel's I/O mapping. An output channel with bit channels SHALL get variables on its bits only, its own variable left unset, since CODESYS refuses overlapping output mappings; an input channel SHALL get both. If the CODESYS project gives no access to a channel's bit sub-channels, its report SHALL name the bits left to map by hand.

#### Scenario: Named bit in the plan
- **WHEN** a CODESYS config's node `panel` maps 0x6000:1 with bit 3 named `jog_x_plus`
- **THEN** the plan's channel for input 0x6000 sub 1 of `panel` lists bit 3 with variable `panel_jog_x_plus`

#### Scenario: Output bits only
- **WHEN** node `dio`'s RPDO entry 0x6200:1 has bits 1 and 6 named `lamp` and `horn`
- **THEN** the script sets `dio_lamp` and `dio_horn` on the channel's bits 1 and 6, leaves the channel's own variable unset, and the report says the output goes through its bits

### Requirement: Settings that do not carry over to CODESYS
Every set config value that the relevance table of `canopen-config-contract` marks as not used by CODESYS SHALL be in the plan's `not_carried` list with where it is set and the table's reason, the same text the check's warning gives.

#### Scenario: Bridge-only status location
- **WHEN** node `rtd` has `emcy_code_location` `%IW20`
- **THEN** `not_carried` lists `emcy_code_location` for `field/rtd` with the reason the check gives for it

### Requirement: Unique object names
Every CANbus, CANopen Manager and node object the script adds SHALL get a name that no other object under the same top-level device uses, adding `_2`, `_3`, ... to the base name when it is taken anywhere in that device's tree, because CODESYS refuses a name used elsewhere in it. Other top-level devices of the project MAY use the same names.

#### Scenario: Three networks
- **WHEN** a config with networks `io`, `motion` and `host` is built into a new project with one PLC
- **THEN** all three networks are added, their managers are named `CANopen_Manager`, `CANopen_Manager_2` and `CANopen_Manager_3`, and the report has no error

#### Scenario: Node name taken in another network
- **WHEN** two networks each have a node named `drive`
- **THEN** the second CODESYS device is named `drive_2` and the build has no error

### Requirement: Carried CODESYS settings written back
The script SHALL write a node's carried CODESYS settings: the device name, "processed by the manager" per PDO, fixed I/O addresses and variable names per entry and abort-on-error / jump-to-line per user startup SDO. It SHALL set the identity-check ticks, and the manager's TIME producer when the master has a TIME COB-ID, when this CODESYS lets the script change them, and otherwise SHALL report which to set by hand.

#### Scenario: Identity checks
- **WHEN** node `dio` has `"codesys": {"checks": ["vendor", "revision"]}`
- **THEN** the CODESYS device checks vendor ID and revision at startup and not product code, or the report names the ticks to set

### Requirement: PDO COB-IDs follow the node ID
The script SHALL write each PDO COB-ID through CODESYS's generic COB-ID setting, as `$NODEID+16#…` when it equals the EDS's node-based default for that PDO and as the literal value otherwise, so a later node ID change in CODESYS moves default COB-IDs with it.

#### Scenario: Node ID changed in canworks
- **WHEN** node `rtd` moves from node ID 5 to 6 and its TPDO1 uses the default COB-ID
- **THEN** after the build its TPDO1 COB-ID is 0x186

### Requirement: DCF mapping as CODESYS reads it
The DCFs written for CODESYS SHALL set every PDO mapping sub-entry beyond the mapped count that has a non-zero default to 0, because CODESYS maps every sub-entry with a value regardless of the count.

#### Scenario: Shorter mapping than the EDS default
- **WHEN** a TPDO's EDS default maps 4 entries and the config maps 2
- **THEN** the DCF gives sub-entries 3 and 4 the value 0, and CODESYS shows 2 mapped entries

### Requirement: CAN bus object named after the network
The CODESYS build and export SHALL name each CAN bus object after its canworks network.

#### Scenario: One network
- **WHEN** a config with one network "field" is built into CODESYS
- **THEN** the CAN bus object is named "field"
