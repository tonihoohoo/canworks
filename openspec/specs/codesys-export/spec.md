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
The plan SHALL hold, per node, its node ID, a name that is a valid IEC 61131-3 identifier, its DCF path, its CODESYS device settings (node ID, optional or mandatory, do not initialize, restore before configuring, SDO timeout) and its PDO channels with PDO mapping object, index, sub-index and variable name. A channel SHALL be planned for every mapped PDO entry, with or without an IEC location. Variable names SHALL be the names the editor declarations give the same entries, using the entry's `name` when it has one.

#### Scenario: Variable names match the editor
- **WHEN** node `dio` maps 0x6000 sub 1 to `%IB8` and the editor declarations name that location `dio_Read_input_8_bit_1`
- **THEN** the plan's channel for input 0x6000 sub 1 of `dio` has that variable name

#### Scenario: Entry without a location
- **WHEN** a CODESYS config's node `dio` maps 0x6000 sub 1 with `name` `door_open` and no `iec_location`
- **THEN** the plan has a channel for input 0x6000 sub 1 of `dio` named `dio_door_open`

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

### Requirement: Settings that do not carry over
Every set config value that the relevance table of `canopen-config-contract` marks as not used by CODESYS SHALL be in the plan's `not_carried` list with where it is set and the table's reason, the same text the check's warning gives.

#### Scenario: Plugin-only status location
- **WHEN** node `rtd` has `emcy_code_location` `%IW20`
- **THEN** `not_carried` lists `emcy_code_location` for `field/rtd` with the reason the check gives for it

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
For each network the script SHALL use an existing CANbus anywhere under the PLC whose network number equals the plan's, and an existing CANopen Manager under it. Only when none exists SHALL it add one, in the highest version installed in that CODESYS or the version of a CANbus the PLC already has, under the network's CAN interface object, or add the CANopen Manager directly under that object when it refuses a CANbus. It SHALL then set the bit rate and the manager settings from the plan.

#### Scenario: Device that ships its CAN interfaces
- **WHEN** the project's PLC already has CANbus objects with network numbers 0 and 1 and the plan's network has number 1
- **THEN** the script adds the manager and nodes under the existing CANbus with number 1 and adds no CANbus

#### Scenario: Plain PLC
- **WHEN** the PLC has no CANbus
- **THEN** the script adds a CANbus and a CANopen Manager in the highest installed versions and sets network number, bit rate and manager settings

#### Scenario: CODESYS as a slave on that interface
- **WHEN** the matching CANbus holds a CANopen device object instead of a manager
- **THEN** that network stops with a message naming the CANbus, and other networks continue

#### Scenario: CAN interface under Communication
- **WHEN** the device has `Communication/CAN`, refuses a CANbus at its root and has no CANbus
- **THEN** the script adds the CANbus (or, if `CAN` refuses that, the CANopen Manager) under `CAN` and the report names `CAN` as the interface

### Requirement: Nodes from their DCF
For each node the script SHALL install the node's DCF in CODESYS's device repository and add it under the manager before installing the next DCF, name the device after the node, and apply the plan's device settings. PDO communication parameters, PDO mappings, heartbeat and guarding settings and startup SDOs SHALL come from the DCF; the script SHALL NOT rewrite them. Identity checks at boot SHALL be left to the user and named in the report.

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
Running the script again SHALL replace each remote device under the network's manager that has the node ID of a node in the plan, SHALL keep devices with other node IDs, and SHALL list both in the report. It SHALL NOT add a second CANbus or manager for a network that already has one.

#### Scenario: Run twice
- **WHEN** the script runs twice on the same project and plan
- **THEN** the project has one CANbus, one manager and one device per node, and the second report names the replaced devices

#### Scenario: Device added by hand
- **WHEN** the user added a device with node ID 20 that is not in the plan
- **THEN** it stays and the report lists it as not managed by canworks

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
When neither a CANbus nor a CANopen Manager can be added under the chosen interface, the network SHALL stop with an error naming that object, its device type and CODESYS's message, and listing the device's other objects, instead of only CODESYS's exception.

#### Scenario: Refused everywhere
- **WHEN** CODESYS refuses both a CANbus and a manager under the chosen object
- **THEN** the report's error names the object and CODESYS's message and lists the device's objects

### Requirement: Same network on another device
When another top-level device than the chosen one has a CANopen Manager on a CANbus with the same network number as a planned network, the report SHALL warn and name that device, and the script SHALL leave that device unchanged.

#### Scenario: Active device switched between runs
- **WHEN** the script ran with `PLC` active, the user makes `HMI` active and runs it again
- **THEN** `HMI` gets the bus, `PLC` keeps its manager and nodes, and the report warns that `PLC` has a manager on the same network number

### Requirement: Bit channels in the CODESYS export
The plan SHALL list each channel's bit channels with bit number and variable name, named as the editor declarations would name them. The script SHALL map each to the bit sub-channel of the channel's I/O mapping. An output channel with bit channels SHALL get variables on its bits only, its own variable left unset, since CODESYS refuses overlapping output mappings; an input channel SHALL get both. If the CODESYS project gives no access to a channel's bit sub-channels, its report SHALL name the bits left to map by hand.

#### Scenario: Named bit in the plan
- **WHEN** a CODESYS config's node `panel` maps 0x6000:1 with bit 3 named `jog_x_plus`
- **THEN** the plan's channel for input 0x6000 sub 1 of `panel` lists bit 3 with variable `panel_jog_x_plus`

#### Scenario: Output bits only
- **WHEN** node `dio`'s RPDO entry 0x6200:1 has bits 1 and 6 named `lamp` and `horn`
- **THEN** the script sets `dio_lamp` and `dio_horn` on the channel's bits 1 and 6, leaves the channel's own variable unset, and the report says the output goes through its bits
