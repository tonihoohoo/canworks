# OpenPLC as a CANopen gateway

OpenPLC as the master of a field network and a slave on an upper network in one config ([docs/gateway.md](../../docs/gateway.md)). The plugin copies values between the two at bus speed, without the PLC program.

| File | What it is |
|---|---|
| `cpp-slave.eds` | The field node: the Lely tutorial ping-pong slave, as in `config/pingpong`. |
| `gateway_eds.json` | The description of the gateway's own objects (one bit the program writes). |
| `openplc-gateway.eds` | The gateway's EDS on the upper network, written by `canworks-deploy slave-eds config/gateway/gateway_eds.json -o config/gateway/openplc-gateway.eds --gateway config/gateway/canopen_config.json`: the description's object, a slave object per route, the field node status and the SDO bridge record. |
| `canopen_config.json` | Network `field` (master, `vcan0`, node 2) and network `upper` (slave, `vcan1`, node ID 20), and the gateway section. |

## Routes

| Route | Slave object | Field entry | Direction |
|---|---|---|---|
| `pong` | 0x2101:1 (ro) | node 2 TPDO entry 0x4001 | up: the node's value goes to the upper master |
| `ping` | 0x2000:1 (rww) | node 2 RPDO entry 0x4000 | down: the upper master's value goes to the node |

The node's TPDO entry also has a PLC location (`%ID100`), so the program sees the value the route sends up. The RPDO entry the `ping` route writes has no location: one writer per object.

`status` puts node 2's NMT state at 0x5E00:2 and its operational bit in 0x5E10:1; `emcy_forward` sends node 2's EMCYs on the upper network; `on_upper_loss` `"zero"` sends 0 to node 2 when the upper master is lost; `sdo_bridge` lets the upper master read node 2's objects through 0x5F00.
