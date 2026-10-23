## 0. Before applying

- [ ] 0.1 Rebase on main after `remove-openplc-plugin` and `add-bridge-mailboxes` merged; re-validate with OpenSpec 1.14.0

## 1. PC tools

- [ ] 1.1 `openplcmodbus.py`: find canworks' located declarations in `main.st` (names of the `canworks` list), clashes with non-located declarations
- [ ] 1.2 Rewrite: remove them and the generated comment, drop an empty `VAR` block, replace uses with `canworks.<name>` outside comments and strings and not after `.`, case-insensitive; backup `canworks/main-before-move.st`; atomic write
- [ ] 1.3 Server: project scan reports the count and first locations; `POST /api/openplc/move-main` returns moved declarations, uses, clashes
- [ ] 1.4 Problems warning that opens the Project page
- [ ] 1.5 Project page notice with **Use canworks.\* in main**; switch banner sentence; result message (counts, backup, reopen in editor, Build errors for types)

## 2. Tests and docs

- [ ] 2.1 Unit tests: comments, strings, qualified names, mixed case, empty `VAR` dropped, user hardware I/O kept, clash left and named, backup written
- [ ] 2.2 Extend `test_configurator_openplc_modbus_page.py` (switched plugin project with a located `main`): notice, button, `main.st` after, notice gone
- [ ] 2.3 `docs/configurator.md` OpenPLC section; README if it describes the switch; tools minor version bump
- [ ] 2.4 CI time: no new job or test file; record wall and summed job time in the PR

## 3. Hardware (Linux device with the real node)

- [ ] 3.1 Bench copy of a plugin project: switch, Save, **Use canworks.\* in main**, OpenPLC Editor Build and upload; the program reads and writes node 23's values through `canworks.*`
