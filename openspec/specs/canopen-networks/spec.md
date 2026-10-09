# canopen-networks Specification

## Purpose
Lets one PLC run several CANopen networks, one master per CAN interface, from one configuration file, with each network running and failing on its own.

## Requirements

### Requirement: Network list
A version 2 config SHALL hold a `networks` list of 1 to 8 entries. Each CANopen entry SHALL have an `adapter`, a `master` and a `nodes` list with the same fields and meaning as the version 1 top level, and MAY have a `name`. A J1939 entry (`"protocol": "j1939"`) SHALL have an `adapter` and a `j1939` object as `j1939-config` defines. A version 1 config SHALL be read as one CANopen network with no name.

#### Scenario: Two networks
- **WHEN** a version 2 config has networks on `can0` (nodes 2 and 3) and `can1` (nodes 2 and 10)
- **THEN** the plugin loads it and logs one line per network naming its interface, bit rate, master node ID and number of slaves

#### Scenario: Version 1 file
- **WHEN** the plugin loads `config/pingpong/canopen_config.json` (version 1)
- **THEN** it runs one network exactly as before this change, with the same log lines and the same generated files

#### Scenario: Too many networks
- **WHEN** a version 2 config has 9 networks
- **THEN** the configuration is rejected, saying at most 8 networks are supported

#### Scenario: CANopen and J1939 networks
- **WHEN** a version 2 config has a CANopen network on `can0` and a J1939 network on `can1`
- **THEN** the plugin loads it and logs one line for the CANopen network as above and one for the J1939 network naming its interface, bit rate, address and numbers of received and sent PGNs

### Requirement: Network names
A network's `name` SHALL match `[A-Za-z][A-Za-z0-9_]*` and be at most 16 characters; without `name`, the network SHALL be named after its adapter's `interface` when the interface name matches that pattern, and the config SHALL be rejected otherwise. Names SHALL be unique in the file, compared without case.

#### Scenario: Default name
- **WHEN** a network has no `name` and its adapter interface is `can1`
- **THEN** the network is named `can1` in logs, diagnostics and exports

#### Scenario: Duplicate names
- **WHEN** two networks are both named `drives` (or `Drives` and `drives`)
- **THEN** the configuration is rejected, naming both JSON paths

#### Scenario: Interface name that cannot be a network name
- **WHEN** a network has no `name` and its interface is `can-x.1`
- **THEN** the configuration is rejected, asking for a `name`

### Requirement: Networks use separate adapters
No two networks SHALL use the same CAN interface, and no two `slcan` adapters SHALL use the same serial device.

#### Scenario: Same interface twice
- **WHEN** two networks both have adapter interface `can0`
- **THEN** the configuration is rejected, naming both networks and the interface

### Requirement: Per-network checks
Node ID uniqueness, the master's node ID, COB-ID clashes and automatic COB-IDs SHALL be checked and assigned within each network only. The same node ID MAY appear in different networks, and each network MAY use any master node ID.

#### Scenario: Same node ID on two networks
- **WHEN** network `io` and network `drives` both have a node 2
- **THEN** the configuration loads and each network boots its own node 2

#### Scenario: Same COB-ID on two networks
- **WHEN** a TPDO on network `io` and an RPDO on network `drives` use COB-ID 0x181
- **THEN** the configuration loads, because the frames are on different buses

### Requirement: IEC locations unique across networks
Every IEC location in the file (PDO entries, SDO variables, status, state, EMCY, NMT command and bus diagnostic locations) SHALL be checked against every other location in the file, across networks, with the same overlap rules as within one network.

#### Scenario: Clash between networks
- **WHEN** a TPDO entry on network `io` and a TPDO entry on network `drives` both map `%IW100`
- **THEN** the configuration is rejected, naming both JSON paths and the location

### Requirement: A config error stops every network
Any configuration, EDS or dcfgen error in any network SHALL leave the whole plugin inactive with no CAN interface opened, as for a single network, and the log SHALL name the network of each problem.

#### Scenario: One network has a bad EDS
- **WHEN** network `drives` names an EDS that does not exist and network `io` is valid
- **THEN** the plugin logs the error with `drives` in it, opens neither interface, and the PLC runs normally

### Requirement: Networks run independently
Each network SHALL have its own CAN connection, master, SYNC, heartbeat, TIME, node supervision, boot retries and bus diagnostics. An interface that is missing, down or bus-off SHALL affect only its own network's nodes, status bits and bus state byte; the other networks SHALL keep exchanging PDOs.

#### Scenario: One interface unplugged
- **WHEN** two networks run and the USB adapter of network `drives` is unplugged
- **THEN** network `drives` reports no bus and its nodes go down (inputs hold, outputs stop), while network `io` keeps its nodes operational and its inputs updating every scan

#### Scenario: Interface comes back
- **WHEN** the adapter of network `drives` is plugged in again
- **THEN** network `drives` reconnects and boots its nodes, and network `io` is not restarted

### Requirement: Same scan for all networks
At each PLC scan, the inputs of every running network SHALL be copied into the PLC image before the program runs, and the outputs SHALL be handed to every network after it runs, with no network's work blocking the scan.

#### Scenario: Inputs from both networks in one scan
- **WHEN** a node on `io` and a node on `drives` both send new TPDO values before a scan
- **THEN** the program sees both new values in that scan

### Requirement: Network in log messages
With more than one network, every log line about a network, its master, its bus or its nodes SHALL start with the network name. With one network, log lines SHALL stay as they were.

#### Scenario: Node lost on a named network
- **WHEN** node 10 on network `drives` stops its heartbeat
- **THEN** the log line reads `drives: node 10 (...) ...` with the same text as for a single network after the prefix

### Requirement: Generated files per network
With a version 2 config, each network's dcfgen output and prepared EDS copies SHALL go into `.canworks/<network name>/` next to the config, and SHALL be reused while that network's part of the config and its EDS files are unchanged. A version 1 config SHALL keep using `.canworks/`.

#### Scenario: Change one network only
- **WHEN** only a PDO on network `io` changes between two PLC starts
- **THEN** the log says the device configuration was generated for `io` and reused for `drives`

### Requirement: Protocols built into the plugin
The plugin SHALL be one library that runs every supported protocol, each protocol selectable at build time and on by default. Its log at load and its diagnostics status SHALL name the protocols it was built with. A config with a network whose protocol is not built in SHALL be rejected as a configuration error naming the network and the protocol.

#### Scenario: Default build
- **WHEN** the plugin is built with default options and loads a config with a CANopen and a J1939 network
- **THEN** it logs that it supports canopen and j1939 and runs both networks

#### Scenario: J1939-only build
- **WHEN** the plugin is built without CANopen and loads a config with a CANopen network
- **THEN** the configuration is rejected with an error naming the network and saying CANopen is not built into this plugin, and no interface is opened

#### Scenario: Build without Lely
- **WHEN** the plugin is built without CANopen on a system without Lely or dcfgen installed
- **THEN** the build succeeds
