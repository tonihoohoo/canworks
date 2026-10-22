## MODIFIED Requirements

### Requirement: Master without SYNC
The master produces SYNC when the configuration gives a SYNC period greater than 0. When it does not, the master SHALL NOT produce SYNC: its 0x1006 (communication cycle period) SHALL be 0, which switches the SYNC producer off (CiA 301). A configuration that gives a SYNC period greater than 0 SHALL produce SYNC exactly as before. Without SYNC, the bridge SHALL reject `sync_window_us` and `sync_counter_overflow` in the `master` object, naming the field and saying it needs `sync_period_us`.

#### Scenario: No SYNC on the bus
- **WHEN** the config has no `sync_period_us` and the network runs for 10 seconds with event-driven PDOs only
- **THEN** no frame with COB-ID 0x080 is sent by the master, and the master's 0x1006 reads 0

#### Scenario: SYNC period given
- **WHEN** the config has `"sync_period_us": 100000`
- **THEN** the master sends SYNC every 100 ms as before

#### Scenario: SYNC window without SYNC
- **WHEN** the config has no `sync_period_us` and `"sync_window_us": 5000`
- **THEN** the bridge rejects the configuration, naming `sync_window_us` and saying it needs `sync_period_us`

#### Scenario: SYNC window with PLC-cycle SYNC
- **WHEN** a config has `"sync_source": "plc_cycle"` and `"sync_window_us": 5000`
- **THEN** the bridge rejects it, saying SYNC from the PLC cycle is not available and naming `sync_period_us`

## REMOVED Requirements

### Requirement: SYNC from the PLC cycle
**Reason**: SYNC from the PLC cycle needed the plugin inside the PLC scan, which is removed; the bridge has no PLC cycle.
**Migration**: Use timer SYNC (`sync_period_us`).

### Requirement: PLC-cycle SYNC never holds the scan
**Reason**: SYNC from the PLC cycle is removed with the plugin.
**Migration**: Use timer SYNC (`sync_period_us`).

### Requirement: PLC-cycle SYNC settings
**Reason**: SYNC from the PLC cycle is removed with the plugin; `sync_source` and `sync_cycles` leave the schema.
**Migration**: Use timer SYNC (`sync_period_us`).
