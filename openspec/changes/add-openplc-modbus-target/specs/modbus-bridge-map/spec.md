## ADDED Requirements

### Requirement: Map hash
The PC tools and the bridge SHALL compute the same 32-bit map hash of a bridge config: CRC-32 (IEEE 802.3) of a text with one line per located value, sorted by direction (`I` before `Q`) and first byte, each `<I|Q> <first byte> <byte count> <bit number or ->`, followed by the line `word_order low_first` or `word_order high_first`, lines ending in a newline. Names and types SHALL NOT be part of it (the program converts by the generated declarations, which Update declarations rewrites). For an `openplc` config the located values include the map hash block (input bytes 0-3), the status block (input bytes 4-11) and the PLC link header (output bytes 0-5). `canworks-deploy --export-modbus-map` SHALL print it, and the JSON and ST map formats SHALL carry it.

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
