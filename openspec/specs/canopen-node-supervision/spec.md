# canopen-node-supervision Specification

## Purpose
Defines what the PLC sees when CANopen nodes are missing or fail: the PLC keeps scanning, each node's state is visible to the program, and the master recovers nodes on its own.

## Requirements

### Requirement: Keep scanning on node failure
A missing, unconfigurable, or lost slave SHALL NOT stop the PLC. A missing, unconfigurable, or lost slave that is not mandatory SHALL NOT stop the other nodes. The plugin SHALL NOT request a PLC stop because of a node failure.

#### Scenario: Slave absent at start-up
- **WHEN** the PLC starts and a configured slave that is not mandatory never answers boot-up
- **THEN** the PLC enters and stays in RUNNING, the other slaves are brought up normally, and the absent node's input locations read zero

#### Scenario: Slave lost while running
- **WHEN** an operational slave stops communicating
- **THEN** the PLC keeps running, that node's input locations keep their last received values, and the outputs mapped to that node are no longer sent to it

### Requirement: Loss detection
The master SHALL detect that an operational slave is lost using the slave's heartbeat or node guarding, as the JSON configures for that node. It SHALL report the loss within the configured timeout.

#### Scenario: Heartbeat timeout
- **WHEN** a slave configured with a heartbeat timeout sends no heartbeat within that timeout
- **THEN** the master marks the node not operational and logs the node ID and the reason

### Requirement: Per-node status bit
Each slave entry MAY give a `status_location` (an `%IX` input bit). When it is given, the plugin SHALL set that bit to TRUE while the node is OPERATIONAL and its PDO exchange is active, and to FALSE otherwise.

#### Scenario: Status follows node state
- **WHEN** node 2 has `status_location` `%IX10.0` and goes from operational to lost and back to operational
- **THEN** `%IX10.0` reads TRUE, then FALSE, then TRUE again, each change visible by the next scan cycle after the master detects it

### Requirement: Background recovery
The master SHALL keep retrying the boot-up and configuration of every node that is not operational, without operator action and without blocking other nodes or the PLC scan. A node that the PLC program holds in STOPPED or PRE-OPERATIONAL through its NMT command byte, or that an operator holds through a manual NMT command on the diagnostics channel, SHALL NOT be booted again because it left OPERATIONAL; it SHALL still be booted and configured again after a boot-up message, and its loss SHALL still be detected and reported.

#### Scenario: Slave comes back
- **WHEN** a lost or absent slave starts answering again
- **THEN** the master reconfigures its PDOs over SDO, switches it to OPERATIONAL, resumes its PDO exchange, and sets its status bit to TRUE

#### Scenario: Node stopped by the program
- **WHEN** the program holds node 5 in STOPPED through its NMT command byte
- **THEN** the master does not boot node 5 again while it reports STOPPED in its heartbeat, and logs no retry for it

#### Scenario: Node stopped by an operator
- **WHEN** an operator sends STOP to node 5 over the diagnostics channel
- **THEN** the master does not boot node 5 again while it reports STOPPED, and boots and configures it again after a boot-up message, keeping it STOPPED

### Requirement: Per-node state byte
Each slave entry MAY give a `state_location` (an `%IB` input byte). When it is given, the plugin SHALL keep that byte at the node's NMT state as CiA 301 codes it: 4 STOPPED, 5 OPERATIONAL, 127 PRE-OPERATIONAL. A node the master has never heard from, or has detected as lost, SHALL read 0. A boot-up message SHALL set 127. The state SHALL follow heartbeat and node-guarding messages, the NMT commands the master sends to the node, and loss detection.

#### Scenario: Normal boot
- **WHEN** node 5 has `state_location` `%IB20` and heartbeat supervision, and boots and is started by the master
- **THEN** `%IB20` reads 0 before the node is heard, 127 after its boot-up message, and 5 once it reports OPERATIONAL

#### Scenario: Node lost and back
- **WHEN** node 5's heartbeat times out and the node later sends a boot-up message and is reconfigured
- **THEN** `%IB20` reads 0 while the node is lost, 127 after the boot-up message and 5 after the master starts it again

