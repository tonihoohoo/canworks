# canopen-master-bringup Specification

## Purpose
Brings a CANopen network up from the OpenPLC runtime: loads the JSON network configuration and the slaves' EDS files, opens the SocketCAN interface, and configures and starts every slave node as the NMT master.

## Requirements

### Requirement: JSON network configuration
The plugin SHALL read its network configuration from the JSON file given as its config path in `plugins.conf`. Any configuration error SHALL leave the plugin inactive, and SHALL NOT stop the PLC or put the runtime into ERROR. The file SHALL describe the CAN interface, the master's node ID, the bus bit rate, and a list of slave nodes, and MAY give the SYNC period (`master.sync_period_us`). The list MAY be empty only when `master.diagnostics` is given (a scan-only configuration): the master then starts, produces its heartbeat and SYNC as configured and serves the diagnostics channel, with no slave to boot; an empty list without `master.diagnostics` SHALL reject the configuration. Each node entry SHALL give a node ID (1-127), an EDS file path, and its PDO entries; a node MAY have no PDO entries, and is then booted, supervised and sent its startup SDOs with all its PDOs switched off.

#### Scenario: Valid configuration loads
- **WHEN** the runtime starts the plugin with a config that names `vcan0`, master node ID 1, and one slave (node ID 2) with a readable EDS file
- **THEN** the plugin loads the configuration and logs the interface, the master node ID, and the number of configured slaves

#### Scenario: Missing configuration
- **WHEN** the config file does not exist
- **THEN** the plugin logs a warning naming the expected path, stays inactive, opens no CAN interface, and the PLC starts and runs normally

#### Scenario: Malformed configuration
- **WHEN** the config file is not valid JSON or lacks a required field
- **THEN** the plugin logs an error naming the file and the missing or invalid field, stays inactive, opens no CAN interface, and the PLC starts and runs normally

#### Scenario: Duplicate or out-of-range node IDs
- **WHEN** two slave entries share a node ID, a node ID is outside 1-127, or a slave uses the master's node ID
- **THEN** the plugin rejects the configuration, names the offending node IDs in the error log, and stays inactive

#### Scenario: Node without PDOs
- **WHEN** a slave entry has neither `tx_pdos` nor `rx_pdos`
- **THEN** the plugin accepts the configuration, boots the node, writes its startup SDOs and disables every PDO its EDS defines

#### Scenario: Scan-only configuration
- **WHEN** the config has `master.diagnostics` and `"nodes": []`
- **THEN** the plugin loads it, opens the CAN interface, starts the master and the diagnostics channel, and logs 0 slaves

#### Scenario: Empty node list without diagnostics
- **WHEN** the config has `"nodes": []` and no `master.diagnostics`
- **THEN** the plugin rejects the configuration, saying the node list is empty

#### Scenario: No SYNC period
- **WHEN** the `master` object gives no `sync_period_us`, or gives 0, and every configured PDO is event-driven
- **THEN** the plugin loads the configuration and logs that the master produces no SYNC

### Requirement: General EDS support
The plugin SHALL accept any CiA 306-conformant EDS file for a slave, and SHALL also accept vendor EDS files whose only defects are in objects the configuration does not use (see "EDS lint scope"). On the device, at load, it SHALL derive the master and per-slave device configurations from the JSON and the EDS files, with no step run by the user beforehand.

#### Scenario: Device configuration generated at load
- **WHEN** the plugin starts with a valid JSON config and valid EDS files
- **THEN** it generates the device configurations on the device before bringing the network up, and logs where it wrote them

#### Scenario: Invalid EDS file
- **WHEN** a referenced EDS file is missing or cannot be parsed even after the corrections in "Prepared EDS copy"
- **THEN** the plugin logs an error naming the node ID and the EDS file, and stays inactive

