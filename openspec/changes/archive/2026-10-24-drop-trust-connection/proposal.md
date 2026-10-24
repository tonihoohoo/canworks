## Why

truST has its own Modbus connection kind and export target (`trust`, `--export-plcopen --for trust`) next to the generic **Other PLC** path. It carries its own transport files, its own checks for truST's one-request driver and slow scan, three Problems fixes and a blocks limit, and its own sections across the docs. Every other PLC that imports PLCopen XML goes through the generic export.

Toni (2026-10-24): "Explore drop trust as separate modbus target. Also docs." After the explore (report `research/drop-trust-target-2026-10-24.md` in the project files): "Propose".

The explore checked that the generic export (whole library, all mailboxes) already imports into truST 0.24.75 with nothing unsupported and builds unchanged, so truST stays useful to CI as a strict IEC compiler without being a product target.

## What Changes

- **No truST connection kind.** `bridge.connections[].kind` loses `trust`; the check refuses it like any unknown kind (clean cut, nothing is in real use). Add connection lists OpenPLC, Other PLC, Node-RED and HMI.
- **No truST export target.** `--export-plcopen --for` takes `generic` (and refuses `codesys` as today). Gone: `canworks_io.st` (the `%IB0`/`%QB0` byte image), `io.toml.part` (truST's `modbus-tcp` driver), the byte copy loops in `canworks_in`/`canworks_out`, the truST README steps, the 127.0.0.1 default bridge host, the one-request map check with its trim hint, and the 500 ms watchdog floor. The `trust` PLCopen dialect, identical to `generic`, goes.
- **No truST fixes in the configurator.** Problems loses **Set the watchdog to 500 ms**, **Trim the mailboxes for truST** and **Set canworks blocks to None** for truST; the bridge page loses the truST watchdog hint and the "None or SDO and send only" blocks limit. "Cannot download" stays for Other PLC (no PLC link).
- **CI keeps truST as a compiler.** The import-and-build check switches from the truST export to the generic export with the whole library and all mailboxes. Same shard, same path filter, same pinned binary: CI time unchanged.
- **Docs.** README, `docs/plcopen.md` (truST row and section), `docs/modbus-bridge.md`, `docs/configurator.md`, `docs/deploy.md`, `docs/plc-library.md`, `docs/node-red.md` and the Node-RED dashboard example drop truST. truST is named only in `docs/development.md`, as the compiler CI builds the PLCopen export with.

## Non-goals

- A truST example or truST wiring instructions. The "truST example with HMI" explore is built on the removed export and is parked with this change.
- Changing the generic export's content or the library.
- Removing the strict-typing choices in the library and copy programs (typed literals, `SEL` instead of `BOOL_TO_WORD`): they stay for every strict compiler.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `plcopen-export`: `generic` is the only Modbus PLC target; the truST transport and trim requirements are removed.
- `modbus-connections`: no `trust` kind, its blocks limit, download refusals and fixes go.
- `canopen-configurator`: new-config card, Add connection, PLCopen download and reachability scenarios without truST.
- `plc-library`: the truST build goes through the generic export.
- `canopen-ci`: the compile check uses the generic export.
- `canopen-deploy`: the refused-export scenario uses the generic target.
- `nodered-dashboard-example`: the shared logic names the CODESYS example only.

## Impact

- Code: `tools/deploy/canworks/plcopen_targets.py`, `plcopen.py`, `connections.py`, `bridgecheck.py`, `cli.py`, `openplcmodbus.py` (comments), `configurator/server.py`, `configurator/static/{bridge,app,target}.js`, both schema copies.
- Tests: `tools/deploy/tests/test_plcopen.py` (truST cases out, `TrustImport` on the generic export), `test_configurator_bridge.py`, `test_configurator_bridge_page.py`, small mentions elsewhere; `test/plcopen/fetch-trust.sh`, `.github/ci/plcopen-paths.txt`, `.github/scripts/ci_changes.py` and the CI step keep working with wording changes.
- Tools minor version bump (0.134.0); version-stamped goldens regenerated.
