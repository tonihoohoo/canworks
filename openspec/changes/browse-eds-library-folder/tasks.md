## 1. Server

- [ ] 1.1 `list_folders`: `eds` count per entry and for the current folder
- [ ] 1.2 `list_folders` on Windows: drive list for path `""`, drive roots get parent `""`
- [ ] 1.3 `/api/online/settings`: `eds_count` and `eds_count_capped` (walk stops after 5000 entries)
- [ ] 1.4 Unit tests for the counts, the cap and the drive list (drive list with a patched drive probe)

## 2. Page

- [ ] 2.1 `chooseFolder({title, start, note})` dialog in `app.js`/`index.html`: Up, path field with Go, folder list with EDS counts, Cancel and Use this folder; keyboard and focus as in the design
- [ ] 2.2 Nodes tab: replace the text field with the path text, Choose folder…, Clear and the EDS count line; re-match the scanned devices after a change
- [ ] 2.3 Start in the current library folder, its nearest existing parent, or home

## 3. Tests and docs

- [ ] 3.1 Page tests: choose a folder with the mouse and with the keyboard only, Cancel leaves it unchanged, Clear, the count line (some, none, capped), axe and layout fit on the dialog in both themes
- [ ] 3.2 Update existing page tests that type into the old field
- [ ] 3.3 `docs/configurator.md` (Nodes) and README where the library folder is mentioned

## 4. Hardware

- [ ] 4.1 On Windows: choose a library on another drive, scan, and see the devices matched
