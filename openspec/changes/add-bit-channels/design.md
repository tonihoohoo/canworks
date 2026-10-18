## Context

A PDO entry binds one object to one IEC location (`canopen-pdo-io` "Explicit IEC location per PDO entry"), with an optional `name` that replaces the EDS part of its variable name. The OpenPLC runtime keeps one table per location size: `bool_input[index][bit]`, `byte_input[index]`, `int_input[index]` and so on, each a table of pointers to the program's located variables (`plugin/src/can/iec_location.h`, `image_io.h`). `%IX140.3` and `%IB140` are therefore two unrelated variables; writing the byte does not set the bit. The plugin writes inputs through the runtime's journal in `cycle_start` and reads outputs under the image lock in `cycle_end` (`process_image.h`).

Raw CAN and J1939 signals already cut bit fields out of frames to `%IX` locations. CANopen PDO entries have no such thing.

## Goals / Non-Goals

**Goals:** a bit of a byte or word entry reaches the program as its own named BOOL, both directions; names typed once in the configurator reach every place that names the entry; no cost for configs without bits.

**Non-Goals:** manual mode; bit fields wider than one bit (a 3-bit mode field stays a masked integer); bit channels on slave bindings, SDO variables, J1939 or raw signals; renaming objects in the EDS.

## Decisions

### Config shape: `bits` on the entry

```json
{ "index": "0x6000", "subindex": 1, "type": "UNSIGNED8",
  "bits": [ { "bit": 0, "name": "jog_x_plus",  "iec_location": "%IX140.0" },
            { "bit": 1, "name": "jog_x_minus", "iec_location": "%IX140.1" } ] }
```

The bits live inside the entry so the PDO layout stays one list of objects, as on the bus; a separate top-level list would need its own reference to node, PDO and entry. Bit 0 is the least significant bit of the entry's value as received (CiA 301 little-endian), the numbering the device notes and CiA 402 use.

Rules:
- Allowed on INTEGER8..64 and UNSIGNED8..64 entries; refused on BOOLEAN, REAL32 and REAL64.
- `bit` from 0 to the type's size minus 1, each at most once per entry.
- OpenPLC target: each bit needs `iec_location`, `%IX` on a TPDO entry and `%QX` on an RPDO entry, and takes part in the overlap check like any other location. CODESYS target: no location (CODESYS assigns addresses, as for entries). Modbus bridge target: no location; the bit is the entry's own byte bit (see below).
- The entry's `iec_location` is optional when it has bits. A TPDO entry may have both (the program sees the whole value and the bits). An RPDO entry with bits must not have its own location: two writers of one bit would fight. Unlisted bits of an RPDO entry are sent as 0.
- `name`: an identifier up to 64 characters, unique within the node together with the entry names (ignoring case), as entry names are today.

Alternatives considered: (a) a location type that addresses a bit inside a byte location (`%IB140.3`): not IEC 61131-3 and not something the OpenPLC editor can declare; (b) letting `%IX140.0..7` alias `%IB140`: the runtime's tables do not alias, and changing that means changing the runtime, which this project does not do.

### Plugin: bit bindings next to value bindings

`ProcessImage::build` adds, per bit channel, a small record (input or output binding index, bit number, location). Inputs: `copy_to_plc` already has the entry's raw value from the snapshot; it writes the value to the entry's location when it has one, then `(raw >> bit) & 1` to each bit location through `journal_write_bool`. Outputs: `copy_from_plc` builds the entry's value from its bit locations (`image_read_output` on `%QX`, NULL pointer reads 0) instead of reading a whole-value location. No new buffers: the snapshot slots stay one per entry. An entry with only bits is a binding with no whole-value location. Timeouts, node failure and "Inputs while a PDO is timed out" apply to the bits as they apply to the entry's value, because the bits are written from the same value.

Cost: one journal write per mapped bit per scan, the same as a BOOL entry today.

### Names and defaults

Declared name: `<node>_<name>` (network prefix with several networks). Without `name`: `<entry part>_bit<n>`, where the entry part is the entry's `name` or the EDS name the declaration uses today, for example `panel_Read_input_8_bit_1_bit3`. The tools never take a bit name from device notes at declaration time: a note edit must not silently rename a PLC variable the program uses. The configurator copies the note's bit name into `name` when the user maps the bit (turned into an identifier: `ready to switch on` becomes `ready_to_switch_on`), so the config holds the name and the user can change it.

### Configurator

In the PDOs tab, an integer entry's row gets **Bits…** (with a count when bits are mapped, "Bits 3/8"). It unfolds a table under the row: bit number, the note's bit name in grey, a tick, the name field (placeholder: the default name), the location with **Suggest**. **Map all bits** ticks all bits and places them on consecutive free `%IX`/`%QX` bytes, bit n at bit n mod 8 of the (n div 8)-th byte, which keeps the program readable; **Unmap all** clears them. On an RPDO entry, ticking the first bit asks before it clears the entry's whole-value location. Each change is one undo step. Problems name node, PDO, entry and bit. In the CODESYS target the location column is hidden, as for entries; in a bridge config it shows the computed coil or discrete input number read-only.

Online, the entry's value cell gets the mapped bits under it, each with name and a lit or dim dot.

### Exports and trace

- Declarations and new editor project: one `BOOL` per located bit, right after its entry (or where its entry would be), with a comment naming node, PDO, index:subindex, bit number and the note's bit text.
- Bus trace: under the entry's decoded value, one line per bit channel with its name and 0/1. In editor-project mode the declared variable name is used, as for entries.
- DBC: a one-bit signal per bit channel at the entry's start bit plus n, named by the bit channel's declared name; the entry's own signal stays (DBC signals may overlap).
- HTML documents: bit rows under the entry in the PDO details, and bit locations in the PLC I/O cross-reference.
- CODESYS: the plan lists bit channels per channel (`bits: [{bit, variable}]`). The script maps each to the channel's bit sub-channel in the I/O mapping. The CODESYS scripting API's support for bit sub-channels is checked first in apply (task 5.1); if it cannot address them, the plan still lists them, the script maps only the channel and its report names the bits to map by hand, and the spec delta is adjusted before archive.
- Modbus bridge: locations are byte addresses and a bit is already visible as discrete input or coil `n×8+b` of its byte, so a bit channel needs no location: the map adds a named discrete input or coil row at the entry's own byte and bit, and the Node-RED flow emits and accepts it by that name. A bit channel on an entry with no location is refused on the bridge (it would have no address).

## Risks / Trade-offs

- **CODESYS bit sub-channels** may not be reachable from the scripting API → fallback described above; proven on the real CODESYS install in the HW task, as for #148.
- **Output entry with partial bits** sends 0 on unmapped bits. A device bit that must stay 1 needs a mapped bit set by the program; documented, and the configurator's bit table shows "sent as 0" on unticked output bits.
- **Name collisions** between a bit name and an entry name in the same node are errors, like two entry names today.
- **Program edits after a rename**: renaming a bit changes its declaration; the editor project's existing "Never overwrite" rule still applies, so the user updates their program, the same as renaming an entry today.

## Migration Plan

None. Configs without `bits` behave and declare exactly as before. Plugin and PC tools are released together as usual; the bench Pi gets the new plugin before the hardware tasks.

## Open Questions

None blocking. Defaults chosen: bits inside the entry; output entries are bits or a whole value, not both; default name `<entry part>_bit<n>`; names copied from notes only when the bit is mapped in the configurator.
