## MODIFIED Requirements

### Requirement: Protocols built into the plugin
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

## REMOVED Requirements

### Requirement: Same scan for all networks
**Reason**: There is no PLC scan inside canworks any more; every network writes into and reads from the bridge's one byte image.
**Migration**: None.
