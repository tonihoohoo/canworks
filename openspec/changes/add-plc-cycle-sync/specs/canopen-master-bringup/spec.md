## ADDED Requirements

### Requirement: SYNC from the PLC cycle
With `"master.sync_source": "plc_cycle"` the master SHALL send one SYNC from `cycle_start()` on every `sync_cycles`-th PLC frame (default 1), after the inputs were copied to the PLC, with the outputs the previous frame published at `cycle_end()`. Lely's SYNC timer SHALL NOT run (master 0x1006 = 0); the frame SHALL use the 0x1005 COB-ID and the `sync_counter_overflow` counter. Without `sync_source`, or with `"timer"`, SYNC SHALL work as before.

#### Scenario: One SYNC per PLC frame
- **WHEN** the config has `"sync_source": "plc_cycle"`, the PLC program has one task with a 10 ms interval, and the PLC runs for 10 seconds
- **THEN** the master sends 1000 ± 1 SYNC frames on COB-ID 0x080, the interval between consecutive SYNCs is 10 ms, and the master's 0x1006 reads 0

#### Scenario: Every second frame
- **WHEN** the config has `"sync_source": "plc_cycle"` and `"sync_cycles": 2` with a 5 ms task
- **THEN** the master sends a SYNC every 10 ms

#### Scenario: PLC stopped
- **WHEN** the PLC is stopped while `"sync_source"` is `"plc_cycle"`
- **THEN** the master sends no further SYNC

#### Scenario: Counter with PLC-cycle SYNC
- **WHEN** the config has `"sync_source": "plc_cycle"` and `"sync_counter_overflow": 10`
- **THEN** the SYNC frames carry a counter running from 1 to 10

#### Scenario: Existing configuration unchanged
- **WHEN** a configuration gives no `sync_source`
- **THEN** the generated master configuration and the SYNC timing are the same as before this change

### Requirement: PLC-cycle SYNC never holds the scan
`cycle_start()` SHALL NOT block, allocate, log or wait for the bus thread when it requests a SYNC. When the bus thread has not sent the previous SYNC by the time the next one is due, it SHALL send one SYNC for both and count one skipped frame.

#### Scenario: Busy bus thread
- **WHEN** the bus thread is held busy for 25 ms while SYNC is requested every 10 ms
- **THEN** the PLC frames keep their timing, the master sends one SYNC when the bus thread is free, and two skipped frames are counted

### Requirement: PLC-cycle SYNC settings
`sync_source` SHALL accept only `"timer"` and `"plc_cycle"`, and `sync_cycles` only 1-1000. The plugin SHALL reject `sync_cycles` without `"plc_cycle"`, and `"plc_cycle"` together with a `sync_period_us` greater than 0, naming the field. At start it SHALL log the SYNC source, `sync_cycles` and the runtime's base tick, and SHALL warn when the base tick times `sync_cycles` is below 1 ms.

#### Scenario: Period and PLC cycle both given
- **WHEN** the config has `"sync_source": "plc_cycle"` and `"sync_period_us": 10000`
- **THEN** the plugin rejects the configuration, naming `sync_period_us` and saying the SYNC period comes from the PLC cycle

#### Scenario: Cycles without PLC-cycle SYNC
- **WHEN** the config has `"sync_cycles": 2` and no `sync_source`
- **THEN** the plugin rejects the configuration, naming `sync_cycles` and saying it needs `"sync_source": "plc_cycle"`

#### Scenario: Very short cycle
- **WHEN** `"sync_source"` is `"plc_cycle"` and the runtime's base tick is 500 µs with `sync_cycles` 1
- **THEN** the configuration loads and the log warns that a SYNC period below 1 ms may not carry all PDOs

### Requirement: SYNC statistics
For either SYNC source the plugin SHALL keep the number of SYNCs sent, the last, shortest and longest interval between two sent SYNCs in microseconds, the number of skipped frames (0 with the timer), and the number of late PDOs. A late PDO SHALL be a node TPDO with a cyclic synchronous type (1-240) that was due at one SYNC and had not arrived when the next SYNC was sent.

#### Scenario: Steady cycle
- **WHEN** `"sync_source"` is `"plc_cycle"` with a 10 ms task and every synchronous PDO arrives in time
- **THEN** the late PDO and skipped counts stay 0 and the shortest and longest intervals are close to 10000 µs

### Requirement: SYNC warnings
The plugin SHALL log skipped frames and late PDOs as warnings, naming the node and PDO for a late PDO, at most once per 10 seconds for each PDO and once per 10 seconds for skips.

#### Scenario: PDO too slow for the cycle
- **WHEN** `"sync_source"` is `"plc_cycle"` with a 1 ms task and node 5's TPDO 1 (type 1) needs longer than 1 ms to arrive on the bus
- **THEN** the late PDO count rises and the log names node 5 TPDO 1, no more than once per 10 seconds

## MODIFIED Requirements

### Requirement: Master without SYNC
The master produces SYNC when the configuration gives a SYNC period greater than 0 or `"sync_source": "plc_cycle"`. When it does neither, the master SHALL NOT produce SYNC: its 0x1006 (communication cycle period) SHALL be 0, which switches the SYNC producer off (CiA 301). A configuration that gives a SYNC period greater than 0 SHALL produce SYNC exactly as before. Without SYNC, the plugin SHALL reject `sync_window_us` and `sync_counter_overflow` in the `master` object, naming the field and saying it needs `sync_period_us` or `"sync_source": "plc_cycle"`.

#### Scenario: No SYNC on the bus
- **WHEN** the config has no `sync_period_us`, no `sync_source`, and the network runs for 10 seconds with event-driven PDOs only
- **THEN** no frame with COB-ID 0x080 is sent by the master, and the master's 0x1006 reads 0

#### Scenario: SYNC period given
- **WHEN** the config has `"sync_period_us": 100000`
- **THEN** the master sends SYNC every 100 ms as before

#### Scenario: SYNC window without SYNC
- **WHEN** the config has no `sync_period_us`, no `sync_source`, and `"sync_window_us": 5000`
- **THEN** the plugin rejects the configuration, naming `sync_window_us` and saying it needs `sync_period_us` or `"sync_source": "plc_cycle"`

#### Scenario: SYNC window with PLC-cycle SYNC
- **WHEN** the config has `"sync_source": "plc_cycle"` and `"sync_window_us": 5000`
- **THEN** the configuration loads and the master's 0x1007 is 5000
