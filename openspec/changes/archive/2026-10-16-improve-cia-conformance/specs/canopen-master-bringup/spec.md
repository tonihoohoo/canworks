## MODIFIED Requirements

### Requirement: Skip configuration when unchanged
A slave entry MAY give `config_check` (default `false`). When it is `true`, the plugin SHALL compute a configuration date from 1 to 65535 and a configuration time from 1 to 86 399 999 for the node, so both are valid values for CiA 301's days since 1984-01-01 and milliseconds after midnight, from the configuration it downloads to that node, such that any change to what is downloaded changes at least one of them, and the same configuration gives the same values at every start. At boot, the master SHALL read the node's 0x1020 sub 1 and sub 2; when both equal the computed values, it SHALL NOT restore defaults or download any configuration to the node, SHALL start the node as for a configured node, and the plugin SHALL log that the node's configuration is unchanged. Otherwise the master SHALL configure the node as without `config_check` and, after the last configuration write succeeded, write the computed date to 0x1020 sub 1 and the time to 0x1020 sub 2. A node whose configuration is unchanged and that is already OPERATIONAL when the master boots it SHALL count as configured and running, and SHALL NOT be reset for it. `config_check` SHALL be rejected, naming the node and object, when the node's EDS does not define 0x1020 sub 1 and sub 2 as writable.

#### Scenario: First boot with a configuration check
- **WHEN** node 2 has `"config_check": true` and reports 0 in 0x1020 sub 1 and sub 2
- **THEN** the master downloads node 2's configuration, writes the computed date and time to 0x1020 sub 1 and sub 2, and starts node 2

#### Scenario: Unchanged configuration
- **WHEN** node 2 has `"config_check": true`, still holds the date and time written at its previous configuration, and boots again with the same `canopen_config.json` and EDS
- **THEN** the master writes nothing to node 2 except NMT commands, the log says node 2's configuration is unchanged, and node 2 becomes OPERATIONAL

#### Scenario: Changed configuration
- **WHEN** the TPDO event timer of node 2 is changed in `canopen_config.json` and the PLC is restarted
- **THEN** the master downloads node 2's configuration again and writes new date and time values to 0x1020

#### Scenario: Master restarted while the node runs
- **WHEN** the PLC runtime restarts while node 2 stays powered and OPERATIONAL with an unchanged configuration
- **THEN** node 2 counts as configured and running, its status bit becomes TRUE, and it is not reset

#### Scenario: EDS without a configuration date
- **WHEN** node 5 has `"config_check": true` and its EDS has no object 0x1020
- **THEN** the plugin and the deploy tool reject the configuration, naming node 5 and object 0x1020

#### Scenario: Values in the CiA 301 ranges
- **WHEN** a node with `"config_check": true` is configured from any configuration
- **THEN** the value written to 0x1020 sub 1 is 1 to 65535 and the value written to 0x1020 sub 2 is 1 to 86 399 999

### Requirement: SYNC from the PLC cycle
With `"master.sync_source": "plc_cycle"` the master SHALL send one SYNC from `cycle_start()` on every `sync_cycles`-th PLC frame (default 1), after the inputs were copied to the PLC, with the outputs the previous frame published at `cycle_end()`. Lely's SYNC timer SHALL NOT run (master 0x1006 = 0); the frame SHALL use the 0x1005 COB-ID and the `sync_counter_overflow` counter. While the master is in NMT STOPPED it SHALL send no SYNC and SHALL NOT count the frames as skipped; it SHALL resume with the next due frame when the master leaves STOPPED. The counter SHALL start again at 1 when the master resets communication. Without `sync_source`, or with `"timer"`, SYNC SHALL work as before.

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

#### Scenario: Master stopped
- **WHEN** `"sync_source"` is `"plc_cycle"`, the PLC runs, and the master is put into NMT STOPPED for 5 seconds
- **THEN** the master sends no SYNC during those 5 seconds, the skipped count does not rise, and SYNC resumes when the master returns to PRE-OPERATIONAL or OPERATIONAL

#### Scenario: Counter after reset communication
- **WHEN** `"sync_counter_overflow"` is 10, the last SYNC carried counter 6, and the master resets communication
- **THEN** the next SYNC carries counter 1

### Requirement: TIME producer
The `master` object MAY give `time_period_ms` (100 to 3600000). When given, the master SHALL produce TIME: it SHALL set the producer bit (bit 30) in its own 0x1012, using `time_cob_id` when given and COB-ID 0x100 otherwise, and SHALL send a TIME_OF_DAY message from the host's real-time clock once the bus is up and then every `time_period_ms`. After the bus recovers, it SHALL send TIME again at once. While the master is in NMT STOPPED it SHALL send no TIME, and SHALL send TIME at once when it leaves STOPPED. Without `time_period_ms` the master SHALL send no TIME. A `time_period_ms` outside the range SHALL reject the configuration, naming the field.

#### Scenario: TIME every second
- **WHEN** `master.time_period_ms` is 1000 and no `time_cob_id` is given
- **THEN** the master sends a 6-byte TIME message with COB-ID 0x100 once the bus is up and then about every second, carrying milliseconds since midnight and days since 1984-01-01 from the host clock

#### Scenario: Own COB-ID
- **WHEN** `master.time_cob_id` is 0x180 and `time_period_ms` is 5000
- **THEN** TIME messages use COB-ID 0x180

#### Scenario: Not configured
- **WHEN** `canworks.json` has no `master.time_period_ms`
- **THEN** no TIME message is sent, as before

#### Scenario: Out of range
- **WHEN** `master.time_period_ms` is 10
- **THEN** the plugin rejects the configuration and names `master.time_period_ms`

#### Scenario: Bus comes back
- **WHEN** the CAN interface goes down and comes back while `time_period_ms` is 60000
- **THEN** the master sends a TIME message as soon as the bus is up again, without waiting for the rest of the period

#### Scenario: Master stopped
- **WHEN** `master.time_period_ms` is 1000 and the master is put into NMT STOPPED for 5 seconds
- **THEN** no TIME message is sent during those 5 seconds, and one is sent as soon as the master leaves STOPPED
