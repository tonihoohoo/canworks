## Why

Every PDO the plugin configures today runs between the master and one node: a node's TPDO lands in a master RPDO and the PLC's `%I`, and a node's RPDO is fed from a master TPDO and the PLC's `%Q`. Data that goes from one device to another always takes the path node → master → PLC scan → master → node. That adds one or two scan cycles of latency, loads the bus with the same data twice, and stops the moment the PLC scan stops.

CiA 301 has a direct path for this: the producer/consumer model. One node's TPDO can be received by the RPDOs of any number of other nodes, simply by giving those RPDOs the same COB-ID and a mapping that matches the TPDO's layout. The master only configures both sides during boot. Typical uses on a machine:
- a joystick module whose TPDO drives the setpoints of a valve module directly;
- an encoder whose position goes straight to a drive's RPDO;
- interlock or "enable" bits that must keep moving when the PLC program is stopped for a download.

Today none of this can be expressed in `canworks.json`: an `rx_pdos` entry always gets a master TPDO on the same COB-ID (so a shared COB-ID is refused as a clash), and a node's heartbeat consumer (0x1016) can only watch the master. Users fall back to startup SDOs that write 0x1400/0x1600 by hand, which the plugin warns about, which the EDS checks do not cover, and which none of the tools (DCF, DBC, HTML docs, configurator) understand.

## What Changes

- **`links` per CANopen master network** (top level in a version 1 file, per network in version 2; new optional field, no schema version change):
  - `from`: a producer node and one of its `tx_pdos` by number. The TPDO keeps all its settings there (COB-ID, transmission, event timer, mapping, `timeout_ms`).
  - `to`: one or more consumer nodes, each with an RPDO number that is not in that node's `rx_pdos`, an optional `transmission` and `event_timer_ms` (the consumer's CiA 301 deadline), and either `entries` (the consumer's own objects in frame order, dummy entries allowed) or `"mapping": "device"` for a consumer whose mapping is fixed.
  - optional `name`, and `on_plc_stop`: `"follow"` (default) or `"keep"`.
- **PLC visibility:** the master keeps receiving the producer TPDO as today. Its entries' `iec_location` becomes optional when the TPDO feeds a link (as for entries only a gateway route uses), so the PLC sees the value only when the config asks.
- **Boot download:** the plugin writes each consumer RPDO (COB-ID off, transmission, deadline, mapping, COB-ID on) into that node's normal configuration download. The consumer RPDO is kept out of dcfgen's input, so the master gets no TPDO on the producer's COB-ID. Configs without `links` produce byte-identical master DCFs and node downloads.
- **Checks at load, in the deploy tool and in the configurator** against both EDS files: producer and consumer exist on the same network, the RPDO exists and its objects are RPDO-mappable with the right access type, entry bit lengths match the producer layout position by position and in total (at most 64 bits), types that differ at the same size give a warning, fixed-mapping devices on either side use the EDS default mapping, a read-only consumer COB-ID must equal the producer's, synchronous consumer types need SYNC. The COB-ID clash check accepts a shared COB-ID only between a link's producer and its consumers.
- **Node-to-node heartbeat watch:** new optional node field `heartbeat_watch`, a list of `{ "node", "timeout_ms" }`. The plugin writes one 0x1016 entry per watched node into the watching node's download, so a consumer can react itself (its 0x1029 error behaviour, EMCY 0x8130) when its producer is gone, without the master.
- **Runtime behaviour:** a lost or rebooted producer or consumer is handled by the existing supervision and boot; the link resumes when both are OPERATIONAL again. The master logs which links a lost node affects. With `"on_plc_stop": "keep"` the master sends no NMT command to the link's nodes on PLC stop, so the link keeps running while the PLC is stopped; warnings when that cannot work (synchronous types, nodes that watch the master's heartbeat).
- **Exports and tools:** DCF export carries the consumer's linked RPDO and 0x1016 entries as ParameterValue; the DBC lists consumers as receivers of the producer's message; the HTML network docs get a links table, consumers in the COB-ID map and the linked RPDOs on node sheets; the configurator gets a Links table per network, a heartbeat watch list on the node page and the checks; the simulator runs linked PDOs between simulated devices, which gives a CI test without hardware.
- **Docs:** docs/config.md (links, heartbeat watch, PLC stop and SYNC behaviour, compatibility list), docs/configurator.md, docs/simulator.md, docs/network-docs.md, docs/deploy.md; README feature bullet.

## Capabilities

### New Capabilities
- `canopen-pdo-links`: the `links` config, the consumer RPDO download, the layout and COB-ID checks, and the runtime behaviour on loss, reboot, PLC stop and with SYNC.

### Modified Capabilities
- `canopen-config-contract`: `links` and `heartbeat_watch` in the schema (v1 and v2 share the definitions).
- `canopen-node-supervision`: node-to-node heartbeat watch; `on_plc_stop` skips nodes of links that keep running.
- `canopen-dcf-export`: ParameterValue for the linked RPDO and heartbeat watch writes.
- `canopen-dbc-export`: link consumers as receivers.
- `canopen-network-docs`: links table, COB-ID map consumers, node sheets.
- `canopen-configurator`: Links table, heartbeat watch, checks, online view.
- `canopen-deploy`: link checks before upload.
- `canopen-device-simulator`: linked PDOs between simulated devices.

## Impact

- Plugin: `plugin/src/can/config.h`/`config.cpp` (`LinkConfig`, `HeartbeatWatch`, parsing, COB-ID clash and unlocated-entry rules), `plugin/src/canopen/eds_check.cpp` (layout and consumer checks, 0x1016 capacity), `dcf_gen.cpp` (linked RPDOs out of the dcfgen YAML, consumer RPDO and 0x1016 writes in the download, input hash), `network.cpp` (`StopNodes` skips kept link nodes, loss log), `canopen_check --dump-writes` output.
- Tools: JSON Schema v1/v2, `contract.py` and the shared fixtures (`test/fixtures/config/cases*.json`), `dcfexport.py`, `dbcexport.py`, `docexport.py`, `simfile.py`, configurator pages and page tests. Deploy tool minor version bump.
- Config format: two new optional fields (`links`, `heartbeat_watch`) within `schema_version` 1 and 2; existing configs load and behave unchanged. An older plugin warns about the unknown fields and runs without the links.
- Not affected: slave networks, J1939 and plain CAN networks, gateway routes, the master DCF, bus load (a link adds no frame: the producer TPDO was already on the bus).
- README: one bullet under "CANopen on the PLC".
