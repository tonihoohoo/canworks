## ADDED Requirements

### Requirement: Library delivery
The `canworks` function block library SHALL be built from its editor library project in this repository into `canworks.stlib`. It SHALL hold the SDO blocks and `CO_RECV_EMCY` of `canopen-plc-sdo`, the NMT blocks of `canopen-plc-nmt`, the CiA 402 blocks, the CAN frame blocks and helper functions of `can-plc-frames`, the J1939 trouble code blocks and functions of `j1939-plc-diagnostics`, and the J1939 message blocks and functions of `j1939-plc-blocks`. Each `deploy-v` release SHALL carry that file, `canworks-deploy library --out DIR` SHALL write the copy that matches the installed tools into `DIR`, `canworks-deploy library --install` SHALL install that copy into OpenPLC Editor on the same computer as the editor's Library Manager does, `canworks-deploy library --project DIR` SHALL enable it in an editor project, and `canworks-deploy library --list` SHALL list its blocks and functions. The library's version SHALL equal the deploy package version. Installing it once with the editor's Library Manager ("install from file") SHALL make the blocks appear in the editor's library tree for every project that enables it.

#### Scenario: Install in the editor
- **WHEN** the user runs `canworks-deploy library --out .` and installs the written file in OpenPLC Editor 4.3.2
- **THEN** the library tree lists `canworks` with the `CO_*`, `CO402_*`, `CAN_*` and `J1939_*` blocks, and a project that enables it and calls `CO_SDO_READ`, `CO_RECV_EMCY`, `CAN_RECEIVE`, `J1939_DM_READ` and `J1939_SEND` builds for OpenPLC Runtime v4

#### Scenario: Install from the command line
- **WHEN** the user runs `canworks-deploy library --install` on a PC where OpenPLC Editor has run, then restarts the editor
- **THEN** the editor's library list shows `canworks` with the tools' version, and libraries installed before are still listed

### Requirement: One library for every protocol
The library SHALL be presented as one general function block library for CANopen, CAN and J1939, not as a CANopen or SDO library. `canworks-deploy library --help`, the project creation output, the configurator and the documentation SHALL describe it by what it holds as a whole ("the canworks function block library"), and SHALL name a protocol or block family only where the text is about that family. The PC tools' module that writes, installs and enables it SHALL be named for the library (`plclibrary`), not for SDO.

#### Scenario: Help text
- **WHEN** the user runs `canworks-deploy library --help`
- **THEN** the description names the CANopen, CiA 402, CAN frame and J1939 blocks and points to `docs/plc-library.md`

#### Scenario: Project created with the blocks
- **WHEN** a project is created with `--blocks`
- **THEN** the output says that the project enables the canworks function block library, without naming only the SDO or CAN blocks

### Requirement: Library documentation
`docs/plc-library.md` SHALL be the library's page: the block families with what each is for and a link to its reference (SDO and EMCY: `plc-sdo.md`; NMT: `plc-nmt.md`; CiA 402: `cia402.md`; CAN frames and helpers: `raw-can.md`; J1939: `j1939.md`), installing and enabling the library, the shared `EXECUTE`/`ENABLE` handshakes, and which plugin interface version each family needs with what happens on an older plugin. The family pages SHALL link to it for installing instead of repeating it. README SHALL link to it as the place for the program's blocks.

#### Scenario: Reader looks for J1939 blocks
- **WHEN** a user opens `docs/plc-library.md`
- **THEN** it lists the J1939 message and trouble code blocks with a link to their reference in `docs/j1939.md`

### Requirement: Interface versions per block family
Each block family SHALL ask the loaded plugin for its own interface (`canopen_plc_api`, `canopen_plc_nmt_api`, `canworks_can_api`, `canworks_j1939_api`) at the version it was built for, and the plugin SHALL keep offering every earlier version it offered, so a program keeps working when the plugin is updated. A block whose interface version the plugin does not offer SHALL end with that family's "not running" error and SHALL NOT affect blocks of other families or versions.

#### Scenario: Mixed versions
- **WHEN** a program calls `CO_SDO_READ` (CANopen interface 1), `CO_RECV_EMCY` (CANopen interface 2) and `J1939_SEND` (J1939 interface 2) on a plugin that offers all of them
- **THEN** all three work
