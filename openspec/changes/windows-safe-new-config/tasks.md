## 1. Writes that survive short locks

- [ ] 1.1 `userdirs.replace_file`: backoff up to about 5 s on Windows, `in_place` fallback, `FileLockedError` with the plain-words message
- [ ] 1.2 Route every temporary-file-and-rename write through it (editor project, config Save, `canworks/` files, simulation, library, local runtime, transmit lists, gateway file)
- [ ] 1.3 Tests: simulated `PermissionError` for N tries then success; deadline then `FileLockedError` with the `.tmp` removed; `in_place` writes the content

## 2. Editor project creation

- [ ] 2.1 `openplc-cli` runs with `CREATE_NO_WINDOW` and stdin closed on Windows
- [ ] 2.2 Existing folder: refuse on `project.json`, `canworks.json`, `canworks/` or an editor file (naming it); otherwise run with `--force`
- [ ] 2.3 Rollback: remove a folder that creation made; in an existing folder, remove only what was added
- [ ] 2.4 `_patch` uses `replace_file(..., in_place=True)`
- [ ] 2.5 Tests with a fake `openplc-cli`: existing empty folder, folder with a user file (kept after a forced failure), folder with `devices/configuration.json` refused, and `--force` passed only for an existing folder

## 3. Configurator

- [ ] 3.1 New config… and New editor project…: "Creating the editor project…" while it runs; Name hint mentions existing empty folders
- [ ] 3.2 Page test: New config with the editor-project tick into an existing empty folder opens it as a project
- [ ] 3.3 README and `docs/configurator.md`

## 4. Windows checks (hand or Remote Control)

- [ ] 4.1 New config with an editor project on the bench Windows PC: no console window appears, the project opens
- [ ] 4.2 Same into an existing empty folder and into a folder with one unrelated file (kept)
- [ ] 4.3 On the PC where the error was seen: New config with an editor project succeeds, or the message names the file and the held-open reason
