## Context

Research: research/modbus-only-2026-10-22.md (project files), section "Function blocks over Modbus". This change is change 3 of 3 and is designed on top of:

- **Change 1, `add-openplc-modbus-target`** (branch `propose/add-openplc-modbus-target`). It gives an OpenPLC program the bridge through the runtime's own Modbus master: input registers 0-1 map hash, 2-5 status; holding registers 0-2 the PLC link header (running, hash) with link states ok, stopped and mismatch; generated programs `canworks_in` (first in the task) and `canworks_out` (last) that copy raw `%IW`/`%QW` words to typed values and to the word array `canworks.link : ARRAY[0..88] OF WORD`; ST blocks `CO_SDO_READ`, `CO_SDO_WRITE` (up to 4 bytes), `CO_NMT`, `CO_NODE_LIVE` with in-out `LINK`, which claim the SDO registers and the control block through owner words in `LINK` (words 22-24) and add ERROR_ID 20 (bridge not reachable), 21 (writes not allowed) and 22 (the config has no such bridge block). Reads and writes use `poll_ms` (default 10 ms); each request is at most 125 registers read or 123 written and is consistent in itself.
- **Change 2, `remove-openplc-plugin`**. It deletes the plugin, its C ABI tables (`canworks_can_api`, `canworks_j1939_api`, the SDO/EMCY table), the C++ library blocks, all CiA 402 support and the runtime header dependency of the engine.

Facts this design relies on:

- Every Modbus write group is sent every poll, changed or not, so the bridge acts on counter changes, never on writes as such (as the control block and SDO bridge registers do now).
- A round trip (program writes a request, the bridge answers, the program sees the answer) takes about two polls: the write goes out with the next poll, the answer comes back with the poll after. At 10 ms that is 20-30 ms (*estimate*, measured in task 8.3).
- The engine services behind the plugin's blocks run on the engine's own threads and do not need the PLC scan: the SDO queue with its per-transfer timeout (`canopen/plc_api.cpp`), the per-network EMCY history of 64 (`canopen/plc_emcy.cpp`), raw sends with echo confirmation, cyclic jobs on the engine timer and filtered receivers with FIFOs (`can/raw/plc_frames.cpp`), J1939 sends, requests, receivers (`j1939/j1939_plc_msgs.cpp`) and the DM1/DM2 store (`j1939/dm.cpp`).

## Goals / Non-Goals

Goals: every function block the plugin had, except CiA 402, works again from an OpenPLC program over Modbus, with today's pins and ERROR_IDs as far as possible; the same blocks work on any Modbus PLC; nothing received between two polls is lost while the queues have room; one block instance that misbehaves (never called again, never reads its receiver) cannot block the others for more than about a second.

Non-goals: CiA 402; scan-synchronous behaviour (SYNC from the PLC cycle); CAN FD; ISO-TP; high frame rates through the program (more than a few hundred frames per second belongs in config raw messages or cyclic jobs).

## Decisions

### 1. Three kinds of bridge blocks

| Block | Direction | Size | Purpose |
|---|---|---|---|
| Request mailbox (1-4) | 72 holding + 72 input registers | 128 data bytes per round trip | Any request that needs an answer: long SDO, sends, requests, opening and closing receivers, cyclic job set-up, DM, ECU lookup, fetching data |
| Receive mailbox (0-1) | 120 input + 3 holding registers | about 7 records per round trip | Records from receiver FIFOs in the bridge: CAN frames, J1939 messages, EMCYs |
| Network info (per network, first 8) and cyclic job table (0-16 jobs) | input (+ 1 holding register per job) | 18 registers per network; a tick and 4 registers per job | Values a block shows continuously without asking: bus state and counters, J1939 address and NAME, cyclic job counts |

Alternative: one mailbox type for everything, each received frame fetched with a request. Rejected: one frame per round trip is about 40 frames per second, and frames arriving between polls would need the bridge queue anyway. Alternative: a ring buffer without acknowledgement. Rejected: a scan slower than the poll would lose records silently.

Every block fits in one Modbus request (72 ≤ 123, 120 ≤ 125), and the group rules (Decision 8) never cut one, so a request or a batch always arrives whole.

### 2. Request mailbox layout

Words are registers; bytes of data are packed high byte first (byte 2k in the high byte of data word k), as the bridge maps bytes to registers.

