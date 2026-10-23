## 0. Order

- [x] 0.1 Apply only after `add-openplc-modbus-target` (change 1) and `remove-openplc-plugin` (change 2) are merged and archived; rebase on main and rewrite the deltas of `plc-library`, `canopen-editor-project` and `modbus-bridge-map` against the archived text (the `LINK` bound and the library list become MODIFIED requirements there)

## 1. Spikes (before the code)

- [x] 1.1 STruC++: a block with an in-out `ARRAY[0..1279] OF WORD`, 40 instances in one program, scan time and generated code size; the test runner's in-out copy-back note of `test/plc_modbus` (STruC++ 0.7.0 copies an in-out array into the instance and back on every call, nested calls too; 20 `CAN_SEND` and 20 `CO_SDO_READ_BYTES` all waiting for one mailbox: about 0.2 ms per scan at -O2 on an x86 runner, 1.3 ms at -O0; 24 KB of generated C++ for that program)
- [x] 1.2 OpenPLC Editor: a global `ARRAY[0..1279] OF WORD` in the `canworks` list loads, builds and is kept on save (needs the editor; with 8.1)
  - Stock OpenPLC Editor on the Mac, library 0.118.1: the list loads, Build only succeeds (its program.st has `link : ARRAY [0..1279] OF WORD`, the same as the uploaded build), and after Save the project file parses equal to the one before (keys reordered only).
- [x] 1.3 Runtime v4.3.1 Modbus master with the extra groups (72-register write, 72- and 120-register reads): one connection, groups sent in file order, all within one poll at 10 ms (`test/openplc_modbus/run.py`: 7 groups, a 120-register read and a 92-register write, mailbox round trips pass)
- [ ] 1.4 CODESYS (if a copy is available on the Windows PC): paste one block's ST source with an in-out word array into a project and build; if not available, leave 8.5 open and say so in the PR

## 2. Bridge

