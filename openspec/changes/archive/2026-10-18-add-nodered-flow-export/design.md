# Design: add-nodered-flow-export

## Context

`modbusmap.py` computes a bridge config's register map (`register_map`: name, table, address, count, type, word order, scale, offset, unit, `byte_in_register`) and the client channels (`suggest_channels`), and writes CSV, JSON and ST. The bridge's own blocks (status 8 bytes, control 6, live list 16 per network, SDO request 14 / response 14) are rows of type `BLOCK`. Entry `name` (add-codesys-target) already names map rows. Node-RED's standard Modbus palette is `node-red-contrib-modbus` (nodes `modbus-client`, `modbus-read`, `modbus-flex-write`).

## Goals / Non-goals

- Goal: import one file and get named signals both ways, with the watchdog, NMT and SDO handled.
- Non-goals: a Node-RED project target, deploying into a running Node-RED (Admin API), an own palette package, MQTT from the bridge. All can come later if the export gets used.

## Decisions

### D1. Export, not target

Node-RED is a client of the bridge, like a PLC with Modbus channels; the bridge target already owns the process image. A target would only hide the location column, which the bridge needs anyway. So this is a fourth map format beside CSV, JSON and ST.

### D2. Flow layout

One tab `canworks <file stem>`, node ids derived from a hash of the config path and the row name so a re-import replaces nodes instead of duplicating them (Node-RED offers "replace" on equal ids).

```
modbus-read (FC4 per read channel, poll) ─┐
                                          ├─ function "decode" ─ link out "canworks in"
modbus-read (FC3 once at start: outputs) ─┘        └─ node status from the status block
link in "canworks out" ─┐
inject keepalive ───────┼─ function "encode" ─ modbus-flex-write (FC16 per write channel)
link in "canworks nmt" ─┤
link in "canworks sdo" ─┘   decode ─ link out "canworks sdo result"
```

The map rows needed at run time are embedded in the function nodes as a JSON constant (name, table, register, count, type, word order, bit, byte half, scale, offset). No other files.

### D3. Values

- Decode: registers are big-endian bytes (`byte_in_register` high/low for byte values), 32/64-bit values joined in the map's `word_order`, signed types sign-extended, REAL32/REAL64 from IEEE bits, 64-bit integers as `BigInt` only above 2^53 (else Number), BOOL from the register bit. `scale`/`offset` applied when the row has them (`raw * scale + offset`), the inverse on encode, rounded to the type.
- Change detection per row on the decoded value; the first complete poll emits every row.
- Encode keeps the output image in flow context, seeded by one FC3 read of each write channel before the first write; until that read succeeds, writes are held (not dropped, last value per topic wins) and the node shows "waiting for bridge".
- A topic that is not an output row, or a value out of the type's range, gives a node warning and writes nothing.

### D4. Watchdog

The keepalive inject fires every `min(poll_ms, watchdog_ms / 3)` and rewrites the write channels from the image (a write from a writer feeds the watchdog). With `watchdog_ms` 0 there is no keepalive. The bridge's `writers` must include Node-RED's address; the export prints a note when the flow's host is loopback and `writers` holds no loopback address (as in the example config, which allows only `192.168.1.20`), or when `writers` is empty.

### D5. NMT and SDO

Only generated when the config locates the control block or SDO blocks. "canworks nmt" takes `{network: name or index, node, command: "start"|"stop"|"preop"|"reset"|"reset_comm"|"run"|"idle"}`, increments the counter and writes the 6 bytes; the result byte from the status block comes back on "canworks in" as topic `bridge_command_result`. "canworks sdo" queues requests (one in flight), writes the request block with a new counter, and the decode side emits `{counter, status: "done"|"aborted", abort, value}` on "canworks sdo result" when the response echoes that counter; a request without an answer after the SDO timeout plus 1 s ends `status: "timeout"`.

### D6. Host and period

`--nodered-host` default: the bridge's `listen` host, or `127.0.0.1` when it is `0.0.0.0`/`::`; port from `listen`. `--nodered-poll-ms` default 100, clamped to `[10, watchdog_ms / 3]` with a note when clamped. In the configurator the export uses the defaults; the docs say to edit the client node for another host. 64-bit integers beyond 2^53 are decimal strings (BigInt does not survive the debug sidebar or file-backed context stores).

### D7. Testing without Node-RED in CI

The function bodies are plain JS strings produced by `nodered.py`. Tests run them under `node` with a stub `node`/`flow` context: decode of a register array built from the map, encode back to registers, keepalive period, counters. Register images packed independently in Python (struct) check decode and encode both ways. Node-RED itself (with `node-red-contrib-modbus` 5.60.2) was run once against a real `canworks-bridge` with the simulated example while applying, and is exercised again in the hardware task, so CI time stays flat. 

## Risks

- Palette node field names change between `node-red-contrib-modbus` versions: the golden test pins the field set we write; the hardware task checks the current release imports cleanly; the docs name the version tested.
- Polling latency (poll + one SYNC) is the price of Modbus; the docs say so and point motion work to a PLC target.
