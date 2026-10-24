## Context

`examples/node-red-dashboard` runs the shared plant (simulated rtd node 5, dio node 6 with output loopback) in canworks-bridge and Node-RED with Dashboard 2.0 in Docker Compose. Its `plant logic` function node is the Node-RED form of `PLANT_LOGIC`. The add-openplc-fuxa-example change (being applied in parallel) puts FUXA 1.3.5 on OpenPLC over OPC UA, with HMI variables `temp1`, `temp2`, `limit`, `ack`, `run`, `alarm`, `light_ok`, `rtd_ok`, `dio_ok`, `canworks_ok`, `dio_in0`, `dio_in1`, `dio_out0`, `dio_out1` and `manual_out1`.

FUXA 1.3.5 (checked in its source and run in Docker):
- Node-RED 4.1.11 is a dependency of the server. It is mounted at `/nodered` (editor) and `/dashboard` (HTTP nodes) when `nodeRedEnabled` is true in `_appdata/mysettings.json`, and its `userDir` is `_appdata/node-red`.
- `node-red-contrib-fuxa` is loaded from the image (`nodesDir`). Its nodes and function nodes reach FUXA through `global.get("fuxa")`. The nodes use `setTag(id, value)`, `getTag(id)` and `getTagId(name)`, plus the runtime's `device-value:changed` events for `get-tag-change`.
- `getTagId(name)` and the editor's tag dropdown (`/nodered/fuxa/devices`) search only `project.devices`. They skip the FUXA Server device (`project.server`). `setTag` and `getTag` by id work on Server tags, because the server is one of the active devices.
- The device type `internal` keeps its values in each browser, so it cannot carry plant values.
- Server tags take their `init` value whenever the project is loaded: at start, and when the project is saved. With `daq: {enabled, restored: true}` a project save keeps the last value. After a container restart the value was back to `init` in two runs (FUXA logged "restored 2/2"). This is not dug into further: the example does not depend on it.
- The Server device polls every 1000 ms by default (`server.polling`). `get-tag-change` fires on that poll.

## Goals / Non-Goals

**Goals:** control in FUXA's Node-RED through node-red-canworks (one Modbus connection), the HMI drawn in FUXA, one `docker compose up`, no internet after the images, the same plant, tags and logic as the other examples, and views that both FUXA examples can share.

**Non-Goals:** FUXA devices on the bridge, Dashboard 2.0, FUXA or Docker in CI, upstream FUXA changes.

## Decisions

### Node-RED owns the bridge; FUXA has no device
The bridge has one Modbus client, Node-RED, which is also its one writer (Toni, 2026-10-23: one Modbus connection for Node-RED). FUXA never sees registers, so a repacked map changes nothing on the HMI side. The bridge's watchdog and safe values cover a FUXA restart (the logic stops with it).

Alternative: a FUXA Modbus device on the bridge for display, with Node-RED for logic. Rejected: two clients, two writers, register addresses in FUXA that move with the map, and FUXA's Modbus driver must be downloaded at first start.

### FUXA Server tags by fixed id
The HMI tags are on the FUXA Server device. Each tag's id equals its name (`limit`, `temp1`, ...), so the flow, the views and the CI check use one name per value. The names and types follow add-openplc-fuxa-example:

| Tag | Type | Written by | Start value |
| --- | --- | --- | --- |
| `temp1`, `temp2` | number (°C) | Node-RED | |
| `rtd_ok`, `dio_ok`, `canworks_ok`, `alarm`, `light_ok` | boolean | Node-RED | |
| `dio_in0`, `dio_in1`, `dio_out0`, `dio_out1` | number (byte) | Node-RED | |
| `bridge_state` | string | Node-RED | |
| `limit` | number (°C) | FUXA | 25 |
| `run` | boolean | FUXA | true |
| `ack` | boolean | FUXA (Node-RED sets it back to false) | false |
| `manual_out1` | number (byte) | FUXA | 0 |

`canworks_ok` is true when the bridge state is `running` and `bridge.bus_ok` is true. `limit`, `run` and `manual_out1` have DAQ with restore, so saving the project in FUXA's editor keeps them. A container restart sets them back to their start values; the README says so. `server.polling` is 200 ms, so operator changes reach the logic within 0.2 s.

If add-openplc-fuxa-example merges first with other tag ids for its OPC UA tags, this example takes its ids. If this one merges first, that change takes these. Whichever merges second adapts.

