## MODIFIED Requirements

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

### Requirement: Ask about EDS and datasheet differences
When the datasheet and the EDS differ for an object (an object or sub-index only in one, or another name, type, size, access, range, default or PDO mapping), the skill SHALL collect every difference and, before writing, show them in one table: one row per difference or per group of differences of the same kind, naming the objects of the row, what the EDS says, what the datasheet says with its page or section, and the answer it will use, follow the EDS by default. The user SHALL be able to accept the table or change single rows to use the datasheet's description (difference stated in `details`) or skip the objects. Following the EDS SHALL mean that the note keeps the EDS's layout, type, size and range and states nothing the EDS contradicts, with the difference named in `details`.

#### Scenario: Many shifted sub-indices
- **WHEN** the datasheet numbers the 16 channels of 0x2200 from sub 0 and the EDS from sub 1
- **THEN** the table has one row for 0x2200 listing the shift, and when the user accepts it, the 16 notes are written under the EDS sub-indices

#### Scenario: Change one row
- **WHEN** the table has rows 1-5 and the user answers "row 3: use the datasheet"
- **THEN** the objects of row 3 get the datasheet's description with the difference in `details`, and rows 1, 2, 4 and 5 follow the EDS

### Requirement: Datasheet notes report
After writing, the skill SHALL tell the user the file it wrote, how many objects got notes, the EDS objects the datasheet does not describe, the items it left out and why, contradictions inside the datasheet and which side it used, each difference row with the answer used, naming those answered with the datasheet's description and objects only in the datasheet as places where the EDS may need fixing, and other differences seen on objects that got no note.

#### Scenario: Report after a run
- **WHEN** the skill writes notes for 12 objects, leaves out 0x2300 because the datasheet's table is unreadable, and the user chose the datasheet's description for 0x2011:3
- **THEN** the report names the file and 12 objects, lists 0x2300 with that reason, and names 0x2011:3 as a possible EDS fix

#### Scenario: Problem on an object without a note
- **WHEN** the datasheet gives the device type 0x1000 another default than the EDS and the built-in note covers 0x1000
- **THEN** the file has no 0x1000 entry and the report lists the default difference under other EDS problems

### Requirement: Datasheet notes do not repeat built-in notes
The skill SHALL read `canworks-deploy notes skeleton` and `canworks-deploy notes builtin` for the EDS, and SHALL write notes for standard objects (0x1000-0x1FFF, 0x6000-0x9FFF) only where the datasheet describes something the built-in note does not, such as the device's own scaling, extra values or manufacturer bits. Where no built-in note applies to a standard object, such as a profile without built-in notes, the skill SHALL write a note where the datasheet describes the object beyond its name, type and default.

#### Scenario: Standard object as the built-in note has it
- **WHEN** the datasheet describes the heartbeat producer time 0x1017 only as the CiA 301 object
- **THEN** the file has no entry for 0x1017

#### Scenario: Encoder without built-in profile notes
- **WHEN** `notes builtin` says there are no built-in notes for profile 406 and the datasheet explains the bits of 0x6000 operating parameters
- **THEN** the file has an entry for 0x6000 with those bits

### Requirement: Notes checks
The configurator SHALL check each notes file against the schema and its EDS and show findings as warnings in the Problems pane naming the notes file: an object or sub-object the EDS does not have, `values` or `bits` on an object that is not an integer type, `values` or `bits` on an ARRAY or RECORD object key (sub-objects do not inherit them), a bit number beyond the object's size, a `scale` of 0. Findings SHALL NOT block saving.

#### Scenario: Object removed in a new EDS revision
- **WHEN** a node's EDS is replaced by a revision without 0x2011 and the notes file still has `0x2011:2`
- **THEN** the Problems pane warns that `valve.eds.notes.json` has a note for 0x2011:2, which `valve.eds` does not have, and Save works

#### Scenario: Values on a record key
- **WHEN** the notes file has `"0x6423": {"values": {"128": "controlling"}}` and 0x6423 is a RECORD
- **THEN** the Problems pane warns that the values of 0x6423 are not used by its sub-objects

## ADDED Requirements

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
The skill SHALL compare the built-in note of each standard object the datasheet describes with the datasheet, and SHALL write the device's own `text`, `unit` or `values` where the built-in one does not fit the device. Where the device supports none of a built-in list, the note's `text` SHALL say so and `details` SHALL say the built-in list does not apply, since a note cannot remove a built-in field.

#### Scenario: Current instead of torque
- **WHEN** the built-in note of 0x6071 speaks of rated torque and the datasheet says the value is in thousandths of rated current
- **THEN** the note of 0x6071 has the datasheet's text and unit

#### Scenario: Unsupported homing
- **WHEN** the datasheet says homing is not supported and the built-in note of 0x6098 lists homing methods
- **THEN** the note of 0x6098 has `text` saying homing is not supported and `details` saying the listed methods do not apply

### Requirement: Datasheets for several buses
From a manual for several buses, objects marked for another bus only SHALL NOT be differences unless the EDS has them.

#### Scenario: Manual for two buses
- **WHEN** a CANopen and EtherCAT manual marks 0x3B61 as EtherCAT only and the CANopen EDS lacks it, and marks 0x3B60 as EtherCAT only while the EDS has it
- **THEN** 0x3B61 is not a difference, and 0x3B60 is a row of the difference table
