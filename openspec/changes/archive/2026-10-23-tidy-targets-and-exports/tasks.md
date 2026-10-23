## 0. Before applying

- [x] 0.1 Rebase on main after `openplc-modbus-followups` merged (it adds the "Use canworks.* in main" warning to the OpenPLC Project page); re-run `openspec validate tidy-targets-and-exports --strict`

## 1. Export menu

- [x] 1.1 `index.html`: Export ▾ with the group headings "Network files" and "For the program"; items Register map (CSV), Register map (JSON), ST variables ("ST for another PLC" on OpenPLC), Node-RED flow, Download for CODESYS calling the existing export functions (`bridgeExport`, `exportCodesys`)
- [x] 1.2 `app.js` render: For the program items per target (bridge: four; OpenPLC: CSV, JSON and ST for another PLC; CODESYS: Download), a group with no item hidden; the existing per-network hiding of the Network files items unchanged
- [x] 1.3 `bridge.js`: the register map toolbar keeps Pack for Modbus only, plus the line pointing to Export ▾ → For the program

## 2. Header

- [x] 2.1 Remove the Project ▾ menu and the target ▾ (`#menu-target`); the CODESYS Build button is a plain primary button
- [x] 2.2 One placement helper for header menu panels (Export, ⋯, Settings): right-aligned unless that crosses the window's left edge, then left-aligned
- [x] 2.3 Simulation chip compact form ("Simulated" with the full text in the tooltip and Details) when the header would wrap; the header is one row from 1280 px for every target with the chip shown

## 3. Project page and bridge page

- [x] 3.1 `target.js`: Editor project section on an OpenPLC config's Project page (project mode: name, folder, files Save writes; standalone: none, with Move into project… and New editor project… opening the existing dialogs)
- [x] 3.2 Move the OpenPLC facts table (remote device and port, requests per poll with the warning above 40, writer lost after, map hash, first editor locations) to the top of the OpenPLC box on the Modbus bridge page; Problems' request-count warning links to the poll field
- [x] 3.3 Bridge page heading "Modbus bridge" for every bridge target, with the OpenPLC line for OpenPLC configs

## 4. Names

- [x] 4.1 `targets.py` `TITLES`/`LABELS` and the page's `TARGET_TITLE`/`TARGET_LABEL`: "OpenPLC", "Modbus bridge", "CODESYS" (with "the" where grammar needs it); the plugin message and Switch to OpenPLC through Modbus unchanged
- [x] 4.2 New config: first choice "OpenPLC"; Modbus bridge sentence names Node-RED, HMIs and another PLC; check warnings, banners and tooltips use the three names (grep for "OpenPLC through Modbus" and "OpenPLC Runtime" in the page and in check messages)

## 5. Copy as ST call

- [x] 5.1 `targets.py` row `ui:st_calls` for Modbus bridge and OpenPLC; Copy as ST call in Commission OD and NMT, CAN messages and J1939 hidden when not used and in Commission a device without a config
- [x] 5.2 Needed-part hint: tooltip and first comment of the copied ST name the missing setting (SDO bridge registers, control block, request mailbox, receive mailbox) and its page

## 6. Tests

- [x] 6.1 Extend `test_configurator_layout.py`: one header row at 1280 and 1440 px with the simulation chip for OpenPLC and bridge, and every header menu panel inside the window
- [x] 6.2 Extend `test_configurator_bridge_page.py`, `test_configurator_codesys_page.py` and `test_configurator_openplc_modbus_page.py`: Export ▾ items per target, downloads equal to the command-line exports, no export buttons on the bridge page, OpenPLC facts on the bridge page, Editor project section, no Project ▾
- [x] 6.3 Copy as ST visibility per target and the needed-part comment, in the existing Commission and J1939 page tests; `test_targets.py` for the new row
- [ ] 6.4 No new test file or CI job; report CI time against the last green main runs

## 7. Docs and release

- [x] 7.1 `docs/configurator.md`: the "where things are" rule and the Export ▾ groups; `docs/modbus-bridge.md`, `docs/codesys.md` and the Node-RED section: button locations; README if it names a moved button; tour lines
- [x] 7.2 Tools minor version bump (0.120.0); "What's new" in the release notes comes from the PR title

## 8. Hand checks

- [ ] 8.1 Windows (CODESYS config): header one row at 1366 px, Build button with no ▾, Download for CODESYS from Export ▾
- [ ] 8.2 Mac (OpenPLC config with simulated nodes): header one row, Export ▾ fully on screen, Editor project section in standalone and project mode