#### Scenario: Node stopped
- **WHEN** node 5 reports STOPPED in its heartbeat
- **THEN** `%IB20` reads 4 and the status bit, if given, is FALSE

#### Scenario: Wrong location type
- **WHEN** `state_location` is not an `%IB` location, or overlaps another location of the configuration
- **THEN** the plugin rejects the configuration and names the node and the field

### Requirement: Mandatory nodes
Each slave entry MAY give `mandatory` (default `false`). The plugin SHALL pass it to the master configuration so that the master stays PRE-OPERATIONAL, and exchanges no PDOs with any node, until every mandatory node has booted. A mandatory node that is missing SHALL be logged as an error that names it as the reason the network is held. The PLC SHALL keep running.

#### Scenario: Mandatory node absent at start-up
- **WHEN** node 3 has `"mandatory": true` and never answers, and node 2 is present
- **THEN** the PLC keeps running, no PDO data is exchanged with node 2, node 2's status bit reads FALSE, and the log names node 3 as holding the network

#### Scenario: Mandatory node appears
- **WHEN** node 3 then starts answering
- **THEN** the master configures node 3, goes OPERATIONAL, PDO data flows with nodes 2 and 3, and both status bits read TRUE

### Requirement: Node states follow the real NMT state
A node's status bit SHALL be TRUE only while the node is OPERATIONAL and the master is OPERATIONAL. A node's state byte SHALL show the NMT state the master last saw for that node, not a value assumed from the end of the boot step.

#### Scenario: Nodes not started by the master
- **WHEN** `master.start_nodes` is `false` and node 2 boots and is configured
- **THEN** node 2's state byte reads 127 and its status bit reads FALSE

#### Scenario: Stop all nodes on a mandatory failure
- **WHEN** `master.stop_all_nodes` is `true`, node 3 is mandatory and loses its heartbeat
- **THEN** the state bytes of the stopped nodes read 4 and their status bits read FALSE

### Requirement: Master state byte
The `master` object MAY give a `state_location` (an `%IB` input byte). When it is given, the plugin SHALL keep it at the master's own NMT state: 5 OPERATIONAL, 127 PRE-OPERATIONAL, 4 STOPPED, 0 while the master is not running.

#### Scenario: Network held by a mandatory node
- **WHEN** the master has `state_location` `%IB50` and a mandatory node is missing
- **THEN** `%IB50` reads 127, and 5 once the mandatory node has booted

### Requirement: Wrong device reporting
When a node fails the identity check (error status D, M, N or O), the plugin SHALL log one error naming the node, the field that differs, the value the device reported (when it can be read back) and the expected value with its source (the EDS file name or the configured `revision_number` / `serial_number`). Further boot attempts that fail with the same reported identity SHALL NOT be logged again. The plugin SHALL NOT report a node that failed the identity check as not answering.

#### Scenario: Wrong product on the right node ID
- **WHEN** node 5 (named "rtd") uses rtd8.eds with product code 1028, the device reports 1029, and the master retries its boot several times
- **THEN** node 5 is not configured or started, the log shows one error for node 5 (rtd) with "product code", 1029 and 1028 from rtd8.eds, and no "not answering" message for node 5

#### Scenario: Right device swapped in
- **WHEN** the device is then replaced with one that matches
- **THEN** the master configures node 5 and makes it OPERATIONAL without a PLC restart

### Requirement: Per-node boot error byte
Each slave entry MAY give a `boot_error_location` (an `%IB` input byte). When it is given, the plugin SHALL set that byte to the ASCII code of the CiA 302 error status of the node's last failed boot (66 `B` no response, 68 `D` vendor ID, 74 `J` configuration download refused, 77 `M` product code, 78 `N` revision number, 79 `O` serial number, or another letter as reported), to 66 when the plugin reports the node as not answering, and to 0 while the node is OPERATIONAL. It SHALL read 0 before any boot attempt has failed.

