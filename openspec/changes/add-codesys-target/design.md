# Design: add-codesys-target

## Context

Today the target is implicit: a top-level `bridge` object makes a bridge config (`contract.networks` sets `byte_mode`), and `bridge.js` `bridgeTargetField()` switches between OpenPLC and the bridge, repacking locations through `/api/bridge/pack` and `/api/pack_openplc`. CODESYS is a separate export (`codesys/plan.py`, `/api/export_codesys`) whose `MASTER_NOTES`/`NODE_NOTES` already list every setting CODESYS does not take. `plan.channels()` builds channels from `declare.declarations()`, which skips entries without `iec_location`, so CODESYS channel names depend on OpenPLC locations.

## Goals

- One notion of "target" for the whole toolkit: OpenPLC (default), Modbus bridge, CODESYS.
- The page shows only what the target uses, and the check flags leftovers, from one table.
- A CODESYS project needs no IEC locations and keeps its CODESYS settings in the config.

## Decisions

### D1. Target from the config, objects stay the marker

`targets.target(cfg)` returns `"bridge"` when `bridge` is an object, `"codesys"` when `codesys` is an object, else `"openplc"`. Both present is an error (`a config targets one system: remove 'bridge' or 'codesys'`). No separate `target` key: the bridge already works this way, the objects carry the target's own settings, and an empty `{}` is enough to mark a target. A CODESYS config is version 2, like a bridge config; switching a version 1 config converts it when saved, as the bridge switch does.

### D2. The `codesys` objects

```json
"codesys": { "project": "C:\\Projects\\cell.project", "device": "PLC",
             "create": "4096:0000 0004:3.5.22.40", "variables": true }
"networks": [{ "name": "field", "codesys": { "net_id": 1, "interface": "CAN" }, ... }]
```

