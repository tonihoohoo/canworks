## ADDED Requirements

### Requirement: Frame blocks from several PLC tasks
The frame blocks SHALL work when instances in different PLC tasks run at the same time on the same network: each `CAN_SEND` SHALL send its own frame exactly once, each `CAN_RECEIVE` and `CAN_SEND_CYCLIC` SHALL get its own slot, and no block SHALL report another block's result. The scan side SHALL stay free of locks that wait on another thread. A receiver whose filter changes SHALL NOT deliver a frame that matched only its previous filter. `CAN_BUS_INFO` SHALL return within a bounded time even while the bus figures are being updated, giving the previous figures if needed.

#### Scenario: Two tasks send at once
- **WHEN** a fast task and a slow task each call `CAN_SEND` on network 0 in the same millisecond with different identifiers
- **THEN** both frames appear on the bus once each and both blocks report `DONE`

#### Scenario: Receiver changes its identifier
- **WHEN** a `CAN_RECEIVE` on 0x100 is changed to 0x200 while frames with 0x100 keep arriving
- **THEN** no frame with identifier 0x100 is delivered after the change
