## Context

Notes (spec `canopen-device-notes`) are kept per EDS in `<eds>.notes.json`; the page gets each EDS's `builtin` and `device` tables from `/api/state` and keeps unsaved edits in `S.model.notes[eds][key]`. `noteFor()` merges them. The Notes tab (`nodeNotesTab` in `node.js`) loops over the EDS's objects and lists those whose merged note is not empty. The Commission Notes tab calls the same function. The Note editor (`editNote` in `app.js`) is opened from four places.

## Goals / Non-Goals

**Goals:** see the user's own notes at a glance; do every notes task (add, edit, import, export) in one place; no change to the notes file format or what is saved.

**Non-goals:** editing built-in notes, sharing notes between EDS files, importing XDD or spreadsheets, bulk editing.

## Decisions

1. **"Filled" means a device entry with any field other than `name`.** The skeleton written on first save gives every manufacturer object `{"name": ...}`; those are placeholders, not notes. Unsaved edits count, and a removed note (empty entry) does not. Alternative considered: count entries that differ from the EDS. Rejected: `name` is refreshed from the EDS on save anyway.
2. **My notes is the default view.** That is what the request asks for. When the user has no notes yet, the empty state offers the three actions and a link to All notes, so the tab is never a dead end. The view is a segmented button group (tab list semantics are already used by the node tabs, so a radio group avoids nested tabs).
3. **Source mark per row.** Mine / Built-in / Built-in, changed, computed by comparing the device entry (with edits) to the built-in layer. Text label in its own column so it works without colour and in high contrast.
4. **Import is checked on the server, applied on the page.** `POST /api/import_notes {config, eds, data, notes}` loads the text with `notes.load_text`, checks it with `notes.check` against the EDS, drops fields equal to the built-in layer, drops `name`, and returns `{changes: {key: entry}, preview: {new, changed, same, skipped}, warnings}`. The page shows the preview in a modal; on **Import** it writes the changes into `S.model.notes[eds]` as one undo step. Imported entries replace the existing entry of the same key field by field (imported fields win, other fields of the existing entry stay). Alternative: write the file directly on the server. Rejected: it would bypass the draft, undo and Save, which every other notes edit goes through.
5. **Export of own notes.** `/api/export_notes` gets `"own": true`, which writes the device document (identity plus filled entries, with edits) as `<eds>.notes.json`; without it the merged export stays as is (`<eds>.merged.notes.json`).
6. **Note buttons removed elsewhere, display kept.** The other lists keep the note text under the object name and value meanings next to values, because that is where the note is useful. Only the editing entry point moves. Commission without a config stays read-only: the view switch and Export work, Add and Import are not shown, and the tab says why.
7. **Add note picker** reuses the PDO entry picker's filter and table style, listing all objects and sub-objects of the EDS with a "has note" mark; choosing one opens `editNote`. After saving the editor, the view switches to My notes if the new note would otherwise be hidden, and the row is focused.

## Risks / Trade-offs

- Users who wrote notes from the PDO picker lose that shortcut. Mitigation: the Notes tab is one click away on the same node, and the picker still shows the note. If this proves slow in use, a later change can add a link that opens the Notes tab at that object.
- Import of a file for a different device revision could add notes for objects that differ in meaning. Mitigation: identity mismatch warning in the preview, and skipped entries listed.
