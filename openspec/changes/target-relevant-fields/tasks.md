## 1. Table and wording

- [ ] 1.1 `targets.py`: `ui:declarations` OpenPLC only; label per row key for the bar (`LABELS` map next to `ROWS`), served with the table
- [ ] 1.2 Check items for unused values carry `unused: true` and the row key (CLI text unchanged)
- [ ] 1.3 `target.js`: `TARGET_TEXT` and `targetText(key)`; replace the literals of survey rows 7 to 15 (design.md) in `app.js`, `node.js`, `rawcan.js`, `links.js`; gate the address scan line by `ui:editor_project`; Advanced intro text without "dcfgen"

## 2. Page

- [ ] 2.1 `applyTarget`: set unused fields hidden like empty ones unless Show all is on; `shownFor(key)` replaces the `usedBy(k) || has value` exceptions in `renderPdos` (location column), `nodeTabs` (Simulation, CiA 402), SDO variables, `tree.js` (CAN messages, Online access, gateway), `simTabWanted`
- [ ] 2.2 Per-page bar: folded count, Remove all, Show, list rows with place, label, value and Remove; one undo step per action
- [ ] 2.3 Problems: one grouped unused warning with Remove all and a fold-out list; row click opens the page with the bar unfolded; badges and `.field-msg` skip unused items
- [ ] 2.4 View menu toggle "Show fields the target does not use" in the per-PC UI settings; dimmed and tagged fields; "· all fields" in the header badge; switch dialog Keep button "Switch, keep them hidden"
- [ ] 2.5 `readable()` and `humanise()` strip a config path with a drive letter

## 3. Checks

- [ ] 3.1 Unit: `readable()`/`humanise()` with POSIX and `C:\…` prefixes; check items `unused` flag; `ui:declarations` row
- [ ] 3.2 e2e: CODESYS project with leftovers: no location column, no Simulation tab, bars with counts, Remove all per tab and in Problems (undo), badges without them; Show turns the toggle on and brings the column back dimmed; toggle remembered across reload
- [ ] 3.3 e2e guard sweep per target (every page and tab, every setting set): no visible field outside the target's rows, no other target's words; with the toggle on every field visible
- [ ] 3.4 Update `test_configurator_codesys_page.py` "Leftover value" and any test that expected marked fields in place
- [ ] 3.5 README target section and docs/configurator.md: hidden settings bar, grouped problem, View toggle; PC tools minor version bump

## 4. Hand check (Windows desktop)

- [ ] 4.1 Open a CODESYS config with a left-over PDO entry location on Windows: no PLC location column, PDOs tab bar shows it, the message has no file path, Remove all clears it
