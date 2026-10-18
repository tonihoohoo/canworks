# Node-RED

[Node-RED](https://nodered.org) uses a canworks network through the [Modbus bridge](modbus-bridge.md): the bridge runs the CAN bus, and a generated flow turns its registers into named values. Node-RED never touches the bus itself, so the bridge's watchdog, node supervision and SDO handling stay where they are.

- [What you need](#what-you-need)
- [Export and import the flow](#export-and-import-the-flow)
- [Values in and out](#values-in-and-out)
- [NMT commands and SDO requests](#nmt-commands-and-sdo-requests)
- [Timing and limits](#timing-and-limits)

## What you need

- A running `canworks-bridge` with a config ([modbus-bridge.md](modbus-bridge.md#install)). Node-RED is usually on the same device, so set the bridge's `writers` to include `127.0.0.1` (or Node-RED's address when it runs elsewhere); the export says so when the config does not allow it.
- Node-RED 4 with the Modbus palette `node-red-contrib-modbus` (Menu > Manage palette > Install, or `npm install node-red-contrib-modbus` in the Node-RED folder). Tested with 5.60.

## Export and import the flow

In the configurator, open the bridge page and press **Export Node-RED flow**: it downloads `<folder>_node-red.json`. From the command line:

```sh
canworks-deploy --config canworks.json --export-nodered line1_node-red.json
canworks-deploy --config canworks.json --export-nodered line1_node-red.json --nodered-host 192.168.10.5 --nodered-poll-ms 50
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--nodered-host HOST[:PORT]` | the bridge's `listen` address, `127.0.0.1` when it listens on all addresses | Where the flow connects. |
| `--nodered-poll-ms N` | 100 | How often the inputs are read; kept between 10 ms and a third of `watchdog_ms`. |

In Node-RED: Menu > Import, pick the file, Import. The flow is one tab, `canworks line1` (named after the file, without `_node-red`). Its node ids depend on that name and the values, so importing a newer export of the same config offers to replace the nodes instead of adding a second copy. Export again whenever the config's locations change.

## Values in and out

Wire your own flows to the tab with Link nodes:

- **canworks in** (link out): one message per changed value, `msg.topic` its name and `msg.payload` the value. Every value is sent once after the first read. Names are the register map's: the PDO entry's `name` when it has one, else `<node>.<index>:<sub>` such as `dio.0x6000:1`, and status values such as `rtd.state` or `field.bus_state`. Bits are `true`/`false`, REAL objects are numbers, 64-bit integers beyond 2^53 come as decimal strings (a string is also accepted on **canworks out**). J1939 and raw signals with `scale`/`offset` arrive scaled, with `msg.unit`.
- **canworks out** (link in): send `{topic: "dio.0x6411:1", payload: -1234}` to set that output. The value is checked against the type's range (a warning and nothing written when it does not fit), written into the output image and sent to the bridge at once.

With the bridge's blocks in the config, **canworks in** also carries:

| Topic | Payload |
| --- | --- |
| `bridge.state` | `running`, `watchdog` (outputs off by the watchdog) or `idle` |
| `bridge.clients` | connected Modbus clients |
| `bridge.command` | `{counter, result}` of the last NMT command |
| `<network>.node<N>.operational` | from the live list, per configured node |

The tab's decode node shows the bridge state as its status.

**Outputs are not zeroed by a restart.** Before its first write the flow reads the output registers back from the bridge; writes sent before that are held (the last value per name wins). A tick rewrites the outputs every poll period, at most every third of `watchdog_ms`, so the bridge's watchdog keeps them on while Node-RED runs and applies `on_client_loss` when it stops. With `watchdog_ms` 0 nothing is rewritten.

The flow writes whole write channels, so it expects to be the bridge's only writer.

## NMT commands and SDO requests

With a `control_location` in the bridge config:

- **canworks nmt** (link in): `{payload: {network: "field", node: 5, command: "stop"}}`. Commands: `start`, `stop`, `preop`, `reset`, `reset_comm` (node 0: every node of the network), `run` and `idle` (the bridge's outputs, no network or node). The result arrives on **canworks in** as `bridge.command`.

With an `sdo_bridge_location`:

- **canworks sdo** (link in): `{topic: "serial", payload: {network: "field", node: 5, index: 0x1018, subindex: 4}}` reads; add `value` (and `length` 1-4, default 4) to write, which needs `sdo_bridge_write` in the bridge config. Requests queue and run one at a time.
- **canworks sdo result** (link out): the request's topic, `msg.payload` the value read (`true` for a write, `null` when it failed) and `msg.sdo` `{status: "done" | "aborted" | "timeout", abort, abortText, request}`.

`network` is the network's name, its index, or left out when the config has one CANopen master network.

## Timing and limits

- A new input value reaches **canworks in** within one poll period plus one SYNC period (about 100 to 150 ms with the defaults); an output reaches the bus by the next SYNC after the write. That suits monitoring, dashboards and slow control, not motion: a cyclic CiA 402 axis needs a PLC target.
- Node-RED and the bridge talk Modbus TCP, so Node-RED can run on another machine; the bus side needs Linux ([modbus-bridge.md](modbus-bridge.md#limits)).
- The flow depends on `node-red-contrib-modbus`; a palette update that renames node fields would need a new export.