#### Scenario: PDO entry not in the EDS
- **WHEN** a PDO entry in the JSON refers to an object index or subindex that the node's EDS does not define as PDO-mappable
- **THEN** the plugin rejects the configuration and names the node ID, index, and subindex

### Requirement: CAN interface bring-up
The plugin SHALL open the configured SocketCAN interface when the PLC starts. It SHALL close the interface when the PLC stops or the plugin is unloaded.

#### Scenario: Interface available
- **WHEN** the PLC starts and the configured interface exists and is up
- **THEN** the plugin opens it and begins network bring-up

#### Scenario: Interface missing or down
- **WHEN** the PLC starts and the configured interface does not exist or is down
- **THEN** the plugin logs an error naming the interface, the PLC keeps scanning, every node reports not operational, and the plugin retries opening the interface in the background

### Requirement: Slave configuration and start-up
For each configured slave, the master SHALL reset the node, download its PDO communication and mapping parameters over SDO so that they match the JSON, and then switch the node to OPERATIONAL. After this, the master SHALL transmit SYNC at the configured period.

#### Scenario: Slave boots and becomes operational
- **WHEN** a configured slave answers the master's boot-up sequence and accepts every SDO download
- **THEN** its PDO mapping matches the configuration, it is switched to OPERATIONAL, and the plugin logs that the node is operational

#### Scenario: SDO download rejected
- **WHEN** a slave aborts an SDO download during configuration
- **THEN** the plugin logs the node ID, the object index and subindex, and the SDO abort code, leaves that node not operational, and continues bringing up the other nodes

### Requirement: CAN adapter configuration from JSON
The config SHALL describe the CAN adapter in an `adapter` object with a `type` field. The supported types are `socketcan` (defined here) and `slcan` (defined in `canopen-slcan-adapter`). The type `socketcan` has `interface` (required), `bitrate` (required, a CiA 301 rate from 10000 to 1000000), `configure_link` (optional, default true), and `restart_ms` (optional bus-off auto-restart delay). An unknown `type` SHALL leave the plugin inactive with an error naming the type and the supported types. When `configure_link` is true and the PLC starts, the plugin SHALL make the interface run at the configured bit rate and bring it up. When `configure_link` is false, the plugin SHALL leave the link as it finds it. A virtual interface (`vcan`) SHALL only be brought up, since it has no bit rate.

#### Scenario: Link down with no bit rate set
- **WHEN** the PLC starts with `{"type": "socketcan", "interface": "can0", "bitrate": 500000}` and `can0` is down
- **THEN** the plugin sets `can0` to 500 kbit/s, brings it up, logs the interface and bit rate, and starts network bring-up

#### Scenario: Link already up at the configured rate
- **WHEN** `can0` is up at 500 kbit/s and the config asks for 500000
- **THEN** the plugin uses the link without taking it down

#### Scenario: Link up at a different rate
- **WHEN** `can0` is up at 250 kbit/s and the config asks for 500000
- **THEN** the plugin logs a warning naming both rates, takes the link down, sets 500 kbit/s, and brings it up again

#### Scenario: Link left to the system
- **WHEN** `configure_link` is false and `can0` is up at 250 kbit/s while the config says 500000
- **THEN** the plugin does not change the link and logs a warning that the link rate differs from the config

#### Scenario: Not permitted to configure the link
- **WHEN** the plugin cannot change the link because it lacks `CAP_NET_ADMIN`
- **THEN** it logs an error naming the interface and the missing permission, the PLC keeps scanning, every node reports not operational, and the plugin retries in the background as for a missing interface

#### Scenario: Unknown adapter type
- **WHEN** the config has `adapter.type` set to `pcan`
- **THEN** the plugin logs an error naming `pcan` and the supported types `socketcan` and `slcan`, and stays inactive

### Requirement: Startup SDOs
Each node entry MAY have an `sdo` list of object writes, each giving `index`, `subindex`, `type`, and `value`. During node configuration the master SHALL write them in list order, after the PDO communication and mapping parameters and before switching the node to OPERATIONAL. An abort SHALL be handled as for any configuration SDO: logged with node ID, index, subindex, and abort code, leaving that node not operational while other nodes continue.

