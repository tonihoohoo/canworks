## Context

Research: research/nodered-blocks-2026-10-23.md (project files). Today's Node-RED support (`add-nodered-flow-export`, archived 2026-10-18) is a generated flow: `node-red-contrib-modbus` read nodes per suggested read channel, function nodes with generated JavaScript for decode, encode, keepalive, NMT and SDO, and link nodes "canworks in", "canworks out", "canworks nmt", "canworks sdo", "canworks sdo result". `add-bridge-mailboxes` (archived 2026-10-23) added request mailboxes, the receive mailbox, network info and cyclic jobs to the bridge, usable by any Modbus client, and the ST blocks over them.

Facts this design relies on:

- The mailbox protocol is client-neutral: request words and counters in holding registers, answers in input registers, receive batches acknowledged through three holding registers, cyclic jobs kept alive by a holding register per job (docs/modbus-bridge.md "Function block mailboxes").
- After its start the bridge takes the first request words of each mailbox only as the baseline (ERROR_ID 8 if they held a request). The control block and SDO registers have the same rule only for a PLC link (`openplc-modbus-followups`, merged: control result 6, SDO abort 0x08000021); without one they run a command when the counter changes from the bridge's start value.
- A bridge restart always drops the TCP connection, so a client sees every restart as a reconnect.
- Each block fits one Modbus request (72 ≤ 123 written, 120 ≤ 125 read), and the map's suggested channels never cut one.
- Node-RED runs nodes in one JavaScript event loop; node modules are CommonJS, registered with `RED.nodes.registerType`, and config nodes are shared by the nodes that name them. That API has been stable since Node-RED 1.x.

## Goals / Non-Goals

Goals: every ST block's function in Node-RED with the same ERROR_IDs; one Modbus connection per bridge; no third-party runtime dependency; works offline (the package comes with the PC tools); the package and the ST blocks cannot drift apart unnoticed; tests without Node-RED in CI.

Non-goals: npm; dashboard nodes; installing into Node-RED from the configurator; a new bridge protocol; Node-RED directly on SocketCAN; scan-synchronous behaviour.

## Decisions

### 1. A node package inside the PC tools

`tools/deploy/canworks/nodered_package/` is the package source (`package.json` name `node-red-canworks`, version written at build from the tools version, `node-red.nodes` listing the node files, `engines.node >= 18`). It is package data of the wheel, so `canworks-deploy --export-nodered-package OUT.tgz` writes a `.tgz` from the installed copy (a deterministic tar written by Python: sorted entries, fixed times, `package/` prefix as `npm pack` writes it), and the release attaches the same file. Install: Node-RED Menu > Manage palette > Install > upload, or `npm install /path/node-red-canworks-<v>.tgz` in the Node-RED user folder and a restart (Docker: in `/data`).

Alternatives: subflows in the export (code copied into every project, fixes need re-exports, mailbox sharing through flow context); docs snippets (untested); npm (account, token, public name, unpublishing limited; Toni chose `.tgz`).

### 2. Own Modbus TCP client, no dependencies

`lib/modbus.js` over `net.Socket`: function 3 (read holding), 4 (read input), 16 (write multiple), MBAP framing, one outstanding transaction at a time (the bridge answers in order), a timeout per transaction (1 s), reconnect with backoff 0.5-5 s. About 200 lines. `modbus-serial` (what `node-red-contrib-modbus` wraps) pulls `serialport` with native binaries, which an upload install on an offline device cannot build; the bridge itself also has its own server.

### 3. The config node runs one poll cycle

Each cycle (every `poll_ms`, default 10, kept between 10 and a third of `watchdog_ms`):

1. Read the suggested read channels (values, status, live lists, SDO response, mailbox answers, receive mailbox, network info, cyclic table), in map order.
2. Decode values; emit changed ones to every **canworks in** node; update node status.
3. Advance jobs: answers with the expected counter end chunks or jobs; free mailboxes take the next queued job.
4. Write the changed write channels (outputs), every request block that changed, the receive acknowledgement when a batch was taken, and the cyclic keepalives; when the watchdog is on, rewrite the outputs at least every third of `watchdog_ms`.

