## Context

Explore notes: `research/mailbox-performance-2026-10-23.md`. Measured with test/openplc_modbus/run.py's rig: the pinned runtime v4.3.1's `ModbusSlaveDevice` against canworks-bridge, the example's simulated nodes sending a TPDO on every 2 ms SYNC (about 1000 frames/s), and a Python PLC scan that drains and acknowledges each batch:

| poll | scan | frames/s | batches/s |
|---|---|---|---|
| 10 ms | 20 ms | 212-337 | 30-48 |
| 10 ms | ≤10 ms | 340-344 | 49 |
| 5 ms | ≤5 ms | 671-677 | 96-97 |

Every batch was full (7 records). The runtime's master runs, in each cycle, all reads and then all writes (`modbus_master_plugin.py`, phase 1 reads, phase 2 writes), so an acknowledgement written in cycle k+1 shows the next batch in cycle k+2. The bridge's own part is under 1 ms: its loop runs every 1 ms and `build_batch` runs right after it sees the acknowledgement.

    receive rate = records per batch × poll rate / 2

## Goals / Non-Goals

- Goal: more records per poll cycle at no cost for configs that don't need it, and a known, documented rate.
- Non-goal: a bigger `LINK`, multi-frame send, faster polling (`openplc.poll_ms` is already a setting), a ring buffer or double buffering (same area, same rate).

## Decisions

### Batch time instead of per-record time (CAN, J1939)

The header grows from 21 to 25 words: words 21-24 hold the batch time, the 64-bit UTC µs receive time of the batch's first record (the oldest, since records are picked oldest first). CAN records become `hdr, queued, dropped, id_hi, id_lo, fmt<<8|dlc, d0d1, d2d3, d4d5, d6d7` (10 words). J1939 records become `hdr, queued, dropped, pgn_hi, pgn_lo, src<<8|dst, priority, length, d0d1, d2d3, d4d5, d6d7` (12 words, today's fields without the time). EMCY stays at 12 words with its own time: EMCYs are rare, and their time is part of the EMCY history the CANopen side already keeps.

Records per batch, with 1 block (95 record words) and 2 blocks (215): CAN 9 / 21, J1939 7 / 17, EMCY 7 / 17.

The alternative was keeping a 2-word µs offset per record. That gives 12-word CAN records, only 7 per block, so no gain. Rejected.

### `receive_blocks` 1 or 2, `LINK` unchanged

The second block sits right after the first in the Modbus input area and in `LINK` (words 720-959). The network info moves from 840 + 18n to 960 + 18n and the cyclic table from 984 to 1104 (tick), with jobs at 1105 + 4j, up to 1168. `LINK` stays `ARRAY[0..1279]`, so no spec or generated declaration changes its bound. Those places are fixed, whatever the setting. With one block, words 840-959 stay 0 and `CW_RX` never reads them, because it walks only `LINK[723]` record words.

Three or four blocks would need `LINK` beyond 1279. STruC++ copies the in-out array in and out on every block call, so every instance would pay that cost. Rejected for now, and the explore's ×6 option is out.

Each block is its own map block ("bridge.mailbox.receive.0", ".1"), so OpenPLC's groups and the suggested client channels read each with one request (≤125 registers). The map hash covers the new blocks as it does every located block.

### Expected rate in the configurator

`records(kind CAN, blocks) × 1000 / poll_ms / 2`, shown as "about N CAN frames/s at this poll". The figure is only shown for OpenPLC configs, which have a known poll. Other clients get the rule in words: "9 CAN frames per batch, one batch per two of your client's polls".

## Risks / Trade-offs

- `TIMESTAMP` of `CAN_RECEIVE` and `J1939_RECEIVE` loses per-frame precision: frames of one batch share a time. A program that measures frame-to-frame timing must use the trace instead. The docs say so.
- `add-nodered-blocks` mirrors this layout. If it lands first, it has to follow. The ordering puts this change before it.
- A config with `receive_blocks: 2` costs one more Modbus request per poll. The Function blocks section counts it against the 40-request budget.

## Migration Plan

Clean cut (not in real use). Configs without `receive_blocks` get 1. Update declarations and a rebuild pick up the new `LINK` places, and the configurator already tells OpenPLC users to do both when mailboxes change. Bridge and library versions must match, as with every mailbox change: the map hash already refuses a program built for another layout.

## Open Questions

None.
