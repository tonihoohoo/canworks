## 1. Bridge: counters and closed list

- [x] 1.1 `modbus_server.{h,cpp}`: per-client counters (requests per function, exceptions per code, refused writes, last write time/table/range, 5 s request rate); close reasons at every close path; list of the last 8 closed connections kept 10 minutes
- [x] 1.2 `bridge_host.cpp`: counters and closed list in the status answer
- [x] 1.3 C++ tests: counts for reads, writes, refused writes and each exception; each close reason; closed list length and expiry

## 2. Bridge: Modbus trace recorder

- [x] 2.1 `modbus_trace.{h,cpp}`: 4 MiB byte ring of variable-length records, sequence numbers, fetch with max and lost count
- [x] 2.2 Change filter: per client and (function, start, count) a hash of values and result; skipped counts; exceptions, refused writes, functions 8 and 43 always recorded; `changes_only` false records all
- [x] 2.3 Server hook after the answer is queued; nothing recorded while no client traces
- [x] 2.4 `can/diag.cpp`: `modbus_trace_start`/`fetch`/`stop` for the bridge (client filter, 10 s idle end, "not a bridge" elsewhere)
- [x] 2.5 C++ tests: changes-only on a polling client, skipped counts, exceptions always kept, wrap and lost count, idle end, client filter, timing of answers unchanged with a trace running

## 3. PC tools: decoding, recording, saving

- [x] 3.1 `bustrace/model.py`: Modbus record kind; `wire.py` unpacking
- [x] 3.2 `bustrace/decode.py` with `modbusmap.py`: range to named values (word order, bits), client names from `bridge.connections`, hints (past the image, 3xxxx/4xxxx, split value, not a writer), map hash mismatch
- [x] 3.3 `bustrace/recorder.py`: second fetch loop, one session sorted by time, gap markers
- [x] 3.4 `bustrace/stats.py`: Modbus counts in the statistics; By request table
- [x] 3.5 `bustrace/decode.py`: delay matching (write: first frame after it with the new value; read: last frame before it with the value read; other network; not seen within 1 s) and min/avg/max in By request
- [x] 3.6 `bustrace/formats.py`: pcapng IPv4 interface with synthetic handshake per client and comments; reader; other formats leave them out with a note
- [x] 3.7 `diag.py`: `modbus-trace` command (`--config`, `--all`, `-o`, `--duration`, Ctrl-C) and client lines in `status`
- [x] 3.8 Tests: decoding cases, hints, delays (write to RPDO, TPDO to read, other network, not seen), pcapng round trip, tshark decodes the file as Modbus/TCP where tshark is installed, CLI against the simulated bridge

## 4. Configurator

- [x] 4.1 `tracing.py` and `static/trace.js`: Capture… Modbus requests / Only changes / client; Modbus rows in Chronological; source filter; inspector; By request; greyed out with the reason on an adapter or a non-bridge runtime
- [x] 4.2 `static/bridge.js`: Clients panel (connections vs seen clients, closed list, refused-write links)
- [x] 4.3 Page tests: record with the example bridge and a Python client, wrong address hint, source filter, clients panel rows for connected, not connected and unknown clients

## 5. Docs

- [x] 5.1 `docs/modbus-bridge.md`: "Seeing the Modbus traffic" (counters, trace, hints, clients panel)
- [x] 5.2 `docs/trace.md`, `docs/diagnostics.md` (operations, status, `modbus-trace`), `docs/configurator.md`
- [x] 5.3 README: Online diagnostics bullet mentions the Modbus trace
- [x] 5.4 Version bump (minor) and release notes

## 6. Archive

- [x] 6.1 `openspec archive add-modbus-traffic-view --yes` on the branch; one PR with spec, code and archive; squash auto-merge

## 7. Hardware check (Pi)

- [x] 7.1 Pi with OpenPLC at a 10 ms poll: Modbus trace with changes only for 60 s from the Mac configurator, the bridge's CPU with and without the trace (under 5 % with it), no change in OpenPLC's poll timing; By request shows write-to-RPDO and TPDO-to-read delays within one poll plus one SYNC. Result (bridge 0.137.1): bridge CPU 2.7 % without and 3.3 % with the Modbus and CAN traces; OpenPLC's poll unchanged (198.8 writes/s and 695.8 requests/s both ways, about 10.06 ms a cycle), SYNC skipped 0, late PDOs 0; 60 s of changes only recorded about 15 500 requests, the CAN trace about 6 800 frames with 0 lost. The delays were not measurable on this bench: node 23's RPDO is event-driven and OpenPLC's outputs did not change, node 23 has no TPDO and node 5 is absent (see 7.3)
- [x] 7.2 Same bench: a script client on the Mac reads holding register 40001 and writes without being a writer; the hints and the Clients panel show both. Result: the read of 40000 got exception 0x02 with the 4xxxx-notation hint (95 holding registers), the write with fn 6 got 0x01 with the "not in the bridge's writers (127.0.0.1)" hint; `canworks-diag status` counted the exceptions and 3 refused writes, and the Clients panel showed 192.168.1.70 as Not in connections with Add connection beside OpenPLC at about 670 requests/s
- [x] 7.3 Same bench with an output that changes while tracing (a forced valve output, or a config with a node 23 TPDO): By request shows write-to-RPDO and TPDO-to-read delays within one poll plus one SYNC. Result (bridge 0.137.1, `blink_en` forced on for 41 s so the valve %QX6.0 toggled every 500 ms, then unforced): all 76 valve changes in OpenPLC's HR 3 writes reached RPDO 0x217, delay min 0.37, avg 5.39, max 10.08 ms, within one SYNC (10 ms). TPDO-to-read does not apply on this bench (node 23 has no TPDO, node 5 is absent). The trace named HR 3 only by `%QB7`, not the valve bit sharing it, so the delays were matched from the pcapng by hand; fixed in 0.137.2 (bits named in register ranges)
