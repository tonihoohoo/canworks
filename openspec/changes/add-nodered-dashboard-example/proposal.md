## Why

The Node-RED package (`node-red-canworks`, nodered-blocks) gives Node-RED every canworks value by name and the function blocks' jobs, but there is no example that shows what to build with it. A ready dashboard is the quickest way to see canworks working from Node-RED, and Node-RED's dashboard is what most users put on top of it.

Toni (2026-10-24): "Explore example for node red. Node red dashboard should be used in the example." After the explore: "Docker should be main way. Propose".

The explore (report `research/nodered-dashboard-example-2026-10-24.md` in the project files) found:
- **canworks in** sends `msg.topic` = name and `msg.payload` = value, and **canworks out** takes `{topic, payload}`. Dashboard 2.0 widgets use the same shape, so gauges, charts, switches and buttons connect straight to the canworks nodes.
- The classic `node-red-dashboard` is deprecated. `@flowfuse/node-red-dashboard` (Dashboard 2.0, 1.34.0) is its successor and needs Node-RED 3 or newer.
- Node-RED 4.1, Dashboard 2.0 1.34.0 and node-red-canworks 0.132.0 load side by side, and the dashboard page is served.
- The bridge simulates the plant inside itself (`adapter.simulate`), with no CAN interface and no privileges, so it runs in its container image on Docker Desktop for Mac and Windows as well as on Linux.

The CODESYS and truST example changes, explored at the same time, use the same simulated plant and the same tags and logic. The three examples therefore show one machine.

## What Changes

- **A new example `examples/node-red-dashboard/`.** It uses the plant of `examples/modbus-bridge`: a temperature module (node 5) whose first two channels follow a sine and a ramp, and a 16-bit digital I/O module (node 6) whose outputs loop back to its inputs. The loopback is the simulator's CiA 401 default behaviour. `rtd8.eds`, `dio16.eds` and `simulation.json` are byte-identical copies.
- **Its `canworks.json`** has the same networks, with `name`s on the PDO entries that match the shared tag set (`rtd_temp1`, `rtd_temp2`, `dio_in0`, `dio_in1`, `dio_out0`, `dio_out1`). Its bridge listens on `127.0.0.1:1502` with `127.0.0.1` as the only writer and has the mailboxes for the **sdo** and **emcy** nodes.
- **`dashboard.json`**: the dashboard tab only (a Node-RED Dashboard 2.0 UI). It uses the bridge config node of the flow that canworks exports for the config, so the layout and map hash never sit in a committed file. Its pages:
  - **Plant**: the shared HMI. It has the two temperatures (°C) with one trend, status dots for both nodes, a limit input, an alarm lamp and an Ack button, and the bridge state.
  - **I/O**: 16 output switches (`dio_out0`, `dio_out1`) and 16 input lamps (`dio_in0`, `dio_in1`).
  - **Service**: NMT start, stop and reset buttons, a device name read over SDO, and an EMCY table.
- **The shared plant logic, in one function node.** It mirrors `PLANT_LOGIC` of the CODESYS and truST examples. The alarm comes on when temperature 1 goes over the limit (default 25.0 °C) and stays on until Ack while the temperature is back below the limit. It sets bit 0 of `dio_out0`. A running light walks along `dio_out1` every 500 ms and is checked on `dio_in1` (`LIGHT_OK`).
- **Docker Compose as the main way to run it.** `docker compose up` in the folder starts three services:
  - a one-shot `setup` from the bridge image, which exports the Node-RED package and the canworks flow at the bridge's own version, so the versions always match and nothing is exported by hand;
  - `bridge`, which runs the simulated plant;
  - `node-red` (`nodered/node-red:4.1`), which shares the bridge's network, so it reaches `127.0.0.1:1502` on every OS.

  On first start Node-RED installs the canworks `.tgz` and a pinned Dashboard 2.0, then loads the canworks flow plus `dashboard.json`. The dashboard is then at `http://localhost:1880/dashboard`. The image version comes from `CANWORKS_VERSION` (default `latest`).
- **A README for the example** covering Docker (main), and running with an installed bridge and a local Node-RED.
- **A static check in the tools shard.** It confirms that:
  - the plant files match `examples/modbus-bridge`;
  - the bridge accepts the config;
  - `dashboard.json` uses the exported flow's bridge node id;
  - every topic it reads exists in the export's names, and every topic it writes is an output;
  - the compose file and start script name the files that exist.

  It takes milliseconds, needs no Node-RED, and adds no job.
- README.md (Node-RED line and examples) and `docs/node-red.md` (a "Dashboard example" section) point to it.

## Non-goals

- Generating a dashboard automatically in the Node-RED export (one widget per value). This could come later, separately.
- Running Node-RED or Docker in CI. The canworks nodes are already tested against the real bridge (canopen-ci, Node-RED flow tests).
- Simulator faults from the dashboard. The simulator's control channel is not on Modbus, and the plant stays the same as in the other examples.
- Classic `node-red-dashboard` or uibuilder.

## Capabilities

### New Capabilities

- `nodered-dashboard-example`: the example folder, its compose setup, dashboard and logic.

### Modified Capabilities

- `canopen-ci`: the example's static check in the tools shard.
