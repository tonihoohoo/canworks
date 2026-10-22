## ADDED Requirements

### Requirement: Mailbox blocks in the library
The `canworks` library SHALL also hold the blocks of `bridge-plc-blocks` (`CO_SDO_READ_BYTES`, `CO_SDO_WRITE_BYTES`, `CO_SDO_READ_STRING`, `CO_SDO_WRITE_STRING`, `CO_SDO_READ_REAL`, `CO_SDO_WRITE_REAL`, `CO_RECV_EMCY`, `CAN_SEND`, `CAN_SEND_CYCLIC`, `CAN_RECEIVE`, `CAN_BUS_INFO`, `J1939_SEND`, `J1939_RECEIVE`, `J1939_REQUEST`, `J1939_DM_READ`, `J1939_DM_CLEAR`, `J1939_ECU_INFO`, `J1939_FIND_ECU`) and `CW_LINK_SERVICE`, all as ST. The blocks over the bridge from `add-openplc-modbus-target` SHALL take `LINK : ARRAY[0..1023] OF WORD`. `canworks-deploy library --list` SHALL list them, and the library documentation SHALL describe each block's pins, which bridge block it needs, its ERROR_IDs and its cost in polls.

#### Scenario: Install in the editor
- **WHEN** the user installs the library written by `canworks-deploy library --out .` in OpenPLC Editor and enables it in a project generated for a config with mailboxes
- **THEN** the library tree lists `CAN_SEND`, `J1939_RECEIVE` and `CO_SDO_READ_BYTES`, and a program that calls them builds for OpenPLC Runtime v4

### Requirement: Library for other PLCs
`canworks-deploy library --format st --out DIR` SHALL write the blocks over the bridge, `CW_LINK_SERVICE`, the pure ST helpers and pure ST versions of the word-to-REAL and word-to-LREAL helpers as `.st` files, one block or function per file, with a short header naming the library version. The pure ST REAL helpers SHALL give the same bit patterns as the library's own helpers for every normal and subnormal value and zero, and SHALL map infinities and NaN to the IEEE patterns of the same class.

#### Scenario: ST sources
- **WHEN** the user runs `canworks-deploy library --format st --out lib`
- **THEN** `lib` holds one `.st` file per block and function of the bridge blocks and helpers, and they build together with STruC++ without any other source

#### Scenario: REAL helpers agree
- **WHEN** CI converts 10,000 random bit patterns with both the pure ST and the library's REAL helpers
- **THEN** every normal, subnormal and zero value gives the same result
