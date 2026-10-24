## Why

FUXA (a web SCADA/HMI) has Node-RED built in. A user who wants an HMI and some control logic but no PLC can run both in one FUXA container: Node-RED does the logic over the canworks Node-RED package, and FUXA draws the screens. There is no example of that yet.

Toni (2026-10-24): "Explore fuxa example where fuxa integrated node red is used for control and hmi is created with fuxa". After the explore: "Propose".

The explore (report `research/fuxa-nodered-example-2026-10-24.md` in the project files) ran the whole chain in the cloud container: FUXA 1.3.5 with its Node-RED on, the real canworks-bridge built from main with the shared plant, node-red-canworks 0.137.1 and the shared plant logic. It found:
- FUXA's Node-RED (4.1.11 on Node 18) is off by default and turns on with `nodeRedEnabled: true` in `_appdata/mysettings.json`. Its editor is at `/nodered/` and its user folder is `_appdata/node-red`.
- The canworks `.tgz` installs there with Manage palette > Upload, or with `npm install` in that folder. It needs no internet.
- FUXA's own nodes (`node-red-contrib-fuxa`, built in) and `global.get("fuxa")` read and write FUXA tags. Tags of the **FUXA Server** device are shared by every browser and work by tag id. FUXA's node editors look tags up by name only on real devices, so the example uses fixed tag ids.
- A limit written from FUXA raised the alarm. Output bit 0 went out over CAN and came back on the loopback input, and Ack cleared it.
- Saving the FUXA project resets Server tags to their start values unless the tag has DAQ with "restore". With restore, a project save keeps them, but a container restart still starts them from their start values. The example states this, like the OpenPLC example does for a PLC restart.

## What Changes

- **A new example `examples/fuxa-node-red/`** on the plant of `examples/node-red-dashboard` (same `canworks.json`, EDS files and `simulation.json`, byte-identical).
- **Node-RED does the control.** The committed tab `plant.json` has:
  - **canworks in**, the shared **plant logic** function node (the same text as in `examples/node-red-dashboard/dashboard.json`), **canworks out** and the 500 ms tick;
  - a function that writes the plant state to FUXA Server tags;
  - `get-tag-change` nodes that bring the operator's limit, Ack, running light and manual outputs back to the logic.

  Node-RED is the only Modbus client of the bridge. FUXA has no device.
- **FUXA shows the HMI.** `fuxa/project.json` has the Server tags, with fixed ids and the same names as the OpenPLC + FUXA example, and the views **Plant** and **I/O**. Both FUXA examples can share the views when their tag ids match.
- **Docker Compose.** `docker compose up` starts three services:
  - `setup`, from the bridge image, which exports the package and the canworks flow at the bridge's version;
  - `bridge`, which runs the simulated plant;
  - `fuxa` (`frangoteam/fuxa:1.3.5`), which shares the bridge's network.

  `start.sh` turns Node-RED on, installs the package, writes the flow once and loads the FUXA project once. The HMI is at `http://localhost:1881` and the flow at `http://localhost:1881/nodered/`.
- **README for the example**: Docker first, then with an installed bridge and a FUXA of your own. README.md and `docs/node-red.md` link to it.
- **A static check in the tools shard.** It covers the plant files, the identical plant logic, the bridge node id, the topics, the tag ids used by the flow and the views, and the files named by compose and start script.

## Non-goals

- FUXA talking Modbus to the bridge (a second client and writer, and addresses that move with the map).
- Node-RED Dashboard 2.0 inside FUXA (that is the dashboard example).
- Running FUXA or Docker in CI.
- A FUXA change upstream so its nodes find Server tags by name (could be offered to FUXA later; the example does not need it).

## Capabilities

### New Capabilities

- `fuxa-nodered-example`: the example folder, its compose setup, flow and FUXA project.

### Modified Capabilities

- `canopen-ci`: the example's static check in the tools shard.
