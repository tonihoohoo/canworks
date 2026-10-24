## Context

`ModbusTrace::record` (plugin/src/bridge/modbus_trace.cpp) keys each request by its first 5 bytes (function, start, count) and hashes the rest of the request, the answer and the unit. With changes only, a request whose hash equals the last one of its kind from that connection is counted, not kept. The mailbox layout (`MailboxLayout` in mailboxes.h) knows where the self-changing words are:

- `keepalive(j)`: one holding register per cyclic job, written by `CAN_SEND_CYCLIC` every scan;
- `receive_block() + 8` (word 4): the receive mailbox's clock;
- `cyclic_table()` (word 0): the cyclic job table's clock.

The response blocks also carry the clock, but only in an answer the bridge writes once when an operation finishes, so they change only when something happened.

## Goals / Non-Goals

**Goals:** a trace of an idle OpenPLC program with cyclic jobs or a receive mailbox keeps a few records a second, not every request; no change to what is recorded once a request is kept.

**Non-Goals:** a user-set list of words to ignore; leaving out the network info update counter (it changes when the bus state does, which is worth a record); bit functions (1, 2, 5, 15), since the mailbox words are registers.

## Decisions

1. **The filter is in the bridge, from the layout.** The bridge hands `ModbusTrace` two sorted lists of register numbers when it starts: holding registers (keepalives) and input registers (the two clocks). Nothing is configured, and the PC tools need no change. *Alternative:* filter on the PC. Rejected, because the records would still fill the bridge's 4 MiB ring and the network.
2. **Leave the words out of the hash, not out of the record.** For functions 3 and 4 the answer's data bytes, for 6 and 16 the request's data bytes, and for 23 both are hashed register by register, skipping the listed ones. A record that is kept still carries every byte, so the Trace view shows the current keepalive and clock values.
3. **The key stays the same.** Function, start and count still decide the kind, so a request whose range only holds ignored words is counted after its first record, like any unchanged request.

## Risks / Trade-offs

- A client whose keepalive stops changing (a cyclic job that is about to be stopped) is not visible in a changes-only trace. The cyclic job table and the bridge log say when a job is stopped, and turning **Only changes** off records every request.
- The hash loop gets a check per register. It runs only while a trace runs, and a request has at most 125 registers.
