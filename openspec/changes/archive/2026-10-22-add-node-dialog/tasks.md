## 1. Dialog

- [x] 1.1 `server.py`: list the config's EDS files (and the library's) with product names; add endpoint takes node ID, name and the default-PDO choice
- [x] 1.2 Add node dialog (EDS list, Browse…, node ID check, name, Map default PDOs); tree action opens it
- [x] 1.3 Default PDO mapping from the EDS (enabled PDOs, no dummies, suggested names and locations; names only without locations)
- [x] 1.4 Open the new node on PDOs (General when nothing mapped), whatever tab was open before

## 2. PDO table

- [x] 2.1 Variable placeholder = the full declared/export name; "declared as" only when the project's name differs
- [x] 2.2 "not mapped to the PLC" mark with Suggest on entries without a location

## 3. EDS check message

- [x] 3.1 Report after adding only when the EDS has findings, in words, in the message bar

## 4. Checks and docs

- [x] 4.1 Page tests: list pick without a file picker, Browse, taken ID, unique name, default PDOs on/off, CODESYS names only, opened tab, clean EDS shows nothing, placeholder and declared-as rule, not-mapped mark + Suggest
- [x] 4.2 README (adding a node) and docs/configurator.md; PC tools minor version bump
