## MODIFIED Requirements

### Requirement: OpenPLC remote device file
For a bridge config with an OpenPLC connection the PC tools SHALL write the OpenPLC Editor remote device file `devices/remote/<remote_device>.json`: protocol `modbus-tcp`, host `127.0.0.1`, the bridge's port, slave id 1, timeout 1000 ms, and I/O groups, all with `poll_ms` as cycle time except the mailbox groups:
- read the header and status (input registers 0-5, plus live lists and the SDO response when configured) with `set-to-zero`;
- write the PLC link header (holding registers 0-2), then the control block and SDO request when configured;
- one read group (function 4) per input PDO, raw message or J1939 PGN register range and one write group (function 16) per output range, merged with the next contiguous range of the same node or message while within 125 read or 123 write registers, with `keep-last-value`;
- with `bridge.mailboxes`, the mailbox blocks in groups of their own (never shared with another block or value), with the connection's mailbox poll as cycle time and `set-to-zero` for reads.

Each point SHALL get one `%IW` or `%QW` from `iec_base` on in register order and the alias of the value it carries (`<value>_w<n>` for later words of a wider value). Coils and discrete inputs SHALL NOT be used. The tools SHALL report the number of requests every `poll_ms` and, with mailboxes, the number of mailbox requests every mailbox poll, and SHALL warn when the requests per poll, mailbox requests counted as `poll_ms` / mailbox poll each, are above 40.

#### Scenario: Two PDOs of one node
- **WHEN** node `dio` has TPDO 1 at input bytes 12-15 and TPDO 2 at 16-17
- **THEN** the file has one function 4 group at offset 6 with length 3 and three `%IW` points

#### Scenario: Header first
- **WHEN** the file is written for any config with an OpenPLC connection
- **THEN** its first write group is function 16 at offset 0 with length 3

#### Scenario: Mailbox groups on their own
- **WHEN** the file is written for `examples/openplc-modbus` with the default mailboxes, `poll_ms` 10 and no `mailbox_poll_ms`
- **THEN** every group that holds a mailbox block holds nothing else and has cycle time 50, and every other group has cycle time 10
