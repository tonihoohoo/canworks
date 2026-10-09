## Why

The first hardware run of `add-raw-can` (tasks 9.1-9.3, a Raspberry Pi with a USB adapter and one CANopen device on the bus) found five bugs:
- `CAN_SEND` always ended with `ERROR_ID` 6: the raw thread read its clock before writing the frame, and the echo expiry in the same pass took the earlier time as long ago (unsigned wrap).
- `CAN_SEND_CYCLIC` and `CAN_RECEIVE` with `ENABLE := TRUE` from the first scan stayed dead: they start only on the rising edge, and on the first scan the network is not running yet (`ERROR_ID` 1).
- A network with `protocol: none` also started a CANopen master on its interface.
- USB adapters that echo sent frames were treated as not echoing: `SIOCGIFFLAGS` returns 16 flag bits and `IFF_ECHO` is bit 18.
- Frames another program on the PLC host sent (`cansend`) reached config messages but not `CAN_RECEIVE` or the received count.

## What Changes

- Echo expiry ignores frames written after the time it was given.
- `CAN_SEND_CYCLIC` and `CAN_RECEIVE` whose `ENABLE` stays TRUE try to start again on every call after `ERROR_ID` 1, 7 or 8 (not running, bus-off, cancelled). Other errors still need a new rising edge.
- The CANopen runtime starts masters only on CANopen networks.
- Echo support is read from `/sys/class/net/<interface>/flags`.
- On a plain CAN network, frames from other sockets on the PLC host count as received frames for program receivers and counts. On a CANopen or J1939 network they still do not, because the kernel marks the protocol's own frames the same way.

## Impact

- Specs: `can-plc-frames` (cyclic frames, receivers).
- Code: `plugin/src/can/raw/` (plc_frames, raw_io, raw_link, raw_runtime), `plugin/src/canopen/canopen_runtime.cpp`, `library/generate.py` and `library/src/can_common.inc` (regenerated blocks and editor library).
- Docs: `docs/raw-can.md`.
