## Why

Many CAN devices send several layouts on one identifier: a selector signal (usually byte 0) says which "page" a frame is, and the other signals are only valid for their page. DBC files describe this as multiplexing: simple (`M` / `mN`) and extended (`SG_MUL_VAL_`, nested switches, value ranges). Displays, battery packs, sensors and many J1939 proprietary PGNs use it.

canworks cannot use those messages today:
- the plugin writes every signal of a matching frame, so a multiplexed message writes page 1 bytes into page 2 variables
- the raw CAN DBC import drops multiplexed signals and the J1939 import skips multiplexed messages
- DBC export of raw and J1939 messages cannot write multiplexing
- the J1939 trace decodes every page of a multiplexed DBC message at once, so it shows wrong values for the pages not in the frame

The exploration of 2026-10-10 (project notes `research/multiplexed-signals-2026-10-10.md`) settled the scope with Toni:
- raw CAN and J1939 in **one** change (the signal code is shared)
- **extended** multiplexing included, not only simple
- a multiplexed send message is sent with the page the **program** picks unless the config says otherwise
- the J1939 trace fix rides in this change

## What Changes

- **Config** (schema version 2, `raw_signal` and `j1939_signal`):
  - `multiplexer: true` marks a switch signal
  - `mux: {"on": "<switch>", "values": [3, [5, 9]]}` makes a signal valid only when the switch has one of the values or ranges; `on` may be left out when the message has one switch
  - a signal can have both (a nested switch), which is extended multiplexing
  - `valid_location` (%IX) on received raw signals, as J1939 already has
  - `pages` on send entries (`raw.tx`, `j1939.tx`): `"program"` (default), `"all"` or `"rotate"`
  - overlap and length checks are made per page; J1939's "signals SHALL NOT overlap" and raw's overlap warning apply only to signals that can be in the same frame
- **Runtime plugin** (a new shared `plugin/src/can/mux.*`, raw engine, J1939 runtime):
  - receive: a frame updates the always-present signals, the switches and the active page's signals; the rest hold their last value; `valid_location` of a multiplexed signal is FALSE until its page arrives and after `timeout_ms` without it
  - unknown switch values are counted in diagnostics and update only the always-present signals and the switches
  - send: `program` packs the page the switch outputs select; `all` sends every page each period; `rotate` sends the next page each period; `on_change` sends only pages whose signals changed; J1939 requests are answered the same way
- **PC tools**:
  - DBC import (raw and J1939) brings multiplexed signals in; a DBC with several switches and no `SG_MUL_VAL_` is named as a problem
  - DBC export (raw and J1939) writes `M`, `mN`, `mNM` and `SG_MUL_VAL_`
  - contract checks with the plugin's messages, from shared fixtures
- **Configurator**: signal rows gain "Switch" and "Page" columns, the bit grid shows one page at a time with a page picker, send entries get the `pages` choice; the same on the J1939 page.
- **Bus trace and frame inspector**: only the active page's signals are decoded and the row names the page; an unknown page is shown, not hidden; graph series of a multiplexed signal get points only from frames of its page. This fixes the J1939 trace showing every page.
- **Simulator**: raw devices and `canworks-j1939-sim` send multiplexed messages page by page (`all` by default, `rotate` on request).
- **Docs**: `docs/raw-can.md`, `docs/j1939.md`, README limits.

## Capabilities

### New Capabilities
- `can-multiplexed-signals`: the multiplexing fields, their checks and the runtime receive and send behaviour, shared by raw CAN and J1939.

### Modified Capabilities
- `can-raw-messages`: raw signals take the multiplexing fields and `valid_location`; the short-frame rule is per page.
- `j1939-config`: J1939 signals take the multiplexing fields; overlap is checked per page.
- `j1939-pc-tools`: DBC import and export of multiplexed messages; Switch and Page in the J1939 page.
- `j1939-trace`: decoding of multiplexed J1939 messages by page.
- `j1939-simulator`: multiplexed DBC messages sent page by page.
- `canopen-configurator`: Switch and Page columns, page picker, multiplexed DBC import.
- `canopen-dbc-export`: multiplexing of raw messages in the exported DBC.
- `canopen-bus-trace`: raw decoding by page.
- `canopen-device-simulator`: multiplexed sends of plain CAN devices.
- `canopen-config-contract`: the multiplexing fields in the version 2 schema.

## Impact

- **Plugin**: a new `plugin/src/can/mux.*` has the page logic (a table built at start, no allocation on the receive path); `plugin/src/can/raw/config.*`, `raw/engine.*`; `plugin/src/j1939/j1939_config.*`, `j1939_network.*`. No new dependency.
- **PC tools**: `canworks/raw/` (contract, dbc, decode, signals, assist), `canworks/j1939/` (dbc, sim), `canworks/dbcexport.py`, `canworks/bustrace/` (decode, j1939), configurator static pages; minor version bump. cantools is already a dependency.
- **Schemas**: `canworks.v2.schema.json`, `canworks-sim.v2.schema.json` (new optional fields; configs without them are unchanged).
- **CI**: unit tests and the existing simulated-bus and vcan groups; no new job.
- **Hardware**: the bench node sends no multiplexed message, so the hardware check uses the PC adapter as a multiplexed device next to the PLC on the Pi.
- **Not in this change**: CANopen MPDO (CiA 301 multiplexed PDOs), CAN FD, multiplexed messages of the CANopen DBC export beyond today's SDO `Object` multiplexor.
