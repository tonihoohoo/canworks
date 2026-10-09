## ADDED Requirements

### Requirement: CAN frame function blocks
The editor library `canworks` SHALL provide the function blocks `CAN_SEND`, `CAN_SEND_CYCLIC`, `CAN_RECEIVE` and `CAN_BUS_INFO`. Every block SHALL have the input `NETWORK : USINT`, picking the network by its place in the configuration's `networks` list (0 the first), and the outputs `ERROR : BOOL` and `ERROR_ID : UINT`. They SHALL work on networks of every protocol, including `none`. The pins SHALL be:
- `CAN_SEND`: in `EXECUTE : BOOL`, `ID : UDINT`, `EXTENDED : BOOL`, `RTR : BOOL`, `DLC : USINT`, `TIMEOUT : TIME`; in-out `DATA : ARRAY[0..7] OF BYTE`; out `BUSY : BOOL`, `DONE : BOOL`.
- `CAN_SEND_CYCLIC`: in `ENABLE : BOOL`, `ID : UDINT`, `EXTENDED : BOOL`, `DLC : USINT`, `PERIOD : TIME`; in-out `DATA : ARRAY[0..7] OF BYTE`; out `ACTIVE : BOOL`, `COUNT : UDINT`.
- `CAN_RECEIVE`: in `ENABLE : BOOL`, `ID : UDINT`, `MASK : UDINT`, `ANY : BOOL`, `EXTENDED : BOOL`, `DEPTH : UINT`; in-out `RX_DATA : ARRAY[0..7] OF BYTE`; out `ACTIVE : BOOL`, `NEW : BOOL`, `RX_ID : UDINT`, `RX_EXTENDED : BOOL`, `RX_RTR : BOOL`, `RX_DLC : USINT`, `TIMESTAMP : ULINT`, `QUEUED : UINT`, `OVERFLOW : BOOL`, `DROPPED : UDINT`.

The frame data pins are in-out, as the SDO blocks' `BUFFER`, because that is how the editor passes arrays to C++ blocks.
- `CAN_BUS_INFO`: out `STATE : USINT` (0 error active, 1 warning, 2 error passive, 3 bus-off, 4 interface down or missing), `TX_ERRORS : UINT`, `RX_ERRORS : UINT`, `BUS_OFF_COUNT : UDINT`, `BUS_LOAD : USINT` (percent over the last second), `RX_COUNT : UDINT`, `TX_COUNT : UDINT`, `ERROR_FRAMES : UDINT`.

#### Scenario: Send one frame
- **WHEN** the program calls `tx(EXECUTE := TRUE, NETWORK := 0, ID := 16#510, DLC := 2, DATA := d)` with `d[0] = 1`, `d[1] = 2`
- **THEN** the frame `0x510 01 02` appears on the bus once and within a few scans `tx.DONE` is TRUE

#### Scenario: Network that does not exist
- **WHEN** a block is called with a `NETWORK` the running configuration does not have
- **THEN** it reports `ERROR` with `ERROR_ID` 2 and sends nothing

