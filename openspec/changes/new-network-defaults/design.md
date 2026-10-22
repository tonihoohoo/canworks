# Design

## One table of defaults

`app.js` gets one place for the per-protocol defaults, used by every path that creates a network:

| Protocol | `adapter.bitrate` | SYNC |
|---|---|---|
| CANopen (master) | 500000 | none (no `sync_period_us`, no `sync_source`) |
| CANopen (slave) | 500000 | n/a |
| J1939 | 250000 | n/a |
| Plain CAN (`none`) | 500000 | n/a |

`server.py`'s `empty_config()` writes the CANopen row (it is the OpenPLC target's new config; CODESYS and the bridge are made from it by `switch_target`, which keeps the adapter and master as they are).

Plain CAN is not in Toni's ask. 500 kbit/s is chosen so a plain network added next to a CANopen one matches it; switch to 250 kbit/s if Toni prefers.

## Add network…

Today the new network copies the first network's rate. With rates per protocol, copying a CANopen network's 500 kbit/s into a new J1939 network would be wrong more often than right, so the new network takes its protocol's default. Each network has its own interface, so there is no shared-bus reason to copy.

## Protocol switch

Switching protocol keeps the adapter. If `adapter.bitrate` equals the old protocol's default, the user most likely never chose it, so it becomes the new protocol's default; otherwise it is kept. CANopen and plain CAN share 500 kbit/s, so only switches to or from J1939 change the rate.

## SYNC source choice

The bus page shows **SYNC source** with Off / Timer / PLC cycle, derived from the config:

- `sync_source: "plc_cycle"` → PLC cycle (shows "Every N PLC cycles"),
- `sync_period_us` > 0 → Timer (shows "SYNC period (ms)"),
- otherwise → Off (no period field).

Picking Timer writes `sync_period_us: 10000` as a starting value; emptying the period while on Timer removes it, which reads back as Off. Picking Off removes `sync_period_us`, `sync_source` and `sync_cycles`. No new config key. The CODESYS and bridge targets hide PLC cycle as today; Off and Timer stay.

## Default PDOs without SYNC

When a node is added with default PDOs on a network that produces no SYNC, each mapped PDO whose EDS transmission type (sub 2 of its communication object, resolved for the node ID) needs SYNC gets `"transmission": 255`. A read-only transmission type in the EDS is left alone and shows the existing "needs SYNC" problem, since the device cannot change it. The add message lists the PDOs that got 255. With SYNC on, nothing changes.
