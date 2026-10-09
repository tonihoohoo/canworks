## ADDED Requirements

### Requirement: EMCY count is the number received
The EMCY count the status request reports for a node SHALL be the number of emergency messages received from it since the CANopen session started, not the length of the kept history, which stays limited to the last 16.

#### Scenario: More than 16 EMCYs
- **WHEN** node 5 sends 20 EMCYs
- **THEN** the status reports count 20 and the history holds the last 16

### Requirement: Direction of frames on a simulated bus
In a trace of a simulated network, a frame sent by the plugin's master (NMT, SYNC, heartbeat, RPDOs, SDO requests, LSS) or by `send_frame` SHALL be recorded as Tx, and a frame sent by a simulated device as Rx, as on a SocketCAN interface.

#### Scenario: SYNC on a simulated network
- **WHEN** a trace runs on simulated network io, whose master sends SYNC
- **THEN** the SYNC frames are Tx and the "Tx only" filter shows them
