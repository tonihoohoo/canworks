## MODIFIED Requirements

### Requirement: Link code for any Modbus PLC
For a config with the PLC link (`bridge.plc_link`), `canworks-deploy --config FILE --export-modbus-map OUT.st` and the ST format of an Other PLC connection's Download SHALL write the PLC link for a Modbus PLC other than OpenPLC: a global variable list with `ok`, `link`, the channel variables `in_w` (input registers from 0 to the last used) and `out_w` (holding registers from 0 to the last used) and the typed values; the client channels to map onto `in_w` and `out_w`; and the programs `canworks_in` and `canworks_out`, the same conversion and `canworks.link` copy code that an OpenPLC project gets, reading `canworks.in_w` and writing `canworks.out_w` instead of `%IW`/`%QW` words, with `CW_LINK_SERVICE` called first in `canworks_in` and the PLC link header written last in `canworks_out`. The file header SHALL say to save the list as a global variable list named `canworks`, to map the channels, to add the library's ST sources, and that both programs must run every scan, first and last. A config without the PLC link SHALL keep the plain variable list.

#### Scenario: Export for another PLC
- **WHEN** a bridge config with the PLC link and mailboxes is exported to `map.st`
- **THEN** the file declares the channel variables, `canworks_in` and `canworks_out`, and these build together with the library's ST sources
