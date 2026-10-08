# Design

## Context

- The configurator is a vanilla-JS single page (`app.js` 5.6k lines, `trace.js`, `sim.js`, `explain.js`) rendered from one draft object `S.cfg` through an `el()` helper. Every edit goes through `setPath()` → `changed()` → `scheduleCheck()`, which is why a snapshot-based undo is cheap: there is one mutation point and one render per view.
- Confirmations use the native `<dialog id="modal">` through `modal(text, buttons)` (app.js:72-86); `showModal` focuses the first focusable element, which today is the destructive button.
- The review material is in the project notes (`research/ui-ux-review-2026-10-08.md`, screenshots and `report.json`/`report2.json` under `research/ui-ux-review/`). The axe-core run reported `aria-allowed-attr` (critical, Trace tabs), `color-contrast` (serious, `--ok`, inspector tints), `heading-order`, `landmark-complementary-is-top-level` and `empty-table-header`. The interaction probes showed the Export DCF button under the node click point, 5 → 9 problems after one export, "null" text, the destructive default button and the click-only lists.
- `fix-configurator-layout` (archived) already covers clipping, sideways scrolling, the 1100 px breakpoint, the theme and the message bar timing; its `FIT_CHECK` in `tests/test_configurator_layout.py` is the place to add the axe run.

## Goals / Non-Goals

**Goals:**
- No way to trigger an export or lose a problem count by opening a node.
- Every destructive step is either confirmed with a safe default or undoable.
- Everything the mouse can reach, the keyboard can reach; tabs, lists and progress are understood by assistive technology; WCAG 2.1 AA contrast and 24 px targets.
- A header with the frequent actions and a node page the user can navigate.
- Messages in the user's words, busy states on every request, and an automated check that holds the line.

**Non-Goals:**
- A visual redesign, a framework, or a component library. The page keeps its look and its `el()` rendering.
- Reordering, duplicating or disabling nodes (not asked for; could follow).
- A separate "Connection" side bar entry and a new narrow layout (listed in the review as later work).
- Changes to the deploy tool CLI, the plugin or the diagnostics protocol.

## Decisions

### D1. Export DCF leaves the node list
The per-node export becomes a button next to "Remove node" on the node page and an entry "This node's DCF" in the Export menu. The node list item is a `<button class="nav-item">` with the name and the error count, nothing else. Alternative: keep the hover button in a fixed right column; rejected because a control that appears under the pointer still steals clicks on a short name, and the list is the most used control on the page.

### D2. Export checks replace, never append
`exportDcf`, `exportDbc` and `exportHtml` set `S.check = r` (items, errors, warnings as the server returns them) and call `applyCheck()`; the next `runCheck()` restores the edit-time result as today. The server's export check already includes the config check, so nothing is lost. Counts come from the items, in one `countProblems()` used by the pane, the side bar and the Save tooltip.

### D3. Dialog defaults
`modal(text, buttons)` keeps its signature and gets a convention: the first button is the safe one (Cancel or Keep), the last is the action; `{danger: true}` on a button adds `class="danger"` (red text and border, `--error`). After `showModal` the safe button is focused explicitly, so Enter cancels and the dangerous action needs a deliberate Tab or click. Dialogs with a form (new project, restore) focus their first input as now, with the action button last. The `cancel` listener is added once, not per open.

### D4. Undo as a draft snapshot stack
`changed()` pushes a structured clone of `S.cfg` (and the active network and view) onto `S.undo` before applying an edit, capped at 50 entries, coalescing consecutive edits of the same `data-path` within 1 s so typing is one step. Ctrl+Z / Ctrl+Shift+Z (Cmd on macOS) pop and re-render; when focus is in a text field, the browser's own undo runs first and the global one only when the field has nothing to undo (`input.value === S.lastRendered[path]`). Removals of a PDO entry, startup SDO, SDO variable, slave object, descriptor object or route show "Removed 0x6150:1 from TPDO 2. Undo" in the message bar for 6 s; the link pops the stack. Online, trace and simulation actions are not in the stack (they are not edits of the draft). Alternative: confirm every ✕; rejected as the slower and more annoying of the two patterns.

