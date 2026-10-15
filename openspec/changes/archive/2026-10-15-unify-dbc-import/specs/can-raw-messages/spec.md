## MODIFIED Requirements

### Requirement: Raw messages on every network
Every version 2 network, whatever its `protocol`, MAY have a `raw` object with `rx` and `tx` lists of messages and an optional `dbc` file name. `dbc` SHALL name a file relative to the config (the configurator keeps it in the config folder); the plugin SHALL NOT read it. The raw messages SHALL run next to the network's protocol on the same interface without changing what the protocol sends or receives. Raw messages SHALL be available in every build of the plugin, whichever protocols it was built with.

#### Scenario: Display next to CANopen nodes
- **WHEN** a CANopen network on `can0` with nodes 2 and 5 also has a raw `tx` message 0x510 every 100 ms
- **THEN** both nodes boot and exchange PDOs as before, and 0x510 appears on the bus every 100 ms with the values of its `%Q` locations

#### Scenario: Raw messages in a J1939-only build
- **WHEN** the plugin is built without CANopen and loads a network with protocol `none` and raw messages
- **THEN** the network runs and its raw messages work

#### Scenario: DBC file missing on the PLC
- **WHEN** a network's `raw.dbc` names a file that is not next to the config on the PLC
- **THEN** the plugin starts the network and its raw messages as usual
