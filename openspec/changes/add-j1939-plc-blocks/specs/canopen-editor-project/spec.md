## RENAMED Requirements

- FROM: `### Requirement: SDO blocks in a new project`
- TO: `### Requirement: Function blocks in a new project`

## MODIFIED Requirements

### Requirement: Function blocks in a new project
Creating a project with the blocks option (`--blocks`) SHALL enable the `canworks` function block library in the project, in the form the editor itself writes when the user enables a library, so the project's library tree shows all of its blocks (`CO_*`, `CO402_*`, `CAN_*`, `J1939_*`). The option `--sdo-blocks` SHALL no longer exist. Without `--blocks` the project SHALL enable no library unless the config needs it (a cyclic CiA 402 axis). When the editor on the same computer has no `canworks` library, or an older version, creation SHALL install the tools' version into it as `canworks-deploy library --install` does. When that is not possible (the editor has not run on this computer), creation SHALL still succeed and SHALL say how to install the library. The output SHALL call it the canworks function block library.

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
