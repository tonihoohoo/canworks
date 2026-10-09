## 0. Order

- [x] 0.1 Apply after `add-j1939-ecu` and `add-raw-can` have merged; rebase this branch on that `main` and adjust paths to the merged core layout (`plugin/src/can/`, `NetworkRuntime`, raw path).

## 1. Host layer

- [x] 1.1 Bridge host on the shared engine (`plugin/src/can/engine.*`): emulate `plugin_runtime_args_t` (input write, output read, image lock, logger, cycle end) over the byte image, plus the "outputs running" gate; verify that the whole existing plugin test suite passes unchanged.
- [x] 1.2 Interface lock (`/run/canworks/<interface>.lock`, `flock`) in the shared adapter bring-up for plugin and bridge; verify with a C++ test that a second owner fails with the interface and process ID, and the other networks run.

## 2. Config

- [x] 2.1 Schema: `bridge` object and `diagnostics.allow_config_upload` in `schema/canworks.v2.schema.json` (and the packaged copy); `examples/modbus-bridge/canworks.json` (simulated CANopen nodes, made-up names) validates.
- [x] 2.2 Plugin config: byte-addressed locations for bridge configs (parse, sizes, even start, byte-range clash check), bridge object checks (listen, unit, allowlists, blocks, live list network is a CANopen master, `plc_cycle` refused); the plugin refuses bridge configs; verify with one C++ test per rejection message.
- [x] 2.3 PC contract: the same checks in Python from shared fixtures (`test/fixtures/config/cases-bridge.json`); deploy refuses bridge configs for `--runtime` and plain configs for `--bridge`; verify with the shared fixture tests.

## 3. Bridge runtime

- [x] 3.1 Bridge host on a big-endian byte image with input and output snapshots; `canworks-bridge` main (config, logging, signals, start/stop of networks); CMake target with the protocol options; verify on the simulated bus that the example's nodes boot and the log line is right.
- [x] 3.2 Modbus TCP server (`plugin/src/bridge/modbus_server.*`): poll loop, MBAP framing, functions 1-6, 8, 15, 16, 23, exceptions, unit IDs, limits, `max_clients`, idle close, allowlists; verify with C++ tests using a test client for every function and exception.
- [x] 3.3 Register rule and word order; one snapshot per request; writes publish one snapshot; edge detection between snapshots for SDO triggers, NMT command bytes and raw triggers; verify map, tearing (10,000 reads of a 1 kHz counter), cyclic rewrite and event-driven RPDO timing tests.
- [x] 3.4 Watchdog and `on_client_loss` (`stop`, `zero`, `hold`) through the host's "outputs running" state; verify each action on the simulated bus (SYNC and RPDOs stop, zeros sent once, hold keeps sending, inputs keep updating).
- [x] 3.5 Status block, control block with counter handshake, live lists; verify each command and result code.
- [x] 3.6 SDO bridge registers on the existing SDO request path; verify read, write, write refused without `sdo_bridge_write`, abort code passing.

## 4. Diagnostics and deploy

- [x] 4.1 Bridge part of the hello and live status; `put_config` with staging, check, swap, restart and restore; plugin refusal; verify with simulated-bus tests (valid, invalid, fails at start and restored, not allowed).
- [x] 4.2 `canworks-deploy --bridge` and `--export-modbus-map`; `canworks-diag status` bridge line; verify with tools tests against a stub channel and the example config.

## 5. PC tools and configurator

- [x] 5.1 `canworks/modbusmap.py`: map, CSV/JSON/ST writers, channel suggestion, Pack for Modbus; verify that the map matches the bridge on the example (a C++ test reads a JSON map produced by the Python module from a fixture) and that packing leaves no clash.
- [x] 5.2 Configurator target switch, Modbus bridge page, map preview, exports; verify with page tests (switch the bridge example, saved per type, to bridge, pack, export ST); a cyclic CiA 402 axis stays refused on the bridge, which has no PLC cycle.
- [x] 5.3 HTML document Modbus register map section; verify with the document tests.

## 6. Packaging

- [x] 6.1 `scripts/install-bridge.sh` (build, install, `canworks-bridge@.service`, `/etc/canworks-bridge/NAME/`), with `--without-canopen` and `--without-j1939`; verify with a script test using a stub `systemctl`.
- [x] 6.2 Container image (multi-arch) for the bridge, published by the release workflow; a path-filtered pull request workflow builds it only when its files change.

## 7. CI

- [x] 7.1 Bridge paths `shared` in the area classifier; bridge tests inside the existing plugin test job and tools shards; no new job; state wall time and summed job time against the baseline in the PR.

## 8. Hardware

- [x] 8.1 Pi: bridge with node 23 on `can0`; a Modbus client on the Mac reads inputs, writes outputs (node reacts), stops writing (outputs stop after 1 s), uses the control block (NMT stop/start node 23) and reads 0x1018:1 through the SDO bridge registers. Use a clean PLC start afterwards; the OpenPLC plugin and the bridge must not run on `can0` at the same time. Passed 2026-10-09 from the Windows PC instead of the Mac (outputs: only the output the device is configured for reads back, as expected); the run found the follow-ups fixed in the next change (lock across Docker, the identity log line, the bridge prefix next to a Docker runtime).

## 9. Docs

- [x] 9.1 `docs/modbus-bridge.md` (install, config, register rule with examples, watchdog, control, live list, SDO bridge, security notes, client examples for a PLC with Modbus client channels and for Python), README feature list, PC tools and layout, `docs/configurator.md` bridge page; bump the PC tools minor version.
- [x] 9.2 Run the banned-word check on the branch.
