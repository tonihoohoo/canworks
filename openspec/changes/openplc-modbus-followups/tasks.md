## 0. Before applying

- [ ] 0.1 Rebase on main after `remove-openplc-plugin` and `add-bridge-mailboxes` merged; re-validate with OpenSpec 1.14.0; change 3 already gives its mailboxes a restart baseline ending with ERROR_ID 8; keep this change's control block and SDO registers on the same code

## 1. Bridge and library

- [ ] 1.1 Restart baseline for the control block and the SDO registers (`bridge_blocks.*`), control result 6, SDO abort 0x08000022; bridge tests for restart with a non-zero counter
- [ ] 1.2 ERROR_ID 8 in `CO_NMT`, `CO_SDO_READ`, `CO_SDO_WRITE`; `test/plc_modbus` model case
- [ ] 1.3 Client-loss wording in pre-operational/start log lines; bridged SDO requests at DEBUG, aborts and timeouts at INFO
- [ ] 1.4 `test/openplc_modbus/run.py`: bridge restart with the PLC's last NMT request in place sends nothing

## 2. PC tools

- [ ] 2.1 Scan `main.st` for canworks' located declarations and clashes; Project page warning, Problems warning, switch banner sentence
- [ ] 2.2 **Use canworks.\* in main**: backup, remove, drop empty `VAR`, replace uses outside comments and strings; route and result message
- [ ] 2.3 Save enables the `canworks` library in the project and installs it into the editor when missing or older
- [ ] 2.4 Switch to OpenPLC through Modbus names unnamed CANopen master networks; live list per network
- [ ] 2.5 Unit tests (scanner cases, library on save, naming); extend `test_configurator_openplc_modbus_page.py`

## 3. Docs, version, CI

- [ ] 3.1 `docs/modbus-bridge.md` (restart baseline, result 6, per-node pre-operational), `docs/plc-library.md` (ERROR_ID 8, retry), `docs/configurator.md` (move button, library on save); README if it describes the switch
- [ ] 3.2 Tools minor version bump; CI time recorded in the PR (no new job or test file)

## 4. Hardware (Linux device with the real node)

- [ ] 4.1 Bench copy of a plugin project: switch, Save (library enabled), **Use canworks.\* in main**, Build and upload; values through `canworks.*`, `CO_NODE_LIVE` TRUE for the node
- [ ] 4.2 Restart the bridge while the PLC runs with a finished `CO_NMT` start: no NMT frame on the bus after the restart
