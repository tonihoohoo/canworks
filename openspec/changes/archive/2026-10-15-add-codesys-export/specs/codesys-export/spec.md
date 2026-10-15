## ADDED Requirements

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
The plan SHALL hold, per node, its node ID, a name that is a valid IEC 61131-3 identifier, its DCF path, its CODESYS device settings (node ID, optional or mandatory, do not initialize, restore before configuring, SDO timeout) and its PDO channels with PDO mapping object, index, sub-index and variable name. Variable names SHALL be the names the editor declarations use for the same locations.

#### Scenario: Variable names match the editor
- **WHEN** node `dio` maps 0x6000 sub 1 to `%IB8` and the editor declarations name that location `dio_Read_input_8_bit_1`
- **THEN** the plan's channel for input 0x6000 sub 1 of `dio` has that variable name

### Requirement: CODESYS network number
A network's CODESYS network number SHALL come from the user's override for that network when given, else the interface's trailing number, else 0 with a `not_carried` note.

#### Scenario: Number from the interface
- **WHEN** network `field` runs on `can1` and no override is given
- **THEN** the plan gives `field` network number 1

#### Scenario: Override
- **WHEN** the user gives `field=0` for a network on `can1`
- **THEN** the plan gives `field` network number 0

### Requirement: Settings that do not carry over
Every config setting without a CODESYS counterpart SHALL be in the plan's `not_carried` list with where it is set and why.

#### Scenario: Plugin-only status location
- **WHEN** node `rtd` has `emcy_code_location` `%IW20`
- **THEN** `not_carried` lists `emcy_code_location` for `field/rtd`

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
The script SHALL use the PLC device already in the project: the only device that can take a CANbus, or the one the plan names. Several candidates without a name SHALL stop the run with a list of them. The script SHALL NOT depend on a particular PLC type or CODESYS install path.

#### Scenario: Two PLCs
- **WHEN** the project has two PLC devices and the plan names none
- **THEN** the script stops, names both and changes nothing

### Requirement: Reuses the device's CAN interfaces
For each network the script SHALL use an existing CANbus anywhere under the PLC whose network number equals the plan's, and an existing CANopen Manager under it; only when none exists SHALL it add one, in the highest version installed in that CODESYS or the version of a CANbus the PLC already has. It SHALL then set the CANbus bit rate and the manager settings from the plan.

#### Scenario: Device that ships its CAN interfaces
- **WHEN** the project's PLC already has CANbus objects with network numbers 0 and 1 and the plan's network has number 1
- **THEN** the script adds the manager and nodes under the existing CANbus with number 1 and adds no CANbus

#### Scenario: Plain PLC
- **WHEN** the PLC has no CANbus
- **THEN** the script adds a CANbus and a CANopen Manager in the highest installed versions and sets network number, bit rate and manager settings

#### Scenario: CODESYS as a slave on that interface
- **WHEN** the matching CANbus holds a CANopen device object instead of a manager
- **THEN** that network stops with a message naming the CANbus, and other networks continue

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
- **WHEN** CI runs the script under CPython 3 with the stand-in API and the gantry-cell plan
- **THEN** it creates the recorded tree and settings and reports no error
