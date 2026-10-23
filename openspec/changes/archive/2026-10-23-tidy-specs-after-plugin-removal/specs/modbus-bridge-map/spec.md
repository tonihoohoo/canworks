## MODIFIED Requirements

### Requirement: OpenPLC remote device file
For a bridge config with an OpenPLC connection the PC tools SHALL write the OpenPLC Editor remote device file `devices/remote/<remote_device>.json`: protocol `modbus-tcp`, host `127.0.0.1`, the bridge's port, slave id 1, timeout 1000 ms, and I/O groups, all with `poll_ms` as cycle time:
- read the header and status (input registers 0-5, plus live lists and the SDO response when configured) with `set-to-zero`;
- write the PLC link header (holding registers 0-2), then the control block and SDO request when configured;
- one read group (function 4) per input PDO, raw message or J1939 PGN register range and one write group (function 16) per output range, merged with the next contiguous range of the same node or message while within 125 read or 123 write registers, with `keep-last-value`.
Each point SHALL get one `%IW` or `%QW` from `iec_base` on in register order and the alias of the value it carries (`<value>_w<n>` for later words of a wider value). Coils and discrete inputs SHALL NOT be used. The tools SHALL report the number of requests per poll and warn above 40.

#### Scenario: Two PDOs of one node
- **WHEN** node `dio` has TPDO 1 at input bytes 12-15 and TPDO 2 at 16-17
- **THEN** the file has one function 4 group at offset 6 with length 3 and three `%IW` points

#### Scenario: Header first
- **WHEN** the file is written for any config with an OpenPLC connection
- **THEN** its first write group is function 16 at offset 0 with length 3

### Requirement: Mailbox blocks in the map
The register map, its export formats and Pack for Modbus SHALL include the blocks of `bridge.mailboxes`: Pack for Modbus SHALL place the mailbox input area after the bridge's status, live list and SDO response blocks and the mailbox output area after the control block and SDO request, word-aligned, and SHALL set `input_location` and `output_location`. Each mailbox block (request, response, receive mailbox, acknowledgement, network info, cyclic table, keepalives) SHALL be one located value of the map hash. The OpenPLC remote device groups and the suggested client channels SHALL never cut a request block, response block, receive mailbox or network info block over two requests; the reported number of requests per poll SHALL include them.

#### Scenario: Mailboxes change the hash
- **WHEN** `mailboxes.requests` of a config changes from 1 to 2
- **THEN** the map hash changes and a program built for the old map leaves outputs off

#### Scenario: Response block not cut
- **WHEN** the input registers of a config with an OpenPLC connection before the response block end at register 100
- **THEN** the response block starts a new read group instead of being split at register 125
