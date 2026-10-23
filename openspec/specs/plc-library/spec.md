# plc-library Specification

## Purpose
The `canworks` function block library as a whole: how it is built, delivered, installed and enabled, how it is presented across the tools and docs, and how each block family finds its plugin interface version.

## Requirements

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

### Requirement: One library for every protocol
The library SHALL be presented as one general function block library for CANopen, CAN and J1939, not as a CANopen or SDO library. `canworks-deploy library --help`, the project creation output, the configurator and the documentation SHALL describe it by what it holds as a whole ("the canworks function block library"), and SHALL name a protocol or block family only where the text is about that family. The PC tools' module that writes, installs and enables it SHALL be named for the library (`plclibrary`), not for SDO.

#### Scenario: Help text
- **WHEN** the user runs `canworks-deploy library --help`
- **THEN** the description names the blocks over the bridge and the CAN and J1939 helper functions, and points to `docs/plc-library.md`

#### Scenario: Project created with the blocks
- **WHEN** a project is created with `--blocks`
- **THEN** the output says that the project enables the canworks function block library, without naming only the SDO or CAN blocks

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

### Requirement: ST helper functions
The library SHALL provide these pure ST functions and blocks, needing no bridge, plugin or runtime interface:
- `CAN_GET_BITS(DATA, START_BIT, BIT_LENGTH, MOTOROLA, SIGNED) : LINT` and `CAN_SET_BITS(DATA, START_BIT, BIT_LENGTH, MOTOROLA, VALUE) : BOOL` (in-out `DATA`, 8 bytes), with bit numbering as DBC files use it (`MOTOROLA` FALSE: little-endian, TRUE: big-endian); `CAN_SET_BITS` SHALL return FALSE and write nothing when a bit falls outside the 8 bytes
- `CAN_GET_UINT16(DATA, OFFSET, MOTOROLA) : UINT`, `CAN_GET_UINT32(...) : UDINT` and `CAN_SET_UINT16` / `CAN_SET_UINT32(DATA, OFFSET, MOTOROLA, VALUE) : BOOL` for byte-aligned values at a byte offset
- `CAN_J1939_ID(PRIORITY, PGN, SOURCE, DESTINATION) : UDINT`, `CAN_J1939_PGN(ID) : UDINT` and `CAN_J1939_SOURCE(ID) : USINT`
- `J1939_GET_BITS(DATA, START_BIT : UINT, BIT_LENGTH : USINT, SIGNED : BOOL) : LINT` and `J1939_SET_BITS(DATA, START_BIT : UINT, BIT_LENGTH : USINT, VALUE : LINT) : BOOL` (FALSE, writing nothing, when a bit falls outside the array or `BIT_LENGTH` is not 1..64), with `DATA` an in-out `ARRAY[0..1784] OF BYTE`, little-endian as J1939 sends signals, bits beyond the array read as 0
- `J1939_NAME_MAKE(...) : LWORD` from the NAME fields (`IDENTITY_NUMBER`, `MANUFACTURER_CODE`, `ECU_INSTANCE`, `FUNCTION_INSTANCE`, `ECU_FUNCTION`, `VEHICLE_SYSTEM`, `VEHICLE_SYSTEM_INSTANCE`, `INDUSTRY_GROUP`, `ARBITRARY_ADDRESS_CAPABLE`) and the block `J1939_NAME_SPLIT` the other way
- the block `J1939_DTC_SPLIT` (in `DTC : UDINT`; out `SPN : UDINT`, `FMI : USINT`, `OC : USINT`, `CM : BOOL`) and `J1939_DTC_MAKE(SPN : UDINT, FMI : USINT, OC : USINT) : UDINT`

Their results SHALL equal the engine's and the PC tools' packing for the same layouts, checked by the library tests on STruC++.

#### Scenario: Unpack a signal
- **WHEN** a program calls `CAN_GET_BITS(DATA := buf, START_BIT := 0, BIT_LENGTH := 12, MOTOROLA := FALSE, SIGNED := TRUE)` on data `FF 0F 00 00 00 00 00 00`
- **THEN** the result is -1

#### Scenario: Build a J1939 identifier
- **WHEN** a program calls `CAN_J1939_ID(6, 65280, 128, 255)`
- **THEN** the result is 16#18FF0080

#### Scenario: Signal past byte 8
- **WHEN** a program reads 16 bits at bit 200 of a 40-byte message with `J1939_GET_BITS`
- **THEN** it gets bytes 25 and 26 as a little-endian value

#### Scenario: NAME round trip
- **WHEN** a program makes a NAME from fields and splits it again
- **THEN** it gets the same fields back, and the NAME equals the one the config's `ecu.name` with those fields gives

#### Scenario: Split a code
- **WHEN** a program splits 16#021FF000 with `J1939_DTC_SPLIT`
- **THEN** it gets SPN 520192, FMI 3, OC 2 and CM FALSE

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
