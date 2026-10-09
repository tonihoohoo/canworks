# Design

## Context

- `eds.py` reads ParameterName, DataType, AccessType, PDOMapping, DefaultValue, ParameterValue, LowLimit and HighLimit; `parameters.Entry.to_json` and `server.eds_summary` pass the limits to the page. Nothing else about an object reaches the user.
- `app.js` has `OD_BITS` (0x1001, 0x1002, 0x6040, 0x6041) and `OD_MODES` (0x6060/0x6061) as the only value meanings; the bit view requirement says those names come from a table in the configurator.
- The configurator stores EDS files under the project's `canworks/` folder and saves only `canworks.json` and EDS files there. The deploy bundle copies only the EDS files the config names, so other files in `canworks/` never reach the PLC. The editor snapshot carries the whole `canworks/` folder.
- Lely's dcf-tools and the plugin read EDS/DCF only. A note is documentation; it never changes what is written to a device.
- The project is not in real use: no migration of earlier projects is needed (they simply get a notes file on their next save).

## Goals / Non-Goals

**Goals:**
- A short description, unit, scaling, value meanings and bit names for any object, for any device that has an EDS.
- CiA-defined objects documented without user work.
- Notes written where the user meets the object (object dictionary view, startup SDO editor), saved with the project, readable and diffable by hand.
- The same notes in the network document and the DBC file.

**Non-Goals:**
- XDD/XDC import or export, more than one language, a notes library shared across projects, notes in the trace and frame explanations, notes for slave-device EDS files the configurator builds.

## Decisions

### D1. One notes file per EDS, next to it
`canworks/<eds file name>.notes.json`, e.g. `canworks/valve.eds.notes.json`. The full EDS name (with extension) keeps `x.eds` and `x.dcf` apart and makes the pairing obvious in a file list. "Keep both" on an EDS name clash gives the new EDS its own notes file. Alternative: one `notes.json` for the project keyed by EDS; rejected because two nodes with the same EDS share notes anyway, and per-EDS files can be copied with the EDS into another project.

### D2. Format `canworks-notes.v1`

```json
{
  "format": "canworks-notes.v1",
  "eds": {"file": "valve.eds", "vendor_id": "0x000000AB", "product_code": "0x00001234", "revision": "0x00010002"},
  "objects": {
    "0x2010":   {"name": "Ramp time", "text": "Opening ramp of the valve", "unit": "ms"},
    "0x2011:2": {"name": "Fault reaction", "text": "What the valve does on a bus fault",
                 "values": {"0": "hold position", "1": "close", "2": "open"}},
    "0x2100":   {"name": "Fault bits", "bits": {"0": "coil A open", "1": "coil B open", "7": "overtemperature"}},
    "0x2200:1": {"name": "Pressure", "unit": "bar", "scale": 0.01, "manual": "section 7.3"}
  }
}
```

- Keys: `0x<index>` for a VAR object or a whole ARRAY/RECORD, `0x<index>:<sub>` for a sub-object, the same `0x7130:1` form the DBC comments use. Hex digits upper case, four digits.
- Fields, all optional: `name` (informational copy of the EDS name, ignored on read, refreshed on save), `text` (one line, at most 200 characters), `details` (longer text), `unit`, `scale` (number; shown value = raw × scale), `values` (decimal raw value → meaning), `bits` (bit number 0-63 → meaning; an empty `{}` marks a bit field without names, like 0x1002), `manual` (free text such as a page or section).
- A sub-object without its own entry inherits `text`, `unit`, `scale` and `manual` from its object's entry (an array of 8 identical channels needs one note), but not `values` or `bits`.
- `format` is checked like `schema_version` in `canworks.json`; a later format is a clean cut.