#### Scenario: Wrong device then right device
- **WHEN** node 5 has `boot_error_location` `%IB40`, fails the identity check on its product code, and later a matching device is fitted
- **THEN** `%IB40` reads 77 while the wrong device is fitted and 0 once node 5 is OPERATIONAL

#### Scenario: Wrong location type
- **WHEN** `boot_error_location` or `master.state_location` is not an `%IB` location or overlaps another location of the configuration
- **THEN** the plugin rejects the configuration and names the field

### Requirement: Emergency message logging
The master SHALL receive the emergency (EMCY) messages of every configured slave and log each one with the node, the error code in hex, the CiA 301 error class of the code in words, the error register in hex, and the five manufacturer-specific bytes. An EMCY with error code 0x0000 SHALL be logged as the node's error reset. When a node sends more than 5 EMCY messages within one second, the plugin SHALL log at most one summary line per second for that node, giving the number of EMCY messages not logged one by one and the latest error code and error register, as the bus state log does for state changes. Receiving EMCY messages SHALL NOT change the node's NMT state, status bit or state byte, and SHALL NOT stop the PLC.

#### Scenario: Device reports a fault
- **WHEN** node 3 sends an EMCY with error code 0x4210 and error register 0x09
- **THEN** the log shows node 3, code 0x4210, its class "temperature", error register 0x09 and the manufacturer-specific bytes, and node 3 stays OPERATIONAL

#### Scenario: Error reset
- **WHEN** node 3 then sends an EMCY with error code 0x0000
- **THEN** the log shows that node 3 reset its errors

#### Scenario: Flooding node
- **WHEN** node 3 sends 50 EMCY messages within one second, the last one with code 0x5000
- **THEN** the first 5 are logged one by one, and one summary line for that second names node 3, the 45 further EMCY messages and the latest code 0x5000

#### Scenario: EMCY from an unknown node
- **WHEN** an EMCY arrives from node ID 9, which is not in the configuration
- **THEN** the plugin logs one warning naming node ID 9 and ignores further EMCY messages from it without logging them

### Requirement: Per-node EMCY inputs
Each slave entry MAY give an `emcy_code_location` (an `%IW` input word) and an `error_register_location` (an `%IB` input byte), each independently. When given, the plugin SHALL set the word to the error code and the byte to the error register of the node's most recent EMCY, visible by the next scan cycle after the master receives it. An EMCY with error code 0x0000 SHALL set the word to 0 and the byte to the error register it carries. A boot-up message from the node SHALL set both to 0. Both SHALL read 0 before the node sends any EMCY, and SHALL keep their value while the node is lost.

#### Scenario: Fault then reset
- **WHEN** node 3 has `emcy_code_location` `%IW30` and `error_register_location` `%IB31`, sends an EMCY with code 0x4210 and error register 0x09, and later an EMCY with code 0x0000 and error register 0x00
- **THEN** `%IW30` reads 16#4210 and `%IB31` reads 16#09 after the first, and both read 0 after the second

#### Scenario: Node restarts
- **WHEN** `%IW30` holds 16#4210 and node 3 sends a boot-up message
- **THEN** `%IW30` and `%IB31` read 0

#### Scenario: Node lost after a fault
- **WHEN** `%IW30` holds 16#4210 and node 3's heartbeat times out
- **THEN** `%IW30` still reads 16#4210 while the node is lost

#### Scenario: Wrong location type
- **WHEN** `emcy_code_location` is not an `%IW` location, `error_register_location` is not an `%IB` location, or either overlaps another location of the configuration
- **THEN** the plugin rejects the configuration and names the node and the field

