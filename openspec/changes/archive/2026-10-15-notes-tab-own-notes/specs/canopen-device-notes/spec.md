## MODIFIED Requirements

### Requirement: Export merged notes
The configurator SHALL offer **Export notes…** for a node with two choices: **My notes**, writing the device notes of its EDS (the identity and every entry with a field other than `name`, with the page's unsaved edits) as `<eds file name>.notes.json`; and **Merged with built-in**, writing the merged notes of every object in its EDS to one file in the same format.

#### Scenario: Merged export
- **WHEN** the user exports merged notes for node 4, a CiA 402 drive with a notes file
- **THEN** the file holds the built-in notes of the CiA 301 and 402 objects in its EDS and the device file's entries, merged

#### Scenario: Own export
- **WHEN** the user exports My notes for node 4, whose notes file has a text for 0x2010 and only `name` entries for 0x2011:0-2, with an unsaved unit for 0x2011:1
- **THEN** the file has the identity and the entries of 0x2010 and 0x2011:1 only, with that unit, and no built-in text

## ADDED Requirements

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
