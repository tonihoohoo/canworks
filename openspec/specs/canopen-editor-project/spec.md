# canopen-editor-project Specification

## Purpose
An OpenPLC Editor project created from a CANopen config: made with the editor's own `openplc-cli create`, targeting OpenPLC Runtime v4, with the config in its `canworks/` folder and every CANopen location declared in the program `main`.

## Requirements

### Requirement: Project files
Creating an editor project from a CANopen config SHALL create the project with the installed editor's own New Project command (`openplc-cli create`, Structured Text), so its files and the editor's project history are the editor's own, and SHALL then change only the device configuration's target, `pous/programs/main.st`, the `canworks/` folder and, when the SDO blocks are asked for, the project's list of enabled libraries. The project name SHALL be the folder name. Without a working `openplc-cli` creation SHALL be refused, saying how to install it, and nothing SHALL be written. On Windows `openplc-cli` SHALL run without opening a console window. When Windows refuses to replace one of the new project's files because another program holds it open, creation SHALL try again for about 5 seconds and then write that file in place.

#### Scenario: Files written
- **WHEN** a project is created at `~/workspace/rtd-monitor` from the RTD sensor config
- **THEN** that folder holds what `openplc-cli create rtd-monitor --path ~/workspace` writes, plus `canworks/`, with `main.st` and the target replaced, and `project.json` names the project `rtd-monitor`

#### Scenario: Editor CLI missing
- **WHEN** `openplc-cli` is not on PATH and `$OPENPLC_CLI` is not set
- **THEN** creation is refused with a message pointing to `openplc-cli install-cli` (or `$OPENPLC_CLI`) and no folder is created

#### Scenario: Opens in the editor
- **WHEN** the created project is opened in OpenPLC Editor 4.3.2
- **THEN** it opens with the program `main` and no error, appears in the editor's recent projects, and Build only succeeds for the target OpenPLC Runtime v4

#### Scenario: No console window on Windows
- **WHEN** a project is created on Windows from the configurator
- **THEN** no Command Prompt window appears while `openplc-cli` runs

#### Scenario: New file held open briefly
- **WHEN** another program holds the new `devices/configuration.json` open for 2 seconds after `openplc-cli create` returns
- **THEN** creation still succeeds and the file names the target OpenPLC Runtime v4

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
The project SHALL get the config and its EDS and program files in its `canworks/` folder exactly as moving a standalone config into a project writes them, and creation SHALL be refused when the config does not pass the checks moving it would run.

#### Scenario: Config copied
- **WHEN** a project is created from a config with node 5 using `rtd8.eds`
- **THEN** the project's `canworks/` holds `canworks.json` and `rtd8.eds`, as "move into project" would write them

#### Scenario: Invalid config
- **WHEN** the config has an error
- **THEN** creation is refused with that error and no project folder is created

### Requirement: Order and descriptions
Declarations in `main` SHALL be ordered master diagnostics first, then node by node in config order; within a node: diagnostic inputs, PDO inputs, SDO variable inputs, then PDO outputs, SDO variable outputs and the NMT command byte. Each declaration SHALL carry a one-line comment that the editor shows as the variable's description, naming the node and the source (PDO and object index:subindex with the EDS name, SDO variable, or diagnostic).

#### Scenario: Two nodes
- **WHEN** the config has node `rtd` (inputs only) then node `valve` (status bit and outputs)
- **THEN** all `rtd_` declarations come before the `valve_` ones, and `valve_ok` comes before the valve outputs

#### Scenario: Description
- **WHEN** `rtd_AI0_Input_PV` is mapped from TPDO1
- **THEN** its line ends with a comment naming node `rtd`, TPDO1, the object's index:subindex and its EDS name, and the editor lists that text as the variable's description

### Requirement: Never overwrite
Creating a project SHALL NOT change any existing file. It SHALL be refused when the target folder has `project.json`, `canworks.json`, a `canworks/` folder or any file the editor's New Project writes (`devices/configuration.json`, `devices/pin-mapping.json`, `pous/programs/main.st`), naming that file. An existing folder without them SHALL become the project, and its other files SHALL be left as they were. A failure after the editor wrote files SHALL remove what creation added: the whole folder when creation made it, else only the files and folders creation added.

