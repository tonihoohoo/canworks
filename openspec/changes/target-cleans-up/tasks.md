## 1. Server

- [ ] 1.1 Save: remove the target's unused removable values from the written config, return `left_out`; draft reloads from the written file
- [ ] 1.2 `/api/switch_target`: always remove, always repack; no preview needed by the page
- [ ] 1.3 Drop `show_all_fields` from `UI_SETTINGS`

## 2. Page

- [ ] 2.1 `switchTarget`: no dialog; one undo step; banner with what was done and Undo
- [ ] 2.2 Remove the bar, the grouped problem, the Settings toggle, `S.showAll`/`shownFor`, the "· all fields" mark and their CSS; Problems leaves out removable unused items; save message names `left_out`
- [ ] 2.3 Supervision: EMCY section only when the target uses EMCY settings; EDS without 0x1014 shows one line and no controls (leftover keeps warning and Remove)
- [ ] 2.4 Heartbeat watch: hidden without a writable 0x1016 and no watch; block spans the grid, heading and hint on their own lines

## 3. Checks

- [ ] 3.1 Server tests: save drops unused values and counts them; switch removes without `keep`; UI defaults
- [ ] 3.2 Page tests: CODESYS leftovers hidden with nothing listed, save leaves them out and says how many, no unsaved mark on open; switch has no dialog and Undo restores; EMCY not on CODESYS; no-0x1014 node shows one line; no-0x1016 node has no watch block; watch heading on its own line
- [ ] 3.3 Target sweep: drop the toggle pass; keep the field, wording and blank-tab checks
- [ ] 3.4 README and docs/configurator.md; PC tools minor version bump

## 4. Hand check (Windows)

- [ ] 4.1 The photo's CODESYS config: Supervision tab has Method and no EMCY section or glued text; save says how many settings were left out; switching to OpenPLC and back asks nothing
