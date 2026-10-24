## MODIFIED Requirements

### Requirement: Library builds on strict IEC tools
Every block and function of the library SHALL be plain IEC 61131-3 ST that builds unchanged on compilers that check types strictly: no reserved words or IL operators as names of POUs, pins or locals (`NEW`, `ANY`, `R`, `S`, `N`, `BIT`, checked by a test against one list), no STRING constant longer than the shortest default STRING length (CODESYS: 80), typed literals where a bit-string type is expected (`WORD#0`, `DWORD#16#...`, `BYTE#0`), arithmetic on WORD values done through integer conversions, bit operations on bit-string types only, and TIME conversions through `TIME_TO_DWORD`/`DWORD_TO_TIME` (milliseconds). A word counter SHALL wrap at 65536 without an arithmetic overflow. CI SHALL build the whole library with STruC++ and, through the generic PLCopen export, with the pinned truST release as a strict compiler (truST is a compiler check only, not a target).

#### Scenario: Whole library on truST
- **WHEN** the generic export with the library and all mailboxes is imported into a truST project with a program that calls `CO_SDO_READ`, `CAN_RECEIVE`, `CO_SDO_READ_STRING` and `J1939_DM_READ`
- **THEN** the import reports nothing unsupported and `trust-runtime build` succeeds without errors

#### Scenario: Built in CODESYS
- **WHEN** the sources written by `canworks-deploy library --format st` are added to a CODESYS project
- **THEN** no block has a pin or local named like a reserved word, operator or type, and `CW_CHAR` returns every byte value 1-255 as one character with `CW_CHAR_CODE` giving it back

#### Scenario: Ticket counter wraps
- **WHEN** the mailbox ticket counter `LINK[91]` is 65535 and an instance takes a ticket
- **THEN** the counter becomes 1 (0 is skipped) and the PLC does not stop with an overflow
