## 1. Plan and export folder

- [ ] 1.1 `canworks/codesys/plan.py`: build the plan from the config (networks, network numbers with overrides, manager settings, nodes, identifiers, checks, supervision, channels with `declare` names, `not_carried`)
- [ ] 1.2 `canworks/codesys/export.py`: write the folder (per-network DCFs through `dcfexport.export`, plan, packaged script, README); nothing written on failure
- [ ] 1.3 Golden plan files for `examples/modbus-bridge`, `examples/gantry-cell` and a two-network test config; tests for overrides, unknown network, J1939/slave networks in `not_carried`

## 2. The CODESYS script

- [ ] 2.1 `canworks/codesys/import_canworks.py` (package data): IronPython 2.7 / CPython 3 syntax; IDE mode (`projects.primary`, no save) and command-line mode (open or create, save on success)
- [ ] 2.2 PLC selection, CANbus by network number anywhere under the PLC, manager reuse, highest installed versions, slave-device stop
- [ ] 2.3 Settings by parameter id with name check; struct sub-element writes; skipped settings reported
- [ ] 2.4 Nodes: import DCF, add at once, rename, node ID, optional, identity checks, supervision; re-run replaces same node ID and keeps others
- [ ] 2.5 Channel names through `io_mapping.variable`, matched by direction, index, sub-index; `--codesys-no-variables`
- [ ] 2.6 Build, collect errors and warnings, write `import_report.txt` and show it in the message view
- [ ] 2.7 Stand-in CODESYS API for CI and tests: new project, existing CANbus reuse, two networks, re-run, missing parameter, duplicate variable, no open project
- [ ] 2.8 Decide the unique-FileVersion point from the design (test in CODESYS); keep or drop

## 3. Command line

- [ ] 3.1 `cli.py`: `--export-codesys DIR`, `--codesys-net`, `--codesys-plc`, `--codesys-no-variables`
- [ ] 3.2 `--codesys-import PROJECT` with `--codesys-new`, `--codesys-exe`, `--codesys-profile`: find CODESYS and profile, run headless, print the report, exit code
- [ ] 3.3 Deploy tests (export, overrides, CODESYS not found, report error gives non-zero)

## 4. Configurator

- [ ] 4.1 Server route for the zip and Export > CODESYS menu item; Problems panel on errors
- [ ] 4.2 Page test: download contents, errors shown and nothing downloaded

## 5. Docs

- [ ] 5.1 `docs/codesys.md`: what carries over and what does not, IDE and command-line runs, network numbers on devices with their own CAN interfaces, re-runs, repository note, canworks slave under a CODESYS master (`slave-eds`), PC tools and simulator on a CODESYS-run bus, licences
- [ ] 5.2 `docs/deploy.md`, `docs/configurator.md`, README feature list and docs table
- [ ] 5.3 Bump the PC tools version

## 6. Checks

- [ ] 6.1 Manual check in CODESYS on Windows: IDE run and `--codesys-import` on the example configs, re-run, project builds with 0 errors
- [ ] 6.2 CI time: compare the PR's CI wall and summed job time with the baseline and state both in the PR
- [ ] 6.3 Hardware (does not block): a CODESYS controller or display with CAN runs the imported bus against the simulator or real nodes
