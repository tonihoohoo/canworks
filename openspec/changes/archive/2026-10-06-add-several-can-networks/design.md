# Design: several CAN networks

## Context

Today `Config` (plugin/src/config.h) holds one `AdapterConfig`, one `MasterConfig` and one `std::vector<NodeConfig>`. `canopen_plugin.cpp` builds one `ProcessImage`, one `Bus` (thread, adapter, `BusMonitor`, Lely loop and `Network`), one optional `DiagHub` + `DiagServer`. `generate_device_config`, `check_eds_files` and `run_eds_lint` take the whole `Config` and write into `<config dir>/.canopen/`. On the PC, `contract.py`, the exports and the configurator read `cfg["adapter"]`, `cfg["master"]` and `cfg["nodes"]` directly. The diagnostics client (`diag.py`) refuses any hello whose `protocol` is not exactly 1. The cross-plugin clash check (`clash.py`) walks every JSON key generically, so it already sees locations inside a `networks` list.

## Goals / Non-Goals

**Goals:**
- Several networks with as little change as possible to the code that runs one network (`Bus`, `Network`, `BusMonitor`, LSS, trace capture).
- Every v1 file, log line, generated file, export and diagnostics client keeps working unchanged for one network.

**Non-Goals:**
- Gateways or routing between networks (a value from one network goes to another only through the PLC program).
- One trace that records two networks at once.
- Telling the deploy tool which config versions the installed plugin reads before an upload (see Risks).
- More than 8 networks.

## Decisions

### 1. Config model: a list of network configs plus shared settings

A new `ConfigSet` holds the file: `{path, config_dir, file_sha256, schema_version, networks, warnings, notes}`, where each of `networks` is a `Config`, the struct the plugin already had for one network, extended with `network` (the name), `network_index`, `work_dir` and `log_prefix`. Keeping the name `Config` for one network keeps the change to Bus, Network, BusMonitor, dcf_gen, eds_check, eds_lint, ProcessImage and DiagHub small: they take one network's `Config` as before. The top-level `diagnostics` of a version 2 file is copied into every network's `MasterConfig`, so the diagnostics code reads it where it always did. The v1 parser fills one `Config` with an empty name and `work_dir = .canopen`. The v2 parser loops over `networks` with the same adapter/master/node parsers, so the field rules stay in one place. `load_config`/`parse_config` remain for the code that takes a file with one network, and refuse a file with several.

Alternative: keep `Config` as is and add `std::vector<Config> extra_networks`. Rejected: two code paths for the first and the other networks, and the diagnostics fields would sit in a per-network struct while being global.

### 2. Runtime: one Bus, ProcessImage and DiagHub per network

`PluginState` holds a vector of `{GeneratedConfig, ProcessImage, DiagHub, Bus}` per network. Each `Bus` already owns its thread, adapter, monitor and Lely loop, so networks are independent by construction: a missing interface only keeps its own bus thread retrying. `cycle_start()` calls `copy_to_plc` on every image and `cycle_end()` calls `copy_from_plc` on every image; images never overlap because the load rejects clashing locations, so the order does not matter. Copying stays lock-free per image as today.

Alternative: one Lely loop with several CAN controllers. Rejected: Lely's `BasicMaster` is one NMT master per channel anyway, a shared loop would let one network's slow SDO callbacks or bus-off handling delay the other, and the per-loop code (`Bus::run_session`) would need rework instead of reuse.

### 3. Validation order: everything or nothing

All networks are parsed, linted, EDS-checked and passed through dcfgen before any interface opens. Any error in any network rejects the file. Partial start was considered (run the valid networks) and rejected: the config is one contract delivered by one upload, a half-running plant is harder to notice than a stopped plugin, and the spec for one network already says a config error opens no interface.

Cross-network checks after the per-network ones: name pattern and uniqueness (case-insensitive, since names become folder names and identifiers), adapter interface and slcan device uniqueness, then IEC location overlap over all locations in the file using the existing per-network overlap code on the concatenated list.

### 4. Network names and defaults

A name is `[A-Za-z][A-Za-z0-9_]{0,15}`: it is a folder name for dcfgen output and exports, a prefix in IEC variable names, and a log prefix. Defaulting to the interface name means a v2 file with `can0` and `can1` needs no names at all. v1 configs have an empty name, which is what keeps every single-network output byte-identical (no log prefix, no folder, no variable prefix).

### 5. Schema v2 references v1 definitions

