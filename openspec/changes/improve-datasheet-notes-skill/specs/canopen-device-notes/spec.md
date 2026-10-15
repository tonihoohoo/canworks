## MODIFIED Requirements

### Requirement: Notes from a datasheet
The repository SHALL include a Claude skill, `.claude/skills/canworks-datasheet-notes/SKILL.md`, that writes a `canworks-notes.v1` file for one EDS from the device's datasheet. It SHALL require the EDS, write only fields the datasheet states, give every entry a `manual` reference (the printed page and section, with the PDF page when it differs, or the heading when there are no pages), and leave out objects the datasheet does not describe (a row with only name, type and default is not a description). It SHALL run `canworks-deploy notes check` on its file until there are no findings.

#### Scenario: Manufacturer parameter from a PDF manual
- **WHEN** the user gives the skill `valve.eds` and a PDF manual whose page 42, section 6.3.2, says 0x2011 sub 2 selects the bus fault reaction, 0 hold position and 1 close
- **THEN** the written file has `"0x2011:2"` with a one-line `text`, `values` `{"0": "hold position", "1": "close"}` and `manual` "p. 42, 6.3.2", and `canworks-deploy notes check` reports nothing

#### Scenario: Printed page differs from the PDF page
- **WHEN** the object is described on the page printed as 27, which is page 28 of the PDF file
- **THEN** its `manual` is "p. 27 (PDF 28)" followed by the section

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

## ADDED Requirements

### Requirement: Datasheet notes keep built-in names
On a standard object the skill SHALL write `bits` and `values` as the device's complete list, keeping built-in entries the datasheet does not contradict, because a device note's field replaces the built-in field.

#### Scenario: Manufacturer bits in the statusword
- **WHEN** the datasheet names bits 8 and 14 of 0x6041 and says nothing of bit 4
- **THEN** the note's `bits` has the datasheet's names for 8 and 14 and the built-in name of bit 4
