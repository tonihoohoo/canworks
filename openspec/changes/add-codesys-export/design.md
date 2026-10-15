## Context

Findings from the spike (CODESYS V3.5 SP22 Patch 4, CANbus / CANopen_Manager / remote device 4.4.0.0, scripting engine 4.2, IronPython 2.7):

- `device_repository.import_device(path, device_repository.sources[0], Guid("{1ce4a9c1-37d3-496c-9e80-cd99ad3807ee}"), True)` installs a DCF or EDS and returns its device id. A DCF installs as `<vendor>_<product>_DCF` with version `Revision=..., FileVersion=...`; a later DCF of the same product and revision replaces it in the repository.
- A device added to the project copies its parameters at that moment, so *import, add, import, add* keeps each node's own config.
- The CANopen objects keep their settings in `connectors[i].host_parameters` (`device_parameters` is empty). CANbus: connector 1 (`Baudrate`, `NetID`). Manager and remote device: connector 0. Each parameter has a stable numeric `id` (manager: 256 SYNC period, 257 SYNC enable, 288 node ID, ...; device: 1 node ID, `0x01800000 + 0x1000 * n` for TPDO n+1, `0x01400000 + 0x1000 * n` for RPDO n+1, `0x11A0xxxx` / `0x1160xxxx` mapping entries, `0x20000F00` SDO list).
- Plain parameters take `param.value = "..."`. Struct parameters (a PDO, a mapping entry) refuse a whole-value write; their sub-elements are writable: `list(param)[i].value`.
- `param.io_mapping.variable = "name"` names an I/O channel (a new variable in the I/O globals).
- `obj.rename(name)`; otherwise CODESYS names added devices on its own (`rtd_1`).
- `projects.primary` is the open project in the IDE; `projects.open(path)` / `projects.create(path, True)` headless. `sys.argv` carries `--scriptargs:` split on spaces with no quoting, so paths with spaces cannot go through it; `__file__` is the script's path.
- `proj.active_application.build()` and `system.get_message_objects(category)` give the build result.

## Goals / Non-Goals

Goals: the user's CODESYS project gets the same CANopen bus the canworks config describes, from the IDE or the command line, on any CODESYS PLC with CAN (including a vendor's controller or display package with its own device description and an older service pack), re-runnable, with an honest report.

Non-goals: see the proposal.

## Decisions

### 1. Static script plus a computed plan
`import_canworks.py` is one fixed file shipped in the wheel; all knowledge of our config goes into `canworks-codesys.json`, built in Python 3 by canworks from `contract`, `dcfexport` and `declare`. Alternative: generate a script per config. Rejected: a generated script is hard to review and test, and every fix would need re-exporting. The static script is tested once against a fake API.

Plan (format 1), shape only (as built, parameters carry `id`, `name`, `value`, an optional struct `element` and `what` for the report):
```json
{"format": 1, "tool": "canworks-deploy 0.x",
 "project": null, "create": null, "plc": null,
 "networks": [{"name": "field", "net_id": 0, "bitrate_kbit": 250,
   "manager": {"node_id": 1, "heartbeat_ms": 100,
               "sync": {"enabled": true, "period_us": 20000, "window_us": 0},
               "autostart": true, "start_all": false},
   "nodes": [{"node_id": 5, "name": "rtd", "dcf": "field/node_5.dcf",
              "optional": false, "check": {"vendor": true, "product": true, "revision": false},
              "heartbeat_consumer_ms": 300, "guarding": null,
              "channels": [{"dir": "in", "index": 28976, "sub": 1, "variable": "rtd_Temperature_1"}]}]}],
 "not_carried": [{"where": "field/rtd", "setting": "emcy_code_location", "why": "plugin status location"}]}
```

### 2. Run modes
- **IDE:** the user opens their project and runs the script file. It works on `projects.primary` and does not save; the user saves. Without an open project it stops with a message.
- **Command line:** the plan names `project` (open it) or `create` (path plus the PLC device as type, id and version, for a new project). The script saves after a run without errors. `canworks-deploy --codesys-import PROJECT` writes the export into a temporary folder (or the `--export-codesys DIR` given), puts the project path in the plan and runs `CODESYS.exe --profile=... --noUI --runscript=<folder>\import_canworks.py`, then prints `import_report.txt` and exits non-zero when the script reports an error. CODESYS comes from `--codesys-exe`, else the newest `C:\Program Files\CODESYS *\CODESYS\Common\CODESYS.exe`; the profile from `--codesys-profile`, else the newest profile in that install. No path goes through `--scriptargs`.

