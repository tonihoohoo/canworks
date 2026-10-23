## ADDED Requirements

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
