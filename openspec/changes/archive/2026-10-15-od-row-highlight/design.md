## Context

The Object dictionary tab (`app.js`, `entryRow` and the object rows built next to it) renders one `<tr>` per VAR object, per foldable ARRAY/RECORD object and per sub-entry, with the actions in a `td.actions` cell and the Watch box in the last column. Per-node tab state lives in `odState(id)`, which already keeps filters, open groups and the watch list across re-renders. The trace and frame lab tables already have a `.selected` row (solid accent fill), and the network tree uses `--hover` for its selected entry.

## Goals / Non-Goals

**Goals:** make it obvious which entry the row's buttons belong to, with mouse and keyboard alike, without changing what any button does.

**Non-Goals:** a toolbar or side panel for the selected entry; multi-select; changes to the Parameters tab or to which entries the tree lists.

## Decisions

- **Tint plus left bar, not a solid accent fill.** The trace rows use a full accent background, but OD rows hold buttons, a select and in-place inputs; under a solid accent their borders and text lose contrast. A tint (`--sel-bg`, a new token per theme between `--panel` and `--hover`) on every cell plus a 3 px `--accent` bar on the first cell keeps buttons readable and the bar meets 3:1 against the background in both themes. Alternative considered: an outline around the row; it is thin and gets lost in the row borders.
- **Hover is lighter than selection** (`--hover`) and applies only with `@media (hover: hover)`, so touch screens do not get a stuck hover row.
- **Selection key in `odState`.** `st.selected` holds the entry key (`index:subindex`) or `obj:<index>` for an object row. Every render applies it, so watch rounds, Read all and filters keep it without extra code. It is not saved to `ui.json`: selection is a moment-to-moment cue, not a setting.
- **One delegated listener on each group's table** (`pointerdown` and `focusin`) instead of one per row, so the 500+ rows of a large EDS add no listeners. `pointerdown` rather than `click`, so the row is highlighted before a button's own action runs (an Edit dialog opens over an already highlighted row). A text selection drag still works: selecting does not call `preventDefault`.
- **`aria-current="true"`** on the selected `<tr>` instead of `aria-selected`, because the table is not a `grid` widget and axe flags `aria-selected` on plain rows.
- **Forced colours:** the selected row gets `outline: 2px solid Highlight` and the bar uses `Highlight`, since background tints are dropped in that mode.

## Risks / Trade-offs

- [The tint could be mistaken for a state colour] → it is neutral (no hue of the state tokens) and the visual-refresh rule "only warn/error tint rows" still holds, because warn/error rows keep their own tint and the selected one adds only the bar and a neutral wash.
- [Another thread changes the same tab (standard OD without an EDS, device names)] → this change only touches row classes, one listener and CSS; rebase on whichever merges first.
