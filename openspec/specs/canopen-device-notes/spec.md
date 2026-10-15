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
The configurator SHALL offer **Export notes…** for a node with two choices: **My notes**, writing the device notes of its EDS (the identity and every entry with a field other than `name`, with the page's unsaved edits) as `<eds file name>.notes.json`; and **Merged with built-in**, writing the merged notes of every object in its EDS to one file in the same format.

#### Scenario: Merged export
- **WHEN** the user exports merged notes for node 4, a CiA 402 drive with a notes file
- **THEN** the file holds the built-in notes of the CiA 301 and 402 objects in its EDS and the device file's entries, merged

#### Scenario: Own export
- **WHEN** the user exports My notes for node 4, whose notes file has a text for 0x2010 and only `name` entries for 0x2011:0-2, with an unsaved unit for 0x2011:1
- **THEN** the file has the identity and the entries of 0x2010 and 0x2011:1 only, with that unit, and no built-in text

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

### Requirement: Import notes
**Import notes…** on the Notes tab SHALL read a notes file in the `canworks-notes.v1` format, a merged export included, and add its notes to the node's EDS's device notes. Fields equal to the built-in note and `name` SHALL NOT be imported. Each imported entry's fields SHALL replace those fields of the existing entry and keep its other fields. The import SHALL be one draft edit: undoable, marking the draft unsaved, and written by Save.

#### Scenario: Re-import a merged export
- **WHEN** the user imports a merged export of the same EDS into a project whose notes file is empty
- **THEN** the preview lists only the objects that had the user's own notes as new, the built-in notes as already the same, and after Import and Save the notes file holds no built-in text

#### Scenario: Undo an import
- **WHEN** the user imports three notes and presses Ctrl+Z
- **THEN** all three are gone and the draft is clean again if nothing else changed

### Requirement: Import preview
Before an import changes anything, the configurator SHALL check the file against the schema and the node's EDS and show the number of new notes, changed notes, notes already the same, and entries skipped because the EDS has no such object, each listed by object. A different EDS identity SHALL be a warning in the preview, not a refusal. A file that is not valid JSON or has another `format` SHALL be refused with a message saying so.

#### Scenario: Notes from another revision
- **WHEN** the user imports a notes file made for another revision of the EDS that has a note for 0x2012, which this EDS does not have
- **THEN** the preview warns that the file is for another device revision and lists 0x2012 as skipped, and Import adds the other notes

#### Scenario: Not a notes file
- **WHEN** the user picks a file with a JSON syntax error
- **THEN** the import is refused with a message that the file is not a notes file, and nothing changes

### Requirement: Notes from a datasheet
The repository SHALL include a Claude skill, `.claude/skills/canworks-datasheet-notes/SKILL.md`, that writes a `canworks-notes.v1` file for one EDS from the device's datasheet. It SHALL require the EDS, write only fields the datasheet states, give every entry a `manual` reference (page and section, or section when there are no pages), and leave out objects the datasheet does not describe. It SHALL run `canworks-deploy notes check` on its file until there are no findings.

#### Scenario: Manufacturer parameter from a PDF manual
- **WHEN** the user gives the skill `valve.eds` and a PDF manual whose page 42, section 6.3.2, says 0x2011 sub 2 selects the bus fault reaction, 0 hold position and 1 close
- **THEN** the written file has `"0x2011:2"` with a one-line `text`, `values` `{"0": "hold position", "1": "close"}` and `manual` "p. 42, 6.3.2", and `canworks-deploy notes check` reports nothing

### Requirement: Datasheet notes do not repeat built-in notes
The skill SHALL read `canworks-deploy notes skeleton` and `canworks-deploy notes builtin` for the EDS, and SHALL write notes for standard objects (0x1000-0x1FFF, 0x6000-0x9FFF) only where the datasheet describes something the built-in note does not, such as the device's own scaling, extra values or manufacturer bits.

#### Scenario: Standard object as the built-in note has it
- **WHEN** the datasheet describes the heartbeat producer time 0x1017 only as the CiA 301 object
- **THEN** the file has no entry for 0x1017

### Requirement: Datasheet formats
The skill SHALL accept the datasheet as PDF (including scanned pages), DOCX, ODT, HTML or a web page, XLSX or CSV object lists, and plain text or Markdown. It SHALL NOT require converting the datasheet to Markdown: a text copy SHALL be used only to find the object dictionary chapter, PDF pages SHALL then be read as laid out, and DOCX, ODT and HTML MAY be read through a Markdown copy.

#### Scenario: Bit table in a PDF
- **WHEN** a PDF datasheet gives the bits of status object 0x2100 in a table with merged cells
- **THEN** the skill finds the page through the text copy, reads the page itself, and the note's `bits` match the table

### Requirement: Ask about EDS and datasheet differences
When the datasheet and the EDS differ for an object (an object or sub-index only in one, or another type, size, access, range or default), the skill SHALL ask about each difference before writing, showing what the EDS and the datasheet (with page or section) say, and offering: follow the EDS, use the datasheet's description (difference stated in `details`), or skip the object. Each question SHALL also offer to apply the answer to the remaining differences of the same kind.

#### Scenario: Many shifted sub-indices
- **WHEN** the datasheet numbers the 16 channels of 0x2200 from sub 0 and the EDS from sub 1, and the user answers "follow the EDS" with "same for the rest of this kind" on the first one
- **THEN** the skill asks no more questions about 0x2200 and writes the 16 notes under the EDS sub-indices

### Requirement: Datasheet notes keep to the EDS
Keys in the skill's file SHALL be objects and sub-objects the EDS has, whatever the answers to the difference questions, and the skill SHALL NOT change the EDS.

#### Scenario: Object only in the datasheet
- **WHEN** the datasheet describes 0x2012, which the EDS does not have
- **THEN** the skill asks before writing, and whatever the answer, the file has no `0x2012` key and the report lists 0x2012 as missing from the EDS

### Requirement: Datasheet notes do not overwrite notes
The skill SHALL write `<eds file name>.notes.json` next to the EDS only when that file does not exist. When it exists, the skill SHALL write `<eds file name>.datasheet.notes.json` instead and SHALL tell the user to bring it in with **Import notes…**.

#### Scenario: Project already has notes
- **WHEN** `canworks/valve.eds.notes.json` exists and the skill runs for `valve.eds`
- **THEN** the existing file is unchanged and the skill writes `canworks/valve.eds.datasheet.notes.json`

### Requirement: Datasheet notes report
After writing, the skill SHALL tell the user the file it wrote, how many objects got notes, the EDS objects the datasheet does not describe, the items it left out and why, and each EDS and datasheet difference with the answer used, naming those answered with the datasheet's description as places where the EDS may need fixing.

#### Scenario: Report after a run
- **WHEN** the skill writes notes for 12 objects, leaves out 0x2300 because the datasheet's table is unreadable, and the user chose the datasheet's description for 0x2011:3
- **THEN** the report names the file and 12 objects, lists 0x2300 with that reason, and names 0x2011:3 as a possible EDS fix
