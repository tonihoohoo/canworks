## 0. Order

- [x] 0.1 Apply after `add-plcopen-export` (#259, merged); rebase on main and rewrite the deltas against the archived text where they touch the same requirements. `add-nodered-blocks` follows this change and turns its export into the Node-RED connection's Download

## 1. Config and checks

- [x] 1.1 `targets.py`: two targets (Modbus bridge, CODESYS); the relevance table keys OpenPLC-only rows on `conn:openplc` instead of a target
- [x] 1.2 Schema and `bridgecheck`: `bridge.connections` (kinds, unique names, addresses, one `openplc`), refusal of `bridge.openplc` with the one message, OpenPLC connection checks (`plc_link` true, `word_order` `low_first`), writers-differ warning, loopback listen error naming the connection
- [x] 1.3 Plugin configs (neither `bridge` nor `codesys`): one refusal message naming **Use with canworks-bridge** in the bridge, deploy and check

## 2. Bridge

- [x] 2.1 `config.cpp`: drop `parse_openplc` and its defaults; refuse `openplc` with the message; accept `connections` as a list without reading it, refuse other types; tests

## 3. PC tools

- [x] 3.1 `openplcmodbus.py` and the editor project files read the OpenPLC connection (`poll_ms`, `remote_device`, `iec_base`) instead of `bridge.openplc`
- [x] 3.2 `modbusmap.py`: map hash and Pack for Modbus unchanged by `connections` (the hash ignores them)
- [x] 3.3 PLCopen: remove `--for codesys`, `--codesys-plc`, `--codesys-ethernet`, the CODESYS plan, CODESYS-style globals and `codesys/script/import_canworks_modbus.py`; `--for codesys` refused with the message; shared PLC lookup stays for `import_canworks.py`
- [x] 3.4 `canworks-deploy` check, local runtime and device page key on the OpenPLC connection

## 4. Configurator

- [x] 4.1 New config…: two cards with the works-with list; Project target field with two choices; switching to and from CODESYS drops or keeps connections as specified
- [x] 4.2 Modbus bridge page: Connections first (rows, Add connection with five kinds, Settings per kind, Download, Remove), empty-list text, one undo step per change
- [x] 4.3 Server download routes per kind reusing the CLI code; Download stores `map_hash`; Out of date / Not downloaded yet / In sync states; Problems warnings
- [x] 4.4 Writers follow the connections; "Who may write"; **Use the connections' addresses**; **Listen on all addresses**
- [x] 4.5 Adding an OpenPLC connection sets the bridge settings, mailboxes and live lists and repacks; New editor project… / Move into project… / Use with this OpenPLC project; Remove asks and leaves editor files
- [x] 4.6 Export ▾: network files only, plus Download for CODESYS on CODESYS configs; remove the register map buttons, For another PLC dialog and CODESYS route text
- [x] 4.7 Plugin configs open read-only with **Use with canworks-bridge**

## 5. Examples, fixtures and wording

- [x] 5.1 Convert repo examples and test fixtures from `bridge.openplc` to an OpenPLC connection (clean cut, no auto-conversion)
- [x] 5.2 Wording-only updates in `canopen-editor-project`, `modbus-bridge-map`, `modbus-bridge-mailboxes`, `device-install`, `canopen-virtual-example`, `canopen-deploy` and `canopen-ci` where they say "OpenPLC target" or `bridge.openplc`

## 6. Tests and CI

- [x] 6.1 Unit tests for the checks, downloads and hash; bridge tests; page tests for Connections, writers, out of date, New config and Export ▾; golden files without the CODESYS route
- [x] 6.2 State CI wall time and summed job time against the baseline in the PR

## 7. Docs

- [x] 7.1 README (Modbus bridge first, connections), `docs/configurator.md` (the placement rule), `docs/modbus-bridge.md`, `docs/openplc.md`, `docs/plcopen.md` and `docs/codesys.md` without the Modbus client route, tour lines
- [x] 7.2 Version bump of the tools

## 8. Hardware and desktop

- [x] 8.1 Pi: a converted OpenPLC project with the OpenPLC connection runs against node 23 (values both ways, status at %IB4)
  - 2026-10-23, tools and bridge 0.124.0: canopen-node23-modbus converted with Add connection → OpenPLC, rebuilt and uploaded; `canworks.ok` TRUE, status block at %IB4 (link ok, counter moving), map hash 0xbbb64e18, SDO 0x1018:1 and 0x1008 reads, a forced output reached node 23 (0x217 toggling) and the heartbeat stayed operational. Found: the old `bridge.openplc` stayed after Add connection and blocked Save (fixed: Add connection → OpenPLC drops it and keeps its settings). The project's own `main.st` needed the 0.122.0 pin renames (`ALL_IDS`, `RECEIVED`).
- [x] 8.2 Mac and Windows: New config, add each connection kind, Download, out-of-date after a change, Export ▾
  - 2026-10-23, tools 0.124.0, both passed: two New config choices (bridge preselected); all five kinds added; each Download equals the command line's file (PLCopen XML apart from its creation time); a moved PDO entry turned the rows Out of date with one Problems warning each, Download again cleared them; Export ▾ holds network files only. Windows: LF line endings, folders with spaces fine. Found and fixed: the New config tooltip still named OpenPLC, and a config name with spaces stayed in Download names. Open: a config with OpenPLC and truST passes the check although the truST Download is refused (map size, 50 ms watchdog).

## 9. Archive

- [x] 9.1 `openspec archive modbus-connections` in the same PR
