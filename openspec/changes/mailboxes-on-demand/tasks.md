## 0. Order

- [ ] 0.1 Apply only after `modbus-connections`, `faster-mailboxes` and `add-nodered-blocks` are merged and archived (coordinator says when): rebase on main, rewrite the deltas against the archived text (Function blocks section from faster-mailboxes, Connection kinds and OpenPLC connection bridge settings from modbus-connections, the Node-RED connection and block nodes from add-nodered-blocks), re-validate
- [ ] 0.2 If add-nodered-blocks has not merged when the rest is ready, leave the Node-RED blocks choice out (task 3.4) and say so in the PR

## 1. Bridge

- [ ] 1.1 `bridge_host.cpp` / `mailbox_engine`: count operations started and receivers opened; status JSON `bridge.mailboxes` {operations, receivers_opened} only with mailboxes
- [ ] 1.2 C++ test: counts after one SDO read, one RX_OPEN and a restart's ERROR_ID 8 request

## 2. PC tools

- [ ] 2.1 `mailboxuse.py`: mailbox block table (block → parts), shared by the check, the configurator API and the docs table test; scan of ST POUs and global lists for block instances (comments and strings stripped, `canworks_in`/`canworks_out` left out); tests incl. comments, strings, FB-local instances, arrays of blocks
- [ ] 2.2 Schema + `bridgecheck.py`/`modbusmap.py`: `blocks` on `trust`, `plc`, `nodered`; truST only `none`/`sdo_send`
- [ ] 2.3 `server.py`: check adds the program scan results for an OpenPLC connection (errors per missing part, info when unused); `/api/bridge/map` returns the cost without mailboxes and with the default parts
- [ ] 2.4 `diag.py`: mailboxes line and the unused hint; "no mailboxes"
- [ ] 2.5 Version bump (minor)

## 3. Configurator

- [ ] 3.1 Remove every place that turns the mailboxes on by itself (New config, OpenPLC connection add, target switch)
- [ ] 3.2 Function blocks section: switch label, always-visible Works without / Needs mailboxes (with alternatives), cost as a difference in both states, Who needs them
- [ ] 3.3 Problems: Turn on what the program uses (exact parts, one undo step, places the areas), Turn off the mailboxes
- [ ] 3.4 Connection rows: canworks blocks choice for trust (2 options), plc, nodered (only with block nodes); union into `bridge.mailboxes` in the same undo step; row text with the parts; Out of date on a change
- [ ] 3.5 New editor project: "Install the canworks library in the project" and its hint
- [ ] 3.6 Page tests: new config + OpenPLC has no mailboxes; section in both states; program scan error + fix; unused info + Turn off; truST choice; two connections' union; undo of each

## 4. Examples

- [ ] 4.1 `examples/openplc-modbus` keeps its mailboxes and passes the scan with no mailbox problem; virtual plant stays without
- [ ] 4.2 Integration test still green with the example (mailboxes on), plus a run with mailboxes off (values, CO_NMT, CO_SDO_READ work)

## 5. Docs

- [ ] 5.1 `docs/plc-library.md` With or without the mailboxes: works without, cost table, what can't be done without, alternatives, how they come on
- [ ] 5.2 `docs/modbus-bridge.md` (mailboxes absent by default, the status `mailboxes`, link), `docs/configurator.md` (section, Problems, connection choice, dialog wording)
- [ ] 5.3 README: one sentence (values and bridge blocks as they are; other blocks need the mailboxes, turned on when used); run `tools/deploy/tests/test_readme.py`

## 6. Archive

- [ ] 6.1 `openspec archive mailboxes-on-demand --yes` in the apply PR

## 7. Hardware (Pi, when reachable)

- [ ] 7.1 OpenPLC project on the bench without mailboxes: values, CO_NMT and CO_SDO_READ work; runtime CPU and Modbus requests per poll against the default mailboxes; record in the PR
- [ ] 7.2 Add a CAN_RECEIVE to `main`, Turn on what the program uses, Save, Build: frames arrive; `diag` shows the operations
