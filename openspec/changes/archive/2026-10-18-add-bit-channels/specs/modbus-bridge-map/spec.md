## ADDED Requirements

### Requirement: Bit channels on the bridge
In a bridge config a bit channel SHALL have no `iec_location`; its entry SHALL have one, and a bit channel of an entry without a location SHALL be refused. An RPDO entry with bits SHALL keep its own location in a bridge config. The register map SHALL add a row per bit channel, named `<node>.<name>`, or `<entry row>.bit<n>` without a `name`, with the discrete input (TPDO entry) or coil (RPDO entry) that holds that bit of the entry's value in the bridge's byte order (for an 8-bit entry at `%IBn`: n×8 + bit), and the Node-RED flow SHALL emit and accept it by that name as a boolean.

#### Scenario: Named discrete input
- **WHEN** a bridge config's node `dio` maps 0x6000:1 at `%IB16` with bit 3 named `jog_x_plus`
- **THEN** the map has a row `dio.jog_x_plus`, discrete input 131, and the flow's "canworks in" emits topic `dio.jog_x_plus` with `true` when that bit is set
