## Why

Buttons, lamps, limit switches and status words often travel as one byte or word: a CiA 401 module sends eight inputs as `0x6000:1` (UNSIGNED8), a drive sends its statusword as `0x6041` (UNSIGNED16). Today such an entry reaches the program as one `USINT` or `UINT`, and the program masks bits out by hand (`IF (dio_in AND 16#08) <> 0 THEN`), as the gantry example does. A PDO entry can already be renamed (`name`), but a single bit cannot: there is no `panel_jog_x_plus : BOOL` to write in the program, and the bus trace, the DBC and the documents cannot name what a bit means.

The coming manual mode for the gantry cell needs exactly this: an ordinary I/O module as an operator panel, with each button and lamp named in the configurator and reaching the program as its own BOOL. CODESYS has the same idea: each bit of a BYTE channel can be mapped to its own variable.

## What Changes

- **Bit channels on a PDO entry.** An integer PDO entry (8 to 64 bits, signed or unsigned) may list `bits`: each a bit number, an optional `name` and, on the OpenPLC target, its own `%IX` (TPDO entries) or `%QX` (RPDO entries) location. The entry's own `iec_location` becomes optional when it has bits. An input entry may keep its whole-value location next to its bits; an output entry has either a whole-value location or bits, never both (one writer per bit). Bits of an output entry that are not listed are sent as 0.
- **Plugin.** OpenPLC keeps `%IX` bits and `%IB`/`%IW` values in separate tables (`bool_input[byte][bit]` versus `byte_input[]`; see `plugin/src/can/iec_location.h`), so a bit location is not a view of a byte location. The plugin copies each input bit to its `%IX` location in the same scan step as the entry's value, and builds each output entry's value from its `%QX` bits in `cycle_end`. Same checks as other locations: type, direction, overlap, inside the image, bit number below the entry's size, each bit once.
- **Names.** A bit channel is declared as `<node>_<name>` (with the network prefix when there are several networks). Without a `name` it is `<entry part>_bit<n>`, the entry part being the entry's own `name` or its EDS name. Names are unique within the node together with entry names. The plugin never reads names.
- **Configurator.** An integer entry in the PDOs tab gets **Bits…**, which unfolds a table of the entry's bits: a tick to map the bit, its name and its location with **Suggest**. **Map all bits** ticks every bit and places them on free `%IX`/`%QX` bytes (bit n of a byte entry at `.n`). New bit names start from the device note's bit names (built-in CiA 402 statusword and controlword bits, or the user's notes), so a bit named once on the Notes tab arrives in the program by that name; after that the name lives in the config and renaming a note never renames a variable. The online PDO values show each mapped bit's state with its name.
- **Everywhere the entry name goes, bit names go too:** the editor project and located declarations (one `BOOL` per bit), the bus trace's PDO decode (one line per named bit under the entry's value), the DBC export (a one-bit signal per bit channel, beside the entry's own signal), the HTML documents (bit rows under the entry, and in the PLC I/O cross-reference), the CODESYS export (bit channels named in the plan and on the channel's bit sub-channels), and the Modbus bridge map and its Node-RED flow (a named discrete input or coil row at the entry's own byte, since bridge locations are byte addresses and bit channels need no location there).
- README, `docs/config.md`, `docs/configurator.md`, `docs/trace.md`, `docs/codesys.md`, `docs/modbus-bridge.md` and the tour describe bit channels.

Not in this change: manual mode itself (it builds on this in its own change), bit channels on slave bindings, SDO variables and J1939 or raw CAN signals (those already have bit-sized signals), and renaming from the bus trace.

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `canopen-pdo-io`: bit channels of a PDO entry and their exchange each scan.
- `canopen-configurator`: bit channel editing in the PDOs tab, names from device notes, online bit values.
- `canopen-editor-project`: one BOOL declaration per bit channel.
- `canopen-bus-trace`: bit channel names in PDO decoding.
- `canopen-dbc-export`: one-bit signals for bit channels.
- `canopen-network-docs`: bit channels in the PDO details and the PLC I/O cross-reference.
- `codesys-export`: bit channels in the plan and on CODESYS bit sub-channels.
- `modbus-bridge-map`: named bit rows for bit channels in the map and the Node-RED flow.

## Impact

- Plugin: `plugin/src/can/config.*` (parse and check `bits`), `plugin/src/canopen/process_image.*` (bit bindings in `copy_to_plc` / `copy_from_plc`), the shared config contract in `tools/deploy/canworks/contract.py` and `schema/`.
- PC tools: `configurator/declare.py`, the configurator's PDO table (`static/app.js`), `bustrace/decode.py`, `dbcexport.py`, `docexport.py`, `codesys/plan.py` and `codesys/script/import_canworks.py`, `modbusmap.py`, `nodered.py`.
- Tests: plugin unit tests for parse, checks and the bit copy; a scan test on vcan in an existing CTest job; PC tool unit tests; one browser test in the existing browser job. No new CI job, path filters unchanged.
- Versions: plugin and PC tools minor bumps. Not in real use, so no migration: configs without `bits` are unchanged.
