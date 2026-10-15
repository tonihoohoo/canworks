## ADDED Requirements

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
