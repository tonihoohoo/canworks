## ADDED Requirements

### Requirement: PDO timing with PLC-cycle SYNC
With `"sync_source": "plc_cycle"`, the inputs a node samples at the SYNC sent in frame k SHALL reach the PLC at the `cycle_start()` of frame k+1 when they arrive on the bus before it, and the outputs the scan of frame k writes SHALL be sent in the master's synchronous PDOs right after the SYNC of frame k+1. The scan SHALL NOT wait for the bus in either direction. Event-driven master PDOs SHALL be sent when their data changed, at the SYNC that carries the change, as with the timer.

#### Scenario: Fixed output latency
- **WHEN** `"sync_source"` is `"plc_cycle"` with a 10 ms task, node 23's RPDO 1 has type 1, and the program sets `%QX20.0` to TRUE in one scan
- **THEN** the master's RPDO 1 for node 23 with the new value follows the next SYNC, and over 1000 such changes the time from the scan's `cycle_end()` to that RPDO never exceeds one frame plus the bus thread's wake-up time

#### Scenario: Inputs one frame old
- **WHEN** `"sync_source"` is `"plc_cycle"` with a 10 ms task and node 5's TPDO 1 (type 1) carries a counter the node increments at every SYNC
- **THEN** the PLC sees the counter increase by exactly one in every scan, with no repeated or missed value while no PDO is late

## MODIFIED Requirements

### Requirement: Synchronous PDOs need SYNC
When the master produces no SYNC, the plugin SHALL reject every configured PDO whose effective transmission type needs SYNC: 0-240 or 252. The effective type SHALL be the PDO's `transmission` when the JSON gives it, otherwise the default value of sub-index 2 of the PDO's communication object in the node's EDS. The plugin SHALL NOT change the transmission type on its own to avoid the error. The error SHALL name the node, the PDO, the type and where it came from (JSON or EDS), and say to set `master.sync_period_us`, `"master.sync_source": "plc_cycle"` or a `transmission` of 254 or 255. A PDO's `sync_start` SHALL likewise be rejected without SYNC. PDOs the config does not list are switched off and SHALL NOT be checked.

#### Scenario: Synchronous EDS default without SYNC
- **WHEN** the config has no `sync_period_us` and no `sync_source`, and node 5 has a `tx_pdos` entry 1 without `transmission` whose EDS default for 0x1800 sub 2 is 1
- **THEN** the configuration is rejected, naming node 5, TPDO 1, transmission type 1 from the EDS, and suggesting `sync_period_us`, `"sync_source": "plc_cycle"` or `"transmission": 254`

#### Scenario: Synchronous EDS default with PLC-cycle SYNC
- **WHEN** the config has `"sync_source": "plc_cycle"` and no `sync_period_us`, and node 5's TPDO 1 has EDS default type 1
- **THEN** the configuration loads and the node sends TPDO 1 after every SYNC

#### Scenario: Event-driven override
- **WHEN** the same PDO gives `"transmission": 255` and the EDS marks 0x1800 sub 2 writable
- **THEN** the configuration loads and the node sends TPDO 1 on change without SYNC

#### Scenario: Event-driven EDS default
- **WHEN** the config has no `sync_period_us` and node 23's RPDO 1 has no `transmission` and an EDS default of 255
- **THEN** the configuration loads

#### Scenario: Unlisted synchronous PDO
- **WHEN** the config has no `sync_period_us` and node 5's EDS has TPDO 2 with default type 1, but the config does not list TPDO 2
- **THEN** the configuration loads and TPDO 2 is switched off
