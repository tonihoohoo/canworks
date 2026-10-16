## Context

The Object dictionary tab got a selected row in od-row-highlight: `--sel-bg` wash on every cell, a 3 px `--accent` bar on the first cell, `--hover` under `@media (hover: hover)`, `aria-current`, delegated `pointerdown`/`focusin` listeners and a key kept in the tab state. Other lists grew their own cues: `.trace-row.selected`, `.ids-row.selected`, `table.fx-table tr.selected` and the CAN messages rows fill with `--accent`; `.tree-item.selected` uses `--hover` and bold; `tr.row-open:focus-within` (notes tables) uses the wash only while focus is inside. Most tables (pickers, startup SDO list, commission plan and diff, PDO tables, simulator, J1939, bridge, links) have no cue at all.

The node page's pickers sit in `.objects` boxes (`max-height: 340px`). The trace view already has a resize bar (`traceSizeBar` in `trace.js`) with drag, arrow keys and double-click reset, its heights kept in `trace.json`.

## Goals / Non-Goals

**Goals:** one look and one behaviour for a selected row wherever rows are items; let the user make list boxes taller or shorter; show device notes in the SDO variables picker.

**Non-Goals:** multi-select, actions on the selection, changing the trace inspector's keyboard model, resizing dialogs.

## Decisions

- **The Object dictionary look wins.** A wash plus a left bar keeps buttons, selects and coloured text (EMCY red, error rows, Tx marks) at their own contrast, which a solid accent fill does not; the readable-controls requirement needed special rules to make buttons survive the fill. The solid accent rows are removed, so those special rules go too.
- **One page-wide selection, not a call per table.** Delegated `pointerdown` (capture) and `focusin` listeners on the document select the row they land in, in any `<tbody>` row of a table that is not skipped (`online-bus`, bit grids, the tables with their own selection: Frame lab, CAN messages, object dictionary, or `data-no-select`). A list is named by where its table sits (the nearest `data-path`, `data-picker`, node tab panel or id, the table's class and data, and its place among like tables there); a row by `data-sel`, else its first cell's text, else its place. The selected keys live in one in-memory map, and a mutation observer re-marks rows after any re-render (throttled to a frame, and only while something is selected). Every item table, including ones added later, gets the behaviour with no per-table code. Not saved: selection is a cue, not a setting. The object dictionary tab keeps its own `od-selected` code (its keys survive its folding and search) and shares the CSS.
- **Lists with an inspector keep their selection model.** Trace Chronological, By identifier and Frame lab already select by click and arrow keys and feed an inspector; only their CSS changes to the shared look, and they keep their own selected state.
- **Tree.** The network tree's selected entry takes the same wash and bar instead of hover and bold, so it reads as the same thing.
- **Which tables.** Rows that are items get selection. Key/value status tables (`online-bus`), bit grids (`fx-bytes`, `raw-grid`) and header-only tables do not, since a row there is not something the user acts on.
- **Resize bar: reuse the trace one.** `traceSizeBar` moves to `app.js` as `sizeBar` and the trace view uses it unchanged. A list box declares `data-box="<kind>"` (and `data-box-label`), and the page puts a bar right after it (the same mutation observer finds new boxes), setting the box's `max-height`. Drag, Up/Down 40 px, double-click for the default, range 120 to 3000 px, `role="separator"` with `aria-valuenow`. CSS `resize: vertical` was considered: its corner grip is tiny, cannot be reached by keyboard and does not work on boxes with a sticky table header in every browser, and the trace view already taught users the bar.
- **Heights per kind, in `ui.json`.** One height per kind of box (`pdo_picker`, `sdo_picker`, `sdo_var_picker`, `od_table`, ...), not per node, so a height chosen on one node applies to all nodes. Kept with the other page settings (theme, node tab) because browser storage is lost with the port change at each start. Unknown kinds or out-of-range values read as the default.
- **One note summary.** `noteLine` today returns nothing unless the note has text, details or a manual. It becomes the one summary used by the pickers, the lists and the Notes tab: the text (details and manual on hover, as now), then a muted line `unit bar · ×0.01 · 0 = off, 1 = on` or bit meanings `bit 0 = ready, ...`, long value lists cut after six with the rest on hover. The Notes tab's own `meaning` line moves onto it.
- **Notes in the SDO variables picker** reuse `noteLine(noteOfObj(o))` as the Startup SDO writes picker does; each added variable's header gets `noteLine` of its object, as the Startup SDO writes list rows have.

## Risks / Trade-offs

- [Many files touched] → the helper is small and each list only adds a `data-sel` key and one call; page tests cover one list per page plus the Object dictionary tests that already exist.
- [Users of the trace lists are used to the solid fill] → the bar and wash are clear at a glance and match the rest of the tool; the inspector still follows the row.
- [Other open changes touch the same pages] → rebase on whichever merges first; this change only adds attributes, one call per list and CSS.
