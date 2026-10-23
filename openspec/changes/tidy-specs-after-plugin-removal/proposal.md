## Why

The plugin removal and the Modbus-only chain (#241 through #271) renamed "plugin" to "bridge" in the specs. Requirements and scenarios for features that are now gone stayed behind, though. An explore against `main` at 33e2872 (tools 0.128.0) found specs that describe:

- **PLC-cycle SYNC.** It is a choice on the configurator's bus page and has two DBC scenarios, but the code refuses it.
- **The scan watchdog.** Scenarios expect a "not used by this target" warning. The field is gone from the schema and the relevance table, so it is now an unknown field.
- **A CiA 402 node tab with axis settings.** No such tab exists, and the configurator strips `axis` from old configs.
- **Deploy modes `--bundle` and `--project`, `--doc-cycle-ms`, and a runtime upload over REST.** None of these options exist.
- **The `install-runtime` and `install-stock` scripts and their release assets.** Both scripts are deleted.
- **A `canworks-deploy diag` command.** It does not exist; `canworks-diag status` prints that line. Two docs repeat the mistake.
- **An "OpenPLC target", an `openplc` bridge config and the editor hook.** These are now a bridge config with an OpenPLC connection (`plc_link`).
- **Bit channels with their own `%IX` locations and Suggest.** Bits now live in the entry's own location.
- **A node sheet with CiA 402 axis settings and program download.** Both were removed.
- **Test paths and a CiA 402 example that do not exist**, and PLCopen tests for three targets, of which CODESYS is refused.
- **The plugin's per-scan I/O model.** The bridge has no scan: it publishes inputs every 1 ms and applies outputs at each accepted Modbus write.

Someone who reads these specs, or a later change that builds on them, gets the wrong picture. The same goes for about a dozen Purpose lines that still describe the plugin era.

## What Changes

Specs and docs only. No behaviour changes. The only code touched is dead code.

- MODIFIED requirements make the specs say what `main` does (list under Capabilities).
- ADDED `modbus-bridge` "Bridge image timing" defines once what "scan" means for the bridge in the specs that keep the word (J1939, raw CAN, SDO variables, supervision, slave, gateway). It does not reword about 25 requirements.
- Purpose lines are rewritten by hand in the spec files at apply time, because OpenSpec deltas do not carry Purpose.
- Docs: `docs/plc-library.md` and `docs/modbus-bridge.md` name `canworks-diag status` instead of `canworks-deploy diag`. README's "Five commands" line says the CANopen simulator in the table runs on the device.
- Dead code goes: the `interpolation_period_us` line in `diag.py`, and the bit-location branches of the configurator's bit table (`bits.iec_location` is used by no target).
- Guard: `test_readme.py`'s check for `canworks-*` commands and repository paths also covers `docs/*.md` and `openspec/specs/**`, so a `canworks-deploy diag`-style slip or a deleted script fails spec-check.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `canopen-configurator`: Choose what to edit, Import an EDS, Node tabs, Saved config compared like the deploy tool writes it, Bit channels in the PDOs tab, Empty network is a warning, Header target action, PDO headings per target, Defaults of a new network, SYNC Off on the bus page, OpenPLC editor files on save.
- `canopen-dbc-export`: Comments and timing, Fixed CANopen frames.
- `canopen-config-contract`: Settings the target does not use.
- `canopen-deploy`: Export DCF / DBC / network documentation / CODESYS from the command line, Create an editor project from the command line.
- `canopen-pc-install`: Windows installers without download-and-run, Install scripts from the release.
- `modbus-bridge`: Bridge installs locked dependency versions, PLC link header; ADDED Bridge image timing.
- `modbus-bridge-mailboxes`: Mailboxes section, Mailbox use in diag.
- `modbus-bridge-map`: OpenPLC remote device file, Mailbox blocks in the map.
- `canopen-ci`: Tests selected by protocol area, OpenPLC through Modbus integration test, PLCopen export tests.
- `canopen-network-docs`: Self-contained, offline and printable, Network section, Node sheet.
- Purpose lines only: `canopen-master-bringup`, `canopen-pdo-io`, `canopen-node-supervision`, `canopen-slave-device`, `canopen-gateway`, `canopen-configurator`, `canopen-config-contract`, `canopen-deploy`, `plc-library`, `toolkit-names`.

## Impact

- `openspec/specs/**` (deltas above plus Purpose edits), `docs/plc-library.md`, `docs/modbus-bridge.md`, README.md (one line).
- `tools/deploy/canworks/diag.py` (3 dead lines), `tools/deploy/canworks/configurator/static/app.js` (dead bit-location branches), `tools/deploy/tests/test_readme.py` (scope widened).
- Tests: the existing configurator page tests for Bits… must still pass. If a test asserts the dead location column, it goes with that branch. No new CI job, and CI time stays the same (spec-check already runs on every PR).
- Tools patch version bump for the app.js and diag.py change.
- No hardware tasks.