### Requirement: Send handshake
`CAN_SEND` SHALL follow the handshake of the SDO blocks: a rising edge of `EXECUTE` SHALL queue one frame with the inputs of that call and set `BUSY`; input changes and edges while `BUSY` SHALL be ignored. `DONE` SHALL become TRUE when the frame is confirmed on the bus (the adapter's echo of the sent frame, or the write itself on adapters that do not echo). `ERROR` with `ERROR_ID` 6 SHALL end it when no confirmation came within `TIMEOUT` (`T#0s` meaning 100 ms). Outputs SHALL stay while `EXECUTE` stays TRUE and for one call after it was already FALSE.

#### Scenario: No other device on the bus
- **WHEN** the program sends a frame on a bus where no other device acknowledges it
- **THEN** after `TIMEOUT` the block reports `ERROR` with `ERROR_ID` 6

#### Scenario: Retrigger while busy
- **WHEN** `EXECUTE` falls and rises again while the block is `BUSY`
- **THEN** only the first frame is sent

### Requirement: Cyclic frames
While `ENABLE` is TRUE, `CAN_SEND_CYCLIC` SHALL have the plugin send the frame every `PERIOD` (1 ms to 60 s) from its own timer, whatever the PLC cycle time. `ID` and `EXTENDED` SHALL be taken when `ENABLE` rises; `DATA`, `DLC` and `PERIOD` SHALL be taken on every call and used from the next send. `COUNT` SHALL count frames sent since `ENABLE` rose. `ENABLE` FALSE, a PLC stop or a network restart SHALL stop the job. A network SHALL have at most 16 cyclic jobs.

#### Scenario: Faster than the scan
- **WHEN** the PLC cycle is 50 ms and a block runs with `PERIOD := T#10ms`
- **THEN** the frame appears on the bus about every 10 ms and `COUNT` grows by about 5 per scan

#### Scenario: Period out of range
- **WHEN** `PERIOD` is `T#0s`
- **THEN** the block reports `ERROR` with `ERROR_ID` 3 and sends nothing

### Requirement: Receivers
While `ENABLE` is TRUE, `CAN_RECEIVE` SHALL hold a receiver that queues, in arrival order, every frame on the network with the given format whose `(identifier AND MASK) = (ID AND MASK)`, up to `DEPTH` frames (`0` meaning 32, at most 256). `MASK` 0 SHALL mean every identifier bit (only `ID` itself); `ANY` SHALL take every frame of the format. `ID`, `MASK`, `ANY`, `EXTENDED` and `DEPTH` SHALL be taken when `ENABLE` rises. Each call SHALL take at most one frame from the queue: `NEW` TRUE with that frame's identifier, flags, DLC, data and kernel receive time (UTC microseconds) in the outputs, or `NEW` FALSE with the outputs of the last frame kept. `QUEUED` SHALL give the frames still waiting. A frame arriving at a full queue SHALL be dropped, set `OVERFLOW` until `ENABLE` falls, and count in `DROPPED`. Frames the plugin itself sends SHALL NOT be queued. `ENABLE` FALSE SHALL close the receiver and discard its queue. A network SHALL have at most 32 receivers.

#### Scenario: Drain in one scan
- **WHEN** five matching frames arrived since the last scan and the program calls `WHILE rx.NEW DO ... rx(); END_WHILE` after a first `rx()` call
- **THEN** the program sees the five frames in arrival order in that scan and `QUEUED` is 0

#### Scenario: Range receiver
- **WHEN** a receiver has `ID := 16#600`, `MASK := 16#780` and frames 0x605, 0x705 and 0x67F arrive
- **THEN** the receiver gets 0x605 and 0x67F and not 0x705

#### Scenario: One identifier
- **WHEN** a receiver has `ID := 16#123` and `MASK` left at 0, and frames 0x123 and 0x124 arrive
- **THEN** the receiver gets only 0x123

#### Scenario: Queue full
- **WHEN** a receiver with `DEPTH := 4` gets six frames before the program reads it
- **THEN** it delivers the first four, `OVERFLOW` is TRUE and `DROPPED` is 2

### Requirement: Error IDs of the frame blocks
The frame blocks SHALL report `ERROR_ID`:
- 1: the plugin is not loaded, does not offer the block interface's version, or the network is not running
- 2: no such network
- 3: an input is invalid (identifier out of range for its format, `DLC` over 8, `PERIOD` or `DEPTH` out of range)
- 4: the identifier is one the network's protocol uses and the network does not allow program overrides
- 5: no free receiver, cyclic job or transmit queue space
- 6: not confirmed on the bus within `TIMEOUT`
- 7: the network is bus-off or its interface is down
- 8: cancelled by a PLC stop or a network restart
- 9: the network is listen-only

#### Scenario: Protocol identifier
- **WHEN** node 5 has RPDO1 on 0x205 and the program sends 0x205 with `CAN_SEND`
- **THEN** the block reports `ERROR_ID` 4 and nothing is sent

#### Scenario: Program override allowed
- **WHEN** the same network has `raw.program_override_protocol: true`
- **THEN** the frame is sent and the runtime log notes the first such frame

### Requirement: Frame blocks do not stall the scan
The frame blocks SHALL never wait for CAN traffic, allocate memory or write the log on the PLC scan thread. They SHALL reach the plugin as the SDO blocks do (the plugin's SONAME with `RTLD_NOLOAD`) and call `canworks_can_api(1)`, which returns the version 1 table or NULL. A plugin without that version SHALL give `ERROR_ID` 1. A PLC stop SHALL end every send with `ERROR_ID` 8, close every receiver and stop every cyclic job.

#### Scenario: Plugin not loaded
- **WHEN** a program using `CAN_RECEIVE` runs on a runtime without the plugin
- **THEN** the block reports `ERROR_ID` 1 and the scan time does not change

### Requirement: ST helper functions
The library SHALL provide ST functions that need no plugin:
- `CAN_GET_BITS(DATA, START_BIT, BIT_LENGTH, MOTOROLA, SIGNED) : LINT` and `CAN_SET_BITS(DATA, START_BIT, BIT_LENGTH, MOTOROLA, VALUE) : BOOL` (in-out `DATA`), with bit numbering as DBC files use it (`MOTOROLA` FALSE: little-endian, TRUE: big-endian); `CAN_SET_BITS` SHALL return FALSE and write nothing when a bit falls outside the 8 bytes
- `CAN_GET_UINT16(DATA, OFFSET, MOTOROLA) : UINT`, `CAN_GET_UINT32(...) : UDINT` and `CAN_SET_UINT16` / `CAN_SET_UINT32(DATA, OFFSET, MOTOROLA, VALUE) : BOOL` for byte-aligned values at a byte offset
- `CAN_J1939_ID(PRIORITY, PGN, SOURCE, DESTINATION) : UDINT`, `CAN_J1939_PGN(ID) : UDINT` and `CAN_J1939_SOURCE(ID) : USINT`

Their results SHALL equal the plugin's signal packing for the same layouts.

#### Scenario: Unpack a signal
- **WHEN** a program calls `CAN_GET_BITS(DATA := buf, START_BIT := 0, BIT_LENGTH := 12, MOTOROLA := FALSE, SIGNED := TRUE)` on data `FF 0F 00 00 00 00 00 00`
- **THEN** the result is -1

#### Scenario: Build a J1939 identifier
- **WHEN** a program calls `CAN_J1939_ID(6, 65280, 128, 255)`
- **THEN** the result is 16#18FF0080
