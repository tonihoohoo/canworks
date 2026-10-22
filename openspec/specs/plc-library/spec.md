# plc-library Specification

## Purpose
The `canworks` function block library as a whole: how it is built, delivered, installed and enabled, how it is presented across the tools and docs, and how each block family finds its plugin interface version.

## Requirements

### Requirement: Library delivery
The `canworks` function block library SHALL be built from its editor library project in this repository into `canworks.stlib`. It SHALL hold the blocks over the bridge (`CO_SDO_READ`, `CO_SDO_WRITE`, `CO_NMT`, `CO_NODE_LIVE`), the bit-exact ST conversions `CW_DWORD_TO_REAL`, `CW_REAL_TO_DWORD`, `CW_LWORD_TO_LREAL` and `CW_LREAL_TO_LWORD`, the cyclic CiA 402 ST blocks until `remove-openplc-plugin` removes CiA 402, and the pure ST helper functions of `can-plc-frames`, `j1939-plc-diagnostics` and `j1939-plc-blocks` (`CAN_GET_*`, `CAN_SET_*`, `CAN_J1939_*`, `J1939_GET_BITS`, `J1939_SET_BITS`, `J1939_DTC_*`, `J1939_NAME_*`). Blocks that call into the OpenPLC plugin SHALL NOT be in it. Each `deploy-v` release SHALL carry that file, `canworks-deploy library --out DIR` SHALL write the copy that matches the installed tools into `DIR`, `canworks-deploy library --install` SHALL install that copy into OpenPLC Editor on the same computer as the editor's Library Manager does, `canworks-deploy library --project DIR` SHALL enable it in an editor project, and `canworks-deploy library --list` SHALL list its blocks and functions. The library's version SHALL equal the deploy package version. Installing it once with the editor's Library Manager ("install from file") SHALL make the blocks appear in the editor's library tree for every project that enables it.

#### Scenario: Install in the editor
- **WHEN** the user runs `canworks-deploy library --out .` and installs the written file in OpenPLC Editor 4.3.2
- **THEN** the library tree lists `canworks` with `CO_SDO_READ`, `CO_SDO_WRITE`, `CO_NMT`, `CO_NODE_LIVE` and the helper functions, and a project that enables it and calls `CO_SDO_READ` and `CO_NMT` builds for OpenPLC Runtime v4

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

### Requirement: Blocks over the bridge
`CO_SDO_READ` (EXECUTE, NETWORK, NODE, INDEX, SUBINDEX, TIMEOUT → BUSY, DONE, ERROR, ERROR_ID, ABORT_CODE, DATA : UDINT), `CO_SDO_WRITE` (EXECUTE, NETWORK, NODE, INDEX, SUBINDEX, DATA : UDINT, SIZE, TIMEOUT → BUSY, DONE, ERROR, ERROR_ID, ABORT_CODE), `CO_NMT` (EXECUTE, NETWORK, NODE, COMMAND, TIMEOUT → BUSY, DONE, ERROR, ERROR_ID) and `CO_NODE_LIVE` (NETWORK, NODE → LIVE) SHALL be ST blocks with an in-out `LINK : ARRAY[0..88] OF WORD` (the generated `canworks.link`). They SHALL work through the bridge's SDO bridge registers, control block and live lists with its counter handshake, with the PLCopen EXECUTE/BUSY/DONE/ERROR behaviour of today's blocks. Instances SHALL share the one SDO slot and the one control block: a block whose request finds the slot owned by another instance SHALL stay BUSY until the slot is free, and requests SHALL be served in the order they started. A write's SIZE SHALL be 1-4; a read returns the object's value in DATA, zero-extended. ERROR_ID SHALL keep today's codes, add 20 (bridge not reachable: `canworks.ok` false at start or during the request), 21 (SDO writes not allowed: abort 0x08000020 from the bridge) and 22 (the config has no SDO registers or control block for the request). The blocks SHALL use no runtime-specific interface, so they build for any IEC 61131-3 runtime that has the generated link variable.

#### Scenario: Read the vendor ID
- **WHEN** a program sets EXECUTE of `CO_SDO_READ` with NETWORK 0, NODE 5, INDEX 16#1018, SUBINDEX 1
- **THEN** BUSY is TRUE until the bridge answers, then DONE is TRUE with node 5's vendor ID in DATA

#### Scenario: Two blocks at once
- **WHEN** two `CO_SDO_READ` instances start in the same scan
- **THEN** the first finishes, then the second runs, and both end with DONE

#### Scenario: Bridge not running
- **WHEN** `CO_NMT` starts while `canworks.ok` is FALSE
- **THEN** it ends with ERROR TRUE and ERROR_ID 20 without writing the control block