#### Scenario: Heartbeat period set by startup SDO
- **WHEN** node 2 has `"sdo": [{"index": "0x1017", "subindex": 0, "type": "UNSIGNED16", "value": 100}]`
- **THEN** during configuration the master writes 100 to 0x1017:00 on node 2 before the NMT start, and the write shows on the bus

#### Scenario: Value does not fit the type
- **WHEN** a startup SDO has `type: "UNSIGNED8"` and `value: 300`
- **THEN** the config is rejected with an error naming the node ID, the index and subindex, and the value

#### Scenario: Slave rejects a startup SDO
- **WHEN** the slave aborts a startup SDO write
- **THEN** the plugin logs the node ID, index, subindex, and abort code, and the node stays not operational

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

### Requirement: Node options from JSON
Each slave entry MAY give `mandatory`, `boot`, `reset_communication`, `revision_number`, `serial_number`, `heartbeat_consumer`, `retry_factor`, `time_cob_id`, `error_behavior`, `restore_configuration`, `software_file` and `software_version`. The plugin SHALL pass each given value to dcfgen under its dcfgen name. A field that configures an object on the node and is left out SHALL write nothing to the node, so the node keeps the value from its EDS; this includes the node's heartbeat consumer entries (0x1016). Fields that configure only the master SHALL keep today's values when left out (`boot` true, `mandatory` false, `reset_communication` true, `retry_factor` equal to `life_time_factor`), and the expected revision number SHALL come from the EDS. A `revision_number` of 0 SHALL turn off the revision check for that node. dcfgen warnings SHALL be logged as warnings naming the node. `heartbeat_consumer` on a node SHALL be rejected when the master sends no heartbeat. When `boot` is `false`, the master SHALL NOT boot, configure or retry that node.

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

### Requirement: Firmware download
When a slave entry gives `software_file` (a path relative to the configuration folder) and `software_version`, the master SHALL compare the node's software version (0x1F56 sub 1) with `software_version` during boot and, when they differ, download the file to the node before configuring it. A missing file SHALL be rejected at load with the node and path named. The deploy tool SHALL ship the file with the configuration the same way it ships EDS files.

#### Scenario: Old firmware on the node
- **WHEN** node 4 reports software version 1, its entry gives `"software_version": 2` and `"software_file": "fw/node4.bin"`
- **THEN** the master downloads fw/node4.bin to node 4, then configures and starts it

#### Scenario: Firmware file missing
- **WHEN** `software_file` names a file that is not in the configuration folder
- **THEN** the plugin rejects the configuration and names node 4 and the path

### Requirement: Boot SDO timeout
The `master` object MAY give `sdo_timeout_ms`, an integer from 10 to 60000; a value outside that range SHALL be rejected with the field named. The master SHALL wait this long for each SDO answer while it boots and configures a node: reading the node's identity and software version, downloading PDO communication and mapping parameters and startup SDOs, restoring default parameters, and downloading firmware. When the field is left out the timeout SHALL be 1000 ms. The timeout SHALL NOT change the timeouts of SDO variables or of manual SDO requests from the diagnostics channel, and SHALL NOT change the generated master configuration. When a configuration SDO times out, the error log line SHALL give the timeout in milliseconds.

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

