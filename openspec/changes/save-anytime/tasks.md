## 1. Save

- [ ] 1.1 `server.py`: save writes a draft with errors; the save reply carries the error count
- [ ] 1.2 `app.js`: Save button states (Save / Saved / Saved, N problems), message bar after a save with errors; Allow overlap only affects hand-off
- [ ] 1.3 Update the tests that expect Save disabled with errors

## 2. New config on disk

- [ ] 2.1 `server.py new_config`: write the target's empty config on Create (config folder and editor project `canworks/`)
- [ ] 2.2 New config dialog: errors under the field, field marked and focused, title kept

## 3. Fewer errors in first steps

- [ ] 3.1 Empty master network: one warning, empty state on the tree and Bus page; hand-off steps still refuse it
- [ ] 3.2 New node supervision default (heartbeat 1000 ms, else guarding, else none) with the "set when the node was added" note
- [ ] 3.3 Problem actions: data model, rendering in Problems, undo; supervision problem quick fixes and UI wording

## 4. Hand-off refusals

- [ ] 4.1 Build into CODESYS project and Download for CODESYS refuse with errors (one line, link to Problems)
- [ ] 4.2 Devices: install or update the bridge config refuse with errors

## 5. Checks and docs

- [ ] 5.1 Page tests: save with errors, Create on disk + reload per target, new node without problems, quick fix + undo, hand-off refusals, dialog error placement
- [ ] 5.2 README and docs/configurator.md (save and problems); PC tools minor version bump