### 3. The PLC and its CAN interfaces
- The PLC is the project's only top-level device that can take a CANbus, or the one the plan's `plc` names (`--codesys-plc NAME`); several without a name stops with the list of candidates.
- A network goes on the CANbus whose `NetID` equals the plan's `net_id`, searched anywhere under that PLC, so a device description that already carries CANbus objects, or puts them under its own CAN connectors, is used as it is. Only when there is none does the script add a CANbus under the PLC.
- Added objects use the highest installed version of CANbus (type 15, id `181015`) and CANopen_Manager (type 16, id `181016`) from `device_repository.get_all_devices()`; when the PLC already has a CANbus of another version, that version is used. No version is hard-coded.
- `net_id` comes from `--codesys-net NAME=N`, else the interface's trailing number (`can1` gives 1), else 0 with a report line. Devices number their CAN interfaces in their own way (from 0 or from 1), so the docs tell users to look at their device's CANbus objects first.
- An existing CANopen Manager under that CANbus is reused; a CANopen device object there (CODESYS as slave) stops that network with a message.

### 4. Settings by parameter id, names as a check
Parameters are looked up by numeric id. A missing id is reported and skipped, not fatal, so older or vendor builds of the CANopen Manager keep working and a setting that could not be applied shows in the report. A different name is set anyway and noted: CODESYS shows parameter names in the user's language, so a name check cannot decide.

### 5. Nodes and re-runs
For each node: import its DCF, add the device under the manager at once, rename it to the node's identifier, set node ID and the remaining settings, then name its channels. The spike found no script access to the device's startup identity checks, so they are a report line for the user. A mapped object is the parameter `0x1MMMMEE0` (mapping object `0xMMMM`, entry `EE`) with `Index`/`SubIndex`/`ObjectLength`; its I/O channel, which carries `io_mapping`, is the parameter with the next id. A remote device already under that manager with the same node ID is removed first (re-run); devices with other node IDs are kept and listed. Manual edits on replaced devices are lost, and the report names the replaced devices. The DCF entries stay in the device repository (the project refers to them); the repository then holds the last config per product and revision, which only matters for CODESYS's "Update device" and is noted in the docs.

Open point for apply: giving each DCF a unique `[FileInfo]` FileVersion/FileRevision would keep a repository entry per node. Only if CODESYS accepts it without side effects; the spike did not test it.

### 6. Variable names
Channel names are the editor declaration names from `declare.declarations`, so OpenPLC and CODESYS programs use the same names. A channel is matched by direction, index and sub-index among the device's mapping parameters. A name already used in the project is a CODESYS build error; the script builds and lists such errors. `--codesys-no-variables` leaves channels unnamed.

### 7. What does not carry over
The plan lists every config setting without a CODESYS counterpart; the script copies them into the report. `sync_source: plc_cycle` becomes a note to pick the bus cycle task in CODESYS. The master's heartbeat consumer timeout becomes the node's consumer time where the device parameter exists, else a report line.

### 8. Compatibility
The script uses only the documented ScriptEngine API, syntax that runs on IronPython 2.7 and CPython 3 (CI), no f-strings and no third-party modules; it reads the plan with `json`. Tested CODESYS: V3.5 SP22. Older service packs are expected to work (the calls exist since SP16 or earlier) and are listed as untested in the docs until checked.

## Risks / Trade-offs

- A vendor build of the CANopen Manager with other parameter ids: settings are skipped and reported; nodes and PDOs are still right because they come from the DCF.
- A device package that does not let a CANbus be added freely: reuse by `NetID` covers devices that ship them; the script reports when it cannot add one.
- DCF repository replacement (decision 5): documented; unique FileVersion as a possible follow-up.
- Licences: none needed for the IDE or scripting; the runtime's CANopen licence is the user's own (docs link the CODESYS store).

## Testing

- Plan golden files for `examples/modbus-bridge`, `examples/gantry-cell` and a two-network config.
- `import_canworks.py` under CPython in CI with a fake `projects` / `device_repository` / `system` that records calls: new project, existing CANbus reused, two networks, re-run replacing a node, missing parameter id, duplicate variable build error, IDE mode without a project.
- Manual: in CODESYS on Windows, IDE and command line, project builds with 0 errors.
- Hardware (open task, does not block the PR): a CODESYS controller or display with CAN against the simulator or real nodes.
