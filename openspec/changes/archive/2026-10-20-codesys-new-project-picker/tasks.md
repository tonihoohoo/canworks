## 1. Device repository (Windows PC with CODESYS SP22)

- [x] 1.1 Find where SP22 keeps installed device descriptions and their layout (folder, file names, `DeviceIdentification`/`DeviceInfo` elements, PLC type numbers); record it in design.md and keep a trimmed sample (no vendor names) as a test fixture

## 2. Server

- [x] 2.1 `codesys.run.list_plc_devices(root)`: scan the repository folder, parse identification and name, keep PLC devices, sort by name and newest version; skip unreadable files
- [x] 2.2 `GET /api/codesys/devices[?refresh=1][&project=…]` → `{devices, root, exists}`; cached per server start
- [x] 2.3 `/api/folders?files=.project`: matching files in `entries` with `file: true`
- [x] 2.4 `codesys.run.project_path()` adds `.project`; `cli._codesys` uses it; `MissingProject` failure; `codesys_build` returns GUI wording for it

## 3. Page

- [x] 3.1 `style.css`: one `::placeholder` style (muted, italic) for both themes; CODESYS example placeholders start with "e.g."
- [x] 3.2 `chooseFolder` file mode (`files`, `newName`): files listed after folders, click/Enter picks, New project name + Create here, refusals in the dialog; folder-only callers unchanged
- [x] 3.3 CODESYS page: Browse… next to Project file; field normalised to `.project`; PLC device dropdown with Other…; device field only while the project does not exist, "Existing project" line otherwise
- [x] 3.4 Build on a missing project without a device: create dialog with the dropdown, Create and build sets `codesys.create`, saves and builds; Cancel changes nothing

## 4. Checks

- [x] 4.1 Unit: device scan on the fixture (names, versions, non-PLC left out, broken file skipped), `/api/folders` files mode, `project_path`, `MissingProject` wording
- [x] 4.2 e2e: Browse… picks an existing `.project` (device field hidden); Create here fills a new path; Build on a missing project opens the create dialog and runs the build with the picked device (fake CODESYS runner); placeholder style applied
- [x] 4.3 README CODESYS section and docs/configurator.md, docs/codesys.md: Browse… and the device list; PC tools minor version bump (0.94.0)

## 5. Hardware (Windows PC, CODESYS SP22)

- [x] 5.1 Browse… to a folder, Create here `hwtest`, pick CODESYS Control Win V3 x64 from the list, Build: a new `hwtest.project` with the PLC and the bus, report ok (PASSED 2026-10-20, 0.94.0 on CODESYS 3.5 SP22 Patch 4: list showed the 4 installed PLCs; project created, CANbus, manager and both nodes, built 0 errors 0 warnings)
- [x] 5.2 Build again into the now existing project: device field hidden, project updated, report ok (PASSED: "Existing project" line shown, nodes replaced from the DCFs, saved)
- [x] 5.3 Build with a missing project and the device cleared: create dialog appears, Create and build succeeds (PASSED: `hwtest2` typed without extension became `hwtest2.project`; create dialog listed the PLCs; project created and built)
- [x] 5.4 Found in 5.1: the project file field stayed about 160 px wide beside Browse…, so a path was cut off; the field now takes the row's width (test checks it), and the dialog's New project name block is spaced from the list
