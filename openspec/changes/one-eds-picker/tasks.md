## 1. Shared dialog and field

- [ ] 1.1 `chooseEds({ title, current, matches, builtHere, dcf, mainLabel, extraFields, extraActions, lint })` in `app.js`, from the Add node dialog's list: groups (Matches this device, Built here, In this project, EDS library), product and file name, use counts, "exact revision", Browse… with replace or keep both, library import on the main button
- [ ] 1.2 Enter / double-click presses the main button; focus to the list (Browse… when empty) and back to the opener on close
- [ ] 1.3 `edsField(...)`: product and file name as text, Choose EDS… / Change EDS…
- [ ] 1.4 `server.py`: Commission takes a project EDS by name where it does not yet

## 2. Configure

- [ ] 2.1 Add node dialog on the shared list (no visible change besides keyboard)
- [ ] 2.2 Node General tab: EDS field in place of the dropdown
- [ ] 2.3 Slave device page: EDS field with Built here; remove the dropdown and "Use an EDS file…"

## 3. Commission and Trace

- [ ] 3.1 Add node from EDS…: dialog with the list and the node ID
- [ ] 3.2 Node without an EDS (Nodes table, node page, Parameters tab): Choose EDS… with the matches first
- [ ] 3.3 Change EDS…: the dialog with Clear EDS / Remove node
- [ ] 3.4 Add to config for found devices: the dialog per device with several or no matches, Add node / Skip
- [ ] 3.5 Add to a config…: EDS field in the dialog when the node has none
- [ ] 3.6 LSS result: EDS field with the best match
- [ ] 3.7 Trace Decoding panel and frame inspector: Choose EDS… / Change EDS…

## 4. Simulation

- [ ] 4.1 Extra devices: EDS field, dialog with DCF allowed

## 5. Checks and docs

- [ ] 5.1 Page tests per place: sources listed, pick from each group, Browse… with a clash, Cancel changes nothing, Enter and double-click, focus return; no `input[type=file]` visible and no EDS dropdown left on any view; layout check covers the dialog
- [ ] 5.2 Existing tests updated to the new labels and flows
- [ ] 5.3 README, docs/configurator.md, docs/slave.md; PC tools minor version bump; release notes line
- [ ] 5.4 (optional, real device) Commission walk: scan match preselected, Change EDS…, Trace Choose EDS…, Add to a config…