### Requirement: Skip configuration when unchanged
A slave entry MAY give `config_check` (default `false`). When it is `true`, the plugin SHALL compute a non-zero configuration date and a non-zero configuration time for the node from the configuration it downloads to that node, such that any change to what is downloaded changes at least one of them, and the same configuration gives the same values at every start. At boot, the master SHALL read the node's 0x1020 sub 1 and sub 2; when both equal the computed values, it SHALL NOT restore defaults or download any configuration to the node, SHALL start the node as for a configured node, and the plugin SHALL log that the node's configuration is unchanged. Otherwise the master SHALL configure the node as without `config_check` and, after the last configuration write succeeded, write the computed date to 0x1020 sub 1 and the time to 0x1020 sub 2. A node whose configuration is unchanged and that is already OPERATIONAL when the master boots it SHALL count as configured and running, and SHALL NOT be reset for it. `config_check` SHALL be rejected, naming the node and object, when the node's EDS does not define 0x1020 sub 1 and sub 2 as writable.

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

### Requirement: Store configuration on the node
Saving is never automatic. A slave entry MAY give `store_configuration`, a sub-index of 0x1010 from 1 to 127; it is off when left out, and the master SHALL NOT write to a node's 0x1010 without it. It SHALL be rejected unless the node also has `config_check`, so that a node saves only after a download and never at every boot. After the master configured the node and, with `config_check`, wrote 0x1020, it SHALL write the CiA 301 "save" signature (0x65766173) to that sub-index; a node that aborts it SHALL be handled like any configuration SDO abort. When the configuration is unchanged (see Skip configuration when unchanged) nothing SHALL be stored. A sub-index that the node's EDS does not define as writable SHALL be rejected, naming the node and the sub-index.

#### Scenario: Save after the download
- **WHEN** node 2 has `"config_check": true` and `"store_configuration": 1`, and its configuration was downloaded
- **THEN** after writing 0x1020 the master writes 0x65766173 to node 2's 0x1010 sub 1

#### Scenario: No save unless asked
- **WHEN** node 2 has `"config_check": true` and no `store_configuration`, and its configuration was downloaded
- **THEN** the master writes nothing to node 2's 0x1010

#### Scenario: Store without a configuration check
- **WHEN** node 2 has `"store_configuration": 1` and no `config_check`
- **THEN** the plugin and the deploy tool reject the configuration, saying `store_configuration` needs `config_check`

#### Scenario: Sub-index not in the EDS
- **WHEN** node 2 has `"store_configuration": 3` and its EDS defines 0x1010 sub 1 only
- **THEN** the plugin and the deploy tool reject the configuration, naming node 2 and 0x1010 sub 3

### Requirement: Prepared EDS copy
The plugin SHALL read each node's EDS, for its own EDS checks and for dcfgen, through a copy with these lossless corrections, and SHALL leave the original file unchanged:
- a file that is not valid UTF-8 is converted from CP1252 (bytes CP1252 leaves undefined are read as Latin-1);
- a value written `<number>+$NODEID` is rewritten `$NODEID+<number>`;
- a REAL32 or REAL64 DefaultValue, ParameterValue, LowLimit or HighLimit written as a decimal number is rewritten as the hexadecimal bit pattern of the same value;
- an OCTET_STRING or DOMAIN DefaultValue or ParameterValue that does not start with a hexadecimal digit, which Lely's EDS parser cannot read, is cleared.

The plugin SHALL log one line per node that names the EDS, the kind of each correction and how often it was made. A cleared value SHALL also be logged with its object and its original value. When no correction applies, the plugin SHALL use the original file.

#### Scenario: CP1252 vendor EDS
- **WHEN** a node's EDS contains the byte 0x94 in a `[Comments]` line and is otherwise valid
- **THEN** the node configures as with a UTF-8 file, and the log says the EDS was converted from CP1252

#### Scenario: Decimal REAL default
- **WHEN** an EDS gives `DefaultValue=12.345` for a REAL32 object
- **THEN** dcfgen reads the file without error and the log names the REAL rewrite

#### Scenario: OCTET_STRING value Lely cannot read
- **WHEN** an EDS gives `DefaultValue=----` for the OCTET_STRING object 0x2051
- **THEN** the plugin accepts the EDS and logs that the value of 0x2051 was cleared and was `----`

