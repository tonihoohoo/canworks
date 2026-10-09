## ADDED Requirements

### Requirement: Decoding with gateway-routed entries
The decoding of a network's frames SHALL use the configured PDOs and EDS files of every node whenever the config passes the configurator's check, including PDO entries without a PLC location because a gateway route feeds them. A note about decoding without the config's PDOs SHALL appear only when the config itself has a problem, and SHALL name it in the user's terms, without file paths.

#### Scenario: Virtual-plant io
- **WHEN** a trace of the virtual-plant example's network io is shown
- **THEN** node 5's TPDO 1 is decoded with its mapped objects, the Graph offers its PDO signals, and no decoding note is shown

### Requirement: Identifier filters in hex
The trace's identifier filters SHALL read identifiers in hex, as the trace shows them, with or without `0x`, and the cyclic send jobs SHALL show their identifiers in hex.

#### Scenario: Hex range
- **WHEN** the user filters identifiers from 180 to 1FF
- **THEN** the trace shows the frames with identifiers 0x180 to 0x1FF

### Requirement: Views follow the picked network
On a network switch the trace graph, the Frame lab result, the Simulation view's picked node and the Send panel SHALL drop what belonged to the previous network. A J1939 network SHALL show only J1939 kinds, sequences, trigger conditions and frame examples, and a CANopen network only CANopen ones.

#### Scenario: Simulation node after a switch
- **WHEN** node 5 is picked in the Simulation view on network io and the user switches to motion
- **THEN** the view shows motion's node 4 or no node, never node 5
