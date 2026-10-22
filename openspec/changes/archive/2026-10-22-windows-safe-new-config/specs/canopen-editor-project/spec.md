## MODIFIED Requirements

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