### Requirement: EDS lint scope
Before generating the device configurations, the plugin SHALL run dcfgen's EDS lint on each prepared EDS and sort the findings. A finding SHALL be **blocking** when it names an object in the communication area 0x1000-0x1FFF, which dcfgen reads and writes, and is not limit-only. A finding is **limit-only** when it is about a LowLimit or HighLimit, or about a DefaultValue or ParameterValue that lies outside the object's own limits but inside the range of its data type. Every other finding is **non-blocking**, including findings in objects from 0x2000 up and findings that name no object. Objects mapped into PDOs keep the data type, access type and mappability checks the plugin already runs. dcfgen SHALL be run with lint errors not fatal, so the plugin's rule decides.

The master field `eds_lint` SHALL choose what fails:
- `"communication"` (default): a blocking finding stops the load. Non-blocking findings are logged as one warning per EDS, with their count and the first three.
- `"all"`: any finding stops the load.
- `"off"`: nothing stops the load. Findings are logged as one warning per EDS.

A load stopped by the lint SHALL log an error naming the node, the EDS, each finding that stopped it with its object, and the `eds_lint` setting that would accept it. The pre-contract field `strict_eds` SHALL be read as `eds_lint` `"all"` when `true` and `"off"` when `false`. A config with both fields SHALL be rejected, naming both.

#### Scenario: Signed hex values in profile objects
- **WHEN** a drive EDS with `LowLimit=0xFFFF` on INTEGER16 0x60C0 is used and `eds_lint` is unset
- **THEN** the plugin loads, and logs one warning that names the EDS and the findings in 0x60C0 and 0x60C2

#### Scenario: Limit typo in a communication object
- **WHEN** an EDS gives 0x1800 sub 1 `DefaultValue=$NODEID+0x180` with `HighLimit=0x18F`, the node ID is 23, and `eds_lint` is unset
- **THEN** the plugin loads and the warning names the finding in 0x1800 sub 1

#### Scenario: Broken communication object
- **WHEN** an EDS gives 0x1A00 sub 0 the data type UNSIGNED16 and `eds_lint` is unset
- **THEN** the plugin stays inactive and logs the node, the EDS, the finding in 0x1A00 sub 0 and that `eds_lint: "off"` would accept it

#### Scenario: Old strict_eds true
- **WHEN** the config has `"strict_eds": true` and an EDS has a finding in object 0x6061
- **THEN** the plugin stays inactive, as before this change

#### Scenario: Both fields
- **WHEN** the master has `"strict_eds": false` and `"eds_lint": "communication"`
- **THEN** the configuration is rejected and the error names both fields

### Requirement: No configuration file
When the PLC starts and `plugins.conf` gives the plugin no config path, or no file exists at that path, the plugin SHALL log a warning (naming the path when one is given), open no CAN interface, and let the PLC run normally without CANopen I/O.

#### Scenario: No config file at the configured path
- **WHEN** the PLC starts and the plugin's config path from `plugins.conf` names a file that does not exist
- **THEN** the plugin logs a warning naming that path, opens no CAN interface, and the PLC scans normally

#### Scenario: No config path given
- **WHEN** the PLC starts and the plugin's `plugins.conf` entry has an empty config path
- **THEN** the plugin logs a warning that no configuration file was given, opens no CAN interface, and the PLC scans normally

