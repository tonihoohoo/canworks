# Proposal: add-nodered-flow-export

## Why

Node-RED is a common logic and dashboard tool on the same small Linux devices canworks runs on, but it has no general CANopen support: the flow library has plain CAN frame nodes and CANopen nodes tied to one vendor's controller each. It already speaks Modbus TCP well through the widely used `node-red-contrib-modbus` palette, and the Modbus bridge serves the whole CAN side as Modbus registers. So Node-RED can use canworks today, but only by reading the register map and writing function nodes that pack and unpack words by hand.

Toni explored Node-RED as a project target (2026-10-18) and chose to keep the Modbus bridge as the target and use Node-RED through Modbus. What is missing is the client side: a ready flow that turns registers into named signals.

## What Changes

- **Node-RED flow export** for bridge configs, built from the same register map as the CSV, JSON and ST exports. Importing it into Node-RED gives one flow tab with:
  - a Modbus client node pointed at the bridge, one read node per suggested read channel, polling at a set period;
  - a **"canworks in"** link: one message per changed value, `msg.topic` = the map row's name, `msg.payload` = the value (type, word order, sign, REAL and scale/offset handled); every value once after start;
  - a **"canworks out"** link: `{topic, payload}` sets that value in the output image and writes the changed write channel(s); the image is first read back from the bridge so a restart of Node-RED does not zero outputs;
  - a keepalive that rewrites the outputs at a third of the bridge's `watchdog_ms`, so outputs stay on while the flow runs and the bridge's `on_client_loss` action applies when it stops;
  - when the config has them: the bridge status block shown as the tab's node status, the live list as `<network>_node<N>_operational` signals, **"canworks nmt"** (`{network, node, command}`) over the control block, and **"canworks sdo"** / **"canworks sdo result"** over the SDO registers, all with the bridge's counter handshake.
- `canworks-deploy --config FILE --export-nodered FLOW.json [--nodered-host HOST] [--nodered-poll-ms N]` writes it. Host defaults to the bridge's listen address (`127.0.0.1` when it listens on all addresses), poll period to 100 ms (at most a third of `watchdog_ms`).
- The configurator's bridge page gets **Export Node-RED flow** next to the other map exports (same file as the command line).
- Docs: new `docs/node-red.md` (install the palette, import, wire "canworks in/out", NMT/SDO, latency of poll period plus one SYNC, not for motion); a Node-RED paragraph under Clients in `docs/modbus-bridge.md`; README line.

No new target, config key, schema change, runtime or bridge change. The flow pins no palette version.

## Capabilities

### Modified Capabilities
- `modbus-bridge-map`: Node-RED flow as a further client output of the register map.
- `canopen-deploy`: `--export-nodered`.
- `canopen-configurator`: Export Node-RED flow on the bridge page.
- `canopen-ci`: the flow tests run in the existing tools shard; no new job.

## Impact

- Code: new `tools/deploy/canworks/nodered.py` (flow writer, uses `modbusmap.register_map` and `suggest_channels`); `cli.py` flags; configurator `/api/bridge/export` format `nodered` and one button in `bridge.js`.
- Tests: golden flow for `examples/modbus-bridge/canworks.json`; the flow's function-node code run under `node` against the map (decode and encode of every type, word orders, bits sharing a byte, scale, keepalive period, NMT/SDO counters); a mock Modbus server test that reads/writes through the generated encode and decode code; configurator page test for the button. Node is on the CI runners; the node tests skip with a message where it is missing.
- Version: minor bump of the tools package.
- Hardware task: on the Pi, the bridge (one-line installer) on the bench CAN interface and Node-RED in Docker with the palette; import the exported flow, see the bench node's values arrive on "canworks in", move an output from "canworks out", stop Node-RED and see outputs go off by the watchdog; then uninstall the bridge, remove the Node-RED container, clean PLC start.
