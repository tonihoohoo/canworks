## 1. Server

- [ ] 1.1 `notes.py`: helper for the filled device entries of an EDS (any field other than `name`), and one that drops fields equal to the built-in layer.
- [ ] 1.2 `POST /api/import_notes`: load and schema-check the text, check against the EDS, identity mismatch warning, return changes and preview (new, changed, same, skipped).
- [ ] 1.3 `POST /api/export_notes` with `own: true`: the device document with filled entries and unsaved edits.
- [ ] 1.4 Server tests for import (own file, merged export, wrong format, other EDS identity, unknown objects) and own export.

## 2. Notes tab

- [ ] 2.1 View switch My notes / All notes / All objects, My notes default, kept for the page session; count of own notes on the tab label.
- [ ] 2.2 Source column (Mine, Built-in, Built-in, changed) and empty states with actions.
- [ ] 2.3 Toolbar left-aligned: search, Add note…, Import notes…, Export notes… (My notes, Merged with built-in).
- [ ] 2.4 Add note picker over all objects and sub-objects, then the Note editor; switch view and focus the new row.
- [ ] 2.5 Import preview modal, applied as one undoable draft edit.
- [ ] 2.6 Commission Notes tab: read-only without a config (no Add or Import, reason shown), Export kept.

## 3. Other lists

- [ ] 3.1 Remove the Note buttons from the PDO entry picker, the startup SDO rows and the online object dictionary; keep their note text, units and meanings.

## 4. Tests and docs

- [ ] 4.1 Page tests: My notes default and source marks, add a note to an object without one, import with preview and undo, export both kinds, keyboard only and axe audit in both themes.
- [ ] 4.2 Update tests that used the removed Note buttons.
- [ ] 4.3 README.md and `docs/configurator.md`; PC tools version 0.63.0.
- [ ] 4.4 CI time: wall and summed job time at or below the main baseline, both numbers in the PR description.

## 5. Found while applying

- [ ] 5.1 Commission a device without a config: the Notes tab read the page's config EDS list only, so it was always empty; it now shows the notes the object dictionary is read with (read-only, exportable).
