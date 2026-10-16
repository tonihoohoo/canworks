## Why

The Frame lab's **Examples** tab sometimes shows the text `[object HTMLDivElement]` (one per group, comma-separated) instead of the example frames. It happens whenever the Examples panel is drawn from examples that are already loaded: going to Build or Arbitration and back to Examples, and coming back to the Frame lab after the examples were fetched once. It shows in both the config workspace and Commission a device. The first visit looks fine because the panel says "Loading…" and the list is filled in later through a different path.

Cause: `fxLabExampleList()` (`tools/deploy/canworks/configurator/static/explain.js`) returns a list nested two deep (an optional warning line, then a list of group boxes). `fxLabPanel()` hands that list to `el()` (`static/app.js`), which flattens its children only one level, so the inner list of group boxes is turned into text with `String()`. `fxLabLoad()` uses `fxFill()`, which flattens fully, which is why the first visit works. The Frame lab's tab panels were added by the Frame lab usability change (#121), and this path was not covered by a test.

Reproduced with a browser test at main ce20648: open the Frame lab, wait for the examples, pick Build, pick Examples; the panel's text is `[object HTMLDivElement],[object HTMLDivElement]`. With `el()` flattening fully, the same test shows the groups.

## What Changes

- `el()` flattens nested child lists to any depth, like `fxFill()` already does, so a nested list of elements is never turned into text anywhere on the page. This fixes the Examples tab and guards every other caller that passes nested lists.
- A browser test: open the Frame lab (config workspace and Commission a device), switch Examples → Build → Examples and Examples → Arbitration → Examples, and leave the Frame lab and come back. Each time the Examples panel shows the example chips, and no text in the Frame lab contains `[object `.
- PC tools 0.74.1 (patch).

No file format, server protocol or CLI changes.

## Capabilities

### New Capabilities
None.

### Modified Capabilities
- `canopen-configurator`: the Frame lab layout requirement says the Examples tab shows its example frames every time it is shown, not only on the first visit.

## Impact

- `tools/deploy/canworks/configurator/static/app.js` (`el()`), maybe `explain.js` if a caller relied on one-level flattening (none found).
- `tools/deploy/tests/test_configurator_framelab_ux_page.py` (new test).
- `tools/deploy/pyproject.toml`, `tools/deploy/canworks/__init__.py`, the doc golden files (they carry the version).
- README: no user-visible feature or usage change, so no update.
