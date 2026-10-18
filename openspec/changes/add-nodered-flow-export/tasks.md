# Tasks

## 1. Tests first

- [ ] 1.1 `test/pc-tools/test_nodered.py`: golden flow for `examples/modbus-bridge/canworks.json` (tabs, client node host/port/unit, read nodes per channel, link names, stable ids); non-bridge config refused; host/period defaults and clamping.
- [ ] 1.2 Function code under `node` with a stub context: decode/encode of every CANopen type, both word orders, BOOL bits, byte values in high/low halves, scale/offset; change detection and first full emit; writes held until the read-back; unknown topic and out-of-range value warn and write nothing; keepalive period.
- [ ] 1.3 NMT and SDO links: counter increments, block bytes, SDO result on counter echo, timeout.
- [ ] 1.4 Round trip against a Modbus server stub (FC3/4/16): read named values, write one, read-back seeds outputs.
- [ ] 1.5 Configurator page test: Export Node-RED flow downloads the same bytes as the CLI; a map problem shows instead.

## 2. Code

- [ ] 2.1 `tools/deploy/canworks/nodered.py`: flow writer from `register_map`/`suggest_channels`, function bodies, stable ids.
- [ ] 2.2 `cli.py`: `--export-nodered`, `--nodered-host`, `--nodered-poll-ms`; refuse with uploads and non-bridge configs.
- [ ] 2.3 Configurator: `/api/bridge/export` format `nodered`; button in `bridge.js`.
- [ ] 2.4 Minor version bump of the tools package; release notes line.

## 3. Docs

- [ ] 3.1 `docs/node-red.md`: install the palette, export and import, "canworks in/out", NMT/SDO, `writers`, latency (poll + one SYNC), not for motion, the palette version tested.
- [ ] 3.2 `docs/modbus-bridge.md` Clients: Node-RED paragraph; README: Node-RED line; tour line if the bridge page tour step lists the exports.

## 4. CI

- [ ] 4.1 Tests in the existing tools shard; no new job; CI time against the baseline in the PR.

## 5. Hardware

- [ ] 5.1 On the Pi: bridge from the one-line installer on the bench CAN interface (after the 0.84.0 release), Node-RED in Docker with `node-red-contrib-modbus`; import the exported flow; the bench node's inputs arrive on "canworks in"; an output set from "canworks out" reaches the node; NMT stop/start of the node through "canworks nmt"; stop Node-RED and see outputs off by the watchdog. Then remove the Node-RED container, uninstall the bridge, clean PLC start.
