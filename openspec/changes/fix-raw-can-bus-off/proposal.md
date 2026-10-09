## Why

A bus-off test on the bench (a plain CAN network at 250 kbit/s on a 500 kbit/s bus, the USB adapter the only device sending) passed for `CAN_BUS_INFO` and `CAN_SEND`, but found three gaps:
- `CAN_SEND_CYCLIC` and `CAN_RECEIVE` stayed `ACTIVE` with no error for the whole bus-off: the bus state is checked only when they start, so the program cannot tell a dead bus from a quiet one.
- A plain CAN network logged nothing about bus state; a CANopen network logs every change.
- The docs and the bus-off log line said bus-off lasts until the interface is restarted. The test adapter (gs_usb firmware) leaves bus-off by itself about 2000 times a second, with `restart_ms` unset.

## What Changes

- While the bus is off or the interface down, a running `CAN_SEND_CYCLIC` or `CAN_RECEIVE` shows `ERROR` with `ERROR_ID` 7 and stays `ACTIVE`; the error clears by itself when the bus is back. The block interface's receive info gains a `bus_down` byte (in the struct's padding; not in real use, clean cut).
- Plain CAN networks log bus state changes with the CANopen master's wording and throttle.
- The bus-off log line and docs say some adapters recover by themselves.

## Impact

- Specs: `can-plc-frames` (cyclic frames, receivers), `can-raw-messages` (bus state log).
- Code: `plugin/src/can/can_plc_api.h`, `plugin/src/can/raw/` (plc_frames, raw_io, raw_runtime), `plugin/src/canopen/bus_monitor.cpp`, `library/generate.py` and `library/src/can_common.inc` (regenerated blocks and editor library, tools 0.46.4).
- Docs: `docs/raw-can.md`, `docs/config.md`.
