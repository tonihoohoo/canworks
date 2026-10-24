## Context

OpenPLC v4.3.1's Modbus master (`core/src/drivers/plugins/python/modbus_master/modbus_master_plugin.py`, pymodbus) builds one point per I/O group of the remote device file. Each group has a `cycle_time_ms`. The plugin runs on the greatest common divisor of those times and serves a group when its cycle is due. Each read register is converted in Python and copied into the image through ctypes. Each write group goes out on every one of its cycles, with no change detection. So the master's CPU follows the registers it polls per second.

`openplcmodbus.layout` puts contiguous registers of one class in one group. Mailbox input blocks are class `bridge` today, so they can share a group with the status block and the SDO response. Pack for Modbus puts the mailbox areas last, so a split costs one or two extra groups at most.

A mailbox operation takes about two mailbox polls: the request goes out with one write and the answer comes back with a later read. The receive mailbox shows one batch every two polls, 9 CAN frames per batch with one receive block and 21 with two. The bridge closes a receiver whose batch is not acknowledged within 1 s, and stops a cyclic job whose keepalive stops for about 1 s.

Measured in the cloud (real master plugin, built bridge, Python stand-in for the image, `examples/openplc-modbus`, 10 ms poll):

| Mailboxes | Mailbox groups | Master CPU % |
|---|---|---|
| Off | n/a | 6.8 |
| Defaults | shared, 10 ms | 10.6 |
| Defaults | own, 50 ms | 7.6 |
| Defaults | own, 100 ms | 6.9 |
| 4 requests, 16 jobs | own, 100 ms | 8.0 (16.4 at 10 ms) |

## Goals / Non-Goals

**Goals:**
- OpenPLC with the default mailboxes costs close to OpenPLC without them, with mailbox blocks still answering in a fraction of a second.
- The user sees what the mailbox poll gives before picking it.
- Node-RED reads no idle mailbox part.

**Non-Goals:**
- No change to the bridge, the mailbox protocol, the ST library or the PLC's `canworks_in`/`canworks_out` copy code.
- No run-time switch for OpenPLC or truST: neither can change what it polls.
- No patch of OpenPLC's master. Write change detection there would help everyone and can be asked upstream separately.

## Decisions

**A new class `mailbox` in the layout.** Every item with `mailbox_area` in its extra gets class `mailbox`, so no group mixes mailbox blocks with anything else. Mailbox read groups keep `set-to-zero`, as today. Their `cycleTime` is `mailbox_poll_ms`; every other group keeps `poll_ms`. Alternative: a slower cycle for every `bridge` group. Rejected, because the status block drives `canworks.ok` and must stay at the poll.

**`mailbox_poll_ms` is a multiple of `poll_ms`, at most 250.** The plugin schedules on the greatest common divisor of the cycle times, so a multiple keeps the base tick at `poll_ms`; anything else would make the plugin wake more often than the data needs. 250 ms keeps four writes inside the bridge's 1 s acknowledgement and keepalive limits. The check refuses other values and names the field.

**Default: the smallest multiple of `poll_ms` that is at least 50.** At the default 10 ms poll that is 50 ms: a round trip of about 100-150 ms plus the bus, and about 90 frames per second through one receive block (210 with two). It saved most of the cost in the measurement. 100 ms saves a little more and halves the receive rate. The field is saved only when set, as for `poll_ms`.

**Requests are counted per poll.** The budget warning (above 40) counts the groups at `poll_ms` plus the mailbox groups scaled by `poll_ms / mailbox_poll_ms`, and the Settings line says it plainly: "6 Modbus requests every 10 ms, 2 more every 50 ms".

**What the hint shows.** It is computed in the browser from `mailbox_poll_ms` and `receive_blocks`:
- round trip: 2 × mailbox poll to 3 × mailbox poll, plus the bus;
- receive: frames per batch × 1000 / (2 × mailbox poll) per second.

These are the same formulas as `docs/plc-library.md`. A test keeps them in step.

**Node-RED: tag each read channel with its part.** `nodered.py` already writes `read` as `[start, count]` channels cut at mailbox block borders. It adds a third element: `null` for always, or `requests`, `receive` or `cyclic`. Network info is read always, since **canworks in** emits it. `_cycle` reads a tagged channel only while that part is busy:
- `requests`: a lease holds a mailbox, or for one poll after it ends;
- `receive`: a receiver is open, or one is closing;
- `cyclic`: a cyclic job runs.

When a part turns busy, the next cycle reads it before the job writes, so the job's counter starts from what the bridge holds (as after a connect). Alternative: a slower poll for the mailbox ranges, as for OpenPLC. Rejected, because skipping them costs nothing in latency once a part is busy.

## Risks / Trade-offs

- [The Pi saving may be smaller than the cloud's] The cloud stand-in has no PLC program. On the Pi, `canworks_in` and `canworks_out` also copy every mailbox word every scan, and that does not change. → Task 6 measures the runtime's CPU on the Pi with the default, and the docs give the measured number, whatever it is.
- [Slower receive] A program that receives a busy CAN id at 50 ms can fall behind. → The hint gives the rate, and 10 ms stays one choice away.
- [Mailbox blocks run slower than in the docs today] SDO and send timeouts default to 5 s and 1 s, far above 250 ms × 3, so no block times out because of the poll.
