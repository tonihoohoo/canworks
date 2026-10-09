## Why

canworks only reaches a PLC through the OpenPLC plugin. Most PLCs, soft PLCs, SCADA systems and scripts cannot load that plugin, but almost all of them speak Modbus TCP as a client. Commercial CAN-to-Modbus TCP gateways cover this today, but they:
- are configured in their own tools, with a different register layout per product
- export nothing for the PLC side, so addresses are typed in by hand
- do not promise that a 32-bit value cannot tear across two requests
- mostly offer CANopen or J1939, rarely both, and seldom free SDO access

The exploration of 2026-10-09 (project notes `research/modbus-bridge-2026-10-09.md`, vendor manual comparison `research/modbus-gateways-vendor-manuals-2026-10-09.md`) settled the direction with Toni:
- one common bridge for every protocol canworks has, not one per protocol
- Linux only (Pi, industrial PC); the client PLC can sit anywhere on the network
- an output watchdog of 1 s by default, after which outputs stop

## What Changes

- **`canworks-bridge`**: a new Linux daemon that runs the same engine as the OpenPLC plugin (CANopen master, slave and gateway, J1939, raw CAN, simulated bus, diagnostics channel) behind a runtime-neutral host layer, with a built-in Modbus TCP server in place of the PLC.
  - Every `iec_location` in the config becomes a Modbus register or bit by a fixed rule. This covers PDO entries, SDO variables, node and bus status, timeouts, NMT command bytes, J1939 signals and raw CAN signals and frames. No second mapping is configured.
  - There is no scan. A read is answered from one consistent input snapshot. A write is published to the bus threads at once and goes out at the next SYNC, or at once for event-driven outputs.
  - An output watchdog: when no permitted client has written for `watchdog_ms` (default 1000), outputs `stop` (default), go to `zero` or `hold`.
  - An optional status block, a control block (run/idle, NMT per node or network) with a counter handshake, a live list per CANopen master network, and SDO bridge registers with the same fields as the CANopen gateway's SDO bridge.
  - Client limits: `max_clients` (default 16), `writers` and `readers` IP allowlists.
  - Several instances on one machine, each with its own config and port. An interface can be owned by one process only, and the OpenPLC plugin honours the same lock.
  - Packaging: a CMake target built with the same per-protocol options, `scripts/install-bridge.sh` with a systemd template unit `canworks-bridge@NAME`, and a multi-arch container image.
- **Config** (schema version 2): a top-level `bridge` object. A config with `bridge` is a bridge config: its locations are byte-addressed (`%IW2` is bytes 2 and 3 of the input image). The OpenPLC plugin refuses a bridge config, and the bridge refuses a config without `bridge`.
- **Diagnostics channel**: the bridge serves it like the plugin. A new `put_config` operation (behind `allow_changes` and `allow_config_upload`) replaces the bridge's config and files after a full check, keeping the old config if the new one fails.
- **PC tools**:
  - `canworks-deploy --bridge HOST` uploads a bridge config over the diagnostics channel.
  - `canworks-deploy --export-modbus-map FILE` writes the register map as CSV, JSON or an IEC 61131-3 ST variable list with a client channel table.
  - The HTML network document gets a Modbus register map section.
- **Configurator**: a "Modbus bridge" target for a project, a bridge settings panel, "Pack for Modbus" (dense byte-addressed locations), a register map preview and the exports.
- **CI**: bridge tests run on the simulated bus inside the existing plugin test job, with a small Modbus client written in the C++ test. Map export tests run in the existing tools shards. No new job is added, and time stays within the baseline.

## Capabilities

### New Capabilities
- `modbus-bridge`: the bridge daemon, its config, register mapping, consistency, watchdog, status, control, live list, SDO bridge registers, clients, instances, interface ownership and installation.
- `modbus-bridge-map`: the register map exports (CSV, JSON, ST variable list) and "Pack for Modbus".

### Modified Capabilities
- `canopen-config-contract`: `bridge` in the version 2 schema; bridge configs are byte-addressed and version 2; the plugin refuses them.
- `canopen-configurator`: bridge target, bridge panel, Pack for Modbus, map preview, exports.
- `canopen-online-diagnostics`: `put_config`, and bridge state in the live status.
- `canopen-deploy`: `--bridge` upload and `--export-modbus-map`.
- `canopen-network-docs`: Modbus register map section.
- `canopen-ci`: where the bridge tests run, and the bridge paths in the area classifier.

## Impact

- **Order**: applies after `add-j1939-ecu` and `add-raw-can` have merged. Both move the shared core (`plugin/src/can/`, process image, protocol registration) that the host layer separates from OpenPLC.
- **Plugin source**: a host interface in `plugin/src/can/host.h` with an OpenPLC host (today's behaviour) and a bridge host. The OpenPLC coupling (`plugin_runtime_args_t`: image read/write, image lock, logger) moves behind it. New `plugin/src/bridge/` (Modbus TCP server, byte image, watchdog, control, main). No new third-party dependency; no libmodbus.
- **PC tools**: `canworks/modbusmap.py`, configurator panel; minor version bump.
- **Not in this change**:
  - mailboxes for raw frames and J1939 one-shot sends or requests
  - CiA 309-2 (Modbus function 43/13), which no checked product or common client supports
  - Modbus/TCP Security (TLS)
  - Windows or macOS bridge hosts
  - a truST `io.toml` generator
  - per-entry user-defined safe values
  - one Modbus unit ID per network
- **Hardware**: on the bench Pi, the bridge runs node 23 on `can0` while a Modbus client on the Mac reads inputs, writes outputs, trips the watchdog and uses the SDO bridge registers.
- **Docs**: `docs/modbus-bridge.md`, the README feature list, PC tools and layout, `docs/configurator.md`, and `examples/modbus-bridge/` (simulated nodes, made-up names).