### Requirement: Per-node NMT command byte
Each slave entry MAY give an `nmt_command_location` (an `%QB` output byte) through which the PLC program commands the node with CiA 301 NMT command codes:
- 0 or 1: the master runs the node as it does without the field (boots, configures, starts and recovers it). A change from 2 or 128 to 0 or 1 SHALL send START to a node that is booted.
- 2: the master SHALL send STOP to the node and keep it STOPPED: after any later boot of the node it SHALL configure it and then send STOP again.
- 128: the same with ENTER PRE-OPERATIONAL, keeping the node PRE-OPERATIONAL.
- 129 or 130: when the byte changes to this value, the master SHALL send RESET NODE or RESET COMMUNICATION once, then treat the node as with 0 (boot and configure it again after its boot-up message). Holding the value SHALL NOT repeat the command.
- Any other value SHALL be ignored, with one warning per change naming the node and the value.

The master SHALL act on a change within 100 ms or by the next SYNC, whichever comes first, and SHALL NOT act on the byte before the PLC program has completed its first scan cycle since start. For a node with `boot` false the master SHALL never boot or configure it, and a change to 1 SHALL send START. Each command sent SHALL be logged with the node and the command. A node held in STOPPED or PRE-OPERATIONAL SHALL have its status bit FALSE and SHALL exchange no PDOs. The location SHALL be an `%QB` location that does not overlap another location of the configuration, else the configuration SHALL be rejected naming the node and the field.

#### Scenario: Stop and restart a node
- **WHEN** node 5 is OPERATIONAL with `nmt_command_location` `%QB30` and `state_location` `%IB20`, and the program writes 2 to `%QB30` and later 0
- **THEN** after the first write `%IB20` reads 4, the status bit reads FALSE and node 5's input locations hold their last values; after the second, `%IB20` reads 5 and PDO data flows again

#### Scenario: Held node resets itself
- **WHEN** `%QB30` holds 128 and node 5 power-cycles
- **THEN** the master configures node 5 after its boot-up message and then puts it into PRE-OPERATIONAL, and `%IB20` ends at 127

#### Scenario: Reset a node from the program
- **WHEN** the program changes `%QB30` from 0 to 129 and leaves it there
- **THEN** the master sends one RESET NODE to node 5, configures and starts node 5 after its boot-up message, and sends no further reset

#### Scenario: Unknown command
- **WHEN** the program writes 7 to `%QB30`
- **THEN** the plugin logs one warning naming node 5 and the value 7, and node 5 keeps running

#### Scenario: Wrong location type
- **WHEN** `nmt_command_location` is not an `%QB` location or overlaps another location
- **THEN** the plugin rejects the configuration and names the node and the field

### Requirement: Every node is supervised or says why not
A configured node whose heartbeat consumer time is 0 (from `heartbeat_ms`, or from the EDS default of 0x1017 when `heartbeat_ms` is absent) and that has no node guarding SHALL make the config refused at load, with a message saying its loss would never be detected. A node with an explicit `"heartbeat_ms": 0` SHALL be accepted and SHALL get a warning at every start. The configurator's check SHALL do the same.

#### Scenario: Device without a heartbeat default
- **WHEN** node 7's EDS has 0x1017 default 0, the config has no `heartbeat_ms` and no guarding for node 7
- **THEN** the config is refused, naming node 7 and `heartbeat_ms`

#### Scenario: Unsupervised on purpose
- **WHEN** node 7 has `"heartbeat_ms": 0`
- **THEN** the config is accepted and each start logs a warning that node 7's loss is not detected

### Requirement: Nodes on PLC stop
The master SHALL support `master.on_plc_stop`: `"preop"` (default) sends ENTER PRE-OPERATIONAL, `"stop"` sends STOP, each to every configured node that is up, before the network closes when the PLC stops or the plugin stops; `"keep"` sends no NMT command. No output PDO SHALL be sent between the stop request and the NMT command. On the next PLC start the nodes SHALL be booted and started as usual.

#### Scenario: PLC stopped
- **WHEN** nodes 5 and 23 are OPERATIONAL and the PLC is stopped with the default `on_plc_stop`
- **THEN** both nodes get ENTER PRE-OPERATIONAL before the network closes, and are OPERATIONAL again after the next PLC start

#### Scenario: Old behaviour
- **WHEN** `on_plc_stop` is `"keep"` and the PLC is stopped
- **THEN** no NMT command is sent
