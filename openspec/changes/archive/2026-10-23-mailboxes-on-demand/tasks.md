## 0. Order

- [x] 0.1 Apply only after `modbus-connections`, `faster-mailboxes` and `add-nodered-blocks` are merged and archived (coordinator says when): rebase on main, rewrite the deltas against the archived text (Function blocks section from faster-mailboxes, Connection kinds and OpenPLC connection bridge settings from modbus-connections, the Node-RED connection and block nodes from add-nodered-blocks), re-validate
- [x] 0.2 If add-nodered-blocks has not merged when the rest is ready, leave the Node-RED blocks choice out (task 3.4) and say so in the PR (it merged: Node-RED has the choice without the PLC link)

## 1. Bridge

- [x] 1.1 `bridge_host.cpp` / `mailbox_engine`: count operations started and receivers opened; status JSON `bridge.mailboxes` {operations, receivers_opened} only with mailboxes
- [x] 1.2 C++ test: counts after one SDO read, one RX_OPEN and a restart's ERROR_ID 8 request

## 2. PC tools

- [x] 2.1 `mailboxuse.py`: mailbox block table (block → parts), shared by the check, the configurator API and the docs table test; scan of ST POUs and global lists for block instances (comments and strings stripped, `canworks_in`/`canworks_out` left out); tests incl. comments, strings, FB-local instances, arrays of blocks
- [x] 2.2 Schema + `bridgecheck.py`: `blocks` on `trust`, `plc`, `nodered`; truST only `none`/`sdo_send`
- [x] 2.3 `server.py`: check adds the program scan results for an OpenPLC connection (errors per missing part, info when unused); `/api/bridge/map` returns the cost without mailboxes and with the default parts
- [x] 2.4 `diag.py`: mailboxes line and the unused hint; "no mailboxes"
- [x] 2.5 Version bump (minor, 0.128.0)

## 3. Configurator

- [x] 3.1 Remove every place that turns the mailboxes on by itself (New config, OpenPLC connection add, target switch)
- [x] 3.2 Function blocks section: switch label, always-visible Works without / Needs mailboxes (with alternatives), cost as a difference in both states, Who needs them
- [x] 3.3 Problems: Turn on what the program uses (exact parts, one undo step, places the areas), Turn off the mailboxes
- [x] 3.4 Connection rows: canworks blocks choice for trust (2 options), plc, nodered (only with block nodes); union into `bridge.mailboxes` in the same undo step; row text with the parts; Out of date on a change
- [x] 3.5 New editor project: "Install the canworks library in the project" and its hint
- [x] 3.6 Page tests: new config + OpenPLC has no mailboxes; section in both states; program scan error + fix; unused info + Turn off; truST choice; two connections' union; undo of each

## 4. Examples

- [x] 4.1 `examples/openplc-modbus` keeps its mailboxes and passes the scan with no mailbox problem; virtual plant stays without
- [x] 4.2 Integration test still green with the example (mailboxes on, unchanged); the run with mailboxes off (values, CO_NMT, CO_SDO_READ) moves to HW 7.1 so CI time does not grow

## 5. Docs

- [x] 5.1 `docs/plc-library.md` With or without the mailboxes: works without, cost table, what can't be done without, alternatives, how they come on
- [x] 5.2 `docs/modbus-bridge.md` (mailboxes absent by default, the status `mailboxes`, link), `docs/configurator.md` (section, Problems, connection choice, dialog wording) 
- [x] 5.3 README: one sentence (values and bridge blocks as they are; other blocks need the mailboxes, turned on when used); run `tools/deploy/tests/test_readme.py`

## 6. Archive

- [x] 6.1 `openspec archive mailboxes-on-demand --yes` in the apply PR

## 7. Hardware (Pi, when reachable)

- [x] 7.1 OpenPLC project on the bench without mailboxes: values, CO_NMT and CO_SDO_READ work; runtime CPU and Modbus requests per poll against the default mailboxes; record in the PR (2026-10-23, Pi 5 bench, tools 0.128.2: Turn off the mailboxes offered for a main with values, CO_NMT and CO_SDO_READ only; CO_SDO_READ 0x1018:1 ok, CO_NMT stop/start 5→4→5 ERROR_ID 0. Requests per poll / OpenPLC CPU / bridge CPU: defaults 7 / 31 % / 2.2 %, none 5 / 9.1 % / 2.1 %, request + receive 6 / 27-29 % / 2.5 %)
- [x] 7.2 Add a CAN_RECEIVE to `main`, Turn on what the program uses, Save, Build: frames arrive; `diag` shows the operations (2026-10-23: the fix set exactly requests 1 + receive; CAN_RECEIVE on the node's heartbeat counted about 1 frame/s; diag "mailboxes: 1 operation, 1 receiver opened since start"; ERROR_ID 20 once in the scans before canworks.ok, then normal)
