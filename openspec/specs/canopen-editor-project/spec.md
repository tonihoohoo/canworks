# canopen-editor-project Specification

## Purpose
An OpenPLC Editor project created from a CANopen config: made with the editor's own `openplc-cli create`, targeting OpenPLC Runtime v4, with the config in its `canopen/` folder and every CANopen location declared in the program `main`.

## Requirements

### Requirement: Project files
Creating an editor project from a CANopen config SHALL create the project with the installed editor's own New Project command (`openplc-cli create`, Structured Text), so its files and the editor's project history are the editor's own, and SHALL then change only the device configuration's target, `pous/programs/main.st`, the `canopen/` folder and, when the SDO blocks are asked for, the project's list of enabled libraries. The project name SHALL be the folder name. Without a working `openplc-cli` creation SHALL be refused, saying how to install it, and nothing SHALL be written.

#### Scenario: Files written
- **WHEN** a project is created at `~/workspace/rtd-monitor` from the RTD sensor config
- **THEN** that folder holds what `openplc-cli create rtd-monitor --path ~/workspace` writes, plus `canopen/`, with `main.st` and the target replaced, and `project.json` names the project `rtd-monitor`

#### Scenario: Editor CLI missing
- **WHEN** `openplc-cli` is not on PATH and `$OPENPLC_CLI` is not set
- **THEN** creation is refused with a message pointing to `openplc-cli install-cli` (or `$OPENPLC_CLI`) and no folder is created

#### Scenario: Opens in the editor
- **WHEN** the created project is opened in OpenPLC Editor 4.3.2
- **THEN** it opens with the program `main` and no error, appears in the editor's recent projects, and Build only succeeds for the target OpenPLC Runtime v4

### Requirement: Target, task and instance
The project SHALL target `OpenPLC Runtime v4` and SHALL have one cyclic task `task0` with the editor's default interval `T#20ms` and priority 1, running one instance `instance0` of the program `main`. The interval SHALL be settable when the project is created and SHALL accept only an IEC duration of at least 1 ms. When a runtime address is saved in the configurator's online settings for the config, the project SHALL carry it as the editor's runtime address.

#### Scenario: Defaults
- **WHEN** a project is created without choosing an interval
- **THEN** the device configuration names `OpenPLC Runtime v4` and the task interval is `T#20ms`

#### Scenario: Interval chosen
- **WHEN** the user creates the project with interval `T#10ms`
- **THEN** `task0` runs every `T#10ms`

#### Scenario: Bad interval
- **WHEN** the interval is `10ms` or `T#0ms`
- **THEN** creation is refused naming the interval and nothing is written

### Requirement: CANopen config in the project
The project SHALL get the config and its EDS and program files in its `canopen/` folder exactly as moving a standalone config into a project writes them, and creation SHALL be refused when the config does not pass the checks moving it would run.

#### Scenario: Config copied
- **WHEN** a project is created from a config with node 5 using `rtd8.eds`
- **THEN** the project's `canopen/` holds `canopen.json` and `rtd8.eds`, as "move into project" would write them

#### Scenario: Invalid config
- **WHEN** the config has an error
- **THEN** creation is refused with that error and no project folder is created

### Requirement: CANopen I/O declared in main
The program `main` SHALL declare, in one `VAR` block, a located variable for every location the config uses: mapped PDO entries, master and node diagnostic inputs, NMT command bytes and SDO variable locations, with the names and IEC types of the configurator's located variable declarations. Declarations SHALL use the editor's own form `name : TYPE AT location;`. For every axis node `main` SHALL also declare the axis, named after the node, of the library's axis type, and one drive bridge instance named `<node>_bridge`. The program body SHALL hold a comment saying the block came from `canopen/canopen.json`; when the config has axis nodes, the body SHALL start with generated lines that, for each axis in config order, set the axis's three scaling fields from the config and call its bridge with the axis, the node's mapped standard objects (only those mapped) and its status bit, and say they must stay first. Entries without a location SHALL be left out.

#### Scenario: RTD sensor
- **WHEN** a project is created from a config whose node `rtd` maps four INTEGER16 inputs at `%IW100` to `%IW103` and has status bit `%IX10.0`
- **THEN** `main` declares `rtd_ok : BOOL AT %IX10.0;` and four `INT` variables at `%IW100` to `%IW103`, and nothing else in its VAR block

