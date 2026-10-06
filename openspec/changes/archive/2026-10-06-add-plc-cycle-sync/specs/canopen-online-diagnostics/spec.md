## MODIFIED Requirements

### Requirement: Live status
A status request SHALL return, as of no more than 100 ms before the answer:
- the plugin version, the time since the CANopen session started, and the SHA-256 of the loaded `canopen.json` file;
- the master node ID and NMT state code, and the bus state, TX and RX error counters and bus-off count as the bus diagnostics define them (whether or not their PLC locations are configured);
- the SYNC source (`none`, `timer` or `plc_cycle`), `sync_cycles` for `plc_cycle`, and the SYNC statistics: SYNCs sent, last, shortest and longest interval in microseconds, skipped frames and late PDOs;
- for each configured node: node ID, name, NMT state code as the state byte defines it, status bit value, whether its last boot succeeded, its last boot error letter with Lely's text (or none), whether a boot retry is pending, the hold in force (none, by the program, or by an operator, with STOPPED or PRE-OPERATIONAL), its last emergency code and error register, and for each SDO variable its name, current value, status code and abort code.

These values SHALL be available whether or not the corresponding PLC locations are configured. The configurator's online view SHALL show the SYNC line (source, interval last/min/max, skipped, late PDOs) above the node list.

#### Scenario: Node without status locations
- **WHEN** node 5 has no `status_location`, `state_location` or EMCY locations, and is OPERATIONAL
- **THEN** the status answer shows node 5 with state 5, status bit TRUE and boot succeeded

#### Scenario: Node refused its configuration
- **WHEN** node 23's configuration download is aborted and its boot ends with error letter J
- **THEN** the status answer shows node 23 with boot failed, error letter J with Lely's text, and a retry pending

#### Scenario: Config fingerprint
- **WHEN** the configurator holds a `canopen.json` whose SHA-256 differs from the one in the status answer
- **THEN** the configurator can tell that the runtime runs a different configuration

#### Scenario: SYNC jitter visible
- **WHEN** `"sync_source"` is `"plc_cycle"` with a 10 ms task and the online view is open
- **THEN** the SYNC line shows source "PLC cycle", the last interval near 10000 µs, and the shortest and longest intervals seen since start

#### Scenario: No SYNC
- **WHEN** the master produces no SYNC
- **THEN** the status answer gives SYNC source `none` with zero counts
