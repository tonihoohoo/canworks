## 1. Shared dialog and field

- [ ] 1.1 `chooseEds(...)` in `app.js`, from the Add node dialog's list: groups (Matches this device, Built here, In this project, EDS library), product and file name, use counts, "exact revision", replace or keep both, library import on the main button
- [ ] 1.2 Browse… opens the page's file browser (`chooseFolder` with `.eds`, `.dcf` where taken), starting in the last browsed folder, else the EDS library
- [ ] 1.3 Enter / double-click presses the main button; focus to the list (Browse… when empty) and back to the opener on close
- [ ] 1.4 `edsField(...)`: product and file name as text, Choose EDS… / Change EDS…
- [ ] 1.5 `server.py`: take an EDS by path from any browsed folder; `/api/folders` lists `.eds`/`.dcf` files; Commission takes a project EDS by name

## 2. Notes with the EDS

- [ ] 2.1 Import `<eds>.notes.json` next to an EDS taken from a folder (Browse…, library, commissioning folder) when the config has no notes for it; else keep and say Import notes…
- [ ] 2.2 `.datasheet.notes.json` next to it: not imported, message points to Import notes…

## 3. Configure

- [ ] 3.1 Add node dialog on the shared list
- [ ] 3.2 Node General tab: EDS field in place of the dropdown
- [ ] 3.3 Slave device page: EDS field with Built here; remove the dropdown and "Use an EDS file…"

## 4. Commission and Trace

- [ ] 4.1 Add node from EDS…: dialog with the list and the node ID, no file picker first
- [ ] 4.2 The node's EDS field in the Nodes table and node header (Choose EDS… with matches first; Change EDS… with Clear EDS / Remove node)
- [ ] 4.3 Parameters tab, Trace Decoding panel, frame inspector open the node's field dialog; remove their own pickers
- [ ] 4.4 LSS result: best match as text, no dropdown
- [ ] 4.5 Add to config (found devices) and Add to a config…: use the node's EDS; open its dialog first when it has none; no file input

## 5. Simulation

- [ ] 5.1 Extra devices: EDS field, dialog with DCF allowed

## 6. Checks and docs

- [ ] 6.1 Page tests per place: sources listed, pick from each group, Browse… through the file browser with a clash, notes imported with the EDS (and kept when the config has some), Cancel changes nothing, Enter and double-click, focus return; no visible `input[type=file]` for EDS and no EDS dropdown on any view; layout check covers the dialog
- [ ] 6.2 Existing tests updated to the new labels and flows
- [ ] 6.3 README, docs/configurator.md, docs/slave.md; PC tools minor version bump; release notes line
- [ ] 6.4 (optional, real device) Commission walk: scan match preselected, Change EDS…, Trace Choose EDS…, Add to a config…
