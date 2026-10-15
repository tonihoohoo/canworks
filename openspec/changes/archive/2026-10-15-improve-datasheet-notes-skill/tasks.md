## 1. Skeleton for all objects

- [x] 1.1 `notes.py`: `skeleton(..., all_objects=False)` adds every object and sub-object with `x-default`, `x-low`, `x-high`, `x-pdo` when set (EDS text as written)
- [x] 1.2 `cli.py`: `notes skeleton --all`
- [x] 1.3 Tests: standard objects present, values as written, missing default and limits left out, default output unchanged
- [x] 1.4 `--all` adds an entry with the name for each ARRAY/RECORD object; `--index LOW-HIGH`; UNSIGNED/INTEGER 24-56 type names; stderr line for identity fields the EDS lacks
- [x] 1.5 `builtin`: stderr line with the sets used, naming a profile without built-in notes
- [x] 1.6 EDS read errors name the line (syntax) or section (lists, missing keys)
- [x] 1.7 `check`: finding for `values`/`bits` on an ARRAY/RECORD object key (configurator Problems pane shows it too)
- [x] 1.8 Tests for 1.4-1.7

## 2. Skill

- [x] 2.1 SKILL.md: step 1 uses `notes skeleton --all` for the comparison; difference kinds (names, PDO mapping, empty EDS default, `RW/S`); one table with default answers and how the user changes rows; Follow EDS definition; complete `bits`/`values` on standard objects; page references; contradictions inside the datasheet; unit and scale on sub-objects when sub 0 or packed subs would inherit them; table-only rows; hand-off warns the import may change the user's own notes; report adds other EDS problems; paths not tied to a checkout; stop on an EDS that does not load; profiles without built-in notes; document prefix in `manual`; index rules and family manuals; values as the EDS reads them; spreadsheets; built-in notes checked against the datasheet (own text/unit/values, unsupported lists said in text and details); manuals for several buses; stored, takes-effect and needed objects in details
- [x] 2.2 Skill test: names `--all` and `--index`
- [x] 2.3 Repeat the trial by hand on the three trial pairs (project research folder, not in the repo or CI): the table replaces per-difference questions, no built-in bit names lost, `notes check` clean, import preview clean; note the outcome in the PR
- [x] 2.4 Repeat on at least 4 of the 11 second-trial pairs (PC trial folder, not in the repo or CI), including the two EDS that do not load, the XLSX and the HTML pair; note the outcome in the PR

## 3. Docs

- [x] 3.1 `docs/configurator.md` Notes from a datasheet: the difference table
- [x] 3.2 `docs/deploy.md` Device notes: `--all`, `--index`, the `builtin` sets line
- [x] 3.3 Bump the PC tools version

## 4. CI time

- [x] 4.1 Compare the PR's CI wall and summed job time with the baseline (median of the last 5 green `main` runs) and state both in the PR
