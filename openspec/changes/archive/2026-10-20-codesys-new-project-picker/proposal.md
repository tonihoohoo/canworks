# Proposal

## Why

On Windows with CODESYS, Toni filled in a project file that did not exist yet (`c:\projects\codesystesti`) and pressed **Build into CODESYS project…**. The build failed with `c:\projects\codesystesti does not exist; give --codesys-new TYPE:ID:VERSION to create it`.

The build does pass the new-project device: it reads `codesys.create` from the saved config. The setting was empty. The "PLC device for a new project" field showed its placeholder `4096:0000 0004:3.5.22.40`, and the page has no placeholder styling, so in the dark theme the example looked like a value that was filled in. The Device field next to it (placeholder "the active application's device") looked the same. On top of that:

- the error speaks command-line (`--codesys-new TYPE:ID:VERSION`) to a GUI user;
- a user cannot know a device's TYPE:ID:VERSION without digging in CODESYS's device repository;
- a project name without `.project` is used as typed;
- the Project file is a bare text field, while every other path in the configurator (Open…, New config, EDS library, Add to a config) has the folder dialog.

Usability first: making a new CODESYS project from the configurator should not need any CODESYS knowledge beyond picking the PLC.

## What Changes

- **Placeholders look like placeholders.** One style for every input's placeholder (dimmer and italic), so no default or example reads as a value. Placeholders that are examples, not defaults, start with "e.g." (the CODESYS project file and PLC device fields).
- **Browse… for the CODESYS project file.** The Project file field gets **Browse…**, which opens the existing folder dialog in a file mode: it also lists the folder's `.project` files, a click on one picks it, and a **New project name** field makes a new project in the shown folder. Same Up, drives, typed path and keyboard use as the folder dialog.
- **PLC device from a list.** "PLC device for a new project" becomes a dropdown of the PLC devices installed in CODESYS on this PC, by name and version (for example "CODESYS Control Win V3 x64 3.5.22.40"), read from CODESYS's device repository on disk; "Other (type TYPE:ID:VERSION)…" keeps typing possible, and a value not in the list is shown as typed. The field is shown only while the project file does not exist.
- **Build asks instead of failing.** Build with a project file that does not exist and no PLC device opens a dialog "`<path>` does not exist. Create a new CODESYS project?" with the PLC device dropdown; Create saves `codesys.create` and builds. Cancel changes nothing.
- **`.project` added.** A project file typed or picked without an extension gets `.project` (in the field and in `canworks-deploy --codesys-import`), so the project CODESYS writes is the one the config names.
- **GUI wording.** Build errors about the project are told in the page's terms (fields and buttons), not command-line options.
- PC tools minor version bump.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `canopen-configurator`: CODESYS settings (Browse…, device list, field shown only for a new project, `.project`), CODESYS actions (Build asks to create a missing project); new requirements Placeholder look, CODESYS project file dialog, New project name in the file dialog, PLC devices installed in CODESYS.
- `canopen-deploy`: Import into a CODESYS project from the command line adds `.project` to a project path without an extension.

## Impact

- `tools/deploy/canworks/configurator/static/target.js` (CODESYS page, Build dialog), `app.js` (`chooseFolder` file mode), `style.css` (`::placeholder`).
- `tools/deploy/canworks/configurator/server.py`: `/api/folders?files=.project` lists matching files; new `GET /api/codesys/devices`; build error wording.
- `tools/deploy/canworks/codesys/run.py`: device repository scan (`list_plc_devices`), project path normalising; `cli.py` uses it.
- Tests: unit (device scan on a fake repository folder, `/api/folders` files mode, `.project`), e2e (Browse… picks and creates, Build on a missing project opens the create dialog).
- README: CODESYS section mentions Browse… and the device list.
- Hardware: a check on the Windows PC with CODESYS SP22. No runtime plugin or bridge change.
