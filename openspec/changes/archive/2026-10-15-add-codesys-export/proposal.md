## Why

Many users run CODESYS PLCs and CODESYS-based displays that have CAN interfaces and CODESYS's own CANopen Manager. Today they can use canworks to design and check a CANopen network, simulate it and commission devices, but they then rebuild the whole bus by hand in CODESYS: every node, PDO, COB-ID, transmission type, heartbeat, startup SDO and variable name. That is slow and error-prone, and the two configurations drift apart.

A spike in CODESYS V3.5 SP22 (2026-10-15) showed that this hand work can go away:

- A node DCF from `canworks-deploy --export-dcf`, installed in CODESYS's device repository, brings the node in with our PDO communication parameters, PDO mappings, heartbeat producer time and startup SDOs, because CODESYS's EDS converter takes the DCF's `ParameterValue`, not `DefaultValue`.
- Everything around the nodes (CANbus network number and bit rate, CANopen Manager settings, node ID, supervision, identity check, variable names on the I/O channels) is reachable through CODESYS's documented Python scripting API, which runs in the IDE on an open project and headless from the command line.
- Three identical drives with different configs came in correctly when each DCF was imported and its device added straight away, and the project built with 0 errors.

## What Changes

- **New `--export-codesys DIR`** in `canworks-deploy`: writes a folder with the node DCFs (the existing `canopen-dcf-export` files, per network), a plan file `canworks-codesys.json` with every setting the script applies (computed in canworks, so the script holds no logic about our config), and the static script `import_canworks.py`, plus a short `README.txt`.
- **One script, two ways to run it.** In CODESYS on the open project (Tools > Scripting > Execute Script File…), or from the command line with `CODESYS.exe --noUI --runscript=…`. A new `canworks-deploy --codesys-import PROJECT [--codesys-dir DIR]` does the command-line run for the user: it writes the export, finds CODESYS (or takes `--codesys-exe` and `--codesys-profile`) and runs the script on the given project (or a new one with `--codesys-new`), so no paths go through CODESYS's script arguments.
- **Works on the user's own PLC.** The script never needs a particular PLC type: it uses the PLC device already in the project, reuses CANbus and CANopen Manager objects that are already there (matched by network number), and otherwise adds them using the newest CANbus and CANopen Manager versions installed in that CODESYS. Device versions and CODESYS paths are never hard-coded, so a vendor's CODESYS package and an older CODESYS service pack work as well as the plain IDE.
- **Network numbers.** A network's CODESYS network number comes from its interface (`can1` gives 1) or from `--codesys-net NAME=N`, because CODESYS devices number their CAN interfaces in their own way.
- **Re-runnable.** Running the script again on the same project replaces the nodes it manages (same node ID under the same manager) and leaves everything else as it is.
- **Variable names.** Each mapped PDO entry's I/O channel gets the same name the editor declarations use (`declare.py`), so programs read the same in OpenPLC and CODESYS. CODESYS assigns its own `%I`/`%Q` addresses.
- **Report.** The script prints and writes `import_report.txt`: what it created, reused or replaced, the build result, and every config setting that has no CODESYS counterpart (plugin-only status locations, SDO variables and blocks, CiA 402 axis bridge, PDO links, LSS settings, raw CAN, J1939, gateway and slave networks).
- **Configurator:** the Export menu gets **CODESYS**, downloading the same folder as `<config folder>_codesys.zip`.
- New `docs/codesys.md`; `deploy.md`, `configurator.md` and README updated.

## Capabilities

### New Capabilities
- `codesys-export`: the export folder, the plan, the script's behaviour in CODESYS (tree building, settings, variable names, re-runs, report).

### Modified Capabilities
- `canopen-deploy`: `--export-codesys DIR` and `--codesys-import PROJECT` on the command line.
- `canopen-configurator`: Export > CODESYS.

## Non-goals

- No change to the plugin, the config schema or the DCF content.
- No CODESYS project file, PLCopenXML or native-export generation (undocumented and lossy).
- No J1939, raw CAN, slave or gateway networks in CODESYS (listed in the report). A canworks slave already imports into CODESYS through `canworks-deploy slave-eds`; `docs/codesys.md` says how.
- No import from CODESYS back into canworks.
- No CODESYS runtime setup on Linux (SocketCAN link helper); a later change if needed.

## Impact

- New `tools/deploy/canworks/codesys/` (plan builder, packaged `import_canworks.py`), `cli.py` options, configurator server route and Export menu item.
- Tests: plan golden files for the example configs; the script run in CI under CPython against a fake CODESYS scripting API (it stays Python 2.7 and 3 compatible, as CODESYS runs IronPython 2.7); configurator page test for the download.
- Manual check in a CODESYS install (Windows PC) before release; a check on a CODESYS display with CAN is a hardware task that does not block the PR.
