## Why

When the Modbus client goes away (watchdog), the PLC stops, or the control block says idle, the bridge can stop the outputs, zero them once, hold them, or send the nodes to pre-operational. It applies the same action to every output. Some outputs need a value of their own instead: a valve that must go to 50 %, a brake that must close with a 1, a drive that must get a quick-stop command word, a speed reference that must be a set idle speed. Zero is the wrong value for those, and stopping leaves them to whatever each device does.

Commercial CAN-to-Modbus gateways offer a user-defined value per output for this case, next to hold and zero. Explore report: `research/modbus-bridge-competitors-2026-10-24.md` (gap 4). Toni (2026-10-24): "Propose 1 and 4".

## What Changes

- **New `on_client_loss` action `"safe"`.** When outputs go off, every output location is set to its safe value (0 when it has none), and the outputs keep being sent with those values: RPDOs on their SYNC or event timer, periodic J1939 and raw messages on their period, on-change messages once. The next accepted write ends outputs off. That write starts from the safe values, not from zeros or from the values before the loss.
- **`bridge.safe_values`**: an object from output location to value, such as `{ "%QW10": 500, "%QX12.0": true, "%QD20": -1.5 }`. A value is checked against what is bound at that location: integers in range, REAL objects as numbers, bits as `true`/`false`/0/1, and a bit inside a bound byte or word (a bit channel) sets only that bit. A location with nothing bound, an input location or a value out of range is refused at load. Safe values with another action are a warning: they are not used.
- **At start and at a clean stop.** With `"safe"`, a bridge sends the safe values from the start until the first writer writes (or the PLC link says running), because outputs are off until then. A clean stop (`systemctl stop`, an update) sends the safe values for one SYNC period (at least 20 ms), then `master.on_plc_stop` as now.
- **Map and docs.** The register map (CSV, JSON, ST comments, HTML document) gets a safe value column. `docs/modbus-bridge.md` documents the action, `safe_values` and a table of the five actions. README's Safe stops bullet names safe values.
- **Configurator.** The Modbus bridge page's client-loss choice gets **Safe values**. With it, a **Safe values** table lists every output value of the config (name, location, type, unit) with a safe value field, blank meaning 0. Problems warns when safe values are set but the action is another, with **Use safe values**.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `modbus-bridge`: the `"safe"` action in the output watchdog, `safe_values`, safe values at start and at a clean stop.
- `canopen-config-contract`: `on_client_loss` `"safe"` and `safe_values` in the schema (the schema list also gets `"preop"`, which it was missing).
- `modbus-bridge-map`: the safe value column.
- `canopen-configurator`: the Safe values choice, table and Problems warning.

## Impact

- Bridge: `can/config.{h,cpp}` (parse and check `safe_values` against the bindings), `bridge/bridge_host.cpp` (`enter_off`, start, clean stop, a `safe_image_` beside `clear_outputs`), tests.
- PC tools: both schema copies, `bridgecheck.py` (same checks and the warning), `modbusmap.py` and its exports, `docexport.py`, configurator `static/bridge.js`, tests.
- The PLC link, control block, mailboxes and the other four actions behave as before. Not in real use: no migration.
- CI: tests in the existing bridge and PC tools jobs.
- Tools and bridge minor version bump. Hardware check on the Pi with node 23's valve.
