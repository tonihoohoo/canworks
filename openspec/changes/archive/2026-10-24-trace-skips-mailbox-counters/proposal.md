## Why

The Pi check 7.3 of `add-modbus-traffic-view` (2026-10-24) showed that **Only changes** barely shrinks a Modbus trace of OpenPLC: all 2994 writes of holding registers 3-94 in 60 s were recorded. A few mailbox words change on their own, so almost every request differs from the previous one:

- each `CAN_SEND_CYCLIC` adds 1 to its job's keepalive holding register every PLC scan;
- the receive mailbox (word 4 of its first block) and the cyclic job table (word 0) carry the bridge's millisecond clock, so every read of them differs.

These words say "the client is alive" and "the bridge is alive", not that something happened. Recording every request because of them fills the ring and buries the requests that matter. Toni (2026-10-24): "Yes" to leaving the keepalive out of the comparison, then "Propose".

## What Changes

- **The change filter leaves the self-changing mailbox words out.** When the bridge compares a request with the previous one of its kind, it leaves out the keepalive holding registers and the two clock words in the input area. A request whose only difference is in those words is counted and not recorded, like an unchanged one. Any other change is still recorded in full, with the current keepalive and clock values in it.
- **A single-register write back to an earlier value is a change.** Found while writing the tests: for functions 5 and 6 the filter took the value as part of the kind, so writing 7, 8, 7 to one register skipped the second 7. The kind of those functions is now their address only.
- **Nothing else changes.** Without **Only changes** every request is recorded as today. Exceptions, refused writes and functions 8 and 43 are still always recorded. The record format, the operations and the PC tools stay the same.
- **Docs.** `docs/modbus-bridge.md` "Seeing the Modbus traffic" and `docs/trace.md` say which words the comparison leaves out, and that turning **Only changes** off records every request.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `modbus-bridge`: the Modbus trace recorder's change filter leaves out the keepalive registers and the mailbox clock words.

## Impact

- `plugin/src/bridge/modbus_trace.{h,cpp}`: the hash of a request's data leaves out given holding and input registers (functions 3, 4, 6, 16 and 23).
- `plugin/src/bridge/bridge_host.cpp`: hands the trace the registers from the mailbox layout when the bridge starts.
- `test/bridge/`: tests for a write where only a keepalive changes, a read where only the clock changes, and a change beside them.
- Docs: `docs/modbus-bridge.md`, `docs/trace.md`.
- Tools version bump (bridge build in the tools package). No config change, no Pi config change.