- [x] 2.1 Engine services as change 2 left them (`plugin/src/bridge/mailbox_engine.cpp` over the engine's SDO queue, EMCY history, raw frames and J1939 jobs): SDO queue, EMCY history, raw sends, cyclic jobs, receivers, J1939 sends, requests, receivers, DM store usable from the bridge without the C ABI tables; restore from git history what change 2 deleted
- [x] 2.2 `config.cpp`: `bridge.mailboxes` (counts, locations, defaults, placement after the bridge blocks in an `openplc` config, overlap refusals); log the ranges at start
- [x] 2.3 `mailboxes.{h,cpp}`: request mailboxes (handshake, one operation per mailbox, parallel mailboxes, staging and result buffers, all operations of design Decision 2 with family ERROR_IDs)
- [x] 2.4 Receive mailbox: receivers (CAN, J1939, EMCY), FIFOs and drops, batches, acknowledgement, long J1939 messages held for RX_FETCH, the 1 s / 5 s stall rule, 32-receiver limit
- [x] 2.5 Network info blocks (first 8 networks, every 100 ms) and the cyclic job table with keepalive
- [x] 2.6 Link-state hooks in `bridge_host.cpp`: stopped, mismatch, watchdog and network restart end operations, jobs and receivers; one log line
- [x] 2.7 Map hash: one line per mailbox block (same vectors in C++ and Python)
- [x] 2.8 `test/bridge/`: operations, chunks, FIFO burst and drop, stall, link stop, cyclic jobs and keepalive, a long J1939 message fetched in parts (against a scripted engine)

## 3. PC tools

- [x] 3.1 `modbusmap.py`: mailbox items, Pack for Modbus, hash lines, request count; never cut a mailbox or info block
- [x] 3.2 `openplcmodbus.py`: groups for the mailbox areas, `canworks.link` as `ARRAY[0..1279] OF WORD`, copy code for the new `LINK` places, mailbox flags, `CW_LINK_SERVICE` call
- [x] 3.3 `--export-modbus-map OUT.st` (and Export ST variables) of a PLC link config: the list with `in_w`/`out_w`, the client channels, `canworks_in`/`canworks_out` over them
- [x] 3.4 `bridgecheck.py` and schema: `mailboxes` members and ranges
- [x] 3.5 Configurator Modbus bridge page: Function blocks section (switch, counts, areas with Suggest, cost line, which blocks need what, Update declarations note); New config… and the switch to OpenPLC start with it on; Copy as ST call passes `LINK`
- [x] 3.6 `canworks-deploy library --format st` (PLCopen XML comes with `add-plcopen-export`)
- [x] 3.7 Tests in `tools/deploy/tests/` (pack, hash, groups, link code, export, schema, library formats) and page tests for the section

## 4. Library

- [x] 4.1 Shared blocks: `CW_LINK_SERVICE`, `CW_MB_CALL` (tickets, owner stamp, counter handshake, ERROR_ID 20/22), `CW_SDO_XFER` and `CW_REQUEST` (STAGE/FETCH loops), `CW_RX` (receivers), `CW_CHAR`/`CW_CHAR_CODE`
- [x] 4.2 SDO: `CO_SDO_READ_BYTES`, `CO_SDO_WRITE_BYTES`, `CO_SDO_READ_STRING`, `CO_SDO_WRITE_STRING`, `CO_SDO_READ_REAL`, `CO_SDO_WRITE_REAL`; EMCY: `CO_RECV_EMCY`
- [x] 4.3 Frames: `CAN_SEND`, `CAN_SEND_CYCLIC`, `CAN_RECEIVE`, `CAN_BUS_INFO`
- [x] 4.4 J1939: `J1939_SEND`, `J1939_RECEIVE`, `J1939_REQUEST`, `J1939_ECU_INFO`, `J1939_FIND_ECU`, `J1939_DM_READ`, `J1939_DM_CLEAR`
- [x] 4.5 Change 1's blocks: `LINK` bound 1279
- [x] 4.6 ST source output for other PLCs (`canworks-deploy library --format st`; change 1's REAL/LREAL word helpers are already plain ST)
- [x] 4.7 `test/plc_modbus/`: mailbox model (request and receive mailboxes, one call per poll) and block tests as `canopen-ci` lists; the other-PLC link file and the example program build with the library

## 5. CI

- [x] 5.1 Change 1's OpenPLC through Modbus integration job: an SDO read through a request mailbox and a CAN receiver's frames through the receive mailbox from the example's simulated nodes, through the pinned runtime's own Modbus master (J1939 round trips are covered by the mailbox model and `test/bridge/`; the example has no J1939 network)
- [x] 5.2 CI time: wall and summed job time against the baseline (median of the last 5 green `main` code runs), both numbers in the PR
  - PR #246: 291 s wall and 1423 s summed, against a baseline of 360 s and 2352 s.

## 6. Docs

- [x] 6.1 `docs/plc-library.md`: every block (pins, bridge block needed, ERROR_IDs, polls per call), sharing rules, limits of the link, the move from the plugin's blocks (`LINK := canworks.link`)
- [x] 6.2 `docs/modbus-bridge.md`: `mailboxes`, register layouts, operations, receive batches and acknowledgement, stall rule, link-stop cleanup
- [x] 6.3 `docs/raw-can.md`, `docs/j1939.md`: the blocks over Modbus, throughput and when to use config messages instead (the SDO blocks' text moved to `docs/plc-library.md`, since change 2 removes `docs/plc-sdo.md`)
- [x] 6.4 Using the blocks on another Modbus PLC (library `--format`, map export with link code, channel mapping), in `docs/modbus-bridge.md`
- [x] 6.5 README feature list; configurator docs for the Function blocks section
- [x] 6.6 Example: `examples/openplc-modbus/main.st` uses `CO_SDO_READ_STRING`, `CAN_RECEIVE`, `CO_RECV_EMCY`, `CAN_BUS_INFO` and `CAN_SEND_CYCLIC` (no J1939 network in that example); the ST tests build it
- [x] 6.7 Tools minor version bump

## 7. Archive

- [x] 7.1 OpenSpec archive on the branch once CI is green (open hardware tasks listed in the PR)

## 8. Hardware (Linux device with the real node)

- [x] 8.1 Configurator-generated OpenPLC project with mailboxes, Build and upload from the stock editor: `canworks.ok` TRUE, request count as the page said
  - Raspberry Pi 5, runtime v4.3.1, bridge built from the PR: project uploaded with `openplc-cli upload` (the editor's Build-only output), mailboxes at %IB72 and %QB32, `canworks.ok` TRUE, 7 requests per poll as the page said.
- [x] 8.2 Real node: `CO_SDO_READ_STRING` of 0x1008:0, `CO_SDO_READ_BYTES` of a long object, `CO_RECV_EMCY` on an EMCY the node sends (or skip with a note if it cannot be provoked)
  - Name read as a string; 0x1008, 0x1009 and 0x100A read as bytes (4, 4 and 5 bytes). The node sent no EMCY during the run, so `CO_RECV_EMCY` was not exercised on hardware.
- [ ] 8.3 Measure at a 10 ms poll: `CAN_SEND` round trip, `CAN_RECEIVE` sustained rate before drops, a 1024-byte SDO read; CPU of runtime and bridge; record in the PR
  - Partial: `CAN_SEND` round trip about 28 ms on average (20 to 100 ms), SDO reads 20 to 60 ms, `CAN_SEND_CYCLIC` exactly 10 frames/s; CPU 31 % runtime and 2.7 % bridge. The receive rate measurement found a bug: receivers ignored every batch for half of each 65.5 s bridge clock period (fixed in the follow-up, `CW_RX` latches that the batch is newer than the open). Measured again after the fix (main 7619e6f, tools 0.118.1): over 202 s and three clock wraps the any-ID receiver got 862 frames against 861 on candump (4.25 frames/s, node 23 is the only other sender), 0 dropped, no overflow, no reopen. The rate where drops start needs a second sending device on the bus and stays open. Node 23's longest object is 5 bytes, so the 1024-byte SDO read runs in `test/openplc_modbus/run.py` instead: a simulated node's 1024-byte string through the runtime's Modbus master, the first 128 bytes and 7 FETCHes, about 40 ms for the read.
- [x] 8.4 PLC stop with a running `CAN_SEND_CYCLIC` and an open `CAN_RECEIVE`: frame stops, receiver closed, both back after start; then a clean PLC start
  - Cyclic frame stopped and the receiver closed on PLC stop, both came back on start; ended with a clean PLC start, node OPERATIONAL.
- [ ] 8.5 Another Modbus PLC (CODESYS on the Windows PC, if available): bring in the ST library sources and the exported map, run `CAN_SEND` and `CO_SDO_READ` against the bridge on the Linux device