### D3. Built-in notes, layered, not copied
`tools/deploy/canworks/notes/cia301.json`, `cia401.json`, `cia402.json` in the same format (no `eds` block). CiA 301 applies to every node; a profile file applies when the low 16 bits of the EDS's 0x1000 default are 401 or 402. The device file holds only what the user wrote; a CiA object's note is the field-by-field merge of device entry over built-in entry. Copying the built-in text into each project file was rejected: it goes stale when canworks improves its notes and makes every file large. "Export merged notes" in the node's menu writes the merged view to a file for reading outside canworks.

The built-in texts are canworks' own short wording, not text copied from CiA specifications. Coverage at least: CiA 301 0x1000-0x1029 and the PDO, SDO and NMT communication objects (0x1200-0x1BFF, 0x1F80-0x1F89) with value meanings for transmission types (0x1400/0x1800 sub 2), COB-ID valid/RTR/frame bits, 0x1001 bits; CiA 402 0x603F, 0x6040, 0x6041 (bits), 0x605A-0x605E, 0x6060/0x6061 (modes), 0x6064, 0x606C, 0x6071, 0x6077, 0x607A, 0x607C, 0x607D, 0x6081, 0x6083, 0x6084, 0x6098 (homing methods), 0x60B8-0x60BA, 0x60FF; CiA 401 0x6000, 0x6002, 0x6200, 0x6202, 0x6206, 0x6207, 0x6401, 0x6411, 0x6421-0x6426.

### D4. Skeleton on save
When the configurator saves a project whose EDS has no notes file, it writes one with the `eds` identity from `[DeviceInfo]` and an empty entry (`{"name": "<EDS name>"}`) for every manufacturer object and sub-object (0x2000-0x5FFF). Communication and profile objects get no skeleton entries, because the built-in notes cover them; the user adds an override from the Note editor. An existing notes file is never replaced: on save only entries the user changed are written and `name` fields are refreshed, keeping other keys and their order.

### D5. Where notes appear
- Object dictionary view: `text` as a muted line under the name (full `details` and `manual` on hover or in the Note editor), unit after the value; with `scale` the value shows as `1234 (12.34 bar)`; with `values` as `3 (profile velocity)`; with `bits` the bit view uses them for any object, not only the four built-in ones. Edit offers a list of `values` plus "Other value…". A "Note" button opens the editor (text, details, unit, scale, values table, bits table, manual); saving the note marks the config dirty and is written with Save.
- Startup SDO editor and picker, PDO entry picker, Parameters compare and restore lists: `text` under the name and the value meaning next to the value.
- "Commission a device" without a config: notes shown read-only (built-in, plus a notes file next to a picked EDS if there is one); no Note editor.

### D6. Exports
`docexport` adds a "Note" column and value meanings to the boot configuration list and the PDO table. `dbcexport` sets the signal's unit from `unit`; with `scale` it sets factor = scale (the PLC still sees the raw value; only DBC readers show the scaled one) and min/max accordingly; it adds a `VAL_` table from `values` and appends `text` to the signal comment. An export whose objects have no notes is byte for byte as before; golden files that map CiA objects with built-in notes (for example 0x6061) are updated once, in the same commit as the built-in notes.

### D7. Checks
`notes.check(eds, notes)` returns warnings: schema errors, a key whose object is not in the EDS, `values` or `bits` on a non-integer type, a bit number beyond the type's size, `scale` of 0. The configurator shows them in the Problems pane as warnings with the notes file name; they never block Save. A notes file that is not valid JSON is shown as one warning, its notes are not used and the file is never overwritten until the user fixes or removes it. The deploy tool does not read notes files.

## Risks / Trade-offs

- Users may expect the vendor's own texts. → Mitigated by the skeleton and the editor; XDD import as a converter into this format stays possible later.
- Built-in notes are a maintenance cost. → Kept to the listed objects, in one place, tested for schema validity and for every key being a real CiA object index.
- A scaled DBC signal could confuse a reader comparing raw frames. → Only when the user sets `scale`; the comment says "raw × scale".

## Migration Plan

None. Existing projects get notes files on their next save. Deploy tool minor version bump.
