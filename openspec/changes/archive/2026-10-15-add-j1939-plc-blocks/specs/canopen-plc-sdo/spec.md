## MODIFIED Requirements

### Requirement: Finding the plugin
The blocks SHALL reach the plugin the runtime has already loaded, by its library name, without loading a second copy and whatever install prefix it was installed under, and SHALL call it only through one exported C entry point that takes the API version the library was built for and returns a table of functions, or nothing when the plugin does not offer that version. A block that finds no plugin, or no matching API version, SHALL end with `ERROR_ID` 4 and SHALL look again on its next rising edge. The table SHALL carry the block's `NETWORK` on every request, and each network SHALL run only the requests for its own number, so a network that stops or restarts cancels only its own transfers.

#### Scenario: Library newer than the plugin
- **WHEN** the library asks for an API version the installed plugin does not offer
- **THEN** every block ends with `ERROR_ID` 4, and the plugin logs once that the program's canworks library needs a newer plugin, naming both versions

#### Scenario: Plugin installed under another prefix
- **WHEN** the plugin was installed with `install-stock.sh --prefix /usr/local/canworks`
- **THEN** the blocks find it and transfers work

### Requirement: EMCY interface version
The plugin's C entry point SHALL offer version 2 of its table, which SHALL begin with the fields of version 1 and add the EMCY read functions, and SHALL keep offering version 1. The SDO blocks SHALL ask for version 1 and `CO_RECV_EMCY` for version 2, so that the SDO blocks of a library built with this change keep working with a plugin that offers only version 1, while `CO_RECV_EMCY` ends with `ERROR_ID` 4 there.

#### Scenario: New library, older plugin
- **WHEN** a program built with this library calls `CO_SDO_READ` and `CO_RECV_EMCY` on a runtime whose plugin offers only version 1
- **THEN** the read ends with `DONE`, `CO_RECV_EMCY` shows `ERROR_ID` 4, and the plugin logs once that the program's canworks library needs a newer plugin, naming both versions

## REMOVED Requirements

### Requirement: Library delivery
**Reason**: The library holds CANopen, CAN and J1939 blocks; its delivery is not an SDO matter.
**Migration**: The same requirement, with the J1939 message blocks added, is in the new capability `plc-library`.
