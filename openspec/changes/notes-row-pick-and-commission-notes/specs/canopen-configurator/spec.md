## ADDED Requirements

### Requirement: Add note picker
**Add note…** SHALL open a picker of every object and sub-object of the node's EDS with a search by index or name; each row shows the object, its name and where its note comes from. A click anywhere on a row SHALL pick that object and open its Note editor. The picker SHALL fit its dialog without sideways scrolling at 1000 px; long names SHALL wrap. Rows SHALL show a hover tint and the focused row the selected tint of the Object dictionary tab.

#### Scenario: Pick by clicking a row
- **WHEN** the user opens Add note… and clicks the name "Save_Communication_Parameters" in the row of 0x1010:2
- **THEN** the Note editor of 0x1010:2 opens

#### Scenario: Nothing hidden sideways
- **WHEN** the user opens Add note… for an EDS with long object names in a window 1000 px wide
- **THEN** every column is visible and the list scrolls only up and down

### Requirement: Add note picker by keyboard
Each row of the Add note picker SHALL hold one button named after the object (for example "Write a note for 0x2010:0 Ramp_time"). Down in the search SHALL move to the first row, Up and Down SHALL move between rows, Up on the first row SHALL go back to the search, Enter or Space SHALL pick the focused row, Enter in the search SHALL pick the first match, and Escape SHALL close the picker.

#### Scenario: Pick by keyboard
- **WHEN** the user types `1010` in the search, presses Down twice and Enter
- **THEN** the Note editor of 0x1010:1 opens

## MODIFIED Requirements

### Requirement: Notes tab
The Notes tab SHALL list the objects of the node's EDS in one of three views chosen above the list: **My notes** (the default), the objects and sub-objects whose device notes entry, with the page's unsaved edits, has at least one field other than `name`; **All notes**, the objects with a note, built-in or the user's own; and **All objects**, every object and sub-object of the EDS. Each row SHALL show the object, its name, the note's text, unit and value meanings, where the note comes from as text (**Mine**, **Built-in** or **Built-in, changed**), and a **Note** button opening the Note editor. When the notes can be edited, a click on a row outside its buttons SHALL also open its Note editor, unless the click ends a text selection. The tab SHALL offer a search by index or name and, next to it, **Add note…** (see "Add note picker"), **Import notes…** and **Export notes…** (see `canopen-device-notes`). The tab's label SHALL show the number of the user's notes. The chosen view and the search SHALL be kept while the page is open. An empty view SHALL say why and offer **Add note…**, **Import notes…** and a way to show **All notes**. The tab SHALL work the same in Configure, in Commission with a config and in Commission a device. When the node has no EDS or its notes cannot be edited (a canworks-built EDS, an unreadable notes file, a notes file that cannot be written), the tab SHALL be read-only, SHALL say why, and SHALL offer only the views, the search and **Export notes…**.

#### Scenario: Own notes first
- **WHEN** the user opens the Notes tab of a drive whose notes file has a text for 0x2010 and only `name` entries for its other manufacturer objects, and the user has changed the values of 0x6060
- **THEN** My notes lists 0x2010 marked Mine and 0x6060 marked Built-in, changed, and nothing else, and the tab reads "Notes 2"

#### Scenario: Find a note
- **WHEN** the user picks All notes and types `6060` in the search of a drive
- **THEN** only 0x6060 is listed with its note, and **Note** opens its editor

#### Scenario: Open a note by its row
- **WHEN** the user clicks the text of 0x2010's row on the Notes tab
- **THEN** the Note editor of 0x2010 opens

#### Scenario: Copy note text
- **WHEN** the user drags over part of 0x2010's note text to select it
- **THEN** the text is selected and no editor opens

#### Scenario: Note for an object without one
- **WHEN** the user presses **Add note…**, types `2011`, clicks the row of 0x2011:1, types a text in the Note editor and keeps it
- **THEN** My notes lists 0x2011:1 marked Mine with the focus on its row, and the draft is unsaved

#### Scenario: No notes yet
- **WHEN** the user opens the Notes tab of a node whose EDS has no notes of the user's own
- **THEN** the tab says there are no notes of the user's own yet and offers Add note…, Import notes… and Show all notes

#### Scenario: Notes while commissioning a device
- **WHEN** the user opens the Notes tab of node 12 in "Commission a device", whose EDS is in the EDS library
- **THEN** the tab offers the same views, Note buttons, Add note…, Import notes… and Export notes… as in a config

#### Scenario: Read-only Notes tab
- **WHEN** the EDS of node 12 in "Commission a device" is in a folder that cannot be written
- **THEN** the notes are listed and can be exported, the tab says the notes file next to the EDS cannot be written, and no Note, Add note… or Import notes… button is offered