#### Scenario: Folder exists
- **WHEN** the target folder already has `project.json`
- **THEN** creation is refused naming the file and nothing in the folder changes

#### Scenario: Existing empty folder
- **WHEN** the target folder exists and is empty
- **THEN** the project is created in it

#### Scenario: Existing folder with other files
- **WHEN** the target folder holds only `notes.txt`
- **THEN** the project is created in it and `notes.txt` is unchanged

#### Scenario: Failure after create
- **WHEN** writing `canworks/` fails after `openplc-cli create` succeeded in a folder creation made
- **THEN** the new project folder is removed and the error is shown

#### Scenario: Failure in an existing folder
- **WHEN** writing `canworks/` fails after `openplc-cli create` succeeded in an existing folder that held `notes.txt`
- **THEN** the folder holds only `notes.txt` again and the error is shown

### Requirement: Function blocks in a new project
Creating a project with the blocks option (`--blocks`) SHALL enable the `canworks` function block library in the project, in the form the editor itself writes when the user enables a library, so the project's library tree shows all of its blocks and functions (`CO_*` over the bridge, `CW_*`, `CAN_*`, `J1939_*` helpers). The option `--sdo-blocks` SHALL no longer exist. Without `--blocks` the project SHALL enable the library only when its generated programs need it (the word helpers of `canworks_in`/`canworks_out`). When the editor on the same computer has no `canworks` library, or an older version, creation SHALL install the tools' version into it as `canworks-deploy library --install` does. When that is not possible (the editor has not run on this computer), creation SHALL still succeed and SHALL say how to install the library. The output SHALL call it the canworks function block library.

#### Scenario: Option given
- **WHEN** a project is created with `--blocks` and the library is installed in the editor
- **THEN** opening the project in OpenPLC Editor 4.3.2 shows `canworks` enabled with its blocks, and Build only succeeds

#### Scenario: Library not installed yet
- **WHEN** a project is created with `--blocks` on a PC whose editor does not have the library
- **THEN** the project is created with the library enabled, the library is installed into the editor, and the output says so

#### Scenario: No editor settings on this computer
- **WHEN** a project is created with `--blocks` on a PC where the editor has never run
- **THEN** the project is created with the library enabled and the output says how to install the library

#### Scenario: Old option
- **WHEN** a project is created with `--sdo-blocks`
- **THEN** the command fails as for any unknown option

### Requirement: Variable names with several networks
With several networks, every declared variable name SHALL start with its network's name and an underscore, and each variable's description SHALL name the network. With one network, names and descriptions SHALL stay as they are.

#### Scenario: Same node name on two networks
- **WHEN** networks `io` and `drives` each have a node named `door` with a status location
- **THEN** main declares `io_door_ok` and `drives_door_ok`

### Requirement: Declarations for slave bindings
The located variable declarations and the generated editor project SHALL include one variable per slave binding and status location, named from the object's `name` (or its EDS parameter name), prefixed with the network name, with the IEC type matching the location size.

#### Scenario: Slave declarations
- **WHEN** network `line` binds 0x2000:1 (UNSIGNED16) named `speed_setpoint` to `%IW300`
- **THEN** the declarations contain `line_speed_setpoint AT %IW300 : UINT;`

### Requirement: Declarations for raw messages
The located variable declarations of a project SHALL include every raw message location: signals as `<message>_<signal>` (prefixed with the network name when the config has several networks), and the status, counter, identifier, DLC, data, trigger and enable locations as `<message>_status`, `_counter`, `_id`, `_dlc`, `_data`, `_trigger` and `_enable`. A signal's comment SHALL give its scale, offset and unit when set.

#### Scenario: Signal with scaling
- **WHEN** raw message `Joystick` has signal `X` at `%IW304` with scale 0.1 and unit `%`
- **THEN** the declarations hold `Joystick_X AT %IW304 : INT;` with a comment giving scale 0.1, offset 0 and unit %

### Requirement: Declarations for bit channels
The located variable declarations and `main` of a new editor project SHALL declare one `BOOL` per located bit channel, right after its entry's declaration (or where it would be when the entry has no location), named `<node>_<name>`, or `<node>_<entry part>_bit<n>` without a `name`, where the entry part is the entry's `name` or its EDS name as the entry's own declaration uses it. With several networks the network prefix SHALL apply as for other names. The comment SHALL name the node, the PDO, the object's index:subindex and the bit number; it SHALL NOT take text from the device notes, so a note edit never changes the declarations.

