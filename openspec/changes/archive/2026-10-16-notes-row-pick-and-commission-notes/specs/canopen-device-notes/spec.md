## MODIFIED Requirements

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

## ADDED Requirements

### Requirement: Notes go with the EDS into a config
When "Add to a config…" adds a node from "Commission a device" to a config, the notes file next to the node's EDS SHALL be copied with the EDS when the config has no notes file for that EDS. When the config already has one, it SHALL be kept unchanged and the configurator SHALL say that the commissioning notes were not copied and can be imported on the Notes tab.

#### Scenario: Notes written while commissioning reach the config
- **WHEN** the user wrote notes for node 12 in "Commission a device" and adds node 12 to a config that does not yet use its EDS
- **THEN** the config's canopen folder has the EDS and its notes file, and node 12's Notes tab in the config lists the notes under My notes

#### Scenario: Config already has notes
- **WHEN** the config already has a notes file for that EDS
- **THEN** that file is unchanged and a message says the commissioning notes can be imported on the Notes tab
