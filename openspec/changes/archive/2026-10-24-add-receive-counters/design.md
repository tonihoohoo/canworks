## Context

The bridge already has one per-frame hook for received PDOs: `Network::OnRpdo` (`plugin/src/canopen/network.cpp`) runs for every frame of a mapped RPDO of the master, sets `last_rx` for the timeout check and arms the SYNC bookkeeping. Values reach the byte image through Lely's object writes. J1939 receive goes through `j1939_network.cpp`, which already writes `status_location` into the image per entry. Raw CAN `rx` has `counter_location` since the raw messages change.

## Goals / Non-Goals

**Goals:** count received PDO frames and J1939 messages per configured message, with the field name and wrap rule of raw CAN, at one register per counted message and no cost for others.

**Non-Goals:** latching pulses, per-message timestamps, EMCY or heartbeat counters, counters on PDOs the master sends.

## Decisions

1. **Name and type: `counter_location`, `%IW`, wraps at 65535.** Same as `raw.rx`, so a program uses one rule (`new := counter - last` in UINT arithmetic) everywhere. A double word was considered; at 1 kHz a word wraps after 65 s, far longer than any poll.
2. **What counts.** A PDO frame counts when Lely reports it without error (`ec` false in `OnRpdo`), that is when it was long enough to update the inputs. A short PDO does not count; it is logged as today. A J1939 entry counts each message it takes (after its source filter), a TP or ETP message once when complete. Counting every frame of the COB-ID was rejected: a short frame changes no value, so counting it would make "counter moved" mean nothing to the program.
3. **Where it is counted and written.** `OnRpdo` runs with the master locked and after Lely's object writes (`OnRpdoWrite`, which defers the image update), so it defers the count too: the deferred handlers run in order, and the counter reaches the image with or after the frame's values. While the program holds the network stopped, the values are not updated and the frames are not counted. The J1939 path increments and writes next to `status_location`.
4. **When it resets.** The count starts at 0 when the bridge starts and is not reset by a node loss, a timeout, a CANopen session restart or the PLC link stopping: the program works with differences, and a jump back to 0 would look like 65536 frames. A bridge restart is visible through the map hash and status block.
5. **Simulated bus and local runtime.** The simulated bus runs the same `Network` code, and the local runtime runs the bridge image, so both count like a real bus with no code of their own.
6. **CODESYS target.** CODESYS projects map PDOs into CODESYS's own CANopen manager and have no locations; the configurator does not offer the field there and the check treats it like any other location on a project without locations.
7. **Bridge lost.** On the generated OpenPLC programs a counter is a `*_location` like the status values, so it reads 0 while `canworks.ok` is FALSE, as `raw.rx[].counter_location` already does; programs compare counts while `canworks.ok` is TRUE.

## Risks / Trade-offs

- A config that sets counters on many messages adds registers; each is 2 bytes and packed with the other inputs, so a request is added only past 125 registers. Noted in docs, no extra warning.
- A counter does not say what the merged frames carried. Programs that need every value use `CAN_RECEIVE` on the COB-ID (docs say so).

## Migration Plan

None: new optional field. Not in real use.
