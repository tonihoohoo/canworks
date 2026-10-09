## MODIFIED Requirements

### Requirement: SDO blocks in a new project
Creating a project with the blocks option (`--blocks`) SHALL enable the library `canworks` in the project, in the form the editor itself writes when the user enables a library, so the project's library tree shows the `CO_SDO_*` and `CAN_*` blocks. The option `--sdo-blocks` SHALL no longer exist. Without `--blocks` the project SHALL enable no library unless the config needs it (a cyclic CiA 402 axis). When the editor on the same computer has no `canworks` library, or an older version, creation SHALL install the tools' version into it as `canworks-deploy library --install` does. When that is not possible (the editor has not run on this computer), creation SHALL still succeed and SHALL say how to install the library.

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

## ADDED Requirements

### Requirement: Declarations for raw messages
The located variable declarations of a project SHALL include every raw message location: signals as `<message>_<signal>` (prefixed with the network name when the config has several networks), and the status, counter, identifier, DLC, data, trigger and enable locations as `<message>_status`, `_counter`, `_id`, `_dlc`, `_data`, `_trigger` and `_enable`. A signal's comment SHALL give its scale, offset and unit when set.

#### Scenario: Signal with scaling
- **WHEN** raw message `Joystick` has signal `X` at `%IW304` with scale 0.1 and unit `%`
- **THEN** the declarations hold `Joystick_X AT %IW304 : INT;` with a comment giving scale 0.1, offset 0 and unit %
