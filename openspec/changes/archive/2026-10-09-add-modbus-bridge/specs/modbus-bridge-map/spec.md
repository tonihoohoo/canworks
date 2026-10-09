## ADDED Requirements

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
