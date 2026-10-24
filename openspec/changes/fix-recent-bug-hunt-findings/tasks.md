# Tasks

Finding IDs refer to the table in design.md. Each fix starts with a test that fails on main; a finding whose test cannot be made to fail is dropped with a note in the PR. Repro scripts from the bug hunt seed the tests.

## 1. Bridge

- [ ] 1.1 BRIDGE-1: no-op SIGUSR1 handler in `bridge_main.cpp` and `test/canopen_host` before any network starts; `upload_test.py` case with two CANopen networks: SIGTERM exit 0, both stop NMTs, no run marker; upload applied, no `.canworks-upload` left; a case with the first network's interface lost and a later write.
- [ ] 1.2 BRIDGE-2: request mailbox baseline after `client_wrote()` of the request words; test with a client rewriting counter 7 across a restart (ERROR_ID 8, no SDO), then counter 8 runs.
- [ ] 1.3 BRIDGE-4: idle ends receivers, cyclic jobs and mailbox operations with ERROR_ID 8 and log reason "idle"; test with keepalives written during idle, no "stopped calling" line.
- [ ] 1.4 BRIDGE-6: queued SDO and CAN send operations dropped on cancel; test with a queued SDO write and the watchdog; docs/modbus-bridge.md says what cancelled means.
- [ ] 1.5 BRIDGE-7: `receive`/`cyclic_jobs` without a request mailbox refused in `config.cpp` and `bridgecheck.py`; parity corpus entry; the Function blocks controls keep requests ≥ 1 while either is on.
- [ ] 1.6 BRIDGE-5: count reads of the network info and cyclic table areas as mailbox use; diag text; test.
- [ ] 1.7 BRIDGE-9: call `end_network` on a CANopen session restart; test with an interface bounce and receivers on two networks.
- [ ] 1.8 NODERED-7 (bridge side): function 43/14 Read Device Identification with objects 0, 1, 2 and 0x80 (map hash); other MEI types exception 1; test; docs/modbus-bridge.md function list.
- [ ] 1.9 BRIDGE-8: delete `tools/deploy/OUT.csv`; ignore `OUT.*` in tools/deploy.

## 2. Node-RED package

- [ ] 2.1 NODERED-1: close orphaned receiver slots after `_seed` and on Deploy (`stop()` waits up to 500 ms for queued closes); retry ERROR_ID 5 once after the cleanup; tests with 16 reconnects and repeated Deploys against the fake bridge and `test/nodered/run.py`.
- [ ] 2.2 NODERED-2: form value wins over `msg.payload` for every job node; test with an inject timestamp on SDO write (2, 4 and 8 bytes).
- [ ] 2.3 NODERED-3: `Cyclic.close` sends the stop for the captured slot; a reconnect takes the old slot over or stops it first; ERROR_ID 5 retried; test with `cyclic_jobs: 1`.
- [ ] 2.4 NODERED-4: outputs set since the last confirmed write are written again after `_seed`; test with a stalled bridge.
- [ ] 2.5 NODERED-5: `_guard` ends jobs at once with ERROR_ID 21 while writes are refused; test.
- [ ] 2.6 NODERED-6: receive fetches at the head of the mailbox wait queue; test with a busy single mailbox.
- [ ] 2.7 NODERED-7: read device identification at connect, refuse writes and jobs on a map hash mismatch with the node status; warning only when the bridge answers exception 1; test.
- [ ] 2.8 NODERED-8..10: ERROR_ID 10 with no J1939 network (4 for CANopen); J1939 source 0-253; default port 502; receiver-specific error list in the emcy help; `isFinite` for REAL; use `sdoTimeoutMs` in mailbox SDO jobs; tests; docs/node-red.md.

## 3. PLC programs and exports

- [x] 3.1 BRIDGE-3, EXPORTS-4, EXPORTS-5: mailbox scan for any `ARRAY[...] OF` bounds and dimensions (constants from the project), namespaced types, user FB instances (nested), non-ST POU files; unknown count gives the maximum and no Turn off; tests in `test_mailboxuse`.
- [x] 3.2 EXPORTS-1: `mailbox_items` adds the connections' `choice_parts` before the "nothing needs them" warning; test with OpenPLC plus truST blocks.
- [x] 3.3 EXPORTS-2: compute the trimmed truST map before offering the trim; refusal text with the register count and the canworks blocks None fix; test with virtual-plant.
- [x] 3.4 EXPORTS-3: bit channels declared as BOOL at the map row's bit in bridge configs; `canworks_in` reads, `canworks_out` ORs into the entry's word; OpenPLC, truST, generic PLCopen and the ST map export; STruC++ test in `test/plc_modbus`; docs/plc-library.md.
- [x] 3.5 EXPORTS-6: generic dialect with VAR_EXTERNAL `canworks` and the TC6 2.01 namespace; validate against the TC6 2.01 schema in the test; check whether truST takes the same file and use it there too if it does.
- [x] 3.6 EXPORTS-7: CODESYS build names the CAN bus object after the network; import takes the name from it (interface when it is the default name); round trip test with one network.
- [x] 3.7 EXPORTS-8: "nothing was uploaded" only for commands that upload; test.

