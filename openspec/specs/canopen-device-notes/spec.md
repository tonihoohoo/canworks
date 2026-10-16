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
Each entry of `objects` SHALL be an object that MAY have `name` (a copy of the EDS name, ignored when read), `text` (one line, at most 200 characters), `details`, `unit`, `scale` (a non-zero number; shown value = raw value × scale), `values` (decimal raw value to meaning), `bits` (bit number to meaning; empty for a bit field without names) and `manual` (free text such as a page or section). Each of these fields except `name` MAY instead be `null`, which clears that field (see Device notes over built-in notes).

#### Scenario: Scaled value
- **WHEN** an entry has `"unit": "bar", "scale": 0.01` and the raw value is 1234
- **THEN** the value is shown as 12.34 bar next to the raw 1234

#### Scenario: Cleared field in the schema
- **WHEN** an entry has `"unit": null`
- **THEN** the schema check reports nothing for it

### Requirement: Notes stay on the PC
Notes files SHALL NOT be copied to the PLC by the deploy tool or read by the plugin, and SHALL NOT change any value written to a device.

#### Scenario: Not deployed
- **WHEN** `canworks-deploy` bundles a project whose `canworks/` folder holds `valve.eds` and `valve.eds.notes.json`
- **THEN** the upload contains `valve.eds` and no notes file

### Requirement: Sub-objects inherit the object's note
A sub-object without its own entry, or without its own value for a field, SHALL use the `text`, `details`, `unit`, `scale` and `manual` of its object's entry. It SHALL NOT inherit `values` or `bits`. A field the object's device entry sets to `null` SHALL NOT be inherited from the built-in note.

#### Scenario: Eight channels, one note
- **WHEN** the notes have `"0x6401": {"text": "Analog input value", "unit": "mV"}` and no entries for its sub-objects
- **THEN** 0x6401 sub 1 to sub 8 are all shown with "Analog input value" and the unit mV

#### Scenario: Built-in unit not inherited by the count
- **WHEN** the built-in note of 0x6071 has the unit ‰ on its object key and the device notes have `"0x6071": {"unit": null}` and `"0x6071:1": {"unit": "mA"}`
- **THEN** 0x6071 sub 0 is shown without a unit and sub 1 with mA

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
Where both apply, the note of an object SHALL be the device notes file's entry merged field by field over the built-in entry, then the EDS name and limits. A device field set to `null` SHALL remove that field from the merged note; a sub-object's own value SHALL win over its object's `null`. The device file SHALL hold only what the user wrote; built-in texts SHALL NOT be copied into it.

#### Scenario: Override one field
- **WHEN** the built-in note of 0x6060 has `values` and the device file has `"0x6060": {"values": {"-1": "vendor jog mode"}}`
- **THEN** the merged note has the vendor value as the only `values`, and the built-in `text` of 0x6060

#### Scenario: Clear an unsupported list
- **WHEN** the device file has `"0x6098": {"text": "Homing is not supported", "values": null}`
- **THEN** the merged note of 0x6098 has that text and no value meanings, in the object dictionary, the HTML docs and the merged export

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

### Requirement: Unreadable notes file
A notes file that is not valid JSON or has another `format` SHALL give one warning, its notes SHALL NOT be used, and the configurator SHALL NOT overwrite it.

#### Scenario: Broken file
- **WHEN** `valve.eds.notes.json` has a JSON syntax error
- **THEN** one warning says the notes file cannot be read, no device notes are shown for `valve.eds`, and saving the project leaves the file as it is

