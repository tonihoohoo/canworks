# Design

## Context

Everything here lives in the configurator page (`tools/deploy/canworks/configurator/static/`):

- `explain.js` builds the inspector (`fxInspector`) and the Frame lab (`renderFrameLab`, `fxBuilder`, `fxArbitration`).
- `trace.js` docks the inspector with `traceSplit()`. "Hide inspector" sits in `.trace-split-bar` above the list.
- Below 1280 px, CSS (`style.css` `@media (max-width: 1279px)`) stacks the inspector under a list of fixed height (`.ids-grid` `height: max(244px, …)`). The inspector is `position: static` there, so it lands below the fold.
- The trace prefs (`/api/trace/prefs`, stored by `transmit.py` `check_prefs`) already keep `inspector` and `split` on this PC.
- `updateSimBanner()` in `app.js` writes `simSummary()` plus the warning as one paragraph.


## Goals / Non-Goals

**Goals:**
- One obvious way to close each panel, and an obvious way back.
- A new result always shows where the user is looking, at 1440×900 and 1000×800.
- Less height for the same explanation.

**Non-Goals:**
- Folding the Frame lab into the inspector as a drawer (option C of the findings). That is left for later.
- Any change to the explanation model (`/api/explain`), the CLI or the docs generator. The two bug fixes stay on the page, except that the "Node ID null" caption is checked against the model's `node` field.
- Changes to Sequences, Graph or the transmit list.

## Decisions

### D1. The inspector's title bar carries ✕; closing leaves a rail
- The inspector host gets a header row (title "Inspector", ✕). "Hide inspector" and its separate bar go.
- Closed, `.trace-split` keeps a 28 px column (or row, when narrow) holding a vertical **Inspector ›** button, with `aria-expanded=false`. A floating button was the alternative, but it covers rows. The rail keeps the way back where the panel was.
- Esc is handled on the inspector host only, so Esc in the list keeps its current meaning (none) and Esc in menus still closes them.
- Reopening on select: `selectRow()` with a click or Enter sets `T.inspector = true`. Arrow-key moves go through a separate path (`fxMoveSelection` and keyboard handlers), which does not reopen. The reason: the arrow keys are for scanning the list, while a click is a request to look at a frame.

### D2. Narrow windows share the height of the viewport
- Below 1280 px the split becomes a grid with two rows inside a box whose height is `calc(100vh - top of box)`. The list gets `minmax(120px, (100 - split)%)`, the inspector the rest. Each scrolls on its own, and the existing handle resizes it (it is already `row-resize` there).
- The page scrolls so the split box's top is at the top of the window on the first selection.
- A bottom sheet over the list was considered. It hides the selected row and needs focus trapping, while a shared height needs neither.
- Phone width (under 640 px) keeps the stacked layout, but the inspector gets `scrollIntoView` on select.

### D3. Folding layers with `<details>`, state in the trace prefs
- Identifier, Data bits and On the wire become `<details class="fx-layer">` with the `h3` inside the `summary`. The summary gets a muted one-line summary:
  - Identifier: `id.math` or the identifier text.
  - Data bits: the hex bytes.
  - On the wire: "N bits, S stuff bits, T µs".
- The fold state is a new pref, `fx_fold` (a list of the folded layer keys `id`, `data`, `wire`), checked in `check_prefs`. The Frame lab loads the same prefs (`traceLoadPrefs`), so both views agree.
- Local storage was the alternative. The trace prefs are already the "kept on this PC" store, and they survive a browser change.

### D4. Compact grid
- Bit cells shrink from 24 to 18 px high. The CANopen bit number moves from above each cell into its `aria-label`, its tooltip and the box, with one header row of numbers kept per grid (b7…b0). Targets keep 24 px of width, and the layout check allows 18 px of height for `.fx-bit`, as with checkboxes. A full row then takes about 26 px, so 8 bytes take about 210 px plus the header.
- Grouping: a run of 2 or more whole bytes owned by one field becomes one `<details class="fx-byte-run">` row whose summary shows the field colour, name and hex. Its bits render inside it, so the roving focus still finds them when it is open. When it is closed the summary itself is the tab stop, and Arrow keys move to it as one item.
- Groups stay open while the user points at a field whose bits are inside.

### D5. Frame lab: one frame box, mode tabs, result column
- Layout: `.fx-lab` is a grid. At 1280 px and wider it has `minmax(380px, 1fr) minmax(0, 1.4fr)`, and the result column is `position: sticky; top: header` with its own scroll. Below 1280 px it has one column ordered frame box, result, tabs.
- Tabs use the existing `tabs()` helper (keyboard and focus handling). The chosen tab goes in `FX.lab.mode` for the page session. The old `builderOpen` and `arbOpen` details states are removed.
- The arbitration output renders into the result column (`#fx-lab-inspector`) and replaces any inspector there. Explaining a frame replaces the arbitration output.
- **Clear** sits in the result's header next to the frame text. Clearing bumps `_fxSeq`, so a late answer does not draw.
- Result in view: after drawing, call `scrollIntoView({block: "nearest"})` on the result host when the host's top is outside the window. In the wide layout the sticky column is already in view, so this is a no-op.

### D6. Arbitration bus after the decision
- From `decided + 1` the loser's row draws "–", which it already does. The bus is computed from the winner's bit only: `bus = n > decided ? winnerBits[n].v : wa & wb`.

### D7. "Node ID null"
- The caption for the `node` part uses `id.node != null ? "Node ID n" : "Part of the identifier (no node ID)"`, and the bits keep the identifier colour instead of the node colour. `fxExplainId` already skips the node line when `id.node` is null.

### D8. One-line simulation banner
- `simSummary()` gets a short form: the network label plus "(node 5)", "(nodes 5, 6, 7)", "(bus only)" or "(slave)". The banner shows "Simulated: io (nodes 5, 6, 7), motion (node 4), cell (slave), host (bus only). Do not upload as it is." with a **Details** `<details>` holding today's full sentences.
- The text overflows with an ellipsis on one line, and the full text sits in Details and in the accessible name. Wrapping to 2 lines is allowed under 640 px.

## Risks / Trade-offs

- [Risk] Tests that click "Hide inspector" or read `data-trace=inspector-toggle` break. → Keep the `data-trace=inspector-toggle` hook on the new ✕, add `data-trace=inspector-rail`, and update the tests in the same change.
- [Risk] Shared height in narrow windows makes the list short on low-height screens. → The list keeps a 120 px minimum, the handle resizes it, and a closed inspector gives the list the full height.
- [Risk] A folded Data bits layer hides the field a user points at on the wire. → Pointing at a wire data bit opens the box explanation as today. The box does not depend on the grid being visible.
- [Trade-off] Bit numbers above each cell go away. They stay one hover or focus away, in the header row and the box, which docs/frame-inspector.md already describes as the place for explanations.
- [Trade-off] The 18 px cells fall below the 24 px target height rule used by `Layout.fits()`. → The exception is scoped to `.fx-bit` with 24 px width, like the existing checkbox exception, and recorded in the test.