#### Scenario: No locations
- **WHEN** the config has nodes but no locations at all
- **THEN** `main` has an empty `VAR` ... `END_VAR` block and the project is still created

#### Scenario: Axis node
- **WHEN** a project is created from a config whose node `drive` has `axis` with scale numerator 10 and maps 0x6040 at `%QW100` and 0x6041 at `%IW100`, with status bit `%IX10.0`
- **THEN** `main` declares `drive : AXIS_REF_SM3;` and `drive_bridge : SM_Drive_GenericDS402;` next to the located variables, and its body starts with lines setting `drive.iRatioTechUnitsNum` to 10 and calling `drive_bridge` with `Axis := drive`, the statusword variable, `bOnline :=` the status bit variable and `wControlWord =>` the controlword variable

#### Scenario: Axis project builds
- **WHEN** the example CiA 402 config's project is opened in OpenPLC Editor 4.3.2 and a program line `MC_Power(Axis := drive, Enable := TRUE)` is added
- **THEN** Build only succeeds for the target OpenPLC Runtime v4

### Requirement: Order and descriptions
Declarations in `main` SHALL be ordered master diagnostics first, then node by node in config order; within a node: diagnostic inputs, PDO inputs, SDO variable inputs, then PDO outputs, SDO variable outputs and the NMT command byte. Each declaration SHALL carry a one-line comment that the editor shows as the variable's description, naming the node and the source (PDO and object index:subindex with the EDS name, SDO variable, or diagnostic).

#### Scenario: Two nodes
- **WHEN** the config has node `rtd` (inputs only) then node `valve` (status bit and outputs)
- **THEN** all `rtd_` declarations come before the `valve_` ones, and `valve_ok` comes before the valve outputs

#### Scenario: Description
- **WHEN** `rtd_AI0_Input_PV` is mapped from TPDO1
- **THEN** its line ends with a comment naming node `rtd`, TPDO1, the object's index:subindex and its EDS name, and the editor lists that text as the variable's description

### Requirement: Never overwrite
Creating a project SHALL be refused when the target folder already exists, and SHALL NOT change any existing file. A failure after the editor created the folder SHALL remove that folder, leaving no partly written project behind.

#### Scenario: Folder exists
- **WHEN** the target folder already exists
- **THEN** creation is refused naming the folder and nothing in it changes

#### Scenario: Failure after create
- **WHEN** writing `canopen/` fails after `openplc-cli create` succeeded
- **THEN** the new project folder is removed and the error is shown

### Requirement: SDO blocks in a new project
Creating a project with the SDO blocks option (`--sdo-blocks`) SHALL enable the library `openplc_canopen` in the project, in the form the editor itself writes when the user enables a library, so the project's library tree shows the `CO_SDO_*` blocks. Without the option the project SHALL enable no library. When the editor on the same computer has no `openplc_canopen` library, or an older version, creation SHALL install the tools' version into it as `openplc-canopen-deploy library --install` does. When that is not possible (the editor has not run on this computer), creation SHALL still succeed and SHALL say how to install the library.

#### Scenario: Option given
- **WHEN** a project is created with `--sdo-blocks` and the library is installed in the editor
- **THEN** opening the project in OpenPLC Editor 4.3.2 shows `openplc_canopen` enabled with its eight blocks, and Build only succeeds

#### Scenario: Library not installed yet
- **WHEN** a project is created with `--sdo-blocks` on a PC whose editor does not have the library
- **THEN** the project is created with the library enabled, the library is installed into the editor, and the output says so

#### Scenario: No editor settings on this computer
- **WHEN** a project is created with `--sdo-blocks` on a PC where the editor has never run
- **THEN** the project is created with the library enabled and the output says how to install the library

### Requirement: Variable names with several networks
With several networks, every declared variable name SHALL start with its network's name and an underscore, and each variable's description SHALL name the network. With one network, names and descriptions SHALL stay as they are.

#### Scenario: Same node name on two networks
- **WHEN** networks `io` and `drives` each have a node named `door` with a status location
- **THEN** main declares `io_door_ok` and `drives_door_ok`