Request (holding registers, from the program):

| Word | Content |
|---|---|
| 0 | counter (a new value starts a request) |
| 1 | operation (high byte), network index (low byte) |
| 2-7 | arguments (per operation) |
| 8-71 | data, 128 bytes |

Response (input registers, from the bridge):

| Word | Content |
|---|---|
| 0 | counter echo (the request it belongs to) |
| 1 | state (high byte: 0 idle, 1 busy, 2 done, 3 error), ERROR_ID (low byte) |
| 2-7 | results (per operation) |
| 8-71 | data, 128 bytes |

Operations:

| Op | Name | Arguments | Results, data |
|---|---|---|---|
| 1 | STAGE | offset, length; data | bytes go into the mailbox's staging buffer at offset |
| 2 | FETCH | offset | 128 bytes of the result buffer from offset |
| 3 | SDO_READ | node, index, subindex, timeout ms | size, abort code; first 128 bytes |
| 4 | SDO_WRITE | node, index, subindex, size, timeout ms | abort code; data inline up to 128 bytes, else the staging buffer |
| 5 | CAN_SEND | id (2 words), flags (extended, RTR) and DLC, timeout ms; data 8 bytes | - |
| 6 | CYCLIC_SET | job (0xFFFF: new), id (2), flags and DLC, period ms; data | job number |
| 7 | CYCLIC_STOP | job | - |
| 8 | RX_OPEN | kind and flags, depth, filter (CAN: id, mask; J1939: PGN, source; EMCY: node) | receiver number |
| 9 | RX_CLOSE | receiver | - |
| 10 | RX_FETCH | receiver, offset | 128 bytes of the receiver's held long message |
| 11 | J1939_SEND | PGN (2), destination and priority, length, timeout ms | data inline up to 128 bytes, else staging |
| 12 | J1939_REQUEST | PGN (2), destination, timeout ms | source, length, ACK code; first 128 bytes |
| 13 | DM_READ | source, previous, timeout ms | lamps and flash, count, age ms (2); up to 32 codes |
| 14 | DM_CLEAR | destination, previous only, timeout ms | - |
| 15 | FIND_ECU | data: NAME (4 words), MASK (4 words) | found, address, count; data: the found NAME |

