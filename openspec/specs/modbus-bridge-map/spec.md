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

### Requirement: Map hash
The PC tools and the bridge SHALL compute the same 32-bit map hash of a bridge config: CRC-32 (IEEE 802.3) of a text with one line per located value, sorted by direction (`I` before `Q`) and first byte, each `<I|Q> <first byte> <byte count> <bit number or ->`, followed by the line `word_order low_first` or `word_order high_first`, lines ending in a newline. Names and types SHALL NOT be part of it (the program converts by the generated declarations, which Save rewrites). For an `openplc` config the located values include the map hash block (input bytes 0-3), the status block (input bytes 4-11) and the PLC link header (output bytes 0-5). `canworks-deploy --export-modbus-map` SHALL print it, and the JSON and ST map formats SHALL carry it.

#### Scenario: Rename keeps the hash
- **WHEN** an entry's `name` changes and nothing else
- **THEN** the map hash is unchanged

#### Scenario: Moved entry
- **WHEN** an entry's location moves from `%IW12` to `%IW14`
- **THEN** the map hash changes

#### Scenario: Same hash on both sides
- **WHEN** each shipped example bridge config is hashed by the PC tools and by `canworks-bridge --check-only`
- **THEN** both print the same value

### Requirement: OpenPLC remote device file
For an `openplc` bridge config the PC tools SHALL write the OpenPLC Editor remote device file `devices/remote/<remote_device>.json`: protocol `modbus-tcp`, host `127.0.0.1`, the bridge's port, slave id 1, timeout 1000 ms, and I/O groups, all with `poll_ms` as cycle time:
- read the header and status (input registers 0-5, plus live lists and the SDO response when configured) with `set-to-zero`;
- write the PLC link header (holding registers 0-2), then the control block and SDO request when configured;
- one read group (function 4) per input PDO, raw message or J1939 PGN register range and one write group (function 16) per output range, merged with the next contiguous range of the same node or message while within 125 read or 123 write registers, with `keep-last-value`.
Each point SHALL get one `%IW` or `%QW` from `iec_base` on in register order and the alias of the value it carries (`<value>_w<n>` for later words of a wider value). Coils and discrete inputs SHALL NOT be used. The tools SHALL report the number of requests per poll and warn above 40.

#### Scenario: Two PDOs of one node
- **WHEN** node `dio` has TPDO 1 at input bytes 12-15 and TPDO 2 at 16-17
- **THEN** the file has one function 4 group at offset 6 with length 3 and three `%IW` points

#### Scenario: Header first
- **WHEN** the file is written for any `openplc` config
- **THEN** its first write group is function 16 at offset 0 with length 3

### Requirement: Mailbox blocks in the map
The register map, its export formats and Pack for Modbus SHALL include the blocks of `bridge.mailboxes`: Pack for Modbus SHALL place the mailbox input area after the bridge's status, live list and SDO response blocks and the mailbox output area after the control block and SDO request, word-aligned, and SHALL set `input_location` and `output_location`. Each mailbox block (request, response, receive mailbox, acknowledgement, network info, cyclic table, keepalives) SHALL be one located value of the map hash. The OpenPLC remote device groups and the suggested client channels SHALL never cut a request block, response block, receive mailbox or network info block over two requests; the reported number of requests per poll SHALL include them.

#### Scenario: Mailboxes change the hash
- **WHEN** `mailboxes.requests` of a config changes from 1 to 2
- **THEN** the map hash changes and a program built for the old map leaves outputs off

#### Scenario: Response block not cut
- **WHEN** an `openplc` config's input registers before the response block end at register 100
- **THEN** the response block starts a new read group instead of being split at register 125

### Requirement: Link code for any Modbus PLC
For a config with the PLC link (`bridge.openplc`), `canworks-deploy --config FILE --export-modbus-map OUT.st` and the configurator's **Export ST variables** SHALL write the PLC link for a Modbus PLC other than OpenPLC: a global variable list with `ok`, `link`, the channel variables `in_w` (input registers from 0 to the last used) and `out_w` (holding registers from 0 to the last used) and the typed values; the client channels to map onto `in_w` and `out_w`; and the programs `canworks_in` and `canworks_out`, the same conversion and `canworks.link` copy code that an OpenPLC project gets, reading `canworks.in_w` and writing `canworks.out_w` instead of `%IW`/`%QW` words, with `CW_LINK_SERVICE` called first in `canworks_in` and the PLC link header written last in `canworks_out`. The file header SHALL say to save the list as a global variable list named `canworks`, to map the channels, to add the library's ST sources, and that both programs must run every scan, first and last. A config without the PLC link SHALL keep the plain variable list.

#### Scenario: Export for another PLC
- **WHEN** a bridge config with the PLC link and mailboxes is exported to `map.st`
- **THEN** the file declares the channel variables, `canworks_in` and `canworks_out`, and these build together with the library's ST sources
