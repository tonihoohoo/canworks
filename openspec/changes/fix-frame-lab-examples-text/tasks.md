## 1. Fix

- [ ] 1.1 Make `el()` in `static/app.js` flatten its children to any depth (`children.flat(Infinity)`), matching `fxFill()`
- [ ] 1.2 Check the other `el()` callers for one that relied on one-level flattening (an array meant to show as text); fix any found

## 2. Tests

- [ ] 2.1 Browser test in `test_configurator_framelab_ux_page.py`: config workspace, Frame lab, Examples → Build → Examples and Examples → Arbitration → Examples; the Examples panel has chips and the Frame lab text has no `[object `
- [ ] 2.2 Same test in Commission a device with a node from the EDS library, plus leaving the Frame lab for the Nodes tab and coming back
- [ ] 2.3 Run the configurator page tests locally (Playwright) and the JS unit tests if any touch `el()`

## 3. Release

- [ ] 3.1 PC tools version 0.74.1 and a release note line ("The Frame lab's Examples tab no longer shows [object HTMLDivElement] after switching tabs")
