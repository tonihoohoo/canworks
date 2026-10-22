# Proposal

## Why

On a Windows PC, New config… with "Also create an OpenPLC Editor project" failed with
`[WinError 5] Access is denied: '...\devices\configuration.json.tmp' -> '...\devices\configuration.json'`,
and the new project folder was removed. Before the error, a Command Prompt window opened and stayed on screen for about 10 seconds.

- After `openplc-cli create`, the configurator rewrites the project's `devices/configuration.json` with a temporary file and `os.replace`, with no retry. On Windows that rename fails with error 5 while another program has the new file open: antivirus scanning a just-written file, the search indexer, or a sync client. The tools already have `userdirs.replace_file`, which retries for about a second, but this write does not use it. Neither do most other atomic writes, including the configurator's config Save.
- The configurator runs without a console. On Windows `openplc-cli` is a `.cmd` shim, so starting it opens a new visible console window.
- New config… with the editor-project tick (the default when `openplc-cli` is found) refuses any folder that already exists, even an empty one. `openplc-cli create --force` can create a project in an existing folder.
- When creation fails, the code removes the whole project folder. That is only safe for a folder that creation made itself.

The same 10 steps did not fail on the bench Windows PC. The fix doesn't depend on which program held the file.

## What Changes

- **Atomic writes survive short locks on Windows.** Every write done through a temporary file and a rename goes through one helper. On Windows it retries for up to about 5 s, waiting a little longer each time. It covers the editor project's files, the config Save, `canworks/` files, `simulation.json`, the library and the local runtime files. When the rename still fails, the message says that another program (often antivirus or a sync client) kept the file open, names the file, and says to try again.
- **A new project's own files are written in place when the swap stays locked.** `devices/configuration.json` and `pous/programs/main.st` of a project that is being created are written over directly when the rename keeps failing. Nothing else has read them yet, and a failure removes them anyway.
- **No console window.** On Windows, `openplc-cli` runs with no window (`CREATE_NO_WINDOW`, stdin closed). The New config and New editor project dialogs show "Creating the editor project…" while it runs.
- **An existing folder can become a project.** New config… and New editor project… accept an existing folder that has no `project.json`, `canworks.json` or `canworks/`, and none of the files the editor writes (`devices/configuration.json`, `devices/pin-mapping.json`, `pous/programs/main.st`). The configurator then runs `openplc-cli create` with `--force`. Other files in the folder are left alone. A folder with any of those files is still refused, naming the file, and the existing offers to open a project or config stay.
- **Failure removes only what creation wrote.** When creation fails, a folder that creation made is removed as before. In an existing folder, only the files and empty folders the editor and canworks added are removed, so the user's own files stay.
- The Name hint in New config… says that an existing empty folder is fine.

## Capabilities

### Modified Capabilities

- `canopen-editor-project`: "Never overwrite" allows an existing folder without editor or canworks files; "Project files" adds the hidden console and the write retry.
- `canopen-configurator`: "Folders the configurator cannot use" (New config into an existing folder; saving while another program holds the file); "Target of a new config" (progress while the editor project is created).

## Impact

- `tools/deploy/canworks/userdirs.py` (`replace_file`: longer backoff, an in-place fallback option, a clearer error), and every writer that now calls it: `editorproject.py`, `configurator/server.py`, `project.py`, `plclibrary.py`, `configurator/simulation.py`, `localruntime.py`, `configurator/transmit.py`, `cli.py`.
- `editorproject.create`: existing-folder rules, `--force`, `creationflags`, rollback of only what it wrote.
- `configurator/static/app.js`: progress text and the Name hint.
- README and `docs/configurator.md`: New config into an existing folder.
- No config format change.
