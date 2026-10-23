## Why

The receive mailbox moves at most 7 CAN frames per batch, and with the OpenPLC Modbus master a batch takes two poll cycles: the master reads every group first and writes the acknowledgement afterwards, so the next batch can only be read one cycle later. With the default 10 ms poll that caps `CAN_RECEIVE` at about 350 frames/s (210-340 with a 20 ms PLC task), measured on 2026-10-23 with the pinned runtime's own Modbus master against simulated nodes offering 1000 frames/s (research/mailbox-performance-2026-10-23.md). The bridge itself adds about 1 ms, so throughput can only grow by moving more records per poll cycle.

Each CAN record is 14 words, 4 of them a per-frame UTC timestamp a PLC program almost never needs. The receive area is one 120-register block, the most one Modbus read can carry.

Toni asked for an explore of mailbox performance (2026-10-23) and chose this change: smaller records now, and a second receive block as an option, without multi-frame sending.

## What Changes

- **Smaller records (BREAKING for the record format).** The batch header gets the batch time: the UTC receive time, in microseconds, of the batch's first record (header 21 → 25 words). CAN records drop their own receive time (14 → 10 words) and J1939 records too (16 → 12). One 120-register block then carries 9 CAN frames instead of 7 (+29 %). EMCY records keep their own time (12 words), since an EMCY's time matters and EMCYs are rare. `CAN_RECEIVE` and `J1939_RECEIVE` report the batch time in `TIMESTAMP`, accurate to about one poll.
- **A second receive block.** `bridge.mailboxes.receive_blocks` (1 or 2, default 1) gives the receive mailbox 120 or 240 input registers, read as one or two Modbus requests. One batch spans both blocks: 21 CAN frames per batch, about 1050 frames/s at a 10 ms poll (×3 today). `canworks.link` keeps `ARRAY[0..1279] OF WORD`: the receive mailbox gets words 720-959 whatever the setting, and the network info and cyclic job table move up by 120 words. A third or fourth block would need a bigger `LINK`, which every block copies on every call. That's not worth it now.
- **Configurator.** The Function blocks section shows receive blocks 1 or 2 next to the receive switch, and the expected receive rate at the config's poll, "about N CAN frames/s".
- **No multi-frame send.** `CAN_SEND_CYCLIC` covers periodic frames, and single sends reach about 50 frames/s per request mailbox. Revisit when a program needs bursts.
- **Docs and README.** State the throughput rule (records per batch × poll rate / 2) and the numbers, replacing "a few hundred frames per second". Correct `TIMESTAMP`'s description for `CAN_RECEIVE` and `J1939_RECEIVE`.

Not in real use, so this is a clean cut: no old record format and no conversion.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `modbus-bridge-mailboxes`: `receive_blocks`, the batch time in the header, the smaller CAN and J1939 records.
- `bridge-plc-blocks`: `CAN_RECEIVE` and `J1939_RECEIVE` report the batch time.
- `canopen-configurator`: the Function blocks section's receive blocks and expected rate.

## Impact

- Bridge: `plugin/src/bridge/mailboxes.{h,cpp}` (header, record encoding, receive area size), `plugin/src/can/config.cpp` (`receive_blocks`), C++ mailbox tests.
- PC tools: `mailboxlayout.py` (receive block sizes, `LINK` places), `openplcmodbus.py` / map export (one more read group with 2 blocks; the generated `canworks_in` copy code), configurator page, version bump (minor).
- Library: `CW_RX` (record sizes, header 25 words, walk to word 960), `CAN_RECEIVE`, `J1939_RECEIVE` (TIMESTAMP from the header), `CW_LINK_SERVICE` and every block that reads network info or the cyclic table (new `LINK` places); the ST mailbox model and tests.
- Integration test: the receive-rate measurement as a check (1 and 2 blocks).
- Ordering: after `modbus-connections` (bridge config and exports) and before `add-nodered-blocks`, which mirrors the mailbox layout.