### Requirement: Assign node IDs by LSS at start
A slave entry MAY give an `lss` object with `assign` (boolean, default `false`) and `store` (boolean, default `false`). A node with `"assign": true` SHALL also give `serial_number`; its LSS address is the vendor ID and product code of its EDS `[DeviceInfo]`, its `serial_number`, and its `revision_number` when that is given and not 0. At every master start, before the master sends its first NMT command and before any node boots, the master SHALL, for each node with `lss.assign` in ascending node ID order, look for a device with that LSS address by switching it into LSS configuration state, with the node's `revision_number` or, when that is left out or 0, first with the EDS revision; when no device answers to the EDS revision, by searching the revision range 0 to 0xFFFFFFFF with the other three values fixed. When the device is found, the master SHALL read its node ID; when it differs from the node's `node_id`, the master SHALL set the node ID, and SHALL then switch all devices back to the LSS waiting state. The plugin SHALL log one line per node: assigned (with the previous ID, or "none" for 0xFF), already right, not found, or refused, with the reason. A device that is not found or refuses SHALL NOT stop the start of the other nodes; that node then boots and fails as a node that does not answer, with the usual retries and status. The master's start SHALL reset the communication of the assigned nodes, so a set node ID becomes active before their boot. Nodes without `lss.assign` SHALL see no LSS traffic other than the switch to waiting state, and a configuration without any `lss.assign` node SHALL send no LSS frame at all.

#### Scenario: Device without a node ID
- **WHEN** node 12 has `"lss": {"assign": true}` and `serial_number` 0x00001234, and a device with that vendor ID, product code and serial number is on the bus with node ID 0xFF
- **THEN** the master sets its node ID to 12 before boot, the log says node 12 was assigned (previous: none), and node 12 boots and is configured like any node

#### Scenario: Device already has the right ID
- **WHEN** node 12 has `lss.assign` and the matching device already has node ID 12
- **THEN** the master sends no LSS "configure node-ID" or "store configuration" request to it, and the log says node 12 already had its ID

#### Scenario: Revision found by search
- **WHEN** node 12 has `lss.assign`, no `revision_number`, and the device reports revision 0x00020003
- **THEN** the master finds the device and assigns ID 12

#### Scenario: Device not on the bus
- **WHEN** node 12 has `lss.assign` and no device with its LSS address answers
- **THEN** the log says node 12 was not found by LSS, the other nodes start as usual, and node 12 is handled as a node that does not answer

#### Scenario: No LSS nodes
- **WHEN** no node has `lss.assign`
- **THEN** the master sends no LSS frame (CAN-ID 0x7E5) at any time

#### Scenario: Missing serial number
- **WHEN** node 12 has `"lss": {"assign": true}` and no `serial_number`
- **THEN** the plugin and the deploy tool reject the configuration, saying node 12's LSS assignment needs `serial_number`

### Requirement: LSS store is opt-in
The master SHALL NOT send LSS "store configuration" to a device unless its node has `"lss": {"assign": true, "store": true}`. With `store`, the master SHALL store only right after it set a new node ID for that device, never when the device already had the right ID; a store the device refuses SHALL be logged as a warning with the reason and SHALL NOT stop the node's boot. `store` without `assign` SHALL be rejected.

#### Scenario: No store unless asked
- **WHEN** node 12 has `"lss": {"assign": true}` and the master sets its node ID from 0xFF to 12
- **THEN** no LSS "store configuration" request is sent

#### Scenario: Store after a change
- **WHEN** node 12 has `"lss": {"assign": true, "store": true}` and its device has node ID 0xFF
- **THEN** the master sets node ID 12 and then sends one LSS "store configuration" request to that device

#### Scenario: Store when nothing changed
- **WHEN** node 12 has `"lss": {"assign": true, "store": true}` and its device already has node ID 12
- **THEN** no LSS "store configuration" request is sent

#### Scenario: Store without assign
- **WHEN** node 12 has `"lss": {"store": true}`
- **THEN** the plugin and the deploy tool reject the configuration, saying `lss.store` needs `lss.assign`

### Requirement: LSS assignment before a boot retry
When a node with `lss.assign` is due for a boot retry and has not answered since its last boot attempt, the master SHALL first run the LSS assignment for that node alone (as at start, including `store`) and, when it set a new node ID on a device that had no node ID (0xFF), SHALL switch that device to the LSS waiting state so it starts with the new ID; the retry SHALL then proceed as usual. The master SHALL NOT reset the communication of any other node for this. When the found device already had a different, valid node ID, the master SHALL set and (with `store`) store the new ID, log that the device keeps its old ID until it is reset or power-cycled, and SHALL NOT send an NMT command to the old ID.

