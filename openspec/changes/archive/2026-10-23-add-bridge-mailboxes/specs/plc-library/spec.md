## ADDED Requirements

### Requirement: Mailbox blocks in the library
The `canworks` library SHALL also hold the blocks of `bridge-plc-blocks` (`CO_SDO_READ_BYTES`, `CO_SDO_WRITE_BYTES`, `CO_SDO_READ_STRING`, `CO_SDO_WRITE_STRING`, `CO_SDO_READ_REAL`, `CO_SDO_WRITE_REAL`, `CO_RECV_EMCY`, `CAN_SEND`, `CAN_SEND_CYCLIC`, `CAN_RECEIVE`, `CAN_BUS_INFO`, `J1939_SEND`, `J1939_RECEIVE`, `J1939_REQUEST`, `J1939_DM_READ`, `J1939_DM_CLEAR`, `J1939_ECU_INFO`, `J1939_FIND_ECU`) with their helper blocks (`CW_LINK_SERVICE`, `CW_MB_CALL`, `CW_SDO_XFER`, `CW_REQUEST`, `CW_RX`) and functions (`CW_CHAR`, `CW_CHAR_CODE`), all as ST. The blocks over the bridge from `add-openplc-modbus-target` SHALL take `LINK : ARRAY[0..1279] OF WORD`. `canworks-deploy library --list` SHALL list them, and the library documentation SHALL describe each block's pins, which bridge block it needs, its ERROR_IDs and its cost in polls.

#### Scenario: Install in the editor
- **WHEN** the user installs the library written by `canworks-deploy library --out .` in OpenPLC Editor and enables it in a project generated for a config with mailboxes
- **THEN** the library tree lists `CAN_SEND`, `J1939_RECEIVE` and `CO_SDO_READ_BYTES`, and a program that calls them builds for OpenPLC Runtime v4

### Requirement: Library for other PLCs
`canworks-deploy library --format st --out DIR` SHALL write the library's sources as `.st` files, one block or function per file (the REAL word helpers in one file), each with a short header naming the library version: the blocks over the bridge, their helpers, `CW_LINK_SERVICE`, the CAN and J1939 helper functions and the REAL word helpers, which are plain ST bit arithmetic. `--format st` without `--out` SHALL be refused.

#### Scenario: ST sources
- **WHEN** the user runs `canworks-deploy library --format st --out lib`
- **THEN** `lib` holds one `.st` file per block and function of the bridge blocks and helpers, each starting with the library version, and they build together with STruC++ without any other source

## MODIFIED Requirements

### Requirement: Library delivery
The `canworks` function block library SHALL be built from its editor library project in this repository into `canworks.stlib`. It SHALL hold the blocks over the bridge (`CO_SDO_READ`, `CO_SDO_WRITE`, `CO_NMT`, `CO_NODE_LIVE`), the mailbox blocks of "Requirement: Mailbox blocks in the library", the word helpers `CW_WORDS_TO_REAL`, `CW_REAL_TO_WORDS`, `CW_WORDS_TO_LREAL` and `CW_LREAL_TO_WORDS`, the data type `CW_LINK`, and the pure ST helpers of "Requirement: ST helper functions". It SHALL hold no block that calls into a runtime plugin and no CiA 402 block, and its build SHALL need no OpenPLC runtime source. Each `deploy-v` release SHALL carry that file, `canworks-deploy library --out DIR` SHALL write the copy that matches the installed tools into `DIR`, `canworks-deploy library --install` SHALL install that copy into OpenPLC Editor on the same computer as the editor's Library Manager does, `canworks-deploy library --project DIR` SHALL enable it in an editor project, and `canworks-deploy library --list` SHALL list its blocks and functions. The library's version SHALL equal the deploy package version. Installing it once with the editor's Library Manager ("install from file") SHALL make the blocks appear in the editor's library tree for every project that enables it.

#### Scenario: Install in the editor
- **WHEN** the user runs `canworks-deploy library --out .` and installs the written file in OpenPLC Editor 4.3.2
- **THEN** the library tree lists `canworks` with `CO_SDO_READ`, `CO_SDO_WRITE`, `CO_NMT`, `CO_NODE_LIVE` and the helper functions, and a project that enables it and calls `CO_SDO_READ` and `CO_NMT` builds for OpenPLC Runtime v4

