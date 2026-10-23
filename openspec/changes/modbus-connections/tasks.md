## 0. Order

- [ ] 0.1 Apply after `add-plcopen-export` (#259, merged); rebase on main and rewrite the deltas against the archived text where they touch the same requirements. `add-nodered-blocks` follows this change and turns its export into the Node-RED connection's Download

## 1. Config and checks

- [ ] 1.1 `targets.py`: two targets (Modbus bridge, CODESYS); the relevance table keys OpenPLC-only rows on `conn:openplc` instead of a target
- [ ] 1.2 Schema and `bridgecheck`: `bridge.connections` (kinds, unique names, addresses, one `openplc`), refusal of `bridge.openplc` with the one message, OpenPLC connection checks (`plc_link` true, `word_order` `low_first`), writers-differ warning, loopback listen error naming the connection
- [ ] 1.3 Plugin configs (neither `bridge` nor `codesys`): one refusal message naming **Use with canworks-bridge** in the bridge, deploy and check

## 2. Bridge

- [ ] 2.1 `config.cpp`: drop `parse_openplc` and its defaults; refuse `openplc` with the message; accept `connections` as a list without reading it, refuse other types; tests

## 3. PC tools

- [ ] 3.1 `openplcmodbus.py` and the editor project files read the OpenPLC connection (`poll_ms`, `remote_device`, `iec_base`) instead of `bridge.openplc`
- [ ] 3.2 `modbusmap.py`: map hash and Pack for Modbus unchanged by `connections` (the hash ignores them)
- [ ] 3.3 PLCopen: remove `--for codesys`, `--codesys-plc`, `--codesys-ethernet`, the CODESYS plan, CODESYS-style globals and `codesys/script/import_canworks_modbus.py`; `--for codesys` refused with the message; shared PLC lookup stays for `import_canworks.py`
- [ ] 3.4 `canworks-deploy` check, local runtime and device page key on the OpenPLC connection

## 4. Configurator

- [ ] 4.1 New config…: two cards with the works-with list; Project target field with two choices; switching to and from CODESYS drops or keeps connections as specified
- [ ] 4.2 Modbus bridge page: Connections first (rows, Add connection with five kinds, Settings per kind, Download, Remove), empty-list text, one undo step per change
- [ ] 4.3 Server download routes per kind reusing the CLI code; Download stores `map_hash`; Out of date / Not downloaded yet / In sync states; Problems warnings
- [ ] 4.4 Writers follow the connections; "Who may write"; **Use the connections' addresses**; **Listen on all addresses**
- [ ] 4.5 Adding an OpenPLC connection sets the bridge settings, mailboxes and live lists and repacks; New editor project… / Move into project… / Use with this OpenPLC project; Remove asks and leaves editor files
- [ ] 4.6 Export ▾: network files only, plus Download for CODESYS on CODESYS configs; remove the register map buttons, For another PLC dialog and CODESYS route text
- [ ] 4.7 Plugin configs open read-only with **Use with canworks-bridge**

## 5. Examples, fixtures and wording

- [ ] 5.1 Convert repo examples and test fixtures from `bridge.openplc` to an OpenPLC connection (clean cut, no auto-conversion)
- [ ] 5.2 Wording-only updates in `canopen-editor-project`, `modbus-bridge-map`, `modbus-bridge-mailboxes`, `device-install`, `canopen-virtual-example`, `canopen-deploy` and `canopen-ci` where they say "OpenPLC target" or `bridge.openplc`

## 6. Tests and CI

- [ ] 6.1 Unit tests for the checks, downloads and hash; bridge tests; page tests for Connections, writers, out of date, New config and Export ▾; golden files without the CODESYS route
- [ ] 6.2 State CI wall time and summed job time against the baseline in the PR

## 7. Docs

- [ ] 7.1 README (Modbus bridge first, connections), `docs/configurator.md` (the placement rule), `docs/modbus-bridge.md`, `docs/openplc.md`, `docs/plcopen.md` and `docs/codesys.md` without the Modbus client route, tour lines
- [ ] 7.2 Version bump of the tools

## 8. Hardware and desktop

- [ ] 8.1 Pi: a converted OpenPLC project with the OpenPLC connection runs against node 23 (values both ways, status at %IB4)
- [ ] 8.2 Mac and Windows: New config, add each connection kind, Download, out-of-date after a change, Export ▾

## 9. Archive

- [ ] 9.1 `openspec archive modbus-connections` in the same PR
