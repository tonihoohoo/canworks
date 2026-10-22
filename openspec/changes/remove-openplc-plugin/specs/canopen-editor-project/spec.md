## MODIFIED Requirements

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

## REMOVED Requirements

### Requirement: CANopen I/O declared in main
**Reason**: Located variables in `main` addressed the plugin's image; an OpenPLC project now reaches canworks through the generated `canworks` variable list and `canworks_in`/`canworks_out` (Requirement: Modbus I/O in an OpenPLC project), and the axis lines go with CiA 402.
**Migration**: **Update declarations** or `canworks-deploy --into-project` writes the variable list and programs.
