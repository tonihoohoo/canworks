## 0. Order

- [ ] 0.1 Apply only after `add-openplc-modbus-target` (change 1) and `remove-openplc-plugin` (change 2) are merged and archived; rebase on main and rewrite the deltas of `plc-library`, `canopen-editor-project` and `modbus-bridge-map` against the archived text (the `LINK` bound and the library list become MODIFIED requirements there)

## 1. Spikes (before the code)

- [ ] 1.1 STruC++: a block with an in-out `ARRAY[0..1023] OF WORD`, 40 instances in one program, scan time and generated code size; the test runner's in-out copy-back note of `test/plc_modbus`
- [ ] 1.2 OpenPLC Editor: a global `ARRAY[0..1023] OF WORD` in the `canworks` list loads, builds and is kept on save
- [ ] 1.3 Runtime v4.3.1 Modbus master with the extra groups (72-register write, 72- and 120-register reads): one connection, groups sent in file order, all within one poll at 10 ms
- [ ] 1.4 CODESYS (if a copy is available on the Windows PC): import a PLCopen XML file with one block and an in-out word array; if not available, leave 8.5 open and say so in the PR

## 2. Bridge

- [ ] 2.1 Engine services as change 2 left them: SDO queue, EMCY history, raw sends, cyclic jobs, receivers, J1939 sends, requests, receivers, DM store usable from the bridge without the C ABI tables; restore from git history what change 2 deleted
- [ ] 2.2 `config.cpp`: `bridge.mailboxes` (counts, locations, defaults, placement after the bridge blocks in an `openplc` config, overlap refusals); log the ranges at start
- [ ] 2.3 `mailboxes.{h,cpp}`: request mailboxes (handshake, one operation per mailbox, parallel mailboxes, staging and result buffers, all operations of design Decision 2 with family ERROR_IDs)
- [ ] 2.4 Receive mailbox: receivers (CAN, J1939, EMCY), FIFOs and drops, batches, acknowledgement, long J1939 messages held for RX_FETCH, the 1 s / 5 s stall rule, 32-receiver limit
- [ ] 2.5 Network info blocks (first 8 networks, every 100 ms) and the cyclic job table with keepalive
- [ ] 2.6 Link-state hooks in `bridge_host.cpp`: stopped, mismatch, watchdog and network restart end operations, jobs and receivers; one log line
- [ ] 2.7 Map hash: one line per mailbox block (same vectors in C++ and Python)
- [ ] 2.8 `test/bridge/`: operations, chunks, FIFO burst and drop, stall, link stop, cyclic timing at 5 ms period with a 10 ms poll

## 3. PC tools

- [ ] 3.1 `modbusmap.py`: mailbox items, Pack for Modbus, hash lines, request count; never cut a mailbox or info block
- [ ] 3.2 `openplcmodbus.py`: groups for the mailbox areas, `canworks.link` as `ARRAY[0..1023] OF WORD`, copy code for the new `LINK` places, mailbox flags, `CW_LINK_SERVICE` call
- [ ] 3.3 `--export-modbus-map OUT.st`: `canworks_in`/`canworks_out` for other PLCs over the channel variables
- [ ] 3.4 `bridgecheck.py` and schema: `mailboxes` members and ranges
- [ ] 3.5 Configurator Project page: Function blocks section (switch, counts, cost line, which blocks need what, Update declarations note); New config… OpenPLC defaults
- [ ] 3.6 `canworks-deploy library --format st|plcopen`
- [ ] 3.7 Tests in `tools/deploy/tests/` (pack, hash, groups, link code, export, schema, library formats) and page tests for the section

## 4. Library

