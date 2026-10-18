# Tasks

## 1. Tests first

- [x] 1.1 `tools/deploy/tests/test_nodered.py`: golden flow for `examples/modbus-bridge/canworks.json` (tabs, client node host/port/unit, read nodes per channel, link names, stable ids); non-bridge config refused; host/period defaults and clamping.
- [x] 1.2 Function code under `node` with a stub context (`tests/data/nodered/harness.js`): decode/encode of every CANopen type, both word orders, BOOL bits, byte values in high/low halves, 64-bit, REAL64, scale/offset; change detection and first full emit; writes held until the read-back; unknown topic and out-of-range value warn and write nothing; keepalive and no keepalive without a watchdog.
- [x] 1.3 NMT and SDO links: counter increments, block bytes, SDO result on counter echo, abort, timeout, one request at a time.
- [x] 1.4 Round trip between the generated code and register images packed independently in Python (struct). Also run once while applying: Node-RED 4 with `node-red-contrib-modbus` 5.60.2 against a real `canworks-bridge` on the simulated example (values in, outputs written and looped back by the simulated node, NMT stop/start, SDO read and refused write, outputs off by the watchdog when Node-RED stopped).
- [x] 1.5 Configurator page test: Export Node-RED flow downloads the same bytes as `nodered.flow` and shows the writers note (in the existing bridge page test, no new test class).

## 2. Code

- [x] 2.1 `tools/deploy/canworks/nodered.py`: flow writer from `register_map`/`suggest_channels`, function bodies, stable ids.
- [x] 2.2 `cli.py`: `--export-nodered`, `--nodered-host`, `--nodered-poll-ms`; refuse with uploads and non-bridge configs.
- [x] 2.3 Configurator: `/api/bridge/export` format `nodered`; button in `bridge.js`.
- [x] 2.4 Minor version bump of the tools package (0.85.0).

## 3. Docs

- [x] 3.1 `docs/node-red.md`: install the palette, export and import, "canworks in/out", NMT/SDO, `writers`, latency (poll + one SYNC), not for motion, the palette version tested.
- [x] 3.2 `docs/modbus-bridge.md` Clients: Node-RED paragraph; `docs/configurator.md`, `docs/deploy.md`; README: bridge paragraph, tools table, docs table. The tour does not list the map exports, so no tour line.

## 4. CI

- [ ] 4.1 Tests in the existing tools shard; no new job; CI time against the baseline in the PR.

## 5. Hardware

- [ ] 5.1 On the Pi: bridge from the one-line installer on the bench CAN interface (after the 0.84.0 release), Node-RED in Docker with `node-red-contrib-modbus`; import the exported flow; the bench node's inputs arrive on "canworks in"; an output set from "canworks out" reaches the node; NMT stop/start of the node through "canworks nmt"; stop Node-RED and see outputs off by the watchdog. Then remove the Node-RED container, uninstall the bridge, clean PLC start.