### Requirement: Note editor
The Notes tab SHALL be the only place that opens the Note editor: each row's **Note** button or a click on the row, and **Add note…**. The editor SHALL edit one object or sub-object with text, details, unit, scale, a values table, a bits table and manual. For an object with a built-in note the editor SHALL start from the built-in fields and SHALL save only the fields the user changed into the device notes file. Emptying a field that shows a built-in or inherited value SHALL save that field as `null` (cleared); such a field SHALL show the built-in value greyed and marked hidden, with **Use built-in** to bring it back. The object dictionary view, the startup SDO editor and picker and the PDO entry picker SHALL show notes and SHALL NOT offer a Note button.

#### Scenario: Write a note while commissioning
- **WHEN** the user opens the Note editor of 0x2010 of node 7 from its Notes tab, types "Opening ramp of the valve", unit ms, and saves the project
- **THEN** `0x2010` in the EDS's notes file has that text and unit, and the object dictionary view shows them

#### Scenario: Override a built-in note
- **WHEN** the user adds the value -1 "vendor jog mode" to the values of 0x6060 in the Note editor and saves
- **THEN** the device notes file has only a `values` entry for 0x6060 and the built-in text is not copied

#### Scenario: No Note button in the PDO picker
- **WHEN** the user opens Add entry… on a TPDO of a node whose 0x2010 has a note
- **THEN** the picker shows the note's text under 0x2010's name and has no Note button

#### Scenario: Hide an inherited unit
- **WHEN** the user opens the Note editor of 0x6071 sub 0, which shows the built-in unit ‰, empties the unit and keeps the note
- **THEN** the device notes file has `"0x6071:0": {"unit": null}`, the object dictionary shows sub 0 without a unit, and reopening the editor shows ‰ greyed as hidden with **Use built-in**

#### Scenario: Bring the built-in value back
- **WHEN** the user presses **Use built-in** on that unit and keeps the note
- **THEN** the `null` is removed and sub 0 shows ‰ again

### Requirement: Note edits are draft edits
With a config open, a note edit SHALL mark the draft as changed, SHALL be written with Save, and SHALL be undoable like other draft edits. In "Commission a device", which has no Save, a kept note SHALL be written at once to the notes file next to the node's EDS file, with the same rules as Save (a new file starts from the skeleton; only changed fields are written). A banner SHALL name the file and offer **Undo**; Undo and Ctrl+Z SHALL put back the file as it was before the last note write of the page session. The Object dictionary, Parameters and PDO test tabs SHALL show the new note without reconnecting.

#### Scenario: Undo a note
- **WHEN** the user changes the text of 0x2010 in the Note editor of a config and presses Ctrl+Z
- **THEN** the earlier text is back and the draft is clean again if nothing else changed

#### Scenario: Write a note in Commission a device
- **WHEN** in "Commission a device" the user keeps the text "Opening ramp of the valve" for 0x2010 of node 12, whose EDS is `valve.eds` in the EDS library
- **THEN** `valve.eds.notes.json` in the EDS library has that text for 0x2010, the banner names that file and offers Undo, and the Object dictionary tab of node 12 shows the text

#### Scenario: Undo in Commission a device
- **WHEN** the user then presses Undo in the banner
- **THEN** the notes file is as it was before, and the Notes tab no longer lists 0x2010 under My notes

### Requirement: Commissioning log
In Commission a device, the session log (see "Session log") SHALL record every change made through the page:
- SDO write;
- NMT;
- LSS set ID, set bit rate and store;
- write configuration;
- restore and restore defaults;
- store;
- error history clear;
- note write, notes import and their undo, with the notes file's name.

"Save log" in the bottom panel's Log tab SHALL download `node<N>-commissioning-<time>.txt` with the device identity and EDS name at the top and the changes in order, and the bus events too when "Include bus events" is ticked (unticked by default).

The log SHALL belong to the commissioning session. Leaving Commission a device (Close, or "Add to a config…") with changes not saved SHALL ask whether to save the log first. The log SHALL then be cleared.

#### Scenario: Save the record
- **WHEN** the user gave the device node ID 12, wrote a configuration and stored it, then pressed Save log
- **THEN** the file lists those three changes in order with their results and no bus events

#### Scenario: Not carried into the config
- **WHEN** the user made two changes while commissioning, pressed "Add to a config…" and chose not to save the log
- **THEN** the config opens with an empty session log, and returning to Commission a device starts an empty log

#### Scenario: Note in the log
- **WHEN** the user writes a note for 0x2010 of node 12 while commissioning a device
- **THEN** the log has a change line naming 0x2010 and the notes file

## REMOVED Requirements

### Requirement: Notes read-only without a config
**Reason**: Commission a device now edits notes like a config, writing them at once (see "Note edits are draft edits" and "Notes tab").
**Migration**: None; notes stay read-only only when the notes file cannot be written or read.
