# Design

## Context

`codesys_build` in the configurator server runs `cli._codesys` with `--codesys-import` and the saved config. `cli._codesys` creates a new project when the project file does not exist and `codesys.create` (or `--codesys-new`) gives the device. The CODESYS page (`target.js renderCodesys`) has four plain fields. `chooseFolder()` (app.js) is the page-drawn folder dialog used by Open…, New config, the EDS library and Add to a config; it lists folders through `/api/folders` because browser file pickers give no path.

## Decisions

### Placeholder style, not "e.g." everywhere

Most placeholders in the configurator are defaults ("off", the EDS default, the generated name), which is useful and stays. The fix is a single `::placeholder` rule (muted colour, italic) in both themes, plus "e.g." only where the placeholder is an example (`e.g. C:\Projects\cell.project`). The Device field keeps "the active application's device" as a default.

### File mode of the folder dialog, not a second dialog

`chooseFolder({ title, start, note, files: ".project", newName: true })`. With `files` the server listing (`/api/folders?path=…&files=.project`) adds entries `{name, path, file: true}` for files with that extension (case-insensitive); the dialog lists them after the folders with a file icon. Clicking (or Enter on) a file returns its path at once. With `newName` a "New project name" field and a **Create here** button sit under the list; Create here returns `<shown folder>\<name>.project` (extension added when missing; a name with slashes or an existing file is refused in the dialog). Without `files` the dialog behaves exactly as today, so the other callers do not change. Start: the field's path, else its nearest existing parent, else home (existing rule).

### Installed PLC devices from the repository on disk

Listing devices through CODESYS (`device_repository.get_all_devices()` in a headless run) takes about a minute per CODESYS start, too slow for a dropdown. CODESYS keeps installed device descriptions as `*.devdesc.xml` files in its device repository folder (default `%ProgramData%\CODESYS\Devices`; the exact layout for SP22 is checked first, task 1.1). `codesys.run.list_plc_devices(root=None)` walks that folder, parses each description's `DeviceIdentification` (Type, Id, Version) and `DeviceInfo` (Name, Vendor), keeps PLC devices (type 4096, plus any with a PLC-logic connector if 1.1 shows other types), and returns them sorted by name and newest version first. The server serves it at `GET /api/codesys/devices` → `{devices: [{type, id, version, name, vendor}], root}`, cached per server start, `refresh=1` to rescan. Parse errors skip a file; a missing folder gives an empty list.

If 1.1 shows the descriptions are not readable from disk, the fallback is the same endpoint backed by a headless CODESYS listing run on demand with a "Reading CODESYS devices… (about a minute)" note, cached in the configurator settings until CODESYS's version changes.

The dropdown value is stored as today (`codesys.create` = `TYPE:ID:VERSION`), so the config format does not change. "Other…" swaps the dropdown for the text field. Empty list (no CODESYS, or Download-only PC): the text field with the e.g. placeholder, as today.

### When the device field shows

The page asks the server whether the project file exists (`/api/folders` on the file's folder already tells; a small `exists` flag on `GET /api/codesys/devices?project=…` keeps it one call). Existing project: the device field is hidden and a line says "Existing project: canworks adds the bus to it." Missing project: the field shows. A saved `codesys.create` is kept either way (the check does not delete settings).

### Build on a missing project

`codesysBuild()` checks `project exists` before saving. Missing and no `codesys.create`: modal "`<path>` does not exist. Create a new CODESYS project?" with the device dropdown (first PLC device preselected, the newest CODESYS Control Win V3 x64 if present), **Create and build** / **Cancel**. Create sets `codesys.create` (one undo step), saves, builds. The server keeps the CLI check as the safety net, but its message in the configurator becomes "The project file … does not exist. Pick a PLC device for a new project on the CODESYS page." (`codesys_build` maps the CLI `Failure` by kind, not by text: `cli._codesys` raises a `Failure` subclass `MissingProject`).

### `.project`

`codesys.run.project_path(p)` adds `.project` when `p` has no extension; `cli._codesys` uses it before the exists check, and the page normalises the field on change, so the config and the file on disk agree.

## Risks

- Device repository layout differs between CODESYS versions: the scan is tolerant (any `*.devdesc.xml` under the root, depth-limited) and the text field stays as fallback.
- Several CODESYS versions installed: devices are listed by version; the build uses the newest CODESYS (existing `find_codesys`), which may lack a device only an older one has. The dropdown shows only devices whose version the newest CODESYS has, if the repository path is per version (checked in 1.1).
