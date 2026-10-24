## Why

Every PLC, HMI and script now reaches the CAN networks through the bridge's Modbus server. When a client "sees nothing" or writes the wrong thing, the cause is almost always on the Modbus side: a register address one off, a 4xxxx-style address, the wrong word order, a client that is not in `writers` and gets exception 0x01, a channel that reads past the image, or a client that is not connected at all. Today the bridge shows only the number of connected clients and a request count per client, and the Trace view shows CAN frames only. There is no way to see what a client asked for and what it got.

Commercial CAN-to-Modbus gateways have a protocol traffic page and protocol diagnostics for exactly this. Explore report: `research/modbus-bridge-competitors-2026-10-24.md` (gap 1). Toni (2026-10-24): "Should 1 be similar to can trace?", then "Propose 1 and 4".

## What Changes

- **Client counters in the bridge, always on.** Per connected client: requests per function, exceptions per code, refused writes, the last write (when, which table and range) and the reply rate. The last 8 closed connections stay listed for 10 minutes with why they were closed (idle, replies not read, slot taken by a writer, not in `readers`). `canworks-diag status` prints them.
- **Modbus trace, recorded only while someone watches.** New diagnostics operations `modbus_trace_start`, `modbus_trace_fetch` and `modbus_trace_stop`, read-only like the CAN trace. Each record is one request with its answer: time, client, transaction, unit, function, table and range, the values read or written, and the result or exception. By default only changes are recorded: a request whose function, range and values equal that client's previous one of the same kind is counted, not recorded, and the next recorded one says how many were skipped. Exceptions and refused writes are always recorded.
- **Modbus in the Trace view, next to CAN.** Capture… gets **Modbus requests** (on by default for a bridge project). The Chronological list interleaves Modbus records with the picked network's frames on one timeline, with a source filter CAN / Modbus / both. Each Modbus row names the client by its connection (`OpenPLC`, `Line HMI`) or its address, and decodes the range with the register map: `HR 12-13 dio.valve_cmd = 500`. Exceptions get a plain-language hint (address outside a 40-byte image, a 40001-style address, a client that may not write). A write's inspector gives the time until the first CAN frame carrying each changed value, and a read the time since the frame it got its value from, with a link to that frame. By identifier gets a **By request** table for Modbus: one row per client, function and range with count, cycle time, minimum/average/maximum delay to or from the bus, last values and last error.
- **Saving.** pcapng keeps the Modbus records as a second interface (IPv4 packets on port 502), so Wireshark decodes them as Modbus/TCP and the Trace view opens them again. The other formats keep the CAN frames only and say so.
- **Command line.** `canworks-diag modbus-trace` prints the records live, decoded with `--config`, and writes pcapng with `-o`.
- **Modbus clients panel.** While connected, the Modbus bridge page shows each connection of the config next to what the bridge sees: connected or not, requests per second, exceptions, last write. A client that is not in the config's connections is listed as **Not in connections**.
- **Docs.** `docs/modbus-bridge.md` gets "Seeing the Modbus traffic"; `docs/trace.md`, `docs/diagnostics.md` and `docs/configurator.md` one section or paragraph each; README's Online diagnostics bullet says the Modbus traffic is traced too.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `modbus-bridge`: client counters, recently closed connections, the Modbus trace recorder.
- `canopen-online-diagnostics`: the Modbus trace operations, the clients in the status, `canworks-diag modbus-trace`.
- `canopen-bus-trace`: Modbus records in a trace, their decoding with the register map, saving and opening them.
- `canopen-configurator`: the Modbus capture option, the source filter, By request, and the Modbus clients panel.

## Impact

- Bridge: `modbus_server.{h,cpp}` (counters, closed list, recording hook), a new `modbus_trace.{h,cpp}` ring with the change filter, `bridge_host.cpp` (status), `can/diag.cpp` (three operations, served for the bridge only).
- PC tools: `bustrace/` (record kind, decoding with `modbusmap.py`, pcapng interface, statistics by request), `configurator/tracing.py` and `static/trace.js`, `static/bridge.js` (clients panel), `diag.py` (`modbus-trace`, status lines), tests.
- No change to the register rule, the Modbus functions served or the config. Status and trace need the diagnostics channel, as the CAN trace does.
- CI: the bridge tests run in the existing bridge job; the trace tests in the existing PC tools job; no new job.
- Tools and bridge minor version bump. Hardware check on the Pi with OpenPLC's master.