## 4. Configurator and Devices

- [ ] 4.1 UI-1: `device_networks` leaves out simulated networks; test of the adapter row with a simulated can0 network.
- [ ] 4.2 UI-2: writer warning for any second connection with `writes` next to a PLC link; Add dialog leaves Writes off then; tests.
- [ ] 4.3 UI-3: connection Download refused while the check has an error on that connection or on `bridge.listen` for it; README names the listen address for non-loopback clients; page test.
- [ ] 4.4 UI-4: Start and Update confirmations name an active other instance, Stop A and start B as main action, port and interface clash warnings; page test with the fake SSH device.
- [ ] 4.5 UI-5: finished job text from the job's own instance; page test switching projects.
- [ ] 4.6 UI-6, UI-7: Check now keeps the menu open, shows the result there and in the banner, disabled while the check is off; page test.
- [ ] 4.7 UI-8, UI-12, UI-15 (Devices): sudo field layout, device list above the details below 1000 px, plural, user name case, Actions menu names, Remote link row reason, refreshed checked time; page tests at 800 px.
- [ ] 4.8 UI-9: New editor project disabled without openplc-cli; page test.
- [ ] 4.9 UI-10: address required in Add connection, 127.0.0.1 prefilled for Node-RED and HMI; check message "Give the address of NAME"; page test.
- [ ] 4.10 UI-11: CODESYS import clash reason and role names; test.
- [ ] 4.11 UI-13: header chip shortens the target before the project name; layout test.
- [ ] 4.12 UI-14: a 403 session answer shows the restarted notice and stops polling; page test.
- [ ] 4.13 UI-15 (rest): mailboxes "Off by default" sentence, "in Commission" Problems line.
- [ ] 4.14 DOCS-1: Add OpenPLC dialog and banner texts; DOCS-2: "Update declarations" replaced by Save in the bridge page notice and the generated file headers.

## 5. Installers and updates

- [ ] 5.1 INSTALLERS-1: download job scripts to a file and run it, also in `install-bridge.sh --ssh` and `install-bridge.ps1`; test with a 404 curl stand-in (job ends failed with the download message).
- [ ] 5.2 INSTALLERS-2: job options from the probe (link installed, its instance, discovery advertised); Options box shown open when they differ; tests.
- [ ] 5.3 INSTALLERS-3: `install-link.sh` reads `diagnostics.port` from `--config`; test with port 7541.
- [ ] 5.4 INSTALLERS-4: `remove()` forgets the running job; probe clears inactive jobs; test.
- [ ] 5.5 INSTALLERS-5: the re-check waits for a running check; test.
- [ ] 5.6 INSTALLERS-6: probe and plan compare `name sha256` of every uploaded file; test with an edited EDS.
- [ ] 5.7 INSTALLERS-7: probe exit and step parsed as numbers; test.

## 6. Docs and specs

- [ ] 6.1 DOCS-2: docs/plc-library.md and specs wording (MODIFIED deltas in this change).
- [ ] 6.2 DOCS-3: remove `drive-input` from docs/diagnostics.md, docs/simulator.md and docs/configurator.md.
- [ ] 6.3 DOCS-4, DOCS-5, DOCS-6: README runtime and Devices text, release-notes template, tools/deploy/README.md, docs/install-pc.md.
- [ ] 6.4 DOCS-7: canworks-diag help and docs/local-runtime.md say top-level `diagnostics`.
- [ ] 6.5 DOCS-9, DOCS-10: j1939.md anchor and duplicate paragraph; examples/pdo-link/README.md command.
- [ ] 6.6 DOCS-11: SECURITY.md, schema v2 descriptions (both copies), canworks-config help, `_lely_dcf/README.md`, declare.py comment, docs/simulator.md expression example.
- [ ] 6.7 DOCS-8, DOCS-12: spec scenarios without `--runtime` and `--host` (MODIFIED deltas in this change).
- [ ] 6.8 DOCS-13: extend `test_doc_references` with anchors and per-subcommand options over every doc page, SECURITY.md, tools/deploy/README.md, the release notes template and example and config READMEs.
- [ ] 6.9 README.md and docs/modbus-bridge.md, docs/node-red.md, docs/devices.md for the behaviour changes above.

## 7. CI

- [ ] 7.1 Multi-network stop and upload test in the bridge job; new page tests in `.github/ci/page-test-times.json`; CI time against main in the PR (path filters keep small changes as they are).

## 8. Hardware and desktop checks

- [ ] 8.1 Bench device: a config with the real CANopen network and a second, simulated network; `systemctl stop` exits cleanly, the real node gets its `on_plc_stop` NMT, the next start reports a clean stop; a config upload applies.
- [ ] 8.2 Bench device: with the same config, take the real interface down and up while a client writes outputs of the simulated network; the bridge keeps running.
- [ ] 8.3 Mac: the configurator in Safari: header menus (the #282 fix), Settings → Check now, Devices at a narrow window.
- [ ] 8.4 Node-RED on the bench device: a flow with an EMCY receiver deployed five times, the bridge's receiver count stays at the flow's receivers.
