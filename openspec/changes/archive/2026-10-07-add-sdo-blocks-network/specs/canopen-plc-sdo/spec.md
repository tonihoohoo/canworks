## MODIFIED Requirements

### Requirement: SDO function blocks
The editor library `openplc_canopen` SHALL provide the function blocks `CO_SDO_READ`, `CO_SDO_WRITE`, `CO_SDO_READ_REAL`, `CO_SDO_WRITE_REAL`, `CO_SDO_READ_STRING`, `CO_SDO_WRITE_STRING`, `CO_SDO_READ_BYTES` and `CO_SDO_WRITE_BYTES`. Every block SHALL have the inputs `EXECUTE : BOOL`, `NETWORK : USINT`, `NODE : USINT`, `INDEX : UINT`, `SUBINDEX : USINT` and `TIMEOUT : TIME` (`T#0s` meaning 1 s), and the outputs `BUSY : BOOL`, `DONE : BOOL`, `ERROR : BOOL`, `ERROR_ID : UINT` and `ABORT_CODE : UDINT`. The data pins SHALL be:
- `CO_SDO_READ`: out `DATA : LWORD`, `SIZE : UINT`; `CO_SDO_WRITE`: in `DATA : LWORD`, `SIZE : USINT`.
- `CO_SDO_READ_REAL`: out `VALUE : LREAL`; `CO_SDO_WRITE_REAL`: in `VALUE : LREAL`, `SIZE : USINT`.
- `CO_SDO_READ_STRING`: out `VALUE : STRING`; `CO_SDO_WRITE_STRING`: in `VALUE : STRING`.
- `CO_SDO_READ_BYTES` and `CO_SDO_WRITE_BYTES`: in-out `BUFFER : ARRAY[0..1023] OF BYTE`, and `SIZE : UINT` (out for the read, in for the write).
`NODE` SHALL accept any node ID 1 to 127, whether the configuration lists the node or not. `NETWORK` SHALL pick the network by its place in the configuration's `networks` list, 0 being the first; with a version 1 configuration the only network is 0. A `NETWORK` the running configuration does not have SHALL end the block with `ERROR_ID` 6.

#### Scenario: Read a configured node's object
- **WHEN** the program calls `rd(EXECUTE := TRUE, NODE := 5, INDEX := 16#1018, SUBINDEX := 1)` with `rd : CO_SDO_READ` and node 5's vendor ID is 16#000000AB
- **THEN** within a few scans `rd.DONE` is TRUE, `rd.DATA` is 16#AB and `rd.SIZE` is 4

#### Scenario: Read a node that is not configured
- **WHEN** the program reads 0x1000 subindex 0 of node 40, which the configuration does not list but which is on the bus
- **THEN** the block finishes with `DONE` and the device type

#### Scenario: Node ID out of range
- **WHEN** `NODE` is 0 or 128 at the rising edge of `EXECUTE`
- **THEN** the block finishes with `ERROR`, `ERROR_ID` 6 and sends nothing

#### Scenario: Read on the second network
- **WHEN** the configuration has the networks `io` and `drives`, both with a node 2, and the program reads 0x1017 subindex 0 with `NETWORK := 1, NODE := 2`
- **THEN** the read goes out on `drives` only and the block finishes with `DONE` and drives' node 2's heartbeat period

#### Scenario: Network that does not exist
- **WHEN** the configuration has two networks and `NETWORK` is 2 at the rising edge of `EXECUTE`
- **THEN** the block finishes with `ERROR`, `ERROR_ID` 6 and sends nothing

#### Scenario: One network lost, the other still answers
- **WHEN** drives' node 2 is lost and the program reads from node 2 on both networks
- **THEN** the read on `io` finishes with `DONE` and the read on `drives` with `ERROR_ID` 3

### Requirement: Finding the plugin
The blocks SHALL reach the plugin the runtime has already loaded, by its library name, without loading a second copy and whatever install prefix it was installed under, and SHALL call it only through one exported C entry point that takes the API version the library was built for and returns a table of functions, or nothing when the plugin does not offer that version. A block that finds no plugin, or no matching API version, SHALL end with `ERROR_ID` 4 and SHALL look again on its next rising edge. The table SHALL carry the block's `NETWORK` on every request, and each network SHALL run only the requests for its own number, so a network that stops or restarts cancels only its own transfers.

#### Scenario: Library newer than the plugin
- **WHEN** the library asks for an API version the installed plugin does not offer
- **THEN** every block ends with `ERROR_ID` 4, and the plugin logs once that the program's CANopen library needs a newer plugin, naming both versions

#### Scenario: Plugin installed under another prefix
- **WHEN** the plugin was installed with `install-stock.sh --prefix /usr/local/openplc-canopen`
- **THEN** the blocks find it and transfers work
