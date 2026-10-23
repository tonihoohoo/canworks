## Why

A project made for the OpenPLC plugin has a `main` program whose `VAR` block declares every canworks value at its plugin location (`rtd_ok : BOOL AT %IX10.0;` …), and its code uses those names. After **Switch to OpenPLC through Modbus** and Save, the same values arrive as `canworks.<name>` members filled by `canworks_in`, but `main` still declares the old located variables. They now read nothing (no plugin fills those locations), so the program builds and runs on stale zeros without any warning. Found on the bench run of change 1 (`add-openplc-modbus-target`). Saving leaves the user's POUs alone by design, so moving `main` over needs its own, explicit step.

## What Changes

- **Detection.** For an OpenPLC project (target OpenPLC through Modbus, inside an editor project) the configurator reads `pous/programs/main.st` and finds the located declarations whose names are members of the `canworks` list: canworks' old plugin declarations.
- **Notice and problem.** The Project page shows a warning that `main` still declares N canworks values at their old plugin locations, which read nothing now, with the button **Use canworks.\* in main**. Problems lists the same as a warning that opens the Project page. The banner after the switch names it too.
- **Move.** The button rewrites `main.st`: it removes those located declarations (and the generated `(* CANopen I/O declared from canworks/canworks.json *)` comment), drops a `VAR` block left empty, and replaces every use of each removed name in the program body with `canworks.<name>`, outside comments and strings and not after a `.`. The old file is kept as `canworks/main-before-move.st`; the message says how many declarations and uses moved, that the copy is there, and that an open OpenPLC Editor must reopen the project before Build.
- **Left as they are.** Located declarations of other names (the user's own hardware I/O), other POUs, and CiA 402 axis declarations and generated axis lines (CiA 402 goes with `remove-openplc-plugin`). A name also declared without a location in `main` is not moved and the message names it.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `canopen-configurator`: the notice, the problem and the move action for an OpenPLC project's `main`.
- `canopen-editor-project`: the one exception to "the user's POUs SHALL NOT change": the explicit move action.

## Impact

- PC tools: `canworks/openplcmodbus.py` (find and move), `configurator/server.py` (route `POST /api/openplc/move-main`, project scan), `static/target.js` (notice and button), checks (problem).
- Tests: unit tests for the declaration scan and the rewrite (comments, strings, qualified names, empty `VAR`, name clash); the existing `test_configurator_openplc_modbus_page.py` gains the notice and button, so no new page test file and no new CI job.
- Docs: `docs/configurator.md` (OpenPLC section), README if the switch text there mentions `main`.
- Order: apply after `remove-openplc-plugin` and `add-bridge-mailboxes`, rebased on them; it touches only the OpenPLC Modbus files those changes keep.
