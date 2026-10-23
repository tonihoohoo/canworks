## Why

The hardware rerun of `openplc-modbus-followups` needed new `canworks_in` code from tools 0.119.1 (#253). The config itself had not changed, so Save stayed disabled ("No unsaved changes"), and the only way to rewrite the editor files was a dummy edit: change the SYNC period, save, change it back, save again. The same happens after every tools update that changes what Save generates (the programs, the remote device file, the `canworks` list or the library version), and nothing tells the user that the project still holds the old files.

## What Changes

- **Out-of-date editor files are detected.** For an OpenPLC project the configurator compares what Save would write for the saved config with the files on disk. A file counts as out of date when canworks wrote it last (its stamp matches) and it is missing now or the new text differs; a project canworks never wrote into has nothing out of date. `project.json` counts when its `canworks` list has other members or types than Save writes, or when it does not enable the `canworks` library. The library entry's version does not count: Save installs the tools' own library into the editor anyway, and every tools release would otherwise mark every project.
- **Save is enabled for them.** With the draft equal to the file but the editor files out of date, the Save button reads "Save" and is enabled, with the title "The editor files are from an older canworks; Save writes them again". Saving writes only the editor files; `canworks.json` is unchanged.
- **The Project page says so.** The Project page lists the out-of-date files under the editor files, and Problems lists one warning ("The editor files were made by an older canworks: Save writes them again") that opens the Project page.
- Files changed by someone else keep today's behaviour: Save asks before writing them, naming them.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `canopen-configurator`: the Save button and the OpenPLC Project page know about out-of-date editor files.

## Impact

- `tools/deploy/canworks/openplcmodbus.py`: a read-only `outdated_files(project_dir, cfg, decls, uses)` next to `changed_files`, sharing the text generation with `sync_project`.
- `tools/deploy/canworks/configurator/server.py`: `/api/state` and `openplc_info` carry `outdated`; Problems warning; Save with an unchanged config still runs the editor sync.
- `static/app.js` (`updateSave`), `static/target.js` (Project page list).
- Tests: `tests/test_openplcmodbus.py`, `tests/test_configurator_bridge.py`, `tests/test_configurator_openplc_modbus_page.py` (existing files, no new CI job).
- Docs: `docs/configurator.md`.
- Tools minor version bump.
