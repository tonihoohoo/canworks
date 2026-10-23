## RENAMED Requirements

- FROM: `### Requirement: Protocols built into the plugin`
- TO: `### Requirement: Protocols built into the bridge`

## MODIFIED Requirements

### Requirement: Protocols built into the bridge
The bridge SHALL be one program that runs every supported protocol, each protocol selectable at build time and on by default. Its log at start and its diagnostics status SHALL name the protocols it was built with. A config with a network whose protocol is not built in SHALL be rejected as a configuration error naming the network and the protocol.

#### Scenario: Default build
- **WHEN** the bridge is built with default options and loads a config with a CANopen and a J1939 network
- **THEN** it logs that it supports canopen and j1939 and runs both networks

#### Scenario: J1939-only build
- **WHEN** the bridge is built without CANopen and loads a config with a CANopen network
- **THEN** the configuration is rejected with an error naming the network and saying CANopen is not built into this bridge, and no interface is opened

#### Scenario: Build without Lely
- **WHEN** the bridge is built without CANopen on a system without Lely or dcfgen installed
- **THEN** the build succeeds

### Requirement: Network list
A version 2 config SHALL hold a `networks` list of 1 to 8 entries. Each CANopen entry SHALL have an `adapter`, a `master` and a `nodes` list with the same fields and meaning as the version 1 top level, and MAY have a `name`. A J1939 entry (`"protocol": "j1939"`) SHALL have an `adapter` and a `j1939` object as `j1939-config` defines. A plain CAN entry (`"protocol": "none"`) SHALL have an `adapter` and MAY have a `raw` object as `can-raw-messages` defines. Any entry MAY have a `raw` object. A version 1 config SHALL be read as one CANopen network with no name.

#### Scenario: Two networks
- **WHEN** a version 2 config has networks on `can0` (nodes 2 and 3) and `can1` (nodes 2 and 10)
- **THEN** the bridge loads it and logs one line per network naming its interface, bit rate, master node ID and number of slaves

#### Scenario: Version 1 file
- **WHEN** the bridge loads `config/pingpong/canopen_config.json` (version 1)
- **THEN** it runs one network exactly as before this change, with the same log lines and the same generated files

#### Scenario: Too many networks
- **WHEN** a version 2 config has 9 networks
- **THEN** the configuration is rejected, saying at most 8 networks are supported

#### Scenario: CANopen and J1939 networks
- **WHEN** a version 2 config has a CANopen network on `can0` and a J1939 network on `can1`
- **THEN** the bridge loads it and logs one line for the CANopen network as above and one for the J1939 network naming its interface, bit rate, address and numbers of received and sent PGNs

#### Scenario: CANopen and plain CAN networks
- **WHEN** a version 2 config has a CANopen network on `can0` with two raw messages and a plain CAN network on `can1`
- **THEN** the bridge loads it, the CANopen line also gives the number of raw messages, and the plain network's line names its interface, bit rate and numbers of received and sent raw messages

### Requirement: A config error stops every network
Any configuration, EDS or dcfgen error in any network SHALL leave the whole bridge inactive with no CAN interface opened, as for a single network, and the log SHALL name the network of each problem.

#### Scenario: One network has a bad EDS
- **WHEN** network `drives` names an EDS that does not exist and network `io` is valid
- **THEN** the bridge logs the error with `drives` in it, opens neither interface, and the PLC runs normally

## REMOVED Requirements

### Requirement: Same scan for all networks
**Reason**: There is no PLC scan inside canworks any more; every network writes into and reads from the bridge's one byte image.
**Migration**: None.
