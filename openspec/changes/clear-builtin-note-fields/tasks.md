## 1. Notes merge and file

- [x] 1.1 Schema (deploy tool copy and `schema/`): each note field also allows `null`
- [x] 1.2 `notes.py`: device layer keeps `null`; merge drops fields the device layer sets to `null` (object key clears inherited fields; sub-object own value wins); `filled()` counts `null`; `apply_changes` and `update` keep `null`
- [x] 1.3 `plan_import`: import `null` when the target note has the field, else count it as the same; merged export writes no `null`
- [x] 1.4 `check`: finding for a `null` field that clears nothing
- [x] 1.5 Tests: clear on a VAR, on an object key with sub 0 and a sub-object with its own unit, import of `null` (changed / same), merged export round trip, check finding, docs and DBC export use the merged note

## 2. Note editor

- [x] 2.1 `editNote`: emptying a field that shows a built-in or inherited value saves `null`; an emptied field shows the built-in value greyed as "hidden" with **Use built-in**, which removes the `null`
- [x] 2.2 Page layering in app.js (`noteLayer`, `noteFor`) applies `null` like `notes.note`; Notes tab lists a `null`-only entry under My notes as Built-in, changed
- [x] 2.3 Configurator page tests: clear the unit of 0x6071:0, Use built-in brings it back, undo

## 3. Skill and docs

- [x] 3.1 SKILL.md: write `null` for a built-in field that does not fit (inherited unit on sub 0, unsupported value list), replacing the "cannot remove" workaround
- [x] 3.2 `docs/configurator.md` Device notes and the Note editor text; README; PC tools version bump

## 4. CI time

- [ ] 4.1 Compare the PR's CI wall and summed job time with the baseline (median of the last 5 green `main` runs) and state both in the PR
