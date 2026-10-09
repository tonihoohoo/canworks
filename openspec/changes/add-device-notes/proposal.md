## Why

An EDS gives each object a name, a type, an access, a default and at best a LowLimit/HighLimit. It has no place for what the object does, its unit or scaling, what each value means or what each bit of a vendor bit field means. That is exactly what a user needs when choosing a startup SDO, reading a value in the object dictionary view or reading the network document, and today they have to keep the device manual open next to the configurator. The few meanings the configurator does show (bits of 0x1001, 0x1002, 0x6040, 0x6041 and the 0x6060 modes) are hard-coded in `app.js`.

XDD/XDC (CiA 311) can carry descriptions, units and value meanings, but classic CANopen devices rarely ship an XDD, many vendor XDDs are machine conversions of the EDS with those parts empty, Lely's tools read only EDS/DCF, and writing an XDD by hand is heavy XML. A small notes file next to each EDS, filled in from the configurator while commissioning, plus notes canworks ships for the CiA-defined objects, gives the same result for every device (exploration notes `research/xdd-device-docs-2026-10-09.md` in the project files).

## What Changes

- **Device notes file**: every EDS in a project's `canworks/` folder gets a notes file `<eds file name>.notes.json` (format `canworks-notes.v1`, JSON Schema in `schema/`). Per object or sub-object it holds a short text, an optional longer text, unit, scale, value meanings, bit names and a manual reference. The configurator creates it when the EDS is saved, with the device identity and an empty entry for every manufacturer object (0x2000-0x5FFF) ready to fill in. The file never goes to the PLC.
- **Built-in CiA notes**: canworks ships notes in the same format, written in its own words, for the CiA 301 communication objects and for the CiA 401 and CiA 402 profile objects. The profile notes apply to a node whose EDS declares that profile in 0x1000. They replace the hard-coded bit and mode tables in `app.js`.
- **One merged view**: everywhere a note is shown, the device notes file wins over the built-in note, and the EDS name and limits come last. Editing the note of a CiA object writes only an override into the device file, starting from the built-in text.
- **Where notes show and are edited**: the object dictionary view (text under the entry, unit and scaled value, `3 (profile velocity)` instead of `3`, a value list on edit, bit names in the bit view, a Note editor), the startup SDO editor and picker, the PDO entry picker, and the Parameters compare and restore lists. Notes are read-only in "Commission a device" without a config.
- **Exports**: the network document shows the note and value meaning for each boot write and mapped object; the DBC export adds value tables (`VAL_`), the unit and the note text for PDO signals that have them.
- **Checks**: a notes file that does not match the schema, or names objects its EDS does not have, is a warning in the Problems pane; it never blocks saving the config and the configurator never overwrites a notes file it could not read.

## Capabilities

### New Capabilities
- `canopen-device-notes`: the notes file format, the built-in CiA notes, creation and merge rules, and checks.

### Modified Capabilities
- `canopen-configurator`: Import an EDS (notes file created on save), Save only the project's canopen folder (notes files are saved too), Value formats in the object dictionary view (bit names and value meanings from notes), Editing values in the object dictionary view (value list, unit and scale, note editor), Startup SDO writes (note and value list in the editor).
- `canopen-network-docs`: Boot configuration and PDO details show notes and value meanings.
- `canopen-dbc-export`: Signal types and ranges (unit from notes), Comments and timing (note text and value tables).

## Impact

- `tools/deploy/canworks/`: new `notes.py` (load, merge, validate, skeleton), `notes/` with `cia301.json`, `cia401.json`, `cia402.json`, schema `canworks-notes.v1.schema.json` (also under top-level `schema/`); `configurator/server.py` (notes in the EDS summary and the OD entries, save, problems); `configurator/static/app.js` (note display and editor, `OD_BITS`/`OD_MODES` removed); `docexport.py`; `dbcexport.py`.
- No plugin, runtime, `canworks.json` schema or deploy bundle change; the deploy tool ignores notes files.
- Tests: notes module unit tests, configurator API and page tests, docs and DBC export tests. CI runs them in the existing PC tools job; no new job.
- Docs: `docs/configurator.md` (new "Device notes" section with the file format), `docs/network-docs.md`, README (configurator bullet). Deploy tool minor version bump.
- Non-goals: XDD/XDC import (can later become a converter into notes), XDD/XDC export, notes in more than one language, a per-user notes library shared across projects, notes in the trace and frame explanations.