### D5. Lists are buttons, rows get `tabindex`
`#node-list li` and `#problem-list li` render a `<button>` inside (full width, same style), so they are in the tab order with Enter/Space for free and the active one has `aria-current="true"`. Clickable table rows (`tr.clickable` in Online and Scan, device rows in Simulation) get `tabindex="0"`, `role="button"` and a shared `rowKeys()` handler for Enter and Space, as the Sequences tables already do. The trace frame list keeps its own model (one tab stop, arrows) and adds Home/End and PageUp/PageDown.

### D6. One tabs helper
`tabs(items, active, onPick)` in app.js returns a `<div role="tablist">` of `<button role="tab" aria-selected aria-controls id>` with Left/Right/Home/End moving the selection, and the content host gets `role="tabpanel" aria-labelledby`. Trace (`data-trace-tab`), the Online node tabs and the Simulation tabs use it; `aria-pressed` stays on the real toggle buttons (theme, Relative/UTC, sub-tabs that are filters).

### D7. Live regions and landmarks
`#problem-count` and the job/scan progress lines get `aria-live="polite"`; the message bar gets `role="status"` for information and switches to `role="alert"` for errors. `#problems` and `.fx-box` become `<section aria-label>`; the side bar captions become `<h2>`s styled as today, and in-view fieldset captions stay `<legend>`s. The action column of every table gets `<th><span class="visually-hidden">Actions</span></th>`.

### D8. Header menus
Two native `<details class="menu">` elements ("Project ▾": Move into project…, New editor project…; "Export ▾": All DCFs, This node's DCF (enabled on a node page), DBC with the SDO-frames choice inside the menu, Documentation) with `role="menu"`/`menuitem`, Escape closes, and one open at a time. Commissioning mode renders neither menu, no Save and no Problems pane; the side bar lists Online, Scan, Trace and Frame lab. Alternative: a custom dropdown; rejected since `<details>` gives keyboard and click-outside behaviour with no code.

### D9. Node page sections
The node view renders a sticky bar under the heading with anchors to its sections; the active section follows scrolling with an `IntersectionObserver`. Startup SDO writes and SDO variables render as `<details>` open when they have entries or an error, collapsed when empty, with the count in the summary. "Map an object" is rendered per PDO block as "Add entry…" that opens the same object picker filtered to that PDO's direction; a fixed-mapping PDO keeps "Map all".

### D10. Busy states and the Save button
`busy(button, label, fn)` disables the button, swaps its label for "Saving…" / "Exporting…" / "Adding…" and restores it after the promise settles; a second click while busy does nothing. `updateSave()` sets "Saved" + disabled when the draft is clean, "Save" when dirty, "Save (overlaps allowed)" when the override is on; errors no longer go into the label, the button's `title` says "N errors in Problems" and the button is disabled, so the state reads at a glance and the count lives in one place.

### D11. Wording
The empty-config check message is rewritten on the server (`canopen_check` keeps the deploy CLI text; the configurator maps the `nodes` empty-list error to "No nodes yet. Add a node from its EDS, or turn on Online access for a scan-only configuration."). The trace and Frame lab "decoding without the config's PDOs" notes pass through the same `humanise()` that the Problems pane uses. Unhandled exceptions in the server become `{"error": "The configurator hit an error; see its terminal."}` with the traceback logged to the terminal.

### D12. Automated check
`tests/data/axe.min.js` (axe-core 4.10, MPL-2.0, noted in `_lely_dcf`-style NOTICE) is injected after each `fits()` in the layout test; the test fails on any violation of impact critical or serious, listing rule, node and view. Moderate and minor findings are reported but do not fail, so a new view cannot regress silently while style nits do not block CI.

## Risks / Trade-offs

- **Undo and server checks**: popping the stack re-renders and reschedules the check; a check result from before the pop can land after it. The existing `seq` guard in `runCheck` already drops stale results.
- **Buttons inside the node list** change selectors used by the page tests (`#node-list li[data-node]`); the `data-node` attribute moves to the button and the tests are updated in the same change.
- **Collapsed sections** hide where to add the first startup SDO; the summary says "Startup SDO writes · none · Add" so the action is still visible.
- **Header menus** put the exports one click further away; they are rare actions, and the per-node DCF export gains a visible place on the node page.

## Migration Plan

No data, config or protocol change. The deploy tool minor version bumps; the PC tools update as usual. Page tests that click list items or header buttons are updated with the code.

## Open Questions

- Whether "Move into project…" and "New editor project…" should stay on the start page only (they are one-time actions) rather than a Project menu. The proposal keeps the menu so a standalone config can be moved without closing it.
