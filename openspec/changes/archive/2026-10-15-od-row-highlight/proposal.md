## Why

In a node's Object dictionary tab the name is on the left and the Read, Edit, ST and Note buttons and the Watch box are at the far right of a wide row. On a wide screen, and with sub-entries whose names and descriptions take two lines, it is hard to follow a row across to its buttons, so the user cannot be sure which entry Edit or Read will act on. Nothing on the row changes when it is clicked or when the pointer is over it. On a tab that can write to a live device, acting on the wrong entry is a real risk.

## What Changes

- **Selected row.** Clicking anywhere on an entry row (a VAR object, a sub-entry or a foldable object row) selects it. The selected row is shown with a tinted background and an accent bar on its left edge across the whole row, buttons and Watch box included. Only one row is selected at a time. Clicking a button or the Watch box in a row also selects that row, and the row being edited in place is always the selected one.
- **Hover.** With a mouse, the row under the pointer gets a light tint, so the eye can follow it to its buttons before clicking.
- **Keyboard.** When focus moves into a row (for example Tab to its Read button), that row becomes selected. Escape inside the tree clears the selection. The selected row is announced to assistive technology (`aria-current`).
- **Selection is kept** while values are read, the watch list refreshes, Read all runs, filters and search change and the user moves to another tab and back, per node, until the page is reloaded. A selected row hidden by a filter or a folded object shows highlighted again when it comes back.
- The highlight uses the existing theme tokens, meets the 3:1 contrast rule for non-text marks in Light and Dark, and stays visible in forced-colours (high contrast) mode.

Non-goals: what the buttons do is unchanged; no new toolbar for the selected entry. The standard CiA 301 dictionary without an EDS and device names are a separate change. The Parameters tab table is not changed here.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `canopen-configurator`: the object dictionary view gains a selected row and a hover tint.

## Impact

- `tools/deploy/canworks/configurator/static/app.js` (object dictionary tab rows, `odState`), `style.css` (row highlight rules).
- Page tests in `tools/deploy/tests/test_configurator_online.py`; the layout test's forced-colours and contrast checks.
- README.md (object dictionary tab description) and the PC tools version bump.
- CI: the tests run under the existing configurator `ui` path filter; no new shard or job.
