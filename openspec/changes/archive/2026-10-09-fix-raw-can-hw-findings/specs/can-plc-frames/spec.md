## MODIFIED Requirements

### Requirement: Cyclic frames
While `ENABLE` is TRUE, `CAN_SEND_CYCLIC` SHALL have the plugin send the frame every `PERIOD` (1 ms to 60 s) from its own timer, whatever the PLC cycle time. `ID` and `EXTENDED` SHALL be taken when `ENABLE` rises; `DATA`, `DLC` and `PERIOD` SHALL be taken on every call and used from the next send. `COUNT` SHALL count frames sent since `ENABLE` rose. `ENABLE` FALSE, a PLC stop or a network restart SHALL stop the job. While `ENABLE` stays TRUE after a start failed or a job ended with `ERROR_ID` 1, 7 or 8, the block SHALL try to start the job again on every call, keeping `ERROR` and `ERROR_ID` until it succeeds; other errors SHALL need a new rising edge of `ENABLE`. A network SHALL have at most 16 cyclic jobs.

#### Scenario: Faster than the scan
- **WHEN** the PLC cycle is 50 ms and a block runs with `PERIOD := T#10ms`
- **THEN** the frame appears on the bus about every 10 ms and `COUNT` grows by about 5 per scan

#### Scenario: Period out of range
- **WHEN** `PERIOD` is `T#0s`
- **THEN** the block reports `ERROR` with `ERROR_ID` 3 and sends nothing

#### Scenario: Enabled before the network runs
- **WHEN** a block has `ENABLE := TRUE` from the first scan and the network starts a few scans later
- **THEN** the block reports `ERROR_ID` 1 until the network runs, then starts the job without a new rising edge of `ENABLE`

### Requirement: Receivers
While `ENABLE` is TRUE, `CAN_RECEIVE` SHALL hold a receiver that queues, in arrival order, every frame on the network with the given format whose `(identifier AND MASK) = (ID AND MASK)`, up to `DEPTH` frames (`0` meaning 32, at most 256). `MASK` 0 SHALL mean every identifier bit (only `ID` itself); `ANY` SHALL take every frame of the format. `ID`, `MASK`, `ANY`, `EXTENDED` and `DEPTH` SHALL be taken when `ENABLE` rises. Each call SHALL take at most one frame from the queue: `NEW` TRUE with that frame's identifier, flags, DLC, data and kernel receive time (UTC microseconds) in the outputs, or `NEW` FALSE with the outputs of the last frame kept. `QUEUED` SHALL give the frames still waiting. A frame arriving at a full queue SHALL be dropped, set `OVERFLOW` until `ENABLE` falls, and count in `DROPPED`. Frames the plugin itself sends SHALL NOT be queued. On a network with protocol `none`, frames other programs on the PLC host send SHALL be queued like frames from the bus. While `ENABLE` stays TRUE after opening failed or the receiver ended with `ERROR_ID` 1, 7 or 8, the block SHALL try to open it again on every call, keeping `ERROR` and `ERROR_ID` until it succeeds; other errors SHALL need a new rising edge of `ENABLE`. `ENABLE` FALSE SHALL close the receiver and discard its queue. A network SHALL have at most 32 receivers.

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

#### Scenario: Receiver after a network restart
- **WHEN** a receiver with `ENABLE` TRUE is cancelled by a network restart
- **THEN** the block reports `ERROR_ID` 8 and opens a new receiver on the next call

#### Scenario: Frame from another program on the PLC host
- **WHEN** `cansend` on the PLC host sends a matching frame on the interface of a plain CAN network
- **THEN** the receiver queues it and `CAN_BUS_INFO` counts it in `RX_COUNT`
