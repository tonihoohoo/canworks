# Node-RED

[Node-RED](https://nodered.org) uses a canworks network through the [Modbus bridge](modbus-bridge.md) with the canworks node package `node-red-canworks`: the bridge runs the CAN bus, and the package's nodes read and write its values by name and run the same jobs as the PLC function blocks (SDO, NMT, EMCY, raw CAN, J1939). Node-RED never touches the bus itself, so the bridge's watchdog, node supervision and SDO handling stay where they are.

- [What you need](#what-you-need)
- [Install the package](#install-the-package)
- [Export and import the flow](#export-and-import-the-flow)
- [Values in and out](#values-in-and-out)
- [Block nodes](#block-nodes)
- [Receivers](#receivers)
- [Restart, link loss and watchdog](#restart-link-loss-and-watchdog)
- [Next to OpenPLC: read-only flows](#next-to-openplc-read-only-flows)
- [Timing and limits](#timing-and-limits)
- [From an older export](#from-an-older-export)

## What you need

- A running `canworks-bridge` with a config ([modbus-bridge.md](modbus-bridge.md#install)). Node-RED is usually on the same device. In the configurator, add it as a **Node-RED** connection on the Modbus bridge page with its address (`127.0.0.1` on the bridge's device) and **Writes** on, and the bridge's writers follow; the export says so when the config's `writers` do not allow it.
- Node-RED 3 or 4 on Node.js 18 or newer. In Docker use a versioned image such as `nodered/node-red:4.1`; there is no `4` tag.
- For the block nodes, the bridge parts they use in the config: `control_location` and `status_location` for NMT (the status block carries the bridge's answer; a config with the PLC link has it at `%IB4`), `sdo_bridge_location` and `mailboxes` for SDO, `mailboxes` for the CAN, J1939 and EMCY nodes ([plc-library.md](plc-library.md#the-mailboxes)). The configurator's **Modbus bridge** page turns them on (**Bridge blocks**, **Function blocks**), and **Pack for Modbus** places them.

## Install the package

The package comes with the PC tools, in the same version; it is not on npm and needs no internet:

- **Package** on a Node-RED connection in the configurator, or `canworks-deploy --export-nodered-package .` on the command line, writes `node-red-canworks-<version>.tgz`. Each PC tools release also has it as a file.
- In Node-RED: Menu > Manage palette > Install > upload, pick the file. Or run `npm install /path/to/node-red-canworks-<version>.tgz` in the Node-RED user folder (`~/.node-red`, `/data` in the Docker image) and restart Node-RED.

The palette gets a **canworks** group. Install it once per Node-RED, and again after a PC tools update so the package matches the flows you export.

## Export and import the flow

In the configurator, a Node-RED connection's **Download** on the Modbus bridge page gives `<config>-<connection>.json`, with the connection's bridge address and period. From the command line:

```sh
canworks-deploy --config canworks.json --export-nodered line1_node-red.json
canworks-deploy --config canworks.json --export-nodered line1_node-red.json --nodered-host 192.168.10.5 --nodered-poll-ms 50
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--nodered-host HOST[:PORT]` | the bridge's `listen` address, `127.0.0.1` when it listens on all addresses | Where Node-RED connects. |
| `--nodered-poll-ms N` | 10 | How often the bridge node reads and writes; kept between 10 ms and a third of `watchdog_ms`. |

In Node-RED: Menu > Import, pick the file, Import. The flow is one tab, `canworks line1` (named after the file, without `_node-red`), with a **canworks in**, a **canworks out** and the **canworks bridge** config node `canworks line1`. That config node holds the bridge's address and poll period and the config's layout: the register map, the bridge's blocks and mailboxes and the networks. Every canworks node on any tab uses it, over **one** Modbus TCP connection. Its node ids depend on the name, so importing a newer export of the same config offers to replace the nodes instead of adding a second copy. Export again whenever the config's locations change; the bridge node's edit dialog shows the layout's version and map hash.

## Values in and out

- **canworks in**: one message per changed value, `msg.topic` its name and `msg.payload` the value. Every value is sent once after the first read. Names are the register map's: the PDO entry's `name` when it has one, else `<node>.<index>:<sub>` such as `dio.0x6000:1`, and status values such as `rtd.state` or `field.bus_state`. Bits are `true`/`false`, REAL objects are numbers, 64-bit integers beyond 2^53 come as decimal strings. J1939 and raw signals with `scale`/`offset` arrive scaled, with `msg.unit`. **Topics** limits one node to some names: exact names or a prefix ending in `*`, separated by commas.
- **canworks out**: send `{topic: "dio.0x6411:1", payload: -1234}` (or set **Output** on the node) to set that output. The value is checked against the type's range (a warning and nothing written when it does not fit) and goes to the bridge with the next poll. A string is accepted for 64-bit values.

With the bridge's blocks in the config, **canworks in** also carries:

| Topic | Payload |
| --- | --- |
| `bridge.state` | `running`, `watchdog` (outputs off by the watchdog), `idle`, `map mismatch` or `plc stopped` |
| `bridge.clients` | connected Modbus clients |
| `bridge.command` | `{counter, result, text}` of the last NMT command |
| `bridge.bus_ok` | `false` while a CAN network of the bridge has its bus down, missing or bus-off (status byte 7 bit 1), and while the bridge is not reachable |
| `<network>.node<N>.operational` | from the live list, per configured node |
| `<network>.bus_state`, `.bus_load`, `.tx_errors`, `.rx_errors`, `.bus_offs` | from the network info block (mailboxes), unless the map has a value of that name |
| `<network>.claim`, `.address`, `.name`, `.ecus` | the same, for a J1939 network |

When the connection to the bridge is lost, **canworks in** sends 0 (or `false`) for the status, state and timeout values, every `.operational` and `bridge.bus_ok`; the other values keep their last ones until the bridge answers again ([When the bridge fails](modbus-bridge.md#what-the-nodes-do)).

Every canworks node shows the connection as its status: connected, connecting, reconnecting, or **writes refused** when the bridge's `writers` lacks Node-RED's address.

## Block nodes

Each block node runs one job per message and sends exactly one message when it ends. Its fields are the inputs of the PLC block of the same name in lower case ([plc-library.md](plc-library.md)); fields of an object `msg.payload` override the form. `network` is the network's name or index, or empty when the config has one network of the kind the node needs.

| Node | PLC blocks | Fields | `msg.payload` when done |
| --- | --- | --- | --- |
| **nmt** | `CO_NMT` | `command` (`start`, `stop`, `preop`, `reset`, `reset_comm`, `run`, `idle`), `node` (0: every node) | `true` |
| **sdo** | `CO_SDO_READ`, `CO_SDO_WRITE` and their `_BYTES`, `_STRING`, `_REAL` forms | `node`, `index`, `subindex`, `action` (`read`, `write`), `datatype` (`unsigned`, `signed`, `real`, `bytes`, `string`), `size` (1, 2, 4, 8), `value`, `timeout` | the value read (number, string or Buffer), `true` for a write |
| **can send** | `CAN_SEND` | `can_id`, `extended`, `rtr`, `dlc`, `data`, `timeout` | `true` |
| **can cyclic** | `CAN_SEND_CYCLIC` | `can_id`, `extended`, `dlc`, `data`, `period`, `action` (`start` also changes a running frame, `stop`) | `true` |
| **j1939 send** | `J1939_SEND` | `pgn`, `destination` (255 global), `priority`, `data` (up to 1785 bytes), `timeout` | `true` |
| **j1939 request** | `J1939_REQUEST` | `pgn`, `destination`, `timeout` | the answer as a Buffer; `msg.canworks.source` |
| **j1939 dm** | `J1939_DM_READ`, `J1939_DM_CLEAR` | `action` (`read`, `clear`), `address`, `previous` (DM2/DM3 instead of DM1/DM11), `timeout` | read: `[{spn, fmi, oc, cm}]` with `lamps`, `flash`, `count`, `ageMs` in `msg.canworks`; clear: `true` |
| **find ecu** | `J1939_FIND_ECU` | `ecu_name` (64-bit NAME, decimal or `0x`), `mask` (empty: every bit) | the address, or `null`; `msg.canworks.ecu` the NAME's fields |

A payload that is not an object sets the node's main field: `data` of the send nodes and **can cyclic** (a Buffer, an array of bytes or a hex string such as `"01 02 0a"`), `value` of an **sdo** write, `command` of **nmt**. The form names `can_id`, `datatype` and `ecu_name` differ from the PLC blocks' because Node-RED keeps `id`, `type` and `name` for itself; `msg.payload` may use either.

The message keeps `msg.topic`, and `msg.canworks` says how the job ended: `{status: "done" | "error", errorId, abortCode, abortText, text, request}`. `errorId` is the PLC block's ERROR_ID, with the same numbers ([plc-library.md](plc-library.md), [raw-can.md](raw-can.md), [j1939.md](j1939.md)), and `text` says it in words; `msg.payload` is `null` on an error. Every family shares:

| ERROR_ID | Meaning |
| --- | --- |
| 8 | Cancelled: the link stopped, the network restarted or the bridge restarted. |
| 20 | The bridge is not reachable (or the connection dropped during the job). |
| 22 | The config has no part of the bridge this node needs (the node's status says which, for example **nmt** without a status block), or the flow is read-only. |

Numbers up to 4 bytes go through the SDO registers when the config has them; everything else through a request mailbox, with the long transfers staged and fetched in 128-byte steps. Jobs queue in the order they arrive: each takes the first free request mailbox and keeps it for its whole transfer, short SDO jobs share the SDO registers and NMT commands the control block. Waiting does not count against a job's timeout (5 s when empty). At most 64 jobs wait per bridge node; one more ends with the family's "no free slot" ERROR_ID (5, or 9 for J1939). The node's status shows busy, done or the last ERROR_ID.

## Receivers

**can receive** (`CAN_RECEIVE`: `can_id`, `mask`, `extended`, `all_ids`, `depth`), **j1939 receive** (`J1939_RECEIVE`: `pgn`, `all_pgns`, `source` (empty: any), `all_destinations`, `depth`) and **emcy** (`CO_RECV_EMCY`: `node` (0: every node), `skip_old`) each hold one of the bridge's receivers while they are deployed. They have no input: each received frame or message is one message, in the order the bridge received them:

| Node | `msg.payload` |
| --- | --- |
| **can receive** | `{id, extended, rtr, dlc, data, time}` |
| **j1939 receive** | `{pgn, source, destination, priority, data, time}`; long messages are fetched whole |
| **emcy** | `{node, code, register, data, time}` |

`time` is when the bridge received it: for **emcy** the record's own time, for **can receive** and **j1939 receive** the receive time of the batch's first record, shared by the batch (accurate to about one poll; use a [bus trace](trace.md) for frame-to-frame timing). With `receive_blocks` 2 a batch carries 21 CAN frames instead of 9 ([modbus-bridge.md](modbus-bridge.md#function-block-mailboxes)). `msg.canworks` has `queued`, `dropped` and `overflow` from the bridge's queue. When the bridge closes the receiver (link stop, network restart) or the connection drops, the node sends one message with `msg.canworks.status` `error` and ERROR_ID 8 or 20, and opens the receiver again. More receivers than the bridge has end with the family's "no free receiver" ERROR_ID in the node's status.

## Restart, link loss and watchdog

- **Outputs are not zeroed by a restart.** After every connect the bridge node reads the outputs, the control block, the SDO request, every request mailbox and the receive acknowledgement back from the bridge and writes them unchanged before anything else. Values sent to **canworks out** before that are held (the last value per name wins). After a bridge restart, these first words are its baseline, so nothing left in the registers runs again.
- **Link loss**: the nodes show reconnecting, and the bridge node tries again after 0.5 s, then up to every 5 s. Jobs that were running end with ERROR_ID 20; nothing is repeated by itself. When the bridge is back, values flow again, the receivers open again and a running **can cyclic** is set up again (it says so with one ERROR_ID message), without a redeploy.
- **Watchdog**: the outputs are rewritten at least every third of `watchdog_ms`, so the bridge keeps them on while Node-RED runs and applies `on_client_loss` when it stops. The cyclic frames' keepalives are written every poll, so the bridge stops them within 1 s after Node-RED stops. With `watchdog_ms` 0 nothing is rewritten.

The bridge node writes whole write channels, so it expects to be the bridge's only writer.

## Next to OpenPLC: read-only flows

When a PLC program owns the bridge's writes (a config with the PLC link, `bridge.plc_link`, which an OpenPLC connection turns on), the exported flow is **read-only**, and so is the Download of a Node-RED connection with **Writes** off: its bridge node writes nothing, the tab has no **canworks out**, a **canworks out** added by hand warns once and drops values, and block nodes end each job with ERROR_ID 22. **canworks in** works as usual, so a Node-RED dashboard can run next to the PLC. **Read-only** on the bridge node's edit dialog does the same for any flow.

## Timing and limits

- With the default 10 ms poll a new input value reaches **canworks in** within two poll periods plus one SYNC period; an output reaches the bus by the next SYNC after the write. A short SDO takes a few poll periods, a 1024-byte SDO read about 150 ms on a simulated node. That suits monitoring, dashboards, commissioning and slow control, not motion.
- Node-RED and the bridge talk Modbus TCP, so Node-RED can run on another machine; the bus side needs Linux ([modbus-bridge.md](modbus-bridge.md#limits)).
- The package has no dependencies of its own (its own Modbus TCP client), so a Node-RED update does not break it.

## From an older export

Flows exported by earlier PC tools used `node-red-contrib-modbus` and Link nodes. Delete that tab, install the package and import a new export: values keep their names, the link-in **canworks out** becomes the **canworks out** node, and **canworks nmt** and **canworks sdo** become the **nmt** and **sdo** nodes (their results come out of the node itself, with `msg.canworks` in place of `msg.sdo`).
