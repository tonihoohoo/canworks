## 1. Shared helpers

- [x] 1.1 Page-wide row selection in `app.js`: delegated `pointerdown`/`focusin`, Escape clears, `.row-selected` + `aria-current="true"`, selection map re-applied after every render
- [x] 1.2 Move `traceSizeBar` to `app.js` as `sizeBar`; trace view uses it unchanged; `data-box` boxes get a bar
- [x] 1.3 `server.py`: list box heights per kind in `ui.json` (120 to 3000 px, unknown or broken values read as the default)

## 2. Selected row everywhere

- [x] 2.1 `style.css`/`rawcan.css`: one `.row-selected` rule (wash, 3 px accent bar, hover tint under `(hover: hover)`, forced-colours outline); remove the solid accent row rules and the `row-open:focus-within` rule
- [x] 2.2 Object dictionary tab keeps its own selection code and shares the CSS
- [x] 2.3 Configure page lists: PDO picker, Startup SDO picker and list, SDO variables picker, mapped PDO entries, slave objects and builder, gateway routes, links, notes tables, J1939 tables, bridge tables, simulator tables
- [x] 2.4 Commission page lists: nodes, configure plan and diff, PDO tables, restore tables, watch list
- [x] 2.5 Trace Chronological, By identifier, Frame lab tables, CAN messages rows: shared look, own selection model kept
- [x] 2.6 Network tree selected entry: shared look

## 3. Resizable list boxes

- [x] 3.1 Size bar under the PDO, Startup SDO and SDO variables pickers, slave objects and builder, gateway routes
- [x] 3.2 Size bar under the Object dictionary, simulator values and J1939 signals scroll boxes, Frame lab lists, bridge map, problems list

## 4. SDO variables notes

- [x] 4.1 Device note line under each object name in the SDO variables picker
- [x] 4.2 Note line of the object under each added SDO variable's header
- [x] 4.3 `noteLine` shows unit, scale, named values and bits (cut after six, rest on hover) and a note without text; Notes tab uses it
- [x] 4.4 PDO, Startup SDO writes and SDO variables picker filters match note text

## 5. Tests

- [x] 5.1 Page tests: click and Tab select a row in a picker, the Startup SDO list, a commission table and the CAN messages page; Escape clears; selection survives a field edit re-render and a filter that hides and shows the row
- [x] 5.2 Page test: dragging and arrow keys on the SDO picker's bar change its height; the height comes back after a reload and on another node; double-click resets
- [x] 5.3 Page test: the SDO variables picker and an added variable show the note line; a note with only a unit and named values shows on all three pickers; filtering by note text finds the object
- [x] 5.4 Layout, contrast and axe checks in Light, Dark and forced colours with a selected row in a trace list and a picker

## 6. Docs and release

- [x] 6.1 README.md and docs/configurator.md: selected row and resize bars
- [x] 6.2 Bump the PC tools minor version (with the doc golden files)
- [ ] 6.3 CI time: wall and summed job time against the main baseline in the PR description