A cycle that is still running when the next is due is skipped, not queued. With the default example map one cycle is 3-6 requests.

### 4. Layout comes with the flow

The export puts the config's register map rows (name, byte, type, scale, offset, unit) and the bridge block layout (status, control, live lists, SDO, mailboxes with counts and areas, network names and kinds, `watchdog_ms`, word order, map hash) into the config node as one JSON property. The node's form shows host, port, poll and the map's summary (values in/out, mailboxes); changing the map means exporting again. A config node without layout is refused with a status "export the flow from canworks".

Alternative: the config node reads `canworks.json`. Rejected: Node-RED often runs in a container or on another machine without the config folder, and the map rules (packing, word order) live in Python.

### 5. Jobs and sharing

A node's job is a small state machine in `lib/jobs.js` (one per operation family: SDO short, SDO long, NMT, CAN send, cyclic set/stop, RX open/close, J1939 send/request, DM read/clear, find ECU, RX_FETCH). Short SDO (≤ 4 bytes, no mailbox configured or `size` ≤ 4) and NMT use the SDO registers and the control block with one queue each; everything else uses the request mailboxes with one queue shared by all mailboxes (first free mailbox takes the oldest job). A job keeps its mailbox for its whole transfer (STAGE chunks, the operation, FETCH chunks). Queue wait does not count against the node's timeout (as in the ST blocks). Queue length is bounded (64 per bridge); a job beyond that ends with ERROR_ID 5 of its family ("no free slot"), 9 for J1939.

Counters: a new request uses the last counter + 1, skipping the response's echo, as `CW_MB_CALL` does.

### 6. Receivers

Each **can receive**, **j1939 receive** and **emcy** node opens one receiver (RX_OPEN with its filter) when deployed and the link is up, and closes it on close or redeploy. The config node reads every configured receive block each cycle (1 or 2 after `faster-mailboxes`, which also shortens CAN records to 10 words with a timestamp per batch; the layout table follows it); when the batch sequence changed it hands each record to its receiver's node (generation checked), fetches long J1939 messages with RX_FETCH, then acknowledges. Records become messages in batch order. When the bridge closes receivers (link stop, stall, network restart: generation change), the nodes reopen them and send one status message `{status: "error", errorId: 8}`.

### 7. Restart and reconnect

On every connect, before the first write: read back the holding registers of the outputs, the control block, the SDO request and every request block and acknowledgement, and write them back unchanged. That write is the mailboxes' baseline after a restart and a no-op otherwise (same counters). For the control block and SDO registers it is what keeps a restart safe without a PLC link: the client takes the new bridge's words (after a restart: the start values) as its own last counters, so its next command uses a counter the new bridge has not handled and nothing old is run. Control result 6 and SDO abort 0x08000021 (the PLC-link baseline) end a job with ERROR_ID 8. Then the outputs held by **canworks out** before the read-back are applied (last value per name wins), as today. Jobs that were running at the disconnect end with ERROR_ID 20 (bridge not reachable); the package never repeats a job by itself. Cyclic jobs and receivers are set up again after the reconnect.

### 8. Message contract

