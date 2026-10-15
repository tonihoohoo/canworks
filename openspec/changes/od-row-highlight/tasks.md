## 1. Selection

- [x] 1.1 `odState`: add `selected`; helper that sets it, moves `.od-selected` and `aria-current="true"` to the matching row and clears the old one
- [x] 1.2 Delegated `pointerdown` and `focusin` listeners on each group table select the row they land in (entry rows and object rows); Escape inside the tree clears the selection
- [x] 1.3 Apply the stored selection on every render of the tab, so watch rounds, Read all, search, filters, folding and tab switches keep it; starting an in-place edit selects its row

## 2. Style

- [x] 2.1 `style.css`: `--sel-bg` token for Light, Dark and Auto; `.od-selected` tint on every cell plus a 3 px `--accent` bar on the first cell; hover tint under `@media (hover: hover)`
- [x] 2.2 Forced-colours rule (`Highlight` outline and bar); add the selected row to the contrast token test (bar 3:1 against `--bg` and `--panel`)

## 3. Tests

- [x] 3.1 Page test: click a sub-entry's name, its row is selected; click Read on another row, that row is selected and the first is not; Escape clears
- [x] 3.2 Page test: selection survives a watch round, Read all, a search that hides and then shows the row, and switching to Parameters and back
- [x] 3.3 Keyboard test: Tab into a row's Read button selects the row and axe passes with `aria-current`; layout check in Light, Dark and forced colours

## 4. Docs and release

- [x] 4.1 README.md: one line on the selected row in the object dictionary tab description
- [x] 4.2 Bump the PC tools version (0.62.0, with the doc golden files)
- [ ] 4.3 CI time: wall and summed job time against the main baseline in the PR description
