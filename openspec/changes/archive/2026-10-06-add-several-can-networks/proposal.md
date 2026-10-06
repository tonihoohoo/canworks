# Proposal: several CAN networks

## Why

A config has one `adapter`, one `master` and one `nodes` list, so a PLC with two CAN interfaces (two CAN HATs, or a HAT plus a USB adapter) can run only one CANopen master. Machines often keep drives and I/O on separate buses (different bit rates, bus load, or wiring), and today that needs a second PLC.

## What Changes

- Config `schema_version` 2: a top-level `networks` list, each entry with its own `name`, `adapter`, `master` and `nodes`, plus a top-level `diagnostics` object (one channel for all networks). Version 1 files keep loading unchanged and are read as one network. A published `schema/canopen.v2.schema.json` shares the v1 definitions of adapter, master and node.
- The plugin runs one independent CANopen master per network: its own CAN thread, Lely event loop, dcfgen output, bus diagnostics and node supervision. A network whose interface is missing or bus-off does not disturb the others.
- Checks across networks: unique network names, no two networks on the same interface or serial device, and no IEC location used twice anywhere in the file. Node IDs and COB-IDs are checked per network.
- Online diagnostics: the hello lists the networks; every request takes a `network` name, required when the config has more than one network. Scan, LSS, trace, SDO, NMT, EMCY and status act on that network only. The protocol number stays 1 (all additions are optional fields), so existing clients keep working with single-network configs.
- Configurator: a network bar with add, rename and remove; each network has its own Bus and master section and node list; address suggestions and clash checks cover all networks; online view, scan and trace have a network picker. Saving writes the lowest schema version that holds the config (v1 for one unnamed network).
- Exports and CLI: DCF export per network (`<network>/node_<id>.dcf` with several networks), one DBC file per network, editor-project variable names prefixed with the network name when there are several networks, and a `--network` option for `openplc-canopen-diag` commands, the trace command and the export commands.
- Not **BREAKING**: every v1 file, every single-network workflow and every output for a single network stays as it is.

## Capabilities

### New Capabilities
- `canopen-networks`: several CANopen networks in one config and one plugin: the network list, network names, per-network masters running independently, the checks across networks, and per-network logging and generated files.

### Modified Capabilities
- `canopen-config-contract`: schema version 2 becomes supported next to 1; tools write the lowest version that holds a config.
- `canopen-online-diagnostics`: networks in the hello and a `network` selector on every request.
- `canopen-configurator`: network bar, per-network sections, network picker in online, scan and trace views.
- `canopen-dcf-export`: per-network output folders and a network filter.
- `canopen-dbc-export`: one DBC file per network instead of one per config.
- `canopen-editor-project`: network-prefixed variable names with several networks.
- `canopen-device-parameters`: `--network` for backup, compare, restore and store.
- `canopen-bus-trace`: a trace records one network and decodes with that network's nodes.

## Impact

- Plugin: `config.cpp/h` (Config splits into a list of network configs plus diagnostics), `canopen_plugin.cpp` (one Bus, ProcessImage and DiagHub per network), `dcf_gen.cpp`, `eds_check.cpp`, `eds_lint.cpp` (per network work directory), `diag.cpp/h` (network routing), log labels. `Network`, `Bus` and `BusMonitor` keep their one-network shape.
- Schema: new `schema/canopen.v2.schema.json` and its copy in the deploy tool package; v1 unchanged.
- Deploy tool: `contract.py`, `dcfexport.py`, `dbcexport.py`, `editorproject.py`, `configurator/declare.py`, `diag.py`, `parameters.py`, `bustrace`, configurator server and `static/app.js`, `static/trace.js`.
- Tests: two-network unit and sim tests (two virtual buses), a vcan0 + vcan1 run in CI, v1 compatibility fixtures, v2 schema fixtures.
- Docs: `docs/config.md`, `docs/diagnostics.md`, `docs/configurator.md`, `docs/deploy.md`, `docs/trace.md`.
- Overlap with the parallel "SYNC tied to PLC cycle" and EDS simulator changes: see design.md.
