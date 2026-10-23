## 0. Before applying

- [x] 0.1 Rebase on main after `remove-openplc-plugin` and `add-bridge-mailboxes` merged; re-validate with OpenSpec 1.14.0; change 3 already gives its mailboxes a restart baseline ending with ERROR_ID 8; keep this change's control block and SDO registers on the same code

## 1. Bridge and library

- [x] 1.1 Restart baseline for the control block and the SDO registers (`bridge_blocks.*`), control result 6, SDO abort 0x08000021; bridge tests for restart with a non-zero counter
- [x] 1.2 ERROR_ID 8 in `CO_NMT`, `CO_SDO_READ`, `CO_SDO_WRITE`; `test/plc_modbus` model case
- [x] 1.3 Client-loss wording in pre-operational/start log lines; bridged SDO requests at DEBUG, aborts and timeouts at INFO
- [x] 1.4 Restart test: the PLC's last NMT request in place after a bridge start sends nothing (bridge host test `openplc_restart_does_not_replay`, no extra CI step)

## 2. PC tools

- [x] 2.1 Scan `main.st` for canworks' located declarations and clashes; Project page warning, Problems warning, switch banner sentence
- [x] 2.2 **Use canworks.\* in main**: backup, remove (an empty `VAR` block stays, as the editor writes it), replace uses outside comments and strings; route and result message
- [x] 2.3 Save enables the `canworks` library in the project and installs it into the editor when missing or older
- [x] 2.4 Switch to OpenPLC through Modbus adds a live list for unnamed CANopen master networks (interface name)
- [x] 2.5 Unit tests (scanner cases, library on save, naming); extend `test_configurator_openplc_modbus_page.py`

## 3. Docs, version, CI

- [x] 3.1 `docs/modbus-bridge.md` (restart baseline, result 6, per-node pre-operational), `docs/plc-library.md` (ERROR_ID 8, retry), `docs/configurator.md` (move button, library on save); README if it describes the switch
- [x] 3.2 Tools minor version bump; CI time recorded in the PR (no new job or test file): #249 CI 223 s wall, 1497 s summed jobs (baseline 360 s and 2352 s)

## 4. Hardware (Linux device with the real node)

- [x] 4.1 Bench copy of a plugin project: switch, Save (library enabled), **Use canworks.\* in main**, Build and upload; values through `canworks.*`, `CO_NODE_LIVE` TRUE for the node (2026-10-23: on main 9bb5dc9 all but `CO_NODE_LIVE` passed (31 declarations moved, library enabled, values read); `CO_NODE_LIVE` was FALSE because `canworks_in` skipped the live list of an unnamed network, fixed in #253 (tools 0.119.1); rerun on main 39f8906: `CO_NODE_LIVE` TRUE for node 23, `canworks.link[21]` 16#107, `canworks.link[26]` 16#8000)
- [x] 4.2 Restart the bridge while the PLC runs with a finished `CO_NMT` start: no NMT frame on the bus after the restart (2026-10-23, main 9bb5dc9: the log says counter 1 was already there and is not run, result 6; the only NMT frames are the bridge's own stop preop, boot reset and node start)
