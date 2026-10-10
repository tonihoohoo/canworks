## MODIFIED Requirements

### Requirement: Master options from JSON
The `master` object MAY give `vendor_id`, `product_code`, `revision_number`, `serial_number`, `sync_window_us`, `sync_counter_overflow`, `time_cob_id`, `emcy_inhibit_time_us`, `heartbeat_consumer`, `heartbeat_multiplier`, `error_behavior`, `nmt_inhibit_time_us`, `start`, `start_nodes`, `start_all_nodes`, `reset_all_nodes`, `stop_all_nodes` and `boot_time_ms`. The plugin SHALL pass each given value to dcfgen under its dcfgen name, converting microseconds to 100 µs units where the object uses them, and SHALL use dcfgen's defaults for the rest, except `heartbeat_consumer` and `start_nodes`, which SHALL default to `true`. A `_us` value for a 100 µs object that is not a multiple of 100 SHALL be rejected. When `start` is `false`, the master SHALL boot and configure the nodes but stay PRE-OPERATIONAL, exchanging no PDOs, until the PLC program starts it with `CO_NETWORK_START` (`canopen-plc-nmt`), and the plugin SHALL log at load that the network stays PRE-OPERATIONAL until the program starts it.

#### Scenario: Existing configuration unchanged
- **WHEN** a configuration gives none of these fields
- **THEN** the generated master configuration is the same as before this change

#### Scenario: SYNC window and counter
- **WHEN** the master has `"sync_window_us": 5000` and `"sync_counter_overflow": 10`
- **THEN** the master's 0x1007 is 5000 and 0x1019 is 10, and the SYNC messages carry a counter from 1 to 10

#### Scenario: Inhibit time not a multiple of 100 µs
- **WHEN** the master has `"nmt_inhibit_time_us": 150`
- **THEN** the plugin rejects the configuration and names the field

#### Scenario: Start left to the program
- **WHEN** the master has `"start": false` and the program never runs `CO_NETWORK_START`
- **THEN** the load log says the network stays PRE-OPERATIONAL until the PLC program starts it with `CO_NETWORK_START`, the master's state byte reads 127, and no PDO is exchanged, also after all nodes have booted
