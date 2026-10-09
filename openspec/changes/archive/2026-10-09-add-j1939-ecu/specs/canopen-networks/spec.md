## MODIFIED Requirements

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

## ADDED Requirements

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