`schema/canopen.v2.schema.json` defines only the top level, `network` and `diagnostics`, and points at `canopen.v1.schema.json#/$defs/adapter`, `.../master` and `.../node`. The network's master is `allOf: [{$ref: v1 master}, {not: {required: [diagnostics]}}]`. `diagnostics` reuses the v1 master's `diagnostics` subschema by reference. `contract.py` loads the v2 schema with every `$ref` into the v1 file rewritten to a local one and v1's `$defs` copied in, so the refs resolve offline, the unknown-field walker needs no change, and `jsonschema>=4.0` stays enough. The plugin does not use the schema files, so nothing changes there.

This matters for the parallel changes: a field they add to v1's `master` or `node` is valid in v2 without touching the v2 file.

### 6. Diagnostics: one server, per-network hubs, protocol stays 1

`DiagServer` keeps one listener, token and client limit, and gets a list of `DiagHub`s, one per network, each attached to its own `Network`. The server reads `network` from each request (after the hello), resolves it to a hub or answers `network required` / `unknown network`, and queues the request there. Per-network scan, LSS and trace state already lives in `Network` and in the hub, so it becomes per network for free. Trace: the trace state per client gains the hub it traces; `TraceCapture` opens that network's interface.

The protocol number stays 1. Additions are optional fields (`networks` in hello, `network` and `name` in requests and status), and the shipped `diag.py` refuses any protocol other than 1, so bumping it would break every existing client even for single-network configs. A new client sends `network` only when the hello lists more than one network, so it still talks to an older plugin that ignores the field.

### 7. Generated files per network

v2 networks generate into `.canopen/<name>/` (master DCF, concise DCFs, prepared EDS copies, the reuse stamp). The reuse stamp is computed over the network's own JSON subtree, the shared parts that feed dcfgen (none today), and its EDS files, so changing one network regenerates only that one. v1 keeps `.canopen/` so an existing install does not regenerate after the update.

### 8. Tools: lowest version on save, network as a first-class key

The configurator's in-memory model is always a network list (`{networks: [...], diagnostics}`); load converts v1 into it and save converts back to v1 when the rule in the config-contract spec allows. That keeps one code path in `app.js` and lets the "Bus and master" and node list code render one tab's network. Server endpoints that take a node (online, params, OD browser, scan, trace) gain a `network` argument passed through to the diag client.

PC-side helpers get one `networks(cfg)` function in `contract.py` returning normalized `(name, adapter, master, nodes)` tuples for both versions; `dcfexport`, `dbcexport`, `declare`, `editorproject`, `parameters` and `bustrace` switch from `cfg["nodes"]` to it.

### 9. Overlap with the parallel changes

- **SYNC tied to the PLC cycle** (thread "SYNC tied to PLC cycle"): its new `master` fields land in v1's `master` definition and become per network here through the reference. Its `cycle_end()` hook must trigger SYNC on every network whose master asks for it; with this change `cycle_end()` already loops over the networks, so the SYNC trigger belongs inside that loop. Whichever change merges second rebases `canopen_plugin.cpp` and the configurator's Bus and master section (which this change wraps in a tab).
- **EDS device simulator**: it runs on one interface. If it learns to read nodes from a `canopen.json`, it needs a `--network` option with the same rules as `openplc-canopen-diag`, and its configurator hook (setting simulated values) goes through the network picker of the online view.
- The simulator proposal (branch `propose/add-device-simulator`) adds `adapter.simulate: true`, which runs a network on an in-process virtual bus. Here that is per network: each simulated network gets its own virtual bus, and the interface and serial-device uniqueness check skips simulated adapters. Its separate `simulation.json` will need a network name per simulated device once there are several networks.
- Both touch the configurator's Bus and master section and the schema; the conflict is textual, not semantic. Neither changes the top-level layout this change introduces.

## Risks / Trade-offs

- [A v2 file uploaded to a runtime with an older plugin is rejected at PLC start ("version 2, supported 1"), and CANopen is off] → the log says so plainly; docs/config.md and the release notes say to update the plugin (`install-stock.sh`) and the deploy tool together; tools write v1 whenever possible, so only real multi-network configs are v2.
- [Each network adds a bus thread, a Lely loop and up to two sockets] → limit of 8 networks; the cost per network is what one network costs today.
- [Scan time grows with networks, since `cycle_start`/`cycle_end` copy more images] → the copies are memcpy-sized per bound entry, the same total as one network with the same entries.
- [The refactor to a per-network config touches most plugin files] → keeping `Config` as the one-network struct and adding `ConfigSet` around it limits it to the loader, the plugin state and the diagnostics server, with the v1 test suite green throughout.
- [Configurator UI grows a level of nesting] → with one network the bar shows only "Add network", so today's page is unchanged for most users.

## Migration Plan

No migration of files: v1 files stay v1. An install updated with this change regenerates nothing for a v1 config. Rollback: reinstall the previous plugin; v1 files keep working, v2 files are rejected with the version message.
