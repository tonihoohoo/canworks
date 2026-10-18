# Tasks

## 1. Config contract

- [x] 1.1 Tests: target detection (none, `bridge`, `codesys`, both = error); CODESYS config without any `iec_location` passes the check; entry `name` must be an identifier and unique after prefixing; `codesys` and network `codesys` field checks; v1 config with `codesys` must be version 2.
- [x] 1.2 Schema: `codesys` (project, device, create, variables) and network `codesys` (net_id, interface) in v2; entry `name` in v1 `entry`; `iec_location` not required on rx entries when the config has `codesys` (v2 `if`/`then`); `adapter.interface` optional there.
- [x] 1.3 `targets.py`: `target(cfg)`, the relevance table (D5), `unused(cfg)` returning (path, reason) for set values the target does not use; move the `MASTER_NOTES`/`NODE_NOTES` texts here.
- [x] 1.4 `contract.py`: target errors, unused-setting warnings from `targets.unused`, skip location checks and image limits for CODESYS.
- [x] 1.5 Plugin `config.cpp`: refuse a top-level `codesys` with the D8 message (also in the bridge host); config test fixture.

## 2. Declarations and plan

- [x] 2.1 Tests: entry `name` replaces the EDS part of the declaration name (one and several networks); CODESYS config gives channels for every mapped entry; names unchanged for a config that switches from OpenPLC with generated names; `not_carried` equals `targets.unused` for CODESYS.
- [x] 2.2 `declare.declarations()`: entry `name`; entries without location in CODESYS configs.
- [x] 2.3 `codesys/plan.py`: settings from `codesys`/network `codesys` with flag overrides, `net_id`, channels from 2.2, `not_carried` from `targets.py`.
- [x] 2.4 `modbusmap.py`: entry `name` names the register row.

## 3. Deploy tool

- [x] 3.1 Tests: flags override config settings; `--codesys-import` without a project uses `codesys.project` and fails clearly without one; `--runtime`/`--bridge` refuse a CODESYS config before upload.
- [x] 3.2 `cli.py`: `--codesys-import [PROJECT]`, overrides, refusals.

## 4. Configurator server

- [x] 4.1 Tests: model carries the target and the table; `/api/switch_target` for all six directions (names filled, Remove/Keep, `bridge`/`codesys` added and removed, pack from CODESYS); `/api/codesys/build` refuses an unsaved config and reports "CODESYS not found".
- [x] 4.2 `server.py`: table in the model, `/api/switch_target`, `/api/codesys/build` (report, project lock hint), `/api/export_codesys` takes the plan settings from the config.

## 5. Configurator page

- [x] 5.1 Playwright tests per target: the D5 table's UI keys hidden or shown; a set unused value shown marked with Remove; switching dialogs and one-step undo; Variable column; CODESYS header actions; Export > CODESYS gone; start page target choice; Commission offers only the USB adapter in a CODESYS project.
- [x] 5.2 `target.js`: the Project target field (moved from `bridge.js`), switch dialog, `usedBy(key)`; field helpers, tree, menus and start page consult it.
- [x] 5.3 Bus page CODESYS fieldset (network number, CAN interface object) and project CODESYS settings (project file, device, new project device, variable names on/off) on a "CODESYS" page in the tree, like the bridge page.
- [x] 5.4 PDO table: Variable column (placeholder = generated name), Location column per target.
- [x] 5.5 Header: Build into CODESYS project…, Download for CODESYS; remove Export > CODESYS.

## 6. Docs

- [x] 6.1 `docs/codesys.md` (target first, config settings, Build from the page), `docs/configurator.md` (targets and what each hides), `docs/modbus-bridge.md` (what the bridge target hides), `docs/config.md` (`codesys`, entry `name`), README, tour lines, `tools/deploy/README.md`; version bumps and release notes.

## 7. PC check (Windows PC with CODESYS V3.5 SP22)

- [ ] 7.1 From the configurator on the Windows PC: switch an example project to CODESYS (Remove), Build into a new CODESYS project; 0 build errors, named channels, the report shown. Repeat with the project open in the CODESYS window and check the hint.
- [ ] 7.2 Probe headless whether the script can set a remote device's identity checks and the manager's NMT error behaviour; record the result in the PR (mapping them is a follow-up).