The staging buffer and the result buffer hold 1785 bytes each (the longest J1939 message; SDO byte blocks use up to 1024). A result stays until the next operation other than FETCH on that mailbox; staged bytes until the next operation other than STAGE. The bridge runs one operation per mailbox at a time and operations of different mailboxes in parallel. A new counter while an operation is busy is taken after it ends. A block writes its counter as the last request word plus one (skipping the response's echo), so a mailbox that changes hands never sees an old counter again.

The response's ERROR_ID is already in the numbering of the block family the operation belongs to (SDO, frame, J1939 message, trouble code), so the blocks pass it through. Cost of a 1024-byte SDO read: one SDO_READ and seven FETCH round trips after the CAN transfer, about 200 ms at a 10 ms poll (*estimate*).

### 3. Receive mailbox

Input block, 120 registers:

| Word | Content |
|---|---|
| 0 | batch sequence (wraps; it starts at a different value each run of the bridge) |
| 1-2 | receivers present (word 1 bits 31-16, word 2 bits 15-0; bit n: receiver n has records in this batch) |
| 3 | number of record words used |
| 4 | tick: the bridge's milliseconds (wraps) when the batch was built |
| 5-20 | receiver generations, receiver 2k in the high byte of word 5 + k, 2k+1 in the low byte (0: closed) |
| 21-119 | records |

Each record: word 0 receiver (bits 15-8), kind (bits 7-4: 1 CAN, 2 J1939, 3 EMCY) and flags (bits 3-0: long message, session restart, overflow), word 1 records still queued for that receiver after this one, word 2 dropped count (low 16 bits, the block widens it), words 3-6 receive time in UTC microseconds (high word first), then the payload:

- CAN: id (2 words), flags and DLC, 8 data bytes (14 words in all)
- J1939: PGN (2), source and destination, priority, length, the first 8 data bytes (16 words)
- EMCY: node and error register, error code, 5 manufacturer bytes (12 words)

**Reused receiver numbers.** RX_OPEN answers the receiver number, its generation and the tick. A block takes a record only from a batch whose tick is not older than that tick, while the receiver's generation in the batch is still its own and its present and pending bits are set; a changed generation in a newer batch means the bridge closed the receiver (ERROR_ID 8, the block opens it again). So a record of an earlier receiver with the same number is never taken.

Acknowledgement, 3 holding registers: batch sequence seen, receivers still pending (2 words). The bridge shows the next batch when the acknowledgement names the current sequence with no receivers pending.

Per receiver the bridge keeps a FIFO of `DEPTH` records (CAN 1-256, default 32; J1939 1-32, default 4; EMCY: a cursor into the network's 64-message history). A batch takes records from all receivers in arrival order until it is full. A J1939 message longer than 8 bytes is a record with the long flag and its length; the whole message is held for its receiver, and the block reads it with RX_FETCH through a request mailbox before it reports `NEW`. RX_FETCH makes the held message from the offset on the mailbox's result (result 0 its length), so the rest comes with FETCH like any long result. A batch holds at most one long record per receiver.

**Stalled receivers.** If a batch is not fully acknowledged within 1 s (5 s while a receiver still pending has an RX_FETCH running), the bridge closes the receivers still pending, logs one line naming them, and moves on. Their blocks see ERROR_ID 8 once and reopen. So a block that is no longer called, or a program that never drains, costs the others at most a second.

At most 32 receivers in total (the pending mask is 32 bits). The plugin allowed 32 CAN and 16 J1939 receivers per network; a program over Modbus that needs more uses config raw or J1939 `rx` entries.

### 4. Network info and cyclic job table

Network info, 18 input registers per network, for networks 0-7: CAN state (high) and bus load % (low), TX errors, RX errors, bus-off count (2), RX count (2), TX count (2), error frames (2), J1939 state (high) and address (low), NAME (4, high word first), ECU count, an update counter. A network without a J1939 view has 0xFF in the J1939 state byte and the J1939 ERROR_ID in the address byte (1 not running, 10 not a J1939 network), so `J1939_ECU_INFO` can tell why. `CAN_BUS_INFO` and `J1939_ECU_INFO` read it without a request.

Cyclic job table: a tick word, then 4 input registers per job: state (high: 0 free, 1 active, 2 error) and ERROR_ID (low), the job's generation, frame count (2). The generation tells a block whether the slot is still its own job. Plus one holding register per job, the keepalive: the job's block writes the scan counter there on every call. The bridge sends the job's frame from its own timer every `PERIOD`. A job whose keepalive has not changed for 1 s is stopped and freed, so a block that is no longer called does not leave a frame running.

### 5. Program-owned resources follow the link

When the PLC link header (change 1) enters stopped or mismatch, or the output watchdog fires, the bridge cancels every busy request operation (ERROR_ID 8 or the family's equivalent), stops every cyclic job, closes every receiver and clears the receive mailbox. A network restart cancels the jobs and receivers of that network. This is the plugin's "a PLC stop ends every job and closes every receiver", now driven by the link. For a client without the PLC link header (a non-OpenPLC PLC), the watchdog is the trigger.

### 6. `canworks.link` grows to 1280 words

ST has no arrays of configurable size in a block's in-out, so `LINK` gets one fixed size large enough for the most a config can have:

| Words | Content |
|---|---|
| 0-88 | change 1 (status, control, SDO registers, flags, owners, live lists), unchanged |
| 89 | mailbox flags: request mailbox count (bits 0-2), receive mailbox (bit 4), network info (bit 5), cyclic job count (bits 8-12) |
| 90 | scan counter (incremented by `CW_LINK_SERVICE`) |
| 91-93 | last ticket, lowest waiting ticket this scan, lowest waiting ticket last scan |
| 94-101 | request mailbox owners (4) and owner stamps (4) |
| 102-104 | receive acknowledgement (out): sequence, pending (2, word 103 bits 31-16) |
| 105 | the last batch `CW_LINK_SERVICE` saw |
| 106-127 | reserved |
| 128-143 | cyclic keepalive (out), one per job |
| 144-719 | request mailbox m (m 0-3) at 144 + 144m: request 72 words, then response 72 words |
| 720-839 | receive mailbox |
| 840-983 | network info, network n at 840 + 18n |
| 984-1048 | cyclic job table: tick, then job j at 985 + 4j |
| 1049-1279 | reserved |

`canworks_in` copies input words into their places and calls the new library block `CW_LINK_SERVICE(LINK)` first; `canworks_out` copies the out words to the holding registers. Words of blocks the config does not have stay 0 and their flags are clear. Change 1's blocks only change their declared bound from 88 to 1279.

### 7. Sharing the request mailboxes

A block that needs a mailbox takes a ticket (word 91, incremented). Ticket comparisons wrap: ticket a is before b when `(a - b) AND 16#8000` is set. On each call while waiting it writes its ticket into word 92 when it is lower than what is there. `CW_LINK_SERVICE` moves word 92 to 93 at the start of the next scan. A waiting block whose ticket equals word 93 takes the first free mailbox. So mailboxes go to waiting instances in the order they started, and an instance that stops being called simply drops out of the order. The owner keeps the mailbox for its whole transaction (STAGE..., the operation, FETCH...) and stamps word 98 + m with the scan counter on every call. `CW_LINK_SERVICE` frees a mailbox whose owner has not stamped it for 100 scans; the bridge finishes or times out what it was doing before it takes that mailbox's next counter.

Change 1's SDO and control block owners (words 22-23) keep their own simpler owner rule.

Each block keeps its own timeout: the bridge gets `TIMEOUT` with the operation and ends it on the bus side; the block also gives up 2 s after the bridge's own limit if no answer came (ERROR_ID 20 when the link is not ok, else the family's timeout ID). Waiting for a mailbox does not count against `TIMEOUT`.

### 8. Map, groups and requests per poll

`bridge.mailboxes` places its blocks in one contiguous input area and one contiguous output area:

- input: responses (144 bytes per mailbox), receive mailbox (240 bytes), network info (36 bytes per network, first 8), cyclic table (a 2-byte tick and 8 bytes per job);
- output: requests (144 bytes per mailbox), acknowledgement (6 bytes), keepalives (2 bytes per job).

`input_location` and `output_location` are required and must be even bytes; Pack for Modbus places each area as a whole after the other bridge blocks, and the configurator's Suggest finds a free place for one area. Each block is one located value for the map hash, so a program built without mailboxes or with another count is refused like any other map mismatch.

Change 1's group rule gets one addition: a group is never cut inside a mailbox block or a network info block. With one request mailbox, the receive mailbox, two networks and 8 cyclic jobs a poll grows by about three read requests and one write request (*estimate*); the configurator shows the count against change 1's budget of 40.

### 9. Engine services and change 2

Change 2 removes the C ABI tables and the PLC-thread glue of the plugin's blocks. The engine-side services they called (listed under Context) are what the mailboxes drive; they move to a host-neutral place (`plugin/src/can/jobs/` or similar, decided in change 2's apply) and keep their behaviour: queues, limits, echo confirmation, protocol identifier guards, `raw.program_override_protocol`, transport protocol handling. If change 2 has already deleted one of them when this change is applied, task 2.1 restores it from git history rather than writing it anew.

### 10. The blocks

Plain ST in `library/modbus/`, one file per block, sharing helper blocks: `CW_MB_CALL` (ticket, owner stamp and the counter handshake of one request), `CW_SDO_XFER` (an SDO transfer with STAGE and FETCH), `CW_REQUEST` (any other operation with STAGE and FETCH) and `CW_RX` (a receiver: open, records of the current batch, pending mark, close, reopen after a retryable ERROR_ID), and the functions `CW_CHAR` and `CW_CHAR_CODE` (character and code by table, as STruC++ has no CHAR conversions). Pins are the plugin's pins plus the in-out `LINK : ARRAY[0..1279] OF WORD`; data pins stay in-out arrays of today's sizes (`ARRAY[0..7] OF BYTE`, `ARRAY[0..1023] OF BYTE`, `ARRAY[0..1784] OF BYTE`, `ARRAY[0..31] OF UDINT`, `ARRAY[0..4] OF BYTE`). The EXECUTE and ENABLE behaviour stays as the plugin's specs wrote it. Receivers and cyclic jobs are opened with RX_OPEN and CYCLIC_SET on the rising edge of `ENABLE` (and again while a retryable ERROR_ID holds), so their set-up costs one round trip; `CAN_SEND_CYCLIC` sends CYCLIC_SET again only when `DATA`, `DLC` or `PERIOD` changed.

ERROR_IDs: each family keeps its numbers; "the plugin is not loaded" now means "the network is not running"; 20 (bridge not reachable) and 22 (the config has no such bridge block: no mailboxes, no receive mailbox, no network info, no cyclic job table, or a network past the first 8 for info) are added to every family; 5/9 (no free receiver or job) also covers the 32-receiver and 16-job limits of the link.

### 11. Any Modbus PLC

The blocks use only IEC 61131-3 standard functions and `TON`, and `LINK` is a word array, so they compile on any runtime that can hold a 1280-word array and call the blocks every scan. For PLCs other than OpenPLC:

- `canworks-deploy library --format st --out DIR` writes every source of the library as `.st` files, one per block or function, with a version header: the bridge blocks, their helpers, `CW_LINK_SERVICE`, the CAN and J1939 helpers and change 1's REAL word helpers (`CW_DWORD_TO_REAL` and friends, already plain ST bit arithmetic). PLCopen XML output is not part of this change; it comes in the following change `add-plcopen-export`, which will cover these blocks too.
- For a config with the PLC link (`bridge.openplc`, which gives the map hash and the PLC link header), `--export-modbus-map OUT.st` writes the PLC link for that PLC instead of the plain variable list: a global variable list `canworks` with `ok`, `link`, the channel variables `in_w : ARRAY[0..n] OF WORD` (input registers from 0) and `out_w` (holding registers from 0) and the typed values; the client channels to map onto `in_w` and `out_w`; and `canworks_in` and `canworks_out`, the same code as change 1 generates with `canworks.in_w[r]` and `canworks.out_w[r]` in place of the `%IW`/`%QW` words. A config without the PLC link keeps the plain variable list.

### 12. Configurator

The Modbus bridge page of a bridge or OpenPLC config gets a **Function blocks** section, next to the SDO bridge whose place it shares: a switch, request mailboxes (0-4), receive mailbox on or off, cyclic jobs (0-16), network info on or off, the input and output area with Suggest, a line with the registers it takes (and, for OpenPLC, the requests per poll of the whole map against the budget of 40), and which blocks need which part. For OpenPLC a count change moves both areas to a free place at once; another client keeps its places until Suggest, since its channels name them. New OpenPLC configs (and a switch to OpenPLC) start with it on: one request mailbox, receive mailbox, 4 cyclic jobs, network info. For OpenPLC the page says that a change needs **Update declarations** (Save does it in a project opened in the configurator) and a new Build.

## Risks / Trade-offs

- Latency: each block call that needs an answer costs about two polls before the CAN side starts. Programs that sent many short frames per scan with `CAN_SEND` will be slower; the docs point them to config raw messages and `CAN_SEND_CYCLIC`.
- Receive throughput: about 8 short records per round trip, so about 300-400 per second (*estimate*). Bursts are absorbed by the bridge FIFOs; sustained higher rates overflow and are counted.
- STruC++ 0.7.0 passes an in-out array by copying it into the block instance and back on every call (nested helper calls too), so each block call moves `LINK` (2.5 KB) a few times: 40 busy instances cost about 0.2 ms per scan at -O2 on an x86 runner (task 1.1). Fine for OpenPLC's 20 ms task on the Linux device; a program with hundreds of instances should share fewer. `LINK` is also copied every scan by the generated programs; on the Linux device that is negligible, on a small PLC it may not be (stated in the docs).
- Fixed limits of the link (4 mailboxes, 32 receivers, 16 cyclic jobs, info for 8 networks) are lower than the plugin's per-network limits; the configurator and docs say so.
- Ordering by tickets assumes all instances run in one task (OpenPLC's one task). Several tasks of another PLC may interleave; the blocks stay correct but the order is then per task.

## Migration Plan

Nothing in use. Programs that used the plugin's blocks get the same block names with the extra `LINK := canworks.link` argument; ERROR_ID 1 means the network is not running. Existing bridge configs without `mailboxes` behave as before.

## Open Questions

None for Toni. Spike items in tasks 1.x (STruC++ with a 1280-word in-out array and many instances, the editor's handling of a large global array, the ST sources in CODESYS).
