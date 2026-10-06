## MODIFIED Requirements

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

## ADDED Requirements

### Requirement: SDO blocks in a new project
Creating a project with the SDO blocks option (`--sdo-blocks`) SHALL enable the library `openplc_canopen` in the project, in the form the editor itself writes when the user enables a library, so the project's library tree shows the `CO_SDO_*` blocks. Without the option the project SHALL enable no library. When the editor has no `openplc_canopen` library installed, creation SHALL still succeed and SHALL say how to install it (`openplc-canopen-deploy library --out DIR`, then the editor's Library Manager).

#### Scenario: Option given
- **WHEN** a project is created with `--sdo-blocks` and the library is installed in the editor
- **THEN** opening the project in OpenPLC Editor 4.3.2 shows `openplc_canopen` enabled with its eight blocks, and Build only succeeds

#### Scenario: Library not installed yet
- **WHEN** a project is created with `--sdo-blocks` on a PC whose editor does not have the library
- **THEN** the project is created with the library enabled and the output says how to install the library
