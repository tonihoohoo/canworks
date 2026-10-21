## 1. Server

- [x] 1.1 Save: remove the target's unused removable values from the written config, return `left_out`; draft reloads from the written file
- [x] 1.2 `/api/switch_target`: always remove, always repack; no preview needed by the page
- [x] 1.3 Drop `show_all_fields` from `UI_SETTINGS`

## 2. Page

- [x] 2.1 `switchTarget`: no dialog; one undo step; banner with what was done and Undo
- [x] 2.2 Remove the bar, the grouped problem, the Settings toggle, `S.showAll`/`shownFor`, the "· all fields" mark and their CSS; Problems leaves out removable unused items; save message names `left_out`
- [x] 2.3 Supervision: EMCY section only when the target uses EMCY settings; EDS without 0x1014 shows one line and no controls (leftover keeps warning and Remove)
- [x] 2.4 Heartbeat watch: hidden without a writable 0x1016 and no watch; block spans the grid, heading and hint on their own lines

## 3. Checks

- [x] 3.1 Server tests: save drops unused values and counts them; switch removes without `keep`; UI defaults
- [x] 3.2 Page tests: CODESYS leftovers hidden with nothing listed, save leaves them out and says how many, no unsaved mark on open; switch has no dialog and Undo restores; EMCY not on CODESYS; no-0x1014 node shows one line; no-0x1016 node has no watch block; watch heading on its own line
- [x] 3.3 Target sweep: drop the toggle pass; keep the field, wording and blank-tab checks
- [x] 3.4 README and docs/configurator.md; PC tools minor version bump

## 4. Hand check (Windows)

- [x] 4.1 The photo's CODESYS config: Supervision tab has Method and no EMCY section or glued text; save says how many settings were left out; switching to OpenPLC and back asks nothing
  - 2026-10-21 PASSED on Windows, tools 0.96.0 from the tag, Edge: a CODESYS copy of the example and a copy of a real CODESYS project config. Open: no unsaved mark, no problems, no bar or toggle. Supervision: Method shown, no EMCY section, watch heading and hint on their own lines, no glued text. Save after one edit: "(27 settings CODESYS does not use left out)", values gone from the file. Switch to OpenPLC ("12 PDO entries got a location") and back ("13 settings CODESYS does not use removed"): no dialog, Undo works.