- [ ] 4.1 Shared private blocks: `CW_LINK_SERVICE`, `CW_MB_CLAIM` (tickets, owner stamp), `CW_MB_CALL` (counter handshake, STAGE/FETCH loops, timeouts, ERROR_ID 20/22)
- [ ] 4.2 SDO: `CO_SDO_READ_BYTES`, `CO_SDO_WRITE_BYTES`, `CO_SDO_READ_STRING`, `CO_SDO_WRITE_STRING`, `CO_SDO_READ_REAL`, `CO_SDO_WRITE_REAL`; EMCY: `CO_RECV_EMCY`
- [ ] 4.3 Frames: `CAN_SEND`, `CAN_SEND_CYCLIC`, `CAN_RECEIVE`, `CAN_BUS_INFO`
- [ ] 4.4 J1939: `J1939_SEND`, `J1939_RECEIVE`, `J1939_REQUEST`, `J1939_ECU_INFO`, `J1939_FIND_ECU`, `J1939_DM_READ`, `J1939_DM_CLEAR`
- [ ] 4.5 Change 1's blocks: `LINK` bound 1023
- [ ] 4.6 Pure ST REAL/LREAL word helpers for other PLCs; PLCopen XML writer in `library/generate.py`
- [ ] 4.7 `test/plc_modbus/`: mailbox model (request and receive mailboxes, one call per poll) and block tests as `canopen-ci` lists; REAL helper comparison over 10,000 patterns

## 5. CI

- [ ] 5.1 Change 1's OpenPLC through Modbus integration job: block program with `CAN_SEND`/`CAN_RECEIVE` on vcan0, `CO_SDO_READ_STRING` from the simulated node, a 40-byte `J1939_SEND`/`J1939_RECEIVE` round trip with the J1939 simulator
- [ ] 5.2 CI time: wall and summed job time against the baseline (median of the last 5 green `main` code runs), both numbers in the PR

## 6. Docs

- [ ] 6.1 `docs/plc-library.md`: every block (pins, bridge block needed, ERROR_IDs, polls per call), sharing rules, limits of the link, the move from the plugin's blocks (`LINK := canworks.link`)
- [ ] 6.2 `docs/modbus-bridge.md`: `mailboxes`, register layouts, operations, receive batches and acknowledgement, stall rule, link-stop cleanup
- [ ] 6.3 `docs/raw-can.md`, `docs/j1939.md`, `docs/plc-sdo.md`: the blocks over Modbus, throughput and when to use config messages instead
- [ ] 6.4 Using the blocks on another Modbus PLC (library `--format`, map export with link code, channel mapping), in `docs/modbus-bridge.md`
- [ ] 6.5 README feature list; configurator docs for the Function blocks section
- [ ] 6.6 Example: `examples/openplc-modbus/` gets a program using `CAN_RECEIVE`, `CO_SDO_READ_STRING` and `J1939_REQUEST`
- [ ] 6.7 Tools minor version bump

## 7. Archive

- [ ] 7.1 OpenSpec archive on the branch once CI is green (open hardware tasks listed in the PR)

## 8. Hardware (Linux device with the real node)

- [ ] 8.1 Configurator-generated OpenPLC project with mailboxes, Build and upload from the stock editor: `canworks.ok` TRUE, request count as the page said
- [ ] 8.2 Real node: `CO_SDO_READ_STRING` of 0x1008:0, `CO_SDO_READ_BYTES` of a long object, `CO_RECV_EMCY` on an EMCY the node sends (or skip with a note if it cannot be provoked)
- [ ] 8.3 Measure at a 10 ms poll: `CAN_SEND` round trip, `CAN_RECEIVE` sustained rate before drops, a 1024-byte SDO read; CPU of runtime and bridge; record in the PR
- [ ] 8.4 PLC stop with a running `CAN_SEND_CYCLIC` and an open `CAN_RECEIVE`: frame stops, receiver closed, both back after start; then a clean PLC start
- [ ] 8.5 Another Modbus PLC (CODESYS on the Windows PC, if available): import the PLCopen XML library and the exported map, run `CAN_SEND` and `CO_SDO_READ` against the bridge on the Linux device
