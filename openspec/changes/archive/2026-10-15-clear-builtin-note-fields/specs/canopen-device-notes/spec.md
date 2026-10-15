## MODIFIED Requirements

### Requirement: Note fields
Each entry of `objects` SHALL be an object that MAY have `name` (a copy of the EDS name, ignored when read), `text` (one line, at most 200 characters), `details`, `unit`, `scale` (a non-zero number; shown value = raw value × scale), `values` (decimal raw value to meaning), `bits` (bit number to meaning; empty for a bit field without names) and `manual` (free text such as a page or section). Each of these fields except `name` MAY instead be `null`, which clears that field (see Device notes over built-in notes).

#### Scenario: Scaled value
- **WHEN** an entry has `"unit": "bar", "scale": 0.01` and the raw value is 1234
- **THEN** the value is shown as 12.34 bar next to the raw 1234

#### Scenario: Cleared field in the schema
- **WHEN** an entry has `"unit": null`
- **THEN** the schema check reports nothing for it

### Requirement: Sub-objects inherit the object's note
A sub-object without its own entry, or without its own value for a field, SHALL use the `text`, `details`, `unit`, `scale` and `manual` of its object's entry. It SHALL NOT inherit `values` or `bits`. A field the object's device entry sets to `null` SHALL NOT be inherited from the built-in note.

#### Scenario: Eight channels, one note
- **WHEN** the notes have `"0x6401": {"text": "Analog input value", "unit": "mV"}` and no entries for its sub-objects
- **THEN** 0x6401 sub 1 to sub 8 are all shown with "Analog input value" and the unit mV

#### Scenario: Built-in unit not inherited by the count
- **WHEN** the built-in note of 0x6071 has the unit ‰ on its object key and the device notes have `"0x6071": {"unit": null}` and `"0x6071:1": {"unit": "mA"}`
- **THEN** 0x6071 sub 0 is shown without a unit and sub 1 with mA

### Requirement: Device notes over built-in notes
Where both apply, the note of an object SHALL be the device notes file's entry merged field by field over the built-in entry, then the EDS name and limits. A device field set to `null` SHALL remove that field from the merged note; a sub-object's own value SHALL win over its object's `null`. The device file SHALL hold only what the user wrote; built-in texts SHALL NOT be copied into it.

#### Scenario: Override one field
- **WHEN** the built-in note of 0x6060 has `values` and the device file has `"0x6060": {"values": {"-1": "vendor jog mode"}}`
- **THEN** the merged note has the vendor value as the only `values`, and the built-in `text` of 0x6060

#### Scenario: Clear an unsupported list
- **WHEN** the device file has `"0x6098": {"text": "Homing is not supported", "values": null}`
- **THEN** the merged note of 0x6098 has that text and no value meanings, in the object dictionary, the HTML docs and the merged export

### Requirement: Import notes
**Import notes…** on the Notes tab SHALL read a notes file in the `canworks-notes.v1` format, a merged export included, and add its notes to the node's EDS's device notes. Fields equal to the built-in note and `name` SHALL NOT be imported. A `null` field SHALL be imported when the note it lands on has that field (built-in, inherited or the user's own) and SHALL count as the same otherwise. Each imported entry's fields SHALL replace those fields of the existing entry and keep its other fields. The import SHALL be one draft edit: undoable, marking the draft unsaved, and written by Save. A merged export SHALL NOT contain `null` fields.

#### Scenario: Re-import a merged export
- **WHEN** the user imports a merged export of the same EDS into a project whose notes file is empty
- **THEN** the preview lists only the objects that had the user's own notes as new, the built-in notes as already the same, and after Import and Save the notes file holds no built-in text

#### Scenario: Undo an import
- **WHEN** the user imports three notes and presses Ctrl+Z
- **THEN** all three are gone and the draft is clean again if nothing else changed

#### Scenario: Import a cleared unit
- **WHEN** the imported file has `"0x6071": {"unit": null}` and the built-in note of 0x6071 has a unit
- **THEN** the preview lists 0x6071 as new, and after Import the unit is gone from 0x6071 sub 0

### Requirement: Notes checks
The configurator SHALL check each notes file against the schema and its EDS and show findings as warnings in the Problems pane naming the notes file: an object or sub-object the EDS does not have, `values` or `bits` on an object that is not an integer type, `values` or `bits` on an ARRAY or RECORD object key (sub-objects do not inherit them), a bit number beyond the object's size, a `scale` of 0, a `null` field that clears nothing (no built-in or inherited value). Findings SHALL NOT block saving.

#### Scenario: Object removed in a new EDS revision
- **WHEN** a node's EDS is replaced by a revision without 0x2011 and the notes file still has `0x2011:2`
- **THEN** the Problems pane warns that `valve.eds.notes.json` has a note for 0x2011:2, which `valve.eds` does not have, and Save works

#### Scenario: Values on a record key
- **WHEN** the notes file has `"0x6423": {"values": {"128": "controlling"}}` and 0x6423 is a RECORD
- **THEN** the Problems pane warns that the values of 0x6423 are not used by its sub-objects

#### Scenario: Nothing to clear
- **WHEN** the notes file has `"0x2010": {"unit": null}` and 0x2010 has no built-in note
- **THEN** the Problems pane warns that 0x2010 clears its unit, but there is none to clear

### Requirement: Datasheet notes correct built-in notes
The skill SHALL compare the built-in note of each standard object the datasheet describes with the datasheet, and SHALL write the device's own `text`, `unit` or `values` where the built-in one does not fit the device. Where a built-in field does not apply to the device at all, such as a list of modes the device supports none of or a unit that sub 0 or other sub-objects would inherit, the note SHALL set that field to `null` and `details` SHALL say why.

#### Scenario: Current instead of torque
- **WHEN** the built-in note of 0x6071 speaks of rated torque and the datasheet says the value is in thousandths of rated current
- **THEN** the note of 0x6071 has the datasheet's text and unit

#### Scenario: Unsupported homing
- **WHEN** the datasheet says homing is not supported and the built-in note of 0x6098 lists homing methods
- **THEN** the note of 0x6098 has `text` saying homing is not supported, `values` set to `null`, and `details` saying so
