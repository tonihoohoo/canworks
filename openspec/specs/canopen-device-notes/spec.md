# canopen-device-notes Specification

## Purpose
Explain CANopen objects to the people who configure and commission a network: a short text, unit, scale, value meanings and bit names per object, from built-in CiA notes and a notes file next to each EDS, shown in the configurator and used by the exports, without changing what is written to a device.

## Requirements

### Requirement: Notes file per EDS
Each EDS under a project's `canworks/` folder MAY have a notes file next to it named `<eds file name>.notes.json`. The file SHALL be JSON with `"format": "canworks-notes.v1"`, an `eds` block with the EDS file name, vendor ID, product code and revision, and an `objects` map. Keys of `objects` SHALL be `0x<index>` for a VAR object or a whole ARRAY/RECORD and `0x<index>:<subindex>` for a sub-object, the index as four upper-case hex digits.

#### Scenario: Notes for a valve parameter
- **WHEN** `canworks/valve.eds.notes.json` has `"0x2011:2": {"text": "What the valve does on a bus fault", "values": {"0": "hold position", "1": "close"}}`
- **THEN** the configurator shows that text for 0x2011 sub 2 of every node using `valve.eds`, and a value of 1 as `1 (close)`

### Requirement: Notes schema
A JSON Schema for the notes format SHALL ship with the deploy tool and in the repository's `schema/` folder, and the configurator SHALL check notes files against it.

#### Scenario: Wrong key form
- **WHEN** a notes file has the key `0x6060:sub1`
- **THEN** the schema check names that key

### Requirement: Note fields
Each entry of `objects` SHALL be an object that MAY have `name` (a copy of the EDS name, ignored when read), `text` (one line, at most 200 characters), `details`, `unit`, `scale` (a non-zero number; shown value = raw value × scale), `values` (decimal raw value to meaning), `bits` (bit number to meaning; empty for a bit field without names) and `manual` (free text such as a page or section).

#### Scenario: Scaled value
- **WHEN** an entry has `"unit": "bar", "scale": 0.01` and the raw value is 1234
- **THEN** the value is shown as 12.34 bar next to the raw 1234

### Requirement: Notes stay on the PC
Notes files SHALL NOT be copied to the PLC by the deploy tool or read by the plugin, and SHALL NOT change any value written to a device.

#### Scenario: Not deployed
- **WHEN** `canworks-deploy` bundles a project whose `canworks/` folder holds `valve.eds` and `valve.eds.notes.json`
- **THEN** the upload contains `valve.eds` and no notes file

### Requirement: Sub-objects inherit the object's note
A sub-object without its own entry SHALL use the `text`, `details`, `unit`, `scale` and `manual` of its object's entry. It SHALL NOT inherit `values` or `bits`.

#### Scenario: Eight channels, one note
- **WHEN** the notes have `"0x6401": {"text": "Analog input value", "unit": "mV"}` and no entries for its sub-objects
- **THEN** 0x6401 sub 1 to sub 8 are all shown with "Analog input value" and the unit mV

### Requirement: Built-in CiA notes
The deploy tool SHALL ship notes in the same format for the CiA 301 communication objects and for the CiA 401 and CiA 402 profile objects, written in canworks' own words. The CiA 301 notes SHALL apply to every node. A profile's notes SHALL apply to a node whose EDS gives 0x1000 a default whose low 16 bits are that profile number.

#### Scenario: CiA 402 drive
- **WHEN** a node's EDS gives 0x1000 the default 0x00020192 and the user reads 0x6061 as 3
- **THEN** the value is shown as `3 (profile velocity)` without any notes file in the project

#### Scenario: Not a drive
- **WHEN** a node's EDS gives 0x1000 the default 0x00000191 (CiA 401) and has a vendor object at 0x6060
- **THEN** no CiA 402 mode meaning is shown for 0x6060

### Requirement: Bit names and value meanings come from notes
The built-in notes SHALL include at least the bit names of 0x1001, 0x6040 and 0x6041, 0x1002 as a bit field, the value meanings of the PDO transmission type (0x1400-0x15FF and 0x1800-0x19FF sub 2) and of 0x6060/0x6061, and the homing methods of 0x6098. The configurator SHALL take every bit name and value meaning it shows from notes, with none hard-coded in the page.

#### Scenario: Transmission type
- **WHEN** the user looks at 0x1800 sub 2 of any node with value 254
- **THEN** its meaning is shown as event-driven, manufacturer-specific

### Requirement: Device notes over built-in notes
Where both apply, the note of an object SHALL be the device notes file's entry merged field by field over the built-in entry, then the EDS name and limits. The device file SHALL hold only what the user wrote; built-in texts SHALL NOT be copied into it.

#### Scenario: Override one field
- **WHEN** the built-in note of 0x6060 has `values` and the device file has `"0x6060": {"values": {"-1": "vendor jog mode"}}`
- **THEN** the merged note has the vendor value as the only `values`, and the built-in `text` of 0x6060

### Requirement: Export merged notes
The configurator SHALL offer "Export merged notes" for a node, writing the merged notes of every object in its EDS to one file in the same format.

#### Scenario: Merged export
- **WHEN** the user exports merged notes for node 4, a CiA 402 drive with a notes file
- **THEN** the file holds the built-in notes of the CiA 301 and 402 objects in its EDS and the device file's entries, merged

### Requirement: Notes file created with the project
When the configurator saves a project and an EDS it uses has no notes file, it SHALL write one with the EDS identity and an entry with only `name` for every manufacturer object and sub-object (0x2000-0x5FFF) of the EDS.

#### Scenario: First save
- **WHEN** the user adds a node from `valve.eds`, which has manufacturer objects 0x2010 and 0x2011 sub 0-2, and saves
- **THEN** `canworks/valve.eds.notes.json` exists with the valve's identity and the keys `0x2010`, `0x2011:0`, `0x2011:1` and `0x2011:2`, each with only its EDS name

### Requirement: Existing notes files are kept
The configurator SHALL NOT replace an existing notes file. On save it SHALL write only the entries the user changed and refresh `name`, keeping all other entries, keys and their order.

#### Scenario: Hand-written notes kept
- **WHEN** the notes file has a hand-written `"0x2010": {"text": "Ramp", "x-source": "manual p. 12"}` and the user edits the note of 0x2011:1 and saves
- **THEN** the entry of 0x2010 is unchanged, including `x-source`, and 0x2011:1 has the new note

### Requirement: Notes checks
The configurator SHALL check each notes file against the schema and its EDS and show findings as warnings in the Problems pane naming the notes file: an object or sub-object the EDS does not have, `values` or `bits` on an object that is not an integer type, a bit number beyond the object's size, a `scale` of 0. Findings SHALL NOT block saving.

#### Scenario: Object removed in a new EDS revision
- **WHEN** a node's EDS is replaced by a revision without 0x2011 and the notes file still has `0x2011:2`
- **THEN** the Problems pane warns that `valve.eds.notes.json` has a note for 0x2011:2, which `valve.eds` does not have, and Save works

### Requirement: Unreadable notes file
A notes file that is not valid JSON or has another `format` SHALL give one warning, its notes SHALL NOT be used, and the configurator SHALL NOT overwrite it.

#### Scenario: Broken file
- **WHEN** `valve.eds.notes.json` has a JSON syntax error
- **THEN** one warning says the notes file cannot be read, no device notes are shown for `valve.eds`, and saving the project leaves the file as it is
