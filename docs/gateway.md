# OpenPLC as a CANopen gateway

A gateway is one config with a [slave network](slave.md) (the upper network, run by another master) and one or more master networks (the field), plus a top-level `gateway` section. The plugin copies values between the two sides itself, at bus speed and without the PLC program: an upper master sees the field nodes' data as objects of one slave, and writes field outputs through it. Field node states, EMCYs and SDO access can be passed up as well.

[`config/gateway`](../config/gateway/README.md) is a complete example: the ping-pong node on the field network `field` and the gateway as node 20 on the upper network `upper`, with one route each way.

## Steps

1. Set up the field network as usual, with its nodes and PDO entries. An RPDO entry that only a route writes needs no `iec_location`.
2. Add a slave network for the upper side and a `gateway` section with `upper` naming it and one route per value.
3. Generate the upper network's EDS with the gateway objects: `openplc-canopen-deploy slave-eds description.json -o gateway.eds --gateway canopen_config.json --update-config` ([deploy.md](deploy.md#the-slave-eds)), or **Build the EDS** with **With the gateway objects** ticked in the configurator. The generator adds a slave object per route, the status ARRAYs and the SDO bridge record, and `--update-config` (the configurator always) writes each route's slave object into the config.
4. Deploy, and import the EDS into the upper master's tool.

## The `gateway` section

```json
"gateway": {
  "upper": "upper",
  "routes": [
    { "name": "pong", "slave": { "index": "0x2101", "subindex": 1 },
      "field": { "network": "field", "node": 2, "index": "0x4001", "subindex": 0 } },
    { "name": "ping", "slave": { "index": "0x2000", "subindex": 1 },
      "field": { "network": "field", "node": 2, "index": "0x4000", "subindex": 0 } }
  ],
  "status": { "index": "0x5E00" },
  "emcy_forward": true,
  "on_upper_loss": "zero",
  "sdo_bridge": true
}
```

| Field | Required | Meaning |
|---|---|---|
| `upper` | yes | The name of the slave network the upper master runs. The config needs at least one master network besides it. |
| `routes[]` | no | One value each (below). |
| `status` | no | An object: publish the field nodes' states (below). `index` defaults to 0x5E00. |
| `emcy_forward` | no | `true`: a field node's EMCY goes out as the gateway's EMCY (below). Default `false`. |
| `on_upper_loss` | no | What routed values down do when the gateway leaves OPERATIONAL or loses the upper master's heartbeat: `"hold"` (default) keeps the last values, `"zero"` sets routed field outputs to 0, `"stop_nodes"` sends NMT stop to the field nodes that receive routes and starts them again when the upper master starts the gateway. |
| `sdo_bridge` | no | `true`: the upper master reads field node objects through a record in the gateway's dictionary (below). Default `false`. |
| `sdo_bridge_index` | no | The bridge record's index, default 0x5F00. |
| `sdo_bridge_write` | no | `true`: the bridge may also write field node objects. Default `false`. |

`gateway` exists only in a `schema_version` 2 file.

## Routes

| Field | Meaning |
|---|---|
| `slave` | `index` and `subindex` of an object in the upper network's EDS. |
| `field` | `network` (a master network's name), `node` (a node ID on it), `index` and `subindex` of one of that node's PDO entries. |
| `name` | Optional. Names the slave object the generator adds for the route. |

A route from a field node's TPDO entry goes **up**: the plugin writes the value into the slave object, which must be one the upper master reads (AccessType `ro` or `rwr`). A route to a field node's RPDO entry goes **down**: the plugin reads a slave object the upper master writes (`rww` or `rw`). Both ends need the same CANopen data type. A value moves to the other network's bus thread as soon as it arrives, also while the PLC program is stopped or slow; the program is not involved.

A routed entry or slave object may also have a PLC location: an input location then shows the program the same value. An object has one writer, so the target of a route (the slave object of a route up, the RPDO entry of a route down) may not also have an output location, and one target takes one route.

## Field node status

With `status`, the gateway's dictionary has for the k-th master network in the config (k = 0 for the first master network, up to 3; a fifth master network gets a warning and no status):

| Object | Type | Content |
|---|---|---|
| `index` + k | ARRAY of UNSIGNED8, 127 sub-indices | Sub-index n: the NMT state of node n (0 while it has not booted, 4 stopped, 5 operational, 127 pre-operational). |
| `index` + 0x10 + k | ARRAY of UNSIGNED32, 4 sub-indices | Operational bits: sub-index 1 nodes 0-31, 2 nodes 32-63, 3 nodes 64-95, 4 nodes 96-127. |

Both are updated on every change and are PDO-mappable; event-driven TPDOs that map them go out on each change and once when the gateway enters OPERATIONAL. The objects of the first master network must be in the EDS; a later network whose two objects are both missing (an EDS generated before that network was added) is left out with a warning.

## EMCY forwarding

With `emcy_forward`, an EMCY from a field node is sent on the upper network as an EMCY of the gateway with the same error code and error register, and in the manufacturer bytes the field network's position among the master networks (byte 0, 0 = the first) and the node ID (byte 1). The field node's error reset clears its entry; the gateway's 0x1001 is the OR of every active field register and the program's own ([slave.md](slave.md#status-and-emcy)).

## SDO bridge

With `sdo_bridge`, the gateway's dictionary has a record at `sdo_bridge_index` (0x5F00) through which the upper master reads or writes one object of up to 4 bytes on a field node:

| Sub-index | Name | Type | Access |
|---|---|---|---|
| 1 | Network | UNSIGNED8 | rw: the field network's position among the master networks, 0 = the first |
| 2 | Node | UNSIGNED8 | rw |
| 3 | Index | UNSIGNED16 | rw |
| 4 | Subindex | UNSIGNED8 | rw |
| 5 | Value | UNSIGNED32 | rw, PDO-mappable |
| 6 | Length | UNSIGNED8 | rw: 1 to 4 bytes |
| 7 | Command | UNSIGNED8 | rw: 1 read, 2 write |
| 8 | Status | UNSIGNED8 | ro, PDO-mappable: 0 idle, 1 busy, 2 done, 3 aborted |
| 9 | Abort code | UNSIGNED32 | ro |

The upper master writes the network, node, object, value and length, then the command, and reads the status until it is 2 or 3; a read leaves the value in sub-index 5. The request goes through the same path as the program's SDO function blocks, so requests to one node queue behind each other and share their timeout. A write needs `sdo_bridge_write: true`; without it command 2 ends with status 3. Segmented transfers and strings are not supported.

## Checks

On top of the [slave network checks](slave.md#direction), a gateway is rejected when `upper` is missing or not a slave network, there is no master network, a route names a network, node or PDO entry that does not exist or a slave object its EDS does not define, a route's direction does not fit the slave object's access type, the two ends have different types, a route target has a second writer, or `status` or `sdo_bridge` is set while the EDS lacks their objects (for `status`, those of the first master network). `sdo_bridge_write` without `sdo_bridge` gives a warning.

## Diagnostics

The slave network's status in the diagnostics channel ([slave.md](slave.md#diagnostics)) has a `gateway` part: the number of routes, whether the upper master is there (`upper_ok`) and how many forwarded field errors are active.
