## 1. Add note picker

- [x] 1.1 Row click picks the object and opens the Note editor; remove the Write / Edit column; Object cell holds the row's button with an accessible name.
- [x] 1.2 Keyboard: Down from the search into the list, Up and Down between rows, Up from the first row back to the search, Enter or Space picks, Escape cancels.
- [x] 1.3 Hover and focus tint as in the Object dictionary tab; table fits the dialog with no sideways scroll at 1000 px and long names wrap.

## 2. Notes tab

- [x] 2.1 Row click opens the Note editor when the tab is editable; ignored on a text selection or a click on a button; Note button kept.

## 3. Commission a device

- [x] 3.1 Server: notes block (builtin, device, editable with reason, error) for the EDS files on the Nodes table; editable when the folder of the EDS is writable.
- [x] 3.2 Server: `POST /api/notes/write` applying one change set with the Save rules (skeleton for a new file); `import_notes` allowed in Commission a device; tests.
- [x] 3.3 Page: `commNotesTab` and `notesEditable` use that block, so views, count, Note, Add note…, Import notes… and Export notes (both kinds) work as in a config.
- [x] 3.4 Kept note and import write at once; banner with the file name and Undo; Ctrl+Z undoes the last write; Object dictionary, Parameters and PDO test tabs refresh.
- [x] 3.5 Commissioning log lines for note writes, imports and undo.
- [x] 3.6 Add to a config copies the EDS's notes file when the config has none for that EDS; banner when it is kept.

## 4. Tests and docs

- [x] 4.1 Page tests: pick by row click and by keyboard, no sideways scroll at 1000 px, Notes tab row click, Commission a device add / import / export / undo with the file written, Add to a config with notes (carry and keep); read-only folder and the write endpoint in server tests; axe audit.
- [x] 4.2 Update tests that expected a read-only Commission Notes tab or the picker's Write button.
- [x] 4.3 README.md and `docs/configurator.md`; PC tools 0.75.0.
- [ ] 4.4 CI time: wall and summed job time at or below the main baseline, both numbers in the PR description.
