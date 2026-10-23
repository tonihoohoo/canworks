## Why

Node-RED uses canworks through the Modbus bridge, but today it only gets values in and out, NMT and SDO up to 4 bytes, through a generated flow built on the third-party `node-red-contrib-modbus` palette. Since `add-bridge-mailboxes` the bridge serves every function block of the ST library (long SDO, strings and REALs, EMCY, CAN frames, cyclic frames, J1939 messages, trouble codes, ECU lookup, bus info) to any Modbus client, but the protocol (counters, staging, batches, acknowledgements) is not something a Node-RED user can write by hand. Toni (2026-10-23) wants the ST block library for Node-RED, in one change, over one Modbus connection, delivered as a release `.tgz` (no npm).

The generated flow also depends on a palette canworks does not control: its updates have changed its dependencies before, and a renamed node setting breaks an export without warning. Its polling path keeps the default at 100 ms.

Toni's decisions in the explore (2026-10-23): a node package rather than subflows or snippets; the values move into the package too, so there are never two Modbus connections; the full block set in one change; Modbus stays the transport (a push API would save about 10 ms, which Node-RED cannot use); `.tgz` only.

## Where it sits

This change comes after `modbus-connections` (no OpenPLC target any more; programs are connections of a Modbus bridge config, one of them Node-RED with `period_ms` and `bridge_host`) and `faster-mailboxes` (shorter receive records, 1 or 2 receive blocks), and before `mailboxes-on-demand` (mailboxes off by default; a connection's **canworks blocks** choice turns on the parts its program uses, which for Node-RED needs this change's block nodes). It is written against those two proposals and gets its deltas rewritten against their archived text at apply time.

## What Changes

- **A Node-RED node package `node-red-canworks`** in the repository, shipped inside the PC tools and attached to each release as `node-red-canworks-<version>.tgz`. No runtime dependencies: it has its own small Modbus TCP client (read input and holding registers, write multiple registers), like the bridge has its own server.
- **One connection.** A config node **canworks bridge** owns the only Modbus TCP connection to the bridge. It polls the values and the mailbox answers together (default every 10 ms), writes the outputs and requests, keeps the watchdog and the cyclic job keepalives fed, reads the outputs back before its first write, and serves every other node.
- **Values:** **canworks in** (one message per changed value, `msg.topic` the map row's name, plus bridge state, clients, live lists, bus and ECU info) and **canworks out** (set a value by name). Same names, types and scaling as today's flow.
- **Blocks as nodes**, with the ST blocks' inputs, results and ERROR_IDs: **canworks nmt**, **canworks sdo** (read and write, up to 1785 bytes, typed as unsigned, signed, real, bytes or string), **canworks emcy**, **canworks can send**, **canworks can cyclic**, **canworks can receive**, **canworks j1939 send**, **canworks j1939 request**, **canworks j1939 receive**, **canworks j1939 dm** (read DM1/DM2, clear DM3/DM11) and **canworks find ecu**. Inputs come from the node's form or `msg.payload`; each job ends with one message (`msg.payload` the result, `msg.canworks` the status, ERROR_ID and abort code).
- **Sharing without tickets.** The config node queues jobs per request mailbox and keeps a job on its mailbox for its whole transfer; receivers are opened, read in batches, acknowledged and reopened after a link stop by the config node.
- **Restart safe.** After every (re)connect the config node writes back the request, control and SDO words it reads from the bridge before it starts anything new. The mailboxes take that write as their baseline after a bridge restart, and for the control block and SDO registers (whose baseline rule is only for a PLC link) it changes no counter, so a restart never runs an old command, send or write again. A job that still ends with 8 (or control result 6, SDO abort 0x08000021) ends with ERROR_ID 8 and is never repeated by the package.
- **The flow export uses the package.** `--export-nodered` and the Node-RED connection's Download write a tab with a **canworks bridge** config node that carries the config's register map and mailbox layout, a **canworks in** and **canworks out** node, and a comment. `node-red-contrib-modbus` is no longer used (clean cut: old exports are imported again). Default poll 10 ms.
- **Read-only when Node-RED does not own the writes.** A Node-RED connection without Writes, or any config with a PLC link (an OpenPLC connection), gets a flow that only reads: values and status in, no outputs, block nodes end with ERROR_ID 22 "read-only".
- **Get the package from the tools.** `canworks-deploy --export-nodered-package OUT.tgz` writes the package that matches the installed tools (offline). In the configurator both files are on the **Node-RED connection** of `modbus-connections`: its Download gives the flow (with the connection's `bridge_host` and `period_ms`), and **Node-RED package** gives the `.tgz`.
- **One protocol source.** The package's layout table (`lib/layout.js`: offsets, operation codes, record sizes, ERROR_IDs) is generated from the PC tools' mailbox layout; CI fails when it is stale.
- **Docs:** `docs/node-red.md` rewritten (install, nodes, messages, limits), README.

## Capabilities

### New Capabilities

- `nodered-blocks`: the Node-RED package, its config node, value and block nodes, sharing, restart and link-stop behaviour, read-only flows, the Node-RED connection's files, delivery (including the release asset).

### Modified Capabilities

- `modbus-bridge-map`: the Node-RED flow requirement now describes a flow of package nodes.
- `canopen-deploy`: `--export-nodered` default poll and the package export option.
- `canopen-ci`: package tests (plain Node, no Node-RED) and the mailbox scenarios against the real bridge.

## Impact

- New `tools/deploy/canworks/nodered_package/` (package.json, `nodes/*.js` and `*.html`, `lib/modbus.js`, `lib/bridge.js`, `lib/layout.js` generated, `test/`), package data in `pyproject.toml`.
- `tools/deploy/canworks/nodered.py`: flow of package nodes (the generated function-node code and the `node-red-contrib-modbus` nodes go), layout generation, `.tgz` writer; `cli.py`; configurator server route and the Node-RED connection row.
- `release-deploy.yml`: attach the `.tgz`. `ci.yml`: Node tests in the tools shard under its path filter; mailbox scenarios in the existing OpenPLC through Modbus integration job (which already builds and runs the bridge).
- No bridge change, no config schema change (the Node-RED connection's fields come from `modbus-connections`), no ST library change.
- Not in scope: npm publishing; installing into Node-RED from the configurator (Admin API); dashboard nodes; Node-RED on the bus directly.