#### Scenario: Device power-cycled during operation
- **WHEN** node 12 has `"lss": {"assign": true}` without `store`, the bus is OPERATIONAL, and node 12's device loses power and comes back with node ID 0xFF
- **THEN** at node 12's next boot retry the master assigns ID 12 again, the device boots, and node 12 becomes OPERATIONAL without the other nodes being reset

#### Scenario: Device with an old ID
- **WHEN** node 12's device is found at a retry with node ID 5
- **THEN** the master sets node ID 12, the log says the device keeps node ID 5 until it is reset or power-cycled, and no NMT command goes to node 5

### Requirement: LSS configuration checks
`lss.assign` SHALL be rejected for a node with `reset_communication: false`, since the new node ID only becomes active on a communication reset. Two nodes with `lss.assign` and the same vendor ID, product code and serial number (and the same revision, or either revision left out or 0) SHALL be rejected, naming both nodes. When a node with `lss.assign` has an EDS whose `[DeviceInfo]` does not say `LSS_Supported=1` (left out or 0), the plugin and the deploy tool SHALL warn, naming the node, and SHALL accept the configuration.

#### Scenario: Reset communication off
- **WHEN** node 12 has `lss.assign` and `"reset_communication": false`
- **THEN** the plugin and the deploy tool reject the configuration, naming node 12 and both settings

#### Scenario: Same device twice
- **WHEN** nodes 12 and 13 both have `lss.assign` with the same vendor ID, product code and serial number
- **THEN** the configuration is rejected, naming nodes 12 and 13

#### Scenario: EDS says no LSS
- **WHEN** node 12 has `lss.assign` and its EDS does not say `LSS_Supported=1`
- **THEN** a warning names node 12 and the configuration is accepted

### Requirement: TIME producer
The `master` object MAY give `time_period_ms` (100 to 3600000). When given, the master SHALL produce TIME: it SHALL set the producer bit (bit 30) in its own 0x1012, using `time_cob_id` when given and COB-ID 0x100 otherwise, and SHALL send a TIME_OF_DAY message from the host's real-time clock once the bus is up and then every `time_period_ms`. After the bus recovers, it SHALL send TIME again at once. Without `time_period_ms` the master SHALL send no TIME. A `time_period_ms` outside the range SHALL reject the configuration, naming the field.

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

### Requirement: TIME producer logging
When `time_period_ms` is given, the plugin SHALL log at start the COB-ID and period it produces TIME with. It SHALL log a warning once when no configured node's `time_cob_id` has the consumer bit (bit 31) set, saying that no configured node is set to consume TIME.

#### Scenario: No consumer configured
- **WHEN** `time_period_ms` is 1000 and no node sets `time_cob_id` with bit 31
- **THEN** the plugin logs the TIME COB-ID and period, and one warning that no configured node consumes TIME

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

### Requirement: Helper programs run with limits
`dcfgen` and the EDS lint SHALL run as programs found once at start by absolute path, with Python in isolated mode, and SHALL be stopped after 60 s; a time-out or a failure to collect the program's exit status SHALL count as a failure of that step, logged with the reason, and SHALL NOT leave the PLC start waiting.

#### Scenario: Hung generator
- **WHEN** `dcfgen` does not finish within 60 s
- **THEN** it is stopped, the network does not start, the log says `dcfgen` timed out, and the runtime's start returns

### Requirement: Interface names are checked
An interface name SHALL have 1 to 15 characters from letters, digits, `_`, `.`, `:` and `-`, for every network kind; other names SHALL make the config refused at load, and the configurator's check SHALL refuse them too.

#### Scenario: Long name
- **WHEN** a network's interface is `can_machine_main_bus`
- **THEN** the config is refused naming the interface and the 15-character limit
