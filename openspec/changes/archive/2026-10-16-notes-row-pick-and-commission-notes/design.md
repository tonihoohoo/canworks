## Context

The Add note picker (`addNote` in `node.js`) is a modal with a search and a table of Object / Name / Note / button; the only way to choose is the button, which sits in the last column. The table is in a `.note-picker-list` box that scrolls both ways, so long names push the button out of view (seen at a normal laptop width).

The Notes tab (`nodeNotesTab`) is shared by Configure, Commission with a config and Commission a device. Whether it can edit comes from `notesEditable(name)`, which is false whenever `S.state.commission` is true, and the server marks every EDS's notes `editable: false` in that mode and refuses `import_notes`. In Commission a device the node's EDS usually is a library file (absolute path) that is not in `S.state.eds`, so `commNotesTab` falls back to the notes the object dictionary was read with, passed in read-only. Note edits in a config are draft edits in `S.model.notes`, written by Save via `save_notes()`; Commission a device has no Save.

## Goals / Non-Goals

**Goals:** choose an object in the picker with one click, without sideways scrolling; the same notes features in Commission a device as in a config; notes written while commissioning end up where the config will find them.

**Non-goals:** changing the notes file format, the Note editor itself, or how notes show in the other lists; a Save button for Commission a device.

## Decisions

1. **A row click picks, no confirm step.** The picker exists only to choose one object, so a click on the row opens the Note editor at once (Cancel there returns to nothing being changed). The button column is removed; the Object cell holds a real `<button>` with the accessible name "Write a note for 0x2010:0 Name", as the Nodes table does with its node ID (rows are not `role=button`, which axe reports as nested interactive). The Note column keeps "Mine", "Built-in" or "no note".
2. **Keyboard in the picker.** Down from the search focuses the first row's button; Up and Down move between row buttons; Up from the first row goes back to the search; Enter or Space picks; Enter in the search picks the first match (unchanged). The focused row gets the Object dictionary tab's selected tint (`--sel-bg` and accent bar); hover tint only under `@media (hover: hover)`.
3. **No sideways scroll.** The picker table uses fixed Object and Note columns and lets Name wrap (`overflow-wrap: anywhere`), the dialog is wider (up to about 900 px, never wider than the window), and the list scrolls only vertically. Long `Snake_Case_Names` break inside the cell.
4. **Notes tab rows open on click too.** Same pattern as the picker and the Commission Nodes table, so the two note lists do not teach different habits. A click is ignored when the user has selected text in the row, or when it lands on a link or button. The **Note** button stays.
5. **Commission a device writes at once.** There is no draft or Save there, so a kept note goes to `POST /api/notes/write {eds, changes}` which uses the same `notes.update()` and skeleton logic as `save_notes()` and writes `<eds>.notes.json` next to the EDS file the node uses. Import uses the same preview and then the same endpoint. The page keeps the previous file text for Undo (banner button and Ctrl+Z, last write only, per page session). Alternative considered: a Save button in Commission a device. Rejected: nothing else there is saved, and a forgotten Save would lose notes typed with the device on the bench.
6. **Where the file goes.** Next to the EDS: for a library EDS, in the EDS library folder, so every project and later commissioning of the same device sees it; for an EDS the user picked from a file, next to that file. If that folder is not writable, the server says `editable: false` with the reason and the tab stays read-only, showing the reason. canworks-built EDS files (a slave's own) keep built-in notes only, as today.
7. **Notes of a library EDS in the page state.** In Commission a device the server returns the notes block (`builtin`, `device`, `editable`, `error`) for each EDS used on the Nodes table, keyed by the same name the Nodes table uses, so the tab, the count on its label and the Object dictionary tab use one source instead of the read-only fallback.
8. **Log.** Each write is a commissioning log change line: `notes: 0x2010:0 written to <file>` or `notes: imported 12 notes from <file> into <file>`, and Undo adds its own line.
9. **Add to a config.** When a Commission node is added to a config, the EDS is imported as now; if the EDS has a notes file and the config has none for that EDS, the notes file is copied too. If the config already has one, it is kept (no merge) and the banner says the commissioning notes were not copied and can be imported from the Notes tab.

## Risks / Trade-offs

- Writing at once into the EDS library changes a shared folder without a Save. Mitigation: banner with the file name and Undo, a log line, and only fields the user changed are written, as with Save.
- A row click that opens a modal can surprise someone who clicked to select. Mitigation: text selection is not treated as a click, and in the picker choosing is the only thing a row can do.
