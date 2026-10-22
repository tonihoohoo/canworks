## MODIFIED Requirements

### Requirement: Library delivery
The `canworks` function block library SHALL be built from its editor library project in this repository into `canworks.stlib`. It SHALL hold the blocks over the bridge (`CO_SDO_READ`, `CO_SDO_WRITE`, `CO_NMT`, `CO_NODE_LIVE`), the word helpers `CW_WORDS_TO_REAL`, `CW_REAL_TO_WORDS`, `CW_WORDS_TO_LREAL` and `CW_LREAL_TO_WORDS`, the data type `CW_LINK`, and the pure ST helper functions of `can-plc-frames`, `j1939-plc-diagnostics` and `j1939-plc-blocks` (`CAN_GET_*`, `CAN_SET_*`, `CAN_J1939_*`, `J1939_GET_BITS`, `J1939_SET_BITS`, `J1939_DTC_*`, `J1939_NAME_*`). Blocks that call into the OpenPLC plugin and the CiA 402 blocks SHALL NOT be in it. Each `deploy-v` release SHALL carry that file, `canworks-deploy library --out DIR` SHALL write the copy that matches the installed tools into `DIR`, `canworks-deploy library --install` SHALL install that copy into OpenPLC Editor on the same computer as the editor's Library Manager does, `canworks-deploy library --project DIR` SHALL enable it in an editor project, and `canworks-deploy library --list` SHALL list its blocks and functions. The library's version SHALL equal the deploy package version. Installing it once with the editor's Library Manager ("install from file") SHALL make the blocks appear in the editor's library tree for every project that enables it.

#### Scenario: Install in the editor
- **WHEN** the user runs `canworks-deploy library --out .` and installs the written file in OpenPLC Editor 4.3.2
- **THEN** the library tree lists `canworks` with `CO_SDO_READ`, `CO_SDO_WRITE`, `CO_NMT`, `CO_NODE_LIVE` and the helper functions, and a project that enables it and calls `CO_SDO_READ` and `CO_NMT` builds for OpenPLC Runtime v4

#### Scenario: Install from the command line
- **WHEN** the user runs `canworks-deploy library --install` on a PC where OpenPLC Editor has run, then restarts the editor
- **THEN** the editor's library list shows `canworks` with the tools' version, and libraries installed before are still listed

## ADDED Requirements

### Requirement: Blocks over the bridge
`CO_SDO_READ` (EXECUTE, NETWORK, NODE, INDEX, SUBINDEX, TIMEOUT → BUSY, DONE, ERROR, ERROR_ID, ABORT_CODE, DATA : UDINT, SIZE), `CO_SDO_WRITE` (EXECUTE, NETWORK, NODE, INDEX, SUBINDEX, DATA : UDINT, SIZE, TIMEOUT → BUSY, DONE, ERROR, ERROR_ID, ABORT_CODE), `CO_NMT` (EXECUTE, NETWORK, NODE, COMMAND → BUSY, DONE, ERROR, ERROR_ID) and `CO_NODE_LIVE` (NETWORK, NODE → LIVE) SHALL be ST blocks with an in-out `LINK : CW_LINK`. They SHALL work through the bridge's SDO bridge registers, control block and live lists with its counter handshake, with the PLCopen EXECUTE/BUSY/DONE/ERROR behaviour of today's blocks. Instances SHALL share the one SDO slot and the one control block: a block whose request finds the slot owned by another instance SHALL stay BUSY until the slot is free, and requests SHALL be served in the order they started. SIZE SHALL be 1-4 (0 meaning 4 for a read). ERROR_ID SHALL keep today's codes, add 20 (bridge not reachable: `canworks_ok` false at start or during the request) and 21 (SDO writes not allowed: `sdo_bridge_write` false). The blocks SHALL use no runtime-specific interface, so they build for any IEC 61131-3 runtime that has the generated link variable.

#### Scenario: Read the vendor ID
- **WHEN** a program sets EXECUTE of `CO_SDO_READ` with NETWORK 0, NODE 5, INDEX 16#1018, SUBINDEX 1, SIZE 4
- **THEN** BUSY is TRUE until the bridge answers, then DONE is TRUE with node 5's vendor ID in DATA

#### Scenario: Two blocks at once
- **WHEN** two `CO_SDO_READ` instances start in the same scan
- **THEN** the first finishes, then the second runs, and both end with DONE

#### Scenario: Bridge not running
- **WHEN** `CO_NMT` starts while `canworks_ok` is FALSE
- **THEN** it ends with ERROR TRUE and ERROR_ID 20 without writing the control block
