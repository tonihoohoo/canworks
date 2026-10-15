## MODIFIED Requirements

### Requirement: Node options from JSON
Each slave entry MAY give `mandatory`, `boot`, `reset_communication`, `revision_number`, `serial_number`, `heartbeat_consumer`, `retry_factor`, `time_cob_id`, `error_behavior`, and `restore_configuration`. Any other field, including the former `software_file` and `software_version`, SHALL be rejected as unknown, naming the field. The plugin SHALL pass each given value to dcfgen under its dcfgen name. A field that configures an object on the node and is left out SHALL write nothing to the node, so the node keeps the value from its EDS; this includes the node's heartbeat consumer entries (0x1016). Fields that configure only the master SHALL keep today's values when left out (`boot` true, `mandatory` false, `reset_communication` true, `retry_factor` equal to `life_time_factor`), and the expected revision number SHALL come from the EDS. A `revision_number` of 0 SHALL turn off the revision check for that node. dcfgen warnings SHALL be logged as warnings naming the node. `heartbeat_consumer` on a node SHALL be rejected when the master sends no heartbeat. When `boot` is `false`, the master SHALL NOT boot, configure or retry that node.

#### Scenario: Left-out node settings keep the EDS values
- **WHEN** node 2's EDS has a 0x1016 entry watching the master, a 0x1029 default and a 0x1012 default, and node 2's entry sets none of `heartbeat_consumer`, `error_behavior` or `time_cob_id`
- **THEN** the node's generated configuration writes nothing to 0x1016, 0x1029 or 0x1012

#### Scenario: Revision check off
- **WHEN** node 5's EDS has revision 0x00010003, the device reports 0x00010004, and node 5 has `"revision_number": 0`
- **THEN** node 5 is configured and becomes OPERATIONAL

#### Scenario: Serial number pinned
- **WHEN** node 5 has `"serial_number": "0x00001234"` and the device reports serial number 0x00005678
- **THEN** node 5 is not configured or started

#### Scenario: Node watches the master's heartbeat
- **WHEN** the master has `heartbeat_ms` 100 and `heartbeat_multiplier` 3, and node 2 has `"heartbeat_consumer": true`
- **THEN** node 2's 0x1016 is set to consume the master's heartbeat with a 300 ms timeout

#### Scenario: Firmware fields rejected
- **WHEN** node 4's entry has `"software_file": "fw/node4.bin"`
- **THEN** the plugin and the deploy tool reject the configuration, naming node 4 and the unknown field `software_file`

### Requirement: Boot SDO timeout
The `master` object MAY give `sdo_timeout_ms`, an integer from 10 to 60000; a value outside that range SHALL be rejected with the field named. The master SHALL wait this long for each SDO answer while it boots and configures a node: reading the node's identity, downloading PDO communication and mapping parameters and startup SDOs and restoring default parameters. When the field is left out the timeout SHALL be 1000 ms. The timeout SHALL NOT change the timeouts of SDO variables or of manual SDO requests from the diagnostics channel, and SHALL NOT change the generated master configuration. When a configuration SDO times out, the error log line SHALL give the timeout in milliseconds.

#### Scenario: Slow device within the default
- **WHEN** no `sdo_timeout_ms` is given and a node answers each configuration SDO after 300 ms
- **THEN** the node is configured and switched to OPERATIONAL

#### Scenario: Device slower than the timeout
- **WHEN** `"sdo_timeout_ms": 200` is given and a node answers each configuration SDO after 300 ms
- **THEN** the configuration fails with SDO abort code 0x05040000, the log line names the node, the object and the 200 ms timeout, the node stays not operational, and the master retries its boot as for any configuration error

#### Scenario: Out of range
- **WHEN** the master has `"sdo_timeout_ms": 5`
- **THEN** the plugin and the deploy tool reject the configuration and name `sdo_timeout_ms`

#### Scenario: SDO variables keep their own timeout
- **WHEN** `"sdo_timeout_ms": 5000` is given and an SDO variable has no `timeout_ms`
- **THEN** that SDO variable still times out after 1000 ms

## REMOVED Requirements

### Requirement: Firmware download
**Reason**: Toni: no need for program (firmware) download. The project is not in real use, so the config fields go too.
**Migration**: Remove `software_file` and `software_version` from node entries. Update device firmware with the vendor's tool.
