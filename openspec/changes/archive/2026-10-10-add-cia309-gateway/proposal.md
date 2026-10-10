## Why

Everything that reaches the CANopen networks of a running plugin or bridge from outside goes through the diagnostics channel: TLS, a SCRAM login and our own JSON lines. That suits the configurator and `canworks-diag`, but SCADA systems, test benches, shell scripts and third-party CANopen tools do not speak it, and writing a client for it means implementing TLS with channel binding and SCRAM first. The Modbus bridge serves the process image, not SDO, NMT or LSS on arbitrary nodes.

CiA 309-3 is the standard ASCII gateway protocol for exactly this: one text line per command (`[1] 5 r 0x1018 1 u32`), one line per answer, unsolicited lines for emergencies and boot-ups. Many CANopen tools and test frameworks can already talk it, and a Python script needs nothing but a socket. Lely CANopen, which the plugin already links, ships the text side of a CiA 309-3 gateway (`lely/co/gw_txt.h`, used by its `coctl` tool), so the parser and formatter do not have to be written again.

## What Changes

- **New opt-in CiA 309-3 gateway** in the OpenPLC plugin and in `canworks-bridge`: a top-level `cia309` object (version 2 files; `master.cia309` in version 1). Without it nothing listens.
- **Two ways in:**
  - a plain TCP port that listens on the loopback address only (default `127.0.0.1:7533`), for scripts and tools on the PLC's own computer or reached through an SSH forward. A non-loopback `bind` is rejected: CiA 309-3 has no authentication, so a plain port is never opened on a network;
  - from other machines, the existing diagnostics channel: after the usual TLS + SCRAM login, a new `{"op": "cia309"}` request switches that connection to CiA 309-3 lines. `canworks-diag gateway` opens a local plain port on the PC that tunnels each connection this way, so any CiA 309-3 tool on the engineering PC connects to `127.0.0.1` and the token never leaves `canworks-diag`.
- **Lely's text layer, our service layer.** Each session has a Lely `co_gw_txt_t` that parses lines into `co_gw_req` structures and formats `co_gw_con`/`co_gw_ind` structures back into text. The requests do not go to Lely's `co_gw_t` service object. They go to a new dispatcher that turns them into the diagnostics channel's existing bus-thread requests (`DiagHub`). SDO transfers then queue behind boot configuration, SDO variables and the PLC's SDO blocks, NMT commands keep the operator/program hold rules, and LSS keeps its single-operation lock.
- **Network numbering:** CiA 309 network *n* is the *n*-th network of the config (config order, from 1, the same order as the diagnostics hello and the Modbus control block's index + 1). An optional `cia309.nets` maps numbers to network names explicitly. The plugin logs the numbering when the gateway opens, and `canworks-diag gateway --list` and the HTML network docs show it.
- **Services:** SDO upload and download to any node (expedited and segmented, up to 4096 bytes), NMT start, stop, pre-operational, reset node and reset communication (configured nodes, node 0 = all configured nodes), PDO read of the master's received PDOs, LSS (switch, inquire, configure node ID and bit rate, store, fastscan), EMCY, boot-up and node state notifications, set default network and node, SDO and command timeouts, version. Not served: guarding and heartbeat changes, `init`, `set id`, `set rpdo`/`set tpdo`, PDO write and LSS "activate bit timing" (the config owns them, or the PLC owns the outputs); these answer `ERROR: 100`.
- **Same guards as the diagnostics channel:** reads need nothing more than access; SDO downloads, NMT and LSS need `cia309.allow_changes` (default false). Everything the diagnostics channel refuses without `force` (an SDO write to a configured OPERATIONAL node, an NMT command other than start to one, LSS node IDs in use) is refused unless `cia309.allow_force` is true, because the text protocol has no per-request force flag. A refusal answers `ERROR: 102` and is logged with its reason and the client's address.
- **Never blocks the PLC scan:** the gateway runs on its own thread; bus work goes through the hub that the bus thread already polls; notifications reach sessions through a bounded queue the bus thread never waits on; slow readers lose notifications (counted) and are disconnected at an output cap.
- **Client limits:** `max_clients` (default 4, 1-16) gateway sessions in all, at most 8 outstanding commands per session, 16 KiB per line, idle loopback sessions kept; tunnelled sessions count against the gateway limit, not the diagnostics channel's 4.
- **Bridge:** `canworks-bridge` serves the same gateway; gateway requests never feed or end the Modbus output watchdog.
- **Tools:** `canworks-diag gateway` (tunnel, `--exec LINE`, interactive prompt); configurator Online access gets a "CiA 309-3 gateway" part; the config check, schema and HTML network docs know `cia309`.
- **Tests:** Lely text round-trip unit tests, dispatcher unit tests against a fake hub, and a Python client in CI against the plugin and the bridge on a simulated bus.
- **Docs:** new `docs/cia309-gateway.md`; `docs/diagnostics.md`, `docs/modbus-bridge.md`, `docs/config.md`, `docs/configurator.md`, `docs/network-docs.md`; README feature line.

## Capabilities

### New Capabilities
- `canopen-cia309-gateway`: the CiA 309-3 text gateway: config, listeners, network numbering, services, guards, notifications, limits, scan independence, bridge support, client tools.

### Modified Capabilities
- `canopen-online-diagnostics`: the `cia309` op that switches a logged-in connection to CiA 309-3, and `canworks-diag gateway`.
- `modbus-bridge`: the bridge process runs the CiA 309-3 gateway too, without touching the output watchdog.
- `canopen-configurator`: Online access settings for the gateway.

## Impact

- Plugin: new `plugin/src/can/cia309_server.cpp`/`.h` (listener, sessions, Lely `co_gw_txt_t` per session) and `plugin/src/canopen/cia309_dispatch.cpp`/`.h` (`co_gw_req` to `DiagRequest`, answers to `co_gw_con`); `diag.h`/`diag.cpp` (the `cia309` op hands the TLS connection over; new hub ops `pdo_read`, `lss_store`, `lss_select`; a notification queue on `DiagHub`); `network_diag.cpp`, `network_lss.cpp` (new ops, events); `engine.cpp` (creates the server next to `DiagServer`); `config.cpp`/`config.h` (`cia309`).
- Build: `CMakeLists.txt` checks that the Lely build has `co_gw_txt_create`; without it a config with `cia309` is rejected naming the missing Lely feature. `scripts/build-lely.sh` keeps the gateway parts enabled at the pinned ref.
- Bridge: `bridge_host.cpp` (status lists gateway sessions).
- PC tools: `tools/deploy/canworks/diag.py`, `cli.py` (`gateway`), new `tools/deploy/canworks/cia309.py` (small client used by the tests and the tunnel), contract check, schema `canworks.v1.schema.json`/v2 equivalent, configurator `server.py` and Online access page, network docs generator.
- Tests: `test/unit` (text round trip, dispatcher, guards), new `test/cia309/run.sh` in CI (plugin on vcan with the device simulator, bridge with the simulated example).
- Overlaps: the unmerged `add-remote-access` change forwards only the diagnostics port and the runtime's HTTPS port through `canworks-link`. Because remote gateway sessions ride on the diagnostics channel, `canworks-diag gateway` works over the link without any change to it, and the loopback-only plain port is never reachable through it. Both changes touch `parse_diagnostics` neighbours in `config.cpp`, the schema and `docs/diagnostics.md`; `cia309` is a separate object, so the merge is mechanical.
- Not breaking: no existing field, op or port changes.
