# Design: simplify-start-page

## Context

`renderStart()` in `app.js` draws four `.choice` cards; three set `S.startMode` and retitle the `.browser` section, whose "Open this folder" button calls `startOpen()`, which calls `openFolder(path, mode, isNew, target)`. The server's `State.open(path, mode, new)` already accepts `mode="auto"` and picks project or standalone by `project.json`. `chooseFolder()` is a ready folder dialog (Up, path field, Go, keyboard). `State.new_project()` creates an editor project from a saved standalone config through `editorproject.create`, which needs the editor's `openplc-cli`.

## Decisions

### One Open for both kinds
Open… calls `chooseFolder` and then `openFolder(path, "auto")`. The server answers 404 `no_config` for a folder with neither `project.json` nor `canworks.json` (today it answers that only for `new: false`); the page then asks "This folder has no config. Start a new config here?" with New config… (pre-filled with the folder) and Cancel. The "not an editor project" and "is an editor project" dialogs go, because no card can be wrong any more.

Alternative considered: keep the inline folder browser under two buttons. Rejected: it keeps the page long, keeps Recent below the fold, and duplicates the dialog the EDS library already uses.

### Target first in New config
The target is the one choice that changes the config's shape (top-level `bridge` or `codesys`), so it leads the dialog as three cards with one-line explanations, OpenPLC preselected. The Modbus bridge card says it is the way to Node-RED, HMIs and other Modbus TCP clients, since the Node-RED flow export lives on the bridge page. CODESYS keeps today's behaviour (version 2 config with a `codesys` object).

### Optional editor project for OpenPLC
A new request `POST /api/new` `{path, target, editor_project}` replaces the `new: true` path of `/api/open` for the page. Without `editor_project` it does what `open(path, "standalone", new=True)` and `switch_target` do today, but on the server in one step. With `editor_project` (OpenPLC only) it writes the empty config into a temporary folder, runs `editorproject.create` into `path` (which must not exist yet, as today's New editor project…), and opens `path` as a project. The state gains `openplc_cli` (found or not) so the tick can be disabled with "The OpenPLC Editor's command-line tool was not found on this PC" when it is missing. Task 2.1 checks that an empty config passes `contract.check_config`; if it does not, the request adds no node and relaxes only the "no nodes" check for this call.

The tick defaults on when `openplc_cli` is found, because the editor-project route is the common OpenPLC path and the folder-then-move route stays available by unticking.

### Recent with the target
`State.recent()` entries gain `target` (`targets.target(cfg)` of the folder's config, `null` when unreadable or missing) and keep `mode`. Reading at most `RECENT_MAX` (10) small JSON files when the state is sent is cheap; a missing or broken file shows the row without a target tag instead of failing. Rows show name (last path part), the path in small monospace, the tags, and a relative time from a new `opened` timestamp written by `remember()` (rows without it show no time).

### First run
With an empty Recent, three `.choice` cards take its place and call the same three actions. They go away once anything is in Recent.

### Words
"Standalone config" becomes "config folder" on the start page, the New config dialog and the open/create messages. The mode badge keeps "project …" / "standalone …" for now (it is shown everywhere and in many tests); renaming it is left out.

## Risks / Trade-offs

- Many browser tests open folders by clicking the start cards. They go through a shared helper; updating it plus `test_configurator_page.py` covers most. Tests that click `#start-standalone` directly get the new ids.
- Users who knew the four cards get a different page. The project is not in real use, so no compatibility path.
