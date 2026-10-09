## ADDED Requirements

### Requirement: Bus state log on plain CAN networks
A network with protocol `none` SHALL log its bus state changes as the CANopen master does for its network: a warning on entering error-warning or error-passive, an error line on entering bus-off (saying whether `adapter.restart_ms` makes the kernel restart the controller), an info line on returning to error-active, and an error line for bus-offs the adapter left between two readings. When the state changes more than 5 times within one second, the rest of that second SHALL go into one summary line.

#### Scenario: Wrong bit rate
- **WHEN** a plain network's adapter runs at 250 kbit/s on a 500 kbit/s bus and goes bus-off
- **THEN** the runtime log has an error line saying the interface is bus-off, and while the adapter keeps leaving and entering bus-off at most 5 state lines and one summary line a second
