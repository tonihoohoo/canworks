## MODIFIED Requirements

### Requirement: Signal types and ranges
Signals of INTEGER types SHALL be signed and of UNSIGNED and BOOLEAN types unsigned, with minimum and maximum the full range of the type's bit length. REAL32 and REAL64 signals SHALL be declared as IEEE single and double floats. Offset SHALL be 0. Unit SHALL be the `unit` of the object's merged note (see `canopen-device-notes`), else empty. Factor SHALL be the note's `scale`, else 1, with minimum and maximum scaled by it. The type SHALL be the config entry's `type` where the config names the object, else the EDS data type.

#### Scenario: REAL32 input
- **WHEN** a TPDO maps a REAL32 object
- **THEN** its signal is 32 bits and declared as an IEEE single float

#### Scenario: Scaled pressure
- **WHEN** a TPDO maps 0x2200:1 (INTEGER16) and its note has unit bar and scale 0.01
- **THEN** its signal has factor 0.01, unit "bar", minimum -327.68 and maximum 327.67

### Requirement: Comments and timing
Each signal SHALL have a comment naming the object as `0x<index>:<subindex>`, its CANopen type, and its PLC location, or saying that the PLC does not use it, followed by the note `text` of its merged note when it has one. A signal whose merged note has `values` SHALL get a value table (`VAL_`) with those values and meanings. Each PDO message SHALL have a comment naming the node ID, the PDO and its transmission type (or that the EDS value applies). A PDO with a synchronous transmission type 1-240 SHALL get a `GenMsgCycleTime` attribute of the SYNC period times the transmission type, in milliseconds. With `"sync_source": "plc_cycle"` such a PDO SHALL get no `GenMsgCycleTime`, and its comment SHALL say it is sent every N SYNCs, one SYNC every `sync_cycles` PLC cycles.

#### Scenario: Synchronous TPDO
- **WHEN** the SYNC period is 100000 µs and TPDO 1 has transmission type 1
- **THEN** the message has `GenMsgCycleTime` 100 and its signals' comments read like `0x7130:1 INTEGER16 -> %IW100`

#### Scenario: Synchronous TPDO with PLC-cycle SYNC
- **WHEN** the config has `"sync_source": "plc_cycle"` and `"sync_cycles": 2`, and TPDO 1 has transmission type 1
- **THEN** the message has no `GenMsgCycleTime` and its comment says it is sent at every SYNC, one SYNC every 2 PLC cycles

#### Scenario: Mode of operation display
- **WHEN** a TPDO of a CiA 402 drive maps 0x6061
- **THEN** the file has a `VAL_` line for that signal listing the modes of operation, among them `3 "profile velocity"`

#### Scenario: Without notes
- **WHEN** no mapped object has a note with text, unit, scale or values
- **THEN** the DBC file is byte for byte the same as before this feature