### The flow: plant logic unchanged, adapters around it
`plant.json` is one Node-RED tab (ids `fxnr.*`) that uses the bridge config node of the export named `plant`, as the dashboard example does:
- **canworks in** with the dashboard example's filter → **plant logic**.
- **plant logic** is a copy of the dashboard example's node, with the same `func` text, so the two cannot drift. CI compares them. Output 1 → **canworks out**. Output 2 (the state message) → **to FUXA**. Outputs 3 and 4 (trend, notification) are not wired: FUXA has its own trend and alarms.
- **to FUXA** is a function that maps the state message to tag ids (`lightOk` → `light_ok`, ...). It also computes `canworks_ok`, and calls `global.get("fuxa").setTag(id, value)` for each value that changed. It uses this call rather than the documented **set-tag** node because set-tag looks up `msg.topic` by name, which fails for Server tags (Context). One function replaces fourteen set-tag nodes.
- **get-tag-change** nodes, each with `tagId` set, for `limit`, `run`, `ack` and `manual_out1`. `limit` and `run` go straight to the logic, since the topic is the tag name. `ack` passes only when true, and then **set-tag** (with `tagId: "ack"`) writes false back. `manual_out1` goes through a small function that turns a changed byte into the logic's `switch` messages (`{name: "dio_out1", bit, value}`), one per changed bit.
- A **start** inject (topic `start`) runs once at deploy. It sends the logic its start message and reads `limit`, `run` and `manual_out1` with **get-tag**, so a redeploy picks up the values FUXA already holds.

The dashboard-only switches for `dio_out0` bits 1-7 have no FUXA tag. The OpenPLC + FUXA example does not have them either.

### FUXA project and views
`fuxa/project.json` is a whole FUXA project (the `POST /api/project` body). It has no devices, the Server device with the tags above and `polling: 200`, and the views:
- **Plant**: the two temperatures with a trend, the limit input, the alarm lamp, Ack, the running light switch and its check, status lamps for both nodes, and the bridge state.
- **I/O**: lamps for the 16 input bits, the 16 output bits, and buttons for the 8 bits of `manual_out1`, which work while the running light is off.

The views are drawn in FUXA's editor against the running example and exported, because view SVG cannot practically be written by hand. If add-openplc-fuxa-example already has views on the same tag ids, its views are reused as they are.

### Compose and start script
```
setup   bridge image: copies canworks.json, simulation.json and the EDS files to the plant volume,
        --export-nodered-package /share, --config ... --export-nodered /share/plant_node-red.json; exits
bridge  bridge image on the plant volume; publishes 127.0.0.1:1881 (FUXA's port, which shares this network)
fuxa    frangoteam/fuxa:1.3.5, network_mode service:bridge, entrypoint start.sh, volume for _appdata
```
`start.sh`:
1. writes `mysettings.json` with `nodeRedEnabled: true` when it has no such key, keeping other settings;
2. when `_appdata/node-red/.canworks-version` differs from the exported package, runs `npm install --offline` on the `.tgz` in `_appdata/node-red` (it has no dependencies);
3. when `_appdata/node-red/.canworks-flow` is missing, joins `/share/plant_node-red.json` and `plant.json` into `flows.json`, then writes the marker;
4. starts FUXA (`node main.js` in the image's server folder) and waits for `GET /api/settings`;
5. when `_appdata/.canworks-project` is missing, posts `fuxa/project.json` to `/api/project`, then writes the marker;
6. waits on the server.

Later starts keep the user's flow and FUXA project. `docker compose down -v` starts over.

The port is the same as the OpenPLC + FUXA example's (1881). The README says to stop one before starting the other.

### Security
FUXA security is off and the Node-RED editor is open, as in FUXA's defaults. Only 127.0.0.1 is published. The README says to turn on FUXA's security (`secureEnabled`, with `nodeRedAuthMode: secure`) before exposing it.

### CI check
`tools/deploy/tests/test_fuxa_nodered_example.py`, in the tools shard. It confirms that:
- the plant files are byte-identical to `examples/node-red-dashboard`'s;
- the plant logic `func` is the same as in `dashboard.json`;
- every canworks node uses the export's bridge id;
- every topic read exists in the export, and every topic written is an output;
- every tag id in `plant.json` (get-tag, get-tag-change, set-tag and the ids in **to FUXA**) and in the views exists among the project's Server tags;
- the compose file and start script name files that exist.

No FUXA, node or Docker is involved.

## Risks / Trade-offs

- **Control and HMI in one process.** A FUXA restart or a flow deploy restarts the logic. The README names this. A machine that needs hard timing uses a PLC (the OpenPLC + FUXA example).
- **`global.get("fuxa")` is FUXA's internal API**, the one its own nodes use. A FUXA update could change it. The image is pinned (1.3.5), and the hand checks run the example.
- **Operator values do not survive a container restart.** This is documented. It is the same for a PLC restart in the OpenPLC example.
- **The FUXA project format** may change between FUXA releases. The image pin keeps the example stable. When the pin moves, the views are re-exported.
