# canworks as a CANopen slave

canworks-bridge as node 10 on a network another master runs (`"role": "slave"`, [docs/slave.md](../../docs/slave.md)). The master writes a speed setpoint, a mode and a run bit, which a Modbus client (OpenPLC through Modbus, another PLC or a script) reads; the client answers with the actual speed, a status word and a temperature, and sends an EMCY while the temperature is too high.

| File | What it is |
|---|---|
| `slave_eds.json` | The description the EDS is generated from: identity, heartbeat and the six objects. |
| `openplc-slave.eds` | The slave's EDS, written by `canworks-deploy slave-eds config/slave/slave_eds.json -o config/slave/openplc-slave.eds`. The bridge runs it, and the other master's tool imports the same file. |
| `canopen_config.json` | One slave network `line` on `vcan1`: node ID 10, the six objects bound to bridge locations, the status and EMCY locations. |

## The dictionary

| Object | Name | Type | Access | Bridge |
|---|---|---|---|---|
| 0x2000:1 | speed_setpoint | UNSIGNED16 | rww | `%IW300` |
| 0x2001:1 | mode | UNSIGNED8 | rww | `%IB302` |
| 0x2002:1 | run | BOOLEAN | rww | `%IX303.0` |
| 0x2100:1 | actual_speed | UNSIGNED16 | ro | `%QW300` |
| 0x2100:2 | status_word | UNSIGNED16 | ro | `%QW302` |
| 0x2101:1 | temperature | INTEGER16 | ro | `%QW304` |

RPDO 1 (`0x200` + node ID) carries the three objects from the master, TPDO 1 (`0x180` + node ID) the three to the master, both with transmission type 255; the master may remap them. The slave's heartbeat is 500 ms (0x1017 in the description).

## Status for the client

| Location | Meaning |
|---|---|
| `%IB304` | own NMT state: 5 operational, 127 pre-operational, 4 stopped |
| `%IX303.1` | communication OK: operational and no heartbeat consumer error |
| `%IW306` | SYNCs received |
| `%QW306`, `%QB308` | EMCY code and error register the client sends |

`inputs_on_loss` is `"zero"`: while the master is gone the three inputs read 0, so a client that ramps the speed stops.
