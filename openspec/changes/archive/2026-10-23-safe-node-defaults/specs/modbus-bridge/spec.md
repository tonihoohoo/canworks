## MODIFIED Requirements

### Requirement: Status block
With `status_location` (8 input bytes), the bridge SHALL publish:
- byte 0: state (1 running, 2 outputs off by watchdog, 3 outputs off by idle command)
- byte 1: number of connected clients
- bytes 2-3: a counter incremented every 100 ms
- bytes 4-5: the last control counter handled
- byte 6: the last control result
- byte 7: flags; bit 0 set for the whole run when the previous run of this config did not stop cleanly (Requirement: Unclean stop reported); bit 1 set while any CAN network of the bridge has its interface down or missing or its controller bus-off (error-warning and error-passive do not set it); the other bits 0

The bridge's diagnostics status SHALL name the networks whose bus is not ok (`bus_not_ok`).

#### Scenario: Bridge alive
- **WHEN** a client reads the status block twice 500 ms apart
- **THEN** the counter has grown by about 5

#### Scenario: Start after a clean stop
- **WHEN** the bridge was stopped with `systemctl stop` and started again
- **THEN** byte 7 reads 0

#### Scenario: Start after a crash
- **WHEN** the bridge was killed with SIGKILL and systemd started it again
- **THEN** byte 7 bit 0 is set until the bridge stops, and the counter in bytes 2-3 started again from 0

#### Scenario: Interface down
- **WHEN** the bridge runs one network on `can0` and `can0` is taken down
- **THEN** within 200 ms byte 7 bit 1 is set, and it clears within 200 ms after `can0` is up again

#### Scenario: Simulated network
- **WHEN** every network is simulated
- **THEN** bit 1 stays clear
