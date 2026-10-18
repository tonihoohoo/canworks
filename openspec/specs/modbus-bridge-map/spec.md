# modbus-bridge-map Specification

## Purpose
How a bridge config maps to Modbus registers, and the map exports and packing the PC tools offer for the client side.

## Requirements

### Requirement: Register map from the config
The PC tools SHALL compute a bridge config's Modbus register map with the bridge's rule (byte-addressed locations, input byte n in input register n/2, bits as discrete inputs and coils, `word_order`). The map SHALL list every location of the config, including diagnostics, timeout, status, J1939, raw and bridge block locations, with name, network, node or source, object or signal, direction, Modbus table, start address, number of registers or bits, data type, word order, and scale, offset and unit where the config has them.

#### Scenario: Same map as the bridge
- **WHEN** the map of the example bridge config says a TPDO entry is input registers 6 and 7
- **THEN** the bridge running that config serves that entry's value at input registers 6 and 7

### Requirement: Map export formats
`canworks-deploy --config FILE --export-modbus-map OUT` SHALL write the map as CSV (`.csv`), JSON (`.json`) or an ST variable list (`.st`), chosen by the file extension. The ST list SHALL declare one typed global variable per location with a comment giving its Modbus address, source and unit, and SHALL end with a comment table of suggested client channels (function, start, count, direction) that cover the used ranges in as few requests as the limits of 125 registers per read and 123 per write allow. A config that is not a bridge config SHALL be refused with a message saying so.

#### Scenario: Channel table
- **WHEN** a bridge config uses input bytes 0..299 and output bytes 0..39
- **THEN** the ST file suggests two read channels (registers 0-124 and 125-149) and one write channel (registers 0-19)

### Requirement: Pack for Modbus
The PC tools SHALL be able to reassign all locations of a bridge config densely:
- input data from byte 0 in network, node and PDO (or message) order, word-aligned
- then status and diagnostic locations
- then the bridge's status, live list and SDO bridge response blocks
- outputs the same way

Bit-sized entries SHALL share bytes. Packing SHALL keep every location's size and SHALL leave a config with no clash.

#### Scenario: Pack a mixed config
- **WHEN** a bridge config with 3 nodes, 2 J1939 messages and a status block is packed
- **THEN** its inputs occupy one contiguous byte range from 0 with no gap larger than one byte for alignment, and Check reports no problems

### Requirement: J1939 trouble code lists in bridge configs
A J1939 DM1 trouble code list (`dtcs_location` with `dtcs` above 1) in a Modbus bridge config SHALL place code k at 4 bytes per code from the start, as on a PLC runtime.

#### Scenario: Three codes
- **WHEN** a bridge config has `dtcs_location` `%ID560` with `dtcs` 3
- **THEN** the config is accepted and the three codes lie 4 bytes apart in the image, with no overlap error

### Requirement: Node-RED flow
The PC tools SHALL write a bridge config's register map as a Node-RED flow (JSON importable by Node-RED with the `node-red-contrib-modbus` palette) on one tab, containing: a Modbus TCP client node for the bridge; one input register read node per suggested read channel at the poll period; a link out "canworks in" emitting one message per changed value with `msg.topic` the row's name (the entry's `name` when it has one, else the map's generated name such as `dio.0x6000:1`) and `msg.payload` the decoded value (type, word order, sign, REAL, bit and scale/offset applied), every value once after start; a link in "canworks out" that sets the named output value and writes the changed write channels, after the output image has been read back from the bridge once; and a keepalive that rewrites the outputs at most every third of `watchdog_ms` when the watchdog is on. When the config locates the bridge's status block, control block, live list or SDO blocks, the flow SHALL also show the status as node status, emit the live list as per-node signals, and offer "canworks nmt", "canworks sdo" and "canworks sdo result" links using the bridge's counter handshake. Node ids SHALL be stable for the same config path and names, so a re-import replaces the tab's nodes.

#### Scenario: Named value both ways
- **WHEN** the flow of the example bridge config is imported and the simulated node's input `dio.0x6401:1` changes
- **THEN** "canworks in" emits a message with topic `dio.0x6401:1` and the new value, and a message `{topic: "dio.0x6411:1", payload: 5}` to "canworks out" makes holding register 1 hold 5

#### Scenario: Restart keeps outputs
- **WHEN** outputs hold non-zero values and Node-RED restarts
- **THEN** the first write after the restart carries the values read back from the bridge, not zeros

#### Scenario: Watchdog
- **WHEN** the bridge has `watchdog_ms` 1000 and the flow runs with no messages to "canworks out"
- **THEN** outputs stay on, and they go off by the watchdog within `watchdog_ms` after Node-RED stops

### Requirement: Bit channels on the bridge
In a bridge config a bit channel SHALL have no `iec_location`; its entry SHALL have one, and a bit channel of an entry without a location SHALL be refused. An RPDO entry with bits SHALL keep its own location in a bridge config. The register map SHALL add a row per bit channel, named `<node>.<name>`, or `<entry row>.bit<n>` without a `name`, with the discrete input (TPDO entry) or coil (RPDO entry) that holds that bit of the entry's value in the bridge's byte order (for an 8-bit entry at `%IBn`: n×8 + bit), and the Node-RED flow SHALL emit and accept it by that name as a boolean.

#### Scenario: Named discrete input
- **WHEN** a bridge config's node `dio` maps 0x6000:1 at `%IB16` with bit 3 named `jog_x_plus`
- **THEN** the map has a row `dio.jog_x_plus`, discrete input 131, and the flow's "canworks in" emits topic `dio.jog_x_plus` with `true` when that bit is set
