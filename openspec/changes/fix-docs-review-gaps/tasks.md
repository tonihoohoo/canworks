## 1. HTML documentation for J1939

- [ ] 1.1 `docexport.build()`: route J1939 networks to a new `_j1939_network()` that builds the ECU, DBC, messages, signals, requests, frame map, bus load (29-bit frame bits, transport-protocol frames for long messages, rx only with a DBC cycle time) and I/O rows; add `protocol` to every network and to the summary; default title "CAN network documentation"; `doc_schema_version` 2.
- [ ] 1.2 `docwriter.py`: render the J1939 section (ECU, message tables with signal rows, requests, frame map, bus load), the protocol column in the summary and the message count; `id="canworks-doc"`, theme key `canworks-doc-theme`.
- [ ] 1.3 Tests in `test_docexport.py`: the J1939 example (scenario values), a mixed CANopen + J1939 config (sections and sorted I/O), stable output, nothing private; update the JSON id in `test_docexport.py` and `test_configurator_docs_page.py`.

## 2. SDO blocks and J1939 networks

- [ ] 2.1 `PlcRequests::open()` takes the CANopen master network indexes; `validate()` returns `CANOPEN_PLC_ERR_INPUT` for any other index; `plugin.cpp` / `canopen_runtime.cpp` pass the list.
- [ ] 2.2 Remove `PlcSlave::RefusePlcRequests()` and its call (now refused at start).
- [ ] 2.3 Unit test in the plugin's ctest: a two-network set (CANopen + J1939) refuses `NETWORK := 1` with 6 in `start()`; a slave network index is refused the same way.

## 3. Old names

- [ ] 3.1 Rename the variables in design Decision 4 in the plugin, simulator, CMake files, `install-stock.sh`, `docker/local-runtime/Dockerfile` (also its "canopen-local-runtime" comment), workflows, test scripts and Python tests.
- [ ] 3.2 Help texts: `canworks-deploy` usage and `--config`, `canworks-sim` usage and run-mode text, `canopen_check` header: the config is `canworks.json`.
- [ ] 3.3 `scripts/rename_to_canworks.py`: add the Decision 4 pairs to the mapping and the check; tests in `test/ci/test_rename.py` (mapping, `CANOPEN_PLC_ERR_INPUT` and header guards kept).

## 4. Simulator fault kind

- [ ] 4.1 `simcli.py`: fault kind `nmt-state` instead of `nmt`; update its tests.

## 5. J1939 decoding without cantools

- [ ] 5.1 `bustrace/j1939.load_dbc()`: an `ImportError` of cantools becomes `ValueError("cantools is not installed; reinstall the PC tools")`, so the caller warns and goes on; test with cantools hidden (`sys.modules["cantools"] = None`).

## 6. Configurator start page

- [ ] 6.1 `index.html`: purpose line, the four choice texts from the proposal, `canworks-token` meta (and `app.js` reading it); `app.js`: folder browser titles and the "not an editor project" message say "OpenPLC Editor project".
- [ ] 6.2 `style.css`: `.start-choices` as a 2 × 2 grid, one column below the narrow breakpoint; check light and dark.
- [ ] 6.3 Tests: start page scenario in the configurator page tests (four choices in two rows at 1280 px, titles), `Layout.fits()` on the start page at 1000/1280/1440 and phone width; screenshot before and after in the PR.

## 7. Docs, README, version, CI

- [ ] 7.1 After `docs/review-refresh` is merged, rebase and update only the lines this change makes wrong: `docs/plc-sdo.md` error 6 row, `docs/network-docs.md` (J1939, JSON id and version), `docs/slave.md` state dir variable, `docs/development.md` test variables, the simulator fault kind in `docs/simulator.md` and `docs/diagnostics.md`, `docs/configurator.md` start page text, and README if it lists the HTML export as CANopen only.
- [ ] 7.2 Bump the PC tools minor version; release notes.
- [ ] 7.3 CI time: state wall and summed job time against the median of the last 5 green `main` runs in the PR body; new tests go into existing jobs.
- [ ] 7.4 Banned-word check on the branch (`--files` and `--range origin/main..HEAD`).

## 8. Hardware

- [ ] 8.1 On the bench PLC with a config that has a CANopen and a J1939 network (or the J1939 test config plus a CANopen network), an SDO block with `NETWORK` set to the J1939 network ends with `ERROR_ID` 6 in its first call.
