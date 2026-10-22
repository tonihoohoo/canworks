# Proposal

## Why

Toni asked for usability on different screen sizes (2026-10-21). The usability hunt measured the configurator at 9 window sizes (findings H2, M5, M16, L8 and the screen-size table in `research/ux-deep-hunt-2026-10-21`). The page fits *widths* well, and its tests check widths. What goes wrong is *height*:

- **Everything fixed takes 30-60 % of the window on common laptops.** At 1280×720, which is a 1920×1080 Windows laptop at the default 150 % scale, these are always on screen: header, sub-tabs, connection bar, simulation banner, the one-time "Online moved to Commission" note, and the bottom Problems/Log panel. Configure keeps about 460 px for work and Commission about 400 px. At 1366×768 at 150 % (911×512 CSS px), about 190 px is left.
- **No layout rule looks at height.** `style.css` has only width media queries.
- **At 1100 px and narrower the tree becomes a dropdown.** A user on a 1024 px window can't see the tree and a page side by side.
- **The Trace inspector takes about 40 % of the width before any frame is selected**, so Name and Decoded are cut at 1280-1366 px.
- **Target-specific header buttons push the header to two rows at 1366 px** (CODESYS: Build into CODESYS project…, Download for CODESYS). On a phone the header is four rows (about 410 px).
- Smaller points: the Problems resize handle looks like a horizontal scrollbar. On ≥1800 px windows, forms stay one narrow column with empty space beside them. The PDO table makes the whole page scroll sideways under 640 px.

## What Changes

- **Simulation status as a header chip.** The simulation banner becomes a warning chip in the header ("Simulated: 4 networks"), with Details in a popover holding today's full text and "do not upload it as it is". The chip keeps the warning tint and icon and is always visible. It takes no row of its own.
- **No "moved to Commission" note.** The one-time note from "Workspaces" is removed. The tour already explains the switch.
- **Bottom panel takes room only when it has something.** With no problems, Problems collapses to a one-line strip ("Problems: none"). A problem or a check opening it unfolds it as today. In Commission, Log starts collapsed and shows its count in the strip. The panel's height stays kept on this PC. The resize handle gets a grip mark and a thin line.
- **Connection bar in the sub-tab row.** The connection status (dot, target, round trip, network picker, Connect…/Disconnect) moves to the right end of the sub-tab row, so it is not a separate row. Bus state and allow-changes details stay, and wrap into a second line only when the window is narrower than the row needs.
- **Short windows (height ≤ 800 px).** The header and tabs use compact spacing (about 40 px header). Message bars overlay the top of the work area instead of pushing it down. The bottom strip is one line. Target: at 1280×720 the work area is at least 60 % of the window height in both workspaces.
- **Tree as a rail between 800 and 1100 px.** Instead of a dropdown, the tree becomes a narrow rail (about 56 px) showing network initials and node IDs with state icons and error counts, with the full tree as an overlay on hover, focus or the rail's button. Under 800 px, today's tree button stays.
- **Target actions in one split button.** The CODESYS actions (Build into CODESYS project…, Download for CODESYS) become one primary split button in the header. The bridge target gets **Install on device…** the same way. The header stays one row at ≥1280 px. Under 1100 px, the secondary header actions (Reload from disk, Close, Settings, Quit) go into one "⋯" menu.
- **Trace inspector closed until a frame is selected.** On a page load with nothing selected, the inspector starts as its rail. Selecting a frame opens it, as today. Under 1440 px, it opens as an overlay drawer over the right part of the list instead of taking columns away from it.
- **Wide windows.** From 1800 px, the Bus and master, Supervision and Advanced sections lay out their cards in two columns, as PDOs already do.
- **Narrow windows.** Under 640 px, the PDO table shows each entry as a card (object and name, then variable and location, then PDO and remove). Only a table's own box may scroll sideways, never the page.
- **Tests.** The layout check adds the sizes 1280×720 and 911×512, and checks that the work area takes at least 55 % of the window height on the main views of both workspaces.
- PC tools minor version bump; README screenshots unchanged unless the header changes them; docs/configurator.md "The page".

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `canopen-configurator`: "Simulation banner on one line" (becomes a header chip), "Narrow window layout" (rail between 800 and 1100 px), "Workspaces" (no moved note), "Bottom panel" (collapsed strip), "Close and reopen the inspector" (closed until a selection). New requirements: "Short window layout", "Header target action", "Wide window sections", "PDO table on a phone-width window", "Work area share in the layout check".

## Impact

- `tools/deploy/canworks/configurator/static/style.css` (height media query, rail, chip, strip, cards), `index.html` and `shell.js` (header chip, split button, overflow menu, connection status in the tab row), `connection.js`, `tree.js` (rail), `app.js` (bottom panel states, sim chip text), `trace.js` / `tracewin.js` (inspector start state, drawer), `node.js` (PDO cards).
- Tests: `Layout.fits()` sizes and the work-area share check; page tests for chip Details, panel strip, rail, split button, inspector start state; tests that look for the old banner or the moved note.
- No plugin, bridge or CODESYS export change. No hardware test. A desktop look on Windows at 150 % scale and on a Mac is a hand check.
