## Why

In Commission a device, **Add to a config…** on a node's page opens the chosen config folder and then fails with "only EDS files in the project's canopen folder or the EDS library can be used". The config opens with no node added.

It happens whenever the node already has an EDS in Commission that is not an absolute path in the EDS library:

- the node came from **Add node from EDS…**, or its EDS was picked on its page, or in Trace: the EDS is an unsaved import of the Commission session, known only by its bare name (`fixed-io.eds`);
- the scan matched an EDS in the Commission scratch folder.

`addToConfig()` (`static/commission.js`) calls `/api/open` first, which clears the session's unsaved EDS imports, and then `addScannedNode()` posts the old name to `/api/online/use_eds`. `_use_eds()` (`server.py`) resolves the bare name against the process's working folder, finds it outside the new config's canopen folder and the library, and refuses with 403. A scratch-folder path is refused the same way because the new config's folder is now the only project root.

The existing test only covers a node with no EDS, where the dialog asks for the file, so this path was never exercised.

## What Changes

- **The EDS travels with the device.** `/api/open` takes an optional `carry_eds`: the node's EDS as Commission knows it (an unsaved import's name, a file in the Commission folder, or a file in the EDS library). The server reads its bytes **before** switching folders and, after the folder opens, imports them into the new config as an unsaved EDS, as an EDS import would (same file already there: used as it is; a different file with that name: kept both under a new name). The answer carries the import result, and the page adds the node with it.
- **A failure leaves the page where it was.** An EDS that cannot be read is refused before the folder opens, so the user stays in Commission with the log and connection intact, and the banner says which EDS could not be carried and why.
- **`use_eds` accepts the session's own unsaved imports.** `/api/online/use_eds` with the name of an EDS imported in this session and not saved yet uses it as it is, as `params.py` already does for the object dictionary view.
- **Path checks compare case-insensitively where the file system does.** The root checks in `_use_eds()` and `params.py` compare `os.path.normcase` of both sides, so a library folder typed with a different drive-letter or folder case on Windows is still recognised.
- Tools version 0.74.0 → 0.74.1.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `canopen-configurator`: new requirement "Device EDS carried into a config" under Commission a device.

## Impact

- `tools/deploy/canworks/configurator/server.py` (`/api/open` `carry_eds`, `_use_eds`), `params.py` (normcase), `static/commission.js` (`addToConfig`), `static/app.js` (`addScannedNode` takes an import result).
- Tests: `test_configurator_commissioning_page.py` (Add node from EDS… then Add to a config…; scan match in the library; carry failure stays in Commission), `test_configurator_commissioning.py` (API: `carry_eds` with a pending name, a Commission folder file, a library file, an outside path refused before opening).
- No config format, plugin or runtime change. README: no change (no new feature, the documented one now works).
