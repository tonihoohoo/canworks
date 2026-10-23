## Context

The OpenPLC target is `bridge` plus `bridge.openplc` (`targets.target()`). Everything `openplc` changes concerns the client:

- the bridge's defaults: `listen` 127.0.0.1:1502, `writers` 127.0.0.1, the watchdog at 5 × poll, word order low first;
- the PLC link (now also `plc_link`, from #259);
- the editor files;
- which exports the configurator offers.

Other clients get files from Export ▾ → For the program, which #252 grouped per target. PLCopen (#259) added `plc_link` for any bridge config and a CODESYS-as-Modbus-client transport, which Toni has now ruled out.

## Goals / Non-Goals

**Goals**
- A target means what runs the CAN networks: the Modbus bridge or CODESYS.
- Every Modbus client is shown the same way, as a connection on the Modbus bridge page, with its best hookup: synced files for OpenPLC, a download for the others.
- The page says when a client's files no longer fit the map.
- Several clients per bridge.

**Non-goals**
- Pushing files to a client: no CODESYS script runs, no Node-RED deploy (possible later per kind).
- Reading the client's state over the network.
- Any change to the CAN side or the Modbus wire format.

## Decisions

### Connections live in the config, the bridge ignores them

`bridge.connections` is a list of objects stored in `canworks.json`, so it travels with the project and the out-of-date check works on any PC. Each object has:

- `kind`: `openplc`, `trust`, `plc`, `nodered` or `hmi`;
- `name`: unique, 1-64 characters;
- `address`: an IP address; `127.0.0.1` for `openplc`;
- `writes`: a boolean; always true for `openplc`;
- the kind's own fields:
  - `openplc`: `poll_ms`, `remote_device`, `iec_base`;
  - `trust` and `plc`: `format` (`plcopen` or `st`), `library` (boolean), `bridge_host`;
  - `nodered`: `period_ms`, `bridge_host`;
  - `hmi`: `format` (`csv`, `json` or `st`);
- `map_hash`: the map hash of the last download, written by the configurator; not used by `openplc`.

canworks-bridge accepts `connections` as a list and does not read its entries: the bridge stays client-agnostic, and a new kind needs no bridge release. The PC check validates the entries.

*Alternative*: keep `bridge.openplc` and add `connections` for the others only. Rejected: OpenPLC would stay special in the file and in the code, which is the asymmetry this change removes.

*Alternative*: keep connections in the configurator's UI state only. Rejected: the state would not travel with the project, and the out-of-date check would work on one PC only.

### OpenPLC's bridge side becomes plain bridge settings

Adding an OpenPLC connection writes, in one undo step, the bridge settings that `openplc` used to imply:

- `plc_link: true`;
- `word_order` `low_first`;
- `listen` `127.0.0.1:1502` when `listen` is unset;
- `writers` (see below);
- `watchdog_ms` 5 × `poll_ms` (at least 50) when unset;
- mailboxes on (as the switch does today);
- a live list for every network;
- then a repack.

The check makes an OpenPLC connection an error when `plc_link` is not true or `word_order` is `high_first`, since OpenPLC's master reads 32-bit values low word first. The bridge needs no OpenPLC knowledge: `plc_link` already carries the header, hash and status rules (#259). The bridge refuses `openplc` with "field 'openplc' was removed: OpenPLC is a connection on the Modbus bridge page; open the config in the configurator and add it there". This is a clean cut, as nothing is in real use.

### Writers follow the connections

`bridge.writers` stays the bridge's allowlist. The configurator rewrites it to the sorted, de-duplicated addresses of the connections with `writes` true, as part of the same undo step as any connection change. The bridge page no longer has a Writers field; it shows "Who may write" from the connections.

- A config edited by hand whose `writers` differ from the connections gets a warning with **Use the connections' addresses**.
- A config without connections keeps `writers` as it is. A new bridge config has none, so it starts with `writers` [] and a hint to add a connection.
- `readers` stays as it is (advanced, unchanged).

`listen` stays an explicit field. A connection whose address cannot reach it (any non-loopback address while `listen` is loopback) is an error naming the connection, with **Listen on all addresses** (sets `0.0.0.0` with the same port).

### Out of date = map hash differs

A file connection stores `map_hash` when its Download runs. The page compares it with the current map hash:

- **equal**: Up to date;
- **different**: Out of date, with Download again, plus a Problems warning that opens the bridge page;
- **missing**: Not downloaded yet, with no warning.

The map hash already covers locations, sizes and word order, and the bridge refuses a stale PLC-link program at run time. This warning tells the user before they hit that.

For OpenPLC, the existing "Out-of-date OpenPLC editor files" check stays as it is; the connection row shows its result: In sync, or Out of date with Save.

### Editor project and the OpenPLC connection

- **New editor project…** and **Move into project…** stay on the Project page's Editor project section. On a config without an OpenPLC connection they add one; Add connection → OpenPLC on a standalone config offers the same two actions.
- A config inside an editor project with no OpenPLC connection (made by hand) gets **Use with this OpenPLC project**.
- Removing the OpenPLC connection asks first. It leaves the editor files on disk, and Save then writes no editor files.
- The Editor project section is shown when the config is in an editor project or has an OpenPLC connection.
- The local runtime (`canopen-local-runtime`) and the device page's OpenPLC runtime row key on the OpenPLC connection instead of the target.

### Export ▾

- Network files only.
- "For the program" and its per-target table (`PROGRAM_EXPORTS`) go away. Each item becomes the Download of its connection kind, with the same file and the same command-line equivalent.
- Download for CODESYS stays in Export ▾ on CODESYS configs, next to the network files: it is the CODESYS target's own output, not a Modbus client.

### No CODESYS as a Modbus client

Removed:
- `--for codesys` and its dialect (`addData`, `qualified_only`);
- `canworks-codesys-modbus.json`, `import_canworks_modbus.py`, and the options `--codesys-plc` and `--codesys-ethernet`.

Kept:
- `--for trust|generic`, writing standard TC6;
- `import_canworks.py` (the CODESYS target's script).

The "CODESYS route explained" line goes with it. A user who wants CODESYS gets the CODESYS target.

### Targets table

- `targets.TARGETS` becomes (`bridge`, `codesys`). OpenPLC-only rows (`ui:editor_project`, `ui:openplc_modbus`) become `conn:openplc` rows, which the page evaluates against the connections.
- `master.on_plc_stop` stays bridge-only as before. With a PLC-link connection, `on_client_loss` already says what happens when the PLC stops.
- The header mark reads "Modbus bridge" or "CODESYS". The mode badge already names the editor project.

### Plugin configs

The removed plugin's configs open read-only, as now. The button becomes **Use with canworks-bridge**. It adds `bridge`, plus an OpenPLC connection when the folder is inside an OpenPLC Editor project, with the same clean-ups as today's switch.

## Risks / Trade-offs

- **Every OpenPLC config and test fixture changes** (examples, page tests, the integration test config). This is acceptable as a clean cut; the apply converts them in one commit, with a small script that is not shipped.
- **Writers derived from connections hide a field.** A user who wants a writer that is not a connection adds a connection of kind HMI/SCADA with "writes" ticked, which also documents it.
- **`add-nodered-blocks`** (proposed) offers its package from Export ▾. It must hang off the Node-RED connection instead; tell that thread when this merges.

## Migration Plan

None for users. In the repo, `examples/` and test configs replace `bridge.openplc` with an OpenPLC connection plus explicit bridge settings. The bridge refuses old configs with the pointer.

## Open Questions

None. Toni's input is recorded in the proposal.