#### Scenario: Named bit
- **WHEN** node `panel` maps bit 3 of 0x6000:1 to `%IX140.3` with `name` `jog_x_plus`
- **THEN** the declarations contain `panel_jog_x_plus AT %IX140.3 : BOOL;`

#### Scenario: Default name
- **WHEN** node `panel` maps bit 3 of 0x6000:1, which the EDS names "Read input 8 bit 1", to `%IX140.3` without a name
- **THEN** the declarations contain `panel_Read_input_8_bit_1_bit3 AT %IX140.3 : BOOL;`

### Requirement: Modbus I/O in an OpenPLC project
An editor project created for, or saved from, a config with an OpenPLC connection SHALL get:
- the remote device file of `modbus-bridge-map`;
- a global variable list `canworks` (one global of that name, its members used as `canworks.<name>`) with `ok : BOOL`, `link : ARRAY[0..1279] OF WORD` (the blocks' view of the bridge's status, control, SDO and live list registers and of its mailboxes, "Requirement: Link array for mailboxes") and one member per located value, named as the declarations name it, typed from the value's CANopen or signal type (BOOL for bits, SINT, USINT, INT, UINT, DINT, UDINT, LINT, ULINT, REAL, LREAL, BYTE, WORD, DWORD, LWORD);
- a program `canworks_in` that converts the input words into those variables (32- and 64-bit values from two or four words, lowest word first; REAL and LREAL through the library's `CW_DWORD_TO_REAL` and `CW_LWORD_TO_LREAL`), fills `canworks.link` and sets `canworks.ok` while the bridge's status counter changed within max(300 ms, 3 × `watchdog_ms`) and the bridge's map hash equals the program's;
- a program `canworks_out` that converts the output members and `canworks.link`'s requests into words and then writes the PLC link header with running 1 and the map hash;
- the instances `canworks_in`, the user's `main`, `canworks_out`, in that order, in the project's task, and the `canworks` library enabled.
The raw `%IW`/`%QW` words SHALL be declared only inside `canworks_in` and `canworks_out`. Saving SHALL rewrite only the list, the two programs, the remote device file and the task instances it added; the user's POUs SHALL NOT change, except `main` when the user asks for it with **Use canworks.\* in main** (`canopen-configurator`, "Old located variables in an OpenPLC project's main"). No `VAR` block of located variables SHALL be written into `main` for such a project.

#### Scenario: 32-bit value
- **WHEN** node `enc` maps an UNSIGNED32 position and the bridge serves 0x00012345
- **THEN** `canworks.enc_position` reads 74565 in the program after `canworks_in` ran

#### Scenario: Bridge down
- **WHEN** the bridge stops while the PLC runs
- **THEN** `canworks.ok` becomes FALSE within max(300 ms, 3 × `watchdog_ms`) plus one poll

#### Scenario: Build
- **WHEN** a project is created from the shipped OpenPLC example config and built with OpenPLC Editor 4.3.2's Build only
- **THEN** the build succeeds and its `conf/modbus_master.json` lists the canworks device

#### Scenario: Save keeps main
- **WHEN** a switched plugin project whose `main` declares located canworks values is saved
- **THEN** `main.st` is unchanged and the Project page offers **Use canworks.\* in main**

### Requirement: Link array for mailboxes
In an editor project for a config with an OpenPLC connection, `canworks.link` SHALL be declared `ARRAY[0..1279] OF WORD`. `canworks_in` SHALL copy the response blocks, receive mailbox, network info and cyclic table into their `LINK` places, set the mailbox flags from the config and then call `CW_LINK_SERVICE(LINK := canworks.link)` before any user code runs; `canworks_out` SHALL copy the request blocks, receive acknowledgement and keepalives from `LINK` to their holding registers before writing the PLC link header. Words of blocks the config does not have SHALL stay 0. Update declarations SHALL rewrite the declaration and both programs when `mailboxes` changes.

#### Scenario: Mailboxes added later
- **WHEN** the user turns on the Function blocks section of an existing OpenPLC project and runs Update declarations
- **THEN** the remote device file, `canworks_in`, `canworks_out` and the map hash constant are rewritten, the user's POUs are unchanged, and the project builds
