## MODIFIED Requirements

### Requirement: Notes tab
The Notes tab SHALL list the objects of the node's EDS in one of three views chosen above the list: **My notes** (the default), the objects and sub-objects whose device notes entry, with the page's unsaved edits, has at least one field other than `name`; **All notes**, the objects with a note, built-in or the user's own; and **All objects**, every object and sub-object of the EDS. Each row SHALL show the object, its name, the note's text, unit and value meanings, where the note comes from as text (**Mine**, **Built-in** or **Built-in, changed**), and a **Note** button opening the Note editor. The tab SHALL offer a search by index or name and, next to it, **Add note…**, **Import notes…** and **Export notes…** (see `canopen-device-notes`). **Add note…** SHALL open a picker of all objects and sub-objects of the EDS, searchable by index or name and marking those with a note, and then the Note editor of the chosen one. The tab's label SHALL show the number of the user's notes. The chosen view and the search SHALL be kept while the page is open. An empty view SHALL say why and offer **Add note…**, **Import notes…** and a way to show **All notes**. When the node has no EDS or its notes cannot be edited, the tab SHALL be read-only, SHALL say why, and SHALL offer only the views, the search and **Export notes…**.

#### Scenario: Own notes first
- **WHEN** the user opens the Notes tab of a drive whose notes file has a text for 0x2010 and only `name` entries for its other manufacturer objects, and the user has changed the values of 0x6060
- **THEN** My notes lists 0x2010 marked Mine and 0x6060 marked Built-in, changed, and nothing else, and the tab reads "Notes 2"

#### Scenario: Find a note
- **WHEN** the user picks All notes and types `6060` in the search of a drive
- **THEN** only 0x6060 is listed with its note, and **Note** opens its editor

#### Scenario: Note for an object without one
- **WHEN** the user presses **Add note…**, types `2011`, picks 0x2011:1, types a text in the Note editor and keeps it
- **THEN** My notes lists 0x2011:1 marked Mine with the focus on its row, and the draft is unsaved

#### Scenario: No notes yet
- **WHEN** the user opens the Notes tab of a node whose EDS has no notes of the user's own
- **THEN** the tab says there are no notes of the user's own yet and offers Add note…, Import notes… and Show all notes

#### Scenario: Read-only Notes tab
- **WHEN** the user opens the Notes tab of a node in "Commission a device" without a config
- **THEN** the notes are listed and can be exported, and no Note, Add note… or Import notes… button is offered

### Requirement: Note editor
The Notes tab SHALL be the only place in a project that opens the Note editor: each row's **Note** button and **Add note…**. The editor SHALL edit one object or sub-object with text, details, unit, scale, a values table, a bits table and manual. For an object with a built-in note the editor SHALL start from the built-in fields and SHALL save only the fields the user changed into the device notes file. The object dictionary view, the startup SDO editor and picker and the PDO entry picker SHALL show notes and SHALL NOT offer a Note button.

#### Scenario: Write a note while commissioning
- **WHEN** the user opens the Note editor of 0x2010 of node 7 from its Notes tab, types "Opening ramp of the valve", unit ms, and saves the project
- **THEN** `0x2010` in the EDS's notes file has that text and unit, and the object dictionary view shows them

#### Scenario: Override a built-in note
- **WHEN** the user adds the value -1 "vendor jog mode" to the values of 0x6060 in the Note editor and saves
- **THEN** the device notes file has only a `values` entry for 0x6060 and the built-in text is not copied

#### Scenario: No Note button in the PDO picker
- **WHEN** the user opens Add entry… on a TPDO of a node whose 0x2010 has a note
- **THEN** the picker shows the note's text under 0x2010's name and has no Note button