### Requirement: Import notes
**Import notes…** on the Notes tab SHALL read a notes file in the `canworks-notes.v1` format, a merged export included, and add its notes to the node's EDS's device notes. Fields equal to the built-in note and `name` SHALL NOT be imported. A `null` field SHALL be imported when the note it lands on has that field (built-in, inherited or the user's own) and SHALL count as the same otherwise. Each imported entry's fields SHALL replace those fields of the existing entry and keep its other fields. With a config open, the import SHALL be one draft edit: undoable, marking the draft unsaved, and written by Save. In "Commission a device" the import SHALL be written at once to the notes file next to the EDS, as one step that Undo puts back. A merged export SHALL NOT contain `null` fields.

#### Scenario: Re-import a merged export
- **WHEN** the user imports a merged export of the same EDS into a project whose notes file is empty
- **THEN** the preview lists only the objects that had the user's own notes as new, the built-in notes as already the same, and after Import and Save the notes file holds no built-in text

#### Scenario: Undo an import
- **WHEN** the user imports three notes and presses Ctrl+Z
- **THEN** all three are gone and the draft is clean again if nothing else changed

#### Scenario: Import a cleared unit
- **WHEN** the imported file has `"0x6071": {"unit": null}` and the built-in note of 0x6071 has a unit
- **THEN** the preview lists 0x6071 as new, and after Import the unit is gone from 0x6071 sub 0

#### Scenario: Import while commissioning a device
- **WHEN** in "Commission a device" the user imports a notes file with three new notes for node 12's EDS and presses Import in the preview
- **THEN** the notes file next to the EDS has the three notes, and Undo removes them again

### Requirement: Import preview
Before an import changes anything, the configurator SHALL check the file against the schema and the node's EDS and show the number of new notes, changed notes, notes already the same, and entries skipped because the EDS has no such object, each listed by object. A different EDS identity SHALL be a warning in the preview, not a refusal. A file that is not valid JSON or has another `format` SHALL be refused with a message saying so.

#### Scenario: Notes from another revision
- **WHEN** the user imports a notes file made for another revision of the EDS that has a note for 0x2012, which this EDS does not have
- **THEN** the preview warns that the file is for another device revision and lists 0x2012 as skipped, and Import adds the other notes

#### Scenario: Not a notes file
- **WHEN** the user picks a file with a JSON syntax error
- **THEN** the import is refused with a message that the file is not a notes file, and nothing changes

### Requirement: Notes from a datasheet
The repository SHALL include a Claude skill, `.claude/skills/canworks-datasheet-notes/SKILL.md`, that writes a `canworks-notes.v1` file for one EDS from the device's datasheet. It SHALL require the EDS, write only fields the datasheet states, give every entry a `manual` reference (the printed page and section, with the PDF page when it differs, or the heading when there are no pages, preceded by the document's number or short title when the skill used several documents), and leave out objects the datasheet does not describe (a row with only name, type and default is not a description). It SHALL run `canworks-deploy notes check` on its file until there are no findings. When the EDS cannot be read, the skill SHALL stop, tell the user the error with its line or section, and SHALL NOT change the EDS.

#### Scenario: Manufacturer parameter from a PDF manual
- **WHEN** the user gives the skill `valve.eds` and a PDF manual whose page 42, section 6.3.2, says 0x2011 sub 2 selects the bus fault reaction, 0 hold position and 1 close
- **THEN** the written file has `"0x2011:2"` with a one-line `text`, `values` `{"0": "hold position", "1": "close"}` and `manual` "p. 42, 6.3.2", and `canworks-deploy notes check` reports nothing

#### Scenario: Printed page differs from the PDF page
- **WHEN** the object is described on the page printed as 27, which is page 28 of the PDF file
- **THEN** its `manual` is "p. 27 (PDF 28)" followed by the section

#### Scenario: Two documents
- **WHEN** a CANopen manual gives the index rule for 0x2001 and a separate parameter manual describes the parameter on page 18
- **THEN** the note's `manual` starts with the parameter manual's number or short title, then "p. 18"

#### Scenario: EDS that does not load
- **WHEN** `canworks-deploy notes skeleton` refuses the EDS because line 1843 has no `=`
- **THEN** the skill writes no notes file, leaves the EDS as it is, and tells the user line 1843 must be fixed first

### Requirement: Datasheet notes do not repeat built-in notes
The skill SHALL read `canworks-deploy notes skeleton` and `canworks-deploy notes builtin` for the EDS, and SHALL write notes for standard objects (0x1000-0x1FFF, 0x6000-0x9FFF) only where the datasheet describes something the built-in note does not, such as the device's own scaling, extra values or manufacturer bits. Where no built-in note applies to a standard object, such as a profile without built-in notes, the skill SHALL write a note where the datasheet describes the object beyond its name, type and default.

