## 1. One place for failed exports

- [ ] 1.1 Add a notice slot at the top of `#problems-box` (above `#overlap-box` and the list) in `index.html`
- [ ] 1.2 Add `exportStopped(label, r, cfg)` to `app.js`: set `S.check = exportProblems(r, cfg)` with `S.check.export = label`, `applyCheck()`, open `#problems-box`, scroll `#problems` into view, clear the message bar; when `#problems` is hidden, fall back to the old `banner(..., true)` text
- [ ] 1.3 Draw the summary in `applyCheck()`: `notice("error", "<label> export stopped. Nothing was downloaded. Fix the problems below and export again.")` while `S.check.export` is set, nothing otherwise
- [ ] 1.4 Use `exportStopped()` in `exportDcf`, `exportHtml`, `exportCodesys`, `exportDbc`; remove their "export stopped ... (see Problems)" bars
- [ ] 1.5 Success with warnings: "Exported <name> with N warnings." in the message bar and open Problems; drop "(see Problems)"

## 2. Register map and Node-RED flow

- [ ] 2.1 `bridgeExport()` in `bridge.js` uses `exportStopped("Register map" | "Node-RED flow", ...)` instead of joining findings into the bar
- [ ] 2.2 Make `/api/bridge/export` return findings as `items` with `level`, `message` and config `paths` like the other export endpoints, so rows click to their field

## 3. Tests and docs

- [ ] 3.1 Update `test_configurator_page.py`, `test_configurator_docs_page.py` and `test_configurator_ux_page.py`: a failing DCF, DBC, Documentation, CODESYS and register map export shows the Problems summary, lists the findings once, opens a closed Problems panel and leaves `#banner` hidden
- [ ] 3.2 Test the summary clears after an edit and the fallback bar when Problems is hidden
- [ ] 3.3 Update `docs/configurator.md` (Problems and message bars) and README if it mentions the export bar
