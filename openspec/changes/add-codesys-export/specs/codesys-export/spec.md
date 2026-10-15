## ADDED Requirements

### Requirement: Export folder for CODESYS
The CODESYS export SHALL write a folder holding: one subfolder per exported network with that network's node DCFs exactly as `canopen-dcf-export` writes them, a plan file `canworks-codesys.json`, the script `import_canworks.py` (the same file for every config) and a `README.txt` saying how to run it. It SHALL be built on the PC from the config and its EDS files alone. Only master CANopen networks SHALL be exported; slave, gateway, J1939 and plain CAN networks and raw messages SHALL be listed in the plan's `not_carried` list. A config that fails the deploy tool's checks or a DCF that fails validation SHALL stop the export with those messages and write nothing.

#### Scenario: One network, two nodes
- **WHEN** a valid config has network `field` with nodes 5 and 6
- **THEN** the folder has `field/node_5.dcf`, `field/node_6.dcf`, `canworks-codesys.json`, `import_canworks.py` and `README.txt`, and the DCFs equal the `--export-dcf` files for the same config

#### Scenario: J1939 network next to CANopen
- **WHEN** the config also has a J1939 network `engine`
- **THEN** no folder is written for `engine` and the plan's `not_carried` names it

### Requirement: The plan carries every setting the script applies
The plan SHALL hold, per exported network: its name, CODESYS network number, bit rate in kbit/s and the CANopen Manager settings (node ID, heartbeat producer time, SYNC on/off, period and window, autostart and start behaviour); and per node: node ID, a name that is a valid IEC 61131-3 identifier, its DCF path, optional or mandatory, which identity fields to check at boot, heartbeat consumption or node guarding, and its PDO channels with direction, index, sub-index and variable name. Variable names SHALL be the names the editor declarations use for the same locations. The network number SHALL come from the user's override for that network when given, else the interface's trailing number, else 0 with a `not_carried` note. Every config setting without a CODESYS counterpart SHALL be in `not_carried` with where it is set and why.

#### Scenario: Network number from the interface
- **WHEN** network `field` runs on `can1` and no override is given
- **THEN** the plan gives `field` network number 1

#### Scenario: Override
- **WHEN** the user gives `field=0` for a network on `can1`
- **THEN** the plan gives `field` network number 0

#### Scenario: Plugin-only status location
- **WHEN** node `rtd` has `emcy_code_location` `%IW20`
- **THEN** `not_carried` lists `emcy_code_location` for `field/rtd`

#### Scenario: Variable names match the editor
- **WHEN** node `dio` maps 0x6000 sub 1 to `%IB8` and the editor declarations name that location `dio_Read_input_8_bit_1`
- **THEN** the plan's channel for input 0x6000 sub 1 of `dio` has that variable name

### Requirement: Run in the CODESYS IDE on the open project
Run from CODESYS's script menu, the script SHALL work on the project open in the IDE, read the plan next to itself, apply it as the following requirements describe, write `import_report.txt` next to itself, show the report in CODESYS's message view, and SHALL NOT save the project. With no project open it SHALL stop with a message and change nothing.

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

### Requirement: Works on the user's PLC and its CAN interfaces
The script SHALL use the PLC device already in the project: the only device that can take a CANbus, or the one the plan names; several without a name SHALL stop with a list of the candidates. For each network it SHALL use an existing CANbus anywhere under that PLC whose network number equals the plan's, and an existing CANopen Manager under it; only when none exists SHALL it add one. Added CANbus and CANopen Manager objects SHALL use the highest version installed in that CODESYS, or the version of a CANbus the PLC already has. The script SHALL NOT depend on a particular PLC type, CODESYS install path or device version. It SHALL then set the CANbus bit rate and the manager settings from the plan.

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
For each node the script SHALL install the node's DCF in CODESYS's device repository and add it under the manager before installing the next DCF, name the device after the node, and set its node ID, optional flag, identity checks and supervision. The node's PDO communication parameters, PDO mappings, heartbeat producer time and startup SDOs SHALL come from the DCF; the script SHALL NOT rewrite them. When it names a channel it SHALL find it by direction, index and sub-index.

#### Scenario: Three drives of one product
- **WHEN** nodes 4, 5 and 6 use the same EDS with different COB-IDs
- **THEN** each CODESYS device has its own node's COB-IDs and mapping

#### Scenario: Startup SDOs
- **WHEN** node 4 has startup SDOs 0x6065 = 20000 and 0x6098 = 21
- **THEN** the CODESYS device's SDO list writes both with those values

#### Scenario: Variable names
- **WHEN** node `rtd` maps 0x7130 sub 1 to an input named `rtd_Temperature_1`
- **THEN** that I/O channel of device `rtd` maps a new variable `rtd_Temperature_1`

### Requirement: Re-runnable
Running the script again on a project it already changed SHALL replace each remote device under the network's manager that has the node ID of a node in the plan, SHALL keep devices with other node IDs and SHALL list both in the report. It SHALL NOT add a second CANbus or manager for a network that already has one.

#### Scenario: Run twice
- **WHEN** the script runs twice on the same project and plan
- **THEN** the project has one CANbus, one manager and one device per node, and the second report names the replaced devices

#### Scenario: Device added by hand
- **WHEN** the user added a device with node ID 20 that is not in the plan
- **THEN** it stays and the report lists it as not managed by canworks

### Requirement: Settings found by id, failures reported
The script SHALL find CANbus, manager and device settings by CODESYS's numeric parameter id and check the parameter's name; a missing parameter or a different name SHALL skip that setting with a report line, not stop the run. The report SHALL list what was created, reused, replaced and skipped, every `not_carried` entry, and the build's errors and warnings. A step that fails (a DCF that does not install, a device that cannot be added, a build error) SHALL be reported as an error, and in a command-line run the project SHALL NOT be saved.

#### Scenario: Older manager without a setting
- **WHEN** the installed CANopen Manager has no parameter for the SYNC window
- **THEN** the other settings are applied and the report says the SYNC window was not set

#### Scenario: Variable name taken
- **WHEN** the project already declares a global `rtd_Temperature_1`
- **THEN** the report shows the build error naming it, and the command-line run does not save

### Requirement: Script runs on IronPython 2.7 and CPython 3
`import_canworks.py` SHALL use only the CODESYS scripting API and the Python standard library, in syntax both IronPython 2.7 and CPython 3 accept, so CI runs it under CPython against a stand-in for the CODESYS API.

#### Scenario: CI
- **WHEN** CI runs the script under CPython 3 with the stand-in API and the gantry-cell plan
- **THEN** it creates the recorded tree and settings and reports no error
