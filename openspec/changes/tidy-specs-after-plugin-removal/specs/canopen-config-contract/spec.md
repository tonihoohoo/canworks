## MODIFIED Requirements

### Requirement: Settings the target does not use
One relevance table SHALL list, per setting, the targets that use it and why the others do not. The check SHALL warn, with the setting's path and that reason, for every set value its target does not use. Values the target refuses SHALL stay errors. Fields of removed features (`master.sync_source`, `sync_cycles`, `scan_watchdog_ms`, a node's `axis`) SHALL NOT be in the table: they are unknown fields, warned about as ignored, and `"sync_source": "plc_cycle"` is an error.

#### Scenario: Scan watchdog in a CODESYS config
- **WHEN** a CODESYS config has `master.scan_watchdog_ms` 500
- **THEN** the check warns that `scan_watchdog_ms` is an unknown field and is ignored, naming its path

#### Scenario: Scan watchdog in a bridge config
- **WHEN** a bridge config has `master.scan_watchdog_ms` 500
- **THEN** the check warns that `scan_watchdog_ms` is an unknown field and is ignored, naming its path, and the bridge logs the same warning and starts

#### Scenario: Bridge status locations in a CODESYS config
- **WHEN** a CODESYS config has `master.bus_state_location` `%IB10`
- **THEN** the check warns that CODESYS does not use it, naming its path and the reason
