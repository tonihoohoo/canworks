## 1. Fix

- [x] 1.1 Make `el()` in `static/app.js` flatten its children to any depth (`children.flat(Infinity)`), matching `fxFill()`
- [x] 1.2 Check the other `el()` callers for one that relied on one-level flattening (an array meant to show as text); fix any found (none: a list nested two deep was always shown as comma-joined "[object …]" text, so no caller relied on it)

## 2. Tests

- [x] 2.1 Browser test in `test_configurator_framelab_ux_page.py`: config workspace, Frame lab, Examples → Build → Examples and Examples → Arbitration → Examples; the Examples panel has chips and the Frame lab text has no `[object `
- [x] 2.2 Same test in Commission a device with a node from the EDS library, plus leaving the Frame lab for the Nodes tab and coming back
- [x] 2.3 Run the configurator page tests locally (Playwright): 364 passed, 2 skipped

## 3. Release

- [x] 3.1 PC tools version 0.74.1 (pyproject, `canworks/__init__.py`, doc golden files); the release notes are a per-release template with no per-change lines, so nothing to add there
