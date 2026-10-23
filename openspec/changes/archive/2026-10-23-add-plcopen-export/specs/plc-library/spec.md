## ADDED Requirements

### Requirement: Library builds on strict IEC tools
Every block and function of the library SHALL be plain IEC 61131-3 ST that builds unchanged on compilers that check types strictly: no reserved words or IL operators as names of POUs, pins or locals (`NEW`, `ANY`, `R`, `S`, `N`, `BIT`, checked by a test against one list), no STRING constant longer than the shortest default STRING length (CODESYS: 80), typed literals where a bit-string type is expected (`WORD#0`, `DWORD#16#...`, `BYTE#0`), arithmetic on WORD values done through integer conversions, bit operations on bit-string types only, and TIME conversions through `TIME_TO_DWORD`/`DWORD_TO_TIME` (milliseconds). A word counter SHALL wrap at 65536 without an arithmetic overflow. CI SHALL build the whole library with STruC++ and, through the PLCopen export, with the pinned truST release.

#### Scenario: Whole library on truST
- **WHEN** the trust export with the library is imported into a truST project with a program that calls `CO_SDO_READ`, `CAN_RECEIVE`, `CO_SDO_READ_STRING` and `J1939_DM_READ`
- **THEN** `trust-runtime build` succeeds without errors

#### Scenario: Built in CODESYS
- **WHEN** the sources written by `canworks-deploy library --format st` are added to a CODESYS project
- **THEN** no block has a pin or local named like a reserved word, operator or type, and `CW_CHAR` returns every byte value 1-255 as one character with `CW_CHAR_CODE` giving it back

#### Scenario: Ticket counter wraps
- **WHEN** the mailbox ticket counter `LINK[91]` is 65535 and an instance takes a ticket
- **THEN** the counter becomes 1 (0 is skipped) and the PLC does not stop with an overflow

## MODIFIED Requirements

### Requirement: Library for other PLCs
`canworks-deploy library --format st --out DIR` SHALL write the library's sources as `.st` files, one block or function per file (the REAL word helpers in one file), each with a short header naming the library version: the blocks over the bridge, their helpers, `CW_LINK_SERVICE`, the CAN and J1939 helper functions and the REAL word helpers, which are plain ST bit arithmetic. `canworks-deploy library --format plcopen --out DIR` SHALL write the same POUs as one PLCopen XML file `canworks-library.xml` (spec `plcopen-export`). `--format st` or `--format plcopen` without `--out` SHALL be refused.

#### Scenario: ST sources
- **WHEN** the user runs `canworks-deploy library --format st --out lib`
- **THEN** `lib` holds one `.st` file per block and function of the bridge blocks and helpers, each starting with the library version, and they build together with STruC++ without any other source

#### Scenario: PLCopen library
- **WHEN** the user runs `canworks-deploy library --format plcopen --out lib`
- **THEN** `lib/canworks-library.xml` holds every block and function of the library as a POU with its ST body
