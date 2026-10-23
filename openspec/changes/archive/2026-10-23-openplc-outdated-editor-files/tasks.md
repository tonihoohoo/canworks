## 1. Detection

- [x] 1.1 `openplcmodbus.outdated_files`: own files missing, or stamped by canworks and different from what Save would write now; a file changed by someone else is not "outdated" (it stays with `changed_files`)
- [x] 1.2 `project.json` counts as outdated when its `canworks` list members or types differ from Save's, or its library entry is older; Save then writes the current library version
- [x] 1.3 Unit tests: unchanged, new tools text, missing file, hand-edited file, older library

## 2. Configurator

- [x] 2.1 `/api/state` and `openplc_info` carry `outdated` for an OpenPLC project (saved config only; standalone folders never)
- [x] 2.2 Problems warning opening the Project page; Project page list under the editor files
- [x] 2.3 `updateSave`: enabled with the title when the draft is clean and `outdated` is not empty; Save with a clean draft writes the editor files and library only, then refreshes `outdated`
- [x] 2.4 Server and page tests in the existing OpenPLC test files

## 3. Docs, version, CI

- [x] 3.1 `docs/configurator.md` (Save after a tools update)
- [x] 3.2 Tools minor version bump; CI time recorded in the PR (no new job or test file)

## 4. Hardware (Linux device with the real node)

- [ ] 4.1 On the bench copy of the OpenPLC project, after a tools update that changes `canworks_in`: the Project page lists it, Save is enabled without an edit, Save rewrites it and the PLC still builds and runs