#### Scenario: Standard object as the built-in note has it
- **WHEN** the datasheet describes the heartbeat producer time 0x1017 only as the CiA 301 object
- **THEN** the file has no entry for 0x1017

#### Scenario: Encoder without built-in profile notes
- **WHEN** `notes builtin` says there are no built-in notes for profile 406 and the datasheet explains the bits of 0x6000 operating parameters
- **THEN** the file has an entry for 0x6000 with those bits

### Requirement: Datasheet formats
The skill SHALL accept the datasheet as PDF (including scanned pages), DOCX, ODT, HTML or a web page, XLSX or CSV object lists, and plain text or Markdown. It SHALL NOT require converting the datasheet to Markdown: a text copy SHALL be used only to find the object dictionary chapter, PDF pages SHALL then be read as laid out, and DOCX, ODT and HTML MAY be read through a Markdown copy.

#### Scenario: Bit table in a PDF
- **WHEN** a PDF datasheet gives the bits of status object 0x2100 in a table with merged cells
- **THEN** the skill finds the page through the text copy, reads the page itself, and the note's `bits` match the table

### Requirement: Ask about EDS and datasheet differences
When the datasheet and the EDS differ for an object (an object or sub-index only in one, or another name, type, size, access, range, default or PDO mapping), the skill SHALL collect every difference and, before writing, show them in one table: one row per difference or per group of differences of the same kind, naming the objects of the row, what the EDS says, what the datasheet says with its page or section, and the answer it will use, follow the EDS by default. The user SHALL be able to accept the table or change single rows to use the datasheet's description (difference stated in `details`) or skip the objects. Following the EDS SHALL mean that the note keeps the EDS's layout, type, size and range and states nothing the EDS contradicts, with the difference named in `details`.

#### Scenario: Many shifted sub-indices
- **WHEN** the datasheet numbers the 16 channels of 0x2200 from sub 0 and the EDS from sub 1
- **THEN** the table has one row for 0x2200 listing the shift, and when the user accepts it, the 16 notes are written under the EDS sub-indices

#### Scenario: Change one row
- **WHEN** the table has rows 1-5 and the user answers "row 3: use the datasheet"
- **THEN** the objects of row 3 get the datasheet's description with the difference in `details`, and rows 1, 2, 4 and 5 follow the EDS

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
After writing, the skill SHALL tell the user the file it wrote, how many objects got notes, the EDS objects the datasheet does not describe, the items it left out and why, contradictions inside the datasheet and which side it used, each difference row with the answer used, naming those answered with the datasheet's description and objects only in the datasheet as places where the EDS may need fixing, and other differences seen on objects that got no note.

#### Scenario: Report after a run
- **WHEN** the skill writes notes for 12 objects, leaves out 0x2300 because the datasheet's table is unreadable, and the user chose the datasheet's description for 0x2011:3
- **THEN** the report names the file and 12 objects, lists 0x2300 with that reason, and names 0x2011:3 as a possible EDS fix

#### Scenario: Problem on an object without a note
- **WHEN** the datasheet gives the device type 0x1000 another default than the EDS and the built-in note covers 0x1000
- **THEN** the file has no 0x1000 entry and the report lists the default difference under other EDS problems

### Requirement: Datasheet values as the EDS reads them
The skill SHALL write `bits` and `values` as the device reads the EDS object: bits numbered from 0 when the datasheet numbers them from 1, values of signed types as negative decimal when the datasheet gives them in hex, and one entry per raw value when one datasheet row covers several.

#### Scenario: Bits numbered from 1
- **WHEN** the datasheet names bits 1 to 16 of a 16-bit diagnostics object
- **THEN** the note's `bits` are "0" to "15" and `details` says the datasheet numbers them from 1

#### Scenario: Signed hex value
- **WHEN** the datasheet says FFFFh disables a limit of an INTEGER16 object
- **THEN** the note's `values` has "-1"

### Requirement: Datasheet facts the notes fields cannot hold
The skill SHALL put value ranges, fields of several bits, write signatures, a scale that depends on another object, whether a value is stored and when a change takes effect, and objects outside the EDS that the object needs (such as an enable object) in `details`. It MAY write a scale derived from a stated full-scale value when `details` says how. It SHALL NOT write a unit that only the object's name implies.

