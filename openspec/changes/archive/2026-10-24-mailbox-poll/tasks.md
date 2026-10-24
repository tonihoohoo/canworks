## 1. Layout and check

- [x] 1.1 `openplcmodbus.py`: class `mailbox` for items with `mailbox_area`; mailbox groups get `cycleTime` `mailbox_poll_ms`; `settings()` resolves the default (smallest multiple of `poll_ms` that is at least 50); request count per poll plus mailbox requests per mailbox poll; budget warning on the per-poll average
- [x] 1.2 Schema (both copies) and `bridgecheck.py`: `mailbox_poll_ms` on `openplc` only; a multiple of `poll_ms`, at most 250; error naming the field otherwise
- [x] 1.3 Tests: groups never mix mailbox blocks with other registers; cycle times; default for poll 10, 15, 100; check refusals; request count text
- [x] 1.4 Regenerate `examples/openplc-modbus` and `examples/virtual-plant` editor files (neither changed: virtual-plant has no mailboxes, openplc-modbus has no editor files); `test/openplc_modbus/run.py` runs the mailbox steps at a 10 ms mailbox poll and checks the receive rate at the default too (90 frames/s with the runtime's own master)

## 2. Configurator

- [x] 2.1 OpenPLC connection Settings: Mailbox poll choice (multiples of `poll_ms` among 10, 20, 50, 100, 200; placeholder the default), hidden without mailboxes; hint with round trip and receive rate; requests line "N Modbus requests every P ms, M more every Q ms"; a change is one undo step and the next Save writes it
- [x] 2.2 Page tests: choice and hint values for 50 and 100 ms with 1 and 2 receive blocks; hidden without mailboxes; undo; remote device file after Save

## 3. Node-RED

- [x] 3.1 `nodered.py`: tag read channels `null`, `requests`, `receive` or `cyclic`; network info untagged
- [x] 3.2 `lib/bridge.js` `_cycle`: read a tagged channel only while its part is busy (and one poll after); read a part once before the first write when it turns busy
- [x] 3.3 Tests: idle flow reads no mailbox channel; SDO string read, receiver and cyclic job still pass against the simulated bridge; first request after idle

## 4. Docs

- [x] 4.1 `docs/plc-library.md`: mailbox poll table (round trip, receive rate), new Pi numbers (task 6), other PLCs line
- [x] 4.2 `docs/modbus-bridge.md` (receive throughput) and `docs/configurator.md` (OpenPLC Settings): one line each
- [x] 4.3 Version bump (minor, 0.134.0); release notes come from the PR

## 5. Archive

- [x] 5.1 `openspec archive mailbox-poll --yes` on the branch; one PR with spec, code and archive; squash auto-merge

## 6. Hardware check (Pi, after merge)

- [x] 6.1 Pi with node 23, default mailboxes, OpenPLC program that declares mailbox blocks: runtime CPU over 60 s at mailbox poll 10 and 50 ms (data poll 10 ms), compared with 31 % and 9 % from #278. Result (bridge 0.134.0, 2 x 60 s each): OpenPLC runtime about 33 % at mailbox poll 10 ms (9 Modbus groups, all at 10 ms) and about 16 % at 50 ms (mailbox groups at 50 ms); bridge about 3 % in both
- [x] 6.2 Same program: `CO_SDO_READ_STRING` 0x1008 and a `CAN_RECEIVE` work at 50 ms; note the round trip. Result at 50 ms: the string read of 0x1008:0 every 2 s finished 34 times with 0 errors, round trip 60-80 ms (180 ms at most, with byte reads of the same node running alongside); an `ALL_IDS` `CAN_RECEIVE` got 131 frames in about 31 s (about 4.2 per second, as many as the other senders put on the bus), 0 dropped, 0 queued
