## 1. Fixture and reader

- [x] 1.1 Copy the SP22 PLCopenXML exports of virtual-plant into tests as fixtures; check for vendor content (banned-word guard)
- [x] 1.2 `codesys/xmlimport.py`: parse devices, CANbus, manager, remote devices, parameters by id, elements, `<Mapping>`, SDO list with the implicit marker, identity `download` flags
- [x] 1.3 Converter to config: networks, manager, nodes, PDOs, entries with names and bits, user SDOs, carried `codesys` objects, EDS-default omission
- [x] 1.4 EDS matching: library by identity, repository file on this PC, missing list
- [x] 1.5 Import report (not carried, unknown parameters, skipped devices)
- [x] 1.6 Tests: fixture -> config equals virtual-plant apart from listed not-carried items; generated SDO rows skipped; disabled PDO; fixed address carried; missing EDS

## 2. Headless export

- [x] 2.1 `codesys/script/export_canworks_xml.py` (IronPython 2.7 + CPython): list devices with managers and active application, export the chosen device; stand-in support in `tests/fake_codesys.py`
- [x] 2.2 `run.py`: run it, project-in-use message

## 3. Schema and contract

- [x] 3.1 Schema v2 `codesys` objects on node, PDO, entry, startup SDO, network `managed`; relevance table rows; docs/config.md

## 4. Build in place

- [x] 4.1 Plan: carried settings, managed node IDs, removal list, COB-ID as `$NODEID+16#…` or literal
- [x] 4.2 `import_canworks.py`: read existing node, diff, write value changes (generic COB-ID string for COB-IDs), structural change -> replace from DCF, then carried settings
- [x] 4.3 Guarded identity-tick helper (internal API) with "set by hand" report fallback
- [x] 4.4 Read-back check after writing
- [x] 4.5 Stand-in: parameters with elements, generic COB-ID behaviour, regenerated SDO rows, update log; tests: run twice up to date, event timer only, mapping entry added -> replaced, node removed, node ID change moves default COB-IDs

## 5. Configurator and CLI

- [x] 5.1 Import from CODESYS… dialog (source, device list, preview with EDS states and Add EDS…, Create config / Add to this config, Add as new network / Replace)
- [x] 5.2 Build dialog: remove-nodes question
- [x] 5.3 `canworks-deploy --from-codesys`
- [x] 5.4 Configurator tests (Playwright) for the dialog and the remove question

## 6. Docs and release

- [x] 6.1 docs/codesys.md (import, round trip, what is carried, shared device id note), README.md, PC tools version bump

## 7. Check in CODESYS (Windows PC, Toni's typed go)

- [ ] 7.1 Import vp.project -> config; Build into a copy -> every device up to date, project XML unchanged
- [ ] 7.2 Edit event timer, a variable name, add a mapping entry, add a startup SDO, delete a node in canworks; Build -> only those change, fixed addresses and SDO flags set in CODESYS survive
- [ ] 7.3 Identity ticks: confirm the UI tick equals the download flag, and the helper sets them