#### Scenario: Derived scale
- **WHEN** the datasheet says the velocity value 0x7FFFFFFF equals 10000 rpm
- **THEN** the note has unit `rpm`, the scale 10000/2147483647 and `details` saying it is derived from that full-scale value

#### Scenario: Reserved range
- **WHEN** the datasheet lists filter types 0-4 and "5-99 reserved"
- **THEN** `values` has 0 to 4 and `details` says 5-99 are reserved

### Requirement: Datasheet sources with rules and variants
The skill SHALL find the EDS key through an index rule the datasheet states (such as base index plus parameter number, or a hex sub-index) and SHALL write no note from such a rule alone. From a family manual it SHALL describe only what applies to the EDS's device and SHALL NOT count objects of other variants as differences. From a spreadsheet, `text` MAY be the parameter's name in the sheet, and `manual` SHALL name the sheet and the parameter's code rather than a row number.

#### Scenario: Parameter number rule
- **WHEN** the manual says parameter 703 is object 2000h + 703 and describes parameter 703 on page 19
- **THEN** the note is on `0x22BF` with `manual` "p. 19"

#### Scenario: Spreadsheet parameter list
- **WHEN** the sheet "Parameters" lists the parameter code RAMP with index 2000h, sub-index 10h, and its values
- **THEN** the note is on `0x2000:16` with `manual` naming the sheet "Parameters" and RAMP

### Requirement: Datasheet notes keep built-in names
On a standard object the skill SHALL write `bits` and `values` as the device's complete list, keeping built-in entries the datasheet does not contradict, because a device note's field replaces the built-in field.

#### Scenario: Manufacturer bits in the statusword
- **WHEN** the datasheet names bits 8 and 14 of 0x6041 and says nothing of bit 4
- **THEN** the note's `bits` has the datasheet's names for 8 and 14 and the built-in name of bit 4

### Requirement: Datasheet notes correct built-in notes
The skill SHALL compare the built-in note of each standard object the datasheet describes with the datasheet, and SHALL write the device's own `text`, `unit` or `values` where the built-in one does not fit the device. Where a built-in field does not apply to the device at all, such as a list of modes the device supports none of or a unit that sub 0 or other sub-objects would inherit, the note SHALL set that field to `null` and `details` SHALL say why.

#### Scenario: Current instead of torque
- **WHEN** the built-in note of 0x6071 speaks of rated torque and the datasheet says the value is in thousandths of rated current
- **THEN** the note of 0x6071 has the datasheet's text and unit

#### Scenario: Unsupported homing
- **WHEN** the datasheet says homing is not supported and the built-in note of 0x6098 lists homing methods
- **THEN** the note of 0x6098 has `text` saying homing is not supported, `values` set to `null`, and `details` saying so

### Requirement: Datasheets for several buses
From a manual for several buses, objects marked for another bus only SHALL NOT be differences unless the EDS has them.

#### Scenario: Manual for two buses
- **WHEN** a CANopen and EtherCAT manual marks 0x3B61 as EtherCAT only and the CANopen EDS lacks it, and marks 0x3B60 as EtherCAT only while the EDS has it
- **THEN** 0x3B61 is not a difference, and 0x3B60 is a row of the difference table

### Requirement: Notes go with the EDS into a config
When "Add to a config…" adds a node from "Commission a device" to a config, the notes file next to the node's EDS SHALL be copied with the EDS when the config has no notes file for that EDS. When the config already has one, it SHALL be kept unchanged and the configurator SHALL say that the commissioning notes were not copied and can be imported on the Notes tab.

#### Scenario: Notes written while commissioning reach the config
- **WHEN** the user wrote notes for node 12 in "Commission a device" and adds node 12 to a config that does not yet use its EDS
- **THEN** the config's canopen folder has the EDS and its notes file, and node 12's Notes tab in the config lists the notes under My notes

#### Scenario: Config already has notes
- **WHEN** the config already has a notes file for that EDS
- **THEN** that file is unchanged and a message says the commissioning notes can be imported on the Notes tab