- Input: node form fields, overridden by `msg.payload` fields of the same name (`network`, `node`, `index`, `subindex`, `datatype`, `size`, `value`, `can_id`, `extended`, `dlc`, `data`, `period`, `pgn`, `priority`, `destination`, `address`, `ecu_name`, `mask`, `timeout`). Node-RED keeps `id`, `type` and `name` on every node's config for itself, hence `can_id`, `datatype` and `ecu_name`; `msg.payload` may also say `id`, `type`, `name`. A payload that is not an object sets the node's main field (`data`, an SDO write's `value`, NMT's `command`). `network` is the network's name or index, or left out with one network of that kind.
- Output: one message per job, `msg.topic` kept from the input, `msg.payload` the result (a read's value, `true` for a write or send, `null` on error), `msg.canworks = {status: "done" | "error", errorId, abortCode, abortText, request}`. Receivers emit `msg.payload` a record (`{id, extended, dlc, data, time}` for CAN; `{pgn, source, destination, priority, data, time}` for J1939; `{node, code, register, data, time}` for EMCY).
- Data is a `Buffer`; arrays of numbers and hex strings are accepted as input. DTCs are `{spn, fmi, oc, cm}`, NAMEs `{identity, manufacturer, function, ...}` and a `BigInt`-safe decimal string.
- Node status: blue ring busy, green dot done, red ring with the ERROR_ID.

### 9. One source for the layout

`python -m canworks.nodered layout` writes `lib/layout.js` from `mailboxlayout.py` and the ERROR_ID tables (bridge-plc-blocks families); a Python test regenerates it and compares, so a mailbox change that forgets the package fails CI. A second test reads the bridge's own constants (`mailboxes.h`, the record sizes in `mailboxes.cpp`) and compares them with `mailboxlayout.py`, so the chain bridge -> layout -> package is checked end to end. The ST model (`test/plc_modbus/mailbox_model.st`) is ST and cannot drive JavaScript, so the package has its own model (`tests/nodered/fake_bridge.js`) and the real-bridge run below.

### 10. Tests without Node-RED

`node --test` (built in, no packages) with a minimal RED stub (`tests/nodered/harness.js`: registerType, createNode, send, status, on close) and a scripted model of the bridge's registers that stands in for the Modbus client (`Bridge.clientFactory`), run from `test_nodered.py` in the tools shard (21 cases, about 5 s). The engine job, which already builds the bridge, runs `test/nodered/run.py`: the package's nodes on the same stub against the real bridge with the example's simulated nodes, for values in/out, short and long SDO, three SDO reads at once, NMT, CAN receive and acknowledgement, cyclic start/stop and a bridge restart (about 5 s). No new job. Real Node-RED 3.1 and 4.1 were checked by hand: offline `npm install` of the `.tgz`, the flow running against the bridge, and the editor forms.

### 11. Read-only flows and connections

After `modbus-connections` there is no OpenPLC target; a config has connections, and an OpenPLC connection sets `plc_link`. The Node-RED connection's `writes` decides whether the flow writes. With `plc_link` true the PLC owns the outputs and the mailboxes (its blocks' ticket order and owner words assume they are alone), so the flow is read-only whatever `writes` says, and Problems warns when Writes is ticked. This keeps a Node-RED dashboard next to an OpenPLC program safe. The Node-RED connection row carries both files (flow and package); only the flow counts for Out of date, since the package depends on the tools version, not the map.

## Risks / Trade-offs

- Two implementations of the block logic (ST and JavaScript). Mitigated by the generated layout, its check against the bridge's constants, and the real-bridge run (Decisions 9, 10).
- The bridge's CANopen side caps SDO data at 1024 bytes (`CANOPEN_PLC_MAX_DATA`), so the sdo node does too, like the PLC blocks.
- A batch can hold records for a receiver whose open answer arrives in the same read; the bridge node then takes the batch one poll later, once the receiver knows its slot, instead of dropping those records.
- Palette upload needs Node-RED's `editorTheme.palette.upload` (on by default); the docs give the `npm install` line as the other way.
- 10 ms polling: each cycle reads the input channels (3 requests for the example map with default mailboxes) and writes only changed channels, plus a full rewrite every third of `watchdog_ms`. Measured in the cloud container (x86, example with mailboxes, a file node logging every change): Node-RED about 9 % of one core, the bridge with its two simulated nodes about 9 %. The Pi numbers come with the hardware checks (7.1).
- 10 ms polling with many blocks is more requests per second on the bridge; the bench measured 2.2 % CPU for the bridge at 10 ms with the OpenPLC map (estimate for Node-RED: similar). The poll stays configurable.
- Old exports stop working when `node-red-contrib-modbus` is removed by the user; they keep working as long as it stays installed, and a new export replaces the tab (same tab id).

## Migration

Not in real use: clean cut. A re-export replaces the tab; the docs say to remove the old tab's links from user flows and wire **canworks in**/**canworks out** nodes instead.