#### Scenario: Install from the command line
- **WHEN** the user runs `canworks-deploy library --install` on a PC where OpenPLC Editor has run, then restarts the editor
- **THEN** the editor's library list shows `canworks` with the tools' version, and libraries installed before are still listed

#### Scenario: No plugin blocks
- **WHEN** the user runs `canworks-deploy library --list`
- **THEN** the list has `CO_SDO_READ_BYTES`, `CO_RECV_EMCY`, `CAN_SEND`, `J1939_SEND` and `J1939_DM_READ`, and no `CO402_` entry

### Requirement: Library documentation
`docs/plc-library.md` SHALL be the library's page: the blocks over the bridge with their pins, error IDs and how they share the bridge's SDO slot and control block, the mailbox blocks with their pins and error IDs and how they share the request mailboxes, the helper functions with their bit numbering, the word helpers, installing and enabling the library, and the PLCopen `EXECUTE` handshake. `docs/raw-can.md` and `docs/j1939.md` SHALL link to it for the helpers instead of repeating them. README SHALL link to it as the place for the program's blocks. No doc SHALL describe a block that calls a runtime plugin.

#### Scenario: Reader looks for J1939 blocks
- **WHEN** a user opens `docs/plc-library.md`
- **THEN** it lists the J1939 helper functions and the J1939 message and trouble code blocks, which work through the bridge's mailboxes

#### Scenario: Reader looks for the SDO block
- **WHEN** a user opens `docs/plc-library.md`
- **THEN** it describes `CO_SDO_READ` with its pins, its 1-4 byte limit and error IDs 20 and 21, and points to `CO_SDO_READ_BYTES` and `CO_SDO_READ_STRING` for longer transfers

### Requirement: Blocks over the bridge
`CO_SDO_READ` (EXECUTE, NETWORK, NODE, INDEX, SUBINDEX, TIMEOUT → BUSY, DONE, ERROR, ERROR_ID, ABORT_CODE, DATA : UDINT), `CO_SDO_WRITE` (EXECUTE, NETWORK, NODE, INDEX, SUBINDEX, DATA : UDINT, SIZE, TIMEOUT → BUSY, DONE, ERROR, ERROR_ID, ABORT_CODE), `CO_NMT` (EXECUTE, NETWORK, NODE, COMMAND, TIMEOUT → BUSY, DONE, ERROR, ERROR_ID) and `CO_NODE_LIVE` (NETWORK, NODE → LIVE) SHALL be ST blocks with an in-out `LINK : ARRAY[0..1279] OF WORD` (the generated `canworks.link`). They SHALL work through the bridge's SDO bridge registers, control block and live lists with its counter handshake, with the PLCopen EXECUTE/BUSY/DONE/ERROR behaviour of today's blocks. Instances SHALL share the one SDO slot and the one control block: a block whose request finds the slot owned by another instance SHALL stay BUSY until the slot is free, and requests SHALL be served in the order they started. A write's SIZE SHALL be 1-4; a read returns the object's value in DATA, zero-extended. ERROR_ID SHALL keep today's codes, add 20 (bridge not reachable: `canworks.ok` false at start or during the request), 21 (SDO writes not allowed: abort 0x08000020 from the bridge) and 22 (the config has no SDO registers or control block for the request). The blocks SHALL use no runtime-specific interface, so they build for any IEC 61131-3 runtime that has the generated link variable.

#### Scenario: Read the vendor ID
- **WHEN** a program sets EXECUTE of `CO_SDO_READ` with NETWORK 0, NODE 5, INDEX 16#1018, SUBINDEX 1
- **THEN** BUSY is TRUE until the bridge answers, then DONE is TRUE with node 5's vendor ID in DATA

#### Scenario: Two blocks at once
- **WHEN** two `CO_SDO_READ` instances start in the same scan
- **THEN** the first finishes, then the second runs, and both end with DONE

#### Scenario: Bridge not running
- **WHEN** `CO_NMT` starts while `canworks.ok` is FALSE
- **THEN** it ends with ERROR TRUE and ERROR_ID 20 without writing the control block