All optional. `device` is the plan's `plc` (renamed for the user: a display is a device too). `net_id` replaces the number taken from the interface name; without it the plan keeps today's rule (interface's trailing number, else 0 with a note). In a CODESYS config `adapter.interface` is optional, since CODESYS chooses the interface by `net_id`; `adapter.bitrate` stays required. Paths stay as typed (Windows paths are fine; the tools only use `project` on the PC that runs CODESYS).

### D3. Entry `name`

PDO entries (and nothing else in this change) get an optional `name`: an IEC 61131-3 identifier, unique in the config after the network prefix the declarations add. `declare.declarations()` uses it in place of the EDS ParameterName part: `<network>_<node>_<name>` with several networks, `<node>_<name>` with one; that is the rule slave bindings already follow for their `name`. In a CODESYS config `declarations()` yields entries without a location too (kind `pdo`, location `None`), so `plan.channels()` names every mapped entry. The editor-project and Modbus map paths keep skipping entries without a location.

Why the node prefix stays: two nodes of the same product would otherwise collide on every name, and today's generated names already have it, so switching a project to CODESYS keeps its channel names.

### D4. The relevance table

`targets.py` holds rows `(pattern, targets, reasons)`: a JSON path pattern over the version 2 config (`networks[*].master.on_plc_stop`, `networks[*].nodes[*].tx_pdos[*].entries[*].iec_location`, `networks[*]` with `role: slave`, ...), the set of targets that use it, and a reason per target that does not (the `MASTER_NOTES`/`NODE_NOTES` texts move here). It drives:

- **The page.** The server sends the table (patterns and UI keys, not reasons only) with the model. `field()`, `checkbox()`, `choice()` and fieldsets take the path they edit already, so one `usedBy(path)` call hides a field; choice options carry their own key (`sync_source=plc_cycle`). Tree entries, header menu items and start-page actions have keys too (`tree.raw`, `tree.gateway`, `tree.bridge`, `tree.access`, `menu.new_editor_project`, `menu.move_into_project`, ...).
- **The check.** A set value whose row does not include the target is a warning, `'on_plc_stop' is not used by CODESYS: CODESYS decides what the nodes get when the application stops`, with the path, so the Problems entry gets a Remove action (the existing per-problem fix button). Values the target refuses outright stay errors (`sync_source: plc_cycle` in a bridge config, as today).
- **The CODESYS plan.** `not_carried` = the CODESYS warnings, same text.

A field with a value that the target does not use is still shown (marked "not used by CODESYS", with Remove), so a kept value never hides silently. Empty unused fields are hidden.

### D5. What each target hides

| Setting or UI | OpenPLC | Bridge | CODESYS |
|---|---|---|---|
| `bridge` page and tree entry, Pack for Modbus, register map exports | – | ✓ | – |
| CODESYS fields (D2), Build into / Download for CODESYS | – | – | ✓ |
| OpenPLC Editor project: open from start page, Move into project, New editor project, declared marks, editor-overlap check and Allow overlap | ✓ | – | – |
| SYNC source "PLC cycle", `sync_cycles` | ✓ | – (refused) | – |
| scan watchdogs (`master.`, `j1939.`, `raw.scan_watchdog_ms`) | ✓ | – (ignored) | – |
| PDO entry `iec_location`, Suggest, location columns | ✓ | ✓ | – |
| master/node status locations (bus state, counters, node state, boot error, EMCY code, error register, NMT command), TPDO timeout location/ms | ✓ | ✓ | – |
| `sdo_variables`, CiA 402 `axis`, `lss`, `config_check`, `store_configuration`, `emcy_cob_id`, `retry_factor`, `heartbeat_timeout_ms`, node `revision_number`/`serial_number` | ✓ | ✓ | – |
| master `on_plc_stop`, `eds_lint`, `diagnostics`, `cia309`, `heartbeat_multiplier`, `error_behavior`, `reset_all_nodes`, `stop_all_nodes`, `boot_time_ms`, master identity, `sync_counter_overflow`, `emcy_inhibit_time_us` | ✓ | ✓ | – |
| `adapter.type`, `device`, `serial_baudrate`, `configure_link`, `restart_ms`, `simulate`; node `simulate`; Simulation view | ✓ | ✓ | – |
| slave, J1939 and plain CAN networks; raw messages; `gateway` | ✓ | ✓ | – (choices disabled with "stays with canworks") |
| Online access page; Commission through the runtime | ✓ | ✓ | – (Commission through a USB adapter only) |
| Everything else (bit rate, node IDs, PDOs, startup SDOs, heartbeat, guarding, PDO links, TIME, NMT start options, SDO timeout, DCF/DBC/HTML exports, notes, trace) | ✓ | ✓ | ✓ |

`on_plc_stop` stays for the bridge (it applies when the bridge stops). Node `revision_number`/`serial_number` are the plugin's identity check; if task 7.2 shows the CODESYS script can tick the device's identity checks, they move to "used by CODESYS" in a follow-up.

### D6. Switching

`/api/switch_target {config, target, keep}` returns the new config and the list of unused settings, computed server-side from the table (one place for the rules). The page shows the list in the confirm dialog ("CODESYS does not use: 12 status locations, 3 SDO variables, scan watchdog, ...") and applies the result as one undo step.

- To CODESYS: entries get `name` = their current generated name when they have none; with **Remove them** (default) every unused value is dropped, with **Keep them** they stay and show as warnings. `bridge` is removed either way (it is the old target's marker).
- From CODESYS: `codesys` objects are removed; the existing pack (`/api/pack_openplc`, `/api/bridge/pack`) gives every entry without a location one. Entry `name` stays, so declarations and register rows keep the CODESYS channel names.
- OpenPLC ↔ bridge: today's repack choice, plus the unused-settings list with Remove/Keep.

### D7. CODESYS actions

`/api/codesys/build {config}` saves nothing itself: it requires a saved config (like New editor project), runs `cli`'s `--codesys-import` path in a job with the config's `codesys` settings, and streams the report into the log. It is offered when `codesys.run.find_codesys()` finds an install on this PC; otherwise the button explains that CODESYS was not found and Download for CODESYS is the route. A failure mentioning the project lock gets the hint "close the project in CODESYS first". Download for CODESYS is today's `/api/export_codesys` with the plan settings from the config.

### D8. Refusals

The plugin's config loader errors on a top-level `codesys` (`this config is for CODESYS (codesys); import it with canworks-deploy --codesys-import`), and so does the bridge (same loader). `canworks-deploy --runtime/--bridge` stops before upload with the same message, as it does for a bridge config on OpenPLC.

## Risks

- **Hidden values confuse.** Mitigated by D4: a value that is set is never hidden, only marked.
- **Page code churn.** Most fields already pass their path; the work is one `usedBy` check in the field helpers and keys on tree/menu entries. Playwright tests per target pin it.
- **Names.** Entry `name` adds a uniqueness check across the config; the check reports duplicates with both paths.

## Open questions

- Identity check ticks and the manager's NMT error behaviour from the script (task 7.2 probes them; mapping them is a follow-up).
