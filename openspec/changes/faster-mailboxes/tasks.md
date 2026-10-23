## 0. Order

- [ ] 0.1 Apply only after `modbus-connections` is merged and archived: rebase on main, rewrite the deltas against the archived spec text (its bridge config and export changes), re-validate
- [ ] 0.2 Tell the coordinator when this merges, so `add-nodered-blocks` can rebase onto the new layout

## 1. Bridge

- [ ] 1.1 `mailboxes.h/.cpp`: header 25 words with the batch time (words 21-24, the first record's UTC µs); CAN records 10 words, J1939 12, EMCY unchanged; record room 95 words per block (215 with two)
- [ ] 1.2 `receive_blocks` (1 or 2, default 1) in `config.cpp` and the mailbox layout: receive area 120 or 240 registers, one map block per receive block, refusal of other values
- [ ] 1.3 C++ tests: full batch of 9 CAN / 7 J1939 / 7 EMCY records with one block, 21 / 17 / 17 with two; batch time is the first record's time; two-block layout ranges in the start log

## 2. PC tools

- [ ] 2.1 `mailboxlayout.py`: receive block sizes, `receive_blocks` key and default; `LINK` places (receive 720-959, info 960 + 18n, cyclic 1104)
- [ ] 2.2 Map, OpenPLC remote device and suggested client channels: one group or channel per receive block; map hash covers both
- [ ] 2.3 Generated `canworks_in` / ST link export: copy the receive blocks, info and cyclic table to their new `LINK` places
- [ ] 2.4 Configurator Function blocks section: receive blocks 1 or 2, expected rate for OpenPLC, rule in words for other clients; request count includes the second block
- [ ] 2.5 Tools minor version bump; tests (layout, map, remote device, page test of the section)

## 3. Library

- [ ] 3.1 `CW_RX`: header 25 words, record sizes 10 / 12 / 12, walk to word 960
- [ ] 3.2 `CAN_RECEIVE`, `J1939_RECEIVE`: `TIMESTAMP` from the batch time; `CO_RECV_EMCY` unchanged apart from the record start
- [ ] 3.3 `CAN_BUS_INFO`, `J1939_ECU_INFO`, `CAN_SEND_CYCLIC`, `CW_LINK_SERVICE`: new `LINK` places
- [ ] 3.4 ST mailbox model and tests: new record format, a full 9-record batch, a 21-record batch over two blocks, TIMESTAMP shared within a batch; rebuild the library

## 4. Integration test and measurement

- [ ] 4.1 `test/openplc_modbus/run.py`: a receive-rate check with the simulated nodes on a 2 ms SYNC, one and two blocks; expect at least 400 and 900 frames/s at a 10 ms poll with a fast scan (today 344)
- [ ] 4.2 CI time: wall and summed job time against the baseline, in the PR

## 5. Docs

- [ ] 5.1 `docs/modbus-bridge.md`: receive mailbox header and record layouts, `receive_blocks`, the throughput rule and numbers
- [ ] 5.2 `docs/raw-can.md`, `docs/j1939.md`, `docs/plc-library.md`: `TIMESTAMP` is the batch time; receive rate per poll
- [ ] 5.3 README: replace "a program sends and receives a few hundred frames per second at most" with the measured rule (receive about 450 frames/s, or 1050 with two receive blocks, at a 10 ms poll; send about 50 per request mailbox); run `tools/deploy/tests/test_readme.py`

## 6. Archive

- [ ] 6.1 `openspec archive faster-mailboxes --yes` in the apply PR

## 7. Hardware (Pi, when free)

- [ ] 7.1 OpenPLC project with `receive_blocks` 1 and 2 on the bench: Windows gs_usb adapter sending 0x6A0-0x6AF at 200, 500 and 1000 frames/s for 20 s each; frames received against sent, `DROPPED`, no stall closes; record in the PR
